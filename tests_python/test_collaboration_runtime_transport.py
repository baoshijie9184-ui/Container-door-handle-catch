"""ECS-only regression contracts for the complete candidate's HTTP/fixture wiring.

These use urllib's actual cookie processor with an in-memory transport. They do
not replace the nine full-stack scenarios or the real browser acceptance.
"""
from email.message import Message
import importlib.util
import io
import json
from pathlib import Path
import re
from types import SimpleNamespace
import urllib.error
import urllib.request
import urllib.response

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rehearsal = load('collaboration_runtime_rehearsal', 'script/docker/application-rehearsal.py')
scenarios = load('collaboration_runtime_scenarios', 'script/docker/compact-runtime-scenarios.py')
runtime = load('collaboration_runtime_runner', 'script/docker/compact-runtime-acceptance.py')
CONTEXT = 'A' * 43
TOKEN = 'abcdef012345'
SCHEMA = 'doorhandle_compact_candidate_abcdef0123'


def checked(context=CONTEXT):
    return {'authenticated': True, 'userId': '9007199254740993', 'username': 'owned-inspector',
            'role': 'INSPECTOR', 'accountContext': context,
            'capabilities': {'sessionTracking': True, 'changeHistory': True, 'mutations': True, 'realtime': True},
            'identity': {'userId': '9007199254740993', 'employeeId': 81, 'departmentId': 90,
                         'employeeStatus': 'ACTIVE', 'employeeType': 'DETECTION', 'bindingVersion': 0}}


def account():
    return {'username': 'owned-inspector', 'password': 'fixture-secret', 'userId': 9007199254740993,
            'role': 'INSPECTOR', 'employeeId': 81, 'departmentId': 90}


class MemoryHttp(urllib.request.BaseHandler):
    handler_order = 100

    def __init__(self, context=CONTEXT, failure=None):
        self.context, self.failure, self.requests = context, failure, []

    def http_open(self, request):
        self.requests.append(request)
        headers = Message(); headers['Content-Type'] = 'application/json'
        if request.selector == '/api/auth/login':
            for name, value, path in (('DOOR_HANDLE_CONTEXT', self.context, '/'),
                    ('DOOR_HANDLE_TOKEN_' + self.context, 'access-' + self.context[0], '/'),
                    ('DOOR_HANDLE_REFRESH_TOKEN_' + self.context, 'refresh-' + self.context[0], '/api/auth')):
                headers.add_header('Set-Cookie', name + '=' + value + '; Path=' + path + '; HttpOnly; SameSite=Lax')
            data = {'accountContext': self.context}
        elif request.selector == '/api/auth/check':
            data = checked(self.context)
        elif self.failure:
            raise urllib.error.HTTPError(request.full_url, self.failure, 'fixture denial', headers, io.BytesIO(b'{}'))
        else:
            data = {'saved': True}
        response = urllib.response.addinfourl(io.BytesIO(json.dumps({'code': 200, 'data': data}).encode()),
                                             headers, request.full_url, code=200)
        response.msg = 'OK'
        return response


def client(context=CONTEXT, failure=None):
    value = rehearsal.Client(18080); transport = MemoryHttp(context, failure)
    value.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(value.cookies), transport)
    return value, transport


@pytest.mark.parametrize('adapter', ['rehearsal', 'scenarios', 'runtime'])
def test_all_http_adapters_use_cookie_jar_origin_checked_context_and_original_command_id(adapter):
    subject, transport = client(); subject.login('owned-inspector')
    payload = {'requestId': 'same-command-1', 'expectedVersion': '9007199254740993', 'name': 'fixture'}
    if adapter == 'rehearsal':
        result = subject.request('POST', '/api/owned-command', payload)
    elif adapter == 'scenarios':
        result = scenarios.request(subject, 'POST', '/api/owned-command', payload)
    else:
        owner = SimpleNamespace(client=lambda name: subject)
        result = runtime.Runtime.request(owner, 'inspector', 'POST', '/api/owned-command', payload)
    assert result == {'saved': True}
    login, check, saved = transport.requests
    assert login.get_header('Origin') == subject.base
    assert check.get_header('X-account-context') is None
    assert saved.get_header('Origin') == subject.base
    assert saved.get_header('Referer') == subject.base + '/'
    assert saved.get_header('X-account-context') == CONTEXT
    assert saved.get_header('X-request-id') == payload['requestId']
    assert json.loads(saved.data) == payload
    assert 'DOOR_HANDLE_CONTEXT=' + CONTEXT in saved.get_header('Cookie')
    assert 'DOOR_HANDLE_TOKEN_' + CONTEXT + '=access-A' in saved.get_header('Cookie')
    assert 'REFRESH' not in saved.get_header('Cookie')  # actual /api/auth path restriction
    assert subject.account_context == CONTEXT


