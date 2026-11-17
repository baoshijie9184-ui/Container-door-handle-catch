"""ECS-only regression contracts for the complete candidate's HTTP/fixture wiring.

These use urllib's actual cookie processor with an in-memory transport. They do
not replace the nine full-stack scenarios or the real browser acceptance.
"""
from email.message import Message
import importlib.util
import io
import json
import os
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


def test_seed_owns_four_distinct_qualified_people_in_one_transaction_without_fabricated_audit():
    database = OwnedDatabase()
    accounts = scenarios.seed_owned_users(database, SCHEMA, TOKEN, candidate_load_user_count=4)
    assert len(accounts) == 4 and len({v['employeeId'] for v in accounts.values()}) == 4
    assert sum(v['role'] == 'SUPERVISOR' for v in accounts.values()) == 2
    assert set(accounts) == {'inspector', 'peer', 'supervisor', 'reviewer'}
    assert len(database.writes) == 1
    sql = database.writes[0]
    assert sql.startswith('START TRANSACTION;') and sql.endswith('COMMIT;')
    assert sql.count('INSERT INTO organization_department') == 1
    assert sql.count('INSERT INTO employee(') == sql.count('INSERT INTO users(') == 4
    assert sql.count(',TRUE,0,LAST_INSERT_ID(),0,TRUE,') == 4
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


@pytest.mark.parametrize('count', [True, 3, 5, 4.0])
def test_fixture_account_count_is_bounded_before_database_access(count):
    database = OwnedDatabase()
    with pytest.raises(RuntimeError, match='functional candidate'):
        scenarios.seed_owned_users(database, SCHEMA, TOKEN, candidate_load_user_count=count)
    assert database.writes == []


class EmployeeDateDatabase(OwnedDatabase):
    def __init__(self, damage=None):
        super().__init__(fk=0 if damage == 'foreign-key-off' else 1, tables=28 if damage == 'incomplete-schema' else 29)
        self.damage = damage

    def one(self, sql):
        if 'DATABASE()' in sql: return super().one(sql)
        if 'FROM organization_department' in sql: return {'n': 0 if self.damage == 'foreign-department' else 1}
        if 'FROM employee WHERE' in sql: return {'n': 1 if self.damage == 'employee-collision' else 0}
        assert 'FROM employee e' in sql and 'FROM users u WHERE u.employee_id=e.id' in sql
        return {'id': 700, 'hireDate': '2020-01-01' if self.damage == 'normalized' else '2020年春',
                'version': 0, 'departmentId': 90, 'bindings': 1 if self.damage == 'bound' else 0}


def test_browser_legacy_employee_seed_is_unbound_and_does_not_manufacture_write_receipts():
    database = EmployeeDateDatabase()
    value = scenarios.seed_employee_hire_date_fixture(database, SCHEMA, TOKEN, 90)
    assert value == {'employeeId': '700', 'employeeNumber': 'BD' + TOKEN[:16], 'departmentId': '90', 'legacyHireDate': '2020年春'}
    assert len(database.writes) == 1
    sql = database.writes[0]
    assert sql.startswith('START TRANSACTION;') and sql.endswith('COMMIT;')
    assert sql.count('INSERT INTO employee(') == 1 and '2020年春' in sql and 'hiredate@fixture.invalid' in sql
    assert not any(value in sql.upper() for value in ('INSERT INTO USERS', 'UPDATE ', 'AUDIT_EVENT', 'WORKFLOW_INSTANCE', 'FOREIGN_KEY_CHECKS'))


@pytest.mark.parametrize('damage', ['foreign-schema', 'foreign-key-off', 'incomplete-schema', 'foreign-department', 'employee-collision'])
def test_browser_employee_seed_rejects_foreign_or_existing_rows_before_writing(damage):
    database = EmployeeDateDatabase(damage)
    with pytest.raises(RuntimeError):
        scenarios.seed_employee_hire_date_fixture(database, 'doorhandle' if damage == 'foreign-schema' else SCHEMA, TOKEN, 90)
    assert database.writes == []


