"""Tenant event integrity and explicit execution scope. No environment credentials are inferred."""
import base64
import contextvars
import hashlib
import hmac
import json
from pathlib import Path
import re
from contextlib import contextmanager
from types import MappingProxyType


MAX_SIGNED_PAYLOAD = 1_500_000
CONTEXT_FIELDS = {'tenantId', 'actorUserId', 'membershipRevision', 'policyRevision', 'requestId',
                  'rootRunId', 'parentRunId', 'budgetAccountId', 'budgetFence'}
_CURRENT = contextvars.ContextVar('doorhandle_tenant_execution', default=None)


class TenantSecurityError(ValueError):
    pass


def validate_context(value):
    if not isinstance(value, dict) or set(value) != CONTEXT_FIELDS:
        raise TenantSecurityError('Complete tenant execution context is required')
    for key in ('tenantId', 'actorUserId', 'membershipRevision', 'policyRevision'):
        if type(value[key]) is not int or not 1 <= value[key] <= 9223372036854775807:
            raise TenantSecurityError('Invalid tenant membership identity')
    if not isinstance(value['requestId'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', value['requestId']):
        raise TenantSecurityError('Invalid tenant request identity')
    for key in ('rootRunId', 'parentRunId', 'budgetAccountId'):
        if value[key] is not None and (not isinstance(value[key], str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', value[key])):
            raise TenantSecurityError('Invalid tenant execution reference')
    fence = value['budgetFence']
    if type(fence) is not int or not 0 <= fence <= 9223372036854775807:
        raise TenantSecurityError('Invalid root ownership fence')
    if value['budgetAccountId'] is None:
        if fence != 0 or value['rootRunId'] is not None or value['parentRunId'] is not None:
            raise TenantSecurityError('Unadmitted execution cannot claim a root')
    elif fence < 1 or value['rootRunId'] is None:
        raise TenantSecurityError('Admitted execution requires its original root fence')
    return dict(value)


@contextmanager
def execution_scope(context):
    context = validate_context(context)
    previous = _CURRENT.get()
    if previous is not None and dict(previous) != context:
        raise TenantSecurityError('An active worker execution cannot change tenant context')
    token = _CURRENT.set(MappingProxyType(context))
    try:
        yield context
    finally:
        _CURRENT.reset(token)


def current_context():
    value = _CURRENT.get()
    return None if value is None else dict(value)


def require_context():
    value = current_context()
    if value is None:
        raise TenantSecurityError('Missing verified tenant execution scope')
    return validate_context(value)


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise TenantSecurityError('Duplicate signed JSON field')
        value[key] = item
    return value


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def invalid_number(value):
    raise TenantSecurityError('Non-finite signed JSON number')


class TenantEventSecurity:
    def __init__(self, keys=None, active=None, enabled=True):
        self.enabled = bool(enabled)
        self.keys = dict(keys or {})
        self.active = active
        if self.enabled and (not 1 <= len(self.keys) <= 16 or active not in self.keys
                or any(not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', key)
                       or not isinstance(secret, bytes) or not 32 <= len(secret) <= 128 for key, secret in self.keys.items())):
            raise TenantSecurityError('Explicit tenant event signing keys are required')

    @classmethod
    def from_file(cls, filename, active):
        try:
            path = Path(filename).absolute()
            if any(parent.is_symlink() for parent in (path, *path.parents)) or not path.is_file() or path.stat().st_size > 32768:
                raise ValueError()
            data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object)
            if not isinstance(data, dict):
                raise ValueError()
            return cls({key: base64.b64decode(value, validate=True) for key, value in data.items()}, active)
        except Exception:
            raise TenantSecurityError('Tenant event signing Secret is unavailable') from None

    def sign_raw(self, raw):
        if not self.enabled or not isinstance(raw, bytes) or len(raw) > MAX_SIGNED_PAYLOAD:
            raise TenantSecurityError('Invalid bounded tenant signing payload')
        payload = base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
        text = ('doorhandle-tenant-event-v1\n' + self.active + '\n' + payload).encode('ascii')
        return {'keyId': self.active, 'payload': payload,
                'signature': hmac.new(self.keys[self.active], text, hashlib.sha256).hexdigest()}

    def verify_raw(self, seal):
        if not self.enabled or not isinstance(seal, dict) or set(seal) != {'keyId', 'payload', 'signature'}:
            raise TenantSecurityError('Tenant event signature is required')
        key, payload, signature = seal['keyId'], seal['payload'], seal['signature']
        if (not isinstance(key, str) or key not in self.keys or not isinstance(payload, str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,2000000}', payload)
                or not isinstance(signature, str) or not re.fullmatch(r'[a-f0-9]{64}', signature)):
            raise TenantSecurityError('Invalid tenant event signature')
        text = ('doorhandle-tenant-event-v1\n' + key + '\n' + payload).encode('ascii')
        if not hmac.compare_digest(hmac.new(self.keys[key], text, hashlib.sha256).hexdigest(), signature):
            raise TenantSecurityError('Invalid tenant event signature')
        try:
            raw = base64.b64decode(payload + '=' * (-len(payload) % 4), altchars=b'-_', validate=True)
            if len(raw) > MAX_SIGNED_PAYLOAD or base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=') != payload:
                raise ValueError()
            return raw
        except Exception:
            raise TenantSecurityError('Invalid signed tenant payload') from None

    def verify_event(self, event):
        if not isinstance(event, dict):
            raise TenantSecurityError('Tenant event must be an object')
        context = event.get('tenantContext') if isinstance(event, dict) else None
        seal = event.get('tenantSeal') if isinstance(event, dict) else None
        if not self.enabled:
            if context is not None or seal is not None:
                raise TenantSecurityError('Tenant events cannot be downgraded to legacy execution')
            return None
        context = validate_context(context)
        raw = self.verify_raw(seal)
        try:
            unsigned = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object, parse_constant=invalid_number)
            observed = {key: value for key, value in event.items() if key != 'tenantSeal'}
            if not isinstance(unsigned, dict) or json_bytes(unsigned) != json_bytes(observed):
                raise ValueError()
        except Exception:
            raise TenantSecurityError('Signed tenant event changed') from None
        return context
