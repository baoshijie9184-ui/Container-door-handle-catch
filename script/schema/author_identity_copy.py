"""Author eleven original identity tables and exact compact copy SQL; never connects to MySQL."""
from pathlib import Path
import importlib.util
import json
import re

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('compact_parser', ROOT/'script/schema/build_compact_schema.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

FILES = ['migration-V40-stable-identity-audit.sql', 'migration-V54-assignment-identity.sql',
         'migration-V55-identity-mapping-review.sql', 'migration-V56-identity-binding-evidence.sql',
         'migration-V57-identity-reconciliation.sql', 'migration-V61-missing-identity-name-review.sql']
RELATIONS = {
    'detection_identity_control': ('runtime_state', 'DETECTION_IDENTITY_CONTROL', 'CONTROL'),
    'detection_identity_source_control': ('runtime_state', 'DETECTION_IDENTITY_SOURCE_CONTROL', 'SOURCE_CONTROL'),
    'detection_identity_command': ('workflow_instance', 'DETECTION_IDENTITY_COMMAND', 'COMMANDS'),
    'detection_identity_mapping_batch': ('workflow_instance', 'DETECTION_IDENTITY_MAP_BATCH', 'BATCHES'),
    'detection_identity_mapping_item': ('workflow_instance', 'DETECTION_IDENTITY_MAP_ITEM', 'MAPPINGS'),
    'detection_identity_reconciliation_report': ('workflow_instance', 'DETECTION_IDENTITY_REPORT', 'REPORTS'),
    'detection_assignment_identity_event': ('audit_event', 'DETECTION_ASSIGNMENT_IDENTITY', 'ASSIGNMENTS'),
    'detection_identity_binding_event': ('audit_event', 'DETECTION_IDENTITY_BINDING_EVENT', 'EVENTS'),
    'detection_identity_reconciliation_item': ('audit_event', 'DETECTION_IDENTITY_RECON_ITEM', 'ISSUES'),
    'detection_identity_missing_name_evidence': ('audit_event', 'DETECTION_IDENTITY_MISSING_NAME', 'MISSING'),
    'detection_identity_binding': ('runtime_state', 'DETECTION_IDENTITY_BINDING', 'HEADS'),
}
sources, fixture = {}, []
for filename in FILES:
    for statement in p.split_top_level(p.without_comments((ROOT/'sql/mysql'/filename).read_text(encoding='utf8')), ';'):
        create = re.match(r'CREATE TABLE(?: IF NOT EXISTS)?\s+([a-z_]+)', statement, re.I)
        if create and create.group(1) in RELATIONS:
            name = create.group(1)
            if name in sources:
                raise ValueError('Repeated original identity declaration')
            sources[name] = p.parse_table(statement.replace('CREATE TABLE IF NOT EXISTS', 'CREATE TABLE', 1), filename)
            fixture.append(statement + ';')
if set(sources) != set(RELATIONS):
    raise ValueError('Every original identity source must be declared')

java = (ROOT/'doorhandle-module-detection/src/main/java/com/ruanzhu/doorhandle/module/detection/service/DetectionIdentityPersistence.java').read_text(encoding='utf8')
PROJECTIONS = dict(re.findall(r'public static final String ([A-Z_]+) = """\s*(.*?)\s*""";', java, re.S))
if set(PROJECTIONS) != {value[2] for value in RELATIONS.values()}:
    raise ValueError('Identity source and runtime projections differ')


def q(value):
    return 'NULL' if value is None else "'" + str(value).replace("'", "''") + "'"


def obj(**fields):
    return 'JSON_OBJECT(' + ','.join(q(k) + ',' + value for k, value in fields.items()) + ')'


def raw(column):
    return "DATE_FORMAT(s." + column + ",'%Y-%m-%d %H:%i:%s.%f')"


def utc(column):
    return "CONVERT_TZ(s." + column + ",'__SOURCE_IDENTITY_OFFSET__','+00:00')"


def sid(column='id'):
    return 'CAST(s.' + column + ' AS CHAR)'


def identity_scope(task='s.task_id', role='s.identity_role'):
    return "SHA2(CONCAT(CHAR_LENGTH(RTRIM(" + task + ")),':',RTRIM(" + task + "),':',RTRIM(" + role + ")),256)"


def original_key(name, alias='s'):
    return 'JSON_ARRAY(' + ','.join(alias + '.`' + column + '`' for column in sources[name]['primaryKey']) + ')'


def original_row(name, alias='s'):
    return 'JSON_ARRAY(' + ','.join(alias + '.`' + column + '`' for column in sources[name]['columns']) + ')'


def legacy_key(name):
    keys = sources[name]['primaryKey']
    return 'CAST(s.`' + keys[0] + '` AS CHAR)' if len(keys) == 1 else 'SHA2(' + original_key(name) + ',256)'


def workflow(kind, source, payload, actor='s.actor_user_id', result=None, created='created_at', revision='NULL', status='COMPLETED'):
    return dict(workflow_id='SHA2(CONCAT(' + q(kind + ':') + ',' + legacy_key(source) + '),256)',
                kind=q(kind), idempotency_scope=q(kind), request_id='s.request_id' if 'request_id' in sources[source]['columns'] else sid(),
                request_sha256='s.request_sha256' if 'request_sha256' in sources[source]['columns'] else 's.command_sha256' if 'command_sha256' in sources[source]['columns'] else 'SHA2(' + original_row(source) + ',256)',
                owner_user_id='CASE WHEN ' + actor + '>0 THEN ' + actor + ' ELSE 0 END',
                actor_user_id='CASE WHEN ' + actor + '>0 THEN ' + actor + ' END',
                resource_type=q('DETECTION_IDENTITY'), resource_id=q('GLOBAL'), resource_revision=revision,
                status=q(status), payload_version='1', payload_json=payload,
                result_version='1' if result else 'NULL', result_json=result or 'NULL', result_sha256='SHA2(' + result + ',256)' if result else 'NULL',
                created_at=utc(created) if created else 'NULL', updated_at=utc(created) if created else 'NULL',
                finished_at=utc(created) if created else 'NULL', legacy_source=q(source), legacy_key=legacy_key(source))


def audit(kind, source, payload, action, owner='NULL', actor='NULL', created='created_at'):
    return dict(event_id='SHA2(CONCAT(' + q(kind + ':') + ',' + legacy_key(source) + '),256)', kind=q(kind),
                owner_user_id='CASE WHEN ' + owner + '>0 THEN ' + owner + ' END',
                actor_user_id='CASE WHEN ' + actor + '>0 THEN ' + actor + ' END',
                resource_type=q('DETECTION_IDENTITY'), resource_id='s.task_id', action=action,
                payload_version='1', payload_json=payload, occurred_at=utc(created) if created else 'NULL',
                legacy_source=q(source), legacy_key=legacy_key(source))


MAPPINGS = {}
for name in ('detection_identity_control', 'detection_identity_source_control'):
    MAPPINGS[name] = dict(namespace=q(RELATIONS[name][1]), owner_id='0', scope_key=sid('control_id'),
                         revision='s.revision' if name.endswith('_control') and name == 'detection_identity_control' else '0',
                         state_code='s.mode', payload_version='1',
                         payload_json=obj(controlId='s.control_id', activationRevision='s.activation_revision' if name == 'detection_identity_source_control' else 'NULL', legacySource=q(name)),
                         created_at='NULL', updated_at='NULL')
name='detection_identity_command'
MAPPINGS[name]=workflow(RELATIONS[name][1],name,obj(actorUserId='s.actor_user_id',legacyCreatedAt=raw('created_at')),
                       result='CAST(s.result_json AS CHAR CHARACTER SET utf8mb4)')
name='detection_identity_mapping_batch'
MAPPINGS[name]=workflow(RELATIONS[name][1],name,obj(actorUserId='s.actor_user_id',actorName='s.actor_name',revisionBefore='s.revision_before',revisionAfter='s.revision_after',appliedCount='s.applied_count',legacyId=sid(),legacyCreatedAt=raw('created_at')),
                       result='CAST(s.result_json AS CHAR CHARACTER SET utf8mb4)',revision='s.revision_after')
name='detection_identity_mapping_item'
MAPPINGS[name]=workflow(RELATIONS[name][1],name,obj(batchId=sid('batch_id'),taskId='s.task_id',identityRole='s.identity_role',sourceName='s.source_name',sourceSnapshot='s.source_snapshot',previousUserId='s.previous_user_id',previousIdentityName='s.previous_identity_name',targetUserId='s.target_user_id',targetUsername='s.target_username',targetRole='s.target_role',targetRevision='s.target_revision',confirmationBasis='s.confirmation_basis',legacyId=sid()),
                       actor='(SELECT b.actor_user_id FROM '+ '`__SOURCE_SCHEMA__`.detection_identity_mapping_batch b WHERE b.id=s.batch_id)',created=None)
name='detection_identity_reconciliation_report'
MAPPINGS[name]=workflow(RELATIONS[name][1],name,obj(actorUserId='s.actor_user_id',actorName='s.actor_name',protocol='s.protocol',controlRevision='s.control_revision',identityMode='s.identity_mode',sourceMode='s.source_mode',startedAt=raw('started_at'),finishedAt=raw('finished_at'),taskCount='s.task_count',roleCount='s.role_count',issueCount='s.issue_count',datasetSha256='s.dataset_sha256',previousReportId='CASE WHEN s.previous_report_id IS NULL THEN NULL ELSE '+sid('previous_report_id')+' END',summaryJson='CAST(s.summary_json AS CHAR CHARACTER SET utf8mb4)',legacyId=sid()),created='started_at',revision='s.control_revision')
MAPPINGS[name].update(updated_at=utc('finished_at'),finished_at=utc('finished_at'))
name='detection_assignment_identity_event'
MAPPINGS[name]=audit(RELATIONS[name][1],name,obj(taskId='s.task_id',actorUserId='s.actor_user_id',actorName='s.actor_name',assigneeUserId='s.assignee_user_id',assigneeName='s.assignee_name',assigneeRevision='s.assignee_revision',requestId='s.request_id',legacyId=sid(),legacyCreatedAt=raw('created_at')),q('ASSIGNED'),owner='s.assignee_user_id',actor='s.actor_user_id')
MAPPINGS[name].update(revision='s.revision',run_id=identity_scope(role=q('assignment')),sequence_no='s.revision',request_id='s.request_id')
name='detection_identity_binding_event'
MAPPINGS[name]=audit(RELATIONS[name][1],name,obj(taskId='s.task_id',identityRole='s.identity_role',boundUserId='s.bound_user_id',boundIdentityName='s.bound_identity_name',targetRevision='s.target_revision',actorUserId='s.actor_user_id',actorName='s.actor_name',sourceKind='s.source_kind',requestId='s.request_id',sourceBatchId='CASE WHEN s.source_batch_id IS NULL THEN NULL ELSE '+sid('source_batch_id')+' END',legacyId=sid(),legacyCreatedAt=raw('created_at')),'s.source_kind',owner='s.bound_user_id',actor='s.actor_user_id')
MAPPINGS[name].update(revision='s.revision',run_id=identity_scope(),sequence_no='s.revision',request_scope=identity_scope(),request_id='s.request_id',previous_sha256='s.previous_sha256',event_sha256='s.event_sha256')
name='detection_identity_reconciliation_item'
report_actor='(SELECT r.actor_user_id FROM `__SOURCE_SCHEMA__`.detection_identity_reconciliation_report r WHERE r.id=s.report_id)'
MAPPINGS[name]=audit(RELATIONS[name][1],name,obj(reportId=sid('report_id'),taskId='s.task_id',identityRole='s.identity_role',existingName='s.existing_name',existingUserId='s.existing_user_id',identityName='s.identity_name',currentUsername='s.current_username',currentRole='s.current_role',currentRevision='s.current_revision',sourceKind='s.source_kind',sourceRequestId='s.source_request_id',sourceSha256='s.source_sha256',reasonCodes='CAST(s.reason_codes AS CHAR CHARACTER SET utf8mb4)',itemSha256='s.item_sha256',legacyId=sid()),q('OBSERVED'),owner=report_actor,actor=report_actor,created=None)
MAPPINGS[name].update(request_scope="CONCAT('IDREPORT:',s.report_id)",request_id=identity_scope())
name='detection_identity_missing_name_evidence'
batch_actor='(SELECT b.actor_user_id FROM `__SOURCE_SCHEMA__`.detection_identity_mapping_batch b WHERE b.id=s.batch_id)'
MAPPINGS[name]=audit(RELATIONS[name][1],name,obj(batchId=sid('batch_id'),taskId='s.task_id',identityRole='s.identity_role',originalName='s.original_name',sourceSnapshot='s.source_snapshot',targetUserId='s.target_user_id',evidenceReference='s.evidence_reference',legacyCreatedAt=raw('created_at')),q('CONFIRMED'),owner=batch_actor,actor=batch_actor)
MAPPINGS[name].update(request_scope="CONCAT('IDMAP:',s.batch_id)",request_id=identity_scope())
name='detection_identity_binding'
MAPPINGS[name]=dict(namespace=q(RELATIONS[name][1]),owner_id='0',scope_key=identity_scope(),revision='s.revision',
                    current_ref="SHA2(CONCAT('DETECTION_IDENTITY_BINDING_EVENT:',CAST(s.event_id AS CHAR)),256)",payload_version='1',
                    payload_json=obj(taskId='s.task_id',identityRole='s.identity_role',eventSha256='s.event_sha256',legacyId=sid(),legacyEventId=sid('event_id'),legacySource=q(name)),created_at='NULL',updated_at='NULL')

sql=[]
emit=sql.append


def guard(condition):
    emit('INSERT INTO compact_identity_guard SELECT IF(COALESCE(('+condition+'),FALSE),1,0);')


emit('''-- Eleven original identity sources; AUTHORED_NOT_EXECUTED. No source DML or compatibility views.
-- Freeze both schemas in the reviewed migration window; flags assert external evidence, not a write freeze.
-- Strict original column/key/collation/clock/HWM and full-row hash checks. Never --force.
SET NAMES utf8mb4;
SET @compact_identity_previous_concat=@@SESSION.group_concat_max_len;
SET SESSION group_concat_max_len=3200000;
CREATE TEMPORARY TABLE compact_identity_guard(valid INT NOT NULL CHECK(valid=1)) ENGINE=InnoDB;''')
guard("DATABASE() IS NOT NULL AND BINARY DATABASE()<>BINARY '__SOURCE_SCHEMA__' AND @@FOREIGN_KEY_CHECKS=1 AND @compact_identity_source_frozen=1 AND @compact_identity_target_frozen=1 AND @@SESSION.sql_mode REGEXP '(^|,)(STRICT_TRANS_TABLES|STRICT_ALL_TABLES)(,|$)' AND '__SOURCE_IDENTITY_OFFSET__' REGEXP '^[+-][0-9]{2}:[0-9]{2}$' AND CONVERT_TZ('2026-01-01','__SOURCE_IDENTITY_OFFSET__','+00:00') IS NOT NULL")
guard("(SELECT COUNT(DISTINCT privilege_type) FROM information_schema.schema_privileges WHERE table_schema='__SOURCE_SCHEMA__' AND privilege_type IN ('SELECT','TRIGGER') AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1))))=2")
names='('+','.join(q(name) for name in sources)+')'
columns=[];keys=[];metadata=[];collations={}
for name,table in sources.items():
    explicit=re.search(r'COLLATE\s*=\s*([a-z0-9_]+)',table['options'],re.I)
    collations[name]=explicit.group(1) if explicit else '__SOURCE_IDENTITY_COLLATION_'+name+'__'
    for ordinal,(column,c) in enumerate(table['columns'].items(),1):
        declaration=c['declaration'];kind=c['type'].lower()
        if kind in ('boolean','bool'):kind='tinyint(1)'
        nullable='NO' if column in table['primaryKey'] or 'NOT NULL' in declaration.upper() else 'YES'
        co=re.search(r'\bCOLLATE\s+([a-z0-9_]+)',declaration,re.I)
        co=(co.group(1) if co else collations[name]) if kind.startswith(('varchar','char','text','mediumtext','longtext')) else None
        match=re.search(r"\bDEFAULT\s+(CURRENT_TIMESTAMP(?:\(\d+\))?|'[^']*'|FALSE|TRUE|NULL|\d+)",declaration,re.I)
        default=match.group(1).strip("'") if match else None
        if default is not None:default={'FALSE':'0','TRUE':'1','NULL':None,'CURRENT_TIMESTAMP(6)':'current_timestamp(6)','CURRENT_TIMESTAMP':'current_timestamp()'}.get(default.upper(),default)
        extra='auto_increment' if 'AUTO_INCREMENT' in declaration.upper() else 'default_generated' if default and default.startswith('current_timestamp') else ''
        columns.append((name,column,ordinal,kind,nullable,co,default,extra))
    keys.append((name,0,1,','.join(table['primaryKey'])))
    keys.extend((name,0,0,','.join(key)) for key in table['uniqueKeys'])
    for declaration in table['constraints']:
        match=re.match(r'KEY\s+[^ (]+\s*\(([^)]+)\)',declaration,re.I)
        if match:keys.append((name,1,0,match.group(1).replace(' ','')))
emit('CREATE TEMPORARY TABLE compact_identity_columns(table_name VARCHAR(64),column_name VARCHAR(64),position_no INT,column_type VARCHAR(64),nullable VARCHAR(3),collation_name VARCHAR(64),default_value VARCHAR(64),extra VARCHAR(64),PRIMARY KEY(table_name,column_name)) ENGINE=InnoDB;')
emit('INSERT INTO compact_identity_columns VALUES '+','.join('('+','.join(q(value) for value in row)+')' for row in columns)+';')
emit('CREATE TEMPORARY TABLE compact_identity_keys(table_name VARCHAR(64),non_unique INT,is_primary INT,key_columns VARCHAR(1024)) ENGINE=InnoDB;')
emit('INSERT INTO compact_identity_keys VALUES '+','.join('('+','.join(q(value) for value in row)+')' for row in keys)+';')
metadata.append("(SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+" AND table_type='BASE TABLE' AND engine='InnoDB')=11")
metadata.append("(SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+")="+str(len(columns)))
metadata.append("NOT EXISTS(SELECT 1 FROM compact_identity_columns e LEFT JOIN information_schema.columns c ON c.table_schema='__SOURCE_SCHEMA__' AND c.table_name=e.table_name AND c.column_name=e.column_name WHERE c.column_name IS NULL OR c.ordinal_position<>e.position_no OR NOT(BINARY LOWER(c.column_type)<=>BINARY e.column_type) OR NOT(c.is_nullable<=>e.nullable) OR (NOT(c.collation_name<=>e.collation_name) AND NOT(e.column_type='json' AND (c.collation_name IS NULL OR c.collation_name='utf8mb4_bin'))) OR NOT(BINARY (CASE WHEN e.extra='default_generated' THEN LOWER(c.column_default) ELSE c.column_default END)<=>BINARY e.default_value) OR NOT(LOWER(c.extra)<=>e.extra) OR c.generation_expression<>'')")
metadata.append("NOT EXISTS(SELECT 1 FROM information_schema.triggers WHERE event_object_schema='__SOURCE_SCHEMA__' AND event_object_table IN "+names+')')
metadata.append("NOT EXISTS(SELECT 1 FROM information_schema.table_constraints WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+" AND constraint_type IN ('FOREIGN KEY','CHECK'))")
actual="(SELECT table_name,non_unique,(index_name='PRIMARY') is_primary,GROUP_CONCAT(column_name ORDER BY seq_in_index) key_columns,SUM(sub_part IS NOT NULL OR collation<>'A') unsupported FROM information_schema.statistics WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+' GROUP BY table_name,index_name,non_unique)'
metadata += ['(SELECT COUNT(*) FROM '+actual+' a)='+str(len(keys)), 'NOT EXISTS(SELECT 1 FROM '+actual+' a LEFT JOIN compact_identity_keys e ON e.table_name=a.table_name AND e.non_unique=a.non_unique AND e.is_primary=a.is_primary AND e.key_columns=a.key_columns WHERE e.table_name IS NULL OR a.unsupported<>0)']
metadata += ["(SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name="+q(name)+' AND table_collation='+q(collation)+')=1' for name,collation in collations.items()]
for condition in metadata:guard(condition)
emit("CREATE TEMPORARY TABLE compact_identity_sequences AS SELECT table_name,auto_increment FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN "+names+';')
for name,table in sources.items():
    guard('(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.'+name+')<=50000')
    if 'id' in table['columns']:guard('NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.'+name+' WHERE id<=0)')
    for column,c in table['columns'].items():
        if c['type'].lower().startswith('datetime'):
            offset="(IF(LEFT('__SOURCE_IDENTITY_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_IDENTITY_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_IDENTITY_OFFSET__',5,2) AS SIGNED)*60)*1000000)"
            guard('NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.'+name+' s WHERE s.'+column+' IS NOT NULL AND ('+utc(column)+" IS NULL OR TIMESTAMPDIFF(MICROSECOND,"+utc(column)+',s.'+column+')<>'+offset+" OR NOT(CONVERT_TZ("+utc(column)+",'+00:00','__SOURCE_IDENTITY_OFFSET__')<=>s."+column+')))')
for target,kind,_ in RELATIONS.values():
    discriminator='namespace' if target=='runtime_state' else 'kind'
    guard('NOT EXISTS(SELECT 1 FROM '+target+' WHERE '+discriminator+'='+q(kind)+')')
guard("NOT EXISTS(SELECT 1 FROM audit_event WHERE kind='IDENTITY_MIGRATION_CLOCK')")
# Shared cursor allocation must never collide with preserved historical public cursors.
guard('(SELECT COALESCE(MAX(auto_increment),1) FROM compact_identity_sequences) BETWEEN 1 AND 9223372036854775807')
for target in ('workflow_instance','audit_event'):
    emit("SET @compact_identity_next=GREATEST((SELECT COALESCE(MAX(auto_increment),1) FROM compact_identity_sequences),(SELECT auto_increment FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name="+q(target)+'));')
    emit("SET @compact_identity_ddl=CONCAT('ALTER TABLE "+target+" AUTO_INCREMENT=',@compact_identity_next);")
    emit('PREPARE compact_identity_statement FROM @compact_identity_ddl;')
    emit('EXECUTE compact_identity_statement;')
    emit('DEALLOCATE PREPARE compact_identity_statement;')
emit('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;')
emit('START TRANSACTION;')
emit('SET @compact_identity_imported_at=UTC_TIMESTAMP(6);')
emit('CREATE TEMPORARY TABLE compact_identity_snapshots(source_table VARCHAR(64) PRIMARY KEY,row_count BIGINT NOT NULL,snapshot_sha256 CHAR(64) NOT NULL,hash_bytes BIGINT NOT NULL) ENGINE=InnoDB;')
snapshots={}
for name,table in sources.items():
    order=','.join('s.`'+key+'`' for key in table['primaryKey'])
    emit('SELECT '+order+' FROM `__SOURCE_SCHEMA__`.'+name+' s FORCE INDEX(PRIMARY) ORDER BY '+order+' FOR SHARE;')
    chain='GROUP_CONCAT(SHA2('+original_row(name)+',256) ORDER BY '+order+" SEPARATOR '')"
    expression='SELECT COUNT(*) AS n,SHA2(COALESCE('+chain+",''),256) AS h,COALESCE(OCTET_LENGTH("+chain+'),0) AS b FROM `__SOURCE_SCHEMA__`.'+name+' s'
    snapshots[name]=expression
    emit('INSERT INTO compact_identity_snapshots SELECT '+q(name)+',v.n,v.h,v.b FROM ('+expression+') v;')
    guard('(SELECT hash_bytes=row_count*64 FROM compact_identity_snapshots WHERE source_table='+q(name)+')')
for name,(target,kind,projection) in RELATIONS.items():
    values=MAPPINGS[name]
    emit('INSERT INTO '+target+'('+','.join(values)+') SELECT '+','.join(values.values())+' FROM `__SOURCE_SCHEMA__`.'+name+' s;')
    reverse=PROJECTIONS[projection]
    if projection=='HEADS':
        reverse=reverse.replace('COALESCE(a.identity_source_id,a.id) AS event_id',"CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.legacyEventId')) AS UNSIGNED) AS event_id")
    fields=[]
    for column,c in sources[name]['columns'].items():
        expression='t.`'+column+'`'
        if c['type'].upper()=='JSON':expression='CAST('+expression+' AS JSON)'
        fields.append(expression)
    order=','.join('t.`'+key+'`' for key in sources[name]['primaryKey'])
    row='JSON_ARRAY('+','.join(fields)+')'
    chain='GROUP_CONCAT(SHA2('+row+',256) ORDER BY '+order+" SEPARATOR '')"
    check='SELECT COUNT(*) AS n,SHA2(COALESCE('+chain+",''),256) AS h,COALESCE(OCTET_LENGTH("+chain+'),0) AS b FROM ('+reverse+') t'
    guard('EXISTS(SELECT 1 FROM compact_identity_snapshots s JOIN ('+check+') t ON s.row_count=t.n AND s.snapshot_sha256=t.h AND s.hash_bytes=t.b AND t.b=t.n*64 WHERE s.source_table='+q(name)+')')
    # The payload is not an arbitrary document: every V1 key and every ordinary column is checked by baseline constraints.
    predicate=('namespace' if target=='runtime_state' else 'kind')+'='+q(kind)
    guard('(SELECT COUNT(*) FROM '+target+' WHERE '+predicate+')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.'+name+')')
emit("INSERT INTO audit_event(event_id,kind,resource_type,resource_id,action,payload_version,payload_json,occurred_at) SELECT SHA2(CONCAT('identity-migration-clock:',source_table),256),'IDENTITY_MIGRATION_CLOCK','IDENTITY_MIGRATION',source_table,'IMPORTED',1,JSON_OBJECT('sourceTable',source_table,'sourceUtcOffset','__SOURCE_IDENTITY_OFFSET__','sourceSnapshotSha256',snapshot_sha256,'rowCount',row_count,'sourceAutoIncrement',(SELECT CAST(q.auto_increment AS CHAR) FROM compact_identity_sequences q WHERE q.table_name=source_table)),@compact_identity_imported_at FROM compact_identity_snapshots;")
guard("(SELECT COUNT(*) FROM audit_event WHERE kind='IDENTITY_MIGRATION_CLOCK')=11")
for name,expression in snapshots.items():
    guard('EXISTS(SELECT 1 FROM compact_identity_snapshots s JOIN ('+expression+') t ON s.row_count=t.n AND s.snapshot_sha256=t.h AND s.hash_bytes=t.b AND t.b=t.n*64 WHERE s.source_table='+q(name)+')')
for condition in metadata:guard(condition)
guard("NOT EXISTS(SELECT 1 FROM compact_identity_sequences e LEFT JOIN information_schema.tables t ON t.table_schema='__SOURCE_SCHEMA__' AND t.table_name=e.table_name WHERE t.table_name IS NULL OR NOT(t.auto_increment<=>e.auto_increment))")
emit('COMMIT;')
emit('SET SESSION group_concat_max_len=@compact_identity_previous_concat;')
out=ROOT/'sql/mysql/compact/copy/46-detection-identity.sql'
out.write_text('\n'.join(line.rstrip() for part in sql for line in part.splitlines())+'\n',encoding='utf8')
resource=ROOT/'doorhandle-module-detection/src/test/resources/compact/identity-source-evidence.sql'
resource.parent.mkdir(parents=True,exist_ok=True)
resource.write_text('-- Exact original identity CREATE TABLE declarations; no target-derived synthetic source.\n'+'\n'.join(fixture)+'\n',encoding='utf8')
print(json.dumps({'status':'AUTHORED_NOT_EXECUTED','sourceTables':len(sources),'sourceColumns':len(columns),'copy':str(out.relative_to(ROOT))}))