@pytest.mark.parametrize('damage', ['bound', 'normalized'])
def test_browser_employee_seed_checks_actual_legacy_text_and_absent_account_binding(damage):
    database = EmployeeDateDatabase(damage)
    with pytest.raises(RuntimeError, match='persisted unbound and unchanged'):
        scenarios.seed_employee_hire_date_fixture(database, SCHEMA, TOKEN, 90)


@pytest.fixture
def original_runtime(tmp_path, monkeypatch):
    # The test runner can be PID 1 in its disposable container. Runtime's real
    # supervisor runs on the ECS host and must have a non-init kernel identity.
    supervisor_pid = 4321
    monkeypatch.setattr(runtime, 'os', SimpleNamespace(**{**vars(os), 'getpid': lambda: supervisor_pid}))
    attempt = tmp_path / 'original'; attempt.mkdir()
    context = dict(schemaVersion=1, kind='doorhandle-compact-runtime-acceptance', release='ci-224-' + 'a' * 12,
        commit='a' * 40, sourceSha256='b' * 64, identity={'instanceId': 'i-runtime', 'machineId': 'c' * 32},
        acceptanceProfileSha256='d' * 64, candidateBuildSha256='e' * 64)
    progress = []
    def write(path, value):
        path.write_text(json.dumps(value), encoding='utf8'); path.chmod(0o600)
    def read(path): return json.loads(path.read_text()), runtime.sha_file(path)
    instance = SimpleNamespace(attempt=attempt, runtime=tmp_path / 'deployed', args=SimpleNamespace(tag=context['release']),
        build={'settingsSha256': 'f' * 64}, public_file=attempt / 'runtime-acceptance.json', context=lambda: context,
        common=SimpleNamespace(write_json=write), guard=SimpleNamespace(read_private=read),
        transport=SimpleNamespace(supervisor_start=lambda _: '1234', progress=progress.append))
    def complete(initial, status='PASS'):
        if status == 'PASS':
            write(instance.public_file, {**context, 'status': 'PASS'})
            result = dict(status='PASS', release=instance.args.tag, runtimeScenarios=9, ownedCleanup='STOPPED',
                          runtimeReceiptSha256=runtime.sha_file(instance.public_file))
        else: result = dict(status='FAILED_OR_UNKNOWN', release=instance.args.tag, errorType='KeyboardInterrupt')
        runtime.finish_runtime_execution(instance, initial, status, result)
    return SimpleNamespace(instance=instance, write=write, complete=complete, progress=progress,
                           supervisor_pid=supervisor_pid)


def test_runtime_supervision_records_current_identity_and_never_replays_an_existing_operation(original_runtime):
    ctx = original_runtime; value = runtime.begin_runtime_execution(ctx.instance)
    assert value['supervisor']['pid'] == ctx.supervisor_pid > 1 and value['supervisor']['startTicks'] == '1234'
    assert runtime.runtime_execution(ctx.instance) == value
    assert value['operation'] == 'runtime-acceptance' and value['status'] == 'RUNNING'
    with pytest.raises(ValueError, match='do not replay'): runtime.begin_runtime_execution(ctx.instance)


@pytest.mark.parametrize('status', ['PASS', 'FAILED'])
def test_runtime_reconnection_reads_original_result_without_starting_or_cleaning_anything(original_runtime, monkeypatch, status):
    ctx = original_runtime; initial = runtime.begin_runtime_execution(ctx.instance); ctx.complete(initial, status)
    before = {str(p): p.read_bytes() for p in ctx.instance.attempt.iterdir()}
    monkeypatch.setattr(runtime.Runtime, 'run', lambda *_: pytest.fail('observation restarted runtime'))
    monkeypatch.setattr(runtime.Runtime, 'cleanup', lambda *_: pytest.fail('observation cancelled runtime'))
    result = runtime.observe_runtime_execution(ctx.instance)
    assert result['status'] == ('PASS' if status == 'PASS' else 'FAILED_OR_UNKNOWN') and result['terminal'] is True
    assert result['executionId'] == initial['executionId']
    assert before == {str(p): p.read_bytes() for p in ctx.instance.attempt.iterdir()}


