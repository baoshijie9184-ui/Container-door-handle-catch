"""Source-contract regression cases. Execute with the project suite on ECS only."""
from contextlib import contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
import re
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = spec_from_file_location(name, ROOT / 'script/schema' / (name + '.py'))
    result = module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


builder = module('build_compact_schema')
inspector = module('inspect_compact_schema')


COPY_SESSION_PREAMBLES = {
    '45-context.sql': 'SET @compact_context_source_frozen=1; SET @compact_context_target_frozen=1;\n',
    '46-detection-identity.sql': 'SET @compact_identity_source_frozen=1; SET @compact_identity_target_frozen=1;\n',
    '47-detection-runtime.sql': ('SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;\n'
                                 'SET @compact_source_quiesced=1;\n'),
    '48-mcp.sql': 'SET @compact_mcp_source_frozen=1; SET @compact_mcp_target_frozen=1;\n',
}


@pytest.mark.parametrize('target', ['chat_project', 'chat_session', 'chat_message'])
def test_parent_references_and_reconciliation_cannot_substitute_for_a_target_row_producer(tmp_path, monkeypatch, target):
    monkeypatch.syspath_prepend(str(ROOT / 'script/schema'))
    migration = module('compact_migration_runtime')
    model = json.loads((ROOT / 'docs/database/compact-schema-contract.json').read_text('utf8'))
    copy = tmp_path / 'sql/mysql/compact/copy'
    shutil.copytree(ROOT / 'sql/mysql/compact/copy', copy)
    java = Path('doorhandle-module-ai/src/main/java/com/ruanzhu/doorhandle/module/ai/workbench/WorkbenchLegacyMigration.java')
    (tmp_path / java).parent.mkdir(parents=True)
    shutil.copyfile(ROOT / java, tmp_path / java)
    path = copy / '12-chat-and-fingerprints.sql'; body = path.read_text('utf8')
    # Leave every source reference and full-row reconciliation in place, while
    # removing the actual direct/prepared INSERT producer (both session branches).
    body, count = re.subn(r'INSERT INTO `' + target + r'`\(', 'INSERT INTO `not_a_business_target`(', body)
    assert count == (2 if target == 'chat_session' else 1)
    path.write_text(body, encoding='utf8')
    monkeypatch.setattr(migration, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='no row producer for target tables: ' + target):
        migration.copy_plan(model)


def test_support_source_generator_and_all_its_checked_in_outputs_stay_in_sync(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'script/schema'))
    author = module('author_support_copy')
    catalog = tmp_path / 'docs/database/compact-support-source-map.json'
    catalog.parent.mkdir(parents=True)
    shutil.copyfile(author.CATALOG, catalog)
    (tmp_path / 'sql/mysql/compact/copy').mkdir(parents=True)
    monkeypatch.setattr(author, 'ROOT', tmp_path); monkeypatch.setattr(author, 'CATALOG', catalog)
    author.main()
    for name in ('sql/mysql/compact/copy/12-chat-and-fingerprints.sql',
                 'sql/mysql/compact/copy/50-owner-locks.sql',
                 'doorhandle-module-app/src/test/resources/compact-support-source.sql'):
        assert (tmp_path / name).read_bytes() == (ROOT / name).read_bytes()


def test_session_copy_catalog_keeps_every_canonical_field_and_the_observed_project_extension():
    catalog = json.loads((ROOT / 'docs/database/compact-support-source-map.json').read_text('utf8'))
    observed = builder.parse_table(builder.without_comments(catalog['tables']['chat_session']['ddl']), 'observed')
    canonical_sql = next(sql for sql in builder.split_top_level(builder.without_comments(
        (ROOT / 'sql/mysql/schema.sql').read_text('utf8')), ';') if re.match(r'CREATE TABLE IF NOT EXISTS `chat_session`\s*\(', sql))
    canonical = builder.parse_table(canonical_sql.replace('CREATE TABLE IF NOT EXISTS', 'CREATE TABLE', 1), 'canonical')
    assert set(observed['columns']) == set(canonical['columns']) | {'project_id'}
    assert len(observed['columns']) == 15 and len(canonical['columns']) == 14
    sql = (ROOT / 'sql/mysql/compact/copy/12-chat-and-fingerprints.sql').read_text('utf8')
    for column in observed['columns']:
        assert 's.`' + column + '`' in sql and 't.`' + column + '`' in sql
    assert sql.index('ALTER TABLE `chat_session` AUTO_INCREMENT=') < sql.index('START TRANSACTION;')
    assert sql.index('INSERT INTO `chat_session`(') < sql.index('INSERT INTO `chat_message`(')


def test_all_copy_segments_have_only_the_reviewed_external_session_variables():
    paths = sorted((ROOT / 'sql/mysql/compact/copy').glob('*.sql'))
    assert len(paths) == 30
    required = {}
    for path in paths:
        sql = builder.without_comments(path.read_text('utf8'))
        used = set(re.findall(r'(?<!@)@[A-Za-z_][A-Za-z_0-9]*', sql))
        assigned = set(re.findall(r'(?:SET\s+|INTO\s+)(@[A-Za-z_][A-Za-z_0-9]*)', sql, re.I))
        if used - assigned:
            required[path.name] = used - assigned
    assert required == {name: set(re.findall(r'(?<!@)@[A-Za-z_][A-Za-z_0-9]*', preamble))
                        for name, preamble in COPY_SESSION_PREAMBLES.items()}


