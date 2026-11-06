"""Source-contract regression cases. Execute with the project suite on ECS only."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = spec_from_file_location(name, ROOT / 'script/schema' / (name + '.py'))
    result = module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


builder = module('build_compact_schema')
inspector = module('inspect_compact_schema')


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


def test_generated_cli_schema_keeps_trigger_bodies_and_restores_statement_separator():
    sql, catalog = builder.compile_schema()
    assert {guard['name'] for guard in catalog['triggers']} == set(builder.RUNTIME_GUARDS) | set(builder.IDENTITY_GUARDS) | set(builder.QUOTA_GUARDS) | set(builder.AUDIT_GUARDS) | set(builder.WORKFLOW_GUARDS)
    assert 'DELIMITER $$\n' in sql
    assert 'END$$\nDELIMITER ;' in sql
    assert sql.index('DELIMITER ;') < sql.index('ADD CONSTRAINT fk_audit_journal_run')


@pytest.mark.parametrize('mutation', ['missing-protection', 'unexpected-name', 'nested-delete'])
def test_runtime_guard_resource_cannot_drop_a_protection_or_hide_executable_dml(tmp_path, monkeypatch, mutation):
    guard = copy_current_schema_sources(tmp_path, monkeypatch)
    body = guard.read_text(encoding='utf-8')
    if mutation == 'missing-protection':
        body = body[:body.index('CREATE TRIGGER compact_runtime_protect_update')]
    elif mutation == 'unexpected-name':
        body = body.replace('compact_runtime_protect_delete', 'unregistered_trigger', 1)
    else:
        body = body.replace('END$$', 'DELETE FROM runtime_state;\nEND$$', 1)
    guard.write_text(body, encoding='utf-8')
    with pytest.raises(ValueError, match='both guards|Unexpected or repeated|nested DDL/DML'):
        builder.compile_schema()
