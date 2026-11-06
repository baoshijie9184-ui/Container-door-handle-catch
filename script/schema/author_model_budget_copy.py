"""Author V64 migration from the four real source CREATE statements. No database or test execution."""
from pathlib import Path
import importlib.util
import json
import re

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('compact_parser',ROOT/'script/schema/build_compact_schema.py')
parser=importlib.util.module_from_spec(spec);spec.loader.exec_module(parser)
sources={}
for statement in parser.split_top_level(parser.without_comments((ROOT/'sql/mysql/migration-V64-model-budget.sql').read_text(encoding='utf-8')),';'):
    if statement.startswith('CREATE TABLE'):
        table=parser.parse_table(statement.replace('CREATE TABLE IF NOT EXISTS','CREATE TABLE',1),'V64');sources[table['name']]=table
def q(value):return 'NULL' if value is None else "'"+str(value).replace("'","''")+"'"
sql=[]
def emit(value):sql.append(value)
def guard(query):emit('INSERT INTO compact_budget_guard '+query+';')
rows=[]
for name,table in sources.items():
    for column,definition in table['columns'].items():
        declaration=definition['declaration']
        kind=re.match(parser.IDENT+r'\s+([a-z]+(?:\([^)]*\))?(?:\s+UNSIGNED)?)',declaration,re.I).group(2).lower().replace('boolean','tinyint(1)')
        coll=(definition['collation'] or 'utf8mb4_0900_ai_ci') if kind.startswith(('varchar','char')) else None
        nullable='NO' if column in table['primaryKey'] or 'NOT NULL' in declaration.upper() else 'YES'
        found=re.search(r'\bDEFAULT\s+(NULL|TRUE|FALSE|\d+)',declaration,re.I)
        default=found.group(1).upper() if found else None
        default={'TRUE':'1','FALSE':'0','NULL':None}.get(default,default)
        extra='auto_increment' if 'AUTO_INCREMENT' in declaration.upper() else ''
        rows.append((name,column,kind,nullable,coll,default,extra))
emit('''-- V64 model budget copy candidate: NOT EXECUTED. Four original tables, no invented owner or provider request.
-- Source and target must be distinct schemas; writers are stopped. Render __SOURCE_SCHEMA__ as a validated identifier.
-- V64 Java wrote LocalDateTime.now(UTC), including observations normalized to UTC. Do NOT apply a Beijing offset.
-- Actual source columns/keys/checks are verified below; estimatedRows is never evidence that a source is empty.
-- All old attempts remain immutable anonymous audit snapshots. Known components produce MODEL ledger lower bounds only.
-- One connection/transaction, stop at first error and ROLLBACK there. No --force, source writes, artificial reservations or retries.
SET NAMES utf8mb4;
CREATE TEMPORARY TABLE compact_budget_guard(valid INT NOT NULL CHECK(valid=1)) ENGINE=InnoDB;''')
guard("SELECT IF(DATABASE() IS NOT NULL AND BINARY DATABASE()<>BINARY '__SOURCE_SCHEMA__' AND @@FOREIGN_KEY_CHECKS=1 AND @@SESSION.sql_mode REGEXP '(^|,)(STRICT_TRANS_TABLES|STRICT_ALL_TABLES)(,|$)',1,0)")
guard("SELECT IF(COUNT(DISTINCT privilege_type)=2,1,0) FROM information_schema.schema_privileges WHERE table_schema='__SOURCE_SCHEMA__' AND privilege_type IN ('SELECT','TRIGGER') AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)))")
emit('CREATE TEMPORARY TABLE compact_budget_columns(table_name VARCHAR(64),column_name VARCHAR(64),column_type VARCHAR(64),nullable VARCHAR(3),collation_name VARCHAR(64),default_value VARCHAR(64),extra VARCHAR(64),PRIMARY KEY(table_name,column_name)) ENGINE=InnoDB;')
emit('INSERT INTO compact_budget_columns VALUES\n'+',\n'.join('('+','.join(map(q,row))+')' for row in rows)+';')
names='('+','.join(map(q,sources))+')'
guard("SELECT IF(COUNT(*)=4,1,0) FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+" AND table_type='BASE TABLE' AND engine='InnoDB'")
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.columns c LEFT JOIN compact_budget_columns e ON e.table_name=c.table_name AND e.column_name=c.column_name WHERE c.table_schema='__SOURCE_SCHEMA__' AND c.table_name IN "+names+" AND e.column_name IS NULL")
guard("SELECT IF(COUNT(*)=0,1,0) FROM compact_budget_columns e LEFT JOIN information_schema.columns c ON c.table_schema='__SOURCE_SCHEMA__' AND c.table_name=e.table_name AND c.column_name=e.column_name WHERE c.column_name IS NULL OR NOT(BINARY LOWER(c.column_type)<=>BINARY e.column_type) OR NOT(c.is_nullable<=>e.nullable) OR NOT(c.collation_name<=>e.collation_name) OR NOT(c.column_default<=>e.default_value) OR NOT(LOWER(c.extra)<=>e.extra) OR c.generation_expression<>''")
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.triggers WHERE event_object_schema='__SOURCE_SCHEMA__' AND event_object_table IN "+names)
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.table_constraints WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+" AND constraint_type='FOREIGN KEY'")
emit('CREATE TEMPORARY TABLE compact_budget_unique_keys(table_name VARCHAR(64),primary_key BOOLEAN,key_columns VARCHAR(1024)) ENGINE=InnoDB;')
keys=[]
for name,table in sources.items():
    keys.append((name,1,','.join(table['primaryKey'])))
    keys.extend((name,0,','.join(key)) for key in table['uniqueKeys'])