@pytest.fixture
def migration_copy_sessions(tmp_path, monkeypatch):
    """Exercise the real orchestration/plan/rendering, with no database process."""
    monkeypatch.syspath_prepend(str(ROOT / 'script/schema'))
    migration = module('migrate_compact'); model, model_sha = migration.contract()
    plan = migration.copy_plan(model); identity = {'instanceId': 'synthetic', 'machineId': 'synthetic'}
    config = {'scope': 'ecs-disposable-migration', 'serverUuid': 'synthetic-server',
              'sourceSchema': 'doorhandle_legacy_verify_0123456789',
              'targetSchema': 'doorhandle_compact_candidate_0123456789',
              'sourceOffsets': {name: '+00:00' for name in migration.clocks.DOMAINS},
              'sourceCollations': {name: 'utf8mb4_bin' for name in model['sourceTables']},
              'reviewedSourceSnapshot': 'synthetic-observation', 'reviewedSourceSnapshotSha256': 'e' * 64}
    observed = {'kind': 'doorhandle-compact-source-observation', 'status': 'FROZEN_SOURCE_OBSERVED',
                'ecs': identity, 'sourceSchema': config['sourceSchema'], 'serverUuid': config['serverUuid'],
                'contractSha256': model_sha, 'sourceSnapshotSha256': 'a' * 64,
                'sourceMetadataSha256': 'b' * 64, 'sourceSnapshot': {'tables': {}}}
    rendered = {step['name']: migration.render_copy(
        (ROOT / 'sql/mysql/compact/copy' / step['name']).read_text('utf8'), config,
        source_snapshot_sha256=observed['sourceSnapshotSha256']) for step in plan if step['kind'] == 'sql'}
    calls = []; state = {'locked': False, 'loseLockBefore': None}

    class CopyBoundaryReached(Exception):
        pass

    class Mysql:
        def admitted_server(self): return {'serverUuid': config['serverUuid']}
        @contextmanager
        def source_lock(self, schema, tables):
            assert schema == config['sourceSchema'] and tables == model['sourceTables']
            state['locked'] = True
            try: yield {'kind': 'MYSQL_LOCK_TABLES_READ', 'sourceTableCount': 131}
            finally: state['locked'] = False
        def assert_source_lock(self):
            assert state['locked']
            if state['loseLockBefore'] == plan[len(calls)]['name']:
                raise ValueError('synthetic source lock lost')
        def script(self, body, *, database, label):
            assert state['locked'] and database == config['targetSchema']
            name = label.removeprefix('copy-') + '.sql'
            assert body.endswith(rendered[name])
            prefix = body[:-len(rendered[name])]
            # Each call represents a new client session: previous SETs cannot
            # satisfy this segment, and its reviewed SQL body stays unchanged.
            assert prefix == COPY_SESSION_PREAMBLES.get(name, '')
            calls.append({'name': name, 'prefix': prefix})

    mysql = Mysql()
    monkeypatch.setattr(migration, 'Mysql', lambda *_: mysql)
    monkeypatch.setattr(migration, 'compiled_target_parts', lambda: ('', {'sqlSha256': 'c' * 64}, [], [], []))
    monkeypatch.setattr(migration, 'freeze_evidence', lambda *_: {'sha256': 'd' * 64})
    monkeypatch.setattr(migration, 'private_json', lambda *_: (None, observed, 'e' * 64))
    monkeypatch.setattr(migration, 'observed_source', lambda *_: observed)
    monkeypatch.setattr(migration, 'backup_schema', lambda *args, **kwargs: {})
    monkeypatch.setattr(migration, 'initialize_target', lambda *_: None)
    def workbench(*args, **kwargs):
        assert state['locked']; calls.append({'name': 'workbench-java'})
        return {'transaction': 'SYNTHETIC_BRIDGE'}
    monkeypatch.setattr(migration, 'workbench', workbench)
    def after_copy(*_):
        assert state['locked']
        raise CopyBoundaryReached()
    monkeypatch.setattr(migration, 'install_relations', after_copy)
    output = tmp_path / 'migrate'; output.mkdir()
    def run(): return migration.migrate(config, identity, 'f' * 64, output, model, model_sha)
    return run, plan, calls, state, output, CopyBoundaryReached


def test_whole_orchestrator_initializes_every_new_copy_session_under_the_source_lock(migration_copy_sessions):
    run, plan, calls, state, output, boundary = migration_copy_sessions
    with pytest.raises(boundary): run()
    assert [call['name'] for call in calls] == [step['name'] for step in plan]
    assert len(calls) == 31 and sum('prefix' in call for call in calls) == 30
    assert not state['locked']
    record = json.loads((output / 'migration-failed.json').read_bytes())
    assert [step['name'] for step in record['executedSteps']] == [step['name'] for step in plan]
    assert not (output / 'migration-receipt.json').exists()  # This test stops before real relations/restores.


@pytest.mark.parametrize('segment', list(COPY_SESSION_PREAMBLES))
def test_lost_source_lock_never_issues_a_frozen_session_flag_or_next_copy(migration_copy_sessions, segment):
    run, plan, calls, state, output, _ = migration_copy_sessions
    state['loseLockBefore'] = segment
    with pytest.raises(ValueError, match='synthetic source lock lost'): run()
    preceding = [step['name'] for step in plan[:next(i for i, step in enumerate(plan) if step['name'] == segment)]]
    assert [call['name'] for call in calls] == preceding and segment not in preceding
    assert not state['locked'] and not (output / 'migration-receipt.json').exists()
    record = json.loads((output / 'migration-failed.json').read_bytes())
    assert record['status'] == 'FAILED_OR_UNKNOWN_STOPPED'
    assert [step['name'] for step in record['executedSteps']] == preceding


def test_large_comment_free_insert_is_not_copied_into_character_storage():
    source = "INSERT INTO `item` VALUES ('" + 'x' * (1024 * 1024) + "');"
    assert builder.without_comments(source) is source