def test_separate_accounts_never_share_cookie_sessions_and_a_new_login_requires_new_check():
    first, first_wire = client(); second, second_wire = client('B' * 43)
    first.login('first'); second.login('second')
    for subject in (first, second):
        scenarios.request(subject, 'POST', '/api/owned-command', {'requestId': 'isolated-command'})
    assert 'access-A' in first_wire.requests[-1].get_header('Cookie')
    assert 'access-B' not in first_wire.requests[-1].get_header('Cookie')
    assert second_wire.requests[-1].get_header('X-account-context') == 'B' * 43
    first.observe_auth('/api/auth/login', {'accountContext': 'B' * 43})
    assert first.account_context is None
    first.observe_auth('/api/auth/check', checked('B' * 43))
    assert first.prepare_request('POST', '/api/owned-command').get_header('X-account-context') == 'B' * 43


def test_runtime_establishes_and_checks_a_session_once_then_reuses_its_cookie_jar():
    subject, transport = client()
    owner = SimpleNamespace(accounts={'inspector': account()}, clients={}, owner={'port': 18080},
                            rehearsal=SimpleNamespace(Client=lambda port: subject), http=scenarios)
    assert runtime.Runtime.client(owner, 'inspector') is subject
    assert runtime.Runtime.client(owner, 'inspector') is subject
    assert [message.selector for message in transport.requests] == ['/api/auth/login', '/api/auth/check']
    assert subject.account_context == CONTEXT


@pytest.mark.parametrize('context,tracking', [(CONTEXT, True), ('a1' * 32, False)])
def test_shared_client_accepts_scoped_and_legacy_account_contexts(context, tracking):
    subject, _ = client(); identity = checked(context)
    identity['capabilities']['sessionTracking'] = tracking
    subject.observe_auth('/api/auth/check', identity)
    assert subject.prepare_request('POST', '/api/owned-command').get_header('X-account-context') == context
    if not tracking:
        with pytest.raises(RuntimeError, match='every collaboration capability'):
            scenarios.require_account(identity, account())


@pytest.mark.parametrize('context', ['g' * 64, 'a' * 44])
def test_shared_client_still_rejects_malformed_account_contexts(context):
    subject, _ = client()
    with pytest.raises(RuntimeError, match='authenticated account context'):
        subject.observe_auth('/api/auth/check', checked(context))


@pytest.mark.parametrize('status', [401, 409, 500])
def test_failed_writes_are_never_automatically_refreshed_or_retried(status):
    subject, transport = client(failure=status); subject.login('owned-inspector')
    with pytest.raises(RuntimeError, match='unexpected HTTP status'):
        scenarios.request(subject, 'POST', '/api/owned-command', {'requestId': 'retain-original'})
    assert len(transport.requests) == 3
    assert transport.requests[-1].get_header('X-request-id') == 'retain-original'
    assert subject.account_context == CONTEXT


@pytest.mark.parametrize('version', [0, '0', '9007199254740993', '9223372036854775807'])
def test_protected_command_uses_exact_actual_version_and_stable_request_id(version):
    headers = scenarios.command_headers({'version': version}, 'runtime-task-review-' + TOKEN)
    subject, _ = client(); subject.observe_auth('/api/auth/check', checked())
    message = subject.prepare_request('POST', '/api/detection/tasks/owned/review', {'reviewConclusion': 'PASS'}, headers=headers)
    assert message.get_header('X-expected-version') == str(version)
    assert message.get_header('X-request-id') == 'runtime-task-review-' + TOKEN
    assert message.get_header('X-account-context') == CONTEXT


@pytest.mark.parametrize('version', [None, True, 1.5, '01', '-1', '9223372036854775808'])
def test_missing_or_lossy_resource_versions_fail_before_any_write(version):
    with pytest.raises(RuntimeError):
        scenarios.command_headers({'version': version}, 'stable-command')


def test_full_candidate_accepts_bigint_string_identity_and_real_employee_binding():
    scenarios.require_account(checked(), account())
    # Binding revisions start at zero, then advance through real HTTP rebinds.
    # They are revisions, unlike the strictly positive account/employee IDs.
    current, expected = checked(), account()
    current['identity']['bindingVersion'] = '2'; expected['bindingVersion'] = 2
    scenarios.require_account(current, expected)
    with pytest.raises(RuntimeError):
        scenarios.require_account(current, account())
    assert set(scenarios.COLLABORATION_ENV) == {'OPERATIONS_AUDIT_ENABLED', 'COLLABORATION_SESSIONS_ENABLED',
        'COLLABORATION_CHANGE_HISTORY_ENABLED', 'COLLABORATION_MUTATIONS_ENABLED', 'COLLABORATION_REALTIME_ENABLED'}
    assert all(value == 'true' for value in scenarios.COLLABORATION_ENV.values())