emit('INSERT INTO compact_budget_unique_keys VALUES '+','.join('('+q(name)+','+str(primary)+','+q(columns)+')' for name,primary,columns in keys)+';')
actual="(SELECT table_name,(index_name='PRIMARY') AS primary_key,GROUP_CONCAT(column_name ORDER BY seq_in_index) AS key_columns,SUM(sub_part IS NOT NULL) AS prefixes FROM information_schema.statistics WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+" AND non_unique=0 GROUP BY table_name,index_name)"
guard('SELECT IF(COUNT(*)=0,1,0) FROM '+actual+' a LEFT JOIN compact_budget_unique_keys e ON e.table_name=a.table_name AND e.primary_key=a.primary_key AND e.key_columns=a.key_columns WHERE e.table_name IS NULL OR a.prefixes<>0')
guard('SELECT IF(COUNT(*)=0,1,0) FROM compact_budget_unique_keys e LEFT JOIN '+actual+' a ON e.table_name=a.table_name AND e.primary_key=a.primary_key AND e.key_columns=a.key_columns WHERE a.table_name IS NULL')
# Exact accepted renderings of these simple V64 predicates; no generic removal of grouping parentheses.
emit('CREATE TEMPORARY TABLE compact_budget_checks(table_name VARCHAR(64),semantic_group VARCHAR(64),clause_text VARCHAR(1000)) ENGINE=InnoDB;')
checks={
 'agent_model_budget':{'total':["((total_tokensisnull)or(total_tokens>=0))","(total_tokensisnullortotal_tokens>=0)"],'warning':["(warning_percentbetween1and100)"]},
 'agent_model_budget_attempt':{'status':["(statusin('started','completed','failed','cancelled'))"],'input':["((input_tokensisnull)or(input_tokens>=0))","(input_tokensisnullorinput_tokens>=0)"],'output':["((output_tokensisnull)or(output_tokens>=0))","(output_tokensisnulloroutput_tokens>=0)"]},
 'agent_model_budget_observation':{'remaining':["(remaining_tokens>=0)"]}}