def test_fragment_comment_masking_preserves_offsets_and_quoted_markers():
    source = "/*a\r\nb*/ SELECT '/*literal*/', `--id`; -- note\r\n#last"
    expected = "   \r\n    SELECT '/*literal*/', `--id`;        \r\n     "
    assert builder.without_comments(source) == expected
    assert len(builder.without_comments(source)) == len(source)


def test_comment_free_fast_return_still_rejects_unclosed_quotes():
    with pytest.raises(ValueError, match='Unclosed SQL'):
        builder.without_comments("INSERT INTO item VALUES ('unterminated")


def test_commented_create_is_not_a_table_and_quoted_comment_markers_are_preserved():
    source = "-- CREATE TABLE fake(id INT);\nCREATE TABLE actual(id BIGINT PRIMARY KEY, note TEXT COMMENT '-- ; /* text */') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"
    statements = list(builder.split_top_level(builder.without_comments(source), ';'))
    assert len(statements) == 1
    table = builder.parse_table(statements[0], 'example.sql')
    assert table['name'] == 'actual'
    assert table['columns']['note']['declaration'].endswith("COMMENT '-- ; /* text */'")


def test_executable_comments_cannot_hide_extra_ddl():
    with pytest.raises(ValueError, match='Executable comment'):
        builder.without_comments('/*!80000 CREATE TABLE hidden(id INT) */;')


def test_constraint_expression_commas_do_not_split_columns():
    sql = "CREATE TABLE item(id BIGINT PRIMARY KEY, amount DECIMAL(12,4), kind VARCHAR(24), CONSTRAINT ck_item CHECK(kind IN ('A','B'))) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    table = builder.parse_table(sql, 'example.sql')
    assert set(table['columns']) == {'id', 'amount', 'kind'}
    assert table['columns']['amount']['type'] == 'DECIMAL(12,4)'
    assert len(table['constraints']) == 1


@pytest.mark.parametrize('suffix', [
    'ENGINE=MyISAM DEFAULT CHARSET=utf8mb4',
    'ENGINE=InnoDB DEFAULT CHARSET=latin1',
])
def test_nontransactional_or_wrong_charset_baseline_is_rejected(suffix):
    with pytest.raises(ValueError):
        builder.parse_table('CREATE TABLE item(id BIGINT PRIMARY KEY) ' + suffix, 'example.sql')


def test_comma_hidden_in_generated_comment_cannot_silently_drop_a_column():
    ddl = '''CREATE TABLE item(id BIGINT PRIMARY KEY,
      CONSTRAINT ck_item CHECK(id>0)
      -- END GENERATED FIRST,
      original_json LONGTEXT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'''
    with pytest.raises(ValueError, match='CHECK has trailing SQL'):
        builder.parse_table(builder.without_comments(ddl), 'generated.sql')


def test_generated_section_separator_is_executable_and_preserves_first_column():
    ddl = '''CREATE TABLE item(id BIGINT PRIMARY KEY,
      CONSTRAINT ck_item CHECK(id>0)
      -- END GENERATED FIRST
      ,
      original_json LONGTEXT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'''
    parsed = builder.parse_table(builder.without_comments(ddl), 'generated.sql')
    assert set(parsed['columns']) == {'id', 'original_json'}


def test_low_table_count_does_not_allow_legacy_views_or_duplicate_service_tables():
    contract = {'expectedTargetTables': ['users', 'operation_job']}
    row = lambda schema, name, kind='BASE TABLE': {'schema': schema, 'name': name, 'type': kind, 'engine': 'InnoDB'}
    valid = [row('business', 'users'), row('business', 'operation_job')]
    assert inspector.assess_objects(contract, valid)['passed']
    assert not inspector.assess_objects(contract, valid + [row('business', 'old_command', 'VIEW')])['passed']
    assert not inspector.assess_objects(contract, valid + [row('other_service', 'operation_job')])['passed']
    assert not inspector.assess_objects(contract, valid[:1])['passed']


@pytest.mark.parametrize('directive', [
    'init-command=DROP TABLE users',
    '!include /etc/mysql/conf.d/other.cnf',
    'tee=/tmp/output',
    '[server]\ninit-file=/tmp/statements.sql',
])
def test_read_only_catalog_client_rejects_executable_options(tmp_path, directive):
    path = tmp_path / 'client.cnf'
    path.write_text('[client]\nhost=127.0.0.1\n' + directive + '\n', encoding='utf-8')
    with pytest.raises(ValueError):
        inspector.validate_client_options(path)


def test_connection_secret_is_never_returned_by_option_validation(tmp_path):
    path = tmp_path / 'client.cnf'
    path.write_text('[client]\nhost=127.0.0.1\nport=13376\nuser=ecsit_example\npassword="semi;hash#word"\nssl-mode=DISABLED\n', encoding='utf-8')
    assert inspector.validate_client_options(path) is None


def test_withdrawn_design_cannot_be_built_or_used_as_the_acceptance_catalog(tmp_path, monkeypatch):
    contract_path = tmp_path / 'docs/database/compact-schema-contract.json'
    contract_path.parent.mkdir(parents=True)
    contract_path.write_text(json.dumps({'status': 'REQUIRES_DOMAIN_REDESIGN'}), encoding='utf-8')
    monkeypatch.setattr(builder, 'ROOT', tmp_path)
    monkeypatch.setattr(inspector, 'CONTRACT', contract_path)
    with pytest.raises(ValueError, match='withdrawn'):
        builder.compile_schema()
    with pytest.raises(ValueError, match='withdrawn'):
        inspector.load_contract()


