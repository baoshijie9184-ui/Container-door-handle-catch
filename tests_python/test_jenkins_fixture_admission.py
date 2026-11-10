"""ECS-run admission tests: a private manifest cannot promote production to a fixture."""
import argparse
import builtins
from contextlib import nullcontext
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'script/jenkins/verify-ecs.py'
spec = importlib.util.spec_from_file_location('jenkins_fixture_admission', SOURCE)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)
IDENTITY = {'instanceId': 'i-fixture', 'machineId': 'a' * 32, 'executionLocation': 'ECS'}
SERVER = '12345678-1234-1234-1234-123456789abc'


def plan(tmp_path, monkeypatch, *, java_only=False):
    monkeypatch.setattr(verifier, 'ROOT', tmp_path)
    private = tmp_path / 'work' / 'private'
    private.mkdir(parents=True)
    data = private / 'mysql-data'
    data.mkdir()
    properties = {}
    for role, suffix in [('source', 'b' * 10), ('mysql', 'c' * 10)]:
        database = 'doorhandle_detection_verify_' + suffix
        file = private / (role + '.json')
        config = {'scope': 'ecs-disposable-mysql', **{key: IDENTITY[key] for key in ('instanceId', 'machineId')},
                  'database': database, 'port': 15444, 'username': 'ecsit_' + suffix, 'password': 'fixture-only-value',
                  'serverUuid': SERVER, 'dataDirectory': str(data),
                  'url': f'jdbc:mysql://127.0.0.1:15444/{database}?sslMode=DISABLED&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai'}
        file.write_text(json.dumps(config), encoding='utf8')
        properties['detection.identity.' + role + '.config'] = str(file)
    migration = private / 'migration.json'
    migration.write_text('{}', encoding='utf8')
    manifest = {'version': 1, 'javaTests': ['IdentityMigrationMySqlTest'], 'fixtureProperties': properties,
                'javaOnly': java_only, 'migrationConfig': str(migration)}
    file = private / 'manifest.json'
    file.write_text(json.dumps(manifest), encoding='utf8')
    args = argparse.Namespace(fixture_manifest=file, java_tests=None, fixture_property=[], java_only=False)
    return args, manifest, file


def migration_loader(monkeypatch, *, scope='ecs-disposable-migration', port=15444, server=SERVER, data_directory=None):
    def load(file):
        config = {'scope': scope, 'connection': {'port': port}, 'serverUuid': server,
                  'dataDirectory': data_directory or str(file.parent / 'mysql-data'),
                  'sourceSchema': 'doorhandle_legacy_verify_' + 'd' * 10,
                  'targetSchema': 'doorhandle_compact_candidate_' + 'e' * 10,
                  'recoverySchemas': {'source': 'doorhandle_legacy_restore_' + 'f' * 10,
                                      'target': 'doorhandle_compact_restore_' + 'a' * 10}}
        return config, IDENTITY, 'd' * 64
    monkeypatch.setitem(sys.modules, 'compact_migration_runtime',
                        types.SimpleNamespace(load_config=load))


def test_production_migration_config_cannot_enter_disposable_acceptance(tmp_path, monkeypatch):
    args, _, _ = plan(tmp_path, monkeypatch)
    migration_loader(monkeypatch, scope='production-migration')
    with pytest.raises(ValueError, match='same explicitly admitted disposable MySQL'):
        verifier.fixture_arguments(args, IDENTITY)


def test_java_only_cannot_claim_whole_migration_acceptance(tmp_path, monkeypatch):
    args, _, _ = plan(tmp_path, monkeypatch, java_only=True)
    with pytest.raises(ValueError, match='requires Python execution'):
        verifier.fixture_arguments(args, IDENTITY)


@pytest.mark.parametrize('change', [{'port': 3306}, {'server': '22345678-1234-1234-1234-123456789abc'}])
def test_whole_copy_and_java_fixtures_cannot_use_different_servers(tmp_path, monkeypatch, change):
    args, _, _ = plan(tmp_path, monkeypatch)
    migration_loader(monkeypatch, **change)
    with pytest.raises(ValueError, match='same explicitly admitted disposable MySQL'):
        verifier.fixture_arguments(args, IDENTITY)