@pytest.mark.parametrize('field', ['commit', 'sourceSha256', 'identity', 'candidateBuildSha256', 'runtime',
    'settingsSha256', 'operation', 'executionId', 'boot'])
def test_runtime_observation_refuses_another_execution_identity(original_runtime, field):
    ctx = original_runtime; value = runtime.begin_runtime_execution(ctx.instance)
    if field == 'boot': value['supervisor']['bootId'] = 'other-boot'
    else: value[field] = 'other-execution'
    ctx.write(runtime.runtime_execution_file(ctx.instance), value)
    with pytest.raises(ValueError): runtime.observe_runtime_execution(ctx.instance)
    assert not ctx.instance.public_file.exists()


def test_runtime_observation_refuses_a_reused_supervisor_pid_without_cleanup(original_runtime):
    ctx = original_runtime; runtime.begin_runtime_execution(ctx.instance)
    ctx.instance.transport.supervisor_start = lambda _: '5678'
    with pytest.raises(ValueError, match='without terminal evidence'): runtime.observe_runtime_execution(ctx.instance)


def test_runtime_dead_supervisor_without_terminal_receipt_stays_unknown(original_runtime):
    ctx = original_runtime; runtime.begin_runtime_execution(ctx.instance)
    def absent(_): raise FileNotFoundError('original process exited')
    ctx.instance.transport.supervisor_start = absent
    with pytest.raises(ValueError, match='retain owned resources'): runtime.observe_runtime_execution(ctx.instance)
    assert runtime.runtime_execution(ctx.instance)['status'] == 'RUNNING'


def test_runtime_observer_follows_the_same_live_operation_until_its_terminal_receipt(original_runtime, monkeypatch):
    ctx = original_runtime; initial = runtime.begin_runtime_execution(ctx.instance); sleeps = []
    def finish(seconds): sleeps.append(seconds); ctx.complete(initial)
    monkeypatch.setattr(runtime.time, 'sleep', finish)
    result = runtime.observe_runtime_execution(ctx.instance)
    assert sleeps == [5] and result['executionId'] == initial['executionId'] and result['status'] == 'PASS'
    assert ctx.progress[0]['status'] == 'RUNNING' and ctx.progress[0]['terminal'] is False


def test_runtime_observer_rechecks_terminal_publication_when_supervisor_exits(original_runtime):
    ctx = original_runtime; initial = runtime.begin_runtime_execution(ctx.instance)
    def finish(_):
        ctx.complete(initial, 'FAILED')
        raise FileNotFoundError('original process just exited')
    ctx.instance.transport.supervisor_start = finish
    assert runtime.observe_runtime_execution(ctx.instance)['status'] == 'FAILED_OR_UNKNOWN'


@pytest.mark.parametrize('damage', ['missing', 'changed', 'different-source'])
def test_runtime_observation_cannot_accept_pass_without_original_complete_public_proof(original_runtime, damage):
    ctx = original_runtime; initial = runtime.begin_runtime_execution(ctx.instance); ctx.complete(initial)
    if damage == 'missing': ctx.instance.public_file.unlink()
    elif damage == 'changed': ctx.instance.public_file.write_bytes(b'changed original')
    else:
        proof = {**ctx.instance.context(), 'status': 'PASS', 'commit': '9' * 40}; ctx.write(ctx.instance.public_file, proof)
        path = runtime.runtime_execution_file(ctx.instance); value = runtime.runtime_execution(ctx.instance)
        value['result']['runtimeReceiptSha256'] = runtime.sha_file(ctx.instance.public_file); ctx.write(path, value)
    with pytest.raises((ValueError, FileNotFoundError)): runtime.observe_runtime_execution(ctx.instance)