def test_current_baseline_cannot_silently_bypass_a_withdrawn_design():
    contract = json.loads(inspector.CONTRACT.read_text(encoding='utf-8'))
    if contract['status'] == 'REQUIRES_DOMAIN_REDESIGN':
        with pytest.raises(ValueError, match='withdrawn'):
            builder.compile_schema()
        with pytest.raises(ValueError, match='withdrawn'):
            inspector.load_contract()
        return
    sql, catalog = builder.compile_schema()
    inspector.load_contract()
    assert set(catalog['tables']) == set(contract['expectedTargetTables'])
    assert catalog['tableCount'] <= 30
    assert catalog['status'] == 'SOURCE_COMPILED_MYSQL_EXECUTION_NOT_PROVEN'
    assert sql


def copy_current_schema_sources(tmp_path, monkeypatch):
    for relative in ['docs/database/compact-schema-contract.json', *[
        'sql/mysql/compact/baseline/' + part for part in builder.PARTS
    ]]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    monkeypatch.setattr(builder, 'ROOT', tmp_path)
    return tmp_path / 'sql/mysql/compact/baseline/35-runtime-guards.sql'


def test_migration_target_compilation_accepts_the_real_baseline_with_exact_after_identity_guards(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'script/schema'))
    runtime = module('compact_migration_runtime')
    _, catalog, base, foreign, guards = runtime.compiled_target_parts()
    assert len(base) == catalog['tableCount'] == 29 and foreign
    assert any('AFTER INSERT ON agent_run' in guard for guard in guards)
    assert any('AFTER UPDATE ON agent_connector' in guard for guard in guards)


def test_migration_target_compilation_refuses_changed_before_or_after_timing(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'script/schema'))
    runtime = module('compact_migration_runtime'); original = runtime.compile_schema
    for name, timing in (('compact_legacy_clock_agent_run_binding_insert', 'BEFORE'),
                         ('compact_runtime_protect_delete', 'AFTER')):
        def changed(name=name, timing=timing):
            sql, catalog = original()
            target = next(guard for guard in catalog['triggers'] if guard['name'] == name)
            target['timing'] = timing
            return sql, catalog
        monkeypatch.setattr(runtime, 'compile_schema', changed)
        with pytest.raises(ValueError, match='Compiled compact target'):
            runtime.compiled_target_parts()


def test_generated_cli_schema_keeps_trigger_bodies_and_restores_statement_separator():
    sql, catalog = builder.compile_schema()
    assert {guard['name'] for guard in catalog['triggers']} == set(builder.RUNTIME_GUARDS) | set(builder.IDENTITY_GUARDS) | set(builder.QUOTA_GUARDS) | set(builder.AUDIT_GUARDS) | set(builder.WORKFLOW_GUARDS) | set(builder.LEGACY_CLOCK_GUARDS)
    assert {guard['name']: guard['event'] for guard in catalog['triggers'] if guard['timing'] == 'AFTER'} == builder.AFTER_GUARDS
    assert 'DELIMITER $$\n' in sql
    assert 'END$$\nDELIMITER ;' in sql
    assert sql.index('DELIMITER ;') < sql.index('ADD CONSTRAINT fk_audit_journal_run')


@pytest.mark.parametrize('mutation', ['missing-protection', 'unexpected-name', 'nested-delete', 'wrong-timing'])
def test_runtime_guard_resource_cannot_drop_a_protection_or_hide_executable_dml(tmp_path, monkeypatch, mutation):
    guard = copy_current_schema_sources(tmp_path, monkeypatch)
    body = guard.read_text(encoding='utf-8')
    if mutation == 'missing-protection':
        body = body[:body.index('CREATE TRIGGER compact_runtime_protect_update')]
    elif mutation == 'unexpected-name':
        body = body.replace('compact_runtime_protect_delete', 'unregistered_trigger', 1)
    elif mutation == 'wrong-timing':
        body = body.replace('BEFORE DELETE', 'AFTER DELETE', 1)
    else:
        body = body.replace('END$$', 'DELETE FROM runtime_state;\nEND$$', 1)
    guard.write_text(body, encoding='utf-8')
    with pytest.raises(ValueError, match='both guards|Unexpected or repeated|nested DDL/DML'):
        builder.compile_schema()


def test_source_compiler_refuses_auto_increment_check_before_ecs_ddl(tmp_path, monkeypatch):
    copy_current_schema_sources(tmp_path, monkeypatch)
    path = tmp_path / 'sql/mysql/compact/baseline/25-agent.sql'
    sql = path.read_text('utf8').replace('CREATE TABLE agent_run (',
        'CREATE TABLE agent_run (\n CONSTRAINT ck_probe_auto CHECK(id>0),', 1)
    path.write_text(sql, encoding='utf8')
    with pytest.raises(ValueError, match='agent_run CHECK cannot reference an AUTO_INCREMENT'):
        builder.compile_schema()


def test_source_compiler_refuses_rewriting_fk_action_on_check_column(tmp_path, monkeypatch):
    copy_current_schema_sources(tmp_path, monkeypatch)
    path = tmp_path / 'sql/mysql/compact/baseline/40-relations.sql'
    before = 'fk_chat_session_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT'
    sql = path.read_text('utf8')
    assert sql.count(before) == 1
    path.write_text(sql.replace(before, before.replace('ON UPDATE RESTRICT', 'ON UPDATE CASCADE')), encoding='utf8')
    with pytest.raises(ValueError, match='CHECK column participates in a rewriting foreign-key action'):
        builder.compile_schema()


