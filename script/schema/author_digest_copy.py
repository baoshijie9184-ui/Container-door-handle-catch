"""Author the complete V65 digest copy; source generation only, no database access."""
from pathlib import Path
import importlib.util
import re

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('digest_compact_parser', ROOT / 'script/schema/build_compact_schema.py')
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)
SOURCE_FILE = ROOT / 'sql/mysql/migration-V65-quality-digests.sql'
SOURCE_NAMES = ('quality_digest_control', 'quality_digest_schedule', 'quality_digest_run', 'quality_digest_audit', 'quality_digest_command')
tables = {}
for statement in parser.split_top_level(parser.without_comments(SOURCE_FILE.read_text(encoding='utf8')), ';'):
    if statement.startswith('CREATE TABLE IF NOT EXISTS quality_digest_'):
        parsed = statement.replace('CREATE TABLE IF NOT EXISTS', 'CREATE TABLE', 1)
        if not re.search(r'\bCHARSET\b', parsed, re.I):
            # Parser-only charset for V65's numeric-only control table; actual
            # runtime table collation is still checked against reviewed metadata.
            parsed += ' DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci'
        value = parser.parse_table(parsed, SOURCE_FILE.name)
        tables[value['name']] = value
assert set(tables) == set(SOURCE_NAMES)
assert sum(len(value['columns']) for value in tables.values()) == 39
baseline = (ROOT / 'sql/mysql/compact/baseline/30-operations.sql').read_text(encoding='utf8')
targets = {}
for statement in parser.split_top_level(parser.without_comments(baseline), ';'):
    if statement.startswith('CREATE TABLE '):
        value = parser.parse_table(statement, '30-operations.sql')
        targets[value['name']] = value


def q(value):
    return 'NULL' if value is None else "'" + str(value).replace("'", "''") + "'"


def field(alias, column):
    return alias + '.`' + column + '`'


def row_json(name, alias='s'):
    values = []
    for name, definition in tables[name]['columns'].items():
        expression = field(alias, name)
        if definition['type'].startswith('DATETIME'):
            expression = "DATE_FORMAT(" + expression + ",'%Y-%m-%d %H:%i:%s.%f')"
        elif definition['type'] == 'JSON':
            expression = 'CAST(' + expression + ' AS CHAR CHARACTER SET utf8mb4)'
        elif definition['type'] == 'DATE':
            expression = 'CAST(' + expression + ' AS CHAR)'
        values += [q(name), expression]
    return 'JSON_OBJECT(' + ','.join(values) + ')'


def source_key(name, alias='s'):
    return 'CAST(JSON_ARRAY(' + ','.join(field(alias, column) for column in tables[name]['primaryKey']) + ') AS CHAR CHARACTER SET utf8mb4)'


def row_hash(name, alias='s'):
    return 'SHA2(CAST(JSON_ARRAY(' + ','.join(field(alias, column) for column in tables[name]['columns']) + ') AS CHAR CHARACTER SET utf8mb4),256)'


def optional_json_text(name):
    expression = "JSON_EXTRACT(s.detail_json," + q('$.' + name) + ")"
    return "CASE WHEN JSON_TYPE(" + expression + ")='NULL' THEN NULL ELSE JSON_UNQUOTE(" + expression + ') END'


output = []
def emit(value): output.append(value)
def guard(query): emit('INSERT INTO compact_digest_guard ' + query + ';')

