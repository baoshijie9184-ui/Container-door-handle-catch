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
from build_compact_schema import (AFTER_GUARDS, LEGACY_CLOCK_AFTER_BINDINGS, check_columns,
                                  compile_schema, parse_table, split_top_level, without_comments)


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


@pytest.mark.parametrize('expression', [
    "CONVERT_TZ(s.created_at,@compact_validation_wall_offset,'+00:00')",
    "IF(s.used_at IS NULL,NULL,CONVERT_TZ(s.used_at,@compact_validation_wall_offset,'+00:00'))",
    "COALESCE(CONVERT_TZ(s.used_at,@compact_validation_wall_offset,'+00:00'),s.created_at)",
    '@compact_validation_wall_offset',
])
@pytest.mark.parametrize('opening,closing', [('', ''), ('(', ')'), ('( ( ', ' ) )')])
@pytest.mark.parametrize('operator', ['<=>', '=', '<>', '!='])
def test_target_clock_comparisons_normalize_complete_grouped_rhs(expression, opening, closing, operator):
    rhs = opening + expression + closing
    column = 'legacy_utc_offset' if expression == clock.VALIDATION else 'created_at'
    prefix = 'SELECT 1 FROM workflow_instance t WHERE '
    comparison = 't.' + column + '<=>' + clock.normalized(rhs)
    expected = ('NOT(' if operator in ('<>', '!=') else '(') + comparison + ')'
    assert clock.projection_checks(prefix + 't.' + column + operator + rhs, clock.targets()) == prefix + expected


def test_grouped_target_clock_rewrite_preserves_source_guards_raw_times_and_other_columns():
    conversion = "(CONVERT_TZ(s.created_at,@compact_validation_wall_offset,'+00:00'))"
    source = 'SELECT 1 FROM `__SOURCE_SCHEMA__`.detection_report_command s WHERE s.created_at<=>' + conversion
    assert clock.projection_checks(source, clock.targets()) == source
    for column in ('mcp_source_created_at', 'resource_revision'):
        statement = 'SELECT 1 FROM workflow_instance t WHERE t.' + column + '<=>' + conversion
        assert clock.projection_checks(statement, clock.targets()) == statement
    statement = 'SELECT 1 FROM workflow_instance t WHERE BINARY t.`created_at`<=>BINARY ' + conversion
    assert clock.projection_checks(statement, clock.targets()) == (
        'SELECT 1 FROM workflow_instance t WHERE (BINARY t.`created_at`<=>BINARY ' + clock.normalized(conversion) + ')')


def test_original_source_catalog_rejects_an_unreviewed_row_shape(monkeypatch, tmp_path):
    value = json.loads(clock.SCHEMA_FILE.read_text('utf8'))
    name = next(iter(value['tables']))
    source = next(iter(value['tables'][name]['sourceFiles']))
    value['tables'][name]['sourceFiles'][source] = '0' * 64
    path = tmp_path / 'catalog.json'; path.write_text(json.dumps(value), encoding='utf8')
    monkeypatch.setattr(clock, 'SCHEMA_FILE', path)
    with pytest.raises(ValueError, match='Original source DDL changed'):
        clock.catalog()


def test_chat_clock_catalog_uses_original_unsigned_primary_keys_and_complete_rows():
    sources = clock.catalog()
    for name, columns in (
        ('agent_message_execution', ['id', 'user_id', 'session_id', 'message_id', 'run_id', 'created_at']),
        ('agent_workspace_turn_snapshot', ['id', 'user_id', 'session_id', 'message_id', 'snapshot_json', 'snapshot_sha256', 'created_at'])):
        assert sources[name]['primaryKey'] == ['id']
        assert list(sources[name]['columns']) == columns
        assert sources[name]['columns']['id']['type'] == 'BIGINT UNSIGNED'
        value = clock.sidecar(name, 's', sources)
        assert "'sourceKey',JSON_OBJECT('id',s.`id`)" in value
        assert "'sourceWallTimes',JSON_OBJECT('created_at',CAST(s.`created_at` AS CHAR))" in value
    assert not any(v['type'].upper().startswith(('DATETIME', 'TIMESTAMP'))
                   for v in sources['agent_context_turn']['columns'].values())


def test_chat_unknown_projection_never_manufactures_absolute_times_or_offsets():
    text = (ROOT / 'sql/mysql/compact/copy/24-chat-evidence.sql').read_text('utf8')
    for column in ('execution_created_at', 'workspace_snapshot_created_at'):
        assert 'm.' + column + '=IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(' in text
        assert '(m.' + column + '<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(' in text
    assert "'sourceUtcOffset',IF(@compact_source_clock_unresolved,NULL,@compact_validation_wall_offset)" in text
    assert "'createdAtSource',IF(@compact_source_clock_unresolved,CAST(s.created_at AS CHAR),DATE_FORMAT(" in text
    assert "'sourceTable','agent_message_execution'" in text
    assert "'sourceTable','agent_workspace_turn_snapshot'" in text
    assert 'UPDATE chat_message' in text and 'm.execution_legacy_id=s.id' in text