def test_digest_author_reproduces_innodb_restrict_equivalent_actions_and_exact_fk_shape(tmp_path):
    for relative in ('script/schema/author_digest_copy.py', 'script/schema/build_compact_schema.py',
                     'sql/mysql/migration-V65-quality-digests.sql', 'sql/mysql/compact/baseline/30-operations.sql'):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    (tmp_path / 'sql/mysql/compact/copy').mkdir()
    subprocess.run([sys.executable, '-B', str(tmp_path / 'script/schema/author_digest_copy.py')],
                   check=True, capture_output=True, text=True)
    generated = (tmp_path / 'sql/mysql/compact/copy/49-digests.sql').read_text(encoding='utf8')
    assert generated == (ROOT / 'sql/mysql/compact/copy/49-digests.sql').read_text(encoding='utf8')
    guard = next(line for line in generated.splitlines() if "r.constraint_name=BINARY 'fk_digest_run_schedule'" in line)
    assert "r.delete_rule IN ('RESTRICT','NO ACTION') AND r.update_rule IN ('RESTRICT','NO ACTION')" in guard
    assert "k.column_name='schedule_id' AND k.ordinal_position=1 AND k.position_in_unique_constraint=1" in guard
    assert "BINARY k.referenced_table_schema=BINARY '__SOURCE_SCHEMA__'" in guard
    assert "k.referenced_table_name='quality_digest_schedule' AND k.referenced_column_name='schedule_id'" in guard
    assert "table_type='BASE TABLE' AND engine='InnoDB'" in generated
    assert 'CASCADE' not in guard and 'SET NULL' not in guard
    control = next(line for line in generated.splitlines() if 'quality_digest_control s LEFT JOIN runtime_state' in line)
    assert 'NOT(BINARY t.`payload_version`<=>BINARY 1)' in control
    status = next(line for line in generated.splitlines()
                  if "BINARY t.table_name=BINARY 'quality_digest_run'" in line and 'c.check_clause' in line)
    expected = "'statusin''pending'',''running'',''completed'',''failed'',''blocked'''"
    assert "t.constraint_type='CHECK' AND t.enforced='YES'" in status
    assert ' IN (BINARY ' + expected + ',BINARY REPLACE(' + expected + ',CHAR(39),CONCAT(CHAR(92),CHAR(39))))' in status
    assert "REPLACE(c.check_clause,'_utf8mb4','')" in status
    assert 'REPLACE(c.check_clause,CHAR(92)' not in status
    command = next(line for line in generated.splitlines()
                   if line.startswith('INSERT INTO workflow_instance(') and "'DIGEST_COMMAND'" in line)
    assert "SELECT SHA2(CONCAT('DIGEST_COMMAND:',CAST(JSON_ARRAY(s.`actor_user_id`,s.`request_id`) AS CHAR CHARACTER SET utf8mb4)),256)" in command
    assert 'legacy-digest-cmd-' not in generated


def test_model_budget_author_reproduces_exact_check_spellings_and_all_enforced_groups(tmp_path):
    for relative in ('script/schema/author_model_budget_copy.py', 'script/schema/build_compact_schema.py',
                     'sql/mysql/migration-V64-model-budget.sql'):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    (tmp_path / 'sql/mysql/compact/copy').mkdir(parents=True)
    subprocess.run([sys.executable, '-B', str(tmp_path / 'script/schema/author_model_budget_copy.py')],
                   check=True, capture_output=True, text=True)
    generated = (tmp_path / 'sql/mysql/compact/copy/38-model-budget.sql').read_text(encoding='utf8')
    assert generated == (ROOT / 'sql/mysql/compact/copy/38-model-budget.sql').read_text(encoding='utf8')
    guards = [line for line in generated.splitlines() if 'c.check_clause' in line]
    assert len(guards) == 7
    assert all(' IN (BINARY e.clause_text,BINARY REPLACE(e.clause_text,CHAR(39),CONCAT(CHAR(92),CHAR(39))))' in line
               for line in guards)
    unknown = next(line for line in guards if 'LEFT JOIN compact_budget_checks e' in line)
    assert 'IF(COUNT(*)=0,1,0)' in unknown
    assert "(e.table_name IS NULL OR t.enforced<>'YES')" in unknown
    for group in ('total', 'warning', 'status', 'input', 'output', 'remaining'):
        guard = next(line for line in guards if "e.semantic_group='" + group + "'" in line)
        assert 'IF(COUNT(*)=1,1,0)' in guard and "t.enforced='YES'" in guard
    for table, count in (('agent_model_budget', 2), ('agent_model_budget_attempt', 3),
                         ('agent_model_budget_observation', 1), ('agent_model_budget_audit', 0)):
        assert "IF(COUNT(*)=" + str(count) + ",1,0) FROM information_schema.table_constraints WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='" + table + "' AND constraint_type='CHECK'" in generated