@pytest.mark.parametrize('capability', ['sessionTracking', 'changeHistory', 'mutations', 'realtime'])
def test_disabled_capabilities_cannot_be_reported_as_complete_runtime_acceptance(capability):
    identity = checked(); identity['capabilities'][capability] = False
    with pytest.raises(RuntimeError, match='every collaboration capability'):
        scenarios.require_account(identity, account())


@pytest.mark.parametrize('damage', ['unbound', 'other-employee', 'resigned', 'wrong-position'])
def test_runtime_checks_current_qualified_personnel_instead_of_only_the_role_label(damage):
    identity = checked()
    if damage == 'unbound': identity['identity']['employeeId'] = None
    elif damage == 'other-employee': identity['identity']['employeeId'] = 82
    elif damage == 'resigned': identity['identity']['employeeStatus'] = 'RESIGNED'
    else: identity['identity']['employeeType'] = 'COLLECTION'
    with pytest.raises(RuntimeError):
        scenarios.require_account(identity, account())


class OwnedDatabase:
    schema = SCHEMA

    def __init__(self, fk=1, tables=29, conflict=None):
        self.fk, self.tables, self.conflict, self.writes, self.index = fk, tables, conflict, [], 0

    def literal(self, value):
        return "'" + value.replace("'", "''") + "'"

    def execute(self, sql):
        self.writes.append(sql)

    def one(self, sql):
        if 'DATABASE()' in sql:
            return {'schema': self.schema, 'fk': self.fk, 'tables': self.tables}
        if 'COUNT(*)' in sql:
            return {'n': int(bool(self.conflict and self.conflict in sql))}
        self.index += 1
        username = re.search(r"BINARY u.username=BINARY '([^']+)'", sql).group(1)
        return {'id': 100 + self.index, 'role': 'SUPERVISOR' if username.endswith(('_supervisor', '_reviewer')) else 'INSPECTOR',
                'enabled': 1, 'accountVersion': 0, 'employeeId': 200 + self.index, 'employeeType': 'DETECTION',
                'employeeStatus': 'ACTIVE', 'departmentId': 90, 'department': 'runtime-' + TOKEN,
                'bindingVersion': 0, 'history': 1}


def test_seed_owns_twenty_distinct_qualified_people_in_one_transaction_without_fabricated_audit():
    database = OwnedDatabase()
    accounts = scenarios.seed_owned_users(database, SCHEMA, TOKEN, candidate_load_user_count=20)
    assert len(accounts) == 20 and len({v['employeeId'] for v in accounts.values()}) == 20
    assert sum(v['role'] == 'SUPERVISOR' for v in accounts.values()) == 2
    assert {'inspector', 'peer', 'supervisor', 'reviewer', 'load_01', 'load_16'} <= accounts.keys()
    assert len(database.writes) == 1
    sql = database.writes[0]
    assert sql.startswith('START TRANSACTION;') and sql.endswith('COMMIT;')
    assert sql.count('INSERT INTO organization_department') == 1
    assert sql.count('INSERT INTO employee(') == sql.count('INSERT INTO users(') == 20
    assert sql.count(',TRUE,0,LAST_INSERT_ID(),0,TRUE,') == 20
    assert "'ACTIVE',0,@runtime_department" in sql and "'DETECTION','UNKNOWN'" in sql
    assert not any(forbidden in sql.upper() for forbidden in ('FOREIGN_KEY_CHECKS', 'UPDATE ', 'AUDIT_EVENT', 'WORKFLOW_INSTANCE'))
    assert all(set(value) == {'username', 'password', 'role', 'userId', 'employeeId', 'departmentId'}
               for value in accounts.values())


@pytest.mark.parametrize('damage', ['foreign-schema', 'foreign-key-off', 'incomplete-schema'])
def test_seed_never_writes_an_unowned_or_incomplete_target(damage):
    database = OwnedDatabase(fk=0 if damage == 'foreign-key-off' else 1,
                             tables=28 if damage == 'incomplete-schema' else 29)
    schema = 'doorhandle' if damage == 'foreign-schema' else SCHEMA
    with pytest.raises(RuntimeError):
        scenarios.seed_owned_users(database, schema, TOKEN)
    assert database.writes == []


@pytest.mark.parametrize('collision', ['organization_department', 'FROM users', 'FROM employee'])
def test_fixture_collisions_do_not_overwrite_existing_users_employees_or_departments(collision):
    database = OwnedDatabase(conflict=collision)
    with pytest.raises(RuntimeError, match='already exists'):
        scenarios.seed_owned_users(database, SCHEMA, TOKEN)
    assert database.writes == []


@pytest.mark.parametrize('count', [True, 19, 41, 20.0])
def test_fixture_account_count_is_bounded_before_database_access(count):
    database = OwnedDatabase()
    with pytest.raises(RuntimeError, match='bounded candidate'):
        scenarios.seed_owned_users(database, SCHEMA, TOKEN, candidate_load_user_count=count)
    assert database.writes == []