def test_an_identity_copy_cannot_omit_the_source_binding(tmp_path, monkeypatch):
    args, manifest, file = plan(tmp_path, monkeypatch)
    del manifest['fixtureProperties']['detection.identity.source.config']
    file.write_text(json.dumps(manifest), encoding='utf8')
    with pytest.raises(ValueError, match='matching configuration'):
        verifier.fixture_arguments(args, IDENTITY)


def test_bound_whole_migration_is_explicit_and_preserves_java_scope(tmp_path, monkeypatch):
    args, manifest, _ = plan(tmp_path, monkeypatch)
    migration_loader(monkeypatch)
    arguments, selected, receipt = verifier.fixture_arguments(args, IDENTITY)
    assert selected == ['IdentityMigrationMySqlTest']
    assert set(value[2:].split('=', 1)[0] for value in arguments) == set(manifest['fixtureProperties'])
    assert args.compact_migration_config == manifest['migrationConfig']
    assert receipt['version'] == 1 and len(receipt['sha256']) == 64


def version_two(tmp_path, monkeypatch):
    args, old, file = plan(tmp_path, monkeypatch)
    first = {'javaTests': ['com.ruanzhu.doorhandle.module.detection.service.IdentityMigrationMySqlTest'],
             'fixtureProperties': old['fixtureProperties']}
    second_properties = {}
    for role, suffix in [('source', 'd' * 10), ('mysql', 'e' * 10)]:
        original = Path(old['fixtureProperties']['detection.identity.' + role + '.config'])
        config = json.loads(original.read_text())
        config['database'] = 'doorhandle_detection_verify_' + suffix
        config['username'] = 'ecsit_' + suffix
        config['url'] = f"jdbc:mysql://127.0.0.1:15444/{config['database']}?sslMode=DISABLED&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai"
        path = original.with_name('digest-' + role + '.json')
        path.write_text(json.dumps(config), encoding='utf8')
        second_properties['doorhandle.digest.copy.' + role + '.config'] = str(path)
    second = {'javaTests': ['com.ruanzhu.doorhandle.module.detection.service.DigestCopyMigrationMySqlTest'],
              'fixtureProperties': second_properties}
    manifest = {'version': 2, 'javaSuites': [first, second], 'sourceRegression': True,
                'wholeMigrationConfig': old['migrationConfig']}
    file.write_text(json.dumps(manifest), encoding='utf8')
    return args, manifest, file


def test_v2_keeps_each_suite_properties_separate_and_records_one_global_class_scope(tmp_path, monkeypatch):
    args, manifest, _ = version_two(tmp_path, monkeypatch)
    migration_loader(monkeypatch)
    arguments, selected, proof = verifier.fixture_arguments(args, IDENTITY)
    assert proof['version'] == 2 and args.source_regression is True
    assert args.compact_migration_config == manifest['wholeMigrationConfig']
    assert selected == [item['javaTests'][0] for item in manifest['javaSuites']]
    assert [suite['id'] for suite in args.java_suites] == ['suite-001', 'suite-002']
    for admitted, configured in zip(args.java_suites, manifest['javaSuites']):
        assert admitted['fixtureOptions'] == ['-D' + key + '=' + value for key, value in configured['fixtureProperties'].items()]
        assert admitted['javaSelection'] == configured['javaTests']
    assert len(arguments) == 4  # Compatibility aggregate is never the Maven invocation.


