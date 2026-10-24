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
CONTEXT_TABLES = ('agent_context_head','agent_context_summary','agent_context_offload','agent_context_origin','agent_context_turn','agent_context_audit','agent_context_bootstrap')


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
    require(table in ('agent_pending_action', 'detection_task', 'detection_identity_control',
                      'detection_identity_command', 'operations_audit', 'detection_identity_mapping_batch', 'detection_identity_mapping_item',
                      'detection_assignment_identity_event', 'detection_identity_source_control',
                      'detection_identity_binding', 'detection_identity_binding_event',
                      'detection_identity_reconciliation_report', 'detection_identity_reconciliation_item',
                      'detection_identity_missing_name_evidence', *CONTEXT_TABLES), 'Unexpected metadata table')
    sql = "SELECT COLUMN_NAME FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='" + table + "';"
    return set(db(mysql, sql).split())


def db(mysql, sql):
    require(mysql.get('State', {}).get('Running'), 'Existing MySQL must be running for metadata inspection')
    command = ('MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --default-character-set=utf8mb4 '
               '--batch --raw --skip-column-names "$MYSQL_DATABASE"')
    return docker('exec', '-i', mysql['Id'], 'sh', '-ec', command, data=sql.encode(), timeout=90).decode().strip()


def exists(mysql, sql):
    value = db(mysql, sql)
    require(value in ('0', '1'), 'Assignment metadata result cannot be interpreted')
    return value == '1'