def test_runtime_observation_timeout_neither_cancels_nor_forges_a_terminal_state(original_runtime, monkeypatch):
    ctx = original_runtime; value = runtime.begin_runtime_execution(ctx.instance)
    value['startedAtUnix'] = runtime.time.time() - (240 * 60 + 121)
    ctx.write(runtime.runtime_execution_file(ctx.instance), value)
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: 0)
    with pytest.raises(ValueError, match='timed out'): runtime.observe_runtime_execution(ctx.instance)
    assert runtime.runtime_execution(ctx.instance)['status'] == 'RUNNING'


@pytest.mark.parametrize('seconds', [900, 1800, 3600])
def test_manual_window_extends_only_the_original_fixed_observation_deadline(original_runtime, monkeypatch, seconds):
    ctx = original_runtime; ctx.instance.args.manual_acceptance_seconds = seconds
    initial = runtime.begin_runtime_execution(ctx.instance)
    assert initial['manualAcceptanceSeconds'] == seconds
    initial['startedAtUnix'] = runtime.time.time() - (240 * 60 + 121)
    ctx.write(runtime.runtime_execution_file(ctx.instance), initial)
    sleeps = []
    def finish(delay): sleeps.append(delay); ctx.complete(initial)
    monkeypatch.setattr(runtime.time, 'sleep', finish)
    assert runtime.observe_runtime_execution(ctx.instance)['status'] == 'PASS' and sleeps == [5]
    # A reconnect after the fixed extension cannot renew the same execution.
    initial['startedAtUnix'] = runtime.time.time() - (240 * 60 + seconds + 121)
    ctx.write(runtime.runtime_execution_file(ctx.instance), initial)
    with pytest.raises(ValueError, match='timed out'): runtime.observe_runtime_execution(ctx.instance)
    assert runtime.runtime_execution(ctx.instance)['status'] == 'RUNNING'


@pytest.mark.parametrize('seconds', [True, -900, 60, '900'])
def test_runtime_execution_rejects_an_invalid_manual_extension(original_runtime, seconds):
    ctx = original_runtime; value = runtime.begin_runtime_execution(ctx.instance)
    value['manualAcceptanceSeconds'] = seconds
    ctx.write(runtime.runtime_execution_file(ctx.instance), value)
    with pytest.raises(ValueError, match='manual acceptance duration'): runtime.runtime_execution(ctx.instance)


def runtime_arguments(phase):
    return ['runtime', phase, '--root', '/home/ci', '--runtime', '/home/runtime', '--tag', 'ci-224-' + 'a' * 12,
        '--commit', 'a' * 40, '--source-sha256', 'b' * 64, '--instance-id', 'i-runtime',
        '--machine-id', 'c' * 32, '--settings', '/home/private/settings.json']


def test_runtime_observation_error_cannot_fall_through_main_destructive_failure_cleanup(monkeypatch, capsys):
    def forbidden(*_): pytest.fail('read-only observation attempted cleanup/write')
    instance = SimpleNamespace(owner={'phase': 'RUNNING'}, cleanup=forbidden, save=forbidden, failure=forbidden)
    monkeypatch.setattr(runtime, 'Runtime', lambda _: instance)
    monkeypatch.setattr(runtime, 'observe_runtime_execution', lambda _: (_ for _ in ()).throw(ValueError('unresolved original')))
    monkeypatch.setattr(runtime.sys, 'argv', runtime_arguments('observe'))
    monkeypatch.setattr(runtime.signal, 'signal', lambda *_: None)
    assert runtime.main() == 2 and json.loads(capsys.readouterr().out)['status'] == 'UNKNOWN'