def worker_version_two(tmp_path, monkeypatch):
    args, manifest, file = version_two(tmp_path, monkeypatch)
    suffix = 'f' * 10
    database = 'doorhandle_worker_verify_' + suffix
    config = {'scope': 'ecs-disposable-mysql', **{key: IDENTITY[key] for key in ('instanceId', 'machineId')},
              'database': database, 'username': 'ecsit_' + suffix, 'password': 'synthetic-worker-only',
              'port': 15444, 'serverUuid': SERVER, 'dataDirectory': str(file.parent / 'mysql-data'),
              'url': f'jdbc:mysql://127.0.0.1:15444/{database}?sslMode=DISABLED&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai'}
    worker = file.parent / 'worker.json'
    worker.write_text(json.dumps(config), encoding='utf8')
    manifest['workerMysqlConfig'] = str(worker)
    file.write_text(json.dumps(manifest), encoding='utf8')
    return args, manifest, worker, config


def test_v2_worker_admission_loads_only_the_fixed_pure_helper_without_pytest_or_worker_runtime(tmp_path, monkeypatch):
    args, manifest, worker, _ = worker_version_two(tmp_path, monkeypatch)
    migration_loader(monkeypatch)
    pure_helper = verifier.WORKER_FIXTURE_HELPER.resolve(strict=True)
    actual_spec = importlib.util.spec_from_file_location
    loaded_origins, imports = [], []
    def record_spec(name, location, *positional, **keywords):
        specification = actual_spec(name, location, *positional, **keywords)
        loaded_origins.append(Path(specification.origin).resolve(strict=True))
        return specification
    actual_import = builtins.__import__
    def only_stdlib_or_migration_stub(name, globals=None, locals=None, fromlist=(), level=0):
        imports.append(name)
        root = name.partition('.')[0]
        if root not in sys.stdlib_module_names and root != 'compact_migration_runtime':
            raise AssertionError('Host admission attempted a non-stdlib dependency: ' + name)
        return actual_import(name, globals, locals, fromlist, level)
    monkeypatch.setattr(importlib.util, 'spec_from_file_location', record_spec)
    # Keep the import guard local to the host admission call. Pytest already
    # being imported must not let a newly executed test module import it again.
    with monkeypatch.context() as admission:
        admission.setattr(builtins, '__import__', only_stdlib_or_migration_stub)
        arguments, selected, proof = verifier.fixture_arguments(args, IDENTITY)
    assert loaded_origins == [pure_helper]
    assert pure_helper == SOURCE.parent.parent / 'schema/worker_mysql_fixture.py'
    assert not any('pytest' in name or 'detection_worker_receipts' in name for name in imports)
    assert args.worker_mysql_config == str(worker)
    assert args.worker_mysql_config_sha256 == hashlib.sha256(worker.read_bytes()).hexdigest()
    assert args.compact_migration_config == manifest['wholeMigrationConfig'] and proof['version'] == 2
    assert selected == [suite['javaTests'][0] for suite in manifest['javaSuites']] and len(arguments) == 4


@pytest.mark.parametrize(('field', 'replacement'), [('scope', 'production'), ('port', 3306)])
def test_v2_worker_admission_still_refuses_production_or_default_mysql_port(tmp_path, monkeypatch, field, replacement):
    args, _, worker, config = worker_version_two(tmp_path, monkeypatch)
    migration_loader(monkeypatch)
    config[field] = replacement
    worker.write_text(json.dumps(config), encoding='utf8')
    with pytest.raises(ValueError):
        verifier.fixture_arguments(args, IDENTITY)


def test_v2_refuses_simple_and_fully_qualified_aliases_of_one_class(tmp_path, monkeypatch):
    args, manifest, file = version_two(tmp_path, monkeypatch)
    manifest['javaSuites'][1]['javaTests'] = ['IdentityMigrationMySqlTest']
    file.write_text(json.dumps(manifest), encoding='utf8')
    with pytest.raises(ValueError, match='globally unique'):
        verifier.fixture_arguments(args, IDENTITY)


