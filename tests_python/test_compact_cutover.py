"""ECS-executed failure contracts for the first compact cutover controller."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'script/docker' / file)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


cutover = load('compact_cutover_contract', 'compact-cutover.py')
schema = load('compact_cutover_schema_contract', 'compact-schema-guard.py')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf8'); path.chmod(0o600)


def verification(tmp_path):
    tag = 'ci-11-' + 'a' * 12
    identity = {'instanceId': 'i-example', 'machineId': 'b' * 32, 'executionLocation': 'ECS'}
    folder = tmp_path / 'verification' / tag
    result = {'status': 'PASS', 'identity': identity, 'fixtureProperties': ['private-fixture'],
              'javaSelection': ['WholeMigrationTest'], 'javaTests': {'passed': 9, 'failed': 0, 'skipped': 0},
              'wholeMigrationRequested': True, 'wholeMigrationTests': {'passed': 3, 'failed': 0, 'skipped': 0}}
    summary = folder / 'checkout/work/ci-evidence/migration.json'
    write(summary, {'status': 'VERIFIED', 'sourceTableCount': 131, 'targetTableCount': 29})
    result['wholeMigrationSummarySha256'] = cutover.sha_file(summary)
    result_file = summary.with_name('receipt.json'); write(result_file, result)
    xml = summary.with_name('java.xml'); xml.write_text('<testsuite tests="9" failures="0"/>')
    files = [('reports/receipt.json', result_file), ('reports/migration.json', summary), ('reports/java.xml', xml)]
    receipt = {'schema': 1, 'kind': 'doorhandle-ecs-ci', 'release': tag, 'commit': 'a' * 40,
               'sourceSha256': 'c' * 64, 'identity': identity, 'scope': 'mysql', 'status': 'PASS',
               'verificationExitCode': 0, 'fixtureReadinessValidated': True,
               'reportFiles': [{'path': name, 'bytes': file.stat().st_size, 'sha256': cutover.sha_file(file)}
                               for name, file in files]}
    file = folder / 'verification-receipt.json'; write(file, receipt)
    return SimpleNamespace(tag=tag, identity=identity, file=file, receipt=receipt, result=result,
                           result_file=result_file, xml=xml)


def admit(tmp_path, fixture):
    return cutover.admitted_verification(tmp_path, fixture.tag, 'a' * 40, 'c' * 64, fixture.identity, schema)


def test_executed_mysql_and_whole_migration_reports_are_bound_to_this_build(tmp_path):
    fixture = verification(tmp_path)
    assert admit(tmp_path, fixture) == cutover.sha_file(fixture.file)


def test_changed_java_report_blocks_cutover_even_when_pass_envelope_is_unchanged(tmp_path):
    fixture = verification(tmp_path); fixture.xml.write_text('<testsuite tests="9" failures="1"/>')
    with pytest.raises(ValueError, match='artifact is missing or changed'):
        admit(tmp_path, fixture)


def test_source_scope_pass_cannot_stand_in_for_executed_database_acceptance(tmp_path):
    fixture = verification(tmp_path); fixture.receipt['scope'] = 'source'; write(fixture.file, fixture.receipt)
    with pytest.raises(ValueError, match='MySQL ECS verification'):
        admit(tmp_path, fixture)


@pytest.mark.parametrize('counts', [{'passed': 0, 'failed': 0, 'skipped': 0},
                                   {'passed': 3, 'failed': 0, 'skipped': 1}])
def test_omitted_whole_migration_cases_cannot_enable_first_cutover(tmp_path, counts):
    fixture = verification(tmp_path); fixture.result['wholeMigrationTests'] = counts
    write(fixture.result_file, fixture.result)
    for item in fixture.receipt['reportFiles']:
        if item['path'] == 'reports/receipt.json':
            item.update(bytes=fixture.result_file.stat().st_size, sha256=cutover.sha_file(fixture.result_file))
    write(fixture.file, fixture.receipt)
    with pytest.raises(ValueError, match='whole-source migration'):
        admit(tmp_path, fixture)


def test_candidate_start_prevents_source_recovery_even_when_no_http_traffic_was_opened():
    instance = object.__new__(cutover.Cutover)
    instance.journal = {'phase': 'FAILED_ACTIVATION_FROZEN', 'activationStarted': True}
    instance.assert_maintenance = lambda: pytest.fail('Source readback or restart must not be attempted')
    with pytest.raises(ValueError, match='compact runtime may have written'):
        instance.recover()
    assert not cutover.may_restore_source(instance.journal)


def test_source_recovery_is_available_before_candidate_start_and_never_implicitly_enabled():
    assert cutover.may_restore_source({'phase': 'MIGRATED', 'activationStarted': False})
    assert not cutover.may_restore_source({'phase': 'ACTIVE', 'activationStarted': False})
    assert not cutover.may_restore_source({'phase': 'MIGRATED'})
    assert not cutover.may_restore_source({'phase': 'SOURCE_RESTORED', 'activationStarted': False})


@pytest.mark.parametrize('action', ['prepare', 'recover'])
@pytest.mark.parametrize('failed_stop', [None, '1' * 64])
def test_partial_source_stop_or_restore_failure_freezes_all_writers_and_reports_unverified_stop(tmp_path, action, failed_stop):
    instance = object.__new__(cutover.Cutover)
    rows = [{'Id': char * 64, 'Config': {'Labels': {'com.docker.compose.service': service}},
             'State': {'Running': True, 'Restarting': False, 'Pid': 12},
             'HostConfig': {'RestartPolicy': {'Name': 'unless-stopped'}}}
            for char, service in (('1', 'backend'), ('2', 'nginx'), ('3', 'mysql'))]
    instance.journal = {'phase': 'PREPARING', 'activationStarted': False, 'sourceSchema': 'old_source',
        'sourceAccountsApproved': True, 'sourceAccounts': [{'user': 'doorhandle', 'host': '%', 'locked': 'N'}],
        'originals': [{'id': row['Id'], 'service': row['Config']['Labels']['com.docker.compose.service']}
                      for row in rows if row['Config']['Labels']['com.docker.compose.service'] != 'mysql']}
    instance.state = tmp_path
    calls = []
    def docker(*args, **kwargs):
        calls.append(args)
        row = next(row for row in rows if row['Id'] == args[-1])
        if args[0] == 'update':
            row['HostConfig']['RestartPolicy']['Name'] = 'no'
        elif args[0] == 'stop':
            if row['Id'] == failed_stop:
                raise RuntimeError('stop unavailable')
            row['State'].update(Running=False, Pid=0)
        return json.dumps([row]).encode()
    instance.ops = SimpleNamespace(docker=docker)
    instance.current = lambda: rows
    instance.sql = lambda *args, **kwargs: '0'
    instance.source_account_rows = lambda: [{'user': 'doorhandle', 'host': '%', 'locked': 'Y'}]
    instance.unexpected_source_writers = lambda: []
    instance.external_source_clients = lambda: []
    instance.event_catalog = lambda: []
    instance.routine_catalog = lambda: []
    instance.persist = lambda phase: instance.journal.update(phase=phase)
    instance.fail_closed(action)
    assert {item[-1] for item in calls if item[0] == 'stop'} == {'1' * 64, '2' * 64}
    assert rows[2]['State']['Running'] is True
    assert instance.journal['failureFreeze']['confirmed'] is (failed_stop is None)
    assert instance.journal['phase'].endswith('_FROZEN' if failed_stop is None else '_NEEDS_REVIEW')


def test_source_root_credential_is_never_locked_or_unlocked():
    instance = object.__new__(cutover.Cutover)
    instance.journal = {'sourceAccounts': [{'user': 'root', 'host': '%', 'locked': 'N'}]}
    instance.sql = lambda *args, **kwargs: pytest.fail('Maintenance root must remain available')
    with pytest.raises(ValueError, match='cannot be safely fenced'):
        instance.fence_accounts()