def test_chat_projection_exception_requires_exact_immutable_audit_reference():
    generated, _ = schema.build()
    guards = generated[ROOT / 'sql/mysql/compact/baseline/35-legacy-clock-chat-projection.sql']
    assert 'BEFORE INSERT ON chat_message' in guards and 'BEFORE UPDATE ON chat_message' in guards
    for condition in ('e.message_id=NEW.id', 'BINARY e.session_id=BINARY NEW.session_id',
                      'BINARY e.run_id=BINARY NEW.execution_run_id', 'e.owner_user_id=NEW.execution_owner_user_id',
                      'e.owner_user_id=NEW.snapshot_owner_user_id', "'$.sourceKey.id'", 'e.occurred_at IS NULL'):
        assert condition in guards
    assert 'NEW.execution_created_at IS NOT NULL' in guards
    assert 'NEW.workspace_snapshot_created_at IS NOT NULL' in guards
    audit_guard = generated[ROOT / 'sql/mysql/compact/baseline/35-legacy-clock-audit-event.sql']
    assert 'NOT(BINARY NEW.message_id<=>BINARY OLD.message_id)' in audit_guard
    assert 'NOT(BINARY NEW.payload_json<=>BINARY OLD.payload_json)' in audit_guard
    # A live message is a projection of retained evidence; it is not an audit
    # parent capable of cascading away the original clock sidecar.
    relations = (ROOT / 'sql/mysql/compact/baseline/40-relations.sql').read_text('utf8')
    audit_relations = [part for part in split_top_level(without_comments(relations), ';')
                       if part.startswith('ALTER TABLE audit_event')]
    assert not any('REFERENCES chat_message' in part for part in audit_relations)


def test_chat_changed_wall_expression_is_refused_during_authoring():
    with pytest.raises(ValueError, match='Reviewed chat raw wall source changed'):
        clock.chat_payloads("JSON_OBJECT('createdAtSource',DATE_FORMAT(x.created_at,'%Y-%m-%d'))")


@pytest.mark.parametrize('table', LEGACY_CLOCK_AFTER_BINDINGS)
def test_auto_increment_source_keys_use_final_row_after_guards_and_keep_shape_checks(table):
    generated, bindings = schema.build()
    baseline = generated[ROOT / 'sql/mysql/compact/baseline' / clock.TABLE_FILES[table]]
    assert 'CONSTRAINT ck_legacy_clock_binding_' + table + ' CHECK' not in baseline
    assert 'CONSTRAINT ck_legacy_clock_shape_' + table + ' CHECK' in baseline
    guards = generated[ROOT / 'sql/mysql/compact/baseline' / ('35-legacy-clock-' + table.replace('_', '-') + '.sql')]
    definition = next(statement for statement in split_top_level(without_comments(baseline), ';')
                      if statement.startswith('CREATE TABLE ' + table + ' ('))
    expected = 'legacy_clock_json IS NULL OR COALESCE(('
    expected += ' OR '.join('(' + condition + ')' for condition in sorted({row[1] for row in bindings[table]})) + '),0)=1'
    expected = schema.row_expression(expected, parse_table(definition, clock.TABLE_FILES[table])['columns'])
    # Both insertion and re-keying are checked against the exact original route;
    # explicit source ids and server-assigned ids use the same NEW.id.
    for event in ('INSERT', 'UPDATE'):
        assert 'AFTER ' + event + ' ON ' + table + ' FOR EACH ROW' in guards
    assert guards.count('IF NOT(' + expected + ') THEN') == 2
    assert 'BINARY NEW.id<=>BINARY' in guards
    assert 'BEFORE UPDATE ON ' + table in guards and 'BEFORE DELETE ON ' + table in guards


def test_row_guard_qualification_preserves_json_paths_literals_and_whole_column_names():
    value = "id=CAST(JSON_UNQUOTE(JSON_EXTRACT(legacy_clock_json,'$.sourceKey.id')) AS DECIMAL(20,0)) AND kind='id legacy_clock_json' AND legacy_id=1"
    assert schema.row_expression(value, {'id', 'legacy_clock_json', 'kind'}) == (
        "NEW.id=CAST(JSON_UNQUOTE(JSON_EXTRACT(NEW.legacy_clock_json,'$.sourceKey.id')) AS DECIMAL(20,0)) AND NEW.kind='id legacy_clock_json' AND legacy_id=1")