emit('INSERT INTO compact_budget_checks VALUES '+','.join('('+q(name)+','+q(group)+','+q(clause)+')' for name,groups in checks.items() for group,values in groups.items() for clause in values)+';')
normalized="LOWER(REPLACE(REPLACE(REPLACE(c.check_clause,'`',''),' ',''),'_utf8mb4',''))"
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.table_constraints t JOIN information_schema.check_constraints c ON c.constraint_schema=t.constraint_schema AND c.constraint_name=t.constraint_name LEFT JOIN compact_budget_checks e ON e.table_name=t.table_name AND BINARY e.clause_text=BINARY "+normalized+" WHERE t.table_schema='__SOURCE_SCHEMA__' AND t.table_name IN "+names+" AND t.constraint_type='CHECK' AND (e.table_name IS NULL OR t.enforced<>'YES')")
for name,groups in checks.items():
    for group in groups:
        guard("SELECT IF(COUNT(*)=1,1,0) FROM information_schema.table_constraints t JOIN information_schema.check_constraints c ON c.constraint_schema=t.constraint_schema AND c.constraint_name=t.constraint_name JOIN compact_budget_checks e ON e.table_name=t.table_name AND BINARY e.clause_text=BINARY "+normalized+f" WHERE t.table_schema='__SOURCE_SCHEMA__' AND t.table_name='{name}' AND t.constraint_type='CHECK' AND e.semantic_group='{group}' AND t.enforced='YES'")
for name,count in [('agent_model_budget',2),('agent_model_budget_attempt',3),('agent_model_budget_observation',1),('agent_model_budget_audit',0)]:
    guard(f"SELECT IF(COUNT(*)={count},1,0) FROM information_schema.table_constraints WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='{name}' AND constraint_type='CHECK'")
guard("SELECT IF(COUNT(*)=0,1,0) FROM llm_quota WHERE scope_type='MODEL'")
guard("SELECT IF(COUNT(*)=0,1,0) FROM llm_usage WHERE entry_type='IMPORTED_USAGE' OR source_audit_event_id IS NOT NULL")
guard("SELECT IF(COUNT(*)=0,1,0) FROM audit_event WHERE kind IN ('LLM_LEGACY_ATTEMPT','LLM_LEGACY_BUDGET_AUDIT','MODEL_QUOTA_OBSERVATION') OR legacy_source IN ('agent_model_budget_attempt','agent_model_budget_audit','agent_model_budget_observation')")
guard("SELECT IF(COUNT(*)=2,1,0) FROM information_schema.triggers WHERE event_object_schema=DATABASE() AND event_object_table='llm_quota' AND action_timing='BEFORE' AND ((trigger_name='compact_quota_history_protect_delete' AND event_manipulation='DELETE') OR (trigger_name='compact_quota_history_protect_update' AND event_manipulation='UPDATE'))")
guard("SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.agent_model_budget WHERE total_tokens<0 OR warning_percent NOT BETWEEN 1 AND 100 OR free_only NOT IN (0,1) OR version<0 OR CHAR_LENGTH(model_id)=0")
for name in ['agent_model_budget_attempt','agent_model_budget_observation','agent_model_budget_audit']:
    guard(f"SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.{name} s LEFT JOIN `__SOURCE_SCHEMA__`.agent_model_budget b ON s.model_id=b.model_id WHERE b.model_id IS NULL")
