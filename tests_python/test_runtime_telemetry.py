"""Payload-free telemetry contracts. Execute only in the ECS verification job."""
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, HTTPServer
import base64
import json
import logging
import queue
import socket
import threading
import time
from types import SimpleNamespace

import pytest

from runtime_telemetry import (
    RuntimeTelemetry, _AccountingExporter, _Admission, _Metrics, _SafeSdkLog,
    safe_attributes, validated_traceparent,
)


@pytest.fixture(autouse=True)
def explicit_configuration(monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith(("OTEL_", "TELEMETRY_", "LANGFUSE_")):
            monkeypatch.delenv(key, raising=False)


def _secret(tmp_path, monkeypatch, name, value):
    file = tmp_path / name
    file.write_text(value, encoding="utf-8")
    monkeypatch.setenv(name, str(file))


def _trace_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv("TELEMETRY_EVENTS_ENABLED", "false")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://langfuse-web:3000/api/public/otel/v1/traces")
    _secret(tmp_path, monkeypatch, "LANGFUSE_PUBLIC_KEY_FILE", "pk-test-only")
    _secret(tmp_path, monkeypatch, "LANGFUSE_SECRET_KEY_FILE", "sk-test-private-only")


class CapturingExporter:
    def __init__(self, **options):
        self.options = options
        self.spans = []
        self.shutdown_called = False

    def export(self, spans):
        from opentelemetry.sdk.trace.export import SpanExportResult
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self):
        self.shutdown_called = True


def _runtime_with_exporter(tmp_path, monkeypatch, exporter):
    from opentelemetry.exporter.otlp.proto.http import trace_exporter
    _trace_configuration(tmp_path, monkeypatch)
    monkeypatch.setattr(trace_exporter, "OTLPSpanExporter", lambda **kwargs: exporter)
    runtime = RuntimeTelemetry.from_env("doorhandle-fixture")
    assert runtime.bootstrap_failure is None
    return runtime


def _metrics_text(metrics):
    from prometheus_client import generate_latest
    return generate_latest(metrics.registry).decode()