@pytest.mark.parametrize('phase', ['manual-status', 'manual-decision'])
def test_manual_control_failure_cannot_clean_up_the_original_running_candidate(monkeypatch, capsys, phase):
    def forbidden(*_): pytest.fail('manual observer attempted original-owner cleanup/write')
    instance = SimpleNamespace(owner={'phase': 'WAITING_FOR_MANUAL_ACCEPTANCE'}, cleanup=forbidden, save=forbidden, failure=forbidden)
    instance.manual = SimpleNamespace(decide=forbidden)
    monkeypatch.setattr(runtime, 'Runtime', lambda _: instance)
    monkeypatch.setattr(runtime, 'runtime_execution_file', lambda _: (_ for _ in ()).throw(ValueError('unresolved original')))
    monkeypatch.setattr(runtime, 'runtime_execution', lambda _: (_ for _ in ()).throw(ValueError('unresolved original')))
    monkeypatch.setattr(runtime.sys, 'stdin', SimpleNamespace(buffer=SimpleNamespace(read=lambda _: b'{}')))
    monkeypatch.setattr(runtime.sys, 'argv', runtime_arguments(phase))
    monkeypatch.setattr(runtime.signal, 'signal', lambda *_: None)
    assert runtime.main() == 2 and json.loads(capsys.readouterr().out)['status'] == 'UNKNOWN'


def test_explicit_runtime_interrupt_keeps_owned_cleanup_before_failed_terminal_publication(monkeypatch):
    events = []
    def interrupted(): events.append('run'); raise KeyboardInterrupt()
    instance = SimpleNamespace(owner={'phase': 'RUNNING'}, run=interrupted, save=lambda _: events.append('save'),
        cleanup=lambda: events.append('cleanup'), failure=lambda *_: events.append('failure') or 'a' * 64,
        transport=SimpleNamespace(progress=lambda _: None))
    monkeypatch.setattr(runtime, 'Runtime', lambda _: instance)
    monkeypatch.setattr(runtime, 'begin_runtime_execution', lambda _: {'executionId': 'a' * 32})
    monkeypatch.setattr(runtime, 'finish_runtime_execution', lambda *a: events.append(a[2]))
    monkeypatch.setattr(runtime.sys, 'argv', runtime_arguments('run'))
    monkeypatch.setattr(runtime.signal, 'signal', lambda *_: None)
    assert runtime.main() == 2 and events == ['run', 'save', 'cleanup', 'failure', 'FAILED']


@pytest.fixture
def runtime_cancel(original_runtime, monkeypatch):
    ctx = original_runtime
    initial = runtime.begin_runtime_execution(ctx.instance)
    events = []
    monkeypatch.setattr(runtime.os, 'pidfd_open', lambda pid, flags: events.append(('pin', pid, flags)) or 91, raising=False)
    monkeypatch.setattr(runtime.os, 'close', lambda fd: events.append(('close', fd)))
    monkeypatch.setattr(runtime.os, 'kill', lambda *_: pytest.fail('numeric PID signal is forbidden'))
    monkeypatch.setattr(runtime.signal, 'pidfd_send_signal', lambda fd, sig: events.append(('signal', fd, sig)), raising=False)
    ctx.instance.transport.supervisor_start = lambda pid: events.append(('identity', pid)) or initial['supervisor']['startTicks']
    return SimpleNamespace(ctx=ctx, initial=initial, events=events)


def test_runtime_cancel_pins_and_signals_only_the_bound_supervisor_without_touching_receipts(runtime_cancel):
    ctx, initial, events = runtime_cancel.ctx, runtime_cancel.initial, runtime_cancel.events
    before = {p.name: p.read_bytes() for p in ctx.instance.attempt.iterdir()}
    result = runtime.cancel_runtime_execution(ctx.instance)
    assert events == [('pin', ctx.supervisor_pid, 0), ('identity', ctx.supervisor_pid),
                      ('signal', 91, runtime.signal.SIGTERM), ('close', 91)]
    assert result == {**ctx.instance.context(), 'operation': 'runtime-acceptance-cancellation',
        'executionId': initial['executionId'], 'supervisor': initial['supervisor'],
        'runtime': initial['runtime'], 'settingsSha256': initial['settingsSha256'], 'requestedSignal': 'SIGTERM',
        'status': 'SIGNAL_SENT', 'terminal': False, 'runtimeStatus': None, 'signalSent': True}
    assert before == {p.name: p.read_bytes() for p in ctx.instance.attempt.iterdir()}