def test_workbench_author_pairs_both_payload_versions_with_clock_provenance_without_losing_identity(tmp_path):
    relative_java = 'doorhandle-module-ai/src/main/java/com/ruanzhu/doorhandle/module/ai/workbench/WorkbenchProtocol.java'
    paths = ['sql/mysql/compact/' + mode + '/30-operations.sql' for mode in ('baseline', 'baseline-fixed-clock')]
    for relative in ('script/schema/author_workbench_constraints.py', relative_java, *paths):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    author = tmp_path / 'script/schema/author_workbench_constraints.py'
    paired = ("AND ((legacy_clock_json IS NULL AND JSON_EXTRACT(payload_json,'$.schemaVersion')=1)"
              " OR (legacy_clock_json IS NOT NULL AND JSON_EXTRACT(payload_json,'$.schemaVersion')=2)) AND JSON_TYPE")
    old = "AND JSON_EXTRACT(payload_json,'$.schemaVersion')=1 AND JSON_TYPE"
    originals = {relative: (ROOT / relative).read_text('utf8') for relative in paths}
    for relative in paths:
        target = tmp_path / relative
        item = next(line for line in originals[relative].splitlines() if line.startswith(' CONSTRAINT ck_workflow_workbench_item CHECK '))
        assert paired in item
        for invariant in ("resource_type='WORKBENCH_ITEM'", 'resource_id IS NOT NULL', 'CHAR_LENGTH(resource_id)<=64',
                          "idempotency_scope='WORKBENCH_ITEM'", 'BINARY request_id=BINARY resource_id',
                          'session_id IS NOT NULL', 'payload_version=1',
                          "JSON_CONTAINS_PATH(payload_json,'all','$.schemaVersion','$.data')=1",
                          "JSON_TYPE(JSON_EXTRACT(payload_json,'$.data'))='OBJECT'"):
            assert invariant in item
        target.write_text(originals[relative].replace(paired, old), encoding='utf8')
    for _ in range(2):
        subprocess.run([sys.executable, '-B', str(author)], check=True, capture_output=True, text=True)
        assert all((tmp_path / relative).read_text('utf8') == original for relative, original in originals.items())
    target = tmp_path / paths[0]
    target.write_text(originals[paths[0]].replace(paired, paired.replace("'$.schemaVersion')=2", "'$.schemaVersion')=3")), encoding='utf8')
    refused = subprocess.run([sys.executable, '-B', str(author)], capture_output=True, text=True)
    assert refused.returncode != 0 and 'Unreviewed workbench item clock/version contract' in refused.stderr


def test_mcp_installation_reservations_keep_a_separate_closed_execution_field_branch():
    mcp = ("(kind='MCP_INSTALLATION' AND execution_state IS NULL AND reserved_bytes IS NOT NULL"
           " AND reserved_bytes>=0 AND exit_verified IS NULL AND execution_deadline IS NULL)")
    for mode in ('baseline', 'baseline-fixed-clock'):
        sql = (ROOT / 'sql/mysql/compact' / mode / '30-operations.sql').read_text('utf8')
        execution = next(line.strip() for line in sql.splitlines() if line.lstrip().startswith('CONSTRAINT ck_workflow_execution CHECK '))
        deadline = 'execution_deadline IS NOT NULL' if mode == 'baseline-fixed-clock' else '(execution_deadline IS NOT NULL OR legacy_clock_json IS NOT NULL)'
        skill = ("(kind='SKILL_DOWNLOAD' AND execution_state IS NOT NULL AND execution_state IN ('RESERVED','RUNNING','SEALED','RELEASED','NEEDS_REVIEW')"
                 " AND reserved_bytes IS NOT NULL AND reserved_bytes>=0 AND exit_verified IS NOT NULL AND " + deadline
                 + " AND ((execution_state IN ('SEALED','RELEASED') AND exit_verified=TRUE AND reserved_bytes=0)"
                 " OR (execution_state IN ('RESERVED','RUNNING','NEEDS_REVIEW') AND exit_verified=FALSE)))")
        nulls = '(execution_state IS NULL AND reserved_bytes IS NULL AND exit_verified IS NULL AND execution_deadline IS NULL)'
        assert execution == 'CONSTRAINT ck_workflow_execution CHECK (' + nulls + ' OR ' + skill + ' OR ' + mcp + '),'
        installation = next(line for line in sql.splitlines() if line.lstrip().startswith('CONSTRAINT ck_workflow_mcp_installation CHECK '))
        assert 'reserved_bytes IS NOT NULL AND reserved_bytes>=0' in installation
    copy = (ROOT / 'sql/mysql/compact/copy/48-mcp.sql').read_text('utf8')
    installation = next(line for line in copy.splitlines() if line.startswith('INSERT INTO workflow_instance(')
                        and "'MCP_INSTALLATION'" in line)
    assert 'reserved_bytes' in installation.split(' SELECT ', 1)[0]
    assert 's.reserved_bytes' in installation.split(' SELECT ', 1)[1]