def test_unconfigured_runtime_is_noop_without_starting_threads(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Unconfigured runtime must not import/configure network SDKs or start threads")
    monkeypatch.setattr(_Metrics, "configure", forbidden)
    monkeypatch.setattr(threading.Thread, "start", forbidden)
    telemetry = RuntimeTelemetry.from_env("doorhandle-fixture")
    with telemetry.span("worker.consume", {"task.id": "task-1"}):
        assert telemetry.inject_headers() == []
    telemetry.close()


def test_allowlist_excludes_payloads_urls_and_identity_without_hmac():
    values = {"task.id": "task-1", "dispatch.id": "dispatch-1", "event.id": "event-1",
              "run.id": "run-1", "session.id": "person@example.com", "owner.id": "12345",
              "prompt": "private prompt", "gen_ai.input.messages": "private messages",
              "tool.arguments": "private tool args", "url": "https://private?Signature=secret",
              "error.message": "private db password", "exception.stacktrace": "secret stack",
              "model.id": "12", "image.count": 2, "outcome": ["not-a-string"]}
    assert safe_attributes(values) == {"task.id": "task-1", "dispatch.id": "dispatch-1",
                                       "event.id": "event-1", "run.id": "run-1",
                                       "model.id": "12", "image.count": 2}


def test_identity_hmac_is_stable_scoped_and_never_verbatim():
    value = {"owner.id": "private-owner", "session.id": "private-owner"}
    output = safe_attributes(value, b"a" * 32)
    assert set(output) == {"owner.id.pseudonym", "session.id.pseudonym"}
    assert output["owner.id.pseudonym"] != output["session.id.pseudonym"]
    assert output == safe_attributes(value, b"a" * 32)
    assert "private-owner" not in json.dumps(output)
    assert safe_attributes(output) == output  # export-boundary second pass


def test_model_identifiers_allow_vendor_namespace_but_not_urls():
    assert safe_attributes({"embedding.model": "BAAI/bge-m3"}) == {"embedding.model": "BAAI/bge-m3"}
    assert safe_attributes({"embedding.model": "https://private/key", "task.id": "private/key"}) == {}


@pytest.mark.parametrize("headers", [
    [("traceparent", "00-" + "0" * 32 + "-" + "1" * 16 + "-01")],
    [("traceparent", "00-" + "1" * 32 + "-" + "0" * 16 + "-01")],
    [("traceparent", "00-" + "a" * 32 + "-" + "b" * 16 + "-ff")],
    [("traceparent", "ff-" + "a" * 32 + "-" + "b" * 16 + "-01")],
    [("traceparent", "00-" + "A" * 32 + "-" + "b" * 16 + "-01")],
    [("traceparent", b"\xff" * 55)],
    [("traceparent", "00-" + "a" * 32 + "-" + "b" * 16 + "-01")] * 2,
    [("ignored", "x")] * 33,
    [None],
])
def test_untrusted_trace_headers_are_bounded_and_rejected(headers):
    assert validated_traceparent(headers) is None


def test_remote_context_is_new_trace_by_default_and_explicit_trust_only(tmp_path, monkeypatch):
    exporter = CapturingExporter()
    telemetry = _runtime_with_exporter(tmp_path, monkeypatch, exporter)
    incoming = [("traceparent", b"00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"),
                ("baggage", b"password=private"), ("tracestate", b"private-state")]
    try:
        with telemetry.span("worker.consume", {"task.id": "task-1"}, headers=incoming):
            outgoing = telemetry.inject_headers()
            assert len(outgoing) == 1 and outgoing[0][0] == "traceparent"
            assert "a" * 32 not in outgoing[0][1]
            with telemetry.span("worker.infer"):
                pass
        with telemetry.span("mem0.search", headers=incoming, trusted_parent=True):
            assert "a" * 32 in telemetry.inject_headers()[0][1]
        assert telemetry.provider.force_flush(timeout_millis=1000)
        consume = next(span for span in exporter.spans if span.name == "worker.consume")
        infer = next(span for span in exporter.spans if span.name == "worker.infer")
        trusted = next(span for span in exporter.spans if span.name == "mem0.search")
        assert consume.parent is None
        assert consume.attributes["source.trace_id"] == "a" * 32
        assert infer.context.trace_id == consume.context.trace_id
        assert infer.parent.span_id == consume.context.span_id
        assert trusted.parent.span_id == int("b" * 16, 16)
    finally:
        telemetry.close()


def test_export_boundary_drops_native_sdk_payload_and_raw_exception(tmp_path, monkeypatch):
    from opentelemetry import trace
    exporter = CapturingExporter()
    telemetry = _runtime_with_exporter(tmp_path, monkeypatch, exporter)
    try:
        with pytest.raises(ValueError, match="business-secret"):
            with telemetry.span("mem0.search", {"owner.id": "raw-owner", "result.count": 3}):
                native = trace.get_current_span()
                native.set_attribute("gen_ai.input.messages", "private-native-prompt")
                native.add_event("private-event", {"token": "native-secret"})
                native.set_status(trace.Status(trace.StatusCode.ERROR, "private-status"))
                raise ValueError("business-secret")
        assert telemetry.provider.force_flush(timeout_millis=1000)
        assert len(exporter.spans) == 1
        span = exporter.spans[0]
        assert span.attributes["error.type"] == "ValueError"
        assert span.attributes["outcome"] == "error"
        assert span.events == () and span.links == ()
        wire = span.to_json()
        assert all(secret not in wire for secret in (
            "business-secret", "private-native-prompt", "native-secret", "private-status", "raw-owner"))
    finally:
        telemetry.close()


def test_real_otlp_http_exporter_sends_sanitized_protobuf_basic_auth_and_v4(tmp_path, monkeypatch):
    """No provider/model calls: exercise the actual pinned SDK HTTP exporter."""
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.path, dict(self.headers), body))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
        def log_message(self, *_args):
            pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .1}, daemon=True)
    thread.start()
    _trace_configuration(tmp_path, monkeypatch)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
                       f"http://127.0.0.1:{server.server_port}/api/public/otel/v1/traces")
    telemetry = RuntimeTelemetry.from_env("doorhandle-fixture")
    try:
        with telemetry.span("embedding.request", {"embedding.model": "BAAI/bge-m3",
                                                  "embedding.dimension": 1024,
                                                  "prompt": "must-not-be-exported"}):
            pass
        assert telemetry.provider.force_flush(timeout_millis=1000)
        assert len(received) == 1
        path, headers, body = received[0]
        normalized = {key.lower(): value for key, value in headers.items()}
        expected = base64.b64encode(b"pk-test-only:sk-test-private-only").decode()
        assert path == "/api/public/otel/v1/traces"
        assert normalized["authorization"] == "Basic " + expected
        assert normalized["x-langfuse-ingestion-version"] == "4"
        assert normalized["content-type"] == "application/x-protobuf"
        message = ExportTraceServiceRequest.FromString(body)
        spans = message.resource_spans[0].scope_spans[0].spans
        assert len(spans) == 1 and spans[0].name == "embedding.request"
        assert b"must-not-be-exported" not in body
        assert b"BAAI/bge-m3" in body
    finally:
        telemetry.close()
        server.shutdown()
        server.server_close()
        thread.join(1)


def test_bounded_admission_is_nonblocking_and_counts_every_drop():
    metrics = _Metrics()
    metrics.configure()
    processor = _Admission(8, metrics, lambda span: span)
    queued = []
    processor.delegate = SimpleNamespace(on_end=queued.append)
    span = SimpleNamespace(context=SimpleNamespace(trace_flags=SimpleNamespace(sampled=True)))
    started = time.monotonic()
    for _ in range(40):
        processor.on_end(span)
    assert time.monotonic() - started < .5
    assert len(queued) == 8
    text = _metrics_text(metrics)
    assert 'doorhandle_telemetry_failures_total{reason="queue_full"} 32.0' in text
    assert "doorhandle_telemetry_pending_spans 8.0" in text
    processor.release(8)
    processor.on_end(span)
    assert len(queued) == 9
    processor.release(1)


