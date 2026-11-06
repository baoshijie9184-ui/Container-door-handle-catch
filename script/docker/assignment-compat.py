#!/usr/bin/env python3
"""Guard assignment readers/writers using immutable images, persisted floors and metadata-only SQL.

Never prints Compose configuration, account names, command bodies or credentials. The guard
does not stop containers, run migrations, pull images, or replay a business command.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid
from urllib.parse import urlsplit

PROJECT = 'doorhandlecatch-monolith'
JSON_LABEL = 'io.doorhandle.assignment-json'
IDENTITY_LABEL = 'io.doorhandle.assignment-identity'
REVIEW_LABEL = 'io.doorhandle.identity-review'
EVIDENCE_LABEL = 'io.doorhandle.identity-evidence'
CONTEXT_LABEL = 'io.doorhandle.context-provenance'
GATE = 'DETECTION_ASSIGNMENT_WRITES_ENABLED'
DIGEST = re.compile(r'sha256:[a-f0-9]{64}')
CID = re.compile(r'[a-f0-9]{64}')
ZONE = dt.timezone(dt.timedelta(hours=8))
KEYS = ('json', 'identity', 'scope', 'review', 'evidence', 'context')
CONTEXT_TABLES = ('runtime_state','content_asset','content_revision','content_link','audit_event')


class GuardError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise GuardError(message)


def docker(*args, data=None, timeout=40):
    try:
        result = subprocess.run(['docker', *args], input=data, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True, timeout=timeout)
        require(len(result.stdout) <= 2 * 1024 * 1024, 'Docker metadata exceeded its bound')
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        raise GuardError('Docker metadata is unavailable; application activation was not approved') from None


def boolean(environment, name, default=False):
    value = environment.get(name, default)
    require(isinstance(value, (str, bool)), 'Application flag has an invalid type')
    if isinstance(value, bool):
        return value
    require(value.lower() in ('true', 'false'), 'Application flag is not a strict boolean')
    return value.lower() == 'true'


def environment(row):
    result = {}
    for item in row.get('Config', {}).get('Env', []):
        require(isinstance(item, str) and '=' in item, 'Container environment cannot be interpreted')
        name, value = item.split('=', 1)
        require(name not in result, 'Container has duplicate environment keys')
        result[name] = value
    return result


def image(reference):
    require(isinstance(reference, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/@-]{0,500}', reference),
            'Application image reference is invalid')
    rows = json.loads(docker('image', 'inspect', reference))
    require(len(rows) == 1 and DIGEST.fullmatch(rows[0].get('Id', '')), 'Image identity unavailable')
    labels = rows[0].get('Config', {}).get('Labels') or {}
    raw_json, raw_identity = labels.get(JSON_LABEL, '0'), labels.get(IDENTITY_LABEL, '0')
    raw_review = labels.get(REVIEW_LABEL, '0')
    raw_evidence = labels.get(EVIDENCE_LABEL, '0')
    raw_context = labels.get(CONTEXT_LABEL, '0')
    require(raw_json in ('0', '2') and raw_identity in ('0', '1') and raw_review in ('0', '1') and raw_evidence in ('0', '1', '2') and raw_context in ('0','2'), 'Unsupported assignment or context image format declaration')
    return rows[0]['Id'], {'json': int(raw_json), 'identity': int(raw_identity), 'scope': int(raw_identity), 'review': int(raw_review), 'evidence': int(raw_evidence), 'context': int(raw_context)}


def container(project, service, optional=False):
    require(project == PROJECT or re.fullmatch(r'doorhandle-rehearsal-[a-f0-9]{12}', project),
            'Unexpected Compose project')
    ids = docker('ps', '-aq', '--no-trunc', '--filter', 'label=com.docker.compose.project=' + project,
                 '--filter', 'label=com.docker.compose.service=' + service).decode().split()
    if optional and not ids:
        return None
    require(len(ids) == 1 and CID.fullmatch(ids[0]), 'Expected one existing application container')
    rows = json.loads(docker('inspect', ids[0]))
    require(len(rows) == 1, 'Container metadata changed')
    row = rows[0]
    labels = row.get('Config', {}).get('Labels') or {}
    require(row.get('Id') == ids[0] and labels.get('com.docker.compose.project') == project
            and labels.get('com.docker.compose.service') == service and DIGEST.fullmatch(row.get('Image', '')),
            'Container does not belong to the selected application')
    return row


def schema(mysql, table):
    # All table identifiers come from literals below, never from HTTP or model text.
    require(table in ('workflow_instance','runtime_state','audit_event','detection_task',
                      'content_asset','content_revision','content_link'), 'Unexpected compact metadata table')
    sql = "SELECT COLUMN_NAME FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='" + table + "';"
    return set(db(mysql, sql).split())


def db(mysql, sql):
    require(mysql.get('State', {}).get('Running'), 'Existing MySQL must be running for metadata inspection')
    database=mysql.get('_doorhandle_database') or environment(mysql).get('MYSQL_DATABASE')
    require(re.fullmatch(r'[A-Za-z0-9_]{1,64}',database or ''),'Explicit database identity required')
    command = ('MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --default-character-set=utf8mb4 '
               '--batch --raw --skip-column-names "$1"')
    return docker('exec', '-i', mysql['Id'], 'sh', '-ec', command, '--', database, data=sql.encode(), timeout=90).decode().strip()


def database_name(environment_value):
    raw=environment_value.get('DB_URL','')
    require(isinstance(raw,str) and raw.startswith('jdbc:mysql://'),'Explicit local MySQL JDBC target required')
    try:
        value=urlsplit(raw[5:]);database=value.path[1:]
        valid=(value.hostname=='mysql' and (value.port or 3306)==3306 and not value.username
               and not value.password and re.fullmatch(r'[A-Za-z0-9_]{1,64}',database))
    except ValueError:
        valid=False
    require(valid,'Application JDBC target must select an explicit schema on the inspected MySQL service')
    return database


def selected_mysql(mysql, environment_value):
    selected=dict(mysql);selected['_doorhandle_database']=database_name(environment_value)
    return selected


def check_current_database(current, database):
    existing=database_name(environment(current))
    require(existing==database or current.get('State',{}).get('Running') is False,
            'Stop the old-schema application writer before a separately verified cross-schema cutover')


def exists(mysql, sql):
    value = db(mysql, sql)
    require(value in ('0', '1'), 'Assignment metadata result cannot be interpreted')
    return value == '1'


def data_floor(mysql):
    floor = {key: 0 for key in KEYS}
    workflow = schema(mysql, 'workflow_instance')
    state = schema(mysql, 'runtime_state')
    audit = schema(mysql, 'audit_event')
    require({'kind','payload_json','payload_version','result_json','result_version','agent_action_operation'}<=workflow
            and {'namespace','owner_id','scope_key','state_code','payload_json'}<=state
            and {'kind','action','payload_json','payload_version','resource_id'}<=audit,
            'The complete compact assignment schema must be migrated before candidate activation')
    selector="kind='AGENT_ACTION' AND agent_action_operation='ASSIGN_QUALITY_TASK'"
    policy="JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.policyVersion'))"
    require(not exists(mysql,"SELECT EXISTS(SELECT 1 FROM workflow_instance WHERE "+selector+" AND ("+policy+" IS NULL OR "+policy+" NOT IN ('quality-assignment-confirmation-v1','quality-assignment-confirmation-v2')) LIMIT 1);"),'An unknown assignment confirmation policy exists')
    bodies={name:"JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$."+name+"'))" for name in ('commandJson','beforeJson')}
    bodies['resultJson']="JSON_UNQUOTE(JSON_EXTRACT(result_json,'$.resultJson'))"
    for name, body in bodies.items():
        condition="("+body+" IS NULL OR NOT JSON_VALID("+body+") OR CASE WHEN JSON_VALID("+body+") THEN JSON_TYPE(CAST("+body+" AS JSON))<>'OBJECT' ELSE 0 END)"
        if name=='resultJson':condition="result_json IS NOT NULL AND "+condition
        require(not exists(mysql,"SELECT EXISTS(SELECT 1 FROM workflow_instance WHERE "+selector+" AND "+condition+" LIMIT 1);"),'Stored compact assignment JSON is invalid; retain the current reader')
    checks=[policy+"='quality-assignment-confirmation-v2'",
            "JSON_CONTAINS_PATH(CAST("+bodies['commandJson']+" AS JSON),'one','$.assigneeUserId','$.assigneeRevision')=1",
            "JSON_CONTAINS_PATH(CAST("+bodies['beforeJson']+" AS JSON),'one','$.assigneeUserId','$.assignedByUserId','$.assignedByName','$.assignmentRevision')=1",
            "CASE WHEN result_json IS NOT NULL THEN JSON_CONTAINS_PATH(CAST("+bodies['resultJson']+" AS JSON),'one','$.after.assigneeUserId','$.after.assignedByUserId','$.after.assignedByName','$.after.assignmentRevision') ELSE 0 END=1"]
    if exists(mysql,"SELECT EXISTS(SELECT 1 FROM workflow_instance WHERE "+selector+" AND ("+' OR '.join(checks)+") LIMIT 1);"):floor['json']=2
    task = schema(mysql,'detection_task')
    require({'assigned_by_user_id','assigned_by_identity_name','assigned_to_revision','assignment_identity_revision'}<=task,
            'Compact assignment identity projection is incomplete')
    require(not exists(mysql,'SELECT EXISTS(SELECT 1 FROM detection_task WHERE assignment_identity_revision<0 LIMIT 1);'),'Assignment identity revision is invalid')
    if exists(mysql,"SELECT EXISTS(SELECT 1 FROM detection_task WHERE assignment_identity_revision>0 OR assigned_by_user_id IS NOT NULL OR assigned_by_identity_name IS NOT NULL OR assigned_to_revision IS NOT NULL LIMIT 1);") or exists(mysql,"SELECT EXISTS(SELECT 1 FROM audit_event WHERE kind='DETECTION_ASSIGNMENT_IDENTITY' LIMIT 1);"):floor['identity']=1
    control="namespace='DETECTION_IDENTITY_CONTROL' AND owner_id=0 AND scope_key='1'"
    source="namespace='DETECTION_IDENTITY_SOURCE_CONTROL' AND owner_id=0 AND scope_key='1'"
    mode=db(mysql,"SELECT state_code FROM runtime_state WHERE "+control+";")
    require(mode in ('','ACTIVE','PREVIEW'),'Stable identity mode is unknown')
    if mode=='ACTIVE':floor['scope']=1
    if exists(mysql,"SELECT EXISTS(SELECT 1 FROM workflow_instance WHERE kind IN ('DETECTION_IDENTITY_MAP_BATCH','DETECTION_IDENTITY_MAP_ITEM','DETECTION_IDENTITY_REPORT') LIMIT 1);"):floor['review']=1
    if exists(mysql,"SELECT EXISTS(SELECT 1 FROM runtime_state WHERE namespace='DETECTION_IDENTITY_BINDING' LIMIT 1);") or exists(mysql,"SELECT EXISTS(SELECT 1 FROM audit_event WHERE kind='DETECTION_IDENTITY_BINDING_EVENT' LIMIT 1);"):floor['evidence']=1
    evidence_mode=db(mysql,"SELECT state_code FROM runtime_state WHERE "+source+";")
    require(evidence_mode in ('','COLLECTING','ACTIVE'),'Identity evidence mode is unknown')
    if evidence_mode=='ACTIVE':
        require(mode=='ACTIVE','Active identity evidence cannot fall back to name authorization')
        floor['evidence']=1
    if exists(mysql,"SELECT EXISTS(SELECT 1 FROM audit_event WHERE kind='DETECTION_IDENTITY_MISSING_NAME' OR (kind='DETECTION_IDENTITY_BINDING_EVENT' AND action='SUPERVISOR_MISSING_NAME') LIMIT 1);"):floor['evidence']=2
    if floor['evidence']:floor['review']=1
    if floor['identity'] or floor['review']:floor['scope']=1
    context_queries=("SELECT EXISTS(SELECT 1 FROM runtime_state WHERE namespace IN ('CONTEXT_HEAD','CONTEXT_BOOTSTRAP') LIMIT 1);",
                     "SELECT EXISTS(SELECT 1 FROM content_asset WHERE asset_kind='CONTEXT_SUMMARY' LIMIT 1);",
                     "SELECT EXISTS(SELECT 1 FROM content_link WHERE link_kind IN ('CONTEXT_SOURCE','TOOL_SOURCE') LIMIT 1);",
                     "SELECT EXISTS(SELECT 1 FROM audit_event WHERE kind IN ('CONTEXT','CONTEXT_TURN') LIMIT 1);")
    if any(exists(mysql,sql) for sql in context_queries):floor['context']=2
    return floor


def database_binding(mysql, project):
    matches = [mount for mount in mysql.get('Mounts', []) if mount.get('Destination') == '/var/lib/mysql']
    require(len(matches) == 1 and matches[0].get('Type') == 'volume', 'Persistent named MySQL volume required')
    name = matches[0].get('Name', '')
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', name), 'MySQL volume identity invalid')
    rows = json.loads(docker('volume', 'inspect', name))
    require(len(rows) == 1 and rows[0].get('Name') == name and rows[0].get('CreatedAt'), 'MySQL volume metadata unavailable')
    labels = rows[0].get('Labels') or {}
    require(labels.get('com.docker.compose.project') == project or labels.get('io.doorhandle.rehearsal') == project,
            'MySQL volume is outside the selected application')
    source = [project, name, rows[0]['CreatedAt'], rows[0].get('Driver')]
    return hashlib.sha256(json.dumps(source, separators=(',', ':')).encode()).hexdigest()


def check_database(environment_value, database):
    require(re.fullmatch(r'[A-Za-z0-9_]{1,64}', database or ''), 'Database identity invalid')
    raw = environment_value.get('DB_URL', '')
    require(isinstance(raw, str) and raw.startswith('jdbc:mysql://'), 'Explicit local MySQL JDBC target required')
    try:
        value = urlsplit(raw[5:])
        valid = value.hostname == 'mysql' and (value.port or 3306) == 3306 and value.path == '/' + database and not value.username and not value.password
    except ValueError:
        valid = False
    require(valid, 'Application JDBC target differs from inspected MySQL; no activation approved')


def maximum(*values):
    return {key: max(value[key] for value in values) for key in KEYS}


def potential(environment_value, capabilities):
    writes = boolean(environment_value, GATE, True)
    return {'json': 2 if writes and capabilities['json'] == 2 and boolean(environment_value, 'AGENT_ACTION_CONFIRMATION_ENABLED') else 0,
            'identity': 1 if writes and capabilities['identity'] == 1 and boolean(environment_value, 'DETECTION_ASSIGNMENT_BINDING_ENABLED') else 0,
            'scope': 1 if capabilities['scope'] == 1 and boolean(environment_value, 'DETECTION_STABLE_IDENTITY_ENABLED') else 0,
            'review': 1 if capabilities['review'] == 1 and boolean(environment_value, 'DETECTION_IDENTITY_REVIEW_ENABLED') else 0,
            'evidence': 2 if capabilities['evidence'] >= 2 and boolean(environment_value,'DETECTION_IDENTITY_MISSING_NAME_REVIEW_ENABLED') else 1 if capabilities['evidence'] >= 1 and boolean(environment_value, 'DETECTION_IDENTITY_EVIDENCE_ENABLED') else 0,
            'context': 2 if capabilities['context']>=2 and boolean(environment_value,'AGENT_DURABLE_CONTEXT_ENABLED') else 0}


def private_state(state):
    state = Path(state)
    require(state.is_dir() and state != Path(state.anchor), 'Expected an existing private deployment state directory')
    for path in (state, *state.parents):
        require(not path.is_symlink(), 'Deployment state path cannot contain links')
        metadata = path.stat()
        require(not metadata.st_mode & 0o022 and metadata.st_uid in (0, os.geteuid()), 'Deployment state ancestor is writable by another account')
    row = state.stat()
    require(not row.st_mode & 0o022 and row.st_uid in (0, os.geteuid()), 'Deployment state is writable by another account')
    return state.resolve()


def read_pin(state, project, binding):
    path = state / 'assignment-protocol-pin.json'
    if not path.exists():
        require(not path.is_symlink(), 'Protocol pin cannot be a broken link')
        return {key: 0 for key in KEYS}
    require(not path.is_symlink(), 'Protocol pin cannot be a link')
    row = path.stat()
    require(stat.S_ISREG(row.st_mode) and row.st_nlink == 1 and row.st_size < 8192 and not row.st_mode & 0o077,
            'Protocol pin is not a private regular file')
    value = json.loads(path.read_text(encoding='utf-8'))
    require(value.get('schema') == 1 and value.get('project') == project and value.get('databaseBinding') == binding,
            'Protocol pin belongs to another deployment or database volume')
    floor = value.get('required', {})
    require({'json', 'identity', 'scope'} <= set(floor) <= set(KEYS)
            and all(type(item) is int and item >= 0 for item in floor.values()), 'Protocol floor is invalid')
    return {key: floor.get(key, 0) for key in KEYS}


def write_json(path, value):
    require(not path.is_symlink(), 'Protocol receipt cannot be a link')
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def guard(state, config, *, project=PROJECT, pin=False, allow_initial=False):
    state = private_state(state)
    services = config.get('services', {})
    backend = services.get('backend', {})
    desired_environment = backend.get('environment', {})
    require(isinstance(desired_environment, dict), 'Resolved Compose environment required')
    target_id, target_capabilities = image(backend.get('image'))
    if boolean(desired_environment, 'DETECTION_IDENTITY_EVIDENCE_ENABLED'):
        require(target_capabilities['evidence'] >= 1 and boolean(desired_environment, 'DETECTION_IDENTITY_REVIEW_ENABLED'), 'Identity evidence requires compatible readers and identity review')
    if boolean(desired_environment,'DETECTION_IDENTITY_MISSING_NAME_REVIEW_ENABLED'):
        require(target_capabilities['evidence']>=2 and boolean(desired_environment,'DETECTION_IDENTITY_EVIDENCE_ENABLED'),'Missing-name confirmation requires its compatible evidence reader')
    if boolean(desired_environment, 'DETECTION_IDENTITY_REVIEW_ENABLED'):
        require(target_capabilities['review'] == 1 and boolean(desired_environment, 'DETECTION_STABLE_IDENTITY_ENABLED')
                and boolean(desired_environment, 'OPERATIONS_AUDIT_ENABLED'), 'Identity review requires compatible readers, stable identity and audit')
    if boolean(desired_environment, 'DETECTION_STABLE_IDENTITY_ENABLED') or boolean(desired_environment, 'DETECTION_ASSIGNMENT_BINDING_ENABLED'):
        require(target_capabilities['identity'] == 1, 'Selected image does not declare the requested identity feature')
    if not boolean(desired_environment, GATE, True):
        require(target_capabilities['json'] == 2, 'Selected legacy image does not implement the assignment write gate')
    mysql = selected_mysql(container(project, 'mysql'), desired_environment)
    current = container(project, 'backend', optional=allow_initial)
    database = mysql['_doorhandle_database']
    check_database(desired_environment, database)
    binding = database_binding(mysql, project)
    observed = data_floor(mysql)
    if boolean(desired_environment,'AGENT_DURABLE_CONTEXT_ENABLED'):
        require(target_capabilities['context']>=2 and boolean(desired_environment,'AGENT_WORKBENCH_ENABLED') and boolean(desired_environment,'AGENT_WORKBENCH_RECOVERY',True) and boolean(desired_environment,'AGENT_WORKBENCH_CHILDREN',True) and boolean(desired_environment,'AGENT_CONTEXT_COMPACTION_ENABLED'),'Persistent context requires compatible origins, durable children, recovery and compaction')
        expected_context={
            'runtime_state':{'namespace','owner_id','scope_key','session_id','state_key','current_ref','payload_version','payload_json'},
            'content_asset':{'asset_kind','identity_key','lifecycle','current_version'},
            'content_revision':{'asset_kind','context_session_id','context_agent_scope','context_revision','context_covered_through'},
            'content_link':{'link_kind','agent_scope','call_id','evidence_version','evidence_json'},
            'audit_event':{'kind','owner_user_id','session_id','payload_version','payload_json'}}
        require(all(fields<=schema(mysql,table) for table,fields in expected_context.items()),'Compact persistent context migration is incomplete')
    if boolean(desired_environment,'AGENT_CONTEXT_OFFLOAD_ENABLED'):
        require(boolean(desired_environment,'AGENT_DURABLE_CONTEXT_ENABLED') and boolean(desired_environment,'AGENT_WORKBENCH_FILES',True),'Context offloading requires persistent context and private files')
    if boolean(desired_environment,'DETECTION_IDENTITY_MISSING_NAME_REVIEW_ENABLED') or observed['evidence']>=2:
        require({'kind','identity_task_id','identity_role','identity_parent_id','payload_json'}<=schema(mysql,'audit_event'),'Compact missing-name identity proof storage is required')
    if boolean(desired_environment, 'DETECTION_IDENTITY_EVIDENCE_ENABLED'):
        require({'namespace','current_ref','revision','payload_json'}<=schema(mysql,'runtime_state')
                and {'kind','revision','previous_sha256','event_sha256','identity_task_id','identity_role'}<=schema(mysql,'audit_event'),
                'Compact identity evidence migration columns are missing')
    if boolean(desired_environment, 'DETECTION_IDENTITY_REVIEW_ENABLED'):
        require({'kind','identity_protocol','payload_json','result_json'}<=schema(mysql,'workflow_instance'),'Compact historical identity review storage is missing')
    if boolean(desired_environment, 'DETECTION_STABLE_IDENTITY_ENABLED'):
        require({'namespace','state_code','revision'}<=schema(mysql,'runtime_state')
                and {'created_user_id','created_identity_name','assignee_user_id','assignee_identity_name',
                     'reviewer_user_id','reviewer_identity_name','disposition_user_id','disposition_identity_name',
                     'rework_user_id','rework_identity_name'}<=schema(mysql,'detection_task'), 'Compact stable identity columns are missing')
    if boolean(desired_environment, 'OPERATIONS_AUDIT_ENABLED'):
        require({'actor_user_id','operation_scope','operation_domain','operation_result','resource_id','request_id','revision','occurred_at'}<=schema(mysql,'audit_event'),'Compact operations audit columns are missing')
    if boolean(desired_environment, 'DETECTION_ASSIGNMENT_BINDING_ENABLED'):
        require({'assigned_by_user_id','assigned_by_identity_name','assigned_to_revision','assignment_identity_revision'}<=schema(mysql,'detection_task')
                and {'kind','identity_task_id','revision','actor_user_id','payload_json'}<=schema(mysql,'audit_event'),'Compact assignment identity storage is missing')
    pinned = read_pin(state, project, binding)
    current_id, current_capabilities, current_potential = None, {key: 0 for key in KEYS}, {key: 0 for key in KEYS}
    if current:
        check_current_database(current, database)
        current_id, current_capabilities = image(current['Image'])
        current_potential = potential(environment(current), current_capabilities)
    required = maximum(observed, pinned, current_potential, potential(desired_environment, target_capabilities))
    require(all(target_capabilities[key] >= required[key] for key in KEYS), 'Selected image cannot read the persisted assignment format; use a compatible rollback image')
    if required['scope']:
        require(boolean(desired_environment, 'DETECTION_STABLE_IDENTITY_ENABLED') and boolean(desired_environment, 'OPERATIONS_AUDIT_ENABLED'),
                'Stable identity data cannot fall back to username authorization')
    if required['identity']:
        require(boolean(desired_environment, 'DETECTION_ASSIGNMENT_BINDING_ENABLED'), 'Persisted assignment identity must remain readable; pause writes instead of disabling its reader')
    if required['review']:
        require(boolean(desired_environment, 'DETECTION_IDENTITY_REVIEW_ENABLED'), 'Persisted identity review receipts require the compatible review interface')
    if required['evidence']:
        require(boolean(desired_environment, 'DETECTION_IDENTITY_EVIDENCE_ENABLED'), 'Persisted identity evidence cannot lose its reader or authorization checks')
    if required['evidence']>=2:
        require(boolean(desired_environment,'DETECTION_IDENTITY_MISSING_NAME_REVIEW_ENABLED'),'Missing-name certificates cannot lose their compatible reader; retain the feature when rolling back')
    if required['context']:
        require(boolean(desired_environment,'AGENT_DURABLE_CONTEXT_ENABLED'),'Persisted context origins cannot lose their authorization reader or be replaced by an older runtime')
    # A first writer must not strand the only recovery image at a lower format.
    existing = maximum(observed, pinned)
    future = potential(desired_environment, target_capabilities)
    require(current is None and all(future[key] <= existing[key] for key in KEYS)
            or current is not None and all(current_capabilities[key] >= required[key] for key in KEYS),
            'Prepare a compatible backend baseline with assignment writes paused and new identity features disabled before first activation')
    receipt = {'schema': 1, 'project': project, 'databaseBinding': binding, 'required': required,
               'observed': observed, 'targetImage': target_id, 'currentImage': current_id,
               'targetCapabilities': target_capabilities, 'assignmentWrites': boolean(desired_environment, GATE, True),
               'checkedAt': dt.datetime.now(ZONE).isoformat(), 'declarationOnly': True}
    if pin:
        write_json(state / 'assignment-protocol-pin.json', {key: receipt[key] for key in ('schema', 'project', 'databaseBinding', 'required', 'checkedAt')})
        write_json(state / 'assignment-transition.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('guard', 'gate'))
    parser.add_argument('--state')
    parser.add_argument('--lock-fd', type=int)
    parser.add_argument('--project', default=PROJECT)
    parser.add_argument('--container')
    parser.add_argument('--pin', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'gate':
            require(args.container and CID.fullmatch(args.container), 'Container identity required')
            rows = json.loads(docker('inspect', args.container))
            require(len(rows) == 1, 'Application metadata changed')
            row = rows[0]
            labels = row.get('Config', {}).get('Labels') or {}
            require(labels.get('com.docker.compose.project') == args.project and labels.get('com.docker.compose.service') == 'backend', 'Gate snapshot must belong to the selected backend')
            _, capabilities = image(row['Image'])
            print(str(boolean(environment(row), GATE, True)).lower() if capabilities['json'] == 2 else 'legacy')
            return
        require(args.state is not None and args.lock_fd is not None and args.lock_fd > 2, 'Inherited deployment lock required')
        state = private_state(args.state)
        import fcntl
        lock_path = state / 'deploy.lock'
        require(not lock_path.is_symlink(), 'Deployment lock cannot be a link')
        descriptor, lock = os.fstat(args.lock_fd), lock_path.stat()
        require(stat.S_ISREG(descriptor.st_mode) and descriptor.st_nlink == 1
                and (descriptor.st_dev, descriptor.st_ino) == (lock.st_dev, lock.st_ino), 'Wrong deployment lock')
        fcntl.flock(args.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        payload = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
        require(len(payload) <= 8 * 1024 * 1024, 'Compose metadata exceeded its bound')
        print(json.dumps(guard(state, json.loads(payload), project=args.project, pin=args.pin)))
    except GuardError as error:
        # GuardError messages are fixed metadata-only strings, never subprocess output.
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
    except (ValueError, KeyError, TypeError, OSError):
        # Do not include subprocess output, SQL, paths or the Compose payload in a public log.
        print('Assignment compatibility was not approved; retain existing images and inspect the private deployment evidence.', file=sys.stderr)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
