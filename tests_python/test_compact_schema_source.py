"""Source-contract regression cases. Execute with the project suite on ECS only."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
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