def test_failed_export_releases_capacity_and_does_not_raise_or_log_secret():
    metrics = _Metrics()
    metrics.configure()
    admission = _Admission(8, metrics, lambda span: span)
    queued = []
    admission.delegate = SimpleNamespace(on_end=queued.append)
    admission.on_end(SimpleNamespace(context=SimpleNamespace(trace_flags=SimpleNamespace(sampled=True))))
    class BrokenExporter:
        def export(self, spans):
            raise RuntimeError("private bearer secret")
    from opentelemetry.sdk.trace.export import SpanExportResult
    exporter = _AccountingExporter(BrokenExporter(), admission, metrics)
    assert exporter.export(queued) == SpanExportResult.FAILURE
    text = _metrics_text(metrics)
    assert 'doorhandle_telemetry_failures_total{reason="export_failed"} 1.0' in text
    assert "doorhandle_telemetry_pending_spans 0.0" in text
    assert "private" not in text


def test_metrics_auth_is_separate_from_business_health(tmp_path, monkeypatch):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    monkeypatch.setenv("TELEMETRY_METRICS_ENABLED", "true")
    monkeypatch.setenv("TELEMETRY_EVENTS_ENABLED", "false")
    monkeypatch.setenv("TELEMETRY_METRICS_PORT", str(port))
    token = "private-machine-token-fixture-12345"
    _secret(tmp_path, monkeypatch, "TELEMETRY_METRICS_TOKEN_FILE", token)
    telemetry = RuntimeTelemetry.from_env("doorhandle-fixture")
    try:
        telemetry.set_ready(True)
        def get(path, authorization=None):
            connection = HTTPConnection("127.0.0.1", port, timeout=1)
            try:
                connection.request("GET", path, headers={"Authorization": authorization} if authorization else {})
                response = connection.getresponse()
                return response.status, response.read().decode()
            finally:
                connection.close()
        assert get("/metrics")[0] == 401
        assert get("/metrics", "Bearer wrong-token")[0] == 401
        assert get("/metrics?token=" + token, "Bearer " + token)[0] == 404
        status, payload = get("/metrics", "Bearer " + token)
        assert status == 200
        assert "doorhandle_runtime_ready 1.0" in payload
        assert "doorhandle_telemetry_tracing_enabled 0.0" in payload
        assert token not in payload
        with telemetry.span("worker.consume", {"task.id": "never-a-prom-label"}):
            pass
        assert "never-a-prom-label" not in get("/metrics", "Bearer " + token)[1]
    finally:
        telemetry.close()
    assert not telemetry.server_thread.is_alive()


def test_enabled_bad_configuration_is_safe_and_business_exception_unchanged(monkeypatch):
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv("TELEMETRY_EVENTS_ENABLED", "false")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "https://password@private.invalid/private")
    runtime = RuntimeTelemetry.from_env("doorhandle-fixture")
    try:
        assert runtime.bootstrap_failure == "config_invalid"
        original = RuntimeError("exact business error")
        with pytest.raises(RuntimeError) as caught:
            with runtime.span("worker.consume"):
                raise original
        assert caught.value is original
    finally:
        runtime.close()


def test_sdk_log_filter_removes_original_exception_and_response():
    record = logging.LogRecord("sdk", logging.ERROR, "", 1, "private-response %s", ("secret",),
                               (ValueError, ValueError("secret"), None))
    record.stack_info = "private stack"
    record.exc_text = "private exception"
    assert _SafeSdkLog().filter(record)
    assert record.getMessage() == "telemetry_sdk_failure"
    assert record.exc_info is record.exc_text is record.stack_info is None


def test_structured_event_queue_is_bounded_and_payload_free():
    telemetry = RuntimeTelemetry("doorhandle-fixture")
    telemetry.metrics.configure()
    telemetry.event_queue = queue.Queue(maxsize=1)
    telemetry.event("worker.consume", "success")
    telemetry.event("https://private?secret=token", "private-payload")
    assert telemetry.event_queue.qsize() == 1
    event = telemetry.event_queue.get_nowait()
    assert event == {"event": "runtime.operation", "service": "doorhandle-fixture",
                     "operation": "worker.consume", "outcome": "success"}
    assert 'reason="event_queue_full"' in _metrics_text(telemetry.metrics)


def test_close_is_bounded_when_exporter_shutdown_is_stuck():
    telemetry = RuntimeTelemetry("doorhandle-fixture")
    telemetry.metrics.configure()
    release = threading.Event()
    telemetry.provider = SimpleNamespace(shutdown=lambda: release.wait(2))
    started = time.monotonic()
    try:
        telemetry.close(timeout_seconds=.1)
        assert time.monotonic() - started < .5
        assert 'reason="shutdown_timeout"' in _metrics_text(telemetry.metrics)
        telemetry.close()  # idempotent; does not start another closer
    finally:
        release.set()