emit('''-- Actual V65 five-table/39-column copy. ECS execution and frozen source only.
-- No source writes, active writers, clock inference, source hash replacement, or FK disabling.
-- BEGIN/COMMIT are this segment only; the outer migration owns source freeze and quarantine.
SET NAMES utf8mb4;
SET @compact_digest_old_concat=@@SESSION.group_concat_max_len;
SET SESSION group_concat_max_len=3200000;
CREATE TEMPORARY TABLE compact_digest_guard(ok TINYINT NOT NULL CHECK(ok=1)) ENGINE=InnoDB;
CREATE TEMPORARY TABLE compact_digest_source_rows(table_name VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,row_key VARCHAR(512) COLLATE utf8mb4_bin NOT NULL,row_sha CHAR(64) NOT NULL,PRIMARY KEY(table_name,row_key)) ENGINE=InnoDB;
CREATE TEMPORARY TABLE compact_digest_sequences(table_name VARCHAR(64) COLLATE utf8mb4_bin NOT NULL PRIMARY KEY,next_id BIGINT UNSIGNED NULL) ENGINE=InnoDB;
CREATE TEMPORARY TABLE compact_digest_existing(table_name VARCHAR(64) NOT NULL,row_key VARCHAR(512) COLLATE utf8mb4_bin NOT NULL,row_sha CHAR(64) NOT NULL,PRIMARY KEY(table_name,row_key)) ENGINE=InnoDB;''')
guard("SELECT IF(DATABASE() IS NOT NULL AND BINARY DATABASE()<>BINARY '__SOURCE_SCHEMA__' AND @@foreign_key_checks=1 AND '__SOURCE_DIGEST_OFFSET__'='+00:00',1,0)")
guard("SELECT IF(COUNT(*)=0,1,0) FROM scheduled_plan WHERE kind='DIGEST_SCHEDULE'")
guard("SELECT IF(COUNT(*)=0,1,0) FROM workflow_instance WHERE kind IN ('DIGEST_RUN','DIGEST_COMMAND')")
guard("SELECT IF(COUNT(*)=0,1,0) FROM audit_event WHERE kind='DIGEST'")
guard("SELECT IF(COUNT(*)=0,1,0) FROM runtime_state WHERE namespace='DIGEST_CONTROL'")

for table, details in tables.items():
    assert details['primaryKey']
    condition = "BINARY table_schema=BINARY '__SOURCE_SCHEMA__' AND BINARY table_name=BINARY " + q(table)
    collation = '__SOURCE_DIGEST_COLLATION_' + table + '__'
    guard('SELECT IF(COUNT(*)=1,1,0) FROM information_schema.tables WHERE ' + condition
          + " AND table_type='BASE TABLE' AND engine='InnoDB' AND BINARY table_collation=BINARY " + q(collation))
    guard('SELECT IF(COUNT(*)=' + str(len(details['columns'])) + ',1,0) FROM information_schema.columns WHERE ' + condition)
    for ordinal, (name, definition) in enumerate(details['columns'].items(), 1):
        declaration = definition['declaration']
        data_type = definition['type'].lower()
        if data_type == 'boolean': data_type = 'tinyint(1)'
        nullability = 'NO' if 'NOT NULL' in declaration.upper() or name in details['primaryKey'] else 'YES'
        extra = 'auto_increment' if 'AUTO_INCREMENT' in declaration.upper() else ''
        expected_collation = collation if data_type.startswith(('varchar', 'char')) else None
        guard('SELECT IF(COUNT(*)=1,1,0) FROM information_schema.columns WHERE ' + condition + ' AND BINARY column_name=BINARY ' + q(name)
              + ' AND ordinal_position=' + str(ordinal) + ' AND BINARY LOWER(column_type)=BINARY ' + q(data_type)
              + ' AND BINARY is_nullable=BINARY ' + q(nullability) + ' AND column_default IS NULL AND BINARY LOWER(extra)=BINARY ' + q(extra)
              + ' AND (BINARY collation_name<=>BINARY ' + q(expected_collation) + ") AND generation_expression=''")
    guard('SELECT IF(COUNT(*)=0,1,0) FROM information_schema.triggers WHERE BINARY event_object_schema=BINARY \'__SOURCE_SCHEMA__\' AND BINARY event_object_table=BINARY ' + q(table))
    allowed_unique = [details['primaryKey'], *details['uniqueKeys']]
    actual_unique = "SELECT index_name,GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ',') cols FROM information_schema.statistics WHERE " + condition + ' AND non_unique=0 GROUP BY index_name'
    guard('SELECT IF(COUNT(*)=' + str(len(allowed_unique)) + ',1,0) FROM (' + actual_unique + ') u')
    for key in allowed_unique:
        guard('SELECT IF(COUNT(*)=1,1,0) FROM (' + actual_unique + ') u WHERE BINARY cols=BINARY ' + q(','.join(key)))
    guard('SELECT IF(COUNT(*)=' + ('1' if table == 'quality_digest_run' else '0')
          + ',1,0) FROM information_schema.referential_constraints WHERE constraint_schema=\'__SOURCE_SCHEMA__\' AND table_name=' + q(table))
    if table == 'quality_digest_run':
        guard("SELECT IF(COUNT(*)=1,1,0) FROM information_schema.referential_constraints r JOIN information_schema.key_column_usage k "
              "ON r.constraint_schema=k.constraint_schema AND r.constraint_name=k.constraint_name AND r.table_name=k.table_name "
              "WHERE BINARY r.constraint_schema=BINARY '__SOURCE_SCHEMA__' AND BINARY r.table_name=BINARY 'quality_digest_run' "
              "AND BINARY r.constraint_name=BINARY 'fk_digest_run_schedule' AND r.delete_rule='RESTRICT' AND r.update_rule='RESTRICT' "
              "AND k.column_name='schedule_id' AND k.ordinal_position=1 AND k.position_in_unique_constraint=1 "
              "AND BINARY k.referenced_table_schema=BINARY '__SOURCE_SCHEMA__' AND k.referenced_table_name='quality_digest_schedule' AND k.referenced_column_name='schedule_id'")
    checks = {'quality_digest_control': 'control_id=1',
              'quality_digest_run': "statusin'pending','running','completed','failed','blocked'"}
    guard('SELECT IF(COUNT(*)=' + ('1' if table in checks else '0')
          + ",1,0) FROM information_schema.table_constraints WHERE constraint_schema='__SOURCE_SCHEMA__' AND table_name=" + q(table) + " AND constraint_type='CHECK'")
    if table in checks:
        guard("SELECT IF(COUNT(*)=1,1,0) FROM information_schema.table_constraints t JOIN information_schema.check_constraints c "
              "ON t.constraint_schema=c.constraint_schema AND t.constraint_name=c.constraint_name "
              "WHERE BINARY t.constraint_schema=BINARY '__SOURCE_SCHEMA__' AND BINARY t.table_name=BINARY " + q(table)
              + " AND t.constraint_type='CHECK' AND t.enforced='YES' AND BINARY LOWER(REGEXP_REPLACE(REPLACE(c.check_clause,'_utf8mb4',''),'[`()[:space:]]',''))=BINARY " + q(checks[table]))
    emit('INSERT INTO compact_digest_sequences SELECT ' + q(table) + ',AUTO_INCREMENT FROM information_schema.tables WHERE ' + condition + ';')
    guard('SELECT IF(COUNT(*)<=50000,1,0) FROM `__SOURCE_SCHEMA__`.' + table)
    emit('INSERT INTO compact_digest_source_rows SELECT ' + q(table) + ',' + source_key(table) + ',' + row_hash(table)
         + ' FROM `__SOURCE_SCHEMA__`.' + table + ' s ORDER BY ' + ','.join('s.' + key for key in details['primaryKey']) + ';')
    guard('SELECT IF(COUNT(*)=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.' + table + ') AND OCTET_LENGTH(COALESCE(GROUP_CONCAT(row_sha ORDER BY row_key SEPARATOR \'\'),\'\'))=64*COUNT(*),1,0) FROM compact_digest_source_rows WHERE table_name=' + q(table))

