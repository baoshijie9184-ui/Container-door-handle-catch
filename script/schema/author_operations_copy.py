"""Author operations/file-delivery migration from the actual V40/V52 source DDL; never connect to a database."""
from pathlib import Path
import importlib.util
import json
import re

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('compact_parser',ROOT/'script/schema/build_compact_schema.py')
parser=importlib.util.module_from_spec(spec);spec.loader.exec_module(parser)
def q(value):return 'NULL' if value is None else "'"+str(value).replace("'","''")+"'"
sources={};ddl=[]
for file,name in [('migration-V40-stable-identity-audit.sql','operations_audit'),('migration-V52-file-delivery-audit.sql','operations_file_delivery')]:
    statement=next(s for s in parser.split_top_level(parser.without_comments((ROOT/'sql/mysql'/file).read_text(encoding='utf-8')),';') if re.match(r'CREATE TABLE IF NOT EXISTS '+name+r'\b',s))
    statement=statement.replace('CREATE TABLE IF NOT EXISTS','CREATE TABLE',1)
    sources[name]=parser.parse_table(statement,file);ddl.append(statement+';')

rows=[]
for name,table in sources.items():
    for column,definition in table['columns'].items():
        dec=definition['declaration']
        kind=re.match(parser.IDENT+r'\s+([a-z]+(?:\([^)]*\))?(?:\s+UNSIGNED)?)',dec,re.I).group(2).lower()
        coll=(definition['collation'] or 'utf8mb4_0900_ai_ci') if kind.startswith(('varchar','char')) else None
        nullable='NO' if column in table['primaryKey'] or 'NOT NULL' in dec.upper() else 'YES'
        match=re.search(r'\bDEFAULT\s+(NULL|CURRENT_TIMESTAMP\(6\)|\d+)',dec,re.I)
        default=match.group(1).lower() if match and match.group(1).upper()!='NULL' else None
        extra='auto_increment' if 'AUTO_INCREMENT' in dec.upper() else 'default_generated' if default=='current_timestamp(6)' else ''
        rows.append((name,column,kind,nullable,coll,default,extra))

