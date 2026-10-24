#!/usr/bin/env python3
"""Metadata-only native MCP protocol guard; never runs tools, migrations or Docker mutations."""
import argparse
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

try:
    _spec = importlib.util.spec_from_file_location('mcp_assignment_guard_common', Path(__file__).with_name('assignment-compat.py'))
    common = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(common)
except Exception:
    print('The native MCP guard requires its matching deployment metadata helper.', file=sys.stderr)
    raise SystemExit(2)
require, GuardError = common.require, common.GuardError
LABEL = 'io.doorhandle.mcp-native-protocol'
GATE = 'AGENT_MCP_WRITES_ENABLED'
PIN = 'mcp-native-protocol-pin.json'


def capability(reference):
    require(isinstance(reference, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/@-]{0,500}', reference), 'Invalid MCP image reference')
    rows = json.loads(common.docker('image', 'inspect', reference))
    require(len(rows) == 1 and common.DIGEST.fullmatch(rows[0].get('Id', '')), 'MCP image identity unavailable')
    value = (rows[0].get('Config', {}).get('Labels') or {}).get(LABEL, '0')
    require(value in ('0', '2', '3', '4'), 'Unsupported MCP protocol declaration')
    return rows[0]['Id'], int(value)


def columns(mysql, table):
    require(table in ('agent_mcp_execution', 'agent_fetch_installation', 'agent_mcp_install_worker', 'agent_mcp_install_job', 'agent_fetch_image', 'agent_fetch_image_command', 'agent_fetch_image_retention', 'agent_fetch_image_retention_control', 'agent_fetch_image_retention_event'), 'Unexpected MCP metadata table')
    return set(common.db(mysql, "SELECT COLUMN_NAME FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='" + table + "';").split())


def observation(mysql):
    floor, execution_pending, install_pending, installer_history = 0, False, False, False
    execution = columns(mysql, 'agent_mcp_execution')
    if 'transport' in execution:
        require({'owner_user_id', 'installation_id', 'state', 'execution_id'} <= execution, 'MCP execution receipt schema is incomplete')
        require(not common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM agent_mcp_execution WHERE transport NOT IN ('STDIO','STREAMABLE_HTTP') LIMIT 1);"), 'Unknown MCP execution transport requires reconciliation')
        if common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM agent_mcp_execution WHERE transport='STDIO' LIMIT 1);"):
            floor = 2
        execution_pending = common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM agent_mcp_execution WHERE transport='STDIO' AND state<>'REMOVED' LIMIT 1);")
    worker = columns(mysql, 'agent_mcp_install_worker')
    if 'writer_transport' in worker:
        require({'native_pool_id', 'installation_id', 'owner_user_id'} <= worker, 'Native MCP installer evidence schema is incomplete')
        require(not common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM agent_mcp_install_worker WHERE writer_transport NOT IN ('STDIO','STREAMABLE_HTTP') LIMIT 1);"), 'Unknown MCP installer transport requires reconciliation')
        if common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM agent_mcp_install_worker WHERE writer_transport='STDIO' LIMIT 1);"):
            floor, installer_history = 2, True
    installation = columns(mysql, 'agent_fetch_installation')
    if installer_history:
        require({'writer_exit_verified', 'transport', 'state', 'owner_user_id', 'installation_id', 'reserved_bytes'} <= installation, 'Native installer is missing its installation snapshot')
        require(not common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM agent_mcp_install_worker w LEFT JOIN agent_fetch_installation i ON i.owner_user_id=w.owner_user_id AND i.installation_id=w.installation_id WHERE w.writer_transport='STDIO' AND (i.installation_id IS NULL OR i.transport<>'STDIO' OR w.native_pool_id IS NULL) LIMIT 1);"), 'Native installer evidence is incomplete; retain the current reader')
    if 'reserved_bytes' in installation:
        require({'writer_exit_verified', 'transport', 'state'} <= installation, 'Native MCP installation schema is incomplete')
        # Even a never-dispatched installation may have no worker row yet.
        if common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM agent_fetch_installation WHERE transport='STDIO' AND reserved_bytes>=536870912 LIMIT 1);"):
            floor, installer_history = 2, True
        install_pending = common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM agent_fetch_installation i WHERE i.transport='STDIO' AND i.writer_exit_verified=FALSE AND i.state<>'REMOVED' AND (i.reserved_bytes>=536870912 OR EXISTS(SELECT 1 FROM agent_mcp_install_worker w WHERE w.owner_user_id=i.owner_user_id AND w.installation_id=i.installation_id AND w.writer_transport='STDIO')) LIMIT 1);")
    image_history = False
    images = columns(mysql, 'agent_fetch_image')
    if images:
        require({'image_id', 'state', 'revision', 'cleanup_request', 'cleanup_owner_user_id', 'runner_pool_id', 'archive_sha256', 'image_absent'} <= images, 'Shared image fence migration is incomplete')
        require({'owner_user_id', 'request_id', 'image_id', 'request_sha256', 'action_name', 'state'} <= columns(mysql, 'agent_fetch_image_command'), 'Shared image command migration is incomplete')
        image_history = common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM agent_fetch_image WHERE state<>'ACTIVE' LIMIT 1);") or common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM agent_fetch_image_command LIMIT 1);")
        if image_history:
            floor = 3
        if 'retention_protocol' in columns(mysql,'agent_fetch_image_command') and common.exists(mysql,"SELECT EXISTS(SELECT 1 FROM agent_fetch_image_command WHERE retention_protocol>=4 LIMIT 1);"):
            floor = 4
    return floor, execution_pending, install_pending, installer_history, image_history