# Preserve all other domains' ordinary target columns across this segment.
for table in ('workflow_instance', 'scheduled_plan', 'audit_event', 'runtime_state'):
    ordinary = [name for name, value in targets[table]['columns'].items() if 'GENERATED' not in value['declaration'].upper()]
    key = "CAST(JSON_ARRAY(namespace,owner_id,scope_key) AS CHAR CHARACTER SET utf8mb4)" if table == 'runtime_state' else 'CAST(id AS CHAR)'
    digest = 'SHA2(CAST(JSON_ARRAY(' + ','.join('`' + name + '`' for name in ordinary) + ') AS CHAR CHARACTER SET utf8mb4),256)'
    emit('INSERT INTO compact_digest_existing SELECT ' + q(table) + ',' + key + ',' + digest + ' FROM ' + table + ';')

guard("SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.quality_digest_control WHERE control_id<>1")
guard("SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.quality_digest_schedule WHERE owner_user_id<=0 OR version<0 OR CHAR_LENGTH(schedule_id) NOT BETWEEN 1 AND 64 OR CHAR_LENGTH(owner_username)>100 OR enabled NOT IN (0,1)")
guard("SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.quality_digest_run r LEFT JOIN `__SOURCE_SCHEMA__`.quality_digest_schedule s ON r.schedule_id=s.schedule_id WHERE s.id IS NULL OR r.owner_user_id<>s.owner_user_id OR r.owner_user_id<=0 OR r.status NOT IN ('PENDING','RUNNING','COMPLETED','FAILED','BLOCKED') OR (r.status='RUNNING' AND (r.claim_token IS NULL OR r.lease_until IS NULL)) OR ((r.snapshot_json IS NULL)<>(r.snapshot_sha256 IS NULL)) OR (r.snapshot_sha256 IS NOT NULL AND NOT REGEXP_LIKE(r.snapshot_sha256,'^[a-f0-9]{64}$','c'))")
guard("SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.quality_digest_command WHERE actor_user_id<=0 OR NOT REGEXP_LIKE(request_sha256,'^[a-f0-9]{64}$','c')")
guard("SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.quality_digest_audit WHERE actor_user_id<=0 OR version<0 OR JSON_TYPE(detail_json)<>'OBJECT'")
# Source ids/high-water marks remain in raw source rows and the full source
# backup. Shared target sequences must also stay above those historical ids.
for target, source in [('workflow_instance', 'quality_digest_run'), ('audit_event', 'quality_digest_audit')]:
    emit("SET @compact_digest_shared_next=(SELECT GREATEST(COALESCE((SELECT AUTO_INCREMENT FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=" + q(target)
         + "),1),COALESCE((SELECT next_id FROM compact_digest_sequences WHERE table_name=" + q(source) + "),1)));")
    emit("SET @compact_digest_ddl=CONCAT('ALTER TABLE " + target + " AUTO_INCREMENT=',CAST(@compact_digest_shared_next AS CHAR));")
    emit('PREPARE compact_digest_statement FROM @compact_digest_ddl; EXECUTE compact_digest_statement; DEALLOCATE PREPARE compact_digest_statement;')
