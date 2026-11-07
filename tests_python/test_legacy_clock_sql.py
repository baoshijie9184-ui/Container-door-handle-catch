"""Historical clock SQL contracts and real MySQL checks; execute on ECS only."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'script/schema'
if str(DIRECTORY) not in sys.path:
    sys.path.insert(0, str(DIRECTORY))
import author_legacy_clock_copy as clock
import author_legacy_clock_schema as schema
from build_compact_schema import split_top_level, without_comments


def test_full_source_row_encoding_includes_every_original_column_and_exact_wall_cast():
    catalog = clock.catalog()
    for name, source in catalog.items():
        value = clock.sidecar(name, 's', catalog)
        for column in source['columns']:
            assert "'" + column + "'," in value
            assert 's.`' + column + '`' in value
        assert 'SHA2(CAST(JSON_OBJECT(' in value
        assert "'sourceSnapshotSha256','__SOURCE_SNAPSHOT_SHA256__'" in value
        assert 'DATE_FORMAT' not in value


def test_checked_in_copies_are_reproducible_source_compilation():
    for filename in clock.COPIES:
        original = (ROOT / 'sql/mysql/compact/copy-fixed-clock' / filename).read_text('utf8')
        compiled = clock.compile_copy(original, filename)
        assert compiled == (ROOT / 'sql/mysql/compact/copy' / filename).read_text('utf8')
        assert '@compact_validation_wall_offset' in compiled
        assert '@compact_source_clock_unresolved' in compiled
        assert 'clock_target.legacy_clock_json<=>' in compiled


def test_original_source_catalog_rejects_an_unreviewed_row_shape(monkeypatch, tmp_path):
    value = json.loads(clock.SCHEMA_FILE.read_text('utf8'))
    name = next(iter(value['tables']))
    source = next(iter(value['tables'][name]['sourceFiles']))
    value['tables'][name]['sourceFiles'][source] = '0' * 64
    path = tmp_path / 'catalog.json'; path.write_text(json.dumps(value), encoding='utf8')
    monkeypatch.setattr(clock, 'SCHEMA_FILE', path)
    with pytest.raises(ValueError, match='Original source DDL changed'):
        clock.catalog()


def mysql(tmp_path):
    specification = importlib.util.spec_from_file_location('clock_mysql_runtime', DIRECTORY / 'compact_migration_runtime.py')
    common = importlib.util.module_from_spec(specification); specification.loader.exec_module(common)
    config, _, _ = common.load_config(Path(os.environ['DOORHANDLE_COMPACT_MIGRATION_CONFIG']))
    assert config['scope'] == 'ecs-disposable-migration'
    # Only session-local temporary data is written; no legacy business table is
    # created, modified, locked or replaced by these protocol probes.
    private = tmp_path / 'private'; private.mkdir(mode=0o700)
    connection = common.Mysql(config, tmp_path)
    connection.admitted_server()
    # The migration account has deliberately read-only grants on the source.
    # Whole-migration acceptance provisions this owned target; temporary probes
    # use its grants and disappear with each client session.
    return connection, config['targetSchema']


@pytest.mark.skipif(os.environ.get('DOORHANDLE_COMPACT_MIGRATION_TESTS') != '1', reason='Explicit admitted ECS MySQL fixture required')
@pytest.mark.parametrize('filename,source_name', [
    ('25-agent-runs.sql', 'agent_research_answer'), ('23-skill-downloads.sql', 'agent_skill_download_lease')])
@pytest.mark.parametrize('unknown,count,refused', [(True, 1, True), (True, 0, False), (False, 1, False)])
def test_mysql_multisource_unknown_nonempty_fails_but_known_offset_remains_supported(tmp_path, filename, source_name, unknown, count, refused):
    connection, database = mysql(tmp_path)
    sql = (ROOT / 'sql/mysql/compact/copy' / filename).read_text('utf8')
    statements = list(split_top_level(without_comments(sql), ';'))
    original = next(value for value in statements if 'OR (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.' + source_name + ')=0' in value)
    guard = original.split()[2]
    token = uuid.uuid4().hex[:10]
    table = 'clock_multisource_' + token
    original = original.replace('`__SOURCE_SCHEMA__`.' + source_name, table)
    setup = 'CREATE TEMPORARY TABLE ' + table + '(id BIGINT PRIMARY KEY);\n'
    if count:
        setup += 'INSERT INTO ' + table + ' VALUES(1);\n'
    setup += 'CREATE TEMPORARY TABLE ' + guard + '(valid INT NOT NULL CHECK(valid=1));\n'
    setup += 'SET @compact_source_clock_unresolved=' + ('1' if unknown else '0') + ';\n'
    command = setup + original + ';\nSELECT JSON_OBJECT(\'admitted\',CAST(\'true\' AS JSON));'
    if refused:
        with pytest.raises(ValueError, match='MySQL operation failed'):
            connection.script(command, database=database, label='clock-refusal')
        evidence = tmp_path / 'private' / (str(connection.sequence).zfill(4) + '-clock-refusal.stderr')
        # Refusing due to syntax, missing tables, authentication or connection
        # errors must never satisfy this test.
        assert 'ERROR 3819' in evidence.read_text('utf8')
    else:
        response = connection.script(command, database=database, label='clock-admission')
        assert json.loads(response.splitlines()[-1])['admitted'] is True


@pytest.mark.skipif(os.environ.get('DOORHANDLE_COMPACT_MIGRATION_TESTS') != '1', reason='Explicit admitted ECS MySQL fixture required')
def test_mysql_json_schema_rejects_extra_keys_and_preserves_raw_null_clock(tmp_path):
    connection, database = mysql(tmp_path)
    source = clock.catalog()['agent_workspace_file']
    contract = schema.source_schema('agent_workspace_file', source)
    valid = {'protocol': clock.PROTOCOL, 'status': 'UNRESOLVED', 'sourceTable': 'agent_workspace_file',
             'sourceKey': {'id': 1}, 'sourceSnapshotSha256': 'a' * 64, 'sourceRowSha256': 'b' * 64,
             'sourceWallTimes': {'created_at': None}}
    malformed = dict(valid, guessedOffset='+00:00')
    query = 'SELECT JSON_OBJECT(\'valid\',JSON_SCHEMA_VALID(' + clock.q(json.dumps(contract)) + ',' + clock.q(json.dumps(valid))
    query += '),\'extra\',JSON_SCHEMA_VALID(' + clock.q(json.dumps(contract)) + ',' + clock.q(json.dumps(malformed)) + '));'
    result = json.loads(connection.script(query, database=database, label='clock-schema').splitlines()[-1])
    assert result == {'valid': 1, 'extra': 0}