guard("SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.agent_model_budget_attempt WHERE CHAR_LENGTH(attempt_id)=0 OR BINARY status NOT IN (BINARY 'STARTED',BINARY 'COMPLETED',BINARY 'FAILED',BINARY 'CANCELLED') OR input_tokens<0 OR output_tokens<0 OR cached_tokens<0 OR CAST(COALESCE(input_tokens,0) AS DECIMAL(65,0))+CAST(COALESCE(output_tokens,0) AS DECIMAL(65,0))>9223372036854775807")
guard("SELECT IF(COUNT(*)=0,1,0) FROM (SELECT model_id FROM `__SOURCE_SCHEMA__`.agent_model_budget_attempt GROUP BY model_id HAVING SUM(CAST(COALESCE(input_tokens,0) AS DECIMAL(65,0))+CAST(COALESCE(output_tokens,0) AS DECIMAL(65,0)))>9223372036854775807) invalid_totals")
guard("SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.agent_model_budget_observation WHERE actor_user_id<=0 OR remaining_tokens<0 OR CHAR_LENGTH(request_id)=0 OR NOT REGEXP_LIKE(request_sha256,'^[a-f0-9]{64}$','c')")
guard("SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.agent_model_budget_audit WHERE actor_user_id<=0")
def original(column):return f"DATE_FORMAT(s.{column},'%Y-%m-%d %H:%i:%s.%f')"
attempt_payload="JSON_OBJECT('legacyId',CAST(s.id AS CHAR),'attemptId',s.attempt_id,'modelId',s.model_id,'status',s.status,'inputTokens',s.input_tokens,'outputTokens',s.output_tokens,'cachedTokens',s.cached_tokens,'startedAtUtc',"+original('started_at')+",'finishedAtUtc',"+original('finished_at')+")"
audit_payload="JSON_OBJECT('legacyId',CAST(s.id AS CHAR),'modelId',s.model_id,'actorUserId',s.actor_user_id,'actionName',s.action_name,'version',s.version,'detailJson',CAST(s.detail_json AS CHAR),'createdAtUtc',"+original('created_at')+")"
known="COALESCE(s.input_tokens,0)+COALESCE(s.output_tokens,0)"
total="(SELECT COALESCE(SUM(COALESCE(a.input_tokens,0)+COALESCE(a.output_tokens,0)),0) FROM `__SOURCE_SCHEMA__`.agent_model_budget_attempt a WHERE a.model_id=s.model_id)"
unresolved="(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_model_budget_attempt a WHERE a.model_id=s.model_id AND (a.status<>'COMPLETED' OR a.finished_at IS NULL OR a.input_tokens IS NULL OR a.output_tokens IS NULL))"
emit('SET @compact_budget_imported_at=UTC_TIMESTAMP(6);\nSTART TRANSACTION;')
emit("INSERT INTO llm_quota(scope_type,owner_user_id,model_id,period_key,total_tokens,reserved_tokens,spent_tokens,unreconciled_legacy_attempts,warning_percent,free_only,expires_at,version,updated_by,created_at,updated_at) SELECT 'MODEL',NULL,s.model_id,'TOTAL',s.total_tokens,0,"+total+","+unresolved+",s.warning_percent,s.free_only,s.expires_at,s.version,s.updated_by,@compact_budget_imported_at,s.updated_at FROM `__SOURCE_SCHEMA__`.agent_model_budget s ORDER BY s.model_id;")
emit("INSERT INTO audit_event(event_id,kind,resource_type,resource_id,request_id,action,outcome,content_sha256,occurred_at,payload_version,payload_json,legacy_source,legacy_key) SELECT CONCAT('legacy-model-attempt-',s.id),'LLM_LEGACY_ATTEMPT','LLM_MODEL',s.model_id,s.attempt_id,'IMPORTED',s.status,SHA2("+attempt_payload+",256),COALESCE(s.finished_at,s.started_at),1,"+attempt_payload+",'agent_model_budget_attempt',CAST(s.id AS CHAR) FROM `__SOURCE_SCHEMA__`.agent_model_budget_attempt s ORDER BY s.id;")
emit("INSERT INTO audit_event(event_id,kind,owner_user_id,actor_user_id,resource_type,resource_id,request_id,action,content_sha256,quantity,unit,request_scope,observed_at,occurred_at,payload_version,payload_json,legacy_source,legacy_key) SELECT CONCAT('legacy-model-observation-',s.id),'MODEL_QUOTA_OBSERVATION',s.actor_user_id,s.actor_user_id,'LLM_MODEL',s.model_id,s.request_id,'OBSERVATION',s.request_sha256,s.remaining_tokens,'TOKENS',CONCAT('OWNER:',s.actor_user_id),s.observed_at,s.created_at,1,JSON_OBJECT('sourceNote',s.source_note),'agent_model_budget_observation',CAST(s.id AS CHAR) FROM `__SOURCE_SCHEMA__`.agent_model_budget_observation s ORDER BY s.id;")
emit("INSERT INTO audit_event(event_id,kind,owner_user_id,actor_user_id,resource_type,resource_id,action,content_sha256,occurred_at,payload_version,payload_json,legacy_source,legacy_key) SELECT CONCAT('legacy-model-policy-audit-',s.id),'LLM_LEGACY_BUDGET_AUDIT',s.actor_user_id,s.actor_user_id,'LLM_MODEL',s.model_id,'IMPORTED',SHA2("+audit_payload+",256),s.created_at,1,"+audit_payload+",'agent_model_budget_audit',CAST(s.id AS CHAR) FROM `__SOURCE_SCHEMA__`.agent_model_budget_audit s ORDER BY s.id;")
emit("INSERT INTO llm_usage(account_id,source_audit_event_id,entry_key,entry_type,reserved_delta,spent_delta,input_tokens,output_tokens,cached_tokens,request_sha256,created_at) SELECT q.id,e.id,'V64_ATTEMPT','IMPORTED_USAGE',0,"+known+",s.input_tokens,s.output_tokens,s.cached_tokens,SHA2(CONCAT('V64_IMPORT',CHAR(10),e.payload_json),256),COALESCE(s.finished_at,s.started_at) FROM `__SOURCE_SCHEMA__`.agent_model_budget_attempt s JOIN llm_quota q ON q.scope_type='MODEL' AND q.owner_user_id IS NULL AND q.period_key='TOTAL' AND q.model_id=s.model_id JOIN audit_event e ON BINARY e.legacy_source=BINARY 'agent_model_budget_attempt' AND BINARY e.legacy_key=BINARY CAST(s.id AS CHAR) AND e.kind='LLM_LEGACY_ATTEMPT' ORDER BY s.id;")
guard("SELECT IF((SELECT COUNT(*) FROM llm_quota WHERE scope_type='MODEL')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_model_budget),1,0)")
for source,kind in [('agent_model_budget_attempt','LLM_LEGACY_ATTEMPT'),('agent_model_budget_observation','MODEL_QUOTA_OBSERVATION'),('agent_model_budget_audit','LLM_LEGACY_BUDGET_AUDIT')]:
    guard(f"SELECT IF((SELECT COUNT(*) FROM audit_event WHERE kind='{kind}')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.{source}),1,0)")