emit('SET @compact_digest_clock_begin=UTC_TIMESTAMP(6);')
emit('START TRANSACTION;')

schedule = {'id':'s.id','plan_id':'s.schedule_id','kind':q('DIGEST_SCHEDULE'),'owner_user_id':'s.owner_user_id',
 'owner_name':'s.owner_username','name':'s.name','cron_expression':'s.cron_expression','time_zone':q('Asia/Shanghai'),
 'enabled':'s.enabled','revision':'s.version','next_fire_at':'s.next_fire_at','payload_version':'1','payload_json':'JSON_OBJECT()',
 'created_at':'s.created_at','updated_at':'s.updated_at'}
run = {'workflow_id':'s.run_id','kind':q('DIGEST_RUN'),'idempotency_scope':"CONCAT('SCHEDULE:',s.schedule_id)",
 'request_id':'s.request_key','request_sha256':"SHA2(CONCAT('[',JSON_QUOTE(s.schedule_id),',',JSON_QUOTE(s.request_key),',',JSON_QUOTE(CAST(s.report_date AS CHAR)),']'),256)",
 'owner_user_id':'s.owner_user_id','actor_user_id':'s.owner_user_id','resource_type':q('SCHEDULE'),'resource_id':'s.schedule_id',
 'run_id':'s.run_id','status':'s.status','revision':'0','fence':"IF(s.status='RUNNING',1,0)",
 'claim_token':"IF(s.status='RUNNING',s.claim_token,NULL)",'lease_expires_at':"IF(s.status='RUNNING',s.lease_until,NULL)",
 'effective_date':'s.report_date','scheduled_for':'s.scheduled_for','error_code':'s.error_code','payload_version':'1',
 'payload_json':"JSON_OBJECT('scheduleId',s.schedule_id,'scheduledFor',DATE_FORMAT(s.scheduled_for,'%Y-%m-%dT%H:%i:%s.%f'),'reportDate',CAST(s.report_date AS CHAR))",
 'result_version':'IF(s.snapshot_json IS NULL,NULL,1)','result_json':'CAST(s.snapshot_json AS CHAR CHARACTER SET utf8mb4)',
 'result_sha256':'s.snapshot_sha256','created_at':'s.created_at','updated_at':'NULL','finished_at':'s.finished_at',
 'legacy_source':q('quality_digest_run'),'legacy_key':'CAST(s.id AS CHAR)','digest_legacy_row_json':row_json('quality_digest_run')}
