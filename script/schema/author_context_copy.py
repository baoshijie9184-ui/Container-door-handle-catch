"""Author six-table V44 context copy from checked-in DDL; no DB or application runs."""
from pathlib import Path
import importlib.util
import re

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('compact_parser', ROOT/'script/schema/build_compact_schema.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
source_text = (ROOT/'sql/mysql/migration-V44-agent-durable-context.sql').read_text(encoding='utf-8')
sources = {}
for statement in p.split_top_level(p.without_comments(source_text), ';'):
    if statement.startswith('CREATE TABLE'):
        table = p.parse_table(statement.replace('CREATE TABLE IF NOT EXISTS', 'CREATE TABLE', 1), 'V44')
        if table['name'] != 'agent_context_turn':
            sources[table['name']] = table
targets = {}
for path in (ROOT/'sql/mysql/compact/baseline').glob('*.sql'):
    for statement in p.split_top_level(p.without_comments(path.read_text(encoding='utf-8-sig')), ';'):
        if statement.startswith('CREATE TABLE '):
            table = p.parse_table(statement, path.name)
            targets[table['name']] = table

def q(value):
    return 'NULL' if value is None else "'"+str(value).replace("'", "''")+"'"

sql = []
def emit(value): sql.append(value)
def guard(query): emit('INSERT INTO compact_context_guard '+query+';')
def yes(condition): guard('SELECT IF('+condition+',1,0)')
def src(table): return '`__SOURCE_SCHEMA__`.'+table
def raw_time(column): return "DATE_FORMAT(s."+column+",'%Y-%m-%d %H:%i:%s.%f')"
def utc(column): return "CONVERT_TZ(s."+column+",'__SOURCE_CONTEXT_OFFSET__','+00:00')"
def obj(**fields): return 'JSON_OBJECT('+','.join(q(k)+','+v for k,v in fields.items())+')'
def scope(state):
    return "SHA2(CONCAT(OCTET_LENGTH(RTRIM(s.session_id)),':',RTRIM(s.session_id),':',OCTET_LENGTH(RTRIM(s."+state+")),':',RTRIM(s."+state+")),256)"
def key(*fields):
    return "CONCAT("+",':',".join("CONCAT(OCTET_LENGTH(CAST(s."+f+" AS CHAR)),':',CAST(s."+f+" AS CHAR))" for f in fields)+")"
def original_digest(fields):
    # Original Jackson compact list algorithm: explicit separators, never SQL JSON_ARRAY formatting.
    pieces = ["CAST(s."+f+" AS CHAR)" if numeric else 'JSON_QUOTE(s.'+f+')' for f,numeric in fields]
    return "SHA2(CONCAT('[',"+",',',".join(pieces)+",']'),256)"

emit('''-- Six V44 context tables: AUTHORED_NOT_EXECUTED. Original source rows/IDs/SHA/JSON remain unchanged.
-- Run on one admitted ECS connection, distinct schemas, frozen writers, real complete target baseline.
-- Caller must establish @compact_context_source_frozen=1 and @compact_context_target_frozen=1
-- from the reviewed migration window; these flags are assertions, not proof of a write freeze.
-- First SQL error requires same-connection ROLLBACK and close. Never --force.
-- JSON_ARRAY is deliberately not used for original Java digests. Native-MySQL/Java parity is an ECS gate.
SET NAMES utf8mb4;
CREATE TEMPORARY TABLE compact_context_guard(valid INT NOT NULL CHECK(valid=1)) ENGINE=InnoDB;''')
yes("DATABASE() IS NOT NULL AND BINARY DATABASE()<>BINARY '__SOURCE_SCHEMA__' AND @@FOREIGN_KEY_CHECKS=1 AND @@SESSION.sql_mode REGEXP '(^|,)(STRICT_TRANS_TABLES|STRICT_ALL_TABLES)(,|$)' AND @compact_context_source_frozen=1 AND @compact_context_target_frozen=1 AND '__SOURCE_CONTEXT_OFFSET__' REGEXP '^[+-][0-9]{2}:[0-9]{2}$' AND CONVERT_TZ('2026-01-01 00:00:00','__SOURCE_CONTEXT_OFFSET__','+00:00') IS NOT NULL")
guard("SELECT IF(COUNT(DISTINCT privilege_type)=2,1,0) FROM information_schema.schema_privileges WHERE table_schema='__SOURCE_SCHEMA__' AND privilege_type IN ('SELECT','TRIGGER') AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)))")
names='('+','.join(map(q,sources))+')'
rows=[]
for name,table in sources.items():
    for ordinal,(column,c) in enumerate(table['columns'].items(),1):
        dec=c['declaration']; kind=c['type'].lower()
        default=re.search(r'\bDEFAULT\s+([^\s,]+)',dec,re.I)
        rows.append((name,column,ordinal,kind,'YES' if re.search(r'\bNULL\b',dec,re.I) and not re.search(r'NOT\s+NULL|PRIMARY\s+KEY',dec,re.I) else 'NO',
                     c['collation'] if kind.startswith(('char','varchar','text','mediumtext')) else None,
                     default.group(1).strip("'") if default else None,'auto_increment' if 'AUTO_INCREMENT' in dec.upper() else ''))
assert len(rows)==60
emit('CREATE TEMPORARY TABLE compact_context_columns(table_name VARCHAR(64),column_name VARCHAR(64),position_no INT,column_type VARCHAR(64),nullable VARCHAR(3),collation_name VARCHAR(64),default_value VARCHAR(64),extra VARCHAR(64),PRIMARY KEY(table_name,column_name)) ENGINE=InnoDB;')
emit('INSERT INTO compact_context_columns VALUES '+','.join('('+','.join(map(q,row))+')' for row in rows)+';')
metadata=[]
metadata.append("SELECT IF(COUNT(*)=6,1,0) FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+" AND table_type='BASE TABLE' AND engine='InnoDB' AND table_collation='utf8mb4_bin'")
metadata.append("SELECT IF(COUNT(*)=60,1,0) FROM information_schema.columns WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names)
metadata.append("SELECT IF(COUNT(*)=0,1,0) FROM compact_context_columns e LEFT JOIN information_schema.columns c ON c.table_schema='__SOURCE_SCHEMA__' AND c.table_name=e.table_name AND c.column_name=e.column_name WHERE c.column_name IS NULL OR c.ordinal_position<>e.position_no OR NOT(BINARY LOWER(c.column_type)<=>BINARY e.column_type) OR NOT(c.is_nullable<=>e.nullable) OR NOT(c.collation_name<=>e.collation_name) OR NOT(c.column_default<=>e.default_value) OR NOT(LOWER(c.extra)<=>e.extra) OR c.generation_expression<>''")
metadata.append("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.triggers WHERE event_object_schema='__SOURCE_SCHEMA__' AND event_object_table IN "+names)
metadata.append("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.table_constraints WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+" AND constraint_type IN ('FOREIGN KEY','CHECK')")
emit('CREATE TEMPORARY TABLE compact_context_keys(table_name VARCHAR(64),non_unique INT,is_primary INT,key_columns VARCHAR(1024)) ENGINE=InnoDB;')
keys=[]
for name,table in sources.items():
    keys.append((name,0,1,','.join(table['primaryKey'])))
    keys.extend((name,0,0,','.join(k)) for k in table['uniqueKeys'])
    for declaration in table['constraints']:
        match=re.match(r'KEY\s+[^ (]+\s*\(([^)]+)\)',declaration,re.I)
        if match: keys.append((name,1,0,match.group(1).replace(' ','')))
emit('INSERT INTO compact_context_keys VALUES '+','.join('('+','.join(map(q,row))+')' for row in keys)+';')
actual="(SELECT table_name,non_unique,(index_name='PRIMARY') is_primary,GROUP_CONCAT(column_name ORDER BY seq_in_index) key_columns,SUM(sub_part IS NOT NULL OR collation<>'A') unsupported FROM information_schema.statistics WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+' GROUP BY table_name,index_name,non_unique)'
metadata.append('SELECT IF(COUNT(*)='+str(len(keys))+',1,0) FROM '+actual+' a')
metadata.append('SELECT IF(COUNT(*)=0,1,0) FROM '+actual+' a LEFT JOIN compact_context_keys e ON e.table_name=a.table_name AND e.non_unique=a.non_unique AND e.is_primary=a.is_primary AND e.key_columns=a.key_columns WHERE e.table_name IS NULL OR a.unsupported<>0')
for query in metadata: guard(query)
emit("CREATE TEMPORARY TABLE compact_context_sequences AS SELECT table_name,auto_increment FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+';')
for name in sources:
    guard('SELECT IF(COUNT(*)=0,1,0) FROM '+src(name)+' WHERE user_id<=0')
for table,where in [('runtime_state',"namespace IN ('CONTEXT_HEAD','CONTEXT_BOOTSTRAP')"),('content_asset',"asset_kind='CONTEXT_SUMMARY'"),('content_revision',"asset_kind='CONTEXT_SUMMARY'"),('content_link',"link_kind IN ('TOOL_SOURCE','CONTEXT_SOURCE')"),('audit_event',"kind='CONTEXT'")]:
    guard('SELECT IF(COUNT(*)=0,1,0) FROM '+table+' WHERE '+where)
for name in ['agent_context_summary','agent_context_offload','agent_context_audit']:
    offset="(IF(LEFT('__SOURCE_CONTEXT_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_CONTEXT_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_CONTEXT_OFFSET__',5,2) AS UNSIGNED)*60)*1000000)"
    guard(f"SELECT IF(COUNT(*)=0,1,0) FROM {src(name)} s WHERE NOT COALESCE(({utc('created_at')} IS NOT NULL AND TIMESTAMPDIFF(MICROSECOND,{utc('created_at')},s.created_at)={offset}),FALSE)")
for name in ['agent_context_origin','agent_context_offload']:
    guard(f"SELECT IF(COUNT(*)=0,1,0) FROM {src(name)} s WHERE NOT JSON_VALID(s.sources_json) OR NOT REGEXP_LIKE(s.sources_sha256,'^[A-Fa-f0-9]{{64}}$','c') OR NOT(BINARY LOWER(s.sources_sha256)<=>BINARY SHA2(s.sources_json,256))")
boot_hash=original_digest([(x,x in ('user_id','history_through')) for x in ['user_id','session_id','agent_scope','logical_task_id','history_through','initial_state']])
summary_hash=original_digest([(x,x=='covered_through') for x in ['summary_json','message_state','sources_json','agent_scope','covered_through','history_sha256','original_state']])
guard(f"SELECT IF(COUNT(*)=0,1,0) FROM {src('agent_context_bootstrap')} s WHERE initialized NOT IN (0,1) OR history_through<0 OR NOT JSON_VALID(initial_state) OR NOT(BINARY LOWER(initial_sha256)<=>BINARY {boot_hash})")
guard(f"SELECT IF(COUNT(*)=0,1,0) FROM {src('agent_context_summary')} s WHERE revision<0 OR covered_through<0 OR before_chars<0 OR after_chars<0 OR status NOT IN ('ACTIVE','INVALIDATED') OR NOT JSON_VALID(message_state) OR NOT JSON_VALID(original_state) OR NOT JSON_VALID(sources_json) OR NOT REGEXP_LIKE(history_sha256,'^[A-Fa-f0-9]{{64}}$','c') OR NOT(BINARY LOWER(summary_sha256)<=>BINARY {summary_hash})")
guard(f"SELECT IF(COUNT(*)=0,1,0) FROM {src('agent_context_offload')} s WHERE byte_length<0 OR NOT REGEXP_LIKE(content_sha256,'^[A-Fa-f0-9]{{64}}$','c')")
guard(f"SELECT IF(COUNT(*)=0,1,0) FROM {src('agent_context_audit')} s WHERE NOT REGEXP_LIKE(content_sha256,'^[A-Fa-f0-9]{{64}}$','c')")

copies=[]
def copy(name,target,mapping,predicate,join):
    columns=','.join(mapping)
    order=','.join('s.'+column for column in sources[name]['primaryKey'])
    emit('INSERT INTO '+target+'('+columns+') SELECT '+','.join(mapping.values())+' FROM '+src(name)+' s ORDER BY '+order+';')
    copies.append((name,target,mapping,predicate,join))
emit('START TRANSACTION;')
copy('agent_context_head','runtime_state',dict(namespace=q('CONTEXT_HEAD'),owner_id='s.user_id',scope_key=scope('agent_scope'),session_id='s.session_id',state_key='s.agent_scope',revision='s.revision',current_ref='s.summary_id',payload_version='1',payload_json=obj(legacySource=q('agent_context_head')),created_at='NULL',updated_at='NULL'),"t.namespace='CONTEXT_HEAD'","t.namespace='CONTEXT_HEAD' AND t.owner_id=s.user_id AND t.session_id=s.session_id AND t.state_key=s.agent_scope")
copy('agent_context_bootstrap','runtime_state',dict(namespace=q('CONTEXT_BOOTSTRAP'),owner_id='s.user_id',scope_key=scope('logical_task_id'),session_id='s.session_id',state_key='s.logical_task_id',revision='0',counter_value='s.history_through',state_code="IF(s.initialized=1,'INITIALIZED','RESERVED')",payload_version='1',payload_json=obj(agentScope='s.agent_scope',initialState='s.initial_state',initialSha256='s.initial_sha256',legacySource=q('agent_context_bootstrap')),created_at='NULL',updated_at='NULL'),"t.namespace='CONTEXT_BOOTSTRAP'","t.namespace='CONTEXT_BOOTSTRAP' AND t.owner_id=s.user_id AND t.session_id=s.session_id AND t.state_key=s.logical_task_id")
asset=dict(asset_id="CONCAT('context-summary:',s.summary_id)",asset_kind=q('CONTEXT_SUMMARY'),owner_user_id='s.user_id',identity_key='s.summary_id',title=q('持久上下文摘要'),visibility=q('PRIVATE'),lifecycle=q('PREPARING'),created_at=utc('created_at'),updated_at='NULL',legacy_source=q('agent_context_summary'),legacy_id='s.id')
copy('agent_context_summary','content_asset',asset,"t.asset_kind='CONTEXT_SUMMARY'","t.asset_kind='CONTEXT_SUMMARY' AND t.legacy_source='agent_context_summary' AND t.legacy_id=s.id")
manifest=obj(schemaVersion='1',sessionId='s.session_id',agentScope='s.agent_scope',contextRevision='s.revision',coveredThrough='s.covered_through',historySha256='s.history_sha256',messageState='s.message_state',policyVersion='s.policy_version',beforeChars='s.before_chars',afterChars='s.after_chars',originalState='s.original_state',createdAtSource=raw_time('created_at'),sourceUtcOffset=q('__SOURCE_CONTEXT_OFFSET__'))
copy('agent_context_summary','content_revision',dict(asset_id=asset['asset_id'],asset_kind=q('CONTEXT_SUMMARY'),version='1',owner_user_id='s.user_id',content_text='s.summary_json',content_sha256='s.summary_sha256',sources_json='s.sources_json',source_run_id='s.run_id',manifest_json=manifest,created_at=utc('created_at'),legacy_source=q('agent_context_summary'),legacy_id='s.id'),"t.asset_kind='CONTEXT_SUMMARY'","t.asset_kind='CONTEXT_SUMMARY' AND t.legacy_source='agent_context_summary' AND t.legacy_id=s.id")
emit("UPDATE content_asset t JOIN "+src('agent_context_summary')+" s ON t.legacy_source='agent_context_summary' AND t.legacy_id=s.id AND t.asset_kind='CONTEXT_SUMMARY' SET t.current_version=1,t.lifecycle=s.status;")
asset.update(lifecycle='s.status',current_version='1')
copy('agent_context_origin','content_link',dict(link_kind=q('TOOL_SOURCE'),owner_user_id='s.user_id',session_id='s.session_id',agent_scope='s.agent_scope',call_id='s.call_key',logical_task_id='s.logical_task_id',run_id='s.run_id',target_type=q('CONTEXT_TASK'),target_id='s.logical_task_id',evidence_version='1',evidence_json=obj(sourcesJson='s.sources_json',sourcesSha256='s.sources_sha256'),created_at='NULL',legacy_source=q('agent_context_origin')),"t.link_kind='TOOL_SOURCE'","t.link_kind='TOOL_SOURCE' AND t.owner_user_id=s.user_id AND t.session_id=s.session_id AND t.agent_scope=s.agent_scope AND t.call_id=s.call_key")
copy('agent_context_offload','content_link',dict(link_kind=q('CONTEXT_SOURCE'),owner_user_id='s.user_id',session_id='s.session_id',agent_scope='s.agent_scope',call_id='s.call_id',target_type=q('WORKSPACE_FILE'),target_id='s.file_id',subject_type=q('CONTEXT_OFFLOAD'),subject_id='s.offload_id',evidence_version='1',evidence_json=obj(contentSha256='s.content_sha256',byteLength='s.byte_length',sourcesJson='s.sources_json',sourcesSha256='s.sources_sha256',createdAtSource=raw_time('created_at'),sourceUtcOffset=q('__SOURCE_CONTEXT_OFFSET__'),lineageKind=q('LEGACY'),sourceOffloadId='NULL',sourceSessionId='NULL',throughMessageId='NULL'),created_at=utc('created_at'),legacy_source=q('agent_context_offload'),legacy_id='s.id'),"t.link_kind='CONTEXT_SOURCE'","t.link_kind='CONTEXT_SOURCE' AND t.legacy_source='agent_context_offload' AND t.legacy_id=s.id")
copy('agent_context_audit','audit_event',dict(event_id="CONCAT('legacy-context-audit-',s.id)",kind=q('CONTEXT'),owner_user_id='s.user_id',resource_type=q('CONTEXT'),resource_id='s.resource_id',session_id='s.session_id',action='s.action',content_sha256='s.content_sha256',occurred_at=utc('created_at'),payload_version='1',payload_json=obj(agentScope='s.agent_scope',createdAtSource=raw_time('created_at'),sourceUtcOffset=q('__SOURCE_CONTEXT_OFFSET__')),legacy_source=q('agent_context_audit'),legacy_key='CAST(s.id AS CHAR)'),"t.kind='CONTEXT'","t.kind='CONTEXT' AND t.legacy_source='agent_context_audit' AND BINARY t.legacy_key=BINARY CAST(s.id AS CHAR)")
for name,target,mapping,predicate,join in copies:
    conditions=[]
    for column,definition in targets[target]['columns'].items():
        if column=='id' or definition['generatedVirtual']: continue
        expected=mapping.get(column)
        if expected is None:
            match=re.search(r'\bDEFAULT\s+([^\s,]+)',definition['declaration'],re.I)
            expected=match.group(1) if match else 'NULL'
        conditions.append('NOT(BINARY t.'+column+'<=>BINARY '+expected+')')
    guard('SELECT IF((SELECT COUNT(*) FROM '+target+' t WHERE '+predicate+')=(SELECT COUNT(*) FROM '+src(name)+'),1,0)')
    guard('SELECT IF(COUNT(*)=0,1,0) FROM '+src(name)+' s LEFT JOIN '+target+' t ON '+join+' WHERE t.'+('namespace' if target=='runtime_state' else 'id')+' IS NULL OR '+' OR '.join(conditions))
for query in metadata: guard(query)
guard("SELECT IF(COUNT(*)=0,1,0) FROM compact_context_sequences e LEFT JOIN information_schema.tables t ON t.table_schema='__SOURCE_SCHEMA__' AND t.table_name=e.table_name WHERE t.table_name IS NULL OR NOT(t.auto_increment<=>e.auto_increment)")
emit('COMMIT;')
emit('-- Original SHA/JSON/time and NULL-safe ordinary-column checks are executed again after every insert.')
out=ROOT/'sql/mysql/compact/copy/45-context.sql'
out.write_text('\n'.join(sql)+'\n',encoding='utf-8')
print('Authored copy/45-context.sql: six source tables, 60 original columns; not executed')