def data_floor(mysql):
    floor = {key: 0 for key in KEYS}
    columns = schema(mysql, 'agent_pending_action')
    if columns:
        require({'operation', 'policy_version', 'command_json', 'before_json', 'result_json'} <= columns,
                'Confirmation schema is incomplete')
        require(not exists(mysql, "SELECT EXISTS(SELECT 1 FROM agent_pending_action WHERE operation='ASSIGN_QUALITY_TASK' AND (policy_version IS NULL OR policy_version NOT IN ('quality-assignment-confirmation-v1','quality-assignment-confirmation-v2')) LIMIT 1);"),
                'An unknown assignment confirmation policy exists')
        for column in ('command_json', 'before_json', 'result_json'):
            require(not exists(mysql, "SELECT EXISTS(SELECT 1 FROM agent_pending_action WHERE operation='ASSIGN_QUALITY_TASK' AND " + column + " IS NOT NULL AND JSON_VALID(" + column + ")=0 LIMIT 1);"),
                    'Stored assignment JSON is invalid; keep the current reader and reconcile')
            null_check = column + ' IS NULL OR ' if column != 'result_json' else ''
            require(not exists(mysql, "SELECT EXISTS(SELECT 1 FROM agent_pending_action WHERE operation='ASSIGN_QUALITY_TASK' AND (" + null_check + "CASE WHEN JSON_VALID(" + column + ") THEN JSON_TYPE(" + column + ")<>'OBJECT' ELSE 0 END) LIMIT 1);"),
                    'Stored assignment JSON has an unsupported shape; retain the current reader')
        checks = ("policy_version='quality-assignment-confirmation-v2'",
                  "CASE WHEN JSON_VALID(command_json) THEN JSON_CONTAINS_PATH(command_json,'one','$.assigneeUserId','$.assigneeRevision') ELSE 0 END=1",
                  "CASE WHEN JSON_VALID(before_json) THEN JSON_CONTAINS_PATH(before_json,'one','$.assigneeUserId','$.assignedByUserId','$.assignedByName','$.assignmentRevision') ELSE 0 END=1",
                  "CASE WHEN JSON_VALID(result_json) THEN JSON_CONTAINS_PATH(result_json,'one','$.after.assigneeUserId','$.after.assignedByUserId','$.after.assignedByName','$.after.assignmentRevision') ELSE 0 END=1")
        if exists(mysql, "SELECT EXISTS(SELECT 1 FROM agent_pending_action WHERE operation='ASSIGN_QUALITY_TASK' AND (" + ' OR '.join(checks) + ") LIMIT 1);"):
            floor['json'] = 2
    columns = schema(mysql, 'detection_task')
    identity = {'assigned_by_user_id', 'assigned_by_identity_name', 'assigned_to_revision', 'assignment_identity_revision'}
    if columns & identity:
        require(identity <= columns, 'Assignment identity migration is incomplete')
        require(not exists(mysql, 'SELECT EXISTS(SELECT 1 FROM detection_task WHERE assignment_identity_revision<0 LIMIT 1);'),
                'Assignment identity revision is invalid')
        if exists(mysql, 'SELECT EXISTS(SELECT 1 FROM detection_task WHERE assignment_identity_revision>0 OR assigned_by_user_id IS NOT NULL OR assigned_by_identity_name IS NOT NULL OR assigned_to_revision IS NOT NULL LIMIT 1);'):
            floor['identity'] = 1
    if schema(mysql, 'detection_assignment_identity_event'):
        if exists(mysql, 'SELECT EXISTS(SELECT 1 FROM detection_assignment_identity_event LIMIT 1);'):
            floor['identity'] = 1
    if schema(mysql, 'detection_identity_control'):
        modes = db(mysql, 'SELECT mode FROM detection_identity_control WHERE control_id=1;')
        require(modes in ('ACTIVE', 'PREVIEW'), 'Stable identity mode is unknown')
        if modes == 'ACTIVE':
            floor['scope'] = 1
    if schema(mysql, 'detection_identity_mapping_batch'):
        if exists(mysql, 'SELECT EXISTS(SELECT 1 FROM detection_identity_mapping_batch LIMIT 1);'):
            floor['review'] = 1
    if schema(mysql, 'detection_identity_mapping_item'):
        if exists(mysql, 'SELECT EXISTS(SELECT 1 FROM detection_identity_mapping_item LIMIT 1);'):
            floor['review'] = 1
    for table in ('detection_identity_binding', 'detection_identity_binding_event'):
        if schema(mysql, table) and exists(mysql, 'SELECT EXISTS(SELECT 1 FROM '+table+' LIMIT 1);'):
            floor['evidence'] = 1
    if schema(mysql, 'detection_identity_source_control'):
        mode = db(mysql, 'SELECT mode FROM detection_identity_source_control WHERE control_id=1;')
        require(mode in ('COLLECTING', 'ACTIVE'), 'Identity evidence mode is unknown')
        if mode == 'ACTIVE':
            require(schema(mysql, 'detection_identity_control') and db(mysql, 'SELECT mode FROM detection_identity_control WHERE control_id=1;') == 'ACTIVE',
                    'Active identity evidence cannot fall back to name-based authorization')
            floor['evidence'] = 1
    missing_schema=schema(mysql,'detection_identity_missing_name_evidence')
    if missing_schema:
        require({'batch_id','task_id','identity_role','original_name','source_snapshot','target_user_id','evidence_reference','created_at'}<=missing_schema,'Missing-name identity migration is incomplete')
        if exists(mysql,'SELECT EXISTS(SELECT 1 FROM detection_identity_missing_name_evidence LIMIT 1);'):floor['evidence']=2
    if schema(mysql,'detection_identity_binding_event') and exists(mysql,"SELECT EXISTS(SELECT 1 FROM detection_identity_binding_event WHERE source_kind='SUPERVISOR_MISSING_NAME' LIMIT 1);"):
        floor['evidence']=2
    if floor['evidence']:
        floor['review'] = 1
    if floor['identity'] or floor['review']:
        floor['scope'] = 1
    for table in CONTEXT_TABLES:
        if schema(mysql,table) and exists(mysql,'SELECT EXISTS(SELECT 1 FROM '+table+' LIMIT 1);'):floor['context']=2
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
    mysql = container(project, 'mysql')
    current = container(project, 'backend', optional=allow_initial)
    database = environment(mysql).get('MYSQL_DATABASE')
    check_database(desired_environment, database)
    binding = database_binding(mysql, project)
    observed = data_floor(mysql)
    if boolean(desired_environment,'AGENT_DURABLE_CONTEXT_ENABLED'):
        require(target_capabilities['context']>=2 and boolean(desired_environment,'AGENT_WORKBENCH_ENABLED') and boolean(desired_environment,'AGENT_WORKBENCH_RECOVERY',True) and boolean(desired_environment,'AGENT_WORKBENCH_CHILDREN',True) and boolean(desired_environment,'AGENT_CONTEXT_COMPACTION_ENABLED'),'Persistent context requires compatible origins, durable children, recovery and compaction')
        expected_context={
            'agent_context_head':{'user_id','session_id','agent_scope','revision','summary_id'},
            'agent_context_summary':{'summary_id','user_id','session_id','agent_scope','revision','status','covered_through','history_sha256','summary_json','summary_sha256','message_state','sources_json','policy_version','run_id','before_chars','after_chars','original_state'},
            'agent_context_offload':{'offload_id','user_id','session_id','agent_scope','call_id','file_id','content_sha256','byte_length','sources_json','sources_sha256'},
            'agent_context_origin':{'user_id','session_id','agent_scope','call_key','logical_task_id','run_id','sources_json','sources_sha256'},
            'agent_context_turn':{'user_id','session_id','message_id','sources_json','sources_sha256'},
            'agent_context_audit':{'user_id','session_id','agent_scope','resource_id','action','content_sha256'},
            'agent_context_bootstrap':{'user_id','session_id','logical_task_id','agent_scope','history_through','initial_state','initial_sha256','initialized'}}
        require(all(fields<=schema(mysql,table) for table,fields in expected_context.items()),'V44 persistent context migration is incomplete')
    if boolean(desired_environment,'AGENT_CONTEXT_OFFLOAD_ENABLED'):
        require(boolean(desired_environment,'AGENT_DURABLE_CONTEXT_ENABLED') and boolean(desired_environment,'AGENT_WORKBENCH_FILES',True),'Context offloading requires persistent context and private files')
    if boolean(desired_environment,'DETECTION_IDENTITY_MISSING_NAME_REVIEW_ENABLED') or observed['evidence']>=2:
        require({'batch_id','task_id','identity_role','original_name','source_snapshot','target_user_id','evidence_reference','created_at'}<=schema(mysql,'detection_identity_missing_name_evidence'),'V61 is required for explicit missing-name identity confirmation')
    if boolean(desired_environment, 'DETECTION_IDENTITY_RECONCILIATION_ENABLED'):
        require(boolean(desired_environment, 'DETECTION_IDENTITY_EVIDENCE_ENABLED'), 'Identity reconciliation requires the source evidence service')
        require({'id', 'request_id', 'actor_user_id', 'actor_name', 'request_sha256', 'protocol', 'control_revision', 'identity_mode', 'source_mode', 'started_at', 'finished_at', 'task_count', 'role_count', 'issue_count', 'dataset_sha256', 'previous_report_id', 'summary_json'} <= schema(mysql, 'detection_identity_reconciliation_report')
                and {'id', 'report_id', 'task_id', 'identity_role', 'existing_name', 'existing_user_id', 'identity_name', 'current_username', 'current_role', 'current_revision', 'source_kind', 'source_request_id', 'source_sha256', 'reason_codes', 'item_sha256'} <= schema(mysql, 'detection_identity_reconciliation_item'),
                'Identity reconciliation migration columns are missing')
    if boolean(desired_environment, 'DETECTION_IDENTITY_EVIDENCE_ENABLED'):
        require({'control_id', 'mode', 'activation_revision'} <= schema(mysql, 'detection_identity_source_control')
                and {'task_id', 'identity_role', 'event_id', 'revision', 'event_sha256'} <= schema(mysql, 'detection_identity_binding')
                and {'id', 'task_id', 'identity_role', 'revision', 'bound_user_id', 'bound_identity_name', 'target_revision', 'actor_user_id', 'actor_name', 'source_kind', 'request_id', 'source_batch_id', 'previous_sha256', 'event_sha256', 'created_at'} <= schema(mysql, 'detection_identity_binding_event'),
                'Identity evidence migration columns are missing')
    if boolean(desired_environment, 'DETECTION_IDENTITY_REVIEW_ENABLED'):
        require({'id', 'request_id', 'actor_user_id', 'actor_name', 'command_sha256', 'revision_before', 'revision_after', 'applied_count', 'result_json', 'created_at'} <= schema(mysql, 'detection_identity_mapping_batch')
                and {'batch_id', 'task_id', 'identity_role', 'source_name', 'source_snapshot', 'previous_user_id', 'previous_identity_name', 'target_user_id', 'target_username', 'target_role', 'target_revision', 'confirmation_basis'} <= schema(mysql, 'detection_identity_mapping_item'),
                'Historical identity review migration columns are missing')
    if boolean(desired_environment, 'DETECTION_STABLE_IDENTITY_ENABLED'):
        require({'control_id', 'mode', 'revision'} <= schema(mysql, 'detection_identity_control')
                and {'request_id', 'actor_user_id', 'request_sha256', 'result_json'} <= schema(mysql, 'detection_identity_command')
                and {'created_user_id', 'created_identity_name', 'assignee_user_id', 'assignee_identity_name',
                     'reviewer_user_id', 'reviewer_identity_name', 'disposition_user_id', 'disposition_identity_name',
                     'rework_user_id', 'rework_identity_name'} <= schema(mysql, 'detection_task'),
                'Stable identity migration columns are missing; no automatic migration is allowed')
    if boolean(desired_environment, 'OPERATIONS_AUDIT_ENABLED'):
        require({'actor_user_id', 'scope', 'domain', 'action', 'resource_id', 'request_id', 'result', 'resource_version', 'created_at'} <= schema(mysql, 'operations_audit'),
                'Operations audit migration columns are missing')
    if boolean(desired_environment, 'DETECTION_ASSIGNMENT_BINDING_ENABLED'):
        require({'assigned_by_user_id', 'assigned_by_identity_name', 'assigned_to_revision', 'assignment_identity_revision'} <= schema(mysql, 'detection_task')
                and {'task_id', 'revision', 'actor_user_id', 'actor_name', 'assignee_user_id', 'assignee_name', 'assignee_revision', 'request_id', 'created_at'} <= schema(mysql, 'detection_assignment_identity_event'),
                'Assignment identity migration columns are missing')
    pinned = read_pin(state, project, binding)
    current_id, current_capabilities, current_potential = None, {key: 0 for key in KEYS}, {key: 0 for key in KEYS}
    if current:
        check_database(environment(current), database)
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