command = {'workflow_id':"CONCAT('legacy-digest-cmd-',SHA2(CAST(JSON_ARRAY(s.actor_user_id,s.request_id) AS CHAR CHARACTER SET utf8mb4),256))",
 'kind':q('DIGEST_COMMAND'),'idempotency_scope':"CONCAT('OWNER:',s.actor_user_id)",'request_id':'s.request_id',
 'request_sha256':'s.request_sha256','owner_user_id':'s.actor_user_id','actor_user_id':'s.actor_user_id','resource_type':q('SCHEDULE'),
 'resource_id':'s.schedule_id','status':q('COMPLETED'),'payload_version':'1','payload_json':"JSON_OBJECT('scheduleId',s.schedule_id)",
 'created_at':'s.created_at','updated_at':'NULL','finished_at':'NULL','legacy_source':q('quality_digest_command'),
 'legacy_key':source_key('quality_digest_command'),'digest_legacy_row_json':row_json('quality_digest_command')}
audit = {'event_id':"CONCAT('legacy-digest-audit-',s.id)",'kind':q('DIGEST'),'owner_user_id':'s.actor_user_id','actor_user_id':'s.actor_user_id',
 'resource_type':q('SCHEDULE'),'resource_id':'s.schedule_id','action':'s.action_name','revision':'s.version',
 'run_id':optional_json_text('runId'),'content_sha256':optional_json_text('snapshotSha256'),
 'occurred_at':'s.created_at','payload_version':'1',
 'payload_json':"JSON_OBJECT("+','.join(q(name)+",JSON_EXTRACT(s.detail_json,"+q('$.'+name)+")" for name in ('cron','enabled','runId','reportDate','format','snapshotSha256'))+")",
 'legacy_source':q('quality_digest_audit'),'legacy_key':'CAST(s.id AS CHAR)',
 'digest_legacy_detail_json':'CAST(s.detail_json AS CHAR CHARACTER SET utf8mb4)'}

for table, source, values in [('scheduled_plan','quality_digest_schedule',schedule),('workflow_instance','quality_digest_run',run),('workflow_instance','quality_digest_command',command),('audit_event','quality_digest_audit',audit)]:
    require_columns = set(values) - set(targets[table]['columns'])
    if require_columns:raise ValueError('Shared digest DDL missing columns: '+str(sorted(require_columns)))
    emit('INSERT INTO '+table+'('+','.join(values)+') SELECT '+','.join(values.values())+' FROM `__SOURCE_SCHEMA__`.'+source+' s ORDER BY '+','.join('s.'+name for name in tables[source]['primaryKey'])+';')
emit("INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,created_at,updated_at) SELECT 'DIGEST_CONTROL',0,CAST(control_id AS CHAR),0,NULL,UTC_TIMESTAMP(6) FROM `__SOURCE_SCHEMA__`.quality_digest_control;")

# Check every original field, explicit new field and every otherwise-unused ordinary column.
for target, source, values, join in [
 ('scheduled_plan','quality_digest_schedule',schedule,"t.kind='DIGEST_SCHEDULE' AND BINARY t.plan_id=BINARY s.schedule_id"),
 ('workflow_instance','quality_digest_run',run,"t.kind='DIGEST_RUN' AND BINARY t.legacy_key=BINARY CAST(s.id AS CHAR)"),
 ('workflow_instance','quality_digest_command',command,"t.kind='DIGEST_COMMAND' AND BINARY t.legacy_key=BINARY "+source_key('quality_digest_command')),
 ('audit_event','quality_digest_audit',audit,"t.kind='DIGEST' AND BINARY t.legacy_key=BINARY CAST(s.id AS CHAR)"),
]:
    predicate="kind='DIGEST_SCHEDULE'" if target=='scheduled_plan' else "legacy_source="+q(source)
    guard('SELECT IF((SELECT COUNT(*) FROM '+target+' WHERE '+predicate+')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.'+source+'),1,0)')
    conditions=[]
    for column, definition in targets[target]['columns'].items():
        if 'GENERATED' in definition['declaration'].upper() or (column=='id' and source!='quality_digest_schedule'):continue
        expected=values.get(column)
        if expected is None:
            expected='0' if column in ('revision','fence','attempts') else 'NULL'
        if column=='payload_json':
            conditions.append('NOT(CAST(t.payload_json AS JSON)<=>CAST('+expected+' AS JSON))')
        elif column=='digest_legacy_row_json':
            conditions.append('NOT(CAST(t.digest_legacy_row_json AS JSON)<=>CAST('+expected+' AS JSON))')
        else:
            conditions.append('NOT(BINARY t.`'+column+'`<=>BINARY '+expected+')')
    guard('SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.'+source+' s LEFT JOIN '+target+' t ON '+join+' WHERE t.id IS NULL OR '+' OR '.join(conditions))