def flag(env, name, default=False):
    return common.boolean(env, name, default)


def native(env):
    return env.get('AGENT_MCP_TRANSPORT', 'STDIO') == 'STDIO'


def potential(env):
    if flag(env, 'AGENT_LOCAL_MCP_ENABLED') and flag(env, GATE, True) and flag(env, 'AGENT_MCP_SHARED_IMAGE_CLEANUP_ENABLED'):
        return 4
    return 2 if native(env) and flag(env, 'AGENT_LOCAL_MCP_ENABLED') and flag(env, GATE, True) and (flag(env, 'AGENT_MCP_NATIVE_PROCESS_ENABLED') or flag(env, 'AGENT_MCP_NATIVE_INSTALL_ENABLED')) else 0


def read_pin(state, project, binding):
    path = state / PIN
    if not path.exists():
        require(not path.is_symlink(), 'MCP protocol pin cannot be a broken link'); return 0
    require(not path.is_symlink(), 'MCP protocol pin cannot be a link')
    row = path.stat()
    require(stat.S_ISREG(row.st_mode) and row.st_nlink == 1 and row.st_size < 8192 and row.st_uid in (0, os.geteuid()) and not row.st_mode & 0o077, 'MCP protocol pin is not a private file')
    value = json.loads(path.read_text(encoding='utf-8'))
    require(value.get('schema') == 1 and value.get('project') == project and value.get('databaseBinding') == binding and type(value.get('required')) is int and value['required'] in (0, 2, 3, 4), 'MCP protocol pin does not match this database')
    return value['required']


