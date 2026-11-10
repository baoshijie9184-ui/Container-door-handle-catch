"""Compile the closed LOGIN_SESSION namespace into SQL sources; never execute SQL.

The SDK session_id/state_key columns remain unused. Credentials are SHA-256 only.
The account enabled/version fields are in the core baseline and explicitly derived
by author_core_copy.py, not added to historical source fixtures.
"""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[2]


def constraint():
    properties = {
        'version': {'type': 'integer', 'enum': [1]},
        'userId': {'type': 'integer', 'minimum': 1, 'maximum': 9223372036854775807},
        'username': {'type': 'string', 'minLength': 1, 'maxLength': 50},
        'role': {'type': 'string', 'enum': ['SUPERVISOR', 'INSPECTOR']},
        'accountContext': {'type': 'string', 'pattern': '^[A-Za-z0-9_-]{43}$'},
        'refreshDigest': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'},
    }
    schema = json.dumps({'type': 'object', 'additionalProperties': False,
                         'required': list(properties), 'properties': properties}, separators=(',', ':'))
    return ("CONSTRAINT ck_runtime_login_session CHECK (namespace<>'LOGIN_SESSION' OR COALESCE(("
            "owner_id>0 AND scope_key REGEXP '^[a-f0-9]{64}$' AND session_id IS NULL AND state_key IS NULL "
            "AND revision>=0 AND state_code IN ('ACTIVE','REVOKED') AND current_ref IS NULL AND counter_value IS NULL "
            "AND provider IS NULL AND credential_sha256 IS NULL AND actor_user_id IS NULL AND request_id IS NULL "
            "AND window_started_at IS NOT NULL AND window_ends_at>window_started_at AND created_at=window_started_at "
            "AND updated_at IS NOT NULL AND payload_version=1 AND payload_json IS NOT NULL "
            "AND JSON_SCHEMA_VALID('" + schema + "',payload_json) "
            "AND JSON_EXTRACT(payload_json,'$.userId')=owner_id),0)=1)")


def main():
    for relative in ('sql/mysql/compact/baseline/30-operations.sql', 'sql/mysql/compact/001-coordination-state.sql'):
        path = ROOT / relative
        text = path.read_text(encoding='utf-8')
        text = re.sub(r'(?m)^\s*CONSTRAINT ck_runtime_login_session CHECK .*\n', '', text)
        text = re.sub(r'(?m)^\s*KEY ix_runtime_login_expiry .*\n', '', text)
        anchor = re.search(r'(?m)^\s*(?:KEY ix_runtime_state|KEY ix_runtime_state_expiry)', text)
        if not anchor:
            raise ValueError('Missing exact runtime index insertion anchor: ' + relative)
        text = text[:anchor.start()] + '    ' + constraint() + ',\n    KEY ix_runtime_login_expiry (namespace,state_code,window_ends_at,owner_id),\n' + text[anchor.start():]
        with path.open('w', encoding='utf-8', newline='\n') as output:
            output.write(text)
    # The classpath fixture must have exactly the full reviewed runtime table, including legacy guards.
    from sync_compact_resources import expected
    destination = ROOT / 'doorhandle-framework/src/main/resources/db/compact/001-coordination-state.sql'
    with destination.open('w', encoding='utf-8', newline='\n') as output:
        output.write(expected()['001-coordination-state.sql'])
    print('LOGIN_SESSION_SQL_SOURCE_COMPILED_NOT_EXECUTED')


if __name__ == '__main__':
    main()