def test_repeated_runtime_cancel_rebinds_each_signal_and_never_forges_terminal(runtime_cancel):
    for _ in range(2):
        assert runtime.cancel_runtime_execution(runtime_cancel.ctx.instance)['status'] == 'SIGNAL_SENT'
    assert runtime_cancel.events.count(('pin', runtime_cancel.ctx.supervisor_pid, 0)) == 2
    assert runtime_cancel.events.count(('signal', 91, runtime.signal.SIGTERM)) == 2
    assert runtime.runtime_execution(runtime_cancel.ctx.instance) == runtime_cancel.initial


@pytest.mark.parametrize('status', ['PASS', 'FAILED'])
def test_runtime_cancel_accepts_only_original_verified_terminal_without_signalling(runtime_cancel, status):
    ctx = runtime_cancel.ctx; ctx.complete(runtime_cancel.initial, status)
    result = runtime.cancel_runtime_execution(ctx.instance)
    assert result['status'] == 'ALREADY_TERMINAL' and result['terminal'] is True and result['signalSent'] is False
    assert result['runtimeStatus'] == ('PASS' if status == 'PASS' else 'FAILED_OR_UNKNOWN')
    assert runtime_cancel.events == []


@pytest.mark.parametrize('field', ['release', 'commit', 'sourceSha256', 'identity', 'acceptanceProfileSha256',
    'candidateBuildSha256', 'runtime', 'settingsSha256', 'operation', 'executionId', 'boot'])
def test_runtime_cancel_refuses_foreign_execution_before_any_signal(runtime_cancel, field):
    ctx = runtime_cancel.ctx; value = dict(runtime_cancel.initial)
    if field == 'boot': value['supervisor'] = dict(value['supervisor'], bootId='foreign-boot')
    else: value[field] = 'foreign-operation'
    ctx.write(runtime.runtime_execution_file(ctx.instance), value)
    with pytest.raises(ValueError): runtime.cancel_runtime_execution(ctx.instance)
    assert runtime_cancel.events == []


def test_runtime_cancel_refuses_reused_pid_and_closes_its_pinned_descriptor(runtime_cancel):
    runtime_cancel.ctx.instance.transport.supervisor_start = lambda _: '5678'
    with pytest.raises(ValueError, match='supervisor identity changed'):
        runtime.cancel_runtime_execution(runtime_cancel.ctx.instance)
    assert runtime_cancel.events == [('pin', runtime_cancel.ctx.supervisor_pid, 0), ('close', 91)]


def test_runtime_cancel_requires_pidfd_instead_of_falling_back_to_numeric_kill(runtime_cancel, monkeypatch):
    monkeypatch.delattr(runtime.os, 'pidfd_open')
    with pytest.raises(ValueError, match='pidfd support'): runtime.cancel_runtime_execution(runtime_cancel.ctx.instance)
    assert runtime_cancel.events == []