@pytest.mark.parametrize('reuse_file', [True, False])
def test_v2_refuses_cross_suite_schema_reuse_even_with_another_config_filename(tmp_path, monkeypatch, reuse_file):
    args, manifest, file = version_two(tmp_path, monkeypatch)
    first, second = manifest['javaSuites']
    original = Path(first['fixtureProperties']['detection.identity.source.config'])
    key = 'doorhandle.digest.copy.source.config'
    if reuse_file:
        second['fixtureProperties'][key] = str(original)
    else:
        Path(second['fixtureProperties'][key]).write_bytes(original.read_bytes())
    file.write_text(json.dumps(manifest), encoding='utf8')
    with pytest.raises(ValueError, match='distinct private inputs and disposable schemas'):
        verifier.fixture_arguments(args, IDENTITY)


@pytest.mark.parametrize('mutation', ['empty', 'global_properties', 'patterns', 'string_classes', 'unknown_property', 'regression_flag'])
def test_v2_cannot_widen_its_audited_suite_protocol(tmp_path, monkeypatch, mutation):
    args, manifest, file = version_two(tmp_path, monkeypatch)
    if mutation == 'empty':manifest['javaSuites'] = []
    elif mutation == 'global_properties':manifest['fixtureProperties'] = {}
    elif mutation == 'patterns':manifest['javaSuites'][0]['javaTests'] = ['*MySqlTest']
    elif mutation == 'string_classes':manifest['javaSuites'][0]['javaTests'] = 'IdentityMigrationMySqlTest'
    elif mutation == 'unknown_property':manifest['javaSuites'][0]['fixtureProperties']['agent.live.models'] = '/private/file'
    else:manifest['sourceRegression'] = 'true'
    file.write_text(json.dumps(manifest), encoding='utf8')
    with pytest.raises(ValueError):verifier.fixture_arguments(args, IDENTITY)


def test_whole_migration_port_and_uuid_cannot_hide_another_data_directory(tmp_path, monkeypatch):
    args, _, _ = version_two(tmp_path, monkeypatch)
    migration_loader(monkeypatch, data_directory=str(tmp_path / 'another-owned-server'))
    with pytest.raises(ValueError, match='same explicitly admitted disposable MySQL server and storage'):
        verifier.fixture_arguments(args, IDENTITY)


def test_original_xml_bytes_are_preserved_and_duplicate_report_paths_never_overwrite(tmp_path):
    root = tmp_path / 'build'
    report = root / 'module/surefire-reports/TEST-org.example.ExampleTest.xml'
    report.parent.mkdir(parents=True)
    raw = b'<?xml version="1.0"?>\r\n<testsuite name="org.example.ExampleTest"><testcase classname="org.example.ExampleTest" name="actualPass"/></testsuite>\r\n'
    report.write_bytes(raw)
    destination = tmp_path / 'java'
    catalog = verifier.archive_java_reports(root, destination, tmp_path)
    assert (tmp_path / catalog[0]['path']).read_bytes() == raw
    counts, selected = verifier.java_report_counts(tmp_path, catalog, ['org.example.ExampleTest'])
    verifier.require_java_pass(counts, selected, fixture=True)
    report.write_bytes(raw.replace(b'actualPass', b'anotherRun'))
    with pytest.raises(FileExistsError):verifier.archive_java_reports(root, destination, tmp_path)
    assert (tmp_path / catalog[0]['path']).read_bytes() == raw


def test_one_passing_class_cannot_cover_another_missing_or_skipped_class():
    counts = {'found': 2, 'passed': 1, 'failed': 0, 'skipped': 1}
    selected = {'Passed': {'found': 1, 'passed': 1, 'failed': 0, 'skipped': 0},
                'Skipped': {'found': 1, 'passed': 0, 'failed': 0, 'skipped': 1}}
    with pytest.raises(RuntimeError):verifier.require_java_pass(counts, selected, fixture=True)
    with pytest.raises(RuntimeError):verifier.require_java_pass({'found': 1, 'passed': 1, 'failed': 0, 'skipped': 0},
        {**selected, 'Missing': {'found': 0, 'passed': 0, 'failed': 0, 'skipped': 0}}, fixture=True)


