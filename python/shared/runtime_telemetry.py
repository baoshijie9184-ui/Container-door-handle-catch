"""Opt-in, payload-free telemetry for the ECS Python runtimes.

Importing this module performs no I/O and starts no threads.  The application
owns ``from_env``/``close``.  Observability never retries a business operation.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import json
import logging
import math
import os
from pathlib import Path
import queue
import re
import threading
import time
from typing import Any, Mapping
from urllib.parse import urlsplit


OPERATIONS = frozenset({
    "runtime.operation", "worker.consume", "worker.infer", "worker.publish",
    "mem0.add", "mem0.search", "mem0.update", "mem0.delete", "mem0.history",
    "embedding.request", "vector.query", "vector.upsert", "vector.delete",
})
OUTCOMES = frozenset({"success", "error", "pending", "replayed", "partial", "cancelled"})
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_MODEL_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z")
_TRACEPARENT = re.compile(r"00-([0-9a-f]{32})-([0-9a-f]{16})-(00|01)\Z")
_ID_KEYS = frozenset({"task.id", "dispatch.id", "event.id", "run.id", "parent.run.id",
                      "model.id", "model.version", "model.config.version", "sop.version",
                      "gen_ai.request.model", "gen_ai.response.model", "embedding.model",
                      "vector.index.version", "tool.name", "error.type"})
_PRIVATE_IDS = frozenset({"owner.id", "session.id", "user.id"})
_MODEL_KEYS = frozenset({"gen_ai.request.model", "gen_ai.response.model", "embedding.model"})
_INT_KEYS = frozenset({"image.count", "image.success_count", "image.failure_count",
                       "result.count", "embedding.dimension", "gen_ai.usage.input_tokens",
                       "gen_ai.usage.output_tokens"})
_ENUMS = {"outcome": OUTCOMES, "gen_ai.operation.name": frozenset({"chat", "embeddings"}),
          "gen_ai.provider.name": frozenset({"siliconflow", "dashscope", "openai", "other"})}
_FAILURES = frozenset({"config_invalid", "dependency_unavailable", "export_failed",
                       "queue_full", "closed", "span_failed", "metrics_failed", "event_queue_full",
                       "shutdown_timeout", "export_sanitization_failed"})


def _operation(value: str) -> str:
    return value if isinstance(value, str) and value in OPERATIONS else "runtime.operation"


def safe_attributes(values: Mapping[str, Any] | None, identity_key: bytes = b"") -> dict:
    """An allowlist, not a best-effort scrub of arbitrary payloads.

    Owner/session/user identifiers never leave the process verbatim. A shared
    private HMAC key permits correlation; without it those fields are omitted.
    """
    result = {}
    for key, value in (values or {}).items():
        if not isinstance(key, str):
            continue
        if key in _PRIVATE_IDS:
            if identity_key and isinstance(value, (str, int)) and len(str(value)) <= 1024:
                digest = hmac.new(identity_key, (key + ":" + str(value)).encode(), hashlib.sha256).hexdigest()
                result[key + ".pseudonym"] = digest
        elif key.endswith(".pseudonym") and key[:-10] in _PRIVATE_IDS:
            if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
                result[key] = value
        elif key in _ID_KEYS:
            pattern = _MODEL_IDENTIFIER if key in _MODEL_KEYS else _IDENTIFIER
            if isinstance(value, (str, int)) and pattern.fullmatch(str(value)) and "//" not in str(value):
                result[key] = str(value)
        elif key in _INT_KEYS:
            if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10**12:
                result[key] = value
        elif key in _ENUMS and isinstance(value, str) and value in _ENUMS[key]:
            result[key] = value
        elif key == "source.trace_id" and isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value):
            result[key] = value
    return result


def validated_traceparent(headers: Any) -> tuple[int, int, int] | None:
    """Accept one strict W3C v00 header; never accept baggage or tracestate.

    Duplicate traceparents are ambiguous and rejected. Header byte counts and
    iteration are bounded so arbitrary incoming Kafka headers are not retained.
    """
    try:
        items = headers.items() if isinstance(headers, Mapping) else (headers or ())
        found = []
        for index, item in enumerate(items):
            if index >= 32:
                return None
            key, value = item
            if isinstance(key, bytes):
                key = key.decode("ascii")
            if not isinstance(key, str) or key.lower() != "traceparent":
                continue
            if isinstance(value, bytes):
                value = value.decode("ascii")
            if not isinstance(value, str) or len(value) != 55:
                return None
            match = _TRACEPARENT.fullmatch(value)
            if not match:
                return None
            trace_id, span_id, flags = (int(part, 16) for part in match.groups())
            if not trace_id or not span_id:
                return None
            found.append((trace_id, span_id, flags))
        return found[0] if len(found) == 1 else None
    except (TypeError, ValueError, UnicodeError):
        return None


def _secret_file(name: str, *, minimum: int = 1) -> bytes:
    path = os.environ.get(name, "")
    if not path:
        raise ValueError("missing private file")
    # Bound reads; an accidentally selected data file is not loaded into memory.
    with Path(path).open("rb") as stream:
        value = stream.read(4097).strip()
    if not minimum <= len(value) <= 4096 or b"\n" in value or b"\r" in value:
        raise ValueError("invalid private file")
    return value


def _boolean(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, str(default)).lower()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError("invalid switch")
    return value in {"true", "1"}


def _number(name: str, default: float, low: float, high: float, integral=False):
    value = float(os.environ.get(name, default))
    if not math.isfinite(value) or not low <= value <= high or (integral and not value.is_integer()):
        raise ValueError("invalid bound")
    return int(value) if integral else value


class _Metrics:
    def __init__(self):
        self.registry = None
        self.failures = self.operations = self.duration = self.enabled = self.pending = self.ready = None

    def configure(self):
        from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
        self.registry = CollectorRegistry(auto_describe=True)
        self.failures = Counter("doorhandle_telemetry_failures_total", "Bounded telemetry failures",
                                ["reason"], registry=self.registry)
        self.operations = Counter("doorhandle_runtime_operations_total", "Runtime operations",
                                  ["operation", "outcome"], registry=self.registry)
        self.duration = Histogram("doorhandle_runtime_operation_seconds", "Runtime operation duration",
                                  ["operation"], registry=self.registry,
                                  buckets=(.01, .05, .1, .5, 1, 5, 15, 60, 300))
        self.enabled = Gauge("doorhandle_telemetry_tracing_enabled", "Trace exporter configured",
                             registry=self.registry)
        self.pending = Gauge("doorhandle_telemetry_pending_spans", "Queued plus in-flight sampled spans",
                             registry=self.registry)
        self.ready = Gauge("doorhandle_runtime_ready", "Business runtime readiness (not exporter health)",
                           registry=self.registry)

    def failure(self, reason):
        if self.failures is not None:
            self.failures.labels(reason if reason in _FAILURES else "span_failed").inc()

    def operation(self, operation, outcome, elapsed):
        if self.operations is not None:
            self.operations.labels(operation, outcome).inc()
            self.duration.labels(operation).observe(elapsed)


class _SafeSdkLog(logging.Filter):
    """SDK/network diagnostics must not print endpoint, response or exception."""
    def filter(self, record):
        record.msg, record.args = "telemetry_sdk_failure", ()
        record.exc_info = record.exc_text = record.stack_info = None
        return True


class _Admission:
    """Public SpanProcessor adapter around the mature SDK BatchSpanProcessor.

    Admission bounds queued *and in-flight* spans, so the SDK's equally sized
    queue cannot silently evict a span. No private SDK queue inspection is used.
    """
    def __init__(self, limit, metrics, sanitizer):
        self.slots = threading.BoundedSemaphore(limit)
        self.metrics, self.sanitizer = metrics, sanitizer
        self.delegate = None
        self.closed = False
        self.lock = threading.Lock()

    def on_start(self, span, parent_context=None):
        pass

    def _on_ending(self, span):
        pass

    def on_end(self, span):
        try:
            if not span.context or not span.context.trace_flags.sampled:
                return
            with self.lock:
                if self.closed:
                    self.metrics.failure("closed")
                    return
                if not self.slots.acquire(blocking=False):
                    self.metrics.failure("queue_full")
                    return
                if self.metrics.pending is not None:
                    self.metrics.pending.inc()
                try:
                    self.delegate.on_end(self.sanitizer(span))
                except Exception:
                    self.release(1)
                    self.metrics.failure("export_sanitization_failed")
        except Exception:
            self.metrics.failure("span_failed")

    def release(self, count):
        for _ in range(count):
            self.slots.release()
            if self.metrics.pending is not None:
                self.metrics.pending.dec()

    def stop_admission(self):
        with self.lock:
            self.closed = True

    def shutdown(self):
        self.stop_admission()
        self.delegate.shutdown()

    def force_flush(self, timeout_millis=30000):
        return self.delegate.force_flush(timeout_millis)


class _AccountingExporter:
    def __init__(self, exporter, admission, metrics):
        self.exporter, self.admission, self.metrics = exporter, admission, metrics

    def export(self, spans):
        from opentelemetry.sdk.trace.export import SpanExportResult
        try:
            result = self.exporter.export(spans)
            if result != SpanExportResult.SUCCESS:
                self.metrics.failure("export_failed")
            return result
        except Exception:
            self.metrics.failure("export_failed")
            return SpanExportResult.FAILURE
        finally:
            self.admission.release(len(spans))

    def shutdown(self):
        try:
            self.exporter.shutdown()
        except Exception:
            self.metrics.failure("export_failed")

    def force_flush(self, timeout_millis=30000):
        return True


class RuntimeSpan:
    def __init__(self, runtime, native=None):
        self.runtime, self.native = runtime, native
        self.outcome = "success"

    def set_attributes(self, attributes):
        try:
            if self.native is not None:
                self.native.set_attributes(safe_attributes(attributes, self.runtime.identity_key))
        except Exception:
            self.runtime.metrics.failure("span_failed")

    def set_outcome(self, outcome):
        self.outcome = outcome if isinstance(outcome, str) and outcome in OUTCOMES else "error"
        self.set_attributes({"outcome": self.outcome})


class RuntimeTelemetry:
    """Small lifecycle-owned API; telemetry failures never change task results."""
    def __init__(self, service_name):
        self.service_name = (service_name if isinstance(service_name, str) and _IDENTIFIER.fullmatch(service_name)
                             else "doorhandle-runtime")
        self.metrics = _Metrics()
        self.identity_key = b""
        self.tracer = self.provider = self.processor = None
        self.server = self.server_thread = self.event_thread = None
        self.event_queue = None
        self.event_logger = None
        self.events_stopped = threading.Event()
        self.closed = False
        self.bootstrap_failure = None
        self._log_filters = []

    @classmethod
    def from_env(cls, service_name, default_metrics_port=9464):
        runtime = cls(service_name)
        # Explicit invalid configuration is observable but fail-open. Enabling
        # telemetry never makes previously working detection/Mem0 unavailable.
        try:
            traces = _boolean("OTEL_ENABLED")
            metrics = _boolean("TELEMETRY_METRICS_ENABLED")
            events = _boolean("TELEMETRY_EVENTS_ENABLED", traces or metrics)
            if not (traces or metrics or events):
                return runtime
            runtime.metrics.configure()
            if os.environ.get("TELEMETRY_ID_HMAC_KEY_FILE"):
                runtime.identity_key = _secret_file("TELEMETRY_ID_HMAC_KEY_FILE", minimum=32)
            for enabled, configure in ((traces, runtime._configure_traces),
                                       (metrics, lambda: runtime._configure_metrics(default_metrics_port))):
                if enabled:
                    try:
                        configure()
                    except ImportError:
                        runtime.bootstrap_failure = "dependency_unavailable"
                        runtime.metrics.failure(runtime.bootstrap_failure)
                    except Exception:
                        runtime.bootstrap_failure = "config_invalid"
                        runtime.metrics.failure(runtime.bootstrap_failure)
            if events:
                runtime.event_queue = queue.Queue(maxsize=128)
                # An owned JSON-only sink works even when the worker's root
                # logger remains at WARNING; no application logging mutation.
                runtime.event_logger = logging.Logger("doorhandle.runtime.events", logging.INFO)
                runtime.event_logger.addHandler(logging.StreamHandler())
                runtime.event_thread = threading.Thread(target=runtime._drain_events,
                                                        name="runtime-telemetry-events", daemon=True)
                runtime.event_thread.start()
        except ImportError:
            runtime.bootstrap_failure = "dependency_unavailable"
            runtime.metrics.failure(runtime.bootstrap_failure)
        except Exception:
            runtime.bootstrap_failure = "config_invalid"
            runtime.metrics.failure(runtime.bootstrap_failure)
        return runtime

    def _configure_traces(self):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import ReadableSpan, SpanLimits, TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
        from opentelemetry.trace import Status
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "")
        parsed = urlsplit(endpoint)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path != "/api/public/otel/v1/traces"):
            raise ValueError("invalid OTLP endpoint")
        public = _secret_file("LANGFUSE_PUBLIC_KEY_FILE").decode("ascii")
        secret = _secret_file("LANGFUSE_SECRET_KEY_FILE").decode("ascii")
        capacity = _number("TELEMETRY_MAX_PENDING_SPANS", 256, 8, 4096, True)
        batch = _number("TELEMETRY_BATCH_SIZE", 32, 1, capacity, True)
        timeout = _number("TELEMETRY_EXPORT_TIMEOUT_SECONDS", 2, .1, 5)
        delay = _number("TELEMETRY_BATCH_DELAY_MS", 500, 100, 10000, True)
        ratio = _number("TELEMETRY_TRACE_SAMPLE_RATIO", 1, 0, 1)
        resource = Resource({"service.name": self.service_name})
        # Resource.create and global providers are intentionally avoided: neither
        # arbitrary OTEL_RESOURCE_ATTRIBUTES nor third-party spans join this pipe.
        def sanitize(span):
            return ReadableSpan(name=_operation(span.name), context=span.context, parent=span.parent,
                                resource=resource, attributes=safe_attributes(span.attributes, self.identity_key),
                                events=(), links=(), kind=span.kind, status=Status(span.status.status_code),
                                start_time=span.start_time, end_time=span.end_time,
                                instrumentation_scope=None)
        self.processor = _Admission(capacity, self.metrics, sanitize)
        # Replace SDK exporter diagnostics at their source, not a raw exception
        # logger in the application. Filters are removed on owned shutdown.
        for name in ("opentelemetry.exporter.otlp.proto.http.trace_exporter",
                     "opentelemetry.exporter.otlp.common.http",
                     "opentelemetry.exporter.http.transport._requests",
                     "opentelemetry.sdk._shared_internal", "opentelemetry.sdk.trace.export"):
            logger, filter_ = logging.getLogger(name), _SafeSdkLog()
            logger.addFilter(filter_)
            self._log_filters.append((logger, filter_))
        exporter = OTLPSpanExporter(endpoint=endpoint, timeout=timeout,
                                    headers={"Authorization": "Basic " + base64.b64encode(
                                        (public + ":" + secret).encode()).decode("ascii"),
                                        "x-langfuse-ingestion-version": "4"})
        self.processor.delegate = BatchSpanProcessor(
            _AccountingExporter(exporter, self.processor, self.metrics), max_queue_size=capacity,
            max_export_batch_size=batch, schedule_delay_millis=delay,
            export_timeout_millis=int(timeout * 1000))
        self.provider = TracerProvider(resource=resource, sampler=ParentBased(TraceIdRatioBased(ratio)),
                                       shutdown_on_exit=False,
                                       span_limits=SpanLimits(max_attributes=32, max_events=0, max_links=0,
                                                              max_attribute_length=128))
        self.provider.add_span_processor(self.processor)
        self.tracer = self.provider.get_tracer("doorhandle.runtime", "1")
        self.metrics.enabled.set(1)

    def _configure_metrics(self, default_port):
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
        host = os.environ.get("TELEMETRY_METRICS_HOST", "127.0.0.1")
        # Only literal IPv4 private/loopback bindings; no hostname resolution,
        # public IPs or implicit public endpoint.
        address = ipaddress.ip_address(host)
        if address.version != 4 or not (address.is_private or address.is_loopback or address.is_unspecified):
            raise ValueError("metrics bind must be private")
        token = _secret_file("TELEMETRY_METRICS_TOKEN_FILE", minimum=24)
        token.decode("ascii")
        port = _number("TELEMETRY_METRICS_PORT", default_port, 1024, 65535, True)
        registry = self.metrics.registry
        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(1)

            def do_GET(self):
                values = self.headers.get_all("Authorization", [])
                supplied = values[0].encode("utf-8") if len(values) == 1 else b""
                expected = b"Bearer " + token
                if not hmac.compare_digest(supplied, expected):
                    self.send_error(401)
                    return
                if self.path != "/metrics":
                    self.send_error(404)
                    return
                payload = generate_latest(registry)
                self.send_response(200)
                self.send_header("Content-Type", CONTENT_TYPE_LATEST)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                pass
        metrics = self.metrics
        class PrivateMetricsServer(HTTPServer):
            def handle_error(self, request, client_address):
                # socketserver's default prints raw exceptions and tracebacks.
                metrics.failure("metrics_failed")
        self.server = PrivateMetricsServer((host, port), Handler)
        self.server_thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.2),
                                               name="runtime-telemetry-metrics", daemon=True)
        self.server_thread.start()

    @contextmanager
    def span(self, name, attributes=None, headers=None, trusted_parent=False):
        operation = _operation(name)
        handle = RuntimeSpan(self)
        started = time.monotonic()
        token = None
        try:
            if self.tracer is not None and not self.closed:
                from opentelemetry import context, trace
                parent = validated_traceparent(headers)
                safe = safe_attributes(attributes, self.identity_key)
                selected_context = None
                if headers is not None:
                    # Asynchronous/untrusted messages begin their own trace.
                    selected_context = context.Context()
                if parent:
                    safe["source.trace_id"] = f"{parent[0]:032x}"
                    if trusted_parent:
                        remote = trace.SpanContext(parent[0], parent[1], True, trace.TraceFlags(parent[2]))
                        selected_context = trace.set_span_in_context(trace.NonRecordingSpan(remote), context.Context())
                handle.native = self.tracer.start_span(operation, context=selected_context, attributes=safe)
                token = context.attach(trace.set_span_in_context(handle.native))
        except Exception:
            self.metrics.failure("span_failed")
        try:
            yield handle
        except BaseException as error:
            # Preserve the exact original business exception and traceback.
            handle.set_outcome("pending" if type(error).__name__ == "ReceiptPending" else "error")
            handle.set_attributes({"error.type": type(error).__name__})
            raise
        finally:
            try:
                if handle.native is not None:
                    from opentelemetry import trace
                    if handle.outcome == "error":
                        handle.native.set_status(trace.StatusCode.ERROR)
                    handle.native.set_attribute("outcome", handle.outcome)
                    handle.native.end()
                self.metrics.operation(operation, handle.outcome, time.monotonic() - started)
                self.event(operation, handle.outcome, handle.native)
            except Exception:
                self.metrics.failure("span_failed")
            finally:
                if token is not None:
                    try:
                        from opentelemetry import context
                        context.detach(token)
                    except Exception:
                        self.metrics.failure("span_failed")

    def inject_headers(self):
        try:
            if self.tracer is None or self.closed:
                return []
            from opentelemetry import trace
            current = trace.get_current_span().get_span_context()
            if current.is_valid:
                return [("traceparent", f"00-{current.trace_id:032x}-{current.span_id:016x}-{int(current.trace_flags) & 1:02x}")]
        except Exception:
            self.metrics.failure("span_failed")
        return []

    def set_ready(self, ready):
        try:
            if self.metrics.ready is not None:
                self.metrics.ready.set(1 if ready else 0)
        except Exception:
            self.metrics.failure("metrics_failed")

    def event(self, operation, outcome, native=None):
        if self.event_queue is None or self.closed:
            return
        event = {"event": "runtime.operation", "service": self.service_name,
                 "operation": _operation(operation),
                 "outcome": outcome if isinstance(outcome, str) and outcome in OUTCOMES else "error"}
        try:
            if native is not None:
                context = native.get_span_context()
                event.update(traceId=f"{context.trace_id:032x}", spanId=f"{context.span_id:016x}")
            self.event_queue.put_nowait(event)
        except queue.Full:
            self.metrics.failure("event_queue_full")
        except Exception:
            self.metrics.failure("span_failed")

    def _drain_events(self):
        while not self.events_stopped.is_set() or not self.event_queue.empty():
            try:
                event = self.event_queue.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                self.event_logger.info(json.dumps(event, separators=(",", ":")))
            except Exception:
                pass
        for handler in self.event_logger.handlers:
            handler.close()

    def close(self, timeout_seconds=3):
        if self.closed:
            return
        self.closed = True
        if self.provider is None and self.server is None and self.event_thread is None and not self._log_filters:
            return
        try:
            requested = float(timeout_seconds)
            budget = min(5.0, max(.1, requested)) if math.isfinite(requested) else 3.0
        except (ValueError, TypeError):
            budget = 3.0
        deadline = time.monotonic() + budget
        if self.processor is not None:
            self.processor.stop_admission()
        self.events_stopped.set()
        def shutdown():
            try:
                if self.server is not None:
                    self.server.shutdown()
                    self.server.server_close()
                if self.provider is not None:
                    self.provider.shutdown()
            except Exception:
                self.metrics.failure("span_failed")
            finally:
                for logger, filter_ in self._log_filters:
                    logger.removeFilter(filter_)
        # SDK shutdown waits for in-flight HTTP; never wait indefinitely on the
        # business shutdown path. Worker/export/HTTP threads are daemon-owned.
        closer = threading.Thread(target=shutdown, name="runtime-telemetry-close", daemon=True)
        closer.start()
        for thread in (closer, self.server_thread, self.event_thread):
            if thread is not None:
                thread.join(max(0, deadline - time.monotonic()))
        if closer.is_alive():
            self.metrics.failure("shutdown_timeout")