def test_compiled_schema_has_no_auto_increment_check_reference_and_exact_after_timing():
    _, compiled = compile_schema()
    for table in compiled['tables'].values():
        automatic = {name for name, value in table['columns'].items() if 'AUTO_INCREMENT' in value['declaration'].upper()}
        assert not any(check_columns(field, table['columns']) & automatic for field in table['constraints'])
    after = {trigger['name']: trigger['event'] for trigger in compiled['triggers'] if trigger['timing'] == 'AFTER'}
    assert after == AFTER_GUARDS


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


@pytest.mark.skipif(os.environ.get('DOORHANDLE_COMPACT_MIGRATION_TESTS') != '1', reason='Explicit admitted ECS MySQL fixture required')
@pytest.mark.parametrize('filename,source_name,target,time_column', [
    ('32-agent-journal.sql', 'agent_run_event', 'audit_event', 'occurred_at'),
    ('33-sdk-checkpoint.sql', 'agent_workbench_sdk_state', 'runtime_state', 'updated_at'),
])
@pytest.mark.parametrize('unknown', [False, True])
@pytest.mark.parametrize('change_target_clock', [False, True])
def test_mysql_generated_clock_join_binds_the_source_and_rejects_changed_target_time(
        tmp_path, filename, source_name, target, time_column, unknown, change_target_clock):
    connection, database = mysql(tmp_path)
    catalog = clock.catalog()
    text = (ROOT / 'sql/mysql/compact/copy' / filename).read_text('utf8')
    statements = list(split_top_level(without_comments(text), ';'))
    projection = next(value for value in statements if value.startswith('INSERT INTO ' + target + '(')
                      and ('FROM `__SOURCE_SCHEMA__`.' + source_name) in value)
    reconciliation = next(value for value in statements if 'NOT(clock_target.legacy_clock_json<=>' in value)
    guard = reconciliation.split()[2]
    target_name = 'clock_join_target'
    source_columns = ','.join('`' + key + '` ' + column['type'] for key, column in catalog[source_name]['columns'].items())
    # Reproduce the real shared source/target column names, including the
    # auto-generated audit id. No persistent rows or original SQL are changed;
    # only the exact generated reconciliation guard can reject the corruption.
    target_columns = []
    for name, column in clock.targets()[target]['columns'].items():
        if column['generatedVirtual']:
            continue
        definition = '`' + name + '` ' + column['type']
        if 'AUTO_INCREMENT' in column['declaration'].upper():
            definition += ' AUTO_INCREMENT PRIMARY KEY'
        target_columns.append(definition)
    wall = "'2026-01-02 03:04:05.123456'"
    if source_name == 'agent_run_event':
        values = {'id': '1', 'run_id': "'run-A'", 'user_id': '7', 'sequence_no': '1',
                  'event_type': "'NOTE'", 'occurred_at': wall, 'payload_json': "'{\"message\":\"clock\"}'"}
    else:
        values = {'id': '1', 'user_id': "'7'", 'session_id': "'Case:session'", 'state_key': "'State:key'",
                  'revision': '1', 'state_json': "' { \"value\": 1 } '", 'updated_at': wall}
    command = ('CREATE TEMPORARY TABLE ' + source_name + '(' + source_columns + ');\n'
               'CREATE TEMPORARY TABLE ' + target_name + '(' + ','.join(target_columns) + ');\n'
               'CREATE TEMPORARY TABLE ' + guard + '(valid INT NOT NULL CHECK(valid=1));\n'
               'SET @compact_source_clock_unresolved=' + ('1' if unknown else '0') + ';\n'
               "SET @compact_validation_wall_offset='+08:00';\n"
               'INSERT INTO ' + source_name + '(' + ','.join(values) + ') VALUES(' + ','.join(values.values()) + ');\n')
    projection = projection.replace('INSERT INTO ' + target + '(', 'INSERT INTO ' + target_name + '(')
    reconciliation = reconciliation.replace('LEFT JOIN ' + target + ' clock_target', 'LEFT JOIN ' + target_name + ' clock_target')
    for original in (projection, reconciliation):
        assert ('`__SOURCE_SCHEMA__`.' + source_name) in original
    command += projection.replace('`__SOURCE_SCHEMA__`.', '') + ';\n'
    if change_target_clock:
        changed = wall if unknown else 'TIMESTAMPADD(MICROSECOND,1,' + time_column + ')'
        command += 'UPDATE ' + target_name + ' SET ' + time_column + '=' + changed + ';\n'
    command += reconciliation.replace('`__SOURCE_SCHEMA__`.', '') + ';\n'
    command = command.replace('__SOURCE_SNAPSHOT_SHA256__', 'a' * 64)
    command += ('SELECT JSON_OBJECT(\'sourceRows\',(SELECT COUNT(*) FROM ' + source_name + '),'
                "'targetRows',(SELECT COUNT(*) FROM " + target_name + '),'
                "'guardRows',COUNT(*),'valid',MIN(valid)) FROM " + guard + ';')
    if change_target_clock:
        with pytest.raises(ValueError, match='MySQL operation failed'):
            connection.script(command, database=database, label='clock-join-rejection')
        evidence = tmp_path / 'private' / (str(connection.sequence).zfill(4) + '-clock-join-rejection.stderr')
        error = evidence.read_text('utf8')
        assert 'ERROR 3819' in error and guard in error
    else:
        result = json.loads(connection.script(command, database=database, label='clock-join-admission').splitlines()[-1])
        assert result == {'sourceRows': 1, 'targetRows': 1, 'guardRows': 1, 'valid': 1}


