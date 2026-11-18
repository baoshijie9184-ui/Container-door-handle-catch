"""Signed, non-replayed Detection Owner authorization before each tenant worker effect."""
import hashlib
import json
from dataclasses import asdict
import re
import ssl
import time
import uuid
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler, HTTPSHandler

from tenant_execution_security import (TenantSecurityError, validate_context, json_bytes,
                                       unique_object, invalid_number)


class TenantExecutionAuthorizationError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise TenantExecutionAuthorizationError('Tenant authorization redirects are forbidden')


class TenantDetectionAuthority:
    def __init__(self, endpoint, security, *, require_tls=False, ca_file=None, on_receipt=None):
        parsed = urlsplit(endpoint)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or parsed.path != '/internal/detection/tenant-executions/authorize'
                or require_tls and parsed.scheme != 'https' or not security.enabled):
            raise ValueError('An explicit trusted Detection Owner tenant authorization endpoint is required')
        self.endpoint, self.security, self.on_receipt = endpoint, security, on_receipt
        context = ssl.create_default_context(cafile=ca_file or None)
        self.http = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=context))

    def original(self, task):
        original = getattr(task, '_tenant_original_event', None)
        raw = getattr(task, '_tenant_original_wire', None)
        if not isinstance(original, dict) or not isinstance(raw, str):
            raise TenantExecutionAuthorizationError('Original sealed tenant task bytes are required')
        self.security.verify_event(original)
        from kafka_event_models import DetectionTaskCreatedEvent
        expected = DetectionTaskCreatedEvent.from_dict(original)
        if json_bytes(asdict(task)) != json_bytes(asdict(expected)):
            raise TenantExecutionAuthorizationError('Worker task changed after tenant verification')
        return original, raw

    def authorize(self, task, owner, phase):
        if not isinstance(owner, str) or not re.fullmatch(r'[a-f0-9]{32}', owner) or phase not in {'READ_INPUT', 'INFER', 'WRITE_RESULT'}:
            raise TenantExecutionAuthorizationError('Actual original worker claim and effect phase are required')
        original, original_wire = self.original(task)
        context = validate_context(task.tenant_context)
        event_sha = hashlib.sha256(self.security.verify_raw(original['tenantSeal'])).hexdigest()
        nonce = str(uuid.uuid4())
        # Preserve all original JSON numbers/bytes; do not round a signed decimal through Python float.
        header = json_bytes({'atEpoch': int(time.time()), 'nonce': nonce, 'phase': phase, 'executionOwnerId': owner})
        unsigned = header[:-1] + b',"originalEvent":' + original_wire.encode('utf-8') + b'}'
        sealed = self.security.sign_raw(unsigned)
        body = json_bytes(sealed)
        request = Request(self.endpoint, body, {'Content-Type': 'application/json; charset=utf-8'}, method='POST')
        try:
            with self.http.open(request, timeout=10) as response:
                if response.status != 200:
                    raise ValueError()
                raw = response.read(65537)
                if len(raw) > 65536:
                    raise ValueError()
            receipt = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object, parse_constant=invalid_number)
            if (not isinstance(receipt, dict) or type(receipt.get('schemaVersion')) is not int or receipt['schemaVersion'] != 1
                    or receipt.get('authorized') is not True or receipt.get('status') != 'AUTHORIZED'
                    or type(receipt.get('tenantId')) is not int or receipt['tenantId'] != context['tenantId']
                    or receipt.get('taskId') != task.task_id or receipt.get('dispatchId') != task.dispatch_id
                    or receipt.get('executionOwnerId') != owner or receipt.get('phase') != phase
                    or type(receipt.get('budgetFence')) is not int or receipt['budgetFence'] != context['budgetFence']
                    or receipt.get('eventSha256') != event_sha or receipt.get('originalEventSha256') != event_sha
                    or json_bytes(validate_context(receipt.get('tenantContext'))) != json_bytes(context)):
                raise ValueError()
            bindings = receipt.get('bindings')
            if (not isinstance(bindings, dict)
                    or set(bindings) != {'bucketName', 'sourcePrefix', 'originalKeys', 'modelArtifact', 'imageManifest'}
                    or any(json_bytes(bindings[key]) != json_bytes(original.get(key)) for key in bindings)):
                raise ValueError()
            evidence = {'schemaVersion': 1, 'nonce': nonce, 'phase': phase, 'executionOwnerId': owner,
                        'eventSha256': event_sha, 'requestSha256': hashlib.sha256(unsigned).hexdigest(),
                        'responseSha256': hashlib.sha256(raw).hexdigest(), 'budgetFence': context['budgetFence']}
            if self.on_receipt is None:
                raise TenantExecutionAuthorizationError('Durable worker authorization receipt storage is required')
            self.on_receipt(task, owner, evidence)
            return evidence
        except TenantExecutionAuthorizationError:
            raise
        except Exception:
            # No remote body, Secret path or authorization payload is exposed; never retry a lost response.
            raise TenantExecutionAuthorizationError('Tenant effect authorization needs verification; operation not started') from None