guard("SELECT IF((SELECT COUNT(*) FROM llm_usage WHERE entry_type='IMPORTED_USAGE')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_model_budget_attempt),1,0)")
def comparison(source,target,join,checks):
    guard(f"SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.{source} s LEFT JOIN {target} t ON {join} WHERE t.id IS NULL OR "+' OR '.join('NOT('+check+')' for check in checks))
comparison('agent_model_budget','llm_quota',"t.scope_type='MODEL' AND t.owner_user_id IS NULL AND t.period_key='TOTAL' AND BINARY t.model_id=BINARY s.model_id",[
    "BINARY t.scope_type<=>BINARY 'MODEL'","BINARY t.period_key<=>BINARY 'TOTAL'",'t.total_tokens<=>s.total_tokens','t.reserved_tokens<=>0','t.spent_tokens<=>'+total,'t.unreconciled_legacy_attempts<=>'+unresolved,'t.warning_percent<=>s.warning_percent','t.free_only<=>s.free_only','t.expires_at<=>s.expires_at','t.version<=>s.version','t.updated_by<=>s.updated_by','t.updated_at<=>s.updated_at','t.created_at<=>@compact_budget_imported_at'])
def event_compare(source,kind,payload,checks):
    comparison(source,'audit_event',f"BINARY t.legacy_source=BINARY '{source}' AND BINARY t.legacy_key=BINARY CAST(s.id AS CHAR)",[
        f"BINARY t.kind<=>BINARY '{kind}'",f"BINARY t.legacy_source<=>BINARY '{source}'","BINARY t.resource_type<=>BINARY 'LLM_MODEL'","BINARY t.resource_id<=>BINARY s.model_id",'t.payload_version<=>1','BINARY t.payload_json<=>BINARY '+payload,
        't.session_id IS NULL','t.message_id IS NULL','t.run_id IS NULL','t.sequence_no IS NULL','t.revision IS NULL','t.policy_version IS NULL','t.previous_sha256 IS NULL','t.event_sha256 IS NULL',*checks])