def test_a_later_suite_cannot_change_its_admitted_private_database_binding(tmp_path, monkeypatch):
    args, _, _ = version_two(tmp_path, monkeypatch)
    migration_loader(monkeypatch)
    verifier.fixture_arguments(args, IDENTITY)
    references = args.java_suites[1]['privateInputs']
    verifier.require_unchanged_inputs(references)
    path = Path(next(iter(references)))
    config = json.loads(path.read_text())
    config['serverUuid'] = '22345678-1234-1234-1234-123456789abc'
    path.write_text(json.dumps(config), encoding='utf8')
    with pytest.raises(ValueError, match='changed after whole-plan admission'):
        verifier.require_unchanged_inputs(references)


def mysql_control_module(filename, monkeypatch):
    name = 'fixture_binlog_admission_' + filename.replace('-', '_').removesuffix('.py')
    spec = importlib.util.spec_from_file_location(name, SOURCE.with_name(filename))
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('log_bin', [0, 1, None])
def test_disposable_start_disables_binlog_before_suites_and_whole_migration(tmp_path, monkeypatch, log_bin):
    preparer = mysql_control_module('prepare-compact-fixtures.py', monkeypatch)
    controller = object.__new__(preparer.Preparation)
    controller.work = tmp_path / 'fixture'; controller.work.mkdir()
    controller.journal = {'token': 'e' * 24}
    controller.args = types.SimpleNamespace(tag='ci-999-' + 'c' * 12, source_sha256='d' * 64)
    controller.identity = IDENTITY; controller.docker = Path('/usr/bin/docker')
    calls, configs, saved, statements = [], [], [], []
    cid, image = 'b' * 64, 'sha256:' + 'f' * 64
    class AvailablePort:
        def __enter__(self): return self
        def __exit__(self, *unused): return None
        def bind(self, address): assert address == ('127.0.0.1', 0)
        def getsockname(self): return ('127.0.0.1', 15444)
    monkeypatch.setattr(preparer, 'socket', types.SimpleNamespace(socket=AvailablePort))
    def docker(*args, **kwargs):
        calls.append(args)
        if args[:2] == ('image', 'inspect'): return json.dumps([{'Id': image}]).encode()
        assert args[0] == 'run'
        return cid.encode()
    controller.docker_call = docker
    controller.save = saved.append; controller.inspect_owned = lambda: {}
    def query(sql):
        assert "'logBin',@@GLOBAL.log_bin" in sql
        return {'uuid': SERVER, 'version': '8.4.6', 'port': 15444, 'fk': 1,
                'data': str(controller.work / 'mysql-data') + '/', 'logBin': log_bin}
    controller.admin_query = query
    def mysql(config, output):
        configs.append(config)
        return types.SimpleNamespace(admitted_server=lambda: {}, script=lambda sql, **kwargs: statements.append(sql))
    controller.runtime = types.SimpleNamespace(Mysql=mysql, quoted=lambda value: '`' + value + '`')
    if log_bin != 0:
        with pytest.raises(ValueError, match='binary logging must be disabled'):
            controller.start_mysql(image)
        assert not configs and 'MYSQL_READY' not in saved
    else:
        controller.start_mysql(image)
        assert controller.journal['binaryLoggingDisabled'] is True
        controller.journal.update(sourceClone='doorhandle_migration_verify_fixture', sourceCollations={})
        whole = controller.whole_config({'sourceOffsets': {}, 'applicationJarSha256': 'a' * 64}, '/tool/java', '/private/app.jar')
        # Source/target backup restorations are separate schemas on this same
        # checked server, not another unconfigured MySQL container.
        assert whole['client']['containerId'] == configs[0]['client']['containerId'] == cid
        assert whole['serverUuid'] == SERVER and whole['connection']['port'] == 15444
        assert set(whole['recoverySchemas']) == {'source', 'target'}
        assert not any('SUPER' in sql for sql in statements)
    launched = next(row for row in calls if row[0] == 'run')
    assert launched.count('--skip-log-bin') == 1
    assert not any('log-bin-trust-function-creators' in item for item in launched)


