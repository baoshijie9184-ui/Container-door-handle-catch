"""ECS-run admission tests: a private manifest cannot promote production to a fixture."""
import argparse
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


def migration_loader(monkeypatch, *, scope='ecs-disposable-migration', port=15444, server=SERVER):
    config = {'scope': scope, 'connection': {'port': port}, 'serverUuid': server}
    monkeypatch.setitem(sys.modules, 'compact_migration_runtime',
                        types.SimpleNamespace(load_config=lambda file: (config, IDENTITY, 'd' * 64)))


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