def test_mcp_tail_checks_compare_temporal_types_at_microsecond_precision_and_keep_other_bytes_exact(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'script/schema'))
    clocks = module('author_legacy_clock_copy')

    def comparisons(guard):
        result = {}
        for match in re.finditer(r'\bNOT\(', guard):
            opening = match.end() - 1
            comparison = guard[opening + 1:clocks.paren(guard, opening)]
            while comparison.startswith('('):
                assert clocks.paren(comparison, 0) == len(comparison) - 1
                comparison = comparison[1:-1]
            pair = re.fullmatch(r'(BINARY CAST\([ta]\.[a-z_][a-z0-9_]* AS CHAR\)|BINARY [ta]\.[a-z_][a-z0-9_]*|[ta]\.[a-z_][a-z0-9_]*)<=>(.+)', comparison)
            assert pair is not None
            left, right = pair.groups()
            actual = re.search(r'[ta]\.[a-z_][a-z0-9_]*', left).group()
            assert actual not in result
            assert list(builder.split_top_level(right, ',')) == [right]
            assert clocks.keyword(right, 'OR') == clocks.keyword(right, 'AND') == -1
            result[actual] = left, right
        return result

    def converted_time(expression, mode):
        assert expression.startswith('CONVERT_TZ(')
        opening = len('CONVERT_TZ')
        assert clocks.paren(expression, opening) == len(expression) - 1
        arguments = list(builder.split_top_level(expression[opening + 1:-1], ','))
        assert len(arguments) == 3 and re.fullmatch(r's\.[a-z_]+', arguments[0])
        offset = "'__SOURCE_MCP_OFFSET__'" if mode == 'copy-fixed-clock' else '@compact_validation_wall_offset'
        assert arguments[1:] == [offset, "'+00:00'"]

    _, catalog = builder.compile_schema()
    checked = []
    for mode in ('copy', 'copy-fixed-clock'):
        sql = (ROOT / 'sql/mysql/compact' / mode / '48-mcp.sql').read_text('utf8')
        guards = [line for line in sql.splitlines() if line.startswith('INSERT INTO compact_mcp_guard ')
                  and ' LEFT JOIN ' in line and ' WHERE ' in line]
        temporal = 0
        for guard in guards:
            target = re.search(r'LEFT JOIN ([a-z_]+) ([ta]) ON ', guard)
            if target is None:
                continue
            table, alias = target.groups()
            checked.append((mode, table, alias))
            values = comparisons(guard)
            fields = {column: definition for column, definition in catalog['tables'][table]['columns'].items()
                      if not definition['generatedVirtual'] and not (column == 'id' and table != 'agent_connector')
                      and not (column == 'legacy_clock_json' and alias == 't')}
            assert set(values) == {alias + '.' + column for column in fields}
            for column, definition in fields.items():
                actual = alias + '.' + column
                left, right = values[actual]
                if definition['type'].upper().startswith(('DATETIME', 'TIMESTAMP')):
                    assert left == actual
                    expected = right
                    if expected.startswith('IF('):
                        assert mode == 'copy' and clocks.paren(expected, 2) == len(expected) - 1
                        branches = list(builder.split_top_level(expected[3:-1], ','))
                        assert len(branches) == 3 and branches[:2] == ['@compact_source_clock_unresolved', 'NULL']
                        converted_time(branches[2], mode)
                    elif expected.startswith('CONVERT_TZ('):
                        assert mode == 'copy-fixed-clock'
                        converted_time(expected, mode)
                    elif expected == 'CAST(@compact_mcp_imported_at AS DATETIME(6))':
                        assert alias == 'a' and column == 'occurred_at'
                    elif expected != 'NULL':
                        assert column in ('mcp_source_created_at', 'mcp_source_updated_at')
                        assert expected == 's.' + column.removeprefix('mcp_source_')
                    temporal += 1
                elif definition['type'].upper() == 'JSON':
                    assert left == 'BINARY CAST(' + actual + ' AS CHAR)'
                    assert right.startswith('BINARY CAST(')
                    cast = right[len('BINARY '):]
                    assert clocks.paren(cast, len('CAST')) == len(cast) - 1
                    assert cast.endswith(' AS CHAR)')
                    assert re.fullmatch(r'NULL|s\.[a-z_]+', cast[len('CAST('):-len(' AS CHAR)')])
                else:
                    assert left == 'BINARY ' + actual and right.startswith('BINARY ')
                    assert right[len('BINARY '):]
                    if column == 'mcp_source_utc_offset':
                        offset = ("'__SOURCE_MCP_OFFSET__'" if mode == 'copy-fixed-clock' else
                                  'IF(@compact_source_clock_unresolved,NULL,@compact_validation_wall_offset)')
                        assert right == 'BINARY ' + offset
        assert sum(item[0] == mode for item in checked) == 14
        assert temporal
        audit = next(line for line in guards if '.agent_local_mcp_audit s LEFT JOIN audit_event t ' in line)
        audit_values = comparisons(audit)
        if mode == 'copy':
            assert audit_values['t.occurred_at'] == ('t.occurred_at', "IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(s.created_at,@compact_validation_wall_offset,'+00:00'))")
            assert len([line for line in sql.splitlines() if 'NOT(clock_target.legacy_clock_json<=>' in line]) == 13
        else:
            assert audit_values['t.occurred_at'] == ('t.occurred_at', "CONVERT_TZ(s.created_at,'__SOURCE_MCP_OFFSET__','+00:00')")
        assert audit_values['t.payload_json'] == ('BINARY t.payload_json', "BINARY JSON_OBJECT('schemaVersion',1,'detailJson',CAST(s.detail_json AS CHAR))")
        assert audit_values['t.legacy_key'] == ('BINARY t.legacy_key', 'BINARY CAST(s.id AS CHAR)')
        clock = next(line for line in guards if 'compact_mcp_snapshots s LEFT JOIN audit_event a ' in line)
        assert comparisons(clock)['a.occurred_at'] == ('a.occurred_at', 'CAST(@compact_mcp_imported_at AS DATETIME(6))')


def test_clock_join_source_binding_preserves_literals_functions_variables_and_existing_qualifiers(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'script/schema'))
    clocks = module('author_legacy_clock_copy')
    sources = {'original': {'columns': {key: {} for key in ('id', 'updated_at', 'payload_json', 'concat')}}}
    value = ("CONCAT(id,`updated_at`,s.id,s . `id`,@id,@@SESSION.id,"
             "'id updated_at','it''s id',\"payload_json\",JSON_EXTRACT(payload_json,'$.id'))")
    assert clocks.source_expression(value, {'s': 'original'}, sources) == (
        "CONCAT(s.id,s.`updated_at`,s.id,s . `id`,@id,@@SESSION.id,"
        "'id updated_at','it''s id',\"payload_json\",JSON_EXTRACT(s.payload_json,'$.id'))")


@pytest.mark.parametrize('auxiliary_catalogued', [True, False])
def test_clock_join_never_guesses_a_bare_column_across_multiple_sources(monkeypatch, auxiliary_catalogued):
    monkeypatch.syspath_prepend(str(ROOT / 'script/schema'))
    clocks = module('author_legacy_clock_copy')
    sources = {'original': {'columns': {'id': {}}}}
    if auxiliary_catalogued:
        sources['auxiliary'] = {'columns': {'id': {}}}
    aliases = {'s': 'original', 'a': 'auxiliary'}
    assert clocks.source_expression('s.id+a.id', aliases, sources) == 's.id+a.id'
    with pytest.raises(ValueError, match='explicit alias before clock reconciliation'):
        clocks.source_expression('id', aliases, sources)


