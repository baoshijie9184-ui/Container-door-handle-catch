"""Author copy24 from actual V44/V45/V66 declarations; never connects to a database."""
from pathlib import Path
import importlib.util
import json
import re

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('compact_parser',ROOT/'script/schema/build_compact_schema.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
source_files={'agent_message_execution':'migration-V66-chat-message-execution.sql','agent_workspace_turn_snapshot':'migration-V45-workspace-turn-snapshot.sql','agent_context_turn':'migration-V44-agent-durable-context.sql'}
tables={}
for name,file in source_files.items():
    for statement in p.split_top_level(p.without_comments((ROOT/'sql/mysql'/file).read_text(encoding='utf-8')),';'):
        if statement.startswith('CREATE TABLE'):
            table=p.parse_table(statement.replace('CREATE TABLE IF NOT EXISTS','CREATE TABLE',1),file)
            if table['name']==name:tables[name]=table
def q(v):return 'NULL' if v is None else "'"+str(v).replace("'","''")+"'"
sql=[]
def emit(v):sql.append(v)
def guard(v):emit('INSERT INTO compact_chat_evidence_guard '+v+';')
names='('+','.join(map(q,tables))+')'
rows=[]
for name,table in tables.items():
    for column,c in table['columns'].items():
        declaration=c['declaration'];kind=c['type'].lower()
        coll=(c['collation'] or 'utf8mb4_0900_ai_ci') if kind.startswith(('varchar','char','mediumtext','text')) else None
        clock=bool(re.search(r'DEFAULT\s+CURRENT_TIMESTAMP\(6\)',declaration,re.I))
        rows.append((name,column,kind,'NO',coll,'current_timestamp(6)' if clock else None,'auto_increment' if 'AUTO_INCREMENT' in declaration.upper() else 'default_generated' if clock else ''))
emit('''-- Independent V44/V45/V66 message evidence copy: AUTHORED_NOT_EXECUTED.
-- Distinct schemas, stopped source writers. __SOURCE_CHAT_OFFSET__ must be an evidenced DATETIME offset.
-- Run after ordinary chat rows are copied if current projections are required. Missing parents never discard evidence.
-- Old ids remain source identities; audit.id is an independent cursor. Preserve source AUTO_INCREMENT metadata in the migration receipt/backup.
-- No source DML, no sequence rewrite, no source FK, no inferred owner/session/run/time.
-- One connection; stop at the first error, ROLLBACK there, then close. Never --force.
SET NAMES utf8mb4;
CREATE TEMPORARY TABLE compact_chat_evidence_guard(valid INT NOT NULL CHECK(valid=1)) ENGINE=InnoDB;''')
guard("SELECT IF(DATABASE() IS NOT NULL AND BINARY DATABASE()<>BINARY '__SOURCE_SCHEMA__' AND @@FOREIGN_KEY_CHECKS=1 AND @@SESSION.sql_mode REGEXP '(^|,)(STRICT_TRANS_TABLES|STRICT_ALL_TABLES)(,|$)' AND '__SOURCE_CHAT_OFFSET__' REGEXP '^[+-][0-9]{2}:[0-9]{2}$' AND CONVERT_TZ('2026-01-01 00:00:00','__SOURCE_CHAT_OFFSET__','+00:00') IS NOT NULL,1,0)")
guard("SELECT IF(COUNT(DISTINCT privilege_type)=2,1,0) FROM information_schema.schema_privileges WHERE table_schema='__SOURCE_SCHEMA__' AND privilege_type IN ('SELECT','TRIGGER') AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)))")
emit('CREATE TEMPORARY TABLE compact_chat_evidence_columns(table_name VARCHAR(64),column_name VARCHAR(64),column_type VARCHAR(64),nullable VARCHAR(3),collation_name VARCHAR(64),default_value VARCHAR(64),extra VARCHAR(64),PRIMARY KEY(table_name,column_name)) ENGINE=InnoDB;')
emit('INSERT INTO compact_chat_evidence_columns VALUES '+','.join('('+','.join(map(q,row))+')' for row in rows)+';')
guard("SELECT IF(COUNT(*)=3,1,0) FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+" AND table_type='BASE TABLE' AND engine='InnoDB'")
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.columns c LEFT JOIN compact_chat_evidence_columns e ON e.table_name=c.table_name AND e.column_name=c.column_name WHERE c.table_schema='__SOURCE_SCHEMA__' AND c.table_name IN "+names+" AND e.column_name IS NULL")
guard("SELECT IF(COUNT(*)=0,1,0) FROM compact_chat_evidence_columns e LEFT JOIN information_schema.columns c ON c.table_schema='__SOURCE_SCHEMA__' AND c.table_name=e.table_name AND c.column_name=e.column_name WHERE c.column_name IS NULL OR NOT(BINARY LOWER(c.column_type)<=>BINARY e.column_type) OR NOT(c.is_nullable<=>e.nullable) OR NOT(c.collation_name<=>e.collation_name) OR NOT(LOWER(c.column_default)<=>e.default_value) OR NOT(LOWER(c.extra)<=>e.extra) OR c.generation_expression<>''")
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.triggers WHERE event_object_schema='__SOURCE_SCHEMA__' AND event_object_table IN "+names)
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.table_constraints WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+" AND constraint_type IN ('FOREIGN KEY','CHECK')")
emit('CREATE TEMPORARY TABLE compact_chat_evidence_keys(table_name VARCHAR(64),is_primary BOOLEAN,key_columns VARCHAR(1024)) ENGINE=InnoDB;')
keys=[(name,primary,','.join(columns)) for name,t in tables.items() for primary,columns in [(1,t['primaryKey']),*((0,key) for key in t['uniqueKeys'])]]
emit('INSERT INTO compact_chat_evidence_keys VALUES '+','.join('('+q(name)+','+str(primary)+','+q(cols)+')' for name,primary,cols in keys)+';')
actual="(SELECT table_name,(index_name='PRIMARY') is_primary,GROUP_CONCAT(column_name ORDER BY seq_in_index) key_columns,SUM(sub_part IS NOT NULL) prefixes FROM information_schema.statistics WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+" AND non_unique=0 GROUP BY table_name,index_name)"
guard('SELECT IF(COUNT(*)=0,1,0) FROM '+actual+' a LEFT JOIN compact_chat_evidence_keys e ON e.table_name=a.table_name AND e.is_primary=a.is_primary AND e.key_columns=a.key_columns WHERE e.table_name IS NULL OR a.prefixes<>0')
guard('SELECT IF(COUNT(*)=0,1,0) FROM compact_chat_evidence_keys e LEFT JOIN '+actual+' a ON e.table_name=a.table_name AND e.is_primary=a.is_primary AND e.key_columns=a.key_columns WHERE a.table_name IS NULL')
kinds={'agent_message_execution':'MESSAGE_EXECUTION','agent_workspace_turn_snapshot':'MESSAGE_WORKSPACE_SNAPSHOT','agent_context_turn':'MESSAGE_CONTEXT_SOURCES'}
guard("SELECT IF(COUNT(*)=0,1,0) FROM audit_event WHERE kind IN ("+','.join(map(q,kinds.values()))+") OR legacy_source IN "+names)
guard("SELECT IF(COUNT(*)=0,1,0) FROM chat_message WHERE execution_run_id IS NOT NULL OR execution_owner_user_id IS NOT NULL OR execution_created_at IS NOT NULL OR execution_legacy_id IS NOT NULL OR execution_evidence_id IS NOT NULL OR snapshot_owner_user_id IS NOT NULL OR workspace_snapshot_json IS NOT NULL OR workspace_snapshot_sha256 IS NOT NULL OR workspace_snapshot_created_at IS NOT NULL OR workspace_snapshot_legacy_id IS NOT NULL OR snapshot_evidence_id IS NOT NULL OR context_owner_user_id IS NOT NULL OR context_sources_json IS NOT NULL OR context_sources_sha256 IS NOT NULL OR context_evidence_id IS NOT NULL")
for name in tables:
    guard(f"SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.{name} WHERE user_id<=0 OR message_id<=0")
