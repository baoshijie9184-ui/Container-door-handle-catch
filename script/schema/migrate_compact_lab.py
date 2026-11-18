#!/usr/bin/env python3
"""Restore and migrate a sealed backup in a personal Ubuntu Docker instance."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
import traceback

import compact_clock_policy as clocks
from compact_migration_runtime import (ROOT, LAB_SCOPE, Mysql, UUID, fresh_output, load_config,
                                       private_json, quoted, require, sha_file, write_json)
from migrate_compact import contract, migrate, observed_source, restore_lab_source, verify


def docker_call(docker, *args, data=None, timeout=45, check=True):
    return subprocess.run([docker, *map(str, args)], input=data, capture_output=True,
                          env=Mysql.environment(), timeout=timeout, check=check)


def checked_image(docker, image):
    require(re.fullmatch(r'sha256:[a-f0-9]{64}', image), 'An immutable locally available Docker image ID is required')
    observed = docker_call(docker, 'image', 'inspect', '--format', '{{.Id}}', image).stdout.decode().strip()
    require(observed == image, 'Local image ID differs')


def root_query(docker, container, port, sql, *, check=True):
    return docker_call(docker, 'exec', '-i', container, 'sh', '-ec',
                       'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --no-defaults --no-login-paths '
                       '-uroot --protocol=TCP -h127.0.0.1 --port="$1" --batch --raw --skip-column-names',
                       '--', port, data=sql.encode(), timeout=15, check=check)


def wait_mysql(docker, container, port):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        result = root_query(docker, container, port, 'SELECT @@server_uuid;\n', check=False)
        if result.returncode == 0:
            uuid = result.stdout.decode().strip()
            require(UUID.fullmatch(uuid), 'Invalid MySQL runtime UUID')
            return uuid
        state = docker_call(docker, 'inspect', '--format', '{{.State.Running}}', container).stdout.strip()
        require(state == b'true', 'Owned MySQL exited before initialization')
        time.sleep(2)
    raise TimeoutError('Owned MySQL did not complete initialization')


def offline_clock_settings(args, manifest, model):
    if args.clock_settings:
        _, value, _ = private_json(args.clock_settings)
        require(set(value) == {'sourceOffsets', 'legacyClockPolicy'}, 'Explicit reviewed clock settings are required')
    else:
        # The original wall clocks stay unresolved where the copy contract supports it.
        # For the remaining domains zero is allowed solely after proving every input empty.
        unresolved = sorted(clocks.UNRESOLVED_DOMAINS)
        empty = sorted(clocks.EMPTY_DOMAIN_TABLES)
        value = {'sourceOffsets': dict.fromkeys(unresolved) | dict.fromkeys(empty, '+00:00'),
                 'legacyClockPolicy': {'version': 1, 'kind': clocks.POLICY_KIND,
                                       'unresolvedDomains': unresolved, 'emptyDomains': empty}}
    clocks.validate(value['sourceOffsets'], value['legacyClockPolicy'], expected_domains=clocks.DOMAINS)
    clocks.require_empty_sources(value['sourceOffsets'], value['legacyClockPolicy'], manifest)
    for domain, table in (('agent', 'agent_research_answer'), ('skill', 'agent_skill_download_lease')):
        if value['sourceOffsets'][domain] is None:
            require(manifest['tables'][table]['rows'] == 0 and table in model['sourceTables'],
                    'Additional legacy clock evidence is required for ' + domain)
    return value


def prepare_java(docker, image, folder):
    holder = docker_call(docker, 'create', '--network=none', image).stdout.decode().strip()
    try:
        docker_call(docker, 'cp', holder + ':/opt/java/openjdk', folder/'jdk', timeout=120)
        docker_call(docker, 'cp', holder + ':/app/app.jar', folder/'app.jar', timeout=120)
    finally:
        docker_call(docker, 'rm', holder)
    java, jar = (folder/'jdk/bin/java').resolve(), folder/'app.jar'
    version = subprocess.run([java, '-version'], capture_output=True, check=True, timeout=15)
    require(re.search(rb'version "17(?:[."]|$)', version.stderr + version.stdout), 'Migration requires Java 17')
    return {'java': str(java), 'applicationJar': str(jar), 'applicationJarSha256': sha_file(jar)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-manifest', type=Path, required=True)
    parser.add_argument('--backup-manifest-sha256', required=True)
    parser.add_argument('--mysql-image', required=True)
    parser.add_argument('--backend-image', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--clock-settings', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    machine = Path('/etc/machine-id').read_text(encoding='ascii').strip()
    require(sys.platform == 'linux' and os.getuid() != 0 and re.fullmatch(r'[a-f0-9]{32}', machine),
            'Run as an authorized non-root user on local Linux')
    require(1024 < args.port <= 65535 and args.port != 3306, 'Choose a separate loopback MySQL port')
    docker = str(Path(shutil.which('docker') or '').resolve())
    require(docker_call(docker, 'context', 'show').stdout.strip() == b'default'
            and docker_call(docker, 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}', 'default')
            .stdout.strip() == b'unix:///var/run/docker.sock', 'Use the existing local Docker socket')
    checked_image(docker, args.mysql_image)
    checked_image(docker, args.backend_image)
    path, manifest, digest = private_json(args.backup_manifest)
    model, model_sha = contract()
    require(digest == args.backup_manifest_sha256 and manifest.get('kind') == 'doorhandle-mysql-private-backup'
            and manifest.get('purpose') == 'source' and manifest.get('migrationContext', {}).get('kind') == 'fixture-origin-copy'
            and set(manifest['tables']) == set(model['sourceTables']) and not manifest['triggers']
            and sha_file(path.parent/'data.sql') == manifest['data']['sha256'], 'Pinned source backup does not match')
    clock_settings = offline_clock_settings(args, manifest, model)
    output = fresh_output(args.output)
    private = output/'private'
    token = secrets.token_hex(5)
    owner = 'doorhandle-lab-' + token
    source = 'doorhandle_migration_verify_' + token
    target = 'doorhandle_compact_candidate_' + token
    recovery = {'source': 'doorhandle_legacy_restore_' + token, 'target': 'doorhandle_compact_restore_' + token}
    username, password = 'mig_' + token, secrets.token_hex(32)
    root_env = private/'mysql-root.env'
    root_env.write_text('MYSQL_ROOT_PASSWORD=' + secrets.token_hex(32) + '\n', encoding='ascii')
    data = output/'mysql-data'
    data.mkdir(mode=0o700)
    container = None
    step = 'prepare-java'

    def cancelled(_signal, _frame):
        raise KeyboardInterrupt('Laboratory migration cancelled')

    signal.signal(signal.SIGTERM, cancelled)
    try:
        workbench = prepare_java(docker, args.backend_image, private)
        step = 'start-owned-mysql'
        labels = ('--label', 'io.doorhandle.lab-migration=' + token, '--label', 'io.doorhandle.lab-machine=' + machine)
        docker_call(docker, 'network', 'create', *labels, owner)
        container = docker_call(docker, 'create', '--name', owner, *labels, '--network', owner, '--restart=no',
                                '--memory=2g', '--memory-swap=2g', '--cpus=2', '--env-file', root_env,
                                '--publish', f'127.0.0.1:{args.port}:{args.port}',
                                '--mount', f'type=bind,src={data},dst={data}', args.mysql_image,
                                f'--datadir={data}', f'--port={args.port}', '--skip-log-bin', '--event-scheduler=OFF',
                                '--partial-revokes=ON', '--character-set-server=utf8mb4',
                                '--collation-server=utf8mb4_unicode_ci').stdout.decode().strip()
        require(re.fullmatch(r'[a-f0-9]{64}', container), 'Invalid owned MySQL container ID')
        write_json(output/'owner.json', {'kind':'doorhandle-lab-migration-owner', 'containerId':container,
                   'network':owner, 'mysqlImage':args.mysql_image, 'backendImage':args.backend_image,
                   'machineId':machine, 'sourceManifestSha256':digest, 'port':args.port})
        docker_call(docker, 'start', container)
        server_uuid = wait_mysql(docker, container, args.port)
        account = "'" + username + "'@'%'"
        grants = ''.join('GRANT ALL PRIVILEGES ON ' + quoted(schema) + '.* TO ' + account + ';\n'
                         for schema in (source, target, *recovery.values()))
        root_query(docker, container, args.port, f"CREATE USER {account} IDENTIFIED BY '{password}';\n" + grants)
        config_path = output/'migration-config.json'
        settings = {'version':1, 'scope':LAB_SCOPE, 'instanceId':'lab-' + machine, 'machineId':machine,
                    'serverUuid':server_uuid, 'sourceSchema':source, 'targetSchema':target, 'recoverySchemas':recovery,
                    'dataDirectory':str(data), 'connection':{'host':'127.0.0.1', 'port':args.port,
                        'username':username, 'password':password}, 'client':{'kind':'docker', 'executable':docker,
                        'containerId':container}, 'sourceCollations':{name:table['collation'] for name,table in
                        manifest['tables'].items()}, 'workbench':workbench, **clock_settings}
        write_json(config_path, settings)
        config, identity, _ = load_config(config_path)

        step = 'restore-source'
        restoration = fresh_output(output/'restore-source')
        restore_lab_source(config, identity, restoration, path, digest, model)
        root_query(docker, container, args.port, 'REVOKE ALL PRIVILEGES ON ' + quoted(source) + '.* FROM ' + account + ';\n'
                   + 'GRANT SELECT, TRIGGER, LOCK TABLES, EVENT, EXECUTE ON ' + quoted(source) + '.* TO ' + account + ';\n')
        source_receipt = restoration/'lab-source-restore.json'
        settings.update(labRestoreReceipt=str(source_receipt), labRestoreReceiptSha256=sha_file(source_receipt))
        observation_config = output/'observe-config.json'
        write_json(observation_config, settings)
        config, identity, _ = load_config(observation_config)
        print('131-table source restored and verified', flush=True)

        step = 'observe-frozen-source'
        observation = fresh_output(output/'observe')
        mysql = Mysql(config, observation)
        mysql.admitted_server()
        with mysql.source_lock(source, model['sourceTables']):
            reviewed = observed_source(mysql, config, identity, model_sha, model['sourceTables'])
        observation_path = observation/'source-observation.json'
        write_json(observation_path, reviewed)
        settings.update(reviewedSourceSnapshot=str(observation_path), reviewedSourceSnapshotSha256=sha_file(observation_path))
        admitted_config = output/'admitted-config.json'
        write_json(admitted_config, settings)
        config, identity, config_sha = load_config(admitted_config)

        step = 'migrate-and-restore-both'
        migration = fresh_output(output/'migration')
        migrate(config, identity, config_sha, migration, model, model_sha)
        step = 'read-back'
        receipt = migration/'migration-receipt.json'
        verify(config, identity, fresh_output(output/'verify'), receipt, model, model_sha)
        print(json.dumps({'status':'VERIFIED', 'receipt':str(receipt), 'targetSchema':target}), flush=True)
        return 0
    except BaseException:
        with (private/'failure.log').open('x', encoding='utf-8') as log:
            traceback.print_exc(file=log)
        stopped = container is None
        if container is not None:
            docker_call(docker, 'stop', '--time', '20', container, check=False)
            state = docker_call(docker, 'inspect', '--format', '{{.State.Running}}', container, check=False)
            stopped = state.returncode == 0 and state.stdout.strip() == b'false'
        print(json.dumps({'status':'STOPPED' if stopped else 'NEEDS_REVIEW', 'failedPhase':step,
                          'evidence':str(output)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