@pytest.mark.parametrize('filename,source,columns', [
    ('32-agent-journal.sql', 'agent_run_event', ('id', 'occurred_at', 'payload_json')),
    ('33-sdk-checkpoint.sql', 'agent_workbench_sdk_state', ('session_id', 'state_key', 'updated_at', 'state_json')),
])
def test_clock_join_compilation_qualifies_source_identity_payload_and_time(monkeypatch, filename, source, columns):
    monkeypatch.syspath_prepend(str(ROOT / 'script/schema'))
    clocks = module('author_legacy_clock_copy')
    original = (ROOT / 'sql/mysql/compact/copy-fixed-clock' / filename).read_text('utf8')
    compiled = clocks.compile_copy(original, filename)
    assert compiled == (ROOT / 'sql/mysql/compact/copy' / filename).read_text('utf8')
    guards = [line for line in compiled.splitlines() if 'NOT(clock_target.legacy_clock_json<=>' in line]
    assert len(guards) == 1
    # This independent token check excludes quoted data and already-qualified
    # identifiers, not the source-binding function under test.
    guard = re.sub(r"'(?:''|\\.|[^'\\])*'", "''", guards[0])
    for column in columns:
        assert source + '.' + column in guard
        assert not re.search(r'(?<![.A-Za-z0-9_`])' + column + r'\b', guard)
    assert 'LEFT JOIN ' in guard and 'clock_target.' in guard


def test_clock_join_qualifies_the_original_source_filter_before_adding_a_target(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'script/schema'))
    clocks = module('author_legacy_clock_copy')
    original = (ROOT / 'sql/mysql/compact/copy-fixed-clock/33-sdk-checkpoint.sql').read_text('utf8')
    original = original.replace('agent_workbench_sdk_state ORDER BY id',
                                'agent_workbench_sdk_state WHERE updated_at IS NOT NULL ORDER BY id')
    compiled = clocks.compile_copy(original, '33-sdk-checkpoint.sql')
    guard = next(line for line in compiled.splitlines() if 'NOT(clock_target.legacy_clock_json<=>' in line)
    assert 'WHERE (agent_workbench_sdk_state.updated_at IS NOT NULL) AND ' in guard


def test_report_author_updates_fixed_and_unresolved_copies_without_nulling_clock_evidence(tmp_path):
    source_catalog = ROOT / 'docs/database/legacy-clock-source-catalog.json'
    catalog = json.loads(source_catalog.read_text('utf8'))
    paths = {Path(name) for table in catalog['tables'].values() for name in table['sourceFiles']}
    paths |= {Path('script/schema') / name for name in (
        'build_compact_schema.py', 'author_report_copy_checks.py', 'author_legacy_clock_copy.py')}
    paths.add(source_catalog.relative_to(ROOT))
    paths |= {path.relative_to(ROOT) for path in (ROOT / 'sql/mysql/compact/baseline').glob('*.sql')}
    filename = '34-quality-report-workflow.sql'
    for mode in ('copy-fixed-clock', 'copy'):
        paths.add(Path('sql/mysql/compact') / mode / filename)
    for relative in paths:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    result = subprocess.run([sys.executable, '-B', str(tmp_path / 'script/schema/author_report_copy_checks.py')],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)['status'] == 'SOURCE_AUTHORED_NOT_EXECUTED'
    for mode in ('copy-fixed-clock', 'copy'):
        relative = Path('sql/mysql/compact') / mode / filename
        assert (tmp_path / relative).read_text('utf8') == (ROOT / relative).read_text('utf8')
    compiled = (tmp_path / 'sql/mysql/compact/copy' / filename).read_text('utf8')
    assert 'NOT(BINARY t.legacy_clock_json<=>BINARY (NULL))' not in compiled
    assert compiled.count('NOT(clock_target.legacy_clock_json<=>') == 7


@pytest.mark.parametrize('kind,source', [
    ('REPORT_DELIVERY', 'detection_report_outbox'),
    ('REPORT_CONSUMPTION', 'detection_report_event_receipt'),
])
def test_terminal_report_orphan_projection_keeps_the_same_owner_and_complete_reconciliation(kind, source):
    for mode in ('copy-fixed-clock', 'copy'):
        sql = (ROOT / 'sql/mysql/compact' / mode / '34-quality-report-workflow.sql').read_text('utf8')
        statements = list(builder.split_top_level(builder.without_comments(sql), ';'))
        projection = next(item for item in statements if item.startswith('INSERT INTO workflow_instance(')
                          and "'" + kind + "'" in item)
        assert 'COALESCE(q.owner_user_id,0)' in projection
        assert 'LEFT JOIN quality_report q ON' in projection
        assert 'NOT(t.owner_user_id<=>(COALESCE(q.owner_user_id,0)))' in sql
        check = next(item for item in statements if 'LEFT JOIN workflow_instance t ON' in item
                     and 'FROM `__SOURCE_SCHEMA__`.' + source + ' ' in item)
        assert 'LEFT JOIN quality_report q ON' in check
        assert 'NOT(BINARY t.legacy_key' in check and 'NOT(BINARY t.payload_json' in check
        assert "source_report.id IS NULL AND (q.id IS NOT NULL OR NOT(BINARY e.delivery_status<=>BINARY 'DELIVERED'))" in sql
        assert 'q.id IS NULL OR NOT(q.id<=>source_report.id)' in sql
