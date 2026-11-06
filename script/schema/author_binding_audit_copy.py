"""Author the V20 association-audit copy and source fixture; never connect to a database."""
from pathlib import Path
import importlib.util
import json
import re

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('compact_parser', ROOT / 'script/schema/build_compact_schema.py')
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)
SOURCE = 'organization_binding_audit'
FILE = 'migration-V20-account-employee-department.sql'
statement = next(s for s in parser.split_top_level(
    parser.without_comments((ROOT / 'sql/mysql' / FILE).read_text(encoding='utf-8')), ';')
    if re.match(r'CREATE TABLE IF NOT EXISTS ' + SOURCE + r'\b', s))
statement = statement.replace('CREATE TABLE IF NOT EXISTS', 'CREATE TABLE', 1)
table = parser.parse_table(statement, FILE)
expected = ['id', 'user_id', 'username', 'actor_user_id', 'actor_username', 'before_employee_id',
            'after_employee_id', 'binding_version', 'action', 'created_at']
if list(table['columns']) != expected or table['primaryKey'] != ['id'] or table['uniqueKeys']:
    raise ValueError('The actual V20 source changed; review the complete ten-column mapping first')


def q(value):
    return 'NULL' if value is None else "'" + str(value).replace("'", "''") + "'"


rows = []
for ordinal, (column, definition) in enumerate(table['columns'].items(), 1):
    declaration = definition['declaration']
    kind = definition['type'].lower()
    collation = definition['collation'] if kind.startswith(('varchar', 'char')) else None
    nullable = 'NO' if column in table['primaryKey'] or 'NOT NULL' in declaration.upper() else 'YES'
    # Every source column has a NULL metadata default; the nullable employee columns explicitly say NULL.
    if re.search(r'\bDEFAULT\b', declaration, re.I):
        raise ValueError('Unexpected V20 source default: ' + declaration)
    extra = 'auto_increment' if 'AUTO_INCREMENT' in declaration.upper() else ''
    rows.append((column, ordinal, kind, nullable, collation, None, extra))

sql = []


def emit(value):
    sql.append(value)


def guard(query):
    emit('INSERT INTO compact_binding_guard ' + query + ';')