sql=[]
def emit(text):sql.append(text)
def guard(query):emit('INSERT INTO compact_operations_guard '+query+';')
emit('''-- Operations/file delivery copy candidate, NOT EXECUTED. Source is actual V40/V52 DDL, not renamed target DDL.
-- Use distinct, stopped source/target schemas; render source identifier and the evidenced fixed source UTC offset explicitly.
-- Target public DDL must already exist, with empty OPERATIONS/FILE_DELIVERY kinds. Other domains may already be copied.
-- Stop at the first error and ROLLBACK on this same connection. Never --force. No source UPDATE/DELETE/DROP.
-- Shared target IDs are new cursor identities; original IDs and DATETIME(6) strings remain in payload + legacy provenance.
SET NAMES utf8mb4;
CREATE TEMPORARY TABLE compact_operations_guard(valid INT NOT NULL CHECK(valid=1)) ENGINE=InnoDB;''')
guard("SELECT IF(DATABASE() IS NOT NULL AND BINARY DATABASE()<>BINARY '__SOURCE_SCHEMA__' AND @@FOREIGN_KEY_CHECKS=1 AND @@SESSION.sql_mode REGEXP '(^|,)(STRICT_TRANS_TABLES|STRICT_ALL_TABLES)(,|$)',1,0)")
guard("SELECT IF(REGEXP_LIKE('__SOURCE_OPERATIONS_OFFSET__','^[+-][0-9]{2}:[0-9]{2}$','c') AND CONVERT_TZ('2026-01-01','__SOURCE_OPERATIONS_OFFSET__','+00:00') IS NOT NULL,1,0)")
guard("SELECT IF(COUNT(DISTINCT privilege_type)=2,1,0) FROM information_schema.schema_privileges WHERE table_schema='__SOURCE_SCHEMA__' AND privilege_type IN ('SELECT','TRIGGER') AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)))")
emit('CREATE TEMPORARY TABLE compact_operations_columns(table_name VARCHAR(64),column_name VARCHAR(64),column_type VARCHAR(64),nullable VARCHAR(3),collation_name VARCHAR(64),default_value VARCHAR(64),extra VARCHAR(64),PRIMARY KEY(table_name,column_name)) ENGINE=InnoDB;')
emit('INSERT INTO compact_operations_columns VALUES\n'+',\n'.join('('+','.join(map(q,row))+')' for row in rows)+';')
names="('operations_audit','operations_file_delivery')"
guard("SELECT IF(COUNT(*)=2,1,0) FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+" AND table_type='BASE TABLE' AND engine='InnoDB'")
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.columns c LEFT JOIN compact_operations_columns e ON e.table_name=c.table_name AND e.column_name=c.column_name WHERE c.table_schema='__SOURCE_SCHEMA__' AND c.table_name IN "+names+" AND e.column_name IS NULL")
guard("SELECT IF(COUNT(*)=0,1,0) FROM compact_operations_columns e LEFT JOIN information_schema.columns c ON c.table_schema='__SOURCE_SCHEMA__' AND c.table_name=e.table_name AND c.column_name=e.column_name WHERE c.column_name IS NULL OR NOT(BINARY LOWER(c.column_type)<=>BINARY e.column_type) OR NOT(c.is_nullable<=>e.nullable) OR NOT(c.collation_name<=>e.collation_name) OR NOT(LOWER(c.column_default)<=>e.default_value) OR NOT(LOWER(c.extra)<=>e.extra) OR c.generation_expression<>''")
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.triggers WHERE event_object_schema='__SOURCE_SCHEMA__' AND event_object_table IN "+names)
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.table_constraints WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+" AND constraint_type IN ('FOREIGN KEY','CHECK')")
emit('CREATE TEMPORARY TABLE compact_operations_unique_keys(table_name VARCHAR(64),primary_key BOOLEAN,key_columns VARCHAR(1024)) ENGINE=InnoDB;')
emit("INSERT INTO compact_operations_unique_keys VALUES ('operations_audit',TRUE,'id'),('operations_audit',FALSE,'actor_user_id,domain,action,resource_id,request_id,result'),('operations_file_delivery',TRUE,'id'),('operations_file_delivery',FALSE,'delivery_id');")
actual="(SELECT table_name,(index_name='PRIMARY') AS primary_key,GROUP_CONCAT(column_name ORDER BY seq_in_index) AS key_columns,SUM(sub_part IS NOT NULL) AS prefixes FROM information_schema.statistics WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+" AND non_unique=0 GROUP BY table_name,index_name)"
guard('SELECT IF(COUNT(*)=0,1,0) FROM '+actual+' a LEFT JOIN compact_operations_unique_keys e ON e.table_name=a.table_name AND e.primary_key=a.primary_key AND e.key_columns=a.key_columns WHERE e.table_name IS NULL OR a.prefixes<>0')
guard('SELECT IF(COUNT(*)=0,1,0) FROM compact_operations_unique_keys e LEFT JOIN '+actual+' a ON e.table_name=a.table_name AND e.primary_key=a.primary_key AND e.key_columns=a.key_columns WHERE a.table_name IS NULL')
guard("SELECT IF(COUNT(*)=0,1,0) FROM audit_event WHERE kind='OPERATIONS' OR legacy_source='operations_audit'")
guard("SELECT IF(COUNT(*)=0,1,0) FROM workflow_instance WHERE kind='FILE_DELIVERY' OR legacy_source='operations_file_delivery'")
def invalid_time(column):
    value=f"s.{column}"
    converted=f"CONVERT_TZ({value},'__SOURCE_OPERATIONS_OFFSET__','+00:00')"
    offset="(IF(LEFT('__SOURCE_OPERATIONS_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_OPERATIONS_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_OPERATIONS_OFFSET__',5,2) AS UNSIGNED)*60))"
    # A non-NULL result may be unchanged outside CONVERT_TZ's supported range.
    return f"{converted} IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,{converted},{value})<=>({offset}*1000000))"

