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
    require(table in ('workflow_instance', 'content_asset', 'content_link', 'runtime_state', 'audit_event', 'agent_connector'), 'Unexpected compact MCP metadata table')
    return set(common.db(mysql, "SELECT COLUMN_NAME FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='" + table + "';").split())


def observation(mysql):
    """Inspect the compact physical tables and only registered MCP protocol rows."""
    floor, execution_pending, install_pending, installer_history = 0, False, False, False
    operations = columns(mysql, 'workflow_instance')
    images = columns(mysql, 'content_asset')
    if not operations:
        require(not images, 'Partial compact MCP schema requires reconciliation')
        return floor, execution_pending, install_pending, installer_history, False
    require({'kind', 'resource_id', 'owner_user_id', 'status', 'mcp_installation_id', 'mcp_transport',
             'mcp_native_pool_id', 'mcp_writer_exit_verified', 'reserved_bytes'} <= operations,
            'Compact MCP execution and installation schema is incomplete')
    require(not common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM workflow_instance WHERE kind='MCP_EXECUTION' AND (mcp_transport IS NULL OR mcp_transport NOT IN ('STDIO','STREAMABLE_HTTP')) LIMIT 1);"), 'Unknown MCP execution transport requires reconciliation')
    if common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM workflow_instance WHERE kind='MCP_EXECUTION' AND mcp_transport='STDIO' LIMIT 1);"):
        floor = 2
    execution_pending = common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM workflow_instance WHERE kind='MCP_EXECUTION' AND mcp_transport='STDIO' AND status<>'REMOVED' LIMIT 1);")
    require(not common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM workflow_instance WHERE kind='MCP_INSTALL_WORKER' AND (mcp_transport IS NULL OR mcp_transport NOT IN ('STDIO','STREAMABLE_HTTP')) LIMIT 1);"), 'Unknown MCP installer transport requires reconciliation')
    if common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM workflow_instance WHERE kind='MCP_INSTALL_WORKER' AND mcp_transport='STDIO' LIMIT 1);"):
        floor, installer_history = 2, True
    if installer_history:
        require(not common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM workflow_instance w LEFT JOIN workflow_instance i ON i.kind='MCP_INSTALLATION' AND i.owner_user_id=w.owner_user_id AND i.resource_id=w.resource_id WHERE w.kind='MCP_INSTALL_WORKER' AND w.mcp_transport='STDIO' AND (i.id IS NULL OR i.mcp_transport<>'STDIO' OR w.mcp_native_pool_id IS NULL) LIMIT 1);"), 'Native installer evidence is incomplete; retain the current reader')
    if common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM workflow_instance WHERE kind='MCP_INSTALLATION' AND mcp_transport='STDIO' AND reserved_bytes>=536870912 LIMIT 1);"):
        floor, installer_history = 2, True
    install_pending = common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM workflow_instance i WHERE i.kind='MCP_INSTALLATION' AND i.mcp_transport='STDIO' AND i.mcp_writer_exit_verified=FALSE AND i.status<>'REMOVED' AND (i.reserved_bytes>=536870912 OR EXISTS(SELECT 1 FROM workflow_instance w WHERE w.kind='MCP_INSTALL_WORKER' AND w.owner_user_id=i.owner_user_id AND w.resource_id=i.resource_id AND w.mcp_transport='STDIO')) LIMIT 1);")
    require({'asset_kind', 'identity_key', 'lifecycle', 'revision', 'connector_cleanup_request',
             'connector_cleanup_owner_user_id', 'connector_runner_pool_id', 'connector_archive_sha256',
             'connector_image_absent'} <= images, 'Compact shared image fence schema is incomplete')
    require({'mcp_image_id', 'request_sha256', 'mcp_action', 'mcp_retention_protocol'} <= operations,
            'Compact shared image command schema is incomplete')
    image_history = common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM content_asset WHERE asset_kind='CONNECTOR_IMAGE' AND lifecycle<>'ACTIVE' LIMIT 1);") or common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM workflow_instance WHERE kind='MCP_IMAGE_COMMAND' LIMIT 1);")
    if image_history:
        floor = 3
    if common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM workflow_instance WHERE kind='MCP_IMAGE_COMMAND' AND mcp_retention_protocol>=4 LIMIT 1);"):
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
    mysql = common.selected_mysql(common.container(project, 'mysql'), desired); database = mysql['_doorhandle_database']
    common.check_database(desired, database); binding = common.database_binding(mysql, project)
    observed, execution_pending, install_pending, installer_history, image_history = observation(mysql)
    current = common.container(project, 'backend', optional=allow_initial)
    current_image, current_reader, current_potential = None, 0, 0
    if current:
        current_env = common.environment(current); common.check_current_database(current, database)
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
        require({'identity_key', 'asset_kind', 'connector_cleanup_owner_user_id', 'connector_archive_sha256'} <= columns(mysql, 'content_asset') and 'mcp_image_id' in columns(mysql, 'workflow_instance'), 'Compact shared image retirement schema is required')
        require({'link_kind','subject_id','target_id','subject_type','state'} <= columns(mysql,'content_link') and {'namespace','owner_id','scope_key','state_code','revision'} <= columns(mysql,'runtime_state') and {'kind','request_id','action','resource_id'} <= columns(mysql,'audit_event'),'Compact recovery-image retention is required before shared cleanup')
        require('mcp_retention_protocol' in columns(mysql,'workflow_instance'),'Compact shared cleanup command protocol is missing')
        target_image = desired.get('AGENT_MCP_GATEWAY_IMAGE', '')
        require(isinstance(target_image, str) and common.DIGEST.fullmatch(target_image), 'Fixed gateway image identity is required')
        require(not common.exists(mysql, "SELECT EXISTS(SELECT 1 FROM content_asset WHERE asset_kind='CONNECTOR_IMAGE' AND identity_key='" + target_image + "' AND lifecycle<>'ACTIVE' LIMIT 1);"), 'A retired or unresolved image cannot become the configured Fetch target')
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
            require({'kind', 'resource_id', 'owner_user_id', 'mcp_installation_id', 'mcp_pool_id', 'mcp_transport', 'mcp_purpose', 'status', 'mcp_exit_verified', 'mcp_cleanup_confirmed'} <= columns(mysql, 'workflow_instance'), 'Compact MCP execution receipt schema is missing')
        if flag(desired, 'AGENT_MCP_DURABLE_INSTALL_ENABLED'):
            require({'kind', 'resource_id', 'owner_user_id', 'status', 'mcp_worker_token', 'mcp_runtime_sha256'} <= columns(mysql, 'workflow_instance'), 'Compact MCP durable installation schema is missing')
        if flag(desired, 'AGENT_MCP_LIFECYCLE_ENABLED'):
            require({'kind', 'resource_id', 'mcp_writer_exit_verified', 'reserved_bytes', 'mcp_reconcile_request', 'mcp_writer_evidence_code'} <= columns(mysql, 'workflow_instance'), 'Compact MCP installation lifecycle schema is missing')
        if flag(desired, 'AGENT_MCP_INSTALL_RECONCILIATION_ENABLED'):
            require({'kind', 'mcp_transport', 'mcp_native_pool_id', 'mcp_controller_pid', 'mcp_controller_started', 'mcp_node_sha256'} <= columns(mysql, 'workflow_instance'), 'Compact MCP installation reconciliation schema is missing')
    if native(desired) and flag(desired, 'AGENT_MCP_NATIVE_INSTALL_ENABLED'):
        require(all(flag(desired, name) for name in ('AGENT_LOCAL_MCP_ENABLED', 'AGENT_MCP_NATIVE_PROCESS_ENABLED', 'AGENT_MCP_EXECUTION_RECEIPTS_ENABLED', 'AGENT_MCP_DURABLE_INSTALL_ENABLED', 'AGENT_MCP_LIFECYCLE_ENABLED', 'AGENT_MCP_INSTALL_RECONCILIATION_ENABLED')), 'Native installation requires the durable queue and all receipt readers')
        require({'mcp_transport', 'mcp_native_pool_id', 'reserved_bytes'} <= columns(mysql, 'workflow_instance'), 'Compact native MCP installation schema is required')
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