emit('''-- Organization binding audit copy candidate, NOT EXECUTED. Source: actual V20, ten columns.
-- Render distinct source schema and the evidenced fixed source UTC offset; keep the source stopped.
-- Target baseline already exists. This kind/provenance must be empty; other domains are retained.
-- Stop on the first error and ROLLBACK on this same connection. Never --force.
-- No source UPDATE/DELETE/DROP. Original IDs/timestamps remain immutable evidence, not new cursor IDs.
SET NAMES utf8mb4;
CREATE TEMPORARY TABLE compact_binding_guard(valid INT NOT NULL CHECK(valid=1)) ENGINE=InnoDB;''')
guard("SELECT IF(DATABASE() IS NOT NULL AND BINARY DATABASE()<>BINARY '__SOURCE_SCHEMA__' AND @@FOREIGN_KEY_CHECKS=1 AND @@SESSION.sql_mode REGEXP '(^|,)(STRICT_TRANS_TABLES|STRICT_ALL_TABLES)(,|$)',1,0)")
guard("SELECT IF(REGEXP_LIKE('__SOURCE_BINDING_OFFSET__','^[+-][0-9]{2}:[0-9]{2}$','c') AND CONVERT_TZ('2026-01-01','__SOURCE_BINDING_OFFSET__','+00:00') IS NOT NULL,1,0)")
guard("SELECT IF(COUNT(DISTINCT privilege_type)=2,1,0) FROM information_schema.schema_privileges WHERE BINARY table_schema=BINARY '__SOURCE_SCHEMA__' AND privilege_type IN ('SELECT','TRIGGER') AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)))")
guard("SELECT IF(COUNT(*)=1,1,0) FROM information_schema.tables WHERE BINARY table_schema=BINARY '__SOURCE_SCHEMA__' AND BINARY table_name=BINARY 'organization_binding_audit' AND table_type='BASE TABLE' AND engine='InnoDB' AND table_collation='utf8mb4_unicode_ci'")
emit('CREATE TEMPORARY TABLE compact_binding_columns(column_name VARCHAR(64),ordinal_position INT,column_type VARCHAR(64),nullable VARCHAR(3),collation_name VARCHAR(64),default_value VARCHAR(64),extra VARCHAR(64),PRIMARY KEY(column_name)) ENGINE=InnoDB;')
emit('INSERT INTO compact_binding_columns VALUES\n' + ',\n'.join('(' + ','.join(map(q, row)) + ')' for row in rows) + ';')
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.columns c LEFT JOIN compact_binding_columns e ON BINARY e.column_name=BINARY c.column_name WHERE BINARY c.table_schema=BINARY '__SOURCE_SCHEMA__' AND BINARY c.table_name=BINARY 'organization_binding_audit' AND e.column_name IS NULL")
guard("SELECT IF(COUNT(*)=0,1,0) FROM compact_binding_columns e LEFT JOIN information_schema.columns c ON BINARY c.table_schema=BINARY '__SOURCE_SCHEMA__' AND BINARY c.table_name=BINARY 'organization_binding_audit' AND BINARY c.column_name=BINARY e.column_name WHERE c.column_name IS NULL OR NOT(c.ordinal_position<=>e.ordinal_position) OR NOT(BINARY LOWER(c.column_type)<=>BINARY e.column_type) OR NOT(BINARY c.is_nullable<=>BINARY e.nullable) OR NOT(BINARY c.collation_name<=>BINARY e.collation_name) OR NOT(BINARY c.column_default<=>BINARY e.default_value) OR NOT(BINARY LOWER(c.extra)<=>BINARY e.extra) OR NOT(BINARY c.generation_expression<=>BINARY '')")
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.triggers WHERE BINARY event_object_schema=BINARY '__SOURCE_SCHEMA__' AND BINARY event_object_table=BINARY 'organization_binding_audit'")
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.table_constraints WHERE BINARY table_schema=BINARY '__SOURCE_SCHEMA__' AND BINARY table_name=BINARY 'organization_binding_audit' AND constraint_type IN ('FOREIGN KEY','CHECK')")
# The only original unique identity is the primary ID. Extra unique keys can destroy repeated historical versions.
guard("SELECT IF(COUNT(*)=1 AND COALESCE(SUM(BINARY index_name=BINARY 'PRIMARY' AND BINARY column_name=BINARY 'id' AND seq_in_index=1 AND sub_part IS NULL AND index_type='BTREE' AND is_visible='YES'),0)=1,1,0) FROM information_schema.statistics WHERE BINARY table_schema=BINARY '__SOURCE_SCHEMA__' AND BINARY table_name=BINARY 'organization_binding_audit' AND non_unique=0")
guard("SELECT IF(COUNT(*)=0,1,0) FROM audit_event WHERE kind='ORGANIZATION_BINDING' OR legacy_source='organization_binding_audit'")