event_compare('agent_model_budget_attempt','LLM_LEGACY_ATTEMPT',attempt_payload,["BINARY t.event_id<=>BINARY CONCAT('legacy-model-attempt-',s.id)",'t.owner_user_id IS NULL','t.actor_user_id IS NULL','BINARY t.request_id<=>BINARY s.attempt_id',"BINARY t.action<=>BINARY 'IMPORTED'",'BINARY t.outcome<=>BINARY s.status','BINARY t.content_sha256<=>BINARY SHA2('+attempt_payload+',256)','t.occurred_at<=>COALESCE(s.finished_at,s.started_at)','t.request_scope IS NULL','t.quantity IS NULL','t.unit IS NULL','t.observed_at IS NULL'])
event_compare('agent_model_budget_observation','MODEL_QUOTA_OBSERVATION',"JSON_OBJECT('sourceNote',s.source_note)",["BINARY t.event_id<=>BINARY CONCAT('legacy-model-observation-',s.id)",'t.owner_user_id<=>s.actor_user_id','t.actor_user_id<=>s.actor_user_id','BINARY t.request_id<=>BINARY s.request_id','BINARY t.content_sha256<=>BINARY s.request_sha256',"BINARY t.action<=>BINARY 'OBSERVATION'",'t.quantity<=>s.remaining_tokens',"BINARY t.unit<=>BINARY 'TOKENS'","BINARY t.request_scope<=>BINARY CONCAT('OWNER:',s.actor_user_id)",'t.observed_at<=>s.observed_at','t.occurred_at<=>s.created_at','t.outcome IS NULL'])
event_compare('agent_model_budget_audit','LLM_LEGACY_BUDGET_AUDIT',audit_payload,["BINARY t.event_id<=>BINARY CONCAT('legacy-model-policy-audit-',s.id)",'t.owner_user_id<=>s.actor_user_id','t.actor_user_id<=>s.actor_user_id',"BINARY t.action<=>BINARY 'IMPORTED'",'t.request_id IS NULL','t.request_scope IS NULL','BINARY t.content_sha256<=>BINARY SHA2('+audit_payload+',256)','t.occurred_at<=>s.created_at','t.outcome IS NULL','t.quantity IS NULL','t.unit IS NULL','t.observed_at IS NULL'])
comparison('agent_model_budget_attempt','llm_usage',"t.entry_type='IMPORTED_USAGE' AND t.entry_key='V64_ATTEMPT' AND t.source_audit_event_id=(SELECT e.id FROM audit_event e WHERE BINARY e.legacy_source=BINARY 'agent_model_budget_attempt' AND BINARY e.legacy_key=BINARY CAST(s.id AS CHAR))",[
    "BINARY t.entry_type<=>BINARY 'IMPORTED_USAGE'","BINARY t.entry_key<=>BINARY 'V64_ATTEMPT'","t.account_id<=>(SELECT q.id FROM llm_quota q WHERE q.scope_type='MODEL' AND q.owner_user_id IS NULL AND q.period_key='TOTAL' AND q.model_id=s.model_id)",'t.root_operation_id IS NULL','t.operation_id IS NULL','t.actor_user_id IS NULL','t.reserved_delta<=>0','t.spent_delta<=>'+known,'t.input_tokens<=>s.input_tokens','t.output_tokens<=>s.output_tokens','t.cached_tokens<=>s.cached_tokens','t.limit_before IS NULL','t.limit_after IS NULL',"BINARY t.request_sha256<=>BINARY SHA2(CONCAT('V64_IMPORT',CHAR(10),"+attempt_payload+"),256)",'t.created_at<=>COALESCE(s.finished_at,s.started_at)'])
emit('COMMIT;\nDROP TEMPORARY TABLE compact_budget_checks;\nDROP TEMPORARY TABLE compact_budget_unique_keys;\nDROP TEMPORARY TABLE compact_budget_columns;\nDROP TEMPORARY TABLE compact_budget_guard;')
(ROOT/'sql/mysql/compact/copy/38-model-budget.sql').write_text('\n'.join(sql)+'\n',encoding='utf-8')
print(json.dumps({'status':'AUTHORED_NOT_EXECUTED','sourceTables':len(sources),'sourceColumns':len(rows)}))