guard("SELECT IF((SELECT COUNT(*) FROM runtime_state WHERE namespace='DIGEST_CONTROL')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.quality_digest_control),1,0)")
control_expected = {'namespace':q('DIGEST_CONTROL'),'owner_id':'0','scope_key':'CAST(s.control_id AS CHAR)','revision':'0',
                    'created_at':'NULL'}
control_conditions = []
for column, definition in targets['runtime_state']['columns'].items():
    if 'GENERATED' in definition['declaration'].upper():continue
    if column == 'updated_at':
        control_conditions.append('(t.updated_at IS NULL OR t.updated_at<@compact_digest_clock_begin OR t.updated_at>UTC_TIMESTAMP(6))')
    else:
        control_conditions.append('NOT(BINARY t.`'+column+'`<=>BINARY '+control_expected.get(column,'NULL')+')')
guard("SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.quality_digest_control s LEFT JOIN runtime_state t ON t.namespace='DIGEST_CONTROL' AND t.owner_id=0 AND BINARY t.scope_key=BINARY CAST(s.control_id AS CHAR) WHERE t.namespace IS NULL OR "+' OR '.join(control_conditions))

for table, details in tables.items():
    guard('SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.'+table+' s LEFT JOIN compact_digest_source_rows p ON p.table_name='+q(table)+' AND BINARY p.row_key=BINARY '+source_key(table)+' WHERE p.row_key IS NULL OR BINARY p.row_sha<>BINARY '+row_hash(table))
    guard('SELECT IF(COUNT(*)=(SELECT COUNT(*) FROM compact_digest_source_rows WHERE table_name='+q(table)+'),1,0) FROM `__SOURCE_SCHEMA__`.'+table)
    guard('SELECT IF(COUNT(*)=0,1,0) FROM compact_digest_sequences p JOIN information_schema.tables s ON BINARY s.table_schema=BINARY \'__SOURCE_SCHEMA__\' AND BINARY s.table_name=BINARY p.table_name WHERE NOT(s.auto_increment<=>p.next_id)')
for table in ('workflow_instance','scheduled_plan','audit_event','runtime_state'):
    ordinary=[name for name,value in targets[table]['columns'].items() if 'GENERATED' not in value['declaration'].upper()]
    key="CAST(JSON_ARRAY(t.namespace,t.owner_id,t.scope_key) AS CHAR CHARACTER SET utf8mb4)" if table=='runtime_state' else 'CAST(t.id AS CHAR)'
    digest='SHA2(CAST(JSON_ARRAY('+','.join('t.`'+name+'`' for name in ordinary)+') AS CHAR CHARACTER SET utf8mb4),256)'
    guard('SELECT IF(COUNT(*)=0,1,0) FROM compact_digest_existing p LEFT JOIN '+table+' t ON BINARY p.row_key=BINARY '+key+' WHERE p.table_name='+q(table)+' AND (t.'+('namespace' if table=='runtime_state' else 'id')+' IS NULL OR BINARY p.row_sha<>BINARY '+digest+')')
emit('COMMIT;')
emit('SET SESSION group_concat_max_len=@compact_digest_old_concat;')
emit('-- Explicit schedule AUTO_INCREMENT preserves deleted historical high-water marks, not merely MAX(id)+1.')
emit("SET @compact_digest_next=(SELECT next_id FROM compact_digest_sequences WHERE table_name='quality_digest_schedule');")
emit("SET @compact_digest_ddl=CONCAT('ALTER TABLE scheduled_plan AUTO_INCREMENT=',CAST(@compact_digest_next AS CHAR));")
emit('PREPARE compact_digest_statement FROM @compact_digest_ddl; EXECUTE compact_digest_statement; DEALLOCATE PREPARE compact_digest_statement;')
guard("SELECT IF(AUTO_INCREMENT=@compact_digest_next,1,0) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='scheduled_plan'")
destination=ROOT/'sql/mysql/compact/copy/49-digests.sql'
destination.write_text('\n'.join(output)+'\n',encoding='utf8')