def guard(state, config, *, project=common.PROJECT, pin=False, allow_initial=False, runner_transition=False, minimum_protocol=0):
    state = common.private_state(state); backend = config.get('services', {}).get('backend', {})
    desired = backend.get('environment', {}); require(isinstance(desired, dict), 'Resolved MCP Compose environment required')
    target, reader = capability(backend.get('image'))
    mysql = common.container(project, 'mysql'); database = common.environment(mysql).get('MYSQL_DATABASE')
    common.check_database(desired, database); binding = common.database_binding(mysql, project)
    observed, execution_pending, install_pending, installer_history, image_history = observation(mysql)
    current = common.container(project, 'backend', optional=allow_initial)
    current_image, current_reader, current_potential = None, 0, 0
    if current:
        current_env = common.environment(current); common.check_database(current_env, database)
        current_image, current_reader = capability(current['Image']); current_potential = potential(current_env)
    held = read_pin(state, project, binding); future = potential(desired)
    require(type(minimum_protocol) is int and minimum_protocol in (0,2,3,4), 'Invalid runner-derived MCP protocol floor')
    required = max(observed, held, current_potential, future, minimum_protocol)
    require(reader >= required, 'Selected backend cannot preserve native MCP receipts; choose a compatible recovery image')
    require(desired.get('AGENT_MCP_TRANSPORT', 'STDIO') in ('STDIO', 'GATEWAY'), 'Unknown MCP transport configuration')
    if flag(desired, 'AGENT_MCP_NATIVE_INSTALL_ENABLED'):
        require(native(desired), 'Native MCP installation cannot run in gateway mode')
    if observed:
        require(flag(desired, 'AGENT_LOCAL_MCP_ENABLED') and flag(desired, 'AGENT_MCP_EXECUTION_RECEIPTS_ENABLED'), 'Native MCP history must retain the metadata reader')
    if installer_history:
        require(flag(desired, 'AGENT_MCP_LIFECYCLE_ENABLED'), 'Native installation history requires its lifecycle reader')
    if not flag(desired, GATE, True):
        require(reader >= 2, 'Selected backend does not implement the MCP write gate')
    if image_history or held >= 3:
        require(flag(desired, 'AGENT_MCP_SHARED_IMAGE_CLEANUP_ENABLED'), 'Shared image fences cannot lose their history and reconciliation interface')
    if flag(desired, 'AGENT_MCP_SHARED_IMAGE_CLEANUP_ENABLED'):
        require(not native(desired) and reader >= 4 and all(flag(desired, name) for name in ('AGENT_LOCAL_MCP_ENABLED', 'AGENT_MCP_EXECUTION_RECEIPTS_ENABLED', 'AGENT_MCP_DURABLE_INSTALL_ENABLED', 'AGENT_MCP_LIFECYCLE_ENABLED', 'AGENT_MCP_INSTALL_RECONCILIATION_ENABLED')), 'Shared image retirement requires deployment-aware gateway readers')
        require({'image_id', 'cleanup_owner_user_id', 'archive_sha256'} <= columns(mysql, 'agent_fetch_image') and 'image_id' in columns(mysql, 'agent_mcp_execution'), 'V59 must be applied before shared image retirement')
        require({'reference_id','image_id','reference_kind','state'} <= columns(mysql,'agent_fetch_image_retention') and {'control_id','state','revision'} <= columns(mysql,'agent_fetch_image_retention_control') and {'request_id','action_name','image_id'} <= columns(mysql,'agent_fetch_image_retention_event'),'V60 recovery-image retention is required before shared cleanup')
        require('retention_protocol' in columns(mysql,'agent_fetch_image_command'),'Shared cleanup command protocol migration is missing')
        target_image = desired.get('AGENT_MCP_GATEWAY_IMAGE', '')
        require(isinstance(target_image, str) and common.DIGEST.fullmatch(target_image), 'Fixed gateway image identity is required')
        require(not common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM agent_fetch_image WHERE image_id='" + target_image + "' AND state<>'ACTIVE' LIMIT 1);"), 'A retired or unresolved image cannot become the configured Fetch target')
        runner = common.container(project, 'mcp-runner', optional=allow_initial)
        desired_runner = config.get('services', {}).get('mcp-runner', {})
        require(flag(desired_runner.get('environment', {}), 'MCP_SHARED_IMAGE_CLEANUP_ENABLED'), 'Runner image lifecycle must be explicitly enabled')
        if runner and not runner_transition:
            require(flag(common.environment(runner), 'MCP_SHARED_IMAGE_CLEANUP_ENABLED'), 'Existing runner has not activated its lifecycle interface')
            require(common.environment(runner).get('MCP_FETCH_IMAGE') == desired.get('AGENT_MCP_GATEWAY_IMAGE'), 'Existing runner target differs from the selected backend release')
        for reference in ((runner['Image'],) if runner and not runner_transition else ()) + (desired_runner.get('image'),):
            metadata = json.loads(common.docker('image', 'inspect', reference))
            require(len(metadata) == 1 and (metadata[0].get('Config', {}).get('Labels') or {}).get('io.doorhandle.mcp-image-lifecycle') == '2', 'Prepare a deployment-aware persistent runner before activating cleanup')
    if flag(desired, 'AGENT_LOCAL_MCP_ENABLED'):
        if flag(desired, 'AGENT_MCP_EXECUTION_RECEIPTS_ENABLED'):
            require({'execution_id', 'owner_user_id', 'installation_id', 'pool_id', 'transport', 'purpose', 'state', 'exit_verified', 'cleanup_confirmed'} <= columns(mysql, 'agent_mcp_execution'), 'MCP execution receipt migrations are missing')
        if flag(desired, 'AGENT_MCP_DURABLE_INSTALL_ENABLED'):
            require({'operation_id', 'owner_user_id', 'status', 'worker_token', 'runtime_sha256'} <= columns(mysql, 'agent_mcp_install_job'), 'MCP durable installation migration is missing')
        if flag(desired, 'AGENT_MCP_LIFECYCLE_ENABLED'):
            require({'installation_id', 'writer_exit_verified', 'reserved_bytes', 'reconcile_request', 'writer_evidence_code'} <= columns(mysql, 'agent_fetch_installation'), 'MCP installation lifecycle migrations are missing')
        if flag(desired, 'AGENT_MCP_INSTALL_RECONCILIATION_ENABLED'):
            require({'writer_transport', 'native_pool_id', 'controller_pid', 'controller_started', 'node_sha256'} <= columns(mysql, 'agent_mcp_install_worker'), 'MCP installation reconciliation migrations are missing')
    if native(desired) and flag(desired, 'AGENT_MCP_NATIVE_INSTALL_ENABLED'):
        require(all(flag(desired, name) for name in ('AGENT_LOCAL_MCP_ENABLED', 'AGENT_MCP_NATIVE_PROCESS_ENABLED', 'AGENT_MCP_EXECUTION_RECEIPTS_ENABLED', 'AGENT_MCP_DURABLE_INSTALL_ENABLED', 'AGENT_MCP_LIFECYCLE_ENABLED', 'AGENT_MCP_INSTALL_RECONCILIATION_ENABLED')), 'Native installation requires the durable queue and all receipt readers')
        require({'writer_transport', 'native_pool_id'} <= columns(mysql, 'agent_mcp_install_worker') and 'reserved_bytes' in columns(mysql, 'agent_fetch_installation'), 'V58 is required before native MCP installation')
        raw_quota = desired.get('AGENT_MCP_STORAGE_QUOTA_BYTES', '268435456')
        require(isinstance(raw_quota, (str, int)) and str(raw_quota).isdigit() and 536870912 <= int(raw_quota) <= 4294967296, 'Native installation reservation exceeds the configured quota')
    if execution_pending or install_pending:
        require(native(desired) and flag(desired, 'AGENT_LOCAL_MCP_ENABLED') and flag(desired, 'AGENT_MCP_NATIVE_PROCESS_ENABLED') and flag(desired, 'AGENT_MCP_EXECUTION_RECEIPTS_ENABLED'), 'Pending native MCP executions must retain their original reconciliation path')
    if install_pending:
        require(flag(desired, 'AGENT_MCP_NATIVE_INSTALL_ENABLED') and flag(desired, 'AGENT_MCP_INSTALL_RECONCILIATION_ENABLED'), 'Pending native installers cannot lose their supervisor reader')
    # A new writer cannot invalidate the only recorded recovery image.
    require(current is None and future <= max(observed, held) or current is not None and current_reader >= required, 'Prepare a compatible paused backend baseline before activating native MCP writers')
    receipt = {'schema': 1, 'project': project, 'databaseBinding': binding, 'required': required, 'observed': observed,
               'targetImage': target, 'currentImage': current_image, 'targetCapability': reader,
               'writesEnabled': flag(desired, GATE, True), 'nativeExecutionPending': execution_pending, 'nativeInstallPending': install_pending,
               'checkedAt': dt.datetime.now(common.ZONE).isoformat(), 'declarationOnly': True}
    if pin:
        common.write_json(state / PIN, {key: receipt[key] for key in ('schema', 'project', 'databaseBinding', 'required', 'checkedAt')})
        common.write_json(state / 'mcp-transition.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('guard', 'gate')); parser.add_argument('--state'); parser.add_argument('--lock-fd', type=int)
    parser.add_argument('--project', default=common.PROJECT); parser.add_argument('--pin', action='store_true'); parser.add_argument('--container')
    args = parser.parse_args()
    if args.action == 'gate':
        require(args.container and common.CID.fullmatch(args.container), 'MCP gate container identity required')
        values = json.loads(common.docker('inspect', args.container)); require(len(values) == 1, 'MCP gate container unavailable')
        row = values[0]; labels = row.get('Config', {}).get('Labels') or {}
        require(row.get('Id') == args.container and labels.get('com.docker.compose.project') == args.project and labels.get('com.docker.compose.service') == 'backend', 'MCP gate container belongs to another deployment')
        _, reader = capability(row['Image']); print(str(flag(common.environment(row), GATE, True)).lower() if reader >= 2 else 'legacy'); return
    require(args.state is not None and args.lock_fd is not None and args.lock_fd > 2, 'Inherited MCP deployment lock required')
    state = common.private_state(args.state); path = state / 'deploy.lock'
    require(not path.is_symlink(), 'MCP deployment lock cannot be a link')
    descriptor, lock = os.fstat(args.lock_fd), path.stat()
    require(stat.S_ISREG(descriptor.st_mode) and descriptor.st_nlink == 1 and (descriptor.st_dev, descriptor.st_ino) == (lock.st_dev, lock.st_ino), 'Wrong MCP deployment lock')
    import fcntl
    fcntl.flock(args.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    payload = sys.stdin.buffer.read(8 * 1024 * 1024 + 1); require(len(payload) <= 8 * 1024 * 1024, 'MCP Compose metadata too large')
    print(json.dumps(guard(state, json.loads(payload), project=args.project, pin=args.pin)))


if __name__ == '__main__':
    try:
        main()
    except GuardError as error:
        print(str(error), file=sys.stderr); raise SystemExit(2)
    except Exception:
        print('Native MCP compatibility was not approved; retain existing evidence and images.', file=sys.stderr); raise SystemExit(2)