@pytest.mark.parametrize('log_bin', [0, 1, None])
def test_independent_sql_recovery_checks_actual_binlog_before_import(tmp_path, monkeypatch, log_bin):
    recovery = mysql_control_module('restore-local-mysql.py', monkeypatch)
    controller = object.__new__(recovery.Recovery)
    controller.directory = tmp_path / 'recovery'; controller.directory.mkdir()
    controller.guard = lambda: None; controller.creation_lock = nullcontext
    node = {'containerId': 'b' * 64}; persisted = []
    controller.create_registered = lambda ordinal: node
    def query(sql):
        assert "'logBin',@@GLOBAL.log_bin" in sql
        return {'uuid': SERVER, 'version': '8.4.6', 'port': 3306, 'events': 'DISABLED',
                'datadir': '/var/lib/mysql/', 'logBin': log_bin}
    client = types.SimpleNamespace(single=query)
    controller.sql_client = lambda cid, output: client
    controller.persist = lambda: persisted.append(True)
    if log_bin != 0:
        with pytest.raises(ValueError, match='binary logging must be disabled'):
            controller.start('a')
        assert not persisted and 'serverUuid' not in node
    else:
        observed, actual = controller.start('a')
        assert actual is client and observed['serverUuid'] == SERVER
        assert observed['binaryLoggingDisabled'] is True and persisted


def test_whole_migration_cannot_use_a_fixture_without_actual_binlog_readback(monkeypatch):
    preparer = mysql_control_module('prepare-compact-fixtures.py', monkeypatch)
    controller = object.__new__(preparer.Preparation); controller.journal = {}
    with pytest.raises(ValueError, match='recovery schemas require the checked binlog-disabled fixture'):
        controller.whole_config({}, '/unused/java', '/unused/app.jar')


def provisioned_profile():
    requirements = json.loads((SOURCE.parent / 'compact-acceptance.json').read_bytes())['javaSuites']
    provisioned = [{'javaTests': [item['className']], 'fixtureProperties': {
        key: '/owned/private/' + item['id'] + '-' + str(number) + '.json'
        for number, key in enumerate(item['fixtureProperties'])}} for item in requirements]
    return requirements, provisioned


def test_actual_profile_batches_all_62_classes_and_original_paths_without_property_collisions(monkeypatch):
    preparer = mysql_control_module('prepare-compact-fixtures.py', monkeypatch)
    requirements, provisioned = provisioned_profile()
    before = json.dumps(provisioned, sort_keys=True)
    groups = preparer.group_provisioned_suites(provisioned, requirements)
    assert len(requirements) == 64 and sum(item['minimumTests'] for item in requirements) == 678
    assert len(groups) == 13 and groups[0] == provisioned[0]
    assert groups[0]['javaTests'] == [requirements[0]['className']]
    original = {item['javaTests'][0]: item['fixtureProperties'] for item in provisioned}
    selected = [name for group in groups for name in group['javaTests']]
    assert len(selected) == len(set(selected)) == 64 and set(selected) == set(original)
    for group in groups:
        assert 1 <= len(group['javaTests']) <= 6
        keys = [key for name in group['javaTests'] for key in original[name]]
        assert len(keys) == len(set(keys)) == len(group['fixtureProperties'])
        assert group['fixtureProperties'] == {key: path for name in group['javaTests'] for key, path in original[name].items()}
    assert json.dumps(provisioned, sort_keys=True) == before