offset_seconds="(IF(LEFT('__SOURCE_CHAT_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_CHAT_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_CHAT_OFFSET__',5,2) AS SIGNED)*60))"
for name in ['agent_message_execution','agent_workspace_turn_snapshot']:
    utc="CONVERT_TZ(created_at,'__SOURCE_CHAT_OFFSET__','+00:00')"
    # CONVERT_TZ can return an unchanged DATETIME outside its supported range, not only NULL.
    # Require the actual change to match the evidenced offset before labelling the result UTC.
    guard(f"SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.{name} WHERE NOT COALESCE(({utc} IS NOT NULL AND TIMESTAMPDIFF(SECOND,{utc},created_at)={offset_seconds}),FALSE)")
for name,body,digest in [('agent_workspace_turn_snapshot','snapshot_json','snapshot_sha256'),('agent_context_turn','sources_json','sources_sha256')]:
    guard(f"SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.{name} WHERE NOT JSON_VALID({body}) OR NOT REGEXP_LIKE({digest},'^[A-Fa-f0-9]{{64}}$','c') OR NOT(BINARY LOWER({digest})<=>BINARY SHA2({body},256))")
payloads={
 'agent_message_execution':"JSON_OBJECT('legacyId',CAST(s.id AS CHAR),'createdAtSource',DATE_FORMAT(s.created_at,'%Y-%m-%d %H:%i:%s.%f'),'sourceUtcOffset','__SOURCE_CHAT_OFFSET__')",
 'agent_workspace_turn_snapshot':"JSON_OBJECT('legacyId',CAST(s.id AS CHAR),'snapshotJson',s.snapshot_json,'createdAtSource',DATE_FORMAT(s.created_at,'%Y-%m-%d %H:%i:%s.%f'),'sourceUtcOffset','__SOURCE_CHAT_OFFSET__')",
 'agent_context_turn':"JSON_OBJECT('sourcesJson',s.sources_json)"}
