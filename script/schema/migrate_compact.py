#!/usr/bin/env python3
"""Observe, migrate, or revalidate the complete legacy source on the admitted ECS.

The source is never mutated. A partially created candidate is retained after any
failure or unknown result. The CLI neither activates applications nor starts or
stops ECS. Deployment uses the verified receipt, not this command's intent.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import compact_clock_policy as clocks

from compact_migration_runtime import (ROOT, Mysql, WORKBENCH_SOURCES, compiled_target_parts,
    copy_plan, executable, fresh_output, freeze_evidence, install_relations,
    load_config, metadata_snapshot, new_schema, private_json, render_copy, require,
    restore_backup, schema_snapshot, sha_file, sha_json, utc_now, write_json,
    backup_schema, validate_migration_receipt, admit_source_trigger_definers, literal)


def contract():
    path = ROOT / 'docs/database/compact-schema-contract.json'
    value = json.loads(path.read_text(encoding='utf8'))
    require(len(value['sourceTables']) == len(set(value['sourceTables'])) == 131
            and len(value['expectedTargetTables']) == len(set(value['expectedTargetTables'])) == 29
            and value['maximumBusinessTables'] == 30, 'The complete source and target contract was redefined')
    return value, sha_file(path)


def observed_source(mysql, config, identity, contract_sha, sources):
    mysql.assert_source_lock()
    admit_source_trigger_definers(mysql, config['sourceSchema'])
    require(mysql.single("SELECT JSON_OBJECT('n',COUNT(*)) FROM information_schema.key_column_usage WHERE table_schema="
                         + literal(config['sourceSchema']) + ' AND referenced_table_schema IS NOT NULL AND BINARY referenced_table_schema<>BINARY '
                         + literal(config['sourceSchema']) + ';')['n'] == 0,
            'Source foreign keys reference an external schema absent from the complete migration/recovery contract')
    if config['scope'] == 'ecs-disposable-migration':
        # EVENT is needed to see this catalog at all. A schema-limited production
        # migration instead receives the administrative catalog in freeze proof.
        grantee = "CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)))"
        for privilege in ('EVENT', 'EXECUTE'):
            require(mysql.single("SELECT JSON_OBJECT('n',SUM(n)) FROM (SELECT COUNT(*) n FROM information_schema.schema_privileges WHERE table_schema="
                    + literal(config['sourceSchema']) + ' AND privilege_type=' + literal(privilege) + ' AND grantee=' + grantee
                    + ' UNION ALL SELECT COUNT(*) n FROM information_schema.user_privileges WHERE privilege_type=' + literal(privilege)
                    + ' AND grantee=' + grantee + ') g;')['n'] > 0,
                    'Disposable source object visibility requires an explicit metadata grant: ' + privilege)
        require(mysql.single("SELECT JSON_OBJECT('n',COUNT(*)) FROM information_schema.events WHERE event_schema="
                             + literal(config['sourceSchema']) + ';')['n'] == 0,
                'Source database events require a separately reviewed restore plan; this migration cannot silently omit them')
        require(mysql.single("SELECT JSON_OBJECT('n',COUNT(*)) FROM information_schema.routines WHERE routine_schema="
                             + literal(config['sourceSchema']) + ';')['n'] == 0,
                'Source stored routines require a separately reviewed restore plan; this migration cannot silently omit them')
    snapshot = schema_snapshot(mysql, config['sourceSchema'], sources)
    require(sum(row['rows'] for row in snapshot['tables'].values()) > 0,
            'An empty source cannot demonstrate preservation of the existing business data')
    require(set(config['sourceCollations']) == set(sources) and all(
        config['sourceCollations'][name] == detail['collation'] for name, detail in snapshot['tables'].items()),
        'Reviewed source collations do not match the entire actual source catalog')
    _, meta_sha = metadata_snapshot(mysql, config['sourceSchema'])
    return {'schemaVersion': 1, 'kind': 'doorhandle-compact-source-observation', 'status': 'FROZEN_SOURCE_OBSERVED',
            'ecs': identity, 'serverUuid': config['serverUuid'], 'sourceSchema': config['sourceSchema'],
            'contractSha256': contract_sha, 'sourceSnapshotSha256': snapshot['snapshotSha256'],
            'sourceMetadataSha256': meta_sha, 'sourceTableCount': len(snapshot['tables']),
            'sourceSnapshot': snapshot, 'observedAtUtc': utc_now()}


def workbench(mysql, config, identity, output, *, source_snapshot_sha256=None):
    value = config.get('workbench')
    require(isinstance(value, dict) and set(value) in ({'java', 'applicationJar', 'applicationJarSha256'}, {'java', 'classpath'}),
            'A built candidate application jar or explicit complete Java classpath is required')
    java = executable(value['java'])
    if 'applicationJar' in value:
        jar = Path(value['applicationJar'])
        require(jar.is_absolute() and jar.resolve(strict=True) == jar and jar.is_file()
                and sha_file(jar) == value['applicationJarSha256'], 'Candidate migration jar checksum differs')
        command = [str(java), '-Dloader.main=com.ruanzhu.doorhandle.module.ai.workbench.CompactWorkbenchMigrationCli',
                   '-cp', str(jar), 'org.springframework.boot.loader.launch.PropertiesLauncher']
        artifact = value['applicationJarSha256']
    else:
        require(isinstance(value['classpath'], list) and value['classpath'], 'Explicit migration classpath required')
        paths = [Path(item) for item in value['classpath']]
        require(all(path.is_absolute() and path.resolve(strict=True) == path and path.exists() for path in paths),
                'Only explicit existing migration classpath files/directories are permitted')
        command = [str(java), '-cp', os.pathsep.join(map(str, paths)),
                   'com.ruanzhu.doorhandle.module.ai.workbench.CompactWorkbenchMigrationCli']
        artifact = sha_json([{'file': str(path), 'sha256': sha_file(path) if path.is_file() else None} for path in paths])
    settings = {'version': 1, 'kind': 'doorhandle-workbench-migration-config',
                'instanceId': identity['instanceId'], 'machineId': identity['machineId'],
                'sourceSchema': config['sourceSchema'], 'targetSchema': config['targetSchema'],
                'serverUuid': config['serverUuid'], 'sourceUtcOffset': config['sourceOffsets'].get('workbench'),
                'sourceCollations': {name: config['sourceCollations'][name] for name in sorted(WORKBENCH_SOURCES)},
                'connection': config['connection'], 'scope': config['scope'], 'client': config['client']}
    extra = clocks.workbench_fields(config['sourceOffsets'], config.get('legacyClockPolicy'), source_snapshot_sha256)
    if extra:
        settings.update(version=2, **extra)
    else:
        require(clocks.fixed_offset(settings['sourceUtcOffset']), 'An observed Workbench source UTC offset is required')
    config_path = output / 'private/workbench.json'
    receipt_path = output / 'workbench-receipt.json'
    write_json(config_path, settings)
    command += ['--config', str(config_path), '--output', str(receipt_path)]
    env = {name: item for name, item in os.environ.items() if name in ('PATH', 'LANG', 'LC_ALL')}
    env.update(DOORHANDLE_ECS_INSTANCE_ID=identity['instanceId'], DOORHANDLE_ECS_MACHINE_ID=identity['machineId'])
    log_path = output / 'private/workbench.log'
    with log_path.open('xb') as log:
        os.chmod(log_path, 0o600)
        completed = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=240)
    require(completed.returncode == 0 and receipt_path.is_file(),
            'Workbench Java copy failed or has UNKNOWN outcome; preserve existing target and source')
    _, receipt, digest = private_json(receipt_path)
    require(receipt.get('status') == 'VERIFIED' and receipt.get('verification', {}).get('matches') is True,
            'Workbench post-commit evidence is incomplete')
    return {'receipt': {'file': receipt_path.name, 'sha256': digest}, 'applicationArtifactSha256': artifact}


def initialize_target(mysql, config, base, guards):
    new_schema(mysql, config['targetSchema'])
    for number, statement in enumerate(base):
        mysql.script(statement + ';', database=config['targetSchema'], label='baseline-' + str(number))
    for number, statement in enumerate(guards):
        mysql.script(statement, database=config['targetSchema'], label='guards-' + str(number))


def migrate(config, identity, config_sha, output, model, model_sha):
    sql, catalog, base, foreign, guards = compiled_target_parts()
    plan = copy_plan(model)
    plan_sha = sha_json(plan)
    mysql = Mysql(config, output)
    server = mysql.admitted_server()
    freeze = freeze_evidence(config, identity)
    _, reviewed, reviewed_sha = private_json(config.get('reviewedSourceSnapshot', ''))
    require(reviewed_sha == config.get('reviewedSourceSnapshotSha256')
            and reviewed.get('kind') == 'doorhandle-compact-source-observation'
            and reviewed.get('status') == 'FROZEN_SOURCE_OBSERVED'
            and reviewed.get('ecs') == identity and reviewed.get('sourceSchema') == config['sourceSchema']
            and reviewed.get('serverUuid') == config['serverUuid'] and reviewed.get('contractSha256') == model_sha,
            'A reviewed complete source observation for this exact schema and server is required')
    # Bind provenance to the reviewed observation before any target DDL. The
    # same complete snapshot is independently verified under the source lock.
    source_binding = clocks.snapshot_binding(reviewed.get('sourceSnapshotSha256'))
    rendered = {step['name']: render_copy((ROOT / 'sql/mysql/compact/copy' / step['name']).read_text(encoding='utf8'),
                    config, source_snapshot_sha256=source_binding)
                for step in plan if step['kind'] == 'sql'}
    attempt = uuid.uuid4().hex
    record = {'schemaVersion': 1, 'kind': 'doorhandle-compact-migration', 'status': 'IN_PROGRESS',
              'attempt': attempt, 'ecs': identity, 'scope': config['scope'], 'startedAtUtc': utc_now(),
              'serverUuid': config['serverUuid'], 'sourceSchema': config['sourceSchema'], 'targetSchema': config['targetSchema'],
              'configSha256': config_sha, 'contractSha256': model_sha, 'sqlSha256': catalog['sqlSha256'],
              'copyPlanSha256': plan_sha, 'reviewedSourceObservationSha256': reviewed_sha,
              'freezeEvidenceSha256': freeze['sha256'], 'sourceTableCount': 131, 'targetTableCount': 29,
              'executedSteps': [], 'lifecycle': 'external-to-jenkins',
              'sourceClockPolicy': clocks.evidence(config['sourceOffsets'], config.get('legacyClockPolicy'))}
    context = {name: record[name] for name in ('attempt', 'ecs', 'scope', 'serverUuid', 'sourceSchema', 'targetSchema',
                                              'contractSha256', 'sqlSha256', 'copyPlanSha256')}
    try:
        with mysql.source_lock(config['sourceSchema'], model['sourceTables']) as lock:
            record['sourceReadLock'] = lock
            observed = observed_source(mysql, config, identity, model_sha, model['sourceTables'])
            require(all(observed[name] == reviewed[name] for name in ('sourceSnapshotSha256', 'sourceMetadataSha256')),
                    'Reviewed source rows, metadata or high-water marks changed; do not migrate')
            source_snapshot = observed['sourceSnapshot']
            record['sourceSnapshotSha256'] = observed['sourceSnapshotSha256']
            record['sourceMetadataSha256'] = observed['sourceMetadataSha256']
            source_backup = backup_schema(mysql, source_snapshot, output / 'private/source-backup',
                                          purpose='source', migration_context=context)
            initialize_target(mysql, config, base, guards)
            for step in plan:
                mysql.assert_source_lock()
                if step['kind'] == 'java':
                    proof = workbench(mysql, config, identity, output, source_snapshot_sha256=record['sourceSnapshotSha256'])
                else:
                    path = ROOT / 'sql/mysql/compact/copy' / step['name']
                    require(sha_file(path) == step['sha256'], 'Copy source changed during migration')
                    body = rendered[step['name']]
                    # These legacy per-segment session guards communicate the
                    # independently verified freeze. They never establish it.
                    domain = {'45-context.sql': 'context', '46-detection-identity.sql': 'identity',
                              '48-mcp.sql': 'mcp'}.get(step['name'])
                    if domain:
                        body = 'SET @compact_' + domain + '_source_frozen=1; SET @compact_' + domain + '_target_frozen=1;\n' + body
                    mysql.script(body, database=config['targetSchema'], label='copy-' + path.stem)
                    proof = {'transaction': 'SEGMENT_COMMITTED_AND_LOCAL_GUARDS_PASSED'}
                record['executedSteps'].append({**step, 'finishedAtUtc': utc_now(), **proof})
                write_json(output / ('step-' + str(len(record['executedSteps'])).zfill(2) + '.json'), record['executedSteps'][-1])
            install_relations(mysql, config['targetSchema'], foreign)
            record['foreignKeysValidated'] = True
            target_snapshot = schema_snapshot(mysql, config['targetSchema'], model['expectedTargetTables'])
            _, target_meta_sha = metadata_snapshot(mysql, config['targetSchema'])
            record['targetSnapshotSha256'] = target_snapshot['snapshotSha256']
            record['targetMetadataSha256'] = target_meta_sha
            target_backup = backup_schema(mysql, target_snapshot, output / 'private/target-backup',
                                          purpose='target', migration_context=context)
            final_source = observed_source(mysql, config, identity, model_sha, model['sourceTables'])
            require(final_source['sourceSnapshotSha256'] == record['sourceSnapshotSha256']
                    and final_source['sourceMetadataSha256'] == record['sourceMetadataSha256'],
                    'Source changed during the supposedly frozen complete migration')
            record['sourceSnapshot'] = source_snapshot
            record['targetSnapshot'] = target_snapshot
            evidence = {**record, 'kind': 'doorhandle-compact-migration-evidence', 'status': 'COPY_VERIFIED',
                        'migrationContext': context}
            evidence_path = output / 'migration-evidence.json'
            write_json(evidence_path, evidence)
            record['evidence'] = {'file': evidence_path.name, 'sha256': sha_file(evidence_path)}
            recovery = {}
            for purpose, backup in (('source', source_backup), ('target', target_backup)):
                folder = output / (purpose + '-recovery')
                restore_backup(mysql, backup, config['recoverySchemas'][purpose], folder, evidence_path)
                file = folder / 'recovery-receipt.json'
                recovery[purpose] = {'file': file.relative_to(output).as_posix(), 'sha256': sha_file(file)}
            record['recovery'] = recovery
            require(mysql.admitted_server() == server, 'MySQL identity or enforcement changed during recovery verification')
            require(freeze_evidence(config, identity) == freeze, 'Source-writer freeze evidence or stopped state changed')
            # Final target readback follows restoration on the same server: copying
            # and validating a clone must never change the candidate or source.
            require(schema_snapshot(mysql, config['targetSchema'], model['expectedTargetTables'])['snapshotSha256']
                    == record['targetSnapshotSha256'], 'Candidate changed during recovery proof')
            require(observed_source(mysql, config, identity, model_sha, model['sourceTables'])['sourceSnapshotSha256']
                    == record['sourceSnapshotSha256'], 'Source changed during recovery proof')
            mysql.assert_source_lock()
        # The lock context must finish successfully before a consumer-visible
        # VERIFIED receipt exists. Validate a private candidate first, then use
        # an atomic same-directory rename; failure never leaves a final receipt.
        record['status'] = 'VERIFIED'
        record['finishedAtUtc'] = utc_now()
        candidate = output / 'migration-receipt.pending.json'
        write_json(candidate, record)
        validate_migration_receipt(candidate)
        candidate.rename(output / 'migration-receipt.json')
        return record
    except BaseException as error:
        record['status'] = 'FAILED_OR_UNKNOWN_STOPPED'
        record['errorType'] = type(error).__name__
        record['finishedAtUtc'] = utc_now()
        # No cleanup/replay: DDL and earlier segment commits are intentionally
        # retained for inspection. A failure is never a complete migration.
        write_json(output / 'migration-failed.json', record)
        raise


def verify(config, identity, output, receipt_path, model, model_sha):
    _, catalog, _, _, _ = compiled_target_parts()
    prior = validate_migration_receipt(receipt_path, {'ecs': identity, 'serverUuid': config['serverUuid'],
        'sourceSchema': config['sourceSchema'], 'targetSchema': config['targetSchema'],
        'contractSha256': model_sha, 'sqlSha256': catalog['sqlSha256'], 'scope': config['scope']})
    if 'sourceClockPolicy' in prior:
        require(prior['sourceClockPolicy'] == clocks.evidence(config['sourceOffsets'], config.get('legacyClockPolicy')),
                'Readback source clock policy differs from the accepted migration')
    mysql = Mysql(config, output)
    mysql.admitted_server()
    freeze = freeze_evidence(config, identity)
    with mysql.source_lock(config['sourceSchema'], model['sourceTables']):
        source = observed_source(mysql, config, identity, model_sha, model['sourceTables'])
        target = schema_snapshot(mysql, config['targetSchema'], model['expectedTargetTables'])
        _, target_meta = metadata_snapshot(mysql, config['targetSchema'])
        require(source['sourceSnapshotSha256'] == prior['sourceSnapshotSha256']
                and source['sourceMetadataSha256'] == prior['sourceMetadataSha256']
                and target['snapshotSha256'] == prior['targetSnapshotSha256'] and target_meta == prior['targetMetadataSha256']
                and freeze['sha256'] == prior['freezeEvidenceSha256'],
                'Current frozen source/candidate differs from the migration receipt; no cutover is approved')
    result = {'schemaVersion': 1, 'kind': 'doorhandle-compact-cutover-readback', 'status': 'VERIFIED',
              'migrationReceiptSha256': sha_file(receipt_path), 'attempt': prior['attempt'], 'ecs': identity,
              'serverUuid': config['serverUuid'], 'sourceSchema': config['sourceSchema'], 'targetSchema': config['targetSchema'],
              'sourceSnapshotSha256': source['sourceSnapshotSha256'], 'targetSnapshotSha256': target['snapshotSha256'],
              'targetMetadataSha256': target_meta, 'freezeEvidenceSha256': freeze['sha256'], 'verifiedAtUtc': utc_now()}
    write_json(output / 'cutover-readback.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('observe', 'migrate', 'verify'), nargs='?', default='migrate')
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    try:
        config, identity, config_sha = load_config(args.config)
        output = fresh_output(args.output)
        model, model_sha = contract()
        if args.mode == 'migrate':
            result = migrate(config, identity, config_sha, output, model, model_sha)
        elif args.mode == 'observe':
            mysql = Mysql(config, output); mysql.admitted_server()
            freeze_evidence(config, identity)
            with mysql.source_lock(config['sourceSchema'], model['sourceTables']):
                result = observed_source(mysql, config, identity, model_sha, model['sourceTables'])
            write_json(output / 'source-observation.json', result)
        else:
            require(args.receipt is not None, 'Verify requires an explicit previously completed migration receipt')
            result = verify(config, identity, output, args.receipt, model, model_sha)
        print(json.dumps({'kind': result['kind'], 'status': result['status'], 'output': str(output)}))
        return 0
    except BaseException as error:
        # JDBC/client failures may include customer data. Keep original logs private.
        print(json.dumps({'status': 'STOPPED_NO_ACTIVATION', 'errorType': type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