def test_provisioning_keeps_every_original_account_and_migration_grant_before_grouping(monkeypatch):
    preparer = mysql_control_module('prepare-compact-fixtures.py', monkeypatch)
    requirements, _ = provisioned_profile()
    controller = object.__new__(preparer.Preparation)
    controller.registry = preparer.registry(SOURCE.parents[2])
    created, written, grants = [], {}, []
    controller.fixture_config = lambda prefix, account, description: {
        'database': prefix + str(len(created)), 'username': account + str(len(created))}
    controller.create_account = lambda config: created.append(dict(config))
    def write_config(name, config):
        written[name] = dict(config)
        return Path('/owned/private') / (name + '.json')
    controller.write_config = write_config
    controller.runtime = types.SimpleNamespace(quoted=lambda value: '`' + value + '`')
    controller.mysql = types.SimpleNamespace(script=lambda sql, **kwargs: grants.append((sql, kwargs)))
    groups = controller.provision_suites(requirements)
    assert len(groups) == 13 and len(created) == len(written) == sum(len(item['fixtureProperties']) for item in requirements)
    assert len({item['database'] for item in created}) == len(created)
    expected_grants = sum(source in item['fixtureProperties'] or strict and target in item['fixtureProperties']
                          for item in requirements for source, target, strict in controller.registry['MIGRATION_PAIRS'])
    assert len(grants) == expected_grants and all(item[1] == {'label': 'fixture-source-read'} for item in grants)
    assert {path for group in groups for path in group['fixtureProperties'].values()} == {
        str(Path('/owned/private') / (name + '.json')) for name in written}


@pytest.mark.parametrize('mutation', ['missing-class', 'duplicate-class', 'duplicate-private-file', 'extra-property', 'wrong-first-class'])
def test_grouping_refuses_to_change_original_class_or_private_input_coverage(monkeypatch, mutation):
    preparer = mysql_control_module('prepare-compact-fixtures.py', monkeypatch)
    requirements, provisioned = provisioned_profile()
    if mutation == 'missing-class': provisioned.pop()
    elif mutation == 'duplicate-class': provisioned[-1]['javaTests'] = list(provisioned[0]['javaTests'])
    elif mutation == 'duplicate-private-file':
        key = next(iter(provisioned[-1]['fixtureProperties']))
        provisioned[-1]['fixtureProperties'][key] = next(iter(provisioned[0]['fixtureProperties'].values()))
    elif mutation == 'extra-property': provisioned[-1]['fixtureProperties']['unreviewed.config'] = '/owned/private/extra.json'
    else: provisioned[0], provisioned[1] = provisioned[1], provisioned[0]
    with pytest.raises(ValueError):
        preparer.group_provisioned_suites(provisioned, requirements)


def test_v2_grouped_classes_keep_all_original_private_inputs_and_migration_pairs(tmp_path, monkeypatch):
    args, manifest, file = version_two(tmp_path, monkeypatch)
    migration_loader(monkeypatch)
    first, second = manifest['javaSuites']
    manifest['javaSuites'] = [{'javaTests': first['javaTests'] + second['javaTests'],
                             'fixtureProperties': {**first['fixtureProperties'], **second['fixtureProperties']}}]
    file.write_text(json.dumps(manifest), encoding='utf8')
    arguments, selected, _ = verifier.fixture_arguments(args, IDENTITY)
    assert selected == first['javaTests'] + second['javaTests'] and len(args.java_suites) == 1
    assert len(args.java_suites[0]['privateInputs']) == len(arguments) == 4
    assert args.java_suites[0]['fixtureProperties'] == sorted(first['fixtureProperties'] | second['fixtureProperties'])


@pytest.mark.parametrize('shared', ['input-file', 'database'])
def test_grouped_invocation_still_refuses_shared_inputs_or_schemas(tmp_path, monkeypatch, shared):
    args, original, file = plan(tmp_path, monkeypatch)
    first = Path(original['fixtureProperties']['detection.identity.mysql.config'])
    second = first.with_name('same-schema-other-path.json')
    second.write_bytes(first.read_bytes())
    manifest = {'version': 2, 'javaSuites': [{'javaTests': ['AccountIdentityServiceTest', 'QualityDigestMySqlTest'],
        'fixtureProperties': {'doorhandle.operations.mysql.config': str(first),
                              'doorhandle.digest.mysql.config': str(first if shared == 'input-file' else second)}}]}
    file.write_text(json.dumps(manifest), encoding='utf8')
    with pytest.raises(ValueError, match='distinct private inputs and disposable schemas'):
        verifier.fixture_arguments(args, IDENTITY)