@pytest.mark.skipif(os.environ.get('DOORHANDLE_COMPACT_MIGRATION_TESTS') != '1', reason='Explicit admitted ECS MySQL fixture required')
@pytest.mark.parametrize('unknown', [False, True])
@pytest.mark.parametrize('legacy_id', ['0', '18446744073709551615'])
@pytest.mark.parametrize('corrupt_id', [False, True])
def test_mysql_sdk_original_unsigned_id_is_recoverable_and_reconciled(tmp_path, unknown, legacy_id, corrupt_id):
    connection, database = mysql(tmp_path)
    statements = list(split_top_level(without_comments(
        (ROOT / 'sql/mysql/compact/copy/33-sdk-checkpoint.sql').read_text('utf8')), ';'))
    projection = next(value for value in statements if value.startswith('INSERT INTO runtime_state(')
                      and 'FROM `__SOURCE_SCHEMA__`.agent_workbench_sdk_state' in value)
    reconciliation = next(value for value in statements if 'NOT(clock_target.legacy_clock_json<=>' in value)
    source = clock.catalog()['agent_workbench_sdk_state']
    target = clock.targets()['runtime_state']
    columns = lambda table: ','.join('`' + name + '` ' + value['type'] for name, value in table['columns'].items())
    # Actual generated projection and full-row reconciliation, temporary tables
    # only. Preserve unsigned endpoints without a JSON double or signed cast.
    command = ('CREATE TEMPORARY TABLE agent_workbench_sdk_state(' + columns(source) + ');\n'
               'CREATE TEMPORARY TABLE sdk_identity_target(' + columns(target) + ');\n'
               'CREATE TEMPORARY TABLE compact_sdk_guard(valid INT NOT NULL CHECK(valid=1));\n'
               'SET @compact_source_clock_unresolved=' + ('1' if unknown else '0') + ';\n'
               "SET @compact_validation_wall_offset='+08:00';\n"
               "INSERT INTO agent_workbench_sdk_state VALUES(" + legacy_id
               + ",'7','Original:Session','State:Key',17,' { \"value\": null } ','2026-01-02 03:04:05.123456');\n")
    command += projection.replace('INSERT INTO runtime_state(', 'INSERT INTO sdk_identity_target(').replace('`__SOURCE_SCHEMA__`.', '') + ';\n'
    if corrupt_id:
        command += "UPDATE sdk_identity_target SET payload_json=JSON_SET(payload_json,'$.legacyId','1');\n"
    command += reconciliation.replace('LEFT JOIN runtime_state clock_target', 'LEFT JOIN sdk_identity_target clock_target').replace('`__SOURCE_SCHEMA__`.', '') + ';\n'
    command = command.replace('__SOURCE_SNAPSHOT_SHA256__', 'a' * 64)
    command += ("SELECT JSON_OBJECT('legacyId',JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.legacyId')),"
                "'originalState',JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.stateJson')),'rows',COUNT(*)) FROM sdk_identity_target GROUP BY payload_json;")
    if corrupt_id:
        with pytest.raises(ValueError, match='MySQL operation failed'):
            connection.script(command, database=database, label='sdk-original-id-rejection')
        error = (tmp_path / 'private' / (str(connection.sequence).zfill(4) + '-sdk-original-id-rejection.stderr')).read_text('utf8')
        assert 'ERROR 3819' in error and 'compact_sdk_guard' in error
    else:
        result = json.loads(connection.script(command, database=database, label='sdk-original-id-copy').splitlines()[-1])
        assert result == {'legacyId': legacy_id, 'originalState': ' { "value": null } ', 'rows': 1}