legacy={name:("CAST(s.id AS CHAR)" if name!='agent_context_turn' else "CONCAT(s.user_id,':',CHAR_LENGTH(s.session_id),':',s.session_id,':',s.message_id)") for name in tables}
occurred={name:("NULL" if name=='agent_context_turn' else "CONVERT_TZ(s.created_at,'__SOURCE_CHAT_OFFSET__','+00:00')") for name in tables}
digests={'agent_message_execution':'SHA2('+payloads['agent_message_execution']+',256)','agent_workspace_turn_snapshot':'s.snapshot_sha256','agent_context_turn':'s.sources_sha256'}
events={name:("CONCAT('legacy-chat-execution-',s.id)" if name=='agent_message_execution' else "CONCAT('legacy-chat-snapshot-',s.id)" if name=='agent_workspace_turn_snapshot' else "SHA2(CONCAT('agent_context_turn:',"+legacy[name]+"),256)") for name in tables}
emit('START TRANSACTION;')
final_audit_guards=[]
for name,kind in kinds.items():
    run='s.run_id' if name=='agent_message_execution' else 'NULL'
    emit(f"INSERT INTO audit_event(event_id,kind,owner_user_id,resource_type,resource_id,session_id,message_id,run_id,action,content_sha256,occurred_at,payload_version,payload_json,legacy_source,legacy_key) SELECT {events[name]},'{kind}',s.user_id,'CHAT_MESSAGE',CAST(s.message_id AS CHAR),s.session_id,s.message_id,{run},'RECORDED',{digests[name]},{occurred[name]},1,{payloads[name]},'{name}',{legacy[name]} FROM `__SOURCE_SCHEMA__`.{name} s;")
    guard(f"SELECT IF((SELECT COUNT(*) FROM audit_event WHERE kind='{kind}')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.{name}),1,0)")
    final_audit_guards.append(sql.pop())
    checks=[f"BINARY t.event_id<=>BINARY {events[name]}",f"BINARY t.kind<=>BINARY '{kind}'",'t.owner_user_id<=>s.user_id','t.actor_user_id IS NULL',"BINARY t.resource_type<=>BINARY 'CHAT_MESSAGE'",'BINARY t.resource_id<=>BINARY CAST(s.message_id AS CHAR)','BINARY t.session_id<=>BINARY s.session_id','t.message_id<=>s.message_id','BINARY t.run_id<=>BINARY '+run,"BINARY t.action<=>BINARY 'RECORDED'",'BINARY t.content_sha256<=>BINARY '+digests[name],'t.occurred_at<=>'+occurred[name],'t.payload_version<=>1','BINARY t.payload_json<=>BINARY '+payloads[name],f"BINARY t.legacy_source<=>BINARY '{name}'",'BINARY t.legacy_key<=>BINARY '+legacy[name]]
    checks += ['t.'+c+' IS NULL' for c in ['request_id','request_scope','revision','sequence_no','quantity','unit','outcome','observed_at','policy_version','previous_sha256','event_sha256','detection_model_id']]
    guard(f"SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.{name} s LEFT JOIN audit_event t ON BINARY t.legacy_source=BINARY '{name}' AND BINARY t.legacy_key=BINARY {legacy[name]} WHERE t.id IS NULL OR "+' OR '.join('NOT('+c+')' for c in checks))
    final_audit_guards.append(sql.pop())
