"""Author exact MCP source fixture and compact copy SQL. No DB/application access."""
from pathlib import Path
import importlib.util
import json
import re

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('compact_parser',ROOT/'script/schema/build_compact_schema.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
relations=json.loads((ROOT/'docs/database/compact-mcp-source-map.json').read_text(encoding='utf-8'))['tables']
source_files=['migration-V25-local-mcp.sql','migration-V34-mcp-install-queue.sql',
 'migration-V47-mcp-execution-receipts.sql','migration-V48-fetch-installation-lifecycle.sql',
 'migration-V49-mcp-process-evidence.sql','migration-V58-native-fetch-install-evidence.sql',
 'migration-V59-fetch-shared-images.sql','migration-V60-fetch-deployment-retention.sql']
sources={};fixture=[]
for filename in source_files:
    for statement in p.split_top_level(p.without_comments((ROOT/'sql/mysql'/filename).read_text(encoding='utf-8')), ';'):
        create=re.match(r'CREATE TABLE(?: IF NOT EXISTS)?\s+([a-z_]+)',statement,re.I)
        alter=re.match(r'ALTER TABLE\s+([a-z_]+)\s+(.+)',statement,re.I|re.S)
        if create and create.group(1) in relations:
            name=create.group(1);sources[name]=p.parse_table(statement.replace('CREATE TABLE IF NOT EXISTS','CREATE TABLE',1),filename)
            fixture.append(statement+';')
        elif alter and alter.group(1) in relations:
            name=alter.group(1)
            for change in p.split_top_level(alter.group(2),','):
                addition=re.fullmatch(r'ADD\s+COLUMN\s+(.+)',change.strip(),re.I|re.S)
                if not addition:raise ValueError('Review MCP source alteration: '+change)
                extra=p.parse_table('CREATE TABLE '+name+' ('+addition.group(1)+',compact_pk_seed BIGINT PRIMARY KEY) '+sources[name]['options'],filename)
                extra['columns'].pop('compact_pk_seed')
                if set(extra['columns'])&set(sources[name]['columns']):raise ValueError('Repeated MCP source column')
                sources[name]['columns'].update(extra['columns'])
            fixture.append(statement+';')
        elif statement.startswith('INSERT IGNORE INTO agent_fetch_image_retention_control'):
            fixture.append(statement+';')
assert set(sources)==set(relations) and len(sources)==13
for name,table in sources.items():
    if set(table['columns'])!=set(relations[name]['columns']):raise ValueError('Review every original MCP field: '+name)
target_tables={}
for path in (ROOT/'sql/mysql/compact/baseline').glob('*.sql'):
    for statement in p.split_top_level(p.without_comments(path.read_text(encoding='utf-8-sig')),';'):
        if statement.startswith('CREATE TABLE '):
            table=p.parse_table(statement,path.name);target_tables[table['name']]=table

def q(value):return 'NULL' if value is None else "'"+str(value).replace("'","''")+"'"
def obj(fields):return 'JSON_OBJECT('+','.join(q(k)+','+v for k,v in fields.items())+')'
def src(name):return '`__SOURCE_SCHEMA__`.'+name
def utc(column):return "CONVERT_TZ(s."+column+",'__SOURCE_MCP_OFFSET__','+00:00')"
def clock_expr(column):
    delta="(IF(LEFT('__SOURCE_MCP_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_MCP_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_MCP_OFFSET__',5,2) AS UNSIGNED)*60)*1000000)"
    return "(s."+column+" IS NULL OR ("+utc(column)+" IS NOT NULL AND TIMESTAMPDIFF(MICROSECOND,"+utc(column)+",s."+column+")="+delta+" AND CONVERT_TZ("+utc(column)+",'+00:00','__SOURCE_MCP_OFFSET__')=s."+column+"))"

sql=[]
def emit(value):sql.append(value)
def guard(condition):emit('INSERT INTO compact_mcp_guard SELECT IF(COALESCE(('+condition+'),FALSE),1,0);')
def query_guard(query):emit('INSERT INTO compact_mcp_guard '+query+';')

emit('''-- Thirteen MCP sources: AUTHORED_NOT_EXECUTED. No source DML or compatibility views.
-- Original DDL and ALTER declarations are the metadata authority; original IDs stay legacy evidence.
-- One admitted ECS connection; both schemas frozen. @compact_mcp_source_frozen/target_frozen=1
-- are reviewed assertions, not standalone proof that writers stopped. Never --force.
-- Fixed UTC offset must have source evidence. Unsupported CONVERT_TZ ranges fail, never relabel unchanged times.
-- Snapshot algorithm: MYSQL_JSON_ARRAY_ROW_SHA256_ORDERED_CONCAT_V1, complete original columns/PK order.
-- Bound 50,000 rows per source per reviewed batch. Exact 64*n byte check prevents GROUP_CONCAT truncation.
SET NAMES utf8mb4;
SET @compact_mcp_previous_concat=@@SESSION.group_concat_max_len;
SET SESSION group_concat_max_len=3200000;
CREATE TEMPORARY TABLE compact_mcp_guard(valid INT NOT NULL CHECK(valid=1)) ENGINE=InnoDB;''')
guard("DATABASE() IS NOT NULL AND BINARY DATABASE()<>BINARY '__SOURCE_SCHEMA__' AND @@FOREIGN_KEY_CHECKS=1 AND @compact_mcp_source_frozen=1 AND @compact_mcp_target_frozen=1 AND @@SESSION.sql_mode REGEXP '(^|,)(STRICT_TRANS_TABLES|STRICT_ALL_TABLES)(,|$)' AND '__SOURCE_MCP_OFFSET__' REGEXP '^[+-][0-9]{2}:[0-9]{2}$' AND CONVERT_TZ('2026-01-01','__SOURCE_MCP_OFFSET__','+00:00') IS NOT NULL")
guard("(SELECT COUNT(DISTINCT privilege_type) FROM information_schema.schema_privileges WHERE table_schema='__SOURCE_SCHEMA__' AND privilege_type IN ('SELECT','TRIGGER') AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1))))=2")
names='('+','.join(map(q,sources))+')'
metadata=[];column_rows=[];key_rows=[];collations={};clocks={}
for name,table in sources.items():
    explicit=re.search(r'COLLATE\s*=\s*([a-z0-9_]+)',table['options'],re.I)
    collations[name]=explicit.group(1) if explicit else '__SOURCE_MCP_COLLATION_'+name+'__'
    for ordinal,(column,c) in enumerate(table['columns'].items(),1):
        decl=c['declaration'];kind=c['type'].lower()
        if kind in ('boolean','bool'):kind='tinyint(1)'
        nullable='NO' if column in table['primaryKey'] or 'NOT NULL' in decl.upper() else 'YES'
        collation=re.search(r'\bCOLLATE\s+([a-z0-9_]+)',decl,re.I)
        collation=(collation.group(1) if collation else collations[name]) if kind.startswith(('varchar','char','text','mediumtext','longtext')) else None
        default=re.search(r"\bDEFAULT\s+(CURRENT_TIMESTAMP(?:\(\d+\))?|'[^']*'|FALSE|TRUE|NULL|\d+)",decl,re.I)
        default=default.group(1).strip("'") if default else None
        if default is not None:default={'FALSE':'0','TRUE':'1','NULL':None,'CURRENT_TIMESTAMP(6)':'current_timestamp(6)','CURRENT_TIMESTAMP':'current_timestamp()'}.get(default.upper(),default)
        extra='auto_increment' if 'AUTO_INCREMENT' in decl.upper() else 'default_generated' if default and default.startswith('current_timestamp') else ''
        column_rows.append((name,column,ordinal,kind,nullable,collation,default,extra))
        if kind.startswith('datetime'):clocks.setdefault(name,[]).append(column)
    key_rows.append((name,0,1,','.join(table['primaryKey'])))
    key_rows.extend((name,0,0,','.join(k)) for k in table['uniqueKeys'])
    for declaration in table['constraints']:
        found=re.match(r'KEY\s+[^ (]+\s*\(([^)]+)\)',declaration,re.I)
        if found:key_rows.append((name,1,0,found.group(1).replace(' ','')))
emit('CREATE TEMPORARY TABLE compact_mcp_columns(table_name VARCHAR(64),column_name VARCHAR(64),position_no INT,column_type VARCHAR(64),nullable VARCHAR(3),collation_name VARCHAR(64),default_value VARCHAR(64),extra VARCHAR(64),PRIMARY KEY(table_name,column_name)) ENGINE=InnoDB;')
emit('INSERT INTO compact_mcp_columns VALUES '+','.join('('+','.join(map(q,row))+')' for row in column_rows)+';')
emit('CREATE TEMPORARY TABLE compact_mcp_keys(table_name VARCHAR(64),non_unique INT,is_primary INT,key_columns VARCHAR(1024)) ENGINE=InnoDB;')
emit('INSERT INTO compact_mcp_keys VALUES '+','.join('('+','.join(map(q,row))+')' for row in key_rows)+';')
metadata.append("SELECT IF(COUNT(*)=13,1,0) FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+" AND table_type='BASE TABLE' AND engine='InnoDB'")
metadata.append("SELECT IF(COUNT(*)="+str(len(column_rows))+",1,0) FROM information_schema.columns WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names)
metadata.append("SELECT IF(COUNT(*)=0,1,0) FROM compact_mcp_columns e LEFT JOIN information_schema.columns c ON c.table_schema='__SOURCE_SCHEMA__' AND c.table_name=e.table_name AND c.column_name=e.column_name WHERE c.column_name IS NULL OR c.ordinal_position<>e.position_no OR NOT(BINARY LOWER(c.column_type)<=>BINARY e.column_type) OR NOT(c.is_nullable<=>e.nullable) OR (NOT(c.collation_name<=>e.collation_name) AND NOT(e.column_type='json' AND (c.collation_name IS NULL OR c.collation_name='utf8mb4_bin'))) OR NOT(BINARY (CASE WHEN e.extra='default_generated' THEN LOWER(c.column_default) ELSE c.column_default END)<=>BINARY e.default_value) OR NOT(LOWER(c.extra)<=>e.extra) OR c.generation_expression<>''")
metadata.append("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.triggers WHERE event_object_schema='__SOURCE_SCHEMA__' AND event_object_table IN "+names)
metadata.append("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.table_constraints WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+" AND constraint_type IN ('FOREIGN KEY','CHECK')")
actual="(SELECT table_name,non_unique,(index_name='PRIMARY') is_primary,GROUP_CONCAT(column_name ORDER BY seq_in_index) key_columns,SUM(sub_part IS NOT NULL OR collation<>'A') unsupported FROM information_schema.statistics WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+' GROUP BY table_name,index_name,non_unique)'
metadata.append('SELECT IF(COUNT(*)='+str(len(key_rows))+',1,0) FROM '+actual+' a')
metadata.append('SELECT IF(COUNT(*)=0,1,0) FROM '+actual+' a LEFT JOIN compact_mcp_keys e ON e.table_name=a.table_name AND e.non_unique=a.non_unique AND e.is_primary=a.is_primary AND e.key_columns=a.key_columns WHERE e.table_name IS NULL OR a.unsupported<>0')
for name,collation in collations.items():metadata.append("SELECT IF(COUNT(*)=1,1,0) FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name="+q(name)+' AND table_collation='+q(collation))
for query in metadata:query_guard(query)
emit("CREATE TEMPORARY TABLE compact_mcp_sequences AS SELECT table_name,auto_increment FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+';')
for name,table in sources.items():
    guard('(SELECT COUNT(*) FROM '+src(name)+')<=50000')
    for column in clocks.get(name,[]):guard('NOT EXISTS(SELECT 1 FROM '+src(name)+' s WHERE NOT COALESCE('+clock_expr(column)+',FALSE))')
    if 'id' in table['columns']:guard('NOT EXISTS(SELECT 1 FROM '+src(name)+' WHERE id<=0)')
mcp_kinds=[re.search("kind='([^']+)'",r['discriminator']).group(1) for r in relations.values() if r['target']=='workflow_instance']
for target,predicate in [('agent_connector','TRUE'),('workflow_instance','kind IN ('+','.join(map(q,mcp_kinds))+')'),('content_asset',"asset_kind='CONNECTOR_IMAGE'"),('content_link',"link_kind='CONNECTOR_RETENTION'"),('runtime_state',"namespace='MCP_RETENTION_CONTROL'"),('audit_event',"kind IN ('MCP','MCP_RETENTION','MCP_MIGRATION_CLOCK')")]:
    guard('NOT EXISTS(SELECT 1 FROM '+target+' WHERE '+predicate+')')
# Dedicated one-to-one connector IDs preserve their deleted-ID high water before transactional row copy.
guard("(SELECT auto_increment FROM compact_mcp_sequences WHERE table_name='agent_local_mcp') BETWEEN 1 AND 9223372036854775807")
emit("SET @compact_mcp_connector_sequence=(SELECT auto_increment FROM compact_mcp_sequences WHERE table_name='agent_local_mcp');")
emit("SET @compact_mcp_connector_ddl=CONCAT('ALTER TABLE agent_connector AUTO_INCREMENT=',@compact_mcp_connector_sequence);")
emit('PREPARE compact_mcp_connector_statement FROM @compact_mcp_connector_ddl;')
emit('EXECUTE compact_mcp_connector_statement;')
emit('DEALLOCATE PREPARE compact_mcp_connector_statement;')
emit('START TRANSACTION;')
emit('CREATE TEMPORARY TABLE compact_mcp_snapshots(source_table VARCHAR(64) PRIMARY KEY,row_count BIGINT NOT NULL,snapshot_sha256 CHAR(64) NOT NULL,bytes_count BIGINT NOT NULL) ENGINE=InnoDB;')
snapshot_queries={}
for name,table in sources.items():
    columns=','.join('CAST(s.'+c+' AS CHAR)' if d['type'].upper()=='JSON' else 's.'+c for c,d in table['columns'].items())
    order=','.join('s.'+c for c in table['primaryKey'])
    grouped="COALESCE(GROUP_CONCAT(SHA2(JSON_ARRAY("+columns+"),256) ORDER BY "+order+" SEPARATOR ''),'')"
    expression='SELECT COUNT(*),SHA2('+grouped+',256),OCTET_LENGTH('+grouped+') FROM '+src(name)+' s'
    snapshot_queries[name]=expression
    emit('INSERT INTO compact_mcp_snapshots SELECT '+q(name)+',v.* FROM ('+expression+') v;')
guard('NOT EXISTS(SELECT 1 FROM compact_mcp_snapshots WHERE bytes_count<>row_count*64)')
copies=[]
owner_scoped={'agent_mcp_execution_command','agent_fetch_installation','agent_fetch_lifecycle_command','agent_mcp_install_worker','agent_fetch_image_command'}
for name,r in relations.items():
    target=r['target'];mapping={}
    for field in r['columns']:
        if field=='id' and target!='agent_connector':continue
        if field=='detail_json':continue
        destination=r['mapping'][field]
        if destination.startswith('CAST('):destination='scope_key'
        expression='s.'+field
        if field in clocks.get(name,[]):expression=utc(field)
        if destination=='scope_key':expression='CAST(s.'+field+' AS CHAR)'
        mapping[destination]=expression
    if target=='workflow_instance':
        kind=re.search("kind='([^']+)'",r['discriminator']).group(1)
        natural='s.'+r['natural']
        mapping.update(workflow_id="CONCAT('mcp:"+name+":',s.id)",kind=q(kind),resource_type=q(kind),idempotency_scope="CONCAT('"+kind+":OWNER:',s.owner_user_id)" if name in owner_scoped else q(kind),payload_version='1',payload_json="JSON_OBJECT('schemaVersion',1)",legacy_source=q(name),legacy_key='CAST(s.id AS CHAR)',mcp_source_created_at='s.created_at',mcp_source_updated_at='s.updated_at',mcp_source_utc_offset=q('__SOURCE_MCP_OFFSET__'))
        mapping.setdefault('request_id',natural);mapping.setdefault('request_sha256','SHA2('+natural+',256)');mapping.setdefault('revision','0')
        predicate='t.kind='+q(kind);join=predicate+' AND t.legacy_source='+q(name)+' AND BINARY t.legacy_key=BINARY CAST(s.id AS CHAR)'
    elif name=='agent_local_mcp':predicate='TRUE';join='t.id=s.id'
    elif name=='agent_local_mcp_audit':
        mapping.update(event_id="CONCAT('legacy-mcp-audit-',s.id)",kind=q('MCP'),resource_type=q('MCP_CONNECTOR'),payload_version='1',payload_json=obj({'schemaVersion':'1','detailJson':'CAST(s.detail_json AS CHAR)'}),legacy_source=q(name),legacy_key='CAST(s.id AS CHAR)')
        predicate="t.kind='MCP'";join=predicate+" AND t.legacy_source='agent_local_mcp_audit' AND BINARY t.legacy_key=BINARY CAST(s.id AS CHAR)"
    elif name=='agent_fetch_image':
        mapping.update(asset_id="CONCAT('connector-image:',s.image_id)",asset_kind=q('CONNECTOR_IMAGE'),title='s.image_id',visibility=q('SYSTEM'),created_at='NULL',legacy_source=q(name))
        predicate="t.asset_kind='CONNECTOR_IMAGE'";join=predicate+' AND t.identity_key=s.image_id'
    elif name=='agent_fetch_image_retention':
        mapping.update(link_kind=q('CONNECTOR_RETENTION'),target_type=q('CONNECTOR_IMAGE'),created_at='NULL',legacy_source=q(name))
        predicate="t.link_kind='CONNECTOR_RETENTION'";join=predicate+' AND t.subject_id=s.reference_id AND t.target_id=s.image_id'
    elif name=='agent_fetch_image_retention_control':
        mapping.update(namespace=q('MCP_RETENTION_CONTROL'),owner_id='0',created_at='NULL',payload_version='1')
        predicate="t.namespace='MCP_RETENTION_CONTROL'";join=predicate+' AND t.owner_id=0 AND t.scope_key=CAST(s.control_id AS CHAR)'
    elif name=='agent_fetch_image_retention_event':
        mapping.update(event_id="CONCAT('legacy-mcp-retention-',s.id)",kind=q('MCP_RETENTION'),resource_type=q('CONNECTOR_IMAGE'),outcome=q('RECORDED'),payload_version='1',payload_json="JSON_OBJECT('schemaVersion',1)",legacy_source=q(name),legacy_key='CAST(s.id AS CHAR)')
        predicate="t.kind='MCP_RETENTION'";join=predicate+" AND t.legacy_source='agent_fetch_image_retention_event' AND BINARY t.legacy_key=BINARY CAST(s.id AS CHAR)"
    else:raise ValueError('Unreviewed MCP route '+name)
    for destination in mapping:
        if destination not in target_tables[target]['columns']:raise ValueError('Missing target column '+target+'.'+destination)
    emit('INSERT INTO '+target+'('+','.join(mapping)+') SELECT '+','.join(mapping.values())+' FROM '+src(name)+' s ORDER BY '+','.join('s.'+c for c in sources[name]['primaryKey'])+';')
    copies.append((name,target,mapping,predicate,join))
emit('SET @compact_mcp_imported_at=UTC_TIMESTAMP(6);')
emit("INSERT INTO audit_event(event_id,kind,resource_type,resource_id,action,payload_version,payload_json,occurred_at) SELECT CONCAT('mcp-migration-clock:',source_table),'MCP_MIGRATION_CLOCK','MCP_MIGRATION',source_table,'IMPORTED',1,JSON_OBJECT('sourceTable',source_table,'sourceUtcOffset','__SOURCE_MCP_OFFSET__','sourceSnapshotSha256',snapshot_sha256,'rowCount',row_count),@compact_mcp_imported_at FROM compact_mcp_snapshots;")
for name,target,mapping,predicate,join in copies:
    conditions=[]
    for column,definition in target_tables[target]['columns'].items():
        if definition['generatedVirtual'] or (column=='id' and target!='agent_connector'):continue
        expected=mapping.get(column)
        if expected is None:
            match=re.search(r'\bDEFAULT\s+([^\s,]+)',definition['declaration'],re.I)
            expected=match.group(1) if match else 'NULL'
        if definition['type'].upper()=='JSON':conditions.append('NOT(BINARY CAST(t.'+column+' AS CHAR)<=>BINARY CAST('+expected+' AS CHAR))')
        else:conditions.append('NOT(BINARY t.'+column+'<=>BINARY '+expected+')')
    guard('(SELECT COUNT(*) FROM '+target+' t WHERE '+predicate+')=(SELECT COUNT(*) FROM '+src(name)+')')
    guard('NOT EXISTS(SELECT 1 FROM '+src(name)+' s LEFT JOIN '+target+' t ON '+join+' WHERE t.'+('namespace' if target=='runtime_state' else 'id')+' IS NULL OR '+' OR '.join(conditions)+')')
for name,expression in snapshot_queries.items():
    guard("(SELECT row_count FROM compact_mcp_snapshots WHERE source_table="+q(name)+")=(SELECT n FROM ("+expression.replace('SELECT COUNT(*),','SELECT COUNT(*) n,',1)+") z)")
    guard("(SELECT snapshot_sha256 FROM compact_mcp_snapshots WHERE source_table="+q(name)+")=(SELECT h FROM ("+expression.replace('SELECT COUNT(*),SHA2(','SELECT COUNT(*),SHA2(',1).replace(',256),OCTET_LENGTH',',256) h,OCTET_LENGTH',1)+") z)")
guard("(SELECT COUNT(*) FROM audit_event WHERE kind='MCP_MIGRATION_CLOCK')=13")
clock_mapping=dict(event_id="CONCAT('mcp-migration-clock:',s.source_table)",kind=q('MCP_MIGRATION_CLOCK'),resource_type=q('MCP_MIGRATION'),resource_id='s.source_table',action=q('IMPORTED'),payload_version='1',payload_json="JSON_OBJECT('sourceTable',s.source_table,'sourceUtcOffset','__SOURCE_MCP_OFFSET__','sourceSnapshotSha256',s.snapshot_sha256,'rowCount',s.row_count)",occurred_at='@compact_mcp_imported_at')
clock_checks=[]
for column,definition in target_tables['audit_event']['columns'].items():
    if column=='id' or definition['generatedVirtual']:continue
    match=re.search(r'\bDEFAULT\s+([^\s,]+)',definition['declaration'],re.I)
    expected=clock_mapping.get(column,match.group(1) if match else 'NULL')
    clock_checks.append('NOT(BINARY a.'+column+'<=>BINARY '+expected+')')
guard("NOT EXISTS(SELECT 1 FROM compact_mcp_snapshots s LEFT JOIN audit_event a ON a.kind='MCP_MIGRATION_CLOCK' AND a.resource_id=s.source_table WHERE a.id IS NULL OR "+' OR '.join(clock_checks)+')')
for query in metadata:query_guard(query)
guard("NOT EXISTS(SELECT 1 FROM compact_mcp_sequences e LEFT JOIN information_schema.tables t ON t.table_schema='__SOURCE_SCHEMA__' AND t.table_name=e.table_name WHERE t.table_name IS NULL OR NOT(t.auto_increment<=>e.auto_increment))")
emit('COMMIT;')
emit('SET SESSION group_concat_max_len=@compact_mcp_previous_concat;')
out=ROOT/'sql/mysql/compact/copy/48-mcp.sql';out.write_text('\n'.join(sql)+'\n',encoding='utf-8')
resource=ROOT/'doorhandle-module-ai/src/test/resources/compact/mcp-source-evidence.sql';resource.parent.mkdir(parents=True,exist_ok=True);resource.write_text('-- Exact original MCP DDL/ALTER; authored from checked-in declarations.\n'+'\n'.join(fixture)+'\n',encoding='utf-8')
print(json.dumps({'status':'AUTHORED_NOT_EXECUTED','sourceTables':len(sources),'sourceColumns':len(column_rows),'copy':str(out.relative_to(ROOT))}))