@pytest.mark.parametrize('where', ['pin', 'identity', 'signal'])
@pytest.mark.parametrize('terminal', [False, True])
def test_runtime_cancel_handles_supervisor_exit_only_with_original_terminal_evidence(runtime_cancel, monkeypatch, where, terminal):
    ctx = runtime_cancel.ctx
    def exited(*_):
        if terminal: ctx.complete(runtime_cancel.initial, 'FAILED')
        raise ProcessLookupError('original exited')
    if where == 'pin': monkeypatch.setattr(runtime.os, 'pidfd_open', exited)
    elif where == 'identity': ctx.instance.transport.supervisor_start = exited
    else: monkeypatch.setattr(runtime.signal, 'pidfd_send_signal', exited)
    if terminal:
        result = runtime.cancel_runtime_execution(ctx.instance)
        assert result['status'] == 'ALREADY_TERMINAL' and result['runtimeStatus'] == 'FAILED_OR_UNKNOWN'
    else:
        with pytest.raises(ValueError, match='without terminal evidence'): runtime.cancel_runtime_execution(ctx.instance)
        assert runtime.runtime_execution(ctx.instance)['status'] == 'RUNNING'
    if where == 'pin': assert runtime_cancel.events == []
    else: assert ('close', 91) in runtime_cancel.events


def test_runtime_cancel_rechecks_execution_after_pin_before_sending(runtime_cancel, monkeypatch):
    ctx = runtime_cancel.ctx
    def changed(pid, flags):
        ctx.write(runtime.runtime_execution_file(ctx.instance), dict(runtime_cancel.initial, executionId='9' * 32))
        return 91
    monkeypatch.setattr(runtime.os, 'pidfd_open', changed)
    with pytest.raises(ValueError, match='execution changed'): runtime.cancel_runtime_execution(ctx.instance)
    assert not any(event[0] == 'signal' for event in runtime_cancel.events)
    assert runtime_cancel.events[-1] == ('close', 91)


@pytest.mark.parametrize('damage', ['missing', 'changed', 'foreign-source'])
def test_runtime_cancel_never_treats_unproven_pass_as_terminal(runtime_cancel, damage):
    ctx = runtime_cancel.ctx; ctx.complete(runtime_cancel.initial)
    if damage == 'missing': ctx.instance.public_file.unlink()
    elif damage == 'changed': ctx.instance.public_file.write_bytes(b'changed')
    else:
        ctx.write(ctx.instance.public_file, {**ctx.instance.context(), 'status': 'PASS', 'commit': '9' * 40})
        value = runtime.runtime_execution(ctx.instance)
        value['result']['runtimeReceiptSha256'] = runtime.sha_file(ctx.instance.public_file)
        ctx.write(runtime.runtime_execution_file(ctx.instance), value)
    with pytest.raises((ValueError, FileNotFoundError)): runtime.cancel_runtime_execution(ctx.instance)
    assert runtime_cancel.events == []


def test_runtime_cancel_control_error_cannot_fall_through_owner_cleanup(monkeypatch, capsys):
    def forbidden(*_): pytest.fail('cancel control attempted original-owner cleanup/write')
    instance = SimpleNamespace(owner={'phase': 'RUNNING'}, cleanup=forbidden, save=forbidden, failure=forbidden)
    monkeypatch.setattr(runtime, 'Runtime', lambda _: instance)
    monkeypatch.setattr(runtime, 'cancel_runtime_execution', lambda _: (_ for _ in ()).throw(ValueError('foreign original')))
    monkeypatch.setattr(runtime.sys, 'argv', runtime_arguments('cancel'))
    monkeypatch.setattr(runtime.signal, 'signal', lambda *_: None)
    assert runtime.main() == 2 and json.loads(capsys.readouterr().out)['status'] == 'UNKNOWN'


@pytest.mark.parametrize('status', ['SIGNAL_SENT', 'ALREADY_TERMINAL'])
def test_runtime_cancel_cli_reports_ack_without_running_observing_or_cleaning(runtime_cancel, monkeypatch, status):
    instance = runtime_cancel.ctx.instance
    expected = {'status': status, 'terminal': status == 'ALREADY_TERMINAL'}
    monkeypatch.setattr(runtime, 'Runtime', lambda _: instance)
    monkeypatch.setattr(runtime, 'cancel_runtime_execution', lambda _: expected)
    monkeypatch.setattr(runtime.sys, 'argv', runtime_arguments('cancel'))
    monkeypatch.setattr(runtime.signal, 'signal', lambda *_: None)
    assert runtime.main() == 0 and runtime_cancel.ctx.progress == [expected]
    assert runtime.runtime_execution(instance)['status'] == 'RUNNING'