for name,table in sources.items():
    bad=["s.actor_user_id<=0","BINARY s.scope NOT IN (BINARY 'PRIVATE',BINARY 'ENTERPRISE')",invalid_time('created_at')]
    for column in ['domain','resource_id']+(['action','request_id','result'] if name=='operations_audit' else ['file_id','correlation_id']):
        bad.append(f"(s.{column} IS NOT NULL AND (CHAR_LENGTH(s.{column})=0 OR REGEXP_LIKE(s.{column},'[^A-Za-z0-9_:./-]','c')))")
    if name=='operations_file_delivery':
        bad += ["NOT REGEXP_LIKE(s.delivery_id,'^[a-fA-F0-9]{8}(-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}$','c')","s.revision<0","s.expected_bytes<0","s.accepted_bytes_lower_bound<0","s.http_status IS NOT NULL AND (s.http_status<100 OR s.http_status>599)","BINARY s.state NOT IN (BINARY 'AUTHORIZED',BINARY 'HEAD_AUTHORIZED',BINARY 'STREAMING',BINARY 'UNKNOWN',BINARY 'SERVER_COMPLETED',BINARY 'HEAD_COMPLETED',BINARY 'INTERRUPTED',BINARY 'REDIRECT_AUTHORIZED')",invalid_time('updated_at')]
    guard(f"SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.`{name}` s WHERE "+' OR '.join('('+b+')' for b in bad))

def time(column):return f"CONVERT_TZ(s.{column},'__SOURCE_OPERATIONS_OFFSET__','+00:00')"
def original(column):return f"DATE_FORMAT(s.{column},'%Y-%m-%d %H:%i:%s.%f')"
audit_payload="JSON_OBJECT('scope',s.scope,'domain',s.domain,'result',s.result,'resourceVersion',s.resource_version,'legacyId',CAST(s.id AS CHAR),'legacyCreatedAt',"+original('created_at')+")"
mode="CASE WHEN s.state IN ('AUTHORIZED','STREAMING','SERVER_COMPLETED') THEN 'BODY' WHEN s.state IN ('HEAD_AUTHORIZED','HEAD_COMPLETED') THEN 'HEAD' WHEN s.state='REDIRECT_AUTHORIZED' THEN 'REDIRECT' ELSE 'UNKNOWN' END"
delivery_payload="JSON_OBJECT('scope',s.scope,'domain',s.domain,'fileId',s.file_id,'correlationId',s.correlation_id,'resourceVersion',s.resource_version,'expectedBytes',s.expected_bytes,'acceptedBytesLowerBound',s.accepted_bytes_lower_bound,'httpStatus',s.http_status,'deliveryMode',"+mode+",'legacyId',CAST(s.id AS CHAR),'legacyCreatedAt',"+original('created_at')+",'legacyUpdatedAt',"+original('updated_at')+")"
digest="SHA2(CONCAT_WS(CHAR(10),CAST(s.actor_user_id AS CHAR),s.scope,s.domain,s.resource_id,COALESCE(s.file_id,'~'),s.correlation_id,COALESCE(CAST(s.resource_version AS CHAR),'~'),COALESCE(CAST(s.expected_bytes AS CHAR),'~'),"+mode+"),256)"
finished="CASE WHEN s.state IN ('SERVER_COMPLETED','HEAD_COMPLETED','INTERRUPTED','REDIRECT_AUTHORIZED') THEN "+time('updated_at')+" ELSE NULL END"
emit('START TRANSACTION;')
emit("INSERT INTO audit_event(event_id,kind,owner_user_id,actor_user_id,resource_type,resource_id,request_id,action,occurred_at,payload_version,payload_json,legacy_source,legacy_key) SELECT CONCAT('legacy-operations-',s.id),'OPERATIONS',s.actor_user_id,s.actor_user_id,'OPERATIONS',s.resource_id,s.request_id,s.action,"+time('created_at')+",1,"+audit_payload+",'operations_audit',CAST(s.id AS CHAR) FROM `__SOURCE_SCHEMA__`.operations_audit s ORDER BY s.id;")
emit("INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,actor_user_id,resource_type,resource_id,status,revision,payload_version,payload_json,created_at,updated_at,finished_at,legacy_source,legacy_key) SELECT s.delivery_id,'FILE_DELIVERY','FILE_DELIVERY',s.delivery_id,"+digest+",s.actor_user_id,s.actor_user_id,'FILE_DELIVERY',s.resource_id,s.state,s.revision,1,"+delivery_payload+","+time('created_at')+","+time('updated_at')+","+finished+",'operations_file_delivery',CAST(s.id AS CHAR) FROM `__SOURCE_SCHEMA__`.operations_file_delivery s ORDER BY s.id;")
for table,kind,source in [('audit_event','OPERATIONS','operations_audit'),('workflow_instance','FILE_DELIVERY','operations_file_delivery')]:
    guard(f"SELECT IF((SELECT COUNT(*) FROM {table} WHERE kind='{kind}')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.{source}),1,0)")