# Only exact original identity matches may become current projections. Orphans remain durable audit rows.
emit('CREATE TEMPORARY TABLE compact_chat_projection(kind VARCHAR(48),legacy_key VARCHAR(512) COLLATE utf8mb4_bin,message_id BIGINT,owner_user_id BIGINT,session_id VARCHAR(128) COLLATE utf8mb4_bin,evidence_id BIGINT UNSIGNED,PRIMARY KEY(kind,message_id)) ENGINE=InnoDB;')
for name,kind,prefix,assignments in [
 ('agent_message_execution','MESSAGE_EXECUTION','execution',"m.execution_run_id=s.run_id,m.execution_created_at=CONVERT_TZ(s.created_at,'__SOURCE_CHAT_OFFSET__','+00:00'),m.execution_legacy_id=s.id"),
 ('agent_workspace_turn_snapshot','MESSAGE_WORKSPACE_SNAPSHOT','snapshot',"m.workspace_snapshot_json=s.snapshot_json,m.workspace_snapshot_sha256=s.snapshot_sha256,m.workspace_snapshot_created_at=CONVERT_TZ(s.created_at,'__SOURCE_CHAT_OFFSET__','+00:00'),m.workspace_snapshot_legacy_id=s.id"),
 ('agent_context_turn','MESSAGE_CONTEXT_SOURCES','context',"m.context_sources_json=s.sources_json,m.context_sources_sha256=s.sources_sha256")]:
    extra=" AND m.role='assistant'" if name!='agent_context_turn' else ''
    # A source snapshot/context key includes its original session. Matching is byte exact, never case folding.
    matching=f"m.id=s.message_id AND BINARY m.session_id=BINARY s.session_id{extra}"
    tail=f"JOIN chat_session c ON BINARY c.session_id=BINARY m.session_id AND c.user_id=s.user_id JOIN audit_event a ON BINARY a.legacy_source=BINARY '{name}' AND BINARY a.legacy_key=BINARY {legacy[name]}"
    emit(f"INSERT INTO compact_chat_projection SELECT '{kind}',{legacy[name]},m.id,s.user_id,s.session_id,a.id FROM `__SOURCE_SCHEMA__`.{name} s JOIN chat_message m ON {matching} {tail};")
    emit(f"UPDATE chat_message m JOIN `__SOURCE_SCHEMA__`.{name} s ON {matching} {tail} SET m.{prefix}_owner_user_id=s.user_id,m.{prefix}_evidence_id=a.id,{assignments};")
    projection=[f'm.{prefix}_evidence_id<=>expected.evidence_id',f'm.{prefix}_owner_user_id<=>s.user_id','BINARY m.session_id<=>BINARY expected.session_id']
    if name=='agent_message_execution':projection+=['BINARY m.execution_run_id<=>BINARY s.run_id',"m.execution_created_at<=>CONVERT_TZ(s.created_at,'__SOURCE_CHAT_OFFSET__','+00:00')",'m.execution_legacy_id<=>s.id']
    elif name=='agent_workspace_turn_snapshot':projection+=['BINARY m.workspace_snapshot_json<=>BINARY s.snapshot_json','BINARY m.workspace_snapshot_sha256<=>BINARY s.snapshot_sha256',"m.workspace_snapshot_created_at<=>CONVERT_TZ(s.created_at,'__SOURCE_CHAT_OFFSET__','+00:00')",'m.workspace_snapshot_legacy_id<=>s.id']
    else:projection+=['BINARY m.context_sources_json<=>BINARY s.sources_json','BINARY m.context_sources_sha256<=>BINARY s.sources_sha256']
    guard(f"SELECT IF(COUNT(*)=0,1,0) FROM compact_chat_projection expected JOIN `__SOURCE_SCHEMA__`.{name} s ON BINARY expected.legacy_key=BINARY {legacy[name]} LEFT JOIN chat_message m ON m.id=expected.message_id WHERE expected.kind='{kind}' AND (m.id IS NULL OR "+' OR '.join('NOT('+c+')' for c in projection)+')')
for validation in final_audit_guards:emit(validation)
emit('COMMIT;\nDROP TEMPORARY TABLE compact_chat_projection;\nDROP TEMPORARY TABLE compact_chat_evidence_keys;\nDROP TEMPORARY TABLE compact_chat_evidence_columns;\nDROP TEMPORARY TABLE compact_chat_evidence_guard;')
(ROOT/'sql/mysql/compact/copy/24-chat-evidence.sql').write_text('\n'.join(sql)+'\n',encoding='utf-8')
print(json.dumps({'status':'AUTHORED_NOT_EXECUTED','sourceTables':len(tables),'sourceColumns':len(rows)}))