@pytest.mark.parametrize('first_failure', ['SIGTERM', 'ordinary-exception'])
def test_runtime_repeated_term_cannot_interrupt_original_failure_cleanup(monkeypatch, first_failure):
    events, handlers = [], {}
    def run():
        if first_failure == 'SIGTERM': handlers[runtime.signal.SIGTERM](None, None)
        raise ValueError('ordinary failure')
    def cleanup():
        handlers[runtime.signal.SIGTERM](None, None)
        handlers[runtime.signal.SIGINT](None, None)
        events.append('cleanup-complete')
    instance = SimpleNamespace(owner={'phase': 'RUNNING'}, run=run, cleanup=cleanup,
        save=lambda _: events.append('save'), failure=lambda *_: events.append('failure') or 'a' * 64,
        transport=SimpleNamespace(progress=lambda _: None))
    monkeypatch.setattr(runtime, 'Runtime', lambda _: instance)
    monkeypatch.setattr(runtime, 'begin_runtime_execution', lambda _: {'executionId': 'a' * 32})
    monkeypatch.setattr(runtime, 'finish_runtime_execution', lambda *a: events.append(a[2]))
    monkeypatch.setattr(runtime.sys, 'argv', runtime_arguments('run'))
    monkeypatch.setattr(runtime.signal, 'signal', lambda number, handler: handlers.__setitem__(number, handler))
    assert runtime.main() == 2 and events == ['save', 'cleanup-complete', 'failure', 'FAILED']
    assert handlers[runtime.signal.SIGHUP] == runtime.signal.SIG_IGN


def test_runtime_post_guards_cover_the_database_and_tool_dependencies_not_just_runtime_services():
    source = (ROOT / 'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    tools = source.split("if ($Action -in @('PrepareTools', 'CleanupTools'))", 1)[1].split("if ($Action -in @('PrepareFixtures'", 1)[0]
    fixtures = source.split("if ($Action -in @('PrepareFixtures', 'CleanupFixtures'))", 1)[1].split("if ($Action -eq 'VerifyEcs')", 1)[0]
    cleanup = source.split("if ($Action -eq 'CleanupRuntime')", 1)[1].split('$verified = Get-Content', 1)[0]
    assert tools.index('$null=Wait-ExistingRuntime') < tools.index("'$executor' cleanup")
    assert fixtures.index('$null=Wait-ExistingRuntime') < fixtures.index("'$helper' cleanup")
    assert cleanup.index('$null=Wait-ExistingRuntime -Cancel') < cleanup.index('$cleanupArguments')
    assert 'Wait-ExistingRuntime -Cancel' not in tools + fixtures
    run = source.split('$fixtureResources = @{}', 1)[1].split('$runtimeResult =', 1)[0]
    assert '$runtimeExit -eq 255' in run and '$observed=Wait-ExistingRuntime' in run
    assert 'Wait-ExistingRuntime -Cancel' not in run
    observer = source.split('function Wait-ExistingRuntime {', 1)[1].split('function Assert-ControlSourcePackage', 1)[0]
    assert "' observe $binding" in observer and "' run $binding" not in observer
    assert 'param([switch]$Cancel)' in observer and 'if ($Cancel)' in observer
    assert observer.index("' cancel $binding") < observer.index('for ($readback=1;') < observer.index('return $state')
    assert '($Cancel -and $state.executionId -cne $ack.executionId)' in observer
    for binding in ('operation', 'executionId', 'requestedSignal', 'release', 'commit', 'sourceSha256',
                    'candidateBuildSha256', 'runtime', 'runtimeStatus', 'terminal'):
        assert '$ack.' + binding in observer
    assert "@('SIGNAL_SENT','ALREADY_TERMINAL')" in observer
    assert "artifacts/runtime-execution-cancellation.json" in observer
