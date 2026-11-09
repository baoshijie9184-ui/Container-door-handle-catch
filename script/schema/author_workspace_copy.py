"""Author the complete V38 workspace copy. Source-only; never connects to a database."""
from pathlib import Path
import importlib.util
import json
import re

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('compact_parser',ROOT/'script/schema/build_compact_schema.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
source=(ROOT/'sql/mysql/migration-V38-agent-workspace.sql').read_text(encoding='utf-8')
tables={}
for statement in p.split_top_level(p.without_comments(source),';'):
    if statement.startswith('CREATE TABLE'):
        table=p.parse_table(statement.replace('CREATE TABLE IF NOT EXISTS','CREATE TABLE',1),'migration-V38-agent-workspace.sql')
        tables[table['name']]=table
if len(tables)!=7 or sum(len(t['columns']) for t in tables.values())!=39:
    raise ValueError('Actual V38 shape changed; review all seven tables and 39 columns before authoring')
# Fork import may change only these five projection fields. Snapshot every other
# actual target field, without copying defaults or ON UPDATE into the temporary table.
session_ddl=next(statement for statement in p.split_top_level(p.without_comments((ROOT/'sql/mysql/compact/baseline/25-agent.sql').read_text(encoding='utf-8')),';') if re.match(r'CREATE TABLE chat_session\b',statement))
session=p.parse_table(session_ddl,'25-agent.sql')
fork_columns={'fork_owner_user_id','fork_request_id','fork_source_session_id','fork_through_message_id','fork_legacy_id'}
if session['primaryKey']!=['id'] or not fork_columns.issubset(session['columns']):
    raise ValueError('Unreviewed target chat_session identity/projection shape')
preserved_columns={name:column for name,column in session['columns'].items() if name not in fork_columns}
snapshot_declarations=[]
for name,column in preserved_columns.items():
    nullable=name not in session['primaryKey'] and 'NOT NULL' not in column['declaration'].upper()
    textual=column['type'].lower().startswith(('char','varchar','tinytext','text','mediumtext','longtext','enum','set'))
    snapshot_declarations.append('`'+name+'` '+column['type']+(' COLLATE '+column['collation'] if textual and column['collation'] else '')+(' NULL' if nullable else ' NOT NULL'))
preserved_names=','.join('`'+name+'`' for name in preserved_columns)
text_types=('char','varchar','tinytext','text','mediumtext','longtext','binary','varbinary','tinyblob','blob','mediumblob','longblob','enum','set','json')
session_checks=[('BINARY t.`'+name+'`<=>BINARY expected.`'+name+'`') if column['type'].lower().startswith(text_types) else ('t.`'+name+'`<=>expected.`'+name+'`') for name,column in preserved_columns.items()]
def q(value):return 'NULL' if value is None else "'"+str(value).replace("'","''")+"'"
sql=[]
def emit(value):sql.append(value)
def guard(value):emit('INSERT INTO compact_workspace_guard '+value+';')
names='('+','.join(map(q,tables))+')'
rows=[]
for name,t in tables.items():
    for ordinal,(column,c) in enumerate(t['columns'].items(),1):
        kind=c['type'].lower();decl=c['declaration'];clock=bool(re.search(r'DEFAULT\s+CURRENT_TIMESTAMP\(6\)',decl,re.I))
        coll=(c['collation'] or 'utf8mb4_0900_ai_ci') if kind.startswith(('varchar','char')) else None
        rows.append((name,column,ordinal,kind,'NO',coll,'current_timestamp(6)' if clock else None,'auto_increment' if 'AUTO_INCREMENT' in decl.upper() else 'default_generated' if clock else ''))
emit('''-- V38 workspace migration candidate: AUTHORED_NOT_EXECUTED. Seven tables, 39 original columns.
-- Existing distinct source/target schemas, stopped source and target writers, explicit evidenced source DATETIME offset.
-- Target baseline/relations already installed. Source grants SELECT+TRIGGER permit complete read-only metadata checks.
-- Private bytes remain at their existing users/{owner}/{file_id}.bin path; separately verify/copy the private volume.
-- All old row IDs stay in legacy provenance. New shared cursors do not inherit per-source AUTO_INCREMENT.
-- Preserve each original source sequence in the migration receipt/backup. Never write or drop source data.
-- Source request/fork rows have no timestamps: their receipt times remain NULL, not guessed from import time.
-- One connection, stop at first error, ROLLBACK there then close. Never --force.
SET NAMES utf8mb4;
CREATE TEMPORARY TABLE compact_workspace_guard(valid INT NOT NULL CHECK(valid=1)) ENGINE=InnoDB;''')
guard("SELECT IF(DATABASE() IS NOT NULL AND BINARY DATABASE()<>BINARY '__SOURCE_SCHEMA__' AND @@FOREIGN_KEY_CHECKS=1 AND @@SESSION.sql_mode REGEXP '(^|,)(STRICT_TRANS_TABLES|STRICT_ALL_TABLES)(,|$)' AND REGEXP_LIKE('__SOURCE_WORKSPACE_OFFSET__','^[+-][0-9]{2}:[0-9]{2}$','c') AND CONVERT_TZ('2026-01-01','__SOURCE_WORKSPACE_OFFSET__','+00:00') IS NOT NULL,1,0)")
guard("SELECT IF(COUNT(DISTINCT privilege_type)=2,1,0) FROM information_schema.schema_privileges WHERE BINARY table_schema=BINARY '__SOURCE_SCHEMA__' AND privilege_type IN ('SELECT','TRIGGER') AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)))")
emit('CREATE TEMPORARY TABLE compact_workspace_columns(table_name VARCHAR(64),column_name VARCHAR(64),ordinal_position INT,column_type VARCHAR(64),nullable VARCHAR(3),collation_name VARCHAR(64),default_value VARCHAR(64),extra VARCHAR(64),PRIMARY KEY(table_name,column_name)) ENGINE=InnoDB;')
emit('INSERT INTO compact_workspace_columns VALUES\n'+',\n'.join('('+','.join(map(q,row))+')' for row in rows)+';')
guard("SELECT IF(COUNT(*)=7,1,0) FROM information_schema.tables WHERE BINARY table_schema=BINARY '__SOURCE_SCHEMA__' AND table_name IN "+names+" AND table_type='BASE TABLE' AND engine='InnoDB' AND table_collation='utf8mb4_0900_ai_ci'")
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.columns c LEFT JOIN compact_workspace_columns e ON BINARY e.table_name=BINARY c.table_name AND BINARY e.column_name=BINARY c.column_name WHERE BINARY c.table_schema=BINARY '__SOURCE_SCHEMA__' AND c.table_name IN "+names+" AND e.column_name IS NULL")
guard("SELECT IF(COUNT(*)=0,1,0) FROM compact_workspace_columns e LEFT JOIN information_schema.columns c ON BINARY c.table_schema=BINARY '__SOURCE_SCHEMA__' AND BINARY c.table_name=BINARY e.table_name AND BINARY c.column_name=BINARY e.column_name WHERE c.column_name IS NULL OR NOT(c.ordinal_position<=>e.ordinal_position) OR NOT(BINARY LOWER(c.column_type)<=>BINARY e.column_type) OR NOT(BINARY c.is_nullable<=>BINARY e.nullable) OR NOT(BINARY c.collation_name<=>BINARY e.collation_name) OR NOT(BINARY LOWER(c.column_default)<=>BINARY e.default_value) OR NOT(BINARY LOWER(c.extra)<=>BINARY e.extra) OR NOT(BINARY c.generation_expression<=>BINARY '')")
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.triggers WHERE BINARY event_object_schema=BINARY '__SOURCE_SCHEMA__' AND event_object_table IN "+names)
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.table_constraints WHERE BINARY table_schema=BINARY '__SOURCE_SCHEMA__' AND table_name IN "+names+" AND constraint_type IN ('FOREIGN KEY','CHECK')")
keys=[(name,primary,','.join(cols)) for name,t in tables.items() for primary,cols in [(1,t['primaryKey']),*((0,key) for key in t['uniqueKeys'])]]
emit('CREATE TEMPORARY TABLE compact_workspace_keys(table_name VARCHAR(64),is_primary BOOLEAN,key_columns VARCHAR(1024)) ENGINE=InnoDB;')
emit('INSERT INTO compact_workspace_keys VALUES '+','.join('('+q(name)+','+str(primary)+','+q(cols)+')' for name,primary,cols in keys)+';')
actual="(SELECT table_name,(index_name='PRIMARY') is_primary,GROUP_CONCAT(column_name ORDER BY seq_in_index) key_columns,SUM(sub_part IS NOT NULL OR index_type<>'BTREE' OR is_visible<>'YES') invalid_shape FROM information_schema.statistics WHERE BINARY table_schema=BINARY '__SOURCE_SCHEMA__' AND table_name IN "+names+" AND non_unique=0 GROUP BY table_name,index_name)"
guard('SELECT IF(COUNT(*)=0,1,0) FROM '+actual+' a LEFT JOIN compact_workspace_keys e ON BINARY e.table_name=BINARY a.table_name AND e.is_primary=a.is_primary AND BINARY e.key_columns=BINARY a.key_columns WHERE e.table_name IS NULL OR a.invalid_shape<>0')
guard('SELECT IF(COUNT(*)=0,1,0) FROM compact_workspace_keys e LEFT JOIN '+actual+' a ON BINARY e.table_name=BINARY a.table_name AND e.is_primary=a.is_primary AND BINARY e.key_columns=BINARY a.key_columns WHERE a.table_name IS NULL')
for table,where in [('content_asset',"asset_kind='WORKSPACE_FILE'"),('content_revision',"asset_kind='WORKSPACE_FILE'"),('content_link',"link_kind IN ('WORKSPACE_FILE','WORKSPACE_BUSINESS')"),('workflow_instance',"kind IN ('WORKSPACE_MUTATION','WORKSPACE_FORK')"),('audit_event',"kind='WORKSPACE'"),('runtime_state',"namespace='WORKSPACE'")]:
    guard(f'SELECT IF(COUNT(*)=0,1,0) FROM {table} WHERE {where}')
for table in ['content_asset','content_revision','content_link','workflow_instance','audit_event']:
    guard(f'SELECT IF(COUNT(*)=0,1,0) FROM {table} WHERE legacy_source IN '+names)
guard("SELECT IF(COUNT(*)="+str(len(session['columns']))+" AND COALESCE(SUM(BINARY column_name IN ("+','.join('BINARY '+q(name) for name in session['columns'])+")),0)="+str(len(session['columns']))+",1,0) FROM information_schema.columns WHERE table_schema=DATABASE() AND BINARY table_name=BINARY 'chat_session'")
guard('SELECT IF(COUNT(*)=0,1,0) FROM chat_session WHERE fork_owner_user_id IS NOT NULL OR fork_request_id IS NOT NULL OR fork_source_session_id IS NOT NULL OR fork_through_message_id IS NOT NULL OR fork_legacy_id IS NOT NULL')
for name in tables:
    guard(f"SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.{name} WHERE user_id"+('<0' if name=='agent_workspace_owner' else '<=0'))
offset="(IF(LEFT('__SOURCE_WORKSPACE_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_WORKSPACE_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_WORKSPACE_OFFSET__',5,2) AS SIGNED)*60))"
utc="CONVERT_TZ(s.created_at,'__SOURCE_WORKSPACE_OFFSET__','+00:00')"
wall="DATE_FORMAT(s.created_at,'%Y-%m-%d %H:%i:%s.%f')"
for name in ['agent_workspace_file','agent_workspace_file_ref','agent_workspace_audit','agent_workspace_business_ref']:
    guard(f'SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.{name} s WHERE NOT COALESCE(({utc} IS NOT NULL AND TIMESTAMPDIFF(SECOND,{utc},s.created_at)={offset}),FALSE)')
guard("SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.agent_workspace_file WHERE byte_length<0 OR NOT REGEXP_LIKE(sha256,'^[a-fA-F0-9]{64}$','c') OR NOT REGEXP_LIKE(file_id,'^[a-f0-9-]{36}$','c')")
guard("SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.agent_workspace_request WHERE NOT REGEXP_LIKE(signature,'^[a-fA-F0-9]{64}$','c')")
guard("SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.agent_workspace_audit WHERE NOT REGEXP_LIKE(content_sha256,'^[a-fA-F0-9]{64}$','c')")
guard("SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.agent_session_fork WHERE through_message_id<=0 OR CHAR_LENGTH(TRIM(source_session_id))=0 OR CHAR_LENGTH(TRIM(fork_session_id))=0")
manifest="JSON_OBJECT('folder',s.folder,'createdAtSource',"+wall+",'sourceUtcOffset','__SOURCE_WORKSPACE_OFFSET__')"
audit_payload="JSON_OBJECT('createdAtSource',"+wall+",'sourceUtcOffset','__SOURCE_WORKSPACE_OFFSET__')"
fork_payload="JSON_OBJECT('sourceSessionId',s.source_session_id,'throughMessageId',s.through_message_id,'resultSessionId',s.fork_session_id)"
mutation_payload="JSON_OBJECT('signature',s.signature)"
emit('START TRANSACTION;')
emit('CREATE TEMPORARY TABLE compact_workspace_session_snapshot('+','.join(snapshot_declarations)+',PRIMARY KEY(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;')
emit('INSERT INTO compact_workspace_session_snapshot('+preserved_names+') SELECT '+preserved_names+' FROM chat_session ORDER BY id;')
emit('CREATE TEMPORARY TABLE compact_workspace_fork_projection(legacy_id DECIMAL(20,0) PRIMARY KEY,target_id BIGINT NOT NULL UNIQUE) ENGINE=InnoDB;')
emit("INSERT INTO compact_workspace_fork_projection SELECT s.id,t.id FROM `__SOURCE_SCHEMA__`.agent_session_fork s JOIN chat_session t ON BINARY t.session_id=BINARY s.fork_session_id AND t.user_id=s.user_id;")
emit("INSERT INTO runtime_state(namespace,owner_id,scope_key,created_at) SELECT 'WORKSPACE',s.user_id,'',NULL FROM `__SOURCE_SCHEMA__`.agent_workspace_owner s;")
emit(f"INSERT INTO content_asset(asset_id,asset_kind,owner_user_id,title,filename,visibility,lifecycle,current_version,created_at,updated_at,legacy_source,legacy_id) SELECT s.file_id,'WORKSPACE_FILE',s.user_id,s.filename,s.filename,'PRIVATE','PREPARING',NULL,{utc},{utc},'agent_workspace_file',s.id FROM `__SOURCE_SCHEMA__`.agent_workspace_file s ORDER BY s.id;")
emit(f"INSERT INTO content_revision(asset_id,asset_kind,version,owner_user_id,filename,content_sha256,byte_length,media_type,object_key,manifest_json,request_id,created_at,legacy_source,legacy_id) SELECT s.file_id,'WORKSPACE_FILE',1,s.user_id,s.filename,s.sha256,s.byte_length,s.content_type,CONCAT('users/',s.user_id,'/',s.file_id,'.bin'),{manifest},s.request_id,{utc},'agent_workspace_file',s.id FROM `__SOURCE_SCHEMA__`.agent_workspace_file s ORDER BY s.id;")
emit("UPDATE content_asset SET current_version=1,lifecycle='ACTIVE' WHERE asset_kind='WORKSPACE_FILE';")
for name,kind,target_type,target_id in [('agent_workspace_file_ref','WORKSPACE_FILE',"'WORKSPACE_FILE'",'s.file_id'),('agent_workspace_business_ref','WORKSPACE_BUSINESS','s.kind','s.resource_id')]:
    emit(f"INSERT INTO content_link(link_kind,owner_user_id,session_id,target_type,target_id,created_at,legacy_source,legacy_id,legacy_created_at,legacy_utc_offset) SELECT '{kind}',s.user_id,s.session_id,{target_type},{target_id},{utc},'{name}',s.id,s.created_at,'__SOURCE_WORKSPACE_OFFSET__' FROM `__SOURCE_SCHEMA__`.{name} s ORDER BY s.id;")
for name,kind,resource,resource_id,digest,payload in [('agent_workspace_request','WORKSPACE_MUTATION','WORKSPACE_MUTATION','NULL','s.signature',mutation_payload),('agent_session_fork','WORKSPACE_FORK','SESSION','s.fork_session_id',"SHA2(CONCAT(s.source_session_id,':',s.through_message_id),256)",fork_payload)]:
    emit(f"INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,resource_type,resource_id,status,payload_version,payload_json,created_at,updated_at,finished_at,legacy_source,legacy_key) SELECT CONCAT('v38-{kind.lower()}-',s.id),'{kind}',CONCAT('OWNER:',s.user_id),s.request_id,{digest},s.user_id,'{resource}',{resource_id},'COMPLETED',1,{payload},NULL,NULL,NULL,'{name}',CAST(s.id AS CHAR) FROM `__SOURCE_SCHEMA__`.{name} s ORDER BY s.id;")
emit(f"INSERT INTO audit_event(event_id,kind,owner_user_id,resource_type,resource_id,session_id,action,content_sha256,occurred_at,payload_version,payload_json,legacy_source,legacy_key) SELECT CONCAT('v38-workspace-audit-',s.id),'WORKSPACE',s.user_id,'WORKSPACE',s.resource_id,s.session_id,s.action,s.content_sha256,{utc},1,{audit_payload},'agent_workspace_audit',CAST(s.id AS CHAR) FROM `__SOURCE_SCHEMA__`.agent_workspace_audit s ORDER BY s.id;")
emit("UPDATE chat_session t JOIN compact_workspace_fork_projection expected ON expected.target_id=t.id JOIN `__SOURCE_SCHEMA__`.agent_session_fork s ON s.id=expected.legacy_id AND BINARY t.session_id=BINARY s.fork_session_id AND t.user_id=s.user_id SET t.fork_owner_user_id=s.user_id,t.fork_request_id=s.request_id,t.fork_source_session_id=s.source_session_id,t.fork_through_message_id=s.through_message_id,t.fork_legacy_id=s.id,t.updated_at=t.updated_at;")

def count(source,target,where):guard(f'SELECT IF((SELECT COUNT(*) FROM {target} WHERE {where})=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.{source}),1,0)')
def tail(source,target,join,checks):guard(f'SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.{source} s LEFT JOIN {target} t ON {join} WHERE t.'+('owner_id' if target=='runtime_state' else 'id')+' IS NULL OR '+' OR '.join('NOT('+check+')' for check in checks))
count('agent_workspace_owner','runtime_state',"namespace='WORKSPACE'")
tail('agent_workspace_owner','runtime_state',"BINARY t.namespace=BINARY 'WORKSPACE' AND t.owner_id=s.user_id AND BINARY t.scope_key=BINARY ''",['t.owner_id<=>s.user_id',"BINARY t.namespace<=>BINARY 'WORKSPACE'","BINARY t.scope_key<=>BINARY ''",'t.revision<=>0','t.created_at IS NULL','t.payload_version<=>1']+['t.'+c+' IS NULL' for c in ['session_id','state_key','state_code','current_ref','counter_value','provider','credential_sha256','actor_user_id','request_id','window_started_at','window_ends_at','payload_json']])
for target in ['content_asset','content_revision']:
    count('agent_workspace_file',target,"asset_kind='WORKSPACE_FILE'")
    checks=["BINARY t.asset_kind<=>BINARY 'WORKSPACE_FILE'",'BINARY t.asset_id<=>BINARY s.file_id','t.owner_user_id<=>s.user_id','BINARY t.filename<=>BINARY s.filename','t.created_at<=>'+utc,"BINARY t.legacy_source<=>BINARY 'agent_workspace_file'",'t.legacy_id<=>s.id']
    if target=='content_asset':
        checks+=['BINARY t.title<=>BINARY s.filename',"BINARY t.visibility<=>BINARY 'PRIVATE'","BINARY t.lifecycle<=>BINARY 'ACTIVE'",'t.current_version<=>1','t.revision<=>1','t.use_count<=>0','t.updated_at<=>'+utc]+['t.'+c+' IS NULL' for c in ['legacy_owner_reference','identity_key','required_role','published_version','last_used_at','activated_at']]
    else:
        checks+=['t.version<=>1','BINARY t.content_sha256<=>BINARY s.sha256','t.byte_length<=>s.byte_length','BINARY t.media_type<=>BINARY s.content_type',"BINARY t.object_key<=>BINARY CONCAT('users/',s.user_id,'/',s.file_id,'.bin')",'BINARY t.manifest_json<=>BINARY '+manifest,'BINARY t.request_id<=>BINARY s.request_id',"BINARY t.content_state<=>BINARY 'PRESENT'","BINARY t.index_state<=>BINARY 'NONE'",'t.chunk_count<=>0']
        checks+=['t.'+c+' IS NULL' for c in ['creator_user_id','title','description_text','content_text','stored_content_sha256','source_bytes','source_sha256','object_version','source_type','source_run_id','source_import_id','source_url','source_query_omitted','source_url_redacted','range_start','max_length','text_chars','manifest_sha256','tool_names_json','sources_json','sources_sha256','approval_status','reviewer_user_id','review_reason','submitted_at','reviewed_at','request_sha256','expires_at','purge_owner_user_id','cleared_chars','purged_at']]
    tail('agent_workspace_file',target,"BINARY t.legacy_source=BINARY 'agent_workspace_file' AND t.legacy_id=s.id",checks)
for name,kind,target_type,target_id in [('agent_workspace_file_ref','WORKSPACE_FILE',"'WORKSPACE_FILE'",'s.file_id'),('agent_workspace_business_ref','WORKSPACE_BUSINESS','s.kind','s.resource_id')]:
    count(name,'content_link',f"link_kind='{kind}'")
    checks=[f"BINARY t.link_kind<=>BINARY '{kind}'",'t.owner_user_id<=>s.user_id','BINARY t.session_id<=>BINARY s.session_id','BINARY t.target_type<=>BINARY '+target_type,'BINARY t.target_id<=>BINARY '+target_id,'t.created_at<=>'+utc,f"BINARY t.legacy_source<=>BINARY '{name}'",'t.legacy_id<=>s.id','t.legacy_created_at<=>s.created_at',"BINARY t.legacy_utc_offset<=>BINARY '__SOURCE_WORKSPACE_OFFSET__'","BINARY t.state<=>BINARY 'ACTIVE'"]
    checks+=['t.'+c+' IS NULL' for c in ['message_id','run_id','call_id','agent_scope','logical_task_id','asset_id','asset_version','subject_type','subject_id','request_id','request_sha256','retained_until','released_at']]
    tail(name,'content_link',f"BINARY t.legacy_source=BINARY '{name}' AND t.legacy_id=s.id",checks)
for name,kind,resource,resource_id,digest,payload in [('agent_workspace_request','WORKSPACE_MUTATION','WORKSPACE_MUTATION','NULL','s.signature',mutation_payload),('agent_session_fork','WORKSPACE_FORK','SESSION','s.fork_session_id',"SHA2(CONCAT(s.source_session_id,':',s.through_message_id),256)",fork_payload)]:
    count(name,'workflow_instance',f"kind='{kind}'")
    checks=[f"BINARY t.workflow_id<=>BINARY CONCAT('v38-{kind.lower()}-',s.id)",f"BINARY t.kind<=>BINARY '{kind}'","BINARY t.idempotency_scope<=>BINARY CONCAT('OWNER:',s.user_id)",'t.owner_user_id<=>s.user_id','BINARY t.request_id<=>BINARY s.request_id','BINARY t.request_sha256<=>BINARY '+digest,f"BINARY t.resource_type<=>BINARY '{resource}'",'BINARY t.resource_id<=>BINARY '+resource_id,"BINARY t.status<=>BINARY 'COMPLETED'",'t.payload_version<=>1','BINARY t.payload_json<=>BINARY '+payload,f"BINARY t.legacy_source<=>BINARY '{name}'",'BINARY t.legacy_key<=>BINARY CAST(s.id AS CHAR)','t.revision<=>0','t.fence<=>0','t.attempts<=>0']
    checks+=['t.'+c+' IS NULL' for c in ['actor_user_id','parent_workflow_id','resource_revision','requested_tokens','decider_user_id','session_id','run_id','chat_action_session_id','confirmation_recorded_at','active_slot','claim_token','lease_expires_at','effective_date','scheduled_for','error_code','next_attempt_at','expires_at','execution_state','reserved_bytes','exit_verified','execution_deadline','result_version','result_json','result_sha256','created_at','updated_at','finished_at']]
    tail(name,'workflow_instance',f"BINARY t.legacy_source=BINARY '{name}' AND BINARY t.legacy_key=BINARY CAST(s.id AS CHAR)",checks)
count('agent_workspace_audit','audit_event',"kind='WORKSPACE'")
checks=["BINARY t.event_id<=>BINARY CONCAT('v38-workspace-audit-',s.id)","BINARY t.kind<=>BINARY 'WORKSPACE'",'t.owner_user_id<=>s.user_id',"BINARY t.resource_type<=>BINARY 'WORKSPACE'",'BINARY t.resource_id<=>BINARY s.resource_id','BINARY t.session_id<=>BINARY s.session_id','BINARY t.action<=>BINARY s.action','BINARY t.content_sha256<=>BINARY s.content_sha256','t.occurred_at<=>'+utc,'t.payload_version<=>1','BINARY t.payload_json<=>BINARY '+audit_payload,"BINARY t.legacy_source<=>BINARY 'agent_workspace_audit'",'BINARY t.legacy_key<=>BINARY CAST(s.id AS CHAR)']
checks+=['t.'+c+' IS NULL' for c in ['actor_user_id','detection_model_id','message_id','run_id','journal_run_id','sequence_no','request_id','request_scope','revision','previous_sha256','event_sha256','quantity','unit','policy_version','outcome','observed_at']]
tail('agent_workspace_audit','audit_event',"BINARY t.legacy_source=BINARY 'agent_workspace_audit' AND BINARY t.legacy_key=BINARY CAST(s.id AS CHAR)",checks)
guard('SELECT IF((SELECT COUNT(*) FROM chat_session)=(SELECT COUNT(*) FROM compact_workspace_session_snapshot),1,0)')
guard('SELECT IF(COUNT(*)=0,1,0) FROM compact_workspace_session_snapshot expected LEFT JOIN chat_session t ON t.id=expected.id WHERE t.id IS NULL OR '+' OR '.join('NOT('+check+')' for check in session_checks))
guard("SELECT IF(COUNT(*)=0,1,0) FROM compact_workspace_fork_projection expected JOIN `__SOURCE_SCHEMA__`.agent_session_fork s ON s.id=expected.legacy_id LEFT JOIN chat_session t ON t.id=expected.target_id WHERE t.id IS NULL OR NOT(t.fork_owner_user_id<=>s.user_id) OR NOT(BINARY t.fork_request_id<=>BINARY s.request_id) OR NOT(BINARY t.fork_source_session_id<=>BINARY s.source_session_id) OR NOT(t.fork_through_message_id<=>s.through_message_id) OR NOT(t.fork_legacy_id<=>s.id)")
guard('SELECT IF(COUNT(*)=0,1,0) FROM chat_session t LEFT JOIN compact_workspace_fork_projection expected ON expected.target_id=t.id WHERE expected.target_id IS NULL AND ('+' OR '.join('t.'+column+' IS NOT NULL' for column in sorted(fork_columns))+')')
emit('COMMIT;\nDROP TEMPORARY TABLE compact_workspace_fork_projection;\nDROP TEMPORARY TABLE compact_workspace_session_snapshot;\nDROP TEMPORARY TABLE compact_workspace_keys;\nDROP TEMPORARY TABLE compact_workspace_columns;\nDROP TEMPORARY TABLE compact_workspace_guard;')
from author_legacy_clock_copy import write_copy
write_copy('43-workspace.sql','\n'.join(sql)+'\n')
print(json.dumps({'status':'AUTHORED_NOT_EXECUTED','sourceTables':len(tables),'sourceColumns':len(rows),'preservedSessionColumns':len(preserved_columns)}))