utc = "CONVERT_TZ(s.created_at,'__SOURCE_BINDING_OFFSET__','+00:00')"
original_time = "DATE_FORMAT(s.created_at,'%Y-%m-%d %H:%i:%s.%f')"
offset_seconds = "(IF(LEFT('__SOURCE_BINDING_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_BINDING_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_BINDING_OFFSET__',5,2) AS UNSIGNED)*60))"
valid = [
    's.user_id>0', 's.actor_user_id>0', 'CHAR_LENGTH(s.username) BETWEEN 1 AND 50',
    'CHAR_LENGTH(s.actor_username) BETWEEN 1 AND 50', 's.binding_version BETWEEN 1 AND 2147483647',
    '(s.before_employee_id IS NULL OR s.before_employee_id>0)',
    '(s.after_employee_id IS NULL OR s.after_employee_id>0)',
    'NOT(s.before_employee_id<=>s.after_employee_id)',
    "((BINARY s.action=BINARY 'BIND' AND s.before_employee_id IS NULL AND s.after_employee_id IS NOT NULL) OR (BINARY s.action=BINARY 'UNBIND' AND s.before_employee_id IS NOT NULL AND s.after_employee_id IS NULL) OR (BINARY s.action=BINARY 'REBIND' AND s.before_employee_id IS NOT NULL AND s.after_employee_id IS NOT NULL))",
    utc + ' IS NOT NULL',
    # Some MySQL versions leave out-of-range CONVERT_TZ input unchanged; that must not become fabricated UTC.
    'TIMESTAMPDIFF(SECOND,' + utc + ',s.created_at)=' + offset_seconds,
]
guard('SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.organization_binding_audit s WHERE NOT COALESCE((' + ' AND '.join('(' + item + ')' for item in valid) + '),FALSE)')
payload = "JSON_OBJECT('username',s.username,'actorUsername',s.actor_username,'beforeEmployeeId',s.before_employee_id,'afterEmployeeId',s.after_employee_id,'legacyId',CAST(s.id AS CHAR),'legacyCreatedAt'," + original_time + ')'
emit('START TRANSACTION;')
emit("INSERT INTO audit_event(event_id,kind,owner_user_id,actor_user_id,resource_type,resource_id,action,revision,occurred_at,payload_version,payload_json,legacy_source,legacy_key) SELECT CONCAT('legacy-binding-',s.id),'ORGANIZATION_BINDING',s.user_id,s.actor_user_id,'USER',CAST(s.user_id AS CHAR),s.action,s.binding_version," + utc + ',1,' + payload + ",'organization_binding_audit',CAST(s.id AS CHAR) FROM `__SOURCE_SCHEMA__`.organization_binding_audit s ORDER BY s.id;")
guard("SELECT IF((SELECT COUNT(*) FROM audit_event WHERE kind='ORGANIZATION_BINDING')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.organization_binding_audit),1,0)")
checks = [
    "BINARY t.legacy_source<=>BINARY 'organization_binding_audit'", 'BINARY t.legacy_key<=>BINARY CAST(s.id AS CHAR)',
    "BINARY t.event_id<=>BINARY CONCAT('legacy-binding-',s.id)", "BINARY t.kind<=>BINARY 'ORGANIZATION_BINDING'",
    't.owner_user_id<=>s.user_id', 't.actor_user_id<=>s.actor_user_id', "BINARY t.resource_type<=>BINARY 'USER'",
    'BINARY t.resource_id<=>BINARY CAST(s.user_id AS CHAR)', 'BINARY t.action<=>BINARY s.action',
    't.revision<=>s.binding_version', 't.occurred_at<=>' + utc, 't.payload_version<=>1',
    'BINARY t.payload_json<=>BINARY ' + payload,
]
checks += ['t.' + column + ' IS NULL' for column in [
    'detection_model_id', 'session_id', 'message_id', 'run_id', 'journal_run_id', 'sequence_no', 'request_id', 'content_sha256',
    'previous_sha256', 'event_sha256', 'quantity', 'unit', 'request_scope', 'policy_version', 'outcome', 'observed_at',
]]
guard("SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.organization_binding_audit s LEFT JOIN audit_event t ON BINARY t.legacy_source=BINARY 'organization_binding_audit' AND BINARY t.legacy_key=BINARY CAST(s.id AS CHAR) WHERE t.id IS NULL OR " + ' OR '.join('NOT(' + item + ')' for item in checks))
emit('COMMIT;\nDROP TEMPORARY TABLE compact_binding_columns;\nDROP TEMPORARY TABLE compact_binding_guard;')
(ROOT / 'sql/mysql/compact/copy/39-organization-binding-audit.sql').write_text('\n'.join(sql) + '\n', encoding='utf-8')
fixture = ROOT / 'doorhandle-module-system/src/test/resources/compact/binding-audit-source-evidence.sql'
fixture.parent.mkdir(parents=True, exist_ok=True)
fixture.write_text('-- Actual V20 audit CREATE TABLE only; no unrelated account/department ALTER or invented FK.\n' + statement + ';\n', encoding='utf-8')
print(json.dumps({'status': 'AUTHORED_NOT_EXECUTED', 'sourceTables': 1, 'sourceColumns': len(rows)}))