target_tables={}
for statement in parser.split_top_level(parser.without_comments((ROOT/'sql/mysql/compact/baseline/30-operations.sql').read_text(encoding='utf-8')),';'):
    if re.match(r'CREATE TABLE (audit_event|workflow_instance)\b',statement):
        table=parser.parse_table(statement,'30-operations.sql')
        target_tables[table['name']]=table

def compare(target,source,checks):
    checks=[f"BINARY t.legacy_source<=>BINARY '{source}'","BINARY t.legacy_key<=>BINARY CAST(s.id AS CHAR)",*checks]
    checked={column for condition in checks for column in re.findall(r'\bt\.([a-z_][a-z0-9_]*)',condition)}
    for column,definition in target_tables[target]['columns'].items():
        declaration=definition['declaration'].upper()
        if column=='id' or column in checked or 'GENERATED ALWAYS' in declaration:
            continue
        if 'NOT NULL' in declaration:
            raise ValueError(f'Unreviewed required target column: {target}.{column}')
        checks.append(f't.{column} IS NULL')
    guard(f"SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.{source} s LEFT JOIN {target} t ON BINARY t.legacy_source=BINARY '{source}' AND BINARY t.legacy_key=BINARY CAST(s.id AS CHAR) WHERE t.id IS NULL OR "+' OR '.join('NOT('+check+')' for check in checks))
compare('audit_event','operations_audit',[
    "BINARY t.kind<=>BINARY 'OPERATIONS'","BINARY t.event_id<=>BINARY CONCAT('legacy-operations-',s.id)","t.owner_user_id<=>s.actor_user_id","t.actor_user_id<=>s.actor_user_id","BINARY t.resource_type<=>BINARY 'OPERATIONS'","BINARY t.resource_id<=>BINARY s.resource_id","BINARY t.request_id<=>BINARY s.request_id","BINARY t.action<=>BINARY s.action","t.revision IS NULL","t.request_scope IS NULL","t.payload_version<=>1","BINARY t.payload_json<=>BINARY "+audit_payload,"t.occurred_at<=>"+time('created_at')])
compare('workflow_instance','operations_file_delivery',[
    "BINARY t.kind<=>BINARY 'FILE_DELIVERY'","BINARY t.workflow_id<=>BINARY s.delivery_id","BINARY t.request_id<=>BINARY s.delivery_id","BINARY t.idempotency_scope<=>BINARY 'FILE_DELIVERY'","BINARY t.request_sha256<=>BINARY "+digest,"t.owner_user_id<=>s.actor_user_id","t.actor_user_id<=>s.actor_user_id","BINARY t.resource_type<=>BINARY 'FILE_DELIVERY'","BINARY t.resource_id<=>BINARY s.resource_id","t.resource_revision IS NULL","BINARY t.status<=>BINARY s.state","t.revision<=>s.revision","t.payload_version<=>1","BINARY t.payload_json<=>BINARY "+delivery_payload,"t.created_at<=>"+time('created_at'),"t.updated_at<=>"+time('updated_at'),"t.finished_at<=>"+finished,"t.claim_token IS NULL","t.lease_expires_at IS NULL","t.expires_at IS NULL","t.parent_workflow_id IS NULL","t.session_id IS NULL","t.run_id IS NULL","t.fence<=>0","t.attempts<=>0"])
emit('COMMIT;\nDROP TEMPORARY TABLE compact_operations_unique_keys;\nDROP TEMPORARY TABLE compact_operations_columns;\nDROP TEMPORARY TABLE compact_operations_guard;')
(ROOT/'sql/mysql/compact/copy/37-operations-file-delivery.sql').write_text('\n'.join(sql)+'\n',encoding='utf-8')
fixture=ROOT/'doorhandle-module-system/src/test/resources/compact/operations-source-evidence.sql'
fixture.parent.mkdir(parents=True,exist_ok=True);fixture.write_text('-- Actual V40/V52 table statements; no legacy task ALTERs or invented target-shaped source.\n'+'\n'.join(ddl)+'\n',encoding='utf-8')
print(json.dumps({'status':'AUTHORED_NOT_EXECUTED','sourceTables':len(sources),'sourceColumns':len(rows)}))
