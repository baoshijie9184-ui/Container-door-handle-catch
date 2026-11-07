#!/usr/bin/env python3
"""Run real candidate business acceptance in this build's disposable ECS stack.

No original application, schema, volume or cloud lifecycle is changed. The local
Jenkins controller supplies a fixed source/jar/image build; all processes and
business assertions execute on the admitted ECS. A missing prerequisite fails
closed, without converting an unexecuted scenario into a successful flag.
"""
import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib


def require(value, message):
    if not value:
        raise ValueError(message)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def sha_file(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


MIB = 1024 ** 2
GIB = 1024 ** 3
RUNTIME_PROFILE = 'bounded-single-ecs-v1'
DISK_FLOOR = 2 * GIB + 256 * MIB
MEMORY_FLOOR = GIB
# Includes short initialization jobs; admission conservatively counts them all.
SERVICE_MEMORY_MIB = {'backend': 1792, 'kafka': 1280, 'mem0': 768, 'chroma': 512,
    'detection-worker': 2048, 'higress': 512, 'redis': 256, 'nginx': 64, 'mcp-runner': 256,
    'mcp-egress': 128, 'model-fixture': 128, 'oss-proxy': 128, 'kafka-init': 256,
    'kafka-storage-init': 64, 'higress-seed': 128, 'higress-config': 128}
MCP_CHILD_MEMORY = 2 * 256 * MIB


def bounded_config(config):
    """Change only this isolated acceptance stack, including actual JVM heaps."""
    value = copy.deepcopy(config)
    require(set(value['services']) <= set(SERVICE_MEMORY_MIB), 'An unbudgeted runtime service was added')
    for name, service in value['services'].items():
        limit = SERVICE_MEMORY_MIB[name] * MIB
        service.update(mem_limit=limit, memswap_limit=limit)
        service['logging'] = {'driver': 'json-file', 'options': {'max-size': '5m', 'max-file': '1'}}
        service.setdefault('labels', {})['io.doorhandle.acceptance-profile'] = RUNTIME_PROFILE
        env = service.setdefault('environment', {})
        if name == 'backend':
            env['JAVA_OPTS'] = '-Xms256m -Xmx1024m -XX:MaxMetaspaceSize=256m -Djava.awt.headless=true'
        if name in ('kafka', 'kafka-init'):
            env['KAFKA_HEAP_OPTS'] = '-Xms128m -Xmx512m' if name == 'kafka' else '-Xms32m -Xmx128m'
        if name == 'kafka':
            # Bounded test retention still retains every scenario/replay event.
            env.update(KAFKA_LOG_SEGMENT_BYTES=str(16 * MIB), KAFKA_LOG_RETENTION_BYTES=str(64 * MIB),
                       KAFKA_LOG_RETENTION_HOURS='24', KAFKA_OFFSETS_TOPIC_NUM_PARTITIONS='3',
                       KAFKA_TRANSACTION_STATE_LOG_NUM_PARTITIONS='1')
    return value


def allocated_bytes(path):
    """Allocated retained bytes, including hardlinks once; never follow links."""
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path and path.is_dir(), 'Resource inventory requires a canonical directory')
    seen, total = set(), 0
    for current, folders, files in os.walk(path, followlinks=False):
        for item in [Path(current), *(Path(current) / name for name in folders + files)]:
            stat = item.lstat(); identity = (stat.st_dev, stat.st_ino)
            if identity not in seen:
                seen.add(identity); total += stat.st_blocks * 512
    return total


def host_probe(directory):
    fs = os.statvfs(directory)
    memory = next(int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines()
                  if line.startswith('MemAvailable:'))
    return {'capturedAtUnix': time.time(), 'diskTotalBytes': fs.f_blocks * fs.f_frsize,
            'diskAvailableBytes': fs.f_bavail * fs.f_frsize, 'memoryAvailableBytes': memory}


def phase_admission(phase, probe, growth_bytes, memory_bytes, measured):
    require(phase in ('runtime-start', 'runtime-backup', 'runtime-restore')
            and type(growth_bytes) is int and growth_bytes > 0 and type(memory_bytes) is int and memory_bytes >= 0
            and isinstance(measured, dict) and measured, 'Runtime phase requires measured inputs and an explicit growth bound')
    result = {'kind': 'doorhandle-bounded-runtime-resource-phase', 'profile': RUNTIME_PROFILE, 'phase': phase,
        'capacityVerdict': 'CONTROLLED_MEASUREMENT', 'productionCapacityVerified': False,
        'growthEnvelopeBytes': growth_bytes, 'memoryAdmissionBytes': memory_bytes,
        'diskFloorBytes': DISK_FLOOR, 'memoryFloorBytes': MEMORY_FLOOR,
        'measuredInputs': measured, 'baselineProbe': probe, 'status': 'FAIL_CLOSED'}
    if probe['diskAvailableBytes'] >= growth_bytes + DISK_FLOOR and probe['memoryAvailableBytes'] >= memory_bytes + MEMORY_FLOOR:
        result['status'] = 'MEASUREMENT_ADMITTED'
    return result


def validate_resource_evidence(summary, raw, context, project):
    """Pure verification shared by remote admission and local byte-only archiving."""
    require(isinstance(summary, dict) and isinstance(raw, bytes) and 0 < len(raw) <= 64 * MIB,
            'Bounded runtime resource evidence is absent or oversized')
    require(all(summary.get(key) == value for key, value in context.items() if key != 'kind')
            and summary.get('kind') == 'doorhandle-bounded-runtime-resources' and summary.get('project') == project
            and summary.get('profile') == RUNTIME_PROFILE and summary.get('capacityVerdict') == 'CONTROLLED_MEASUREMENT'
            and summary.get('productionCapacityVerified') is False
            and summary.get('status') == 'MEASURED_FOR_BOUNDED_SCENARIOS'
            and summary.get('pollIntervalSeconds') == 2 and summary.get('diskFloorBytes') == DISK_FLOOR
            and summary.get('memoryFloorBytes') == MEMORY_FLOOR
            and summary.get('rawProbeFile') == 'checkout/work/runtime-acceptance/resource-probes.jsonl'
            and summary.get('rawProbeSha256') == hashlib.sha256(raw).hexdigest(),
            'Runtime resource evidence differs from this exact bounded attempt')
    def pairs(entries):
        value = {}
        for key, item in entries:
            require(key not in value, 'Duplicate runtime resource evidence key')
            value[key] = item
        return value
    lines = raw.splitlines()
    require(0 < len(lines) <= 250000 and all(0 < len(line) <= MIB for line in lines), 'Invalid resource probe stream bounds')
    samples = [json.loads(line, object_pairs_hook=pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid JSON number'))) for line in lines]
    plans = summary.get('phasePlans', {})
    require(set(plans) == {'runtime-start', 'runtime-backup', 'runtime-restore'}, 'Runtime phase plans are missing')
    for phase, plan in plans.items():
        require(plan == phase_admission(phase, plan['baselineProbe'], plan['growthEnvelopeBytes'],
                    plan['memoryAdmissionBytes'], plan['measuredInputs']) and plan['status'] == 'MEASUREMENT_ADMITTED',
                'Runtime phase was not derived from its measured reserve')
    last, minimum_disk, minimum_memory, containers = None, None, None, {}
    for event in samples:
        require(set(event) == {'probe', 'containers', 'stopReasons'} and event['stopReasons'] == []
                and isinstance(event['containers'], list), 'A failed/partial resource observation cannot pass')
        probe = event['probe']; stamp = probe['capturedAtUnix']
        require(isinstance(stamp, (int, float)) and not isinstance(stamp, bool)
                and (last is None or 0 <= stamp - last <= 2), 'Resource probe interval was not independently bounded')
        last = stamp
        plan = plans.get(probe.get('phase'))
        require(plan is not None, 'Probe belongs to an unknown runtime phase')
        loss = max(0, plan['baselineProbe']['diskAvailableBytes'] - probe['diskAvailableBytes'])
        require(probe.get('diskLossOwnershipProof') is False and probe.get('hostDiskLossUpperBoundBytes') == loss
                and loss <= plan['growthEnvelopeBytes'], 'An exhausted runtime growth envelope was hidden')
        require(type(probe['diskAvailableBytes']) is int and probe['diskAvailableBytes'] >= DISK_FLOOR
                and type(probe['memoryAvailableBytes']) is int and probe['memoryAvailableBytes'] >= MEMORY_FLOOR,
                'Resource pressure was hidden in the raw observation stream')
        minimum_disk = min(minimum_disk or probe['diskAvailableBytes'], probe['diskAvailableBytes'])
        minimum_memory = min(minimum_memory or probe['memoryAvailableBytes'], probe['memoryAvailableBytes'])
        for row in event['containers']:
            cid, service = row['containerId'], row['service']
            require(re.fullmatch(r'[a-f0-9]{64}', cid) and re.fullmatch(r'sha256:[a-f0-9]{64}', row['image'])
                    and service in {*SERVICE_MEMORY_MIB, 'mcp-child', 'owned-helper'}
                    and all(type(row[key]) is int and row[key] >= 0 for key in ('currentBytes', 'peakBytes', 'oom', 'oomKills', 'memoryLimitBytes'))
                    and (0 < row['memoryLimitBytes'] <= 256 * MIB if service == 'owned-helper'
                         else row['memoryLimitBytes'] == (256 * MIB if service == 'mcp-child' else SERVICE_MEMORY_MIB[service] * MIB))
                    and row['oom'] == row['oomKills'] == 0, 'Container resource evidence is incomplete or contains OOM')
            previous = containers.get(cid)
            require(previous is None or (previous['image'] == row['image'] and previous['service'] == service
                    and row['peakBytes'] >= previous['peakBytes']), 'A container resource identity/peak was rewritten')
            containers[cid] = row
    require(summary.get('samples') == len(samples) and summary.get('containers') == containers
            and summary.get('minimumDiskAvailableBytes') == minimum_disk
            and summary.get('minimumMemoryAvailableBytes') == minimum_memory
            and summary.get('latestProbeAtUnix') == last, 'Resource summary disagrees with its actual raw samples')
    observed = {row['service'] for row in containers.values() if row['peakBytes'] > 0}
    required = set(summary.get('requiredDaemonServices', []))
    require(required == set(SERVICE_MEMORY_MIB) - {'kafka-init', 'kafka-storage-init', 'higress-seed', 'higress-config'}
            and required <= observed, 'Some required runtime service peaks were never observed')
    require([row.get('phase') for row in summary.get('phases', [])] == ['runtime-start', 'runtime-backup', 'runtime-restore']
            and all(set(row) == {'phase', 'file', 'sha256'} and re.fullmatch(r'[a-f0-9]{64}', row['sha256'])
                    and row['file'] == 'checkout/work/runtime-acceptance/resource-phase-' + str(index) + '-' + row['phase'] + '.json'
                    for index, row in enumerate(summary['phases'], 1)), 'Runtime phase evidence is incomplete')
    return {'status': 'VERIFIED', 'profile': RUNTIME_PROFILE, 'capacityVerdict': 'CONTROLLED_MEASUREMENT',
            'sampleCount': len(samples), 'productionCapacityVerified': False}


class ResourcePressure(RuntimeError):
    pass


class RuntimeResources:
    """Independent sampling; failures interrupt only this owned controller."""
    def __init__(self, runtime):
        self.runtime = runtime
        self.done = threading.Event(); self.lock = threading.RLock()
        self.thread = None; self.phase = None; self.error = None; self.previous_signal = None
        self.summary = {**runtime.context(), 'kind': 'doorhandle-bounded-runtime-resources',
            'project': runtime.project, 'profile': RUNTIME_PROFILE,
            'capacityVerdict': 'CONTROLLED_MEASUREMENT', 'productionCapacityVerified': False,
            'pollIntervalSeconds': 2, 'diskFloorBytes': DISK_FLOOR, 'memoryFloorBytes': MEMORY_FLOOR,
            'containers': {}, 'phases': [], 'phasePlans': {}, 'samples': 0,
            'requiredDaemonServices': sorted(set(SERVICE_MEMORY_MIB) - {'kafka-init', 'kafka-storage-init', 'higress-seed', 'higress-config'}),
            'rawProbeFile': 'checkout/work/runtime-acceptance/resource-probes.jsonl'}
        self.raw = runtime.directory / 'resource-probes.jsonl'

    def admit(self, phase, growth_bytes, measured, memory_bytes=0):
        with self.lock:
            probe = host_probe(self.runtime.directory)
            plan = phase_admission(phase, probe, growth_bytes, memory_bytes, measured)
            file = self.runtime.directory / ('resource-phase-' + str(len(self.summary['phases']) + 1) + '-' + phase + '.json')
            self.runtime.common.write_json(file, plan)
            self.summary['phases'].append({'phase': phase, 'file': file.relative_to(self.runtime.attempt).as_posix(), 'sha256': sha_file(file)})
            self.summary['phasePlans'][phase] = plan
            require(plan['status'] == 'MEASUREMENT_ADMITTED', 'Measured runtime phase lacks its bounded disk/memory reserve')
            self.phase = plan

    def rows(self):
        ctx = self.runtime
        identifiers = ctx.ops.docker('ps', '-aq', '--no-trunc', '--filter',
            'label=io.doorhandle.rehearsal=' + ctx.project, timeout=0.4).decode().split()
        if ctx.owner.get('mcpPoolId'):
            identifiers += ctx.ops.docker('ps', '-aq', '--no-trunc', '--filter',
                'label=doorhandle.mcp.pool=' + ctx.owner['mcpPoolId'], timeout=0.4).decode().split()
        if not identifiers:
            return []
        require(all(re.fullmatch(r'[a-f0-9]{64}', cid) for cid in identifiers), 'Invalid owned runtime observer inventory')
        inspected = subprocess.run(['docker', 'inspect', *sorted(set(identifiers))], capture_output=True,
                                   timeout=0.4, check=False)
        if inspected.returncode:
            # --rm MCP children may exit between inventory and inspect. Only
            # Docker's exact missing-ID diagnostics are accepted, never a daemon
            # failure or a lost observation of a still-running process.
            missing = inspected.stderr.decode().splitlines()
            require(missing and all(line.removeprefix('Error: No such object: ') in identifiers
                    and line.startswith('Error: No such object: ') for line in missing),
                    'Runtime container inspection failed')
        rows = json.loads(inspected.stdout)
        require(isinstance(rows, list) and all(row['Id'] in identifiers for row in rows), 'Foreign runtime observer response')
        return rows

    def sample(self):
        ctx = self.runtime; probe = host_probe(ctx.directory)
        reasons = []
        if 'latestProbeAtUnix' in self.summary and probe['capturedAtUnix'] - self.summary['latestProbeAtUnix'] > 2:
            reasons.append('PROBE_INTERVAL_EXCEEDED')
        self.summary['latestProbeAtUnix'] = probe['capturedAtUnix']
        if probe['diskAvailableBytes'] < DISK_FLOOR: reasons.append('DISK_FLOOR')
        if probe['memoryAvailableBytes'] < MEMORY_FLOOR: reasons.append('MEMORY_FLOOR')
        if self.phase:
            loss = max(0, self.phase['baselineProbe']['diskAvailableBytes'] - probe['diskAvailableBytes'])
            if loss > self.phase['growthEnvelopeBytes']: reasons.append('PHASE_GROWTH_BOUND')
            probe['phase'] = self.phase['phase']; probe['hostDiskLossUpperBoundBytes'] = loss
            probe['diskLossOwnershipProof'] = False
        containers = []
        # Stop on pressure before any Docker metadata operation can stall.
        if not reasons:
            for row in self.rows():
                labels = row['Config'].get('Labels') or {}; cid = row['Id']
                ordinary = labels.get('io.doorhandle.rehearsal') == ctx.project
                child = (ctx.owner.get('mcpPoolId') and labels.get('doorhandle.mcp.pool') == ctx.owner['mcpPoolId']
                         and labels.get('doorhandle.mcp.managed') == 'true' and row['Image'] == ctx.owner['runtimeMcpImage']
                         and labels.get('doorhandle.mcp.owner') in {str(v['userId']) for v in ctx.accounts.values()})
                require((ordinary or child) and cid not in (ctx.settings['sourceMysqlContainerId'], ctx.owner['mysqlContainerId']),
                        'Resource observer found a foreign container')
                service = labels.get('com.docker.compose.service') or ('mcp-child' if child else 'owned-helper')
                maximum = (256 * MIB if child or service == 'owned-helper' else SERVICE_MEMORY_MIB[service] * MIB)
                actual_limit = row['HostConfig']['Memory']
                memory = {'currentBytes': 0, 'peakBytes': 0, 'oom': 0, 'oomKills': 0}
                if row['State']['Running']:
                    require((actual_limit == maximum if service != 'owned-helper' else 0 < actual_limit <= maximum)
                            and row['HostConfig']['MemorySwap'] == actual_limit,
                            'Actual runtime cgroup differs from the bounded acceptance profile')
                    try:
                        cg = Path('/proc') / str(row['State']['Pid']) / 'cgroup'
                        unified = [line[3:] for line in cg.read_text().splitlines() if line.startswith('0::/')]
                        require(len(unified) == 1 and '..' not in Path(unified[0]).parts
                                and unified[0].endswith(('/docker-' + cid + '.scope', '/docker/' + cid)),
                                'Runtime PID does not belong to its exact cgroup v2 container')
                        base = Path('/sys/fs/cgroup') / unified[0].lstrip('/')
                        require(int((base / 'memory.max').read_text()) == actual_limit
                                and int((base / 'memory.swap.max').read_text()) == 0,
                                'The observed kernel cgroup/swap limit differs from the runtime profile')
                        events = dict(line.split() for line in (base / 'memory.events').read_text().splitlines())
                        memory = {'currentBytes': int((base / 'memory.current').read_text()),
                            'peakBytes': int((base / 'memory.peak').read_text()),
                            'oom': int(events.get('oom', 0)), 'oomKills': int(events.get('oom_kill', 0))}
                    except FileNotFoundError:
                        current = json.loads(ctx.ops.docker('inspect', cid, timeout=0.4))[0]
                        require(current['Id'] == cid and current['Image'] == row['Image'] and not current['State']['Running'],
                                'A running runtime process lost its resource observation')
                        row = current  # An intentional restart can remove its old cgroup.
                if row['State'].get('OOMKilled') or memory['oom'] or memory['oomKills']: reasons.append('OWNED_OOM')
                previous = self.summary['containers'].get(cid, {})
                item = {'service': service, 'containerId': cid, 'image': row['Image'], 'memoryLimitBytes': actual_limit,
                    **memory, 'peakBytes': max(memory['peakBytes'], previous.get('peakBytes', 0)),
                    'oom': max(memory['oom'], previous.get('oom', 0)),
                    'oomKills': max(memory['oomKills'], previous.get('oomKills', 0)),
                    'running': row['State']['Running'], 'exitCode': row['State']['ExitCode']}
                self.summary['containers'][cid] = item; containers.append(item)
        self.summary['samples'] += 1
        for key in ('diskAvailableBytes', 'memoryAvailableBytes'):
            name = 'minimum' + key[0].upper() + key[1:]
            self.summary[name] = min(probe[key], self.summary.get(name, probe[key]))
        entry = json.dumps({'probe': probe, 'containers': containers, 'stopReasons': reasons}) + '\n'
        require((self.raw.stat().st_size if self.raw.exists() else 0) + len(entry.encode('utf8')) <= 64 * MIB,
                'Owned resource evidence reached its retained byte bound')
        with self.raw.open('a', encoding='utf8') as stream:
            os.chmod(self.raw, 0o600)
            stream.write(entry); stream.flush()
        require(not reasons, 'Owned runtime resource boundary reached: ' + ','.join(reasons))

    def start(self):
        require(self.phase is not None and self.thread is None, 'Runtime resource phase must be admitted first')
        try:
            self.sample()
        except BaseException as error:
            self.error = type(error).__name__
            raise
        self.previous_signal = signal.getsignal(signal.SIGUSR1)
        signal.signal(signal.SIGUSR1, lambda *_: (_ for _ in ()).throw(ResourcePressure('Owned runtime resource boundary reached')))
        def observe():
            while not self.done.wait(0.5):
                started = time.monotonic()
                try:
                    with self.lock: self.sample()
                    require(time.monotonic() - started <= 2, 'Runtime resource probe exceeded its bounded interval')
                except BaseException as error:
                    self.error = type(error).__name__; self.summary['status'] = 'FAILED_OR_UNKNOWN'
                    self.summary['failureType'] = self.error
                    self.done.set()
                    # Main's existing failure path freezes creators and performs
                    # independently verified owned cleanup. Never signal a DB or
                    # original deployment, and never continue a failed scenario.
                    os.kill(os.getpid(), signal.SIGUSR1)
        self.thread = threading.Thread(target=observe, name='owned-runtime-resources', daemon=True); self.thread.start()

    def finish(self):
        file = self.runtime.directory / 'resource-summary.json'
        if self.thread is None and file.exists():
            previous, _ = self.runtime.guard.read_private(file)
            require(all(previous.get(key) == value for key, value in self.runtime.context().items() if key != 'kind'),
                    'Existing resource evidence belongs to another runtime')
            return {'file': file.relative_to(self.runtime.attempt).as_posix(), 'sha256': sha_file(file)}
        self.done.set()
        if self.thread:
            self.thread.join(timeout=5)
            require(not self.thread.is_alive(), 'Owned resource observer did not stop')
        if self.previous_signal is not None: signal.signal(signal.SIGUSR1, self.previous_signal)
        self.summary['status'] = ('FAILED_OR_UNKNOWN' if self.error else
            'MEASURED_FOR_BOUNDED_SCENARIOS' if self.summary['samples'] else 'NOT_MEASURED')
        self.summary['rawProbeSha256'] = sha_file(self.raw) if self.raw.exists() else None
        self.runtime.common.write_json(file, self.summary)
        return {'file': file.relative_to(self.runtime.attempt).as_posix(), 'sha256': sha_file(file)}


class Database:
    def __init__(self, mysql, schema, runtime):
        self.mysql, self.schema, self.runtime, self.sequence = mysql, schema, runtime, 0
        self.lock = threading.RLock()
    def literal(self, value):
        return self.runtime.literal(value)
    def execute(self, sql):
        with self.lock:
            self.sequence += 1
            return self.mysql.script(sql, database=self.schema, label='runtime-' + str(self.sequence)).decode('utf8')
    def query(self, sql):
        with self.lock:
            return self.mysql.json_rows(sql, database=self.schema)
    def one(self, sql):
        with self.lock:
            return self.mysql.single(sql, database=self.schema)


class Runtime:
    def __init__(self, args):
        require(sys.platform == 'linux', 'Runtime acceptance is ECS-only')
        self.args = args
        source = Path(args.root) / 'releases' / args.tag
        self.source = source.resolve(strict=True)
        require(self.source == source and re.fullmatch(r'ci-[1-9][0-9]*-[a-f0-9]{12}', args.tag)
                and re.fullmatch(r'[a-f0-9]{40}', args.commit) and args.tag.endswith('-' + args.commit[:12])
                and re.fullmatch(r'[a-f0-9]{64}', args.source_sha256), 'Fixed candidate source identity is required')
        self.cutover = module('runtime_cutover_contract', source / 'script/docker/compact-cutover.py')
        self.guard = module('runtime_schema_contract', source / 'script/docker/compact-schema-guard.py')
        self.ops = module('runtime_owned_ops', source / 'script/docker/monolith-ops.py')
        self.rehearsal = module('runtime_rehearsal_methods', source / 'script/docker/application-rehearsal.py')
        self.http = module('runtime_http_scenarios', source / 'script/docker/compact-runtime-scenarios.py')
        self.recovery = module('runtime_recovery_scenario', source / 'script/docker/compact-runtime-recovery.py')
        self.native = module('runtime_legacy_candidate', source / 'script/jenkins/prepare-legacy-candidate.py')
        self.worker_fence = module('runtime_worker_unknown_result', source / 'script/docker/compact-runtime-worker-fence.py')
        self.common = module('runtime_schema_queries', source / 'script/docker/assignment-compat.py')
        self.acceptance = module('runtime_profile_contract', source / 'script/jenkins/compact-acceptance.py')
        self.profile, self.profile_sha = self.acceptance.profile(source)
        self.identity = self.guard.ecs_identity({'instanceId': args.instance_id, 'machineId': args.machine_id})
        self.root, self.runtime = self.cutover.canonical(args.root), self.cutover.canonical(args.runtime)
        self.cutover.fixed_source(self.root / 'inbox' / args.tag / 'source.tar.gz', source, args.source_sha256, args.commit)
        self.settings, settings_sha = self.guard.read_private(self.cutover.canonical(args.settings))
        settings_fields = {'version', 'sourceMysqlContainerId', 'sourceSchema', 'sourceOffsets', 'java'}
        require(settings_fields <= set(self.settings) <= settings_fields | {'legacyClockPolicy'}
                and self.settings.get('version') == 1, 'Reuse this build\'s exact private fixture settings')
        clocks = module('runtime_clock_policy', source / 'script/schema/compact_clock_policy.py')
        clocks.validate(self.settings['sourceOffsets'], self.settings.get('legacyClockPolicy'))
        self.attempt = self.cutover.canonical(self.root / 'verification' / args.tag)
        self.checkout = self.cutover.canonical(self.attempt / 'checkout')
        self.directory = self.checkout / 'work/runtime-acceptance'
        self.owner_file = self.directory / 'owner.json'
        self.public_file = self.attempt / 'runtime-acceptance.json'
        self.build, self.build_sha = self.guard.read_private(source / 'candidate-build.json')
        require(all(self.build.get(key) == expected for key, expected in {
            'schemaVersion': 1, 'kind': 'doorhandle-compact-candidate-build', 'status': 'BUILT',
            'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256, 'ecs': self.identity}.items()),
            'Runtime must use the exact already-built candidate')
        require(self.build.get('settingsSha256') == settings_sha,
                'Runtime settings differ from the reviewed candidate/fixture input')
        self.images = self.build['images']
        for service in ('backend', 'detection-worker'):
            self.guard.compact_image(self.images[service], self.common)
        self.owner = None
        if self.owner_file.exists():
            self.owner, _ = self.guard.read_private(self.owner_file)
            require(all(self.owner.get(key) == expected for key, expected in self.context().items()),
                    'Runtime resources belong to another build, profile or ECS')
            self.project, self.token = self.owner['project'], self.owner['token']
            self.config = self.guard.read_private(self.directory / 'compose.json')[0] if (self.directory / 'compose.json').exists() else None
        else:
            self.token = secrets.token_hex(6); self.project = 'doorhandle-rehearsal-' + self.token
        self.report = {'checks': [], 'project': self.project}
        self.clients = {}
        self.resources = RuntimeResources(self)
        if self.owner:
            self.accounts = self.guard.read_private(self.directory / 'users.json')[0] if (self.directory / 'users.json').exists() else {}

    def context(self):
        return {'schemaVersion': 1, 'kind': 'doorhandle-compact-runtime-acceptance', 'release': self.args.tag,
                'commit': self.args.commit, 'sourceSha256': self.args.source_sha256, 'identity': self.identity,
                'acceptanceProfileSha256': self.profile_sha, 'candidateBuildSha256': self.build_sha}

    def save(self, phase=None):
        if phase:
            self.owner['phase'] = phase
        self.owner['updatedAtUtc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        self.common.write_json(self.owner_file, self.owner)

    def record(self, scenario, observations):
        required = {item['id'] for item in self.profile['runtimeAcceptance']['scenarios']}
        require(scenario in required and scenario not in self.owner['scenarios'] and isinstance(observations, dict)
                and observations, 'Actual runtime evidence has an invalid or repeated scenario')
        path = self.directory / ('scenario-' + scenario + '.json')
        value = {**self.context(), 'scenario': scenario, 'project': self.project, 'status': 'PASS',
                 'observedAtUtc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'observations': observations}
        self.common.write_json(path, value)
        result = {'file': path.relative_to(self.attempt).as_posix(), 'sha256': sha_file(path)}
        self.owner['scenarios'][scenario] = result; self.save()
        return result

    def check(self, name, condition):
        require(condition, name); self.report['checks'].append(name)

    def row(self, service):
        ids = self.ops.docker('ps', '-aq', '--no-trunc', '--filter', 'label=com.docker.compose.project=' + self.project,
            '--filter', 'label=com.docker.compose.service=' + service).decode().split()
        require(len(ids) == 1, 'Runtime service generation is missing or ambiguous')
        row = json.loads(self.ops.docker('inspect', ids[0]))[0]
        require(row['Id'] != self.settings['sourceMysqlContainerId']
                and row['Config']['Labels'].get('io.doorhandle.rehearsal') == self.project,
                'A runtime container does not belong to this attempt')
        return row

    def dc(self, *args, config=None, **kwargs):
        value = self.config if config is None else config
        self.validate_config(value)
        file = self.directory / ('compose.json' if config is None else 'oneoff-compose.json')
        if config is not None:
            self.common.write_json(file, config)
        return self.ops.docker('compose', '--project-name', self.project, '-f', str(file), *args, **kwargs)

    def client(self, name):
        require(name in self.accounts, 'Unknown runtime account')
        if name not in self.clients:
            self.clients[name] = self.rehearsal.Client(self.owner['port'])
            account = self.accounts[name]
            self.http.request(self.clients[name], 'POST', '/api/auth/login',
                              {'username': account['username'], 'password': account['password']})
        return self.clients[name]

    def request(self, name, method, path, value=None, *, headers=None):
        client = self.client(name)
        body = None if value is None else json.dumps(value, ensure_ascii=False).encode('utf8')
        message = urllib.request.Request(client.base + path, data=body, method=method, headers={
            'Content-Type': 'application/json', 'X-Agent-Action': 'workbench', 'X-Model-Action': 'update',
            'X-Skill-Action': 'update', 'X-MCP-Action': 'update', 'Sec-Fetch-Site': 'same-origin', **(headers or {})})
        with client.opener.open(message, timeout=180) as response:
            raw = response.read(16 * 1024 * 1024 + 1)
            require(len(raw) <= 16 * 1024 * 1024, 'Runtime response exceeds its bounded evidence budget')
            if 'application/json' not in response.headers.get('Content-Type', ''):
                return raw
            result = json.loads(raw)
            if isinstance(result, dict) and 'code' in result:
                require(result['code'] == 200, 'Business operation did not succeed')
                return result.get('data')
            return result

    def fixture(self, method, path, body=None):
        require(path in ('/__fixture/arm', '/__fixture/state'), 'Unsupported local model control')
        script = """import json,os,sys,urllib.request
v=json.load(sys.stdin); r=urllib.request.Request('http://127.0.0.1:8099'+v['path'],method=v['method'],data=None if v['body'] is None else json.dumps(v['body']).encode(),headers={'Content-Type':'application/json','X-Runtime-Token':os.environ['RUNTIME_FIXTURE_TOKEN']})
with urllib.request.urlopen(r,timeout=10) as s: print(s.read().decode())
"""
        return json.loads(self.ops.docker('exec', '-i', self.row('model-fixture')['Id'], 'python', '-B', '-c', script,
            data=json.dumps({'method': method, 'path': path, 'body': body}).encode(), timeout=15))

    def validate_config(self, config):
        self.rehearsal.validate_isolation(config, self.project)
        require('mysql' not in config['services'], 'The runtime may not recreate or relabel the owned fixture MySQL')
        for name, spec in config['services'].items():
            require(spec.get('restart') == 'no' and spec.get('labels', {}).get('io.doorhandle.rehearsal') == self.project,
                    'Runtime process ownership or restart policy differs')
            if name in ('backend', 'mem0', 'model-fixture'):
                require(all(config['networks'][network].get('internal') is True for network in spec.get('networks', {})),
                        'Model-capable services must not reach the external network')
        worker = config['services']['detection-worker']['environment']
        backend = config['services']['backend']['environment']
        require(backend['DB_URL'].startswith('jdbc:mysql://mysql:' + str(self.owner['mysqlPort']) + '/' + self.owner['targetSchema'] + '?')
                and worker['DETECTION_RECEIPT_DB_HOST'] == 'mysql' and str(worker['DETECTION_RECEIPT_DB_PORT']) == str(self.owner['mysqlPort'])
                and worker['DETECTION_RECEIPT_DB_DATABASE'] == self.owner['targetSchema'],
                'Runtime application/worker must use the actual admitted fixture endpoint')
        for name in ('backend', 'mem0'):
            env = config['services'][name]['environment']
            for key in ('OPENAI_API_KEY', 'DEEPSEEK_API_KEY', 'DASHSCOPE_API_KEY', 'EMBEDDING_API_KEY'):
                require(not env.get(key) or env[key] == 'runtime-fixture', 'A model-capable process retained provider credentials')

    def open_database(self):
        preparer = module('runtime_owned_fixtures', self.source / 'script/jenkins/prepare-compact-fixtures.py')
        fixture = preparer.Preparation(self.args); fixture.load(); node = fixture.inspect_owned()
        require(node['State']['Running'] and node['Id'] != self.settings['sourceMysqlContainerId'],
                'The owned disposable fixture MySQL is not running')
        self.fixture_owner = fixture.journal
        sidecar_path = self.checkout / 'work/compact-fixtures/runtime-migration.json'
        sidecar, _ = self.guard.read_private(sidecar_path)
        require(sidecar.get('kind') == 'doorhandle-runtime-migration-input' and sidecar.get('version') == 1
                and sidecar.get('ecs') == self.identity and sidecar.get('serverUuid') == fixture.journal['serverUuid'],
                'A live verified whole-migration input for this build is required')
        receipt_path = self.cutover.canonical(sidecar['migrationReceiptFile'])
        require(receipt_path.is_relative_to(self.checkout / 'work') and sha_file(receipt_path) == sidecar['migrationReceiptSha256'],
                'Actual migration receipt no longer matches the private runtime input')
        reviewed_path = self.cutover.canonical(sidecar['reviewedConfigFile'])
        reviewed, reviewed_sha = self.guard.read_private(reviewed_path)
        require(reviewed_path.is_relative_to(self.checkout / 'work') and reviewed_sha == sidecar['reviewedConfigSha256']
                and all(reviewed.get(key) == value for key, value in {
                    'scope': 'ecs-disposable-migration', 'serverUuid': fixture.journal['serverUuid'],
                    'sourceSchema': fixture.journal['sourceClone'], 'targetSchema': sidecar['targetSchema'],
                    'dataDirectory': fixture.journal['dataDirectory']}.items())
                and reviewed.get('connection', {}).get('host') == '127.0.0.1'
                and reviewed.get('connection', {}).get('port') == fixture.journal['port']
                and reviewed.get('client', {}).get('containerId') == node['Id'],
                'The reviewed migration configuration is not bound to this exact owned fixture')
        require(reviewed.get('sourceOffsets') == self.settings['sourceOffsets']
                and reviewed.get('legacyClockPolicy') == self.settings.get('legacyClockPolicy'),
                'Runtime source clock preservation policy differs from its accepted fixture settings')
        sys.path.insert(0, str(self.source / 'script/schema'))
        self.migration = module('runtime_migration_primitives', self.source / 'script/schema/compact_migration_runtime.py')
        _, catalog = self.guard.source_catalog(self.source)
        receipt = self.migration.validate_migration_receipt(receipt_path, {'ecs': self.identity,
            'scope': 'ecs-disposable-migration', 'serverUuid': fixture.journal['serverUuid'], 'targetSchema': sidecar['targetSchema'],
            'sourceSchema': fixture.journal['sourceClone'], 'configSha256': reviewed_sha,
            'contractSha256': catalog['contractSha256'], 'sqlSha256': catalog['sqlSha256']})
        summary = json.loads((self.checkout / 'work/ci-evidence/migration.json').read_text(encoding='utf8'))
        require(summary.get('migrationReceiptSha256') == sidecar['migrationReceiptSha256']
                and summary.get('sourceSnapshotSha256') == receipt['sourceSnapshotSha256']
                and summary.get('targetSnapshotSha256') == receipt['targetSnapshotSha256']
                and summary.get('sourceRecoveryReceiptSha256') == receipt['recovery']['source']['sha256']
                and summary.get('targetRecoveryReceiptSha256') == receipt['recovery']['target']['sha256'],
                'Runtime migration differs from the one actually accepted by the passing matrix')
        require(self.owner is None or self.owner['mysqlContainerId'] == node['Id'], 'Runtime fixture server changed')
        target = sidecar['targetSchema'] if self.owner is None else self.owner['targetSchema']
        output = self.directory / ('mysql-control-' + uuid.uuid4().hex[:10]); output.mkdir(mode=0o700)
        (output / 'private').mkdir(mode=0o700)
        config = {'scope': 'ecs-disposable-migration', 'serverUuid': fixture.journal['serverUuid'],
            'dataDirectory': fixture.journal['dataDirectory'], 'connection': {'host': '127.0.0.1',
                'port': fixture.journal['port'], 'username': 'root', 'password': fixture.journal['rootPassword']},
            'client': {'kind': 'docker', 'executable': str(fixture.docker), 'containerId': node['Id']}}
        mysql = self.migration.Mysql(config, output); mysql.admitted_server()
        self.db = Database(mysql, target, self.migration); self.mysql_row = dict(node, _doorhandle_database=target)
        if self.owner is None:
            actual = self.guard.inspect_database(self.mysql_row, self.source, require_quiescent=True)
            require(actual['metadataSha256'] == receipt['targetMetadataSha256']
                    and self.migration.schema_snapshot(mysql, target, receipt['targetSnapshot']['tables'])['snapshotSha256']
                        == receipt['targetSnapshotSha256'], 'Migrated target changed before runtime admission')
            pending = self.db.one("SELECT JSON_OBJECT('n',COUNT(*)) FROM workflow_instance WHERE "
                "(kind IN ('DETECTION_CREATION','DETECTION_DISPATCH','REPORT_DELIVERY','SKILL_DOWNLOAD') "
                "AND status IN ('QUEUED','READY','RUNNING','PENDING','SENDING','RETRY')); ")
            require(pending['n'] == 0, 'Copied executable work must be reconciled before starting an isolated runtime')
        return node, target, receipt_path, receipt

    def create_dml_accounts(self, schema):
        accounts = {}
        for role in ('app', 'worker'):
            user, secret = 'rt_' + role + '_' + secrets.token_hex(5), secrets.token_hex(32)
            self.db.execute("CREATE USER '" + user + "'@'%' IDENTIFIED BY '" + secret + "'; GRANT SELECT,INSERT,UPDATE,DELETE ON `"
                + schema + "`.* TO '" + user + "'@'%';")
            accounts[role] = {'username': user, 'password': secret}
        self.common.write_json(self.directory / ('accounts-' + schema + '.json'), accounts)
        return accounts

    def source_observation(self):
        ids = self.ops.docker('ps', '-aq', '--no-trunc', '--filter', 'label=com.docker.compose.project=doorhandlecatch-monolith').decode().split()
        require(ids and self.settings['sourceMysqlContainerId'] in ids, 'Original deployment identity is unavailable')
        result = []
        for row in json.loads(self.ops.docker('inspect', *sorted(ids))):
            require(row['Config']['Labels'].get('com.docker.compose.project') == 'doorhandlecatch-monolith', 'Original deployment inventory changed')
            immutable = {key: row[key] for key in ('Config', 'HostConfig', 'Mounts')}
            result.append({'id': row['Id'], 'image': row['Image'], 'configurationSha256': self.migration.sha_json(immutable),
                'running': row['State']['Running'], 'restarting': row['State'].get('Restarting'),
                'startedAt': row['State']['StartedAt'], 'pid': row['State']['Pid']})
        node = json.loads(self.ops.docker('inspect', self.settings['sourceMysqlContainerId']))[0]
        observed = json.loads(self.common.db(node, "SELECT JSON_OBJECT('serverUuid',@@server_uuid,'schema',DATABASE(),"
            "'tableCount',(SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE'));"))
        require(observed['schema'] == self.settings['sourceSchema'] and observed['tableCount'] == 131,
                'The actual original source no longer matches its admitted 131-table deployment')
        return {'containers': sorted(result, key=lambda row: row['id']), 'database': observed}

    def prepare(self):
        require(self.owner is None and not self.directory.exists() and not self.public_file.exists(),
                'Use a fresh runtime acceptance attempt; unknown results are never replayed')
        verification_sha = self.cutover.admitted_verification(self.root, self.args.tag, self.args.commit,
            self.args.source_sha256, self.identity, self.guard)
        require(verification_sha == self.build['verificationReceiptSha256'], 'Candidate and passing matrix use different attempts')
        self.directory.mkdir(mode=0o700)
        node, schema, receipt_file, receipt = self.open_database()
        with socket.socket() as available:
            available.bind(('127.0.0.1', 0)); port = available.getsockname()[1]
        self.owner = {**self.context(), 'phase': 'PREPARING', 'token': self.token, 'project': self.project,
            'port': port, 'mysqlContainerId': node['Id'], 'mysqlPort': self.fixture_owner['port'],
            'serverUuid': self.fixture_owner['serverUuid'], 'targetSchema': schema,
            'migrationReceiptFile': str(receipt_file), 'migrationReceiptSha256': sha_file(receipt_file),
            'initialTargetSnapshotSha256': receipt['targetSnapshotSha256'], 'scenarios': {}, 'objects': [],
            'sourceBefore': self.source_observation()}
        self.save()
        self.legacy_candidate, self.legacy_candidate_sha, self.legacy_work = self.native.admit_runtime(self)
        self.owner['legacyCandidateSha256'] = self.legacy_candidate_sha; self.save()
        self.accounts = self.http.seed_owned_users(self.db, schema, self.token)
        self.common.write_json(self.directory / 'users.json', self.accounts)
        runtime_accounts = self.create_dml_accounts(schema)
        self.master_key, self.key_reference = self.prepare_key()
        self.owner['modelBaseUrls'] = self.model_routes()
        self.config = self.build_config(schema, runtime_accounts)
        self.common.write_json(self.directory / 'compose.json', self.config)
        self.save('PREPARED')

    def prepare_key(self):
        secret = module('runtime_governed_secret', self.source / 'script/docker/model-secrets.py')
        setting = secret.load_settings(self.root, self.runtime)
        count = self.db.one("SELECT JSON_OBJECT('n',COUNT(*)) FROM llm_configuration;")['n']
        if count:
            require(setting, 'Existing encrypted model history requires its real matching external key and recovery proof')
            require(secret.status(self.root, self.runtime).get('healthy') is True,
                    'The existing external key must already have its independently verified recovery proof')
            proof = secret.backup_key(self.root, self.runtime)
            require(proof.get('decryptionVerified') is True, 'Existing model key lacks its signed verified restore proof')
            raw = self.cutover.canonical(setting['masterKeyFile']).read_bytes()
            self.owner['keyMode'] = 'VERIFIED_EXISTING_POLICY'; self.owner['keyProof'] = proof
            require(len(base64.b64decode(raw.strip(), validate=True)) == 32, 'Existing key is not the matched 256-bit model key')
            return raw, self.cutover.canonical(setting['masterKeyFile'])
        raw = base64.b64encode(secrets.token_bytes(32)) + b'\n'
        reference = self.directory / 'fixture-master-key'
        with reference.open('xb') as stream:
            os.chmod(reference, 0o600); stream.write(raw)
        self.owner['keyMode'] = 'OWNED_FIXTURE_KEY'
        return raw, reference

    def build_config(self, schema, credentials):
        environment = dict(os.environ, APP_IMAGE_TAG=self.args.tag, DOORHANDLE_ENV_FILE=str(self.runtime / 'deploy/cloud.env'),
                           DETECTION_BUILD_CONTEXT=str(self.source / 'work/compact-worker-build'))
        command = ['compose', '--project-name', 'doorhandlecatch-monolith', '--env-file', str(self.runtime / 'deploy/cloud.env')]
        for name in ('compose.monolith.yml', 'compose.cloud.yml', 'compose.detection.yml', 'compose.ai-gateway.yml'):
            command += ['-f', str(self.source / name)]
        config = json.loads(self.ops.docker(*command, 'config', '--format', 'json', env=environment))
        # Policy was verified above; this runtime uses a dedicated key volume,
        # never a writable mount or copied production key file in a backup.
        config.pop('secrets', None)
        for spec in config['services'].values():
            spec.pop('secrets', None)
        config = self.rehearsal.isolated_config(config, self.project, self.owner['port'], self.images, schema)
        require(all(name in config['services'] for name in ('mcp-runner', 'higress-config', 'higress', 'mcp-egress')),
                'The fixed-source gateway overlay is required for actual private MCP acceptance')
        runner = self.build_mcp_image(config['services']['mcp-runner']['image'])
        config['services']['mcp-runner']['image'] = runner
        config['services']['higress-config']['image'] = runner
        config['services']['backend']['environment']['AGENT_MCP_GATEWAY_IMAGE'] = runner
        config['services']['mcp-runner']['environment'].update(MCP_FETCH_IMAGE=runner, MCP_CONTROLLER_PROJECT=self.project)
        # A missing real gateway/proxy prerequisite is a failed scenario, never
        # replaced with a fake MCP row or a production-labeled controller.
        config['services'].pop('mysql')
        for spec in config['services'].values():
            (spec.get('depends_on') or {}).pop('mysql', None)
        for spec in config['networks'].values():
            spec['internal'] = True
        config['networks']['worker-egress'] = {'name': self.project + '-worker-egress', 'driver': 'bridge',
            'internal': False, 'labels': {'io.doorhandle.rehearsal': self.project}}
        # Only the worker and the existing restricted MCP egress proxy receive
        # external connectivity. Model-capable services stay on internal nets.
        config['services']['detection-worker']['networks'] = {'doorhandle-network': {}, 'worker-egress': {}}
        if 'mcp-egress' in config['networks']:
            config['networks']['mcp-egress']['internal'] = False
        app, worker = credentials['app'], credentials['worker']
        for name, spec in config['services'].items():
            env = spec.setdefault('environment', {})
            for key in ('OPENAI_API_KEY', 'DEEPSEEK_API_KEY', 'DASHSCOPE_API_KEY', 'EMBEDDING_API_KEY'):
                if key in env:
                    env[key] = 'runtime-fixture'
            if name == 'backend':
                env.update(DB_URL=f"jdbc:mysql://mysql:{self.owner['mysqlPort']}/{schema}?sslMode=DISABLED&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai",
                    DB_USERNAME=app['username'], DB_PASSWORD=app['password'], APP_BUSINESS_SEED_ENABLED='false',
                    AGENTSCOPE_AI_ENABLED='true', AGENTSCOPE_AI_MODEL='deepseek:runtime-scripted', AGENTSCOPE_AI_EMIT_TOKEN_USAGE='true',
                    AGENT_MODEL_CONFIG_ENABLED='true', APP_MODEL_BUDGET_ENABLED='true', AGENT_WORKBENCH_ENABLED='true',
                    AGENT_CONVERSATION_CONTROL_ENABLED='true', APP_REPORT_EVENTS_ENABLED='true',
                    APP_REPORT_EVENTS_CONSUMER_GROUP='runtime-report-' + self.token, APP_KAFKA_ENABLED='true',
                    APP_KAFKA_CONSUMER_GROUP='runtime-detection-result-' + self.token,
                    OPERATIONS_AUDIT_ENABLED='true', OPERATIONS_FILE_DELIVERY_AUDIT_ENABLED='true',
                    AGENT_RUN_JOURNAL_ENABLED='true', AGENT_DURABLE_CONTEXT_ENABLED='true', AGENT_ACTION_CONFIRMATION_ENABLED='true',
                    AGENT_LOCAL_MCP_ENABLED='true', AGENT_MCP_DURABLE_INSTALL_ENABLED='true', AGENT_MCP_LIFECYCLE_ENABLED='true',
                    AGENT_MCP_EXECUTION_RECEIPTS_ENABLED='true', AGENT_MCP_INSTALL_RECONCILIATION_ENABLED='true',
                    AGENT_MCP_SHARED_IMAGE_CLEANUP_ENABLED='false', AGENT_SKILL_EVOLUTION_ENABLED='true',
                    DETECTION_EXECUTION_COMMANDS_ENABLED='true', APP_DETECTION_WORKER_ENABLED='true',
                    APP_DETECTION_WORKER_CONSUMER_GROUP='runtime-' + self.token,
                    APP_REDIS_ENABLED='true', CHAT_ASSISTANT_RAG_ENABLED='true', AGENT_MODEL_FALLBACK_ENABLED='false',
                    CHAT_ASSISTANT_RAG_QUERY_REWRITE_ENABLED='false', CHAT_ASSISTANT_RAG_RERANK_ENABLED='false',
                    AGENT_MODEL_GATEWAY_BASE_URL='http://model-fixture:8099', AGENT_MODEL_PROXY_URL='', DEEPSEEK_MODEL='runtime-scripted', MEM0_LLM_MODEL='deepseek:runtime-scripted',
                    DEEPSEEK_API_KEY='runtime-fixture', DASHSCOPE_API_KEY='runtime-fixture', OPENAI_API_KEY='runtime-fixture',
                    DEEPSEEK_BASE_URL='http://model-fixture:8099/v1', DASHSCOPE_BASE_URL='http://model-fixture:8099/v1',
                    AGENT_RESPONSES_BASE_URL='http://model-fixture:8099/v1', MODEL_CONFIG_MASTER_KEY_FILE='/run/secrets/model_config_master_key')
                env.update(ALIYUN_OSS_ENDPOINT='http://oss-proxy:9000', ALIYUN_OSS_BASEPREFIX='runtime-acceptance/' + self.token)
            if name == 'mem0':
                env.update(DASHSCOPE_API_KEY='runtime-fixture', EMBEDDING_API_KEY='runtime-fixture',
                    EMBEDDING_PROFILE='explicit-openai-compatible',
                    DASHSCOPE_BASE_URL='http://model-fixture:8099/v1', EMBEDDING_BASE_URL='http://model-fixture:8099/v1',
                    MEM0_LLM_MODEL='runtime-scripted', MODEL_CONFIG_ENABLED='true',
                    MODEL_CONFIG_MASTER_KEY_FILE='/run/secrets/model_config_master_key', MEM0_LIFECYCLE_CLEANUP_ENABLED='false',
                    MEM0_MODEL_GATEWAY_BASE_URL='http://model-fixture:8099')
                env.update(DOORHANDLE_RUNTIME_ACCEPTANCE='true', DOORHANDLE_RUNTIME_PROJECT=self.project,
                           MEM0_RUNTIME_TEST_COLLECTION='doorhandle_runtime_test_' + self.token,
                           MEM0_DUPLICATE_REVIEW_ENABLED='false')
                # The encrypted memory candidate keeps its original endpoint;
                # its new synthetic key is applied by the public publish API.
                # This process has no external network, and infer=false never
                # calls the LLM. Embeddings always use the local fixture.
                env['DEEPSEEK_BASE_URL'] = self.owner['modelBaseUrls']['deepseek']
                env['DASHSCOPE_BASE_URL'] = self.owner['modelBaseUrls']['dashscope']
            if name == 'detection-worker':
                env.update(DETECTION_RECEIPT_DB_HOST='mysql', DETECTION_RECEIPT_DB_PORT=str(self.owner['mysqlPort']),
                    DETECTION_RECEIPT_DB_DATABASE=schema, DETECTION_RECEIPT_DB_USER=worker['username'],
                    DETECTION_RECEIPT_DB_PASSWORD=worker['password'], DETECTION_WORKER_RECEIPTS_ENABLED='true',
                    KAFKA_CONSUMER_GROUP='runtime-' + self.token)
        config['volumes']['runtime-model-key'] = {'name': self.project + '_runtime-model-key',
                                                 'labels': {'io.doorhandle.rehearsal': self.project}}
        for name in ('backend', 'mem0'):
            config['services'][name].setdefault('volumes', []).append({'type': 'volume', 'source': 'runtime-model-key',
                                                                      'target': '/run/secrets', 'read_only': True})
        rag_manifest = self.native.read(self.legacy_work / 'rag-preservation-manifest.json')
        config['volumes']['runtime-rag-preservation'] = {'name': self.project + '_runtime-rag-preservation',
            'labels': {'io.doorhandle.rehearsal': self.project}}
        config['services']['backend']['volumes'].append({'type': 'volume', 'source': 'runtime-rag-preservation',
                                                       'target': '/run/doorhandle-rag', 'read_only': True})
        config['services']['backend']['environment'].update(
            CHAT_ASSISTANT_RAG_STARTUP_MODE='PRESERVE_EXISTING',
            CHAT_ASSISTANT_RAG_PRESERVATION_MANIFEST='/run/doorhandle-rag/preservation.json',
            CHAT_ASSISTANT_RAG_PRESERVATION_MANIFEST_SHA256=self.legacy_candidate['ragManifestSha256'],
            CHAT_ASSISTANT_RAG_PRESERVATION_COMMIT=self.args.commit,
            CHAT_ASSISTANT_CHROMA_EMBEDDING_DIMENSION=str(rag_manifest['embeddingDimension']),
            CHAT_ASSISTANT_CHROMA_COLLECTION=rag_manifest['collection'],
            CHAT_ASSISTANT_CHROMA_TENANT=rag_manifest['tenant'], CHAT_ASSISTANT_CHROMA_DATABASE=rag_manifest['database'])
        model_image = self.build_model_image()
        config['services']['model-fixture'] = {'image': model_image, 'restart': 'no', 'read_only': True,
            'environment': {'RUNTIME_FIXTURE_TOKEN': secrets.token_hex(32)}, 'networks': {'doorhandle-network': {}},
            'labels': {'io.doorhandle.rehearsal': self.project}, 'cap_drop': ['ALL'],
            'security_opt': ['no-new-privileges:true'], 'mem_limit': 128 * 1024 * 1024,
            'healthcheck': {'test': ['CMD', 'python', '-c', "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8099/health',timeout=3)"],
                            'interval': '5s', 'timeout': '4s', 'retries': 10}}
        original_oss = config['services']['detection-worker']['environment']
        endpoint = urllib.parse.urlsplit(original_oss['ALIYUN_OSS_ENDPOINT'])
        bucket = original_oss['ALIYUN_OSS_BUCKET']
        require(endpoint.scheme == 'https' and re.fullmatch(r'oss-[a-z0-9-]+\.aliyuncs\.com', endpoint.hostname or '')
                and endpoint.path in ('', '/') and not endpoint.username and not endpoint.password
                and not endpoint.query and not endpoint.fragment and endpoint.port in (None, 443)
                and re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', bucket), 'A real reviewed Alibaba OSS endpoint is required')
        config['services']['oss-proxy'] = {'image': model_image, 'restart': 'no', 'read_only': True,
            'entrypoint': ['python', '-B', '/fixture/compact-oss-fixture.py'],
            'environment': {'FIXTURE_OSS_BUCKET': bucket, 'FIXTURE_OSS_ENDPOINT': original_oss['ALIYUN_OSS_ENDPOINT'],
                            'FIXTURE_OSS_PREFIX': 'runtime-acceptance/' + self.token + '/'},
            'networks': {'doorhandle-network': {'aliases': [bucket + '.oss-proxy']}, 'worker-egress': {}},
            'labels': {'io.doorhandle.rehearsal': self.project}, 'cap_drop': ['ALL'],
            'security_opt': ['no-new-privileges:true'], 'mem_limit': 128 * 1024 * 1024,
            'healthcheck': {'test': ['CMD', 'python', '-c', "import urllib.request;urllib.request.urlopen('http://127.0.0.1:9000/health',timeout=3)"],
                            'interval': '5s', 'timeout': '4s', 'retries': 10}}
        config['services']['backend'].setdefault('depends_on', {})['oss-proxy'] = {'condition': 'service_healthy'}
        config = bounded_config(config)
        self.validate_config(config)
        return config

    def model_routes(self):
        active = self.db.query("SELECT JSON_OBJECT('revision',c.revision,'sealed',c.sealed_snapshot) "
            "FROM llm_configuration c JOIN runtime_state s ON s.namespace='MODEL_CONFIG_CONTROL' "
            "AND s.owner_id=0 AND s.scope_key='GLOBAL' AND c.revision=CAST(s.current_ref AS UNSIGNED);")
        if not active:
            # An empty history bootstraps from the explicitly local deployment.
            require(self.db.one("SELECT JSON_OBJECT('n',COUNT(*)) FROM llm_configuration;")['n'] == 0,
                    'Model history has no unambiguous active control')
            return {name: 'http://model-fixture:8099/v1' for name in ('deepseek', 'dashscope', 'openai')}
        require(len(active) == 1, 'Model control has multiple active versions')
        code = """import json,base64,sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
v=json.load(sys.stdin); version,nonce,cipher=v['sealed'].split('.')
assert version=='v1'
data=json.loads(AESGCM(base64.b64decode(v['key'])).decrypt(base64.b64decode(nonce),base64.b64decode(cipher),('doorhandle:model-config:'+str(v['revision'])).encode()))
print(json.dumps({p:data['properties'][p]['baseUrl'] for p in ('deepseek','dashscope','openai')}))
"""
        value = {**active[0], 'key': self.master_key.strip().decode('ascii')}
        routes = json.loads(self.ops.docker('run', '--rm', '-i', '--network', 'none', '--read-only', '--pull', 'never',
            '--memory', '128m', '--memory-swap', '128m',
            '--label', 'io.doorhandle.rehearsal=' + self.project, '--entrypoint', 'python', self.images['mem0'],
            '-B', '-c', code, data=json.dumps(value).encode(), timeout=30))
        require(set(routes) == {'deepseek', 'dashscope', 'openai'} and all(isinstance(url, str)
                and urllib.parse.urlsplit(url).scheme in ('http', 'https') for url in routes.values()),
                'Frozen provider endpoints cannot be read for the owned transport fixture')
        return routes

    def build_model_image(self):
        context = self.directory / 'model-image'; context.mkdir(mode=0o700)
        source = self.source / 'script/docker/compact-model-fixture.py'
        require(source.is_file(), 'The fixed-source model fixture implementation is missing')
        (context / 'server.py').write_bytes(source.read_bytes())
        oss_source = self.source / 'script/docker/compact-oss-fixture.py'
        (context / 'oss.py').write_bytes(oss_source.read_bytes())
        (context / 'Dockerfile').write_text('FROM ' + self.images['mem0'] + '\nCOPY --chmod=0644 server.py /app/runtime-model.py\nCOPY --chmod=0644 oss.py /fixture/compact-oss-fixture.py\n'
            'ENTRYPOINT ["python","-B","/app/runtime-model.py"]\n', encoding='utf8')
        tag = 'doorhandlecatch/runtime-model:' + self.args.tag + '-' + self.token
        self.ops.docker('build', '--label', 'io.doorhandle.rehearsal=' + self.project, '-t', tag, str(context), timeout=300)
        image = json.loads(self.ops.docker('image', 'inspect', tag))[0]
        self.owner['modelFixtureImage'] = image['Id']; self.owner['modelFixtureSourceSha256'] = sha_file(source)
        self.owner['ossFixtureSourceSha256'] = sha_file(oss_source); self.save()
        return image['Id']

    def build_mcp_image(self, original):
        require(re.fullmatch(r'sha256:[a-f0-9]{64}', original), 'MCP must derive from the admitted immutable Fetch image')
        image = json.loads(self.ops.docker('image', 'inspect', original))[0]
        labels = image.get('Config', {}).get('Labels') or {}
        require(labels.get('doorhandle.mcp.fetch') == 'true' and labels.get('io.doorhandle.mcp-image-lifecycle') == '2'
                and labels.get('doorhandle.mcp.package-sha256') == 'd722c48bdc1de3e2a81727853bc490cf55c6c935e2038cdcad3c111b1d85db77',
                'MCP dependency/receipt compatibility is not established')
        context = self.directory / 'mcp-image'; context.mkdir(mode=0o700)
        lines = ['FROM ' + original]; catalog = {}
        for name in ('runner.py', 'execution_store.py', 'image_lifecycle.py', 'configure.py'):
            path = self.source / 'deploy/mcp' / name
            raw = path.read_bytes()
            if name == 'runner.py':
                require(raw.count(b"'--memory=256m',") == 1, 'MCP child memory declaration changed')
                raw = raw.replace(b"'--memory=256m',", b"'--memory=256m', '--memory-swap=256m',")
            (context / name).write_bytes(raw)
            catalog[name] = {'fixedSourceSha256': sha_file(path), 'imageSourceSha256': sha_file(context / name)}
            lines.append('COPY --chmod=0644 ' + name + ' /app/' + name)
        (context / 'Dockerfile').write_text('\n'.join(lines) + '\n', encoding='utf8')
        tag = 'doorhandlecatch/runtime-mcp:' + self.args.tag + '-' + self.token
        self.ops.docker('build', '--label', 'io.doorhandle.rehearsal=' + self.project, '-t', tag, str(context), timeout=300)
        result = json.loads(self.ops.docker('image', 'inspect', tag))[0]['Id']
        self.owner['runtimeMcpImage'] = result; self.owner['runtimeMcpSourceHashes'] = catalog; self.save()
        return result

    def install_key(self, raw):
        volume = self.config['volumes']['runtime-model-key']['name']
        self.ops.docker('volume', 'create', '--label', 'io.doorhandle.rehearsal=' + self.project, volume)
        metadata = json.loads(self.ops.docker('volume', 'inspect', volume))[0]
        require(metadata.get('Labels', {}).get('io.doorhandle.rehearsal') == self.project, 'Runtime key volume ownership differs')
        code = "import sys,os; p='/target/model_config_master_key'; f=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o400); os.write(f,sys.stdin.buffer.read(128)); os.close(f); os.chown(p,10001,10001); os.chmod(p,0o400)"
        self.ops.docker('run', '--rm', '-i', '--pull', 'never', '--network', 'none', '--read-only', '--user', '0:0',
            '--memory', '128m', '--memory-swap', '128m',
            '--label', 'io.doorhandle.rehearsal=' + self.project, '--mount', 'type=volume,src=' + volume + ',dst=/target',
            '--entrypoint', 'python', self.images['mem0'], '-B', '-c', code, data=raw, timeout=30)

    def start(self):
        declared = sum(int(spec.get('mem_limit', 0)) for spec in self.config['services'].values())
        physical = allocated_bytes(Path(self.fixture_owner['dataDirectory']) / self.owner['targetSchema'])
        retained = allocated_bytes(self.checkout / 'work/compact-fixtures')
        logs = len(self.config['services']) * 5 * MIB
        # This is a monitored experiment boundary, never a predicted peak/PASS.
        # Existing images, source, all dumps and prior clones remain allocated in
        # the baseline filesystem; none is credited as reclaimable capacity.
        payload_bytes = sum(row['bytes'] for service in ('rag', 'mem0')
                            for row in self.native.read(self.legacy_work / (service + '-payload-files.json')).values())
        growth = physical + payload_bytes + logs + 8 * 64 * MIB + 256 * MIB
        self.resources.admit('runtime-start', growth, {
            'candidateSchemaAllocatedBytes': physical, 'retainedFixturesAllocatedBytes': retained,
            'candidateBuildSha256': self.build_sha, 'applicationJarBytes': self.build['applicationJarBytes'],
            'fullNativeCandidatePayloadBytes': payload_bytes, 'legacyCandidateSha256': self.legacy_candidate_sha,
            'originalDeploymentInventorySha256': self.migration.sha_json(self.owner['sourceBefore']),
            'logLimitBytes': logs, 'kafkaPartitionRetentionEnvelopeBytes': 8 * 64 * MIB,
            'newWritableMeasurementEnvelopeBytes': 256 * MIB,
            'existingDataAndBackups': 'RETAINED_IN_BASELINE_FILESYSTEM'}, declared + MCP_CHILD_MEMORY)
        self.resources.start()
        self.owner['nativeMaterialization'] = self.native.materialize_runtime(self); self.save()
        self.install_key(self.master_key)
        self.dc('create', '--no-build', 'redis', timeout=120)
        network_name = self.config['networks']['doorhandle-network']['name']
        network = json.loads(self.ops.docker('network', 'inspect', network_name))[0]
        require(network.get('Labels', {}).get('io.doorhandle.rehearsal') == self.project and network.get('Internal') is True,
                'Owned internal runtime network was not created')
        self.ops.docker('network', 'connect', '--alias', 'mysql', network['Id'], self.owner['mysqlContainerId'])
        self.owner['mysqlAttachedNetwork'] = network['Id']; self.save('STARTING')
        self.dc('up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '300', timeout=420)
        for name in ('backend', 'detection-worker', 'mem0', 'nginx', 'model-fixture'):
            row = self.row(name)
            require(self.ops.healthy(row['Id']) and (name not in self.images or row['Image'] == self.images[name]),
                    'Actual candidate identity or runtime health differs')
        networks = []
        for name in ('backend', 'mem0', 'model-fixture'):
            row = self.row(name)
            require(row['HostConfig'].get('NetworkMode') != 'host' and not row['HostConfig'].get('Privileged'), 'A model process has host access')
            for attached in row['NetworkSettings']['Networks'].values():
                network = json.loads(self.ops.docker('network', 'inspect', attached['NetworkID']))[0]
                require(network['Internal'] is True and network.get('Labels', {}).get('io.doorhandle.rehearsal') == self.project,
                        'An actual model-capable container can access external traffic')
                networks.append({'service': name, 'networkId': network['Id'], 'internal': True})
        self.owner['observedModelNetworks'] = networks; self.save()
        worker = self.row('detection-worker'); env = self.common.environment(worker)
        require(env['DETECTION_RECEIPT_DB_DATABASE'] == self.owner['targetSchema']
                and env['DETECTION_RECEIPT_DB_PORT'] == str(self.owner['mysqlPort']), 'Actual worker receipt endpoint differs')
        self.rehearsal.verify_ui_entries(self.client('inspector'))
        pool_code = "import sqlite3,json,os; c=sqlite3.connect('file:'+os.environ['MCP_EXECUTION_DB']+'?mode=ro',uri=True); print(json.dumps(c.execute(\"SELECT value FROM metadata WHERE key='pool_id'\").fetchone()[0]))"
        pool = json.loads(self.ops.docker('exec', self.row('mcp-runner')['Id'], '/opt/fetch/.venv/bin/python', '-B', '-c', pool_code, timeout=15))
        require(isinstance(pool, str) and re.fullmatch(r'[a-f0-9]{32}', pool), 'The actual runtime MCP journal pool is unverified')
        self.owner['mcpPoolId'] = pool
        self.save('RUNNING')
        self.native.verify_runtime(self, 'after-start')

    def restart_backend(self):
        self.dc('restart', 'backend', timeout=120)
        end = time.monotonic() + 180
        while time.monotonic() < end:
            if self.ops.healthy(self.row('backend')['Id']):
                self.clients = {}; self.client('inspector')
                if 'after-restart' not in self.owner.get('nativeVerifications', {}):
                    self.native.verify_runtime(self, 'after-restart')
                return
            time.sleep(2)
        raise ValueError('The actual candidate backend did not recover')

    def stop_writers(self):
        services = [name for name in ('nginx', 'backend', 'detection-worker', 'mem0', 'mcp-runner') if name in self.config['services']]
        for name in services:
            row = self.row(name)
            self.ops.docker('stop', '--time', '30', row['Id'], timeout=90)
        for name in services:
            state = self.row(name)['State']
            require(not state['Running'] and not state.get('Restarting') and state['Pid'] == 0, 'A runtime writer did not freeze')

    def worker_scenario(self):
        prefix_check = """import json,os,oss2
b=oss2.Bucket(oss2.Auth(os.environ['ALIYUN_OSS_ACCESS_KEY_ID'],os.environ['ALIYUN_OSS_ACCESS_KEY_SECRET']),os.environ['ALIYUN_OSS_ENDPOINT'],os.environ['ALIYUN_OSS_BUCKET'])
prefix=json.load(__import__('sys').stdin)['prefix']; assert not list(oss2.ObjectIterator(b,prefix=prefix,max_keys=1)); print(json.dumps({'empty':True}))
"""
        prefix = 'runtime-acceptance/' + self.token + '/'
        empty = json.loads(self.ops.docker('exec', '-i', self.row('detection-worker')['Id'], 'python', '-B', '-c', prefix_check,
            data=json.dumps({'prefix': prefix}).encode(), timeout=30))
        require(empty == {'empty': True}, 'The owned OSS prefix already contains data')
        self.owner['ossPrefixProvenEmpty'] = prefix; self.save()
        def chunk(name, value):
            return struct.pack('>I', len(value)) + name + value + struct.pack('>I', zlib.crc32(name + value) & 0xffffffff)
        width, height = 320, 240
        pixels = b''.join(b'\x00' + b''.join(bytes((x % 256, y % 256, (x + y) % 256)) for x in range(width)) for y in range(height))
        image = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b'')
        self.worker_image_bytes = image
        model = int(self.config['services']['detection-worker']['environment']['DETECTION_MODEL_ID'])
        require(model > 0, 'The owned worker lacks its actual deployed PTH model id')
        created = self.request('inspector', 'POST', '/api/detection/tasks', {'taskType': 'BATCH',
            'files': [{'fileName': 'runtime.png', 'contentType': 'image/png', 'relativePath': 'runtime.png', 'fileSize': len(image)}],
            'captureInfo': {'captureDate': time.strftime('%Y-%m-%d'), 'region': '隔离验收',
                'collector': self.accounts['inspector']['username'], 'deviceName': 'runtime-' + self.token,
                'imageFolderName': 'runtime-' + self.token}, 'modelId': model, 'threshold': 0.5})
        task = created['taskId']; urls = created['uploadUrls']
        require(re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', task) and len(urls) == 1, 'Actual task allocation is incomplete')
        upload = urls[0]; prefix = 'runtime-acceptance/' + self.token + '/'
        require(created['uploadPrefix'].startswith(prefix) and upload['objectKey'].startswith(created['uploadPrefix']),
                'Actual detection allocation escaped the owned OSS prefix')
        target = urllib.parse.urlsplit(upload['putUrl'])
        bucket = self.config['services']['detection-worker']['environment']['ALIYUN_OSS_BUCKET']
        require(target.scheme == 'http' and target.hostname in ('oss-proxy', bucket + '.oss-proxy') and target.port == 9000,
                'The upload must pass through the prefix-restricted OSS transport')
        self.owner['objects'].append(upload['objectKey']); self.owner['detectionTaskId'] = task
        self.owner['detectionPrefix'] = created['uploadPrefix']; self.save()
        script = """import sys,json,base64,urllib.request
v=json.load(sys.stdin); r=urllib.request.Request(v['url'],data=base64.b64decode(v['image']),method='PUT',headers={'Content-Type':'image/png'})
with urllib.request.urlopen(r,timeout=60) as s:
 assert s.status==200
 print(json.dumps({'etag':s.headers.get('ETag','').strip('"'),'requestId':s.headers.get('x-oss-request-id')}))
"""
        uploaded = json.loads(self.ops.docker('exec', '-i', self.row('detection-worker')['Id'], 'python', '-B', '-c', script,
            data=json.dumps({'url': upload['putUrl'], 'image': base64.b64encode(image).decode()}).encode(), timeout=90))
        require(uploaded['etag'] and uploaded['requestId'], 'Real OSS PUT returned no verifiable receipt')
        self.request('inspector', 'POST', '/api/detection/tasks/' + task + '/uploaded', {'modelId': model, 'threshold': 0.5,
            'uploadedFiles': [{'fileName': upload['fileName'], 'objectKey': upload['objectKey'], 'etag': uploaded['etag'],
                               'sha256': hashlib.sha256(image).hexdigest()}]})
        deadline = time.monotonic() + 420
        while time.monotonic() < deadline:
            progress = self.request('inspector', 'GET', '/api/detection/tasks/' + task)
            require(progress['status'] not in ('FAILED', 'PARTIAL_FAILED', 'CANCELLED'), 'Actual PTH/Kafka detection failed')
            if progress['status'] == 'COMPLETED':
                break
            time.sleep(2)
        require(progress['status'] == 'COMPLETED' and progress['successfulImages'] == 1
                and progress['failedImages'] == 0 and progress['processedImages'] == 1, 'Actual PTH processing did not finish')
        result = self.request('inspector', 'GET', '/api/detection/tasks/' + task + '/result')
        require(result['resultOssPrefix'].startswith(prefix) and result['successfulImages'] == 1, 'Actual PTH result is missing')
        self.owner['detectionResultPrefix'] = result['resultOssPrefix']; self.save()
        receipt_sql = "SELECT JSON_OBJECT('id',workflow_id,'dispatch',run_id,'status',status,'sha256',result_sha256,'body',result_json,'revision',revision) FROM workflow_instance WHERE kind='DETECTION_WORKER' AND resource_id=" + self.db.literal(task) + ';'
        receipts = self.db.query(receipt_sql)
        require(len(receipts) == 1 and receipts[0]['status'] == 'COMPLETED'
                and hashlib.sha256(receipts[0]['body'].encode()).hexdigest() == receipts[0]['sha256'], 'Actual durable worker result is unverifiable')
        actual = json.loads(receipts[0]['body'])
        require(actual['taskId'] == task and actual['status'] == 'COMPLETED' and actual['successfulImages'] == 1,
                'The persisted worker result differs from the observed task')
        # Re-deliver the original actual created event after restarting the
        # actual worker. Its persisted receipt must prevent another inference.
        # No reconstructed event or fabricated successful receipt is inserted.
        replay = """import os,json,sys,time,secrets
from confluent_kafka import Consumer,Producer,TopicPartition,KafkaError
task=json.load(sys.stdin)['task']; topic='detection.task.created'
c=Consumer({'bootstrap.servers':os.environ['KAFKA_BOOTSTRAP_SERVERS'],'group.id':'runtime-evidence-'+secrets.token_hex(8),'enable.auto.commit':False,'enable.partition.eof':True})
partitions=list(c.list_topics(topic,timeout=10).topics[topic].partitions)
ends={p:c.get_watermark_offsets(TopicPartition(topic,p),timeout=10)[1] for p in partitions}
c.assign([TopicPartition(topic,p,0) for p in partitions]); values=[]; end=time.monotonic()+15
while any(v.offset<ends[v.partition] for v in c.position([TopicPartition(topic,p) for p in partitions])):
 assert time.monotonic()<end
 m=c.poll(1)
 if m is None: continue
 if m.error():
  assert m.error().code()==KafkaError._PARTITION_EOF; continue
 if json.loads(m.value()).get('taskId')==task: values.append({'value':m.value(),'key':m.key(),'partition':m.partition()})
c.close(); assert len(values)==1
p=Producer({'bootstrap.servers':os.environ['KAFKA_BOOTSTRAP_SERVERS']}); acknowledged=[]
def delivered(error,message):
 assert error is None
 acknowledged.append({'topic':message.topic(),'partition':message.partition(),'offset':message.offset()})
p.produce(topic,partition=values[0]['partition'],key=values[0]['key'],value=values[0]['value'],on_delivery=delivered); assert p.flush(15)==0 and len(acknowledged)==1
print(json.dumps(acknowledged[0]))
"""
        self.replay_script = replay
        self.dc('restart', 'detection-worker', timeout=150)
        replayed = json.loads(self.ops.docker('exec', '-i', self.row('detection-worker')['Id'], 'python', '-B', '-c', replay,
            data=json.dumps({'task': task}).encode(), timeout=45))
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            offset = self.ops.docker('exec', self.row('kafka')['Id'], '/opt/kafka/bin/kafka-consumer-groups.sh',
                '--bootstrap-server', 'kafka:9092', '--describe', '--group', 'runtime-' + self.token, timeout=20).decode()
            rows = [row.split() for row in offset.splitlines() if 'detection.task.created' in row]
            if rows and all(len(row) >= 6 and row[5] == '0' for row in rows):
                break
            time.sleep(2)
        require(rows and all(len(row) >= 6 and row[5] == '0' for row in rows), 'The actual replay was not consumed')
        after = self.db.query(receipt_sql)
        require(after == receipts and self.request('inspector', 'GET', '/api/detection/tasks/' + task)['status'] == 'COMPLETED',
                'A duplicate event changed the completed receipt or reran its durable transition')
        self.report_task_id = task
        self.worker_observations = {'taskId': task, 'modelId': model, 'engine': 'pth',
            'inputSha256': hashlib.sha256(image).hexdigest(), 'ossRequestIdSha256': hashlib.sha256(uploaded['requestId'].encode()).hexdigest(),
            'workerReceiptId': receipts[0]['id'], 'workerResultSha256': receipts[0]['sha256'], 'actualReplay': replayed,
            'unchangedDurableReceiptAfterRestart': True, 'successfulImages': 1}

    def sdk_scenario(self):
        return self.http.sdk_scenario(self)

    def skill_scenario(self):
        return self.http.skill_scenario(self)

    def recovery_scenario(self):
        return self.recovery.run(self)

    def admit_backup_phase(self, snapshot):
        # mysqldump uses one complete INSERT per row, --hex-blob and no DDL.
        # Measure every source column's bytes; escaping/binary hex at most double
        # these bytes. Per-row full column names and framing are counted too.
        bound, row_count = MIB, 0
        tables = {}
        for table, detail in snapshot['tables'].items():
            names = [column['name'] for column in detail['columns']]
            prefix = 'INSERT INTO `' + table + '` (' + ', '.join('`' + name + '`' for name in names) + ') VALUES ('
            terms = []
            for column in detail['columns']:
                quoted = self.migration.quoted(column['name'])
                binary = re.match(r'(?:.*blob|.*binary|bit)(?:\(|$)', column['type'], re.I)
                encoded = quoted if binary else 'CAST(' + quoted + ' AS CHAR CHARACTER SET utf8mb4)'
                terms.append('COALESCE(OCTET_LENGTH(' + encoded + '),0)')
            measured = self.db.one("SELECT JSON_OBJECT('rows',COUNT(*),'bytes',COALESCE(SUM(" + '+'.join(terms)
                                   + "),0)) FROM " + self.migration.quoted(table) + ';')
            require(measured['rows'] == detail['rows'], 'Frozen backup row count changed during resource measurement')
            rows, size = int(measured['rows']), int(measured['bytes'])
            row_count += rows
            # NULL, quoting, commas and hex prefixes each fit in 16 bytes/column.
            upper = 2 * size + rows * (len(prefix.encode()) + 16 * len(names) + 4)
            bound += upper; tables[table] = {'rows': rows, 'rawColumnBytes': size, 'dumpUpperBoundBytes': upper}
        self.backup_dump_bound = bound
        native = self.native.measure_runtime_volumes(self)
        native_bound = 5 * sum(row['bytes'] for row in native.values()) + 2 * 64 * MIB
        self.resources.admit('runtime-backup', bound + 64 * MIB + native_bound, {
            'sourceSnapshotSha256': snapshot['snapshotSha256'], 'tables': tables,
            'rows': row_count, 'dumpUpperBoundBytes': bound, 'retainedPriorData': True,
            'nativeVolumeMeasurements': native, 'nativeSnapshotGrowthEnvelopeBytes': native_bound})

    def admit_restore_phase(self, backup):
        file, manifest, checksum = self.migration.private_json(backup)
        dump = self.cutover.canonical(file.parent / manifest['data']['file'])
        require(dump.name == 'data.sql' and dump.stat().st_size == manifest['data']['bytes']
                and sha_file(dump) == manifest['data']['sha256']
                and dump.stat().st_size <= self.backup_dump_bound, 'Measured runtime backup exceeded its admitted bound')
        physical = allocated_bytes(Path(self.fixture_owner['dataDirectory']) / self.owner['targetSchema'])
        # Existing raw dump stays. restore_data additionally retains clean SQL
        # and prefixed SQL input; the original schema and prior clones stay too.
        # Physical clone growth is an enforced measurement envelope, not a claim
        # that InnoDB allocation can be predicted from information_schema.
        native = self.native.measure_runtime_volumes(self)
        native_bytes = sum(row['bytes'] for row in native.values())
        growth = 2 * dump.stat().st_size + 2 * physical + 128 * MIB + native_bytes
        self.resources.admit('runtime-restore', growth, {'backupManifestSha256': checksum,
            'dumpBytes': dump.stat().st_size, 'dumpSha256': manifest['data']['sha256'],
            'retainedRawDumpBytes': dump.stat().st_size, 'additionalSqlCopies': 2,
            'retainedSourceSchemaAllocatedBytes': physical, 'cloneAllocationMeasurementEnvelopeBytes': 2 * physical,
            'restoreOverheadEnvelopeBytes': 128 * MIB, 'nativeVolumeMeasurements': native,
            'newNativeVolumePayloadBytes': native_bytes, 'existingDataAndBackups': 'RETAINED_IN_BASELINE_FILESYSTEM'})

    def memory_scenario(self):
        session = self.request('inspector', 'POST', '/api/chat-assistant/sessions')['sessionId']
        user = self.accounts['inspector']['userId']; owner = 'doorhandlecatch:user:' + str(user)
        seeded = self.seed_memory(owner, session)
        page = self.request('inspector', 'GET', '/api/agent/memories')
        selected = [item for item in page['items'] if item['id'] == seeded['memoryId']]
        require(len(selected) == 1 and hashlib.sha256(selected[0]['memory'].encode()).hexdigest() == seeded['contentSha256'], 'Actual native memory is not visible to its owner')
        require(not any(item['id'] == seeded['memoryId'] for item in self.request('peer', 'GET', '/api/agent/memories')['items']),
                'Another account can read the native memory')
        before = selected[0]; revision = before['lifecycle']['revision']
        changed = self.request('inspector', 'POST', '/api/agent/memories/' + seeded['memoryId'] + '/lifecycle', {
            'requestId': 'runtime-memory-' + self.token, 'expectedDigest': before['digest'], 'expectedRevision': revision,
            'state': 'EXCLUDED', 'autoDelete': False, 'confirmed': True})
        require(changed['state'] == 'EXCLUDED' and changed['revision'] == revision + 1, 'Actual memory governance transition did not persist')
        search = self.bridge('/memories/search', {'query': '质检报告缺陷整改建议', 'user_id': owner,
            'app_id': 'doorhandlecatch', 'run_id': session, 'scope': 'ACCOUNT', 'top_k': 10})
        require(search.get('code') == 200 and isinstance(search.get('data'), list), 'The actual memory read context was unavailable')
        values = search['data']
        require(all(item.get('id') != seeded['memoryId'] for item in values), 'Excluded memory still enters the model read context')
        self.restart_backend()
        restored = self.request('inspector', 'GET', '/api/agent/memories/' + seeded['memoryId'])
        require(restored['lifecycle']['state'] == 'EXCLUDED' and restored['digest'] == before['digest'], 'Memory governance did not survive application restart')
        active = self.request('supervisor', 'GET', '/api/agent/model-config')
        require(active['activeRevision'] == self.owner['modelRevision'], 'The published model version was lost on restart')
        key_run = self.run_sdk('inspector', [{'text': '密钥恢复后模型连接已返回'}], '查看本轮模型配置恢复状态', self.model_id)
        require(key_run['phase'] == 'COMPLETED', 'The candidate cannot decrypt/use its frozen model after restart')
        self.owner['memoryId'] = seeded['memoryId']; self.owner['memorySessionId'] = session; self.save()
        self.record('memory-governance-read-model-key', {'memoryId': seeded['memoryId'], 'contentSha256': seeded['contentSha256'], 'memoryDigest': before['digest'],
            'ownerUserId': user, 'inferenceMode': 'SDK_INFER_FALSE', 'llmCalls': seeded['llmCalls'],
            'excludedFromActualReadContext': True, 'modelRevisionReadAfterRestart': active['activeRevision'],
            'modelReadAfterRestartRunId': key_run['runId'],
            'keyMode': self.owner['keyMode'], 'keyReferenceSha256': sha_file(self.key_reference)})

    def mcp_unknown_control(self, account):
        """Lose the actual control response while a real private Fetch writer exists."""
        route = '/api/agent/mcp/fetch'; user = self.accounts[account]['userId']
        before = self.db.one("SELECT JSON_OBJECT('id',COALESCE(MAX(id),0)) FROM workflow_instance;")['id']
        outcome = {}
        def invoke():
            try:
                outcome['run'] = self.run_sdk(account, [
                    {'tool': 'mcp__fetch__fetch', 'arguments': {'url': 'https://example.com', 'max_length': 2000}}], '查看公开网址 https://example.com',
                    marker='runtime-mcp-fault-' + self.token)
            except BaseException as error:
                outcome['failureType'] = type(error).__name__
        worker = threading.Thread(target=invoke, daemon=True); worker.start()
        paused = False; runner = self.row('mcp-runner'); selected = None; child = None
        try:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                candidates = self.db.query("SELECT JSON_OBJECT('executionId',resource_id,'runId',run_id,'pool',mcp_pool_id,'revision',revision,"
                    "'state',status,'exitVerified',mcp_exit_verified,'cleanupConfirmed',mcp_cleanup_confirmed) FROM workflow_instance WHERE kind='MCP_EXECUTION' AND mcp_purpose='CALL' AND id>"
                    + str(before) + ' AND owner_user_id=' + str(user) + ';')
                require(len(candidates) <= 1, 'The controlled MCP request spawned duplicate executions')
                if candidates:
                    selected = candidates[0]
                    require(selected['pool'] == self.owner['mcpPoolId'], 'The actual fault execution selected another journal pool')
                    ids = self.ops.docker('ps', '-q', '--no-trunc', '--filter', 'label=doorhandle.mcp.pool=' + selected['pool'],
                        '--filter', 'label=doorhandle.mcp.nonce=' + selected['executionId']).decode().split()
                    if ids:
                        require(len(ids) == 1, 'The actual Fetch nonce has multiple writers')
                        child = json.loads(self.ops.docker('inspect', ids[0]))[0]
                        labels = child['Config'].get('Labels') or {}
                        require(child['Image'] == self.owner['runtimeMcpImage'] and child['State']['Running']
                                and labels.get('doorhandle.mcp.managed') == 'true'
                                and labels.get('doorhandle.mcp.owner') == str(user), 'The fault target is not the owned actual Fetch writer')
                        self.ops.docker('pause', runner['Id']); paused = True
                        actual = json.loads(self.ops.docker('inspect', runner['Id']))[0]
                        require(actual['State'].get('Paused') is True, 'The real MCP controller was not suspended')
                        break
                require(worker.is_alive(), 'The Fetch completed before an actual writer/control fault was observed')
                time.sleep(0.05)
            require(paused and selected and child, 'An actual Fetch writer could not be isolated for the control-response fault')
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                pending = self.request(account, 'GET', route)
                matches = [item for item in pending['executionReceipts']['items'] if item['executionId'] == selected['executionId']]
                require(len(matches) == 1, 'The fault execution disappeared instead of retaining its unknown result')
                uncertain = matches[0]
                if uncertain['state'] == 'NEEDS_REVIEW':
                    break
                time.sleep(1)
            require(uncertain['state'] == 'NEEDS_REVIEW' and not uncertain['exitVerified'] and not uncertain['cleanupConfirmed'],
                    'An unavailable actual controller was incorrectly advertised as a confirmed exit')
            denied = urllib.request.Request(self.client(account).base + route + '/install', method='POST',
                data=json.dumps({'expectedRevision': pending['revision'], 'requestId': 'fault-block-' + self.token, 'licenseAccepted': True}).encode(),
                headers={'Content-Type': 'application/json', 'X-MCP-Action': 'update'})
            try:
                self.client(account).opener.open(denied, timeout=20)
            except urllib.error.HTTPError as error:
                require(error.code == 409, 'The actual unknown-result fence failed for an unrelated reason')
                denied_body = error.read(8193)
                require(len(denied_body) <= 8192 and json.loads(denied_body).get('message') == '请先核对已有执行退出 再更换安装',
                        'The rejected installation was blocked by another rule, not the actual pending-execution fence')
            else:
                raise ValueError('An unknown actual execution allowed another installation writer')
            preserved = self.db.one("SELECT JSON_OBJECT('n',COUNT(*)) FROM workflow_instance WHERE kind='MCP_EXECUTION' AND resource_id="
                + self.db.literal(selected['executionId']) + " AND status='NEEDS_REVIEW' AND mcp_pool_id=" + self.db.literal(selected['pool']) + ';')
            require(preserved['n'] == 1, 'The rejected retry erased or replaced actual uncertainty')
        finally:
            if paused:
                self.ops.docker('unpause', runner['Id'])
            worker.join(timeout=90)
        require(not worker.is_alive(), 'The actual SDK fault request is still running; keep its owned resources for review')
        refreshed = self.request(account, 'GET', route)
        unknown = next(item for item in refreshed['executionReceipts']['items'] if item['executionId'] == selected['executionId'])
        self.request(account, 'POST', route + '/executions/' + selected['executionId'] + '/reconcile', {
            'expectedRevision': unknown['revision'], 'requestId': 'fault-reconcile-' + self.token, 'confirmed': True})
        final = self.request(account, 'GET', route)
        settled = next(item for item in final['executionReceipts']['items'] if item['executionId'] == selected['executionId'])
        require(settled['state'] == 'REMOVED' and settled['exitVerified'] and settled['cleanupConfirmed'],
                'The actual resumed controller could not prove writer-tree exit and cleanup')
        live = self.ops.docker('ps', '-q', '--no-trunc', '--filter', 'label=doorhandle.mcp.pool=' + selected['pool'],
            '--filter', 'label=doorhandle.mcp.nonce=' + selected['executionId']).decode().split()
        require(not live, 'The reconciled actual Fetch writer still exists')
        return {'executionId': selected['executionId'], 'runId': selected['runId'], 'poolId': selected['pool'],
            'observedWriterId': child['Id'], 'pausedControllerId': runner['Id'], 'unknownState': uncertain['state'],
            'actualSdkFaultOutcome': outcome.get('failureType') or outcome.get('run', {}).get('phase'),
            'newInstallationBlockedHttpStatus': 409, 'newInstallationBlockedReason': 'PENDING_EXECUTION_EXIT',
            'denialResponseSha256': hashlib.sha256(denied_body).hexdigest(),
            'reconciledState': settled['state'], 'writerExitAndCleanupVerified': True}

    def mcp_scenario(self):
        route = '/api/agent/mcp/fetch'
        peer = self.request('peer', 'GET', route)
        require(peer['status'] == 'NOT_INSTALLED' and peer['installQueue'] == 'DURABLE', 'Fresh private MCP identity is not isolated')
        runner = self.row('mcp-runner')
        # Hold the real dispatcher endpoint so cancellation can be verified for
        # a queued installation instead of relying on a timing race.
        self.ops.docker('pause', runner['Id'])
        try:
            queued = self.request('peer', 'POST', route + '/install', {'expectedRevision': peer['revision'],
                'requestId': 'runtime-cancel-' + self.token, 'licenseAccepted': True})
            cancelled = self.request('peer', 'POST', route + '/install/cancel', {
                'expectedRevision': queued['revision'], 'operationId': queued['operationId'], 'confirmed': True})
            require(cancelled['status'] == 'CANCELLED' and cancelled['installPhase'] == 'CANCELLED',
                    'The actual durable installation was not cancelled')
        finally:
            self.ops.docker('unpause', runner['Id'])
        account = 'reviewer'  # A separate owned supervisor, as required by the profile.
        own = self.request(account, 'GET', route)
        self.request(account, 'POST', route + '/install', {'expectedRevision': own['revision'],
            'requestId': 'runtime-install-' + self.token, 'licenseAccepted': True})
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            installed = self.request(account, 'GET', route)
            if installed['status'] == 'INSTALLED':
                break
            require(installed['status'] == 'INSTALLING', 'Actual fixed Fetch installation failed')
            time.sleep(1)
        require(installed['status'] == 'INSTALLED' and installed['manifest']['image'] == self.owner['runtimeMcpImage']
                and installed['executionReceipts']['supported'], 'The actual private Fetch image/receipt is not established')
        enabled = self.request(account, 'POST', route + '/enabled', {'expectedRevision': installed['revision'], 'enabled': True})
        require(enabled['enabled'], 'Private Fetch was not enabled')
        probe = self.request(account, 'POST', route + '/probe')
        require(probe['connected'] is True and probe['tools'] == ['mcp__fetch__fetch'], 'Actual MCP handshake/tool discovery did not pass')
        fault = self.mcp_unknown_control(account)
        run = self.run_sdk(account, [{'tool': 'mcp__fetch__fetch', 'arguments': {'url': 'https://example.com', 'max_length': 2000}},
            {'text': '公开示例网页已读取'}], '读取用户明确提供的 https://example.com 并概述')
        current = self.request(account, 'GET', route)
        receipts = [item for item in current['executionReceipts']['items'] if item['purpose'] == 'CALL']
        require(receipts, 'Real SDK Fetch produced no execution receipt')
        for item in receipts:
            if item['state'] != 'REMOVED':
                result = self.request(account, 'POST', route + '/executions/' + item['executionId'] + '/reconcile', {
                    'expectedRevision': item['revision'], 'requestId': 'runtime-reconcile-' + uuid.uuid4().hex, 'confirmed': True})
                require(isinstance(result, dict), 'Actual MCP reconciliation returned no result')
        final = self.request(account, 'GET', route)
        call_receipts = [item for item in final['executionReceipts']['items'] if item['purpose'] == 'CALL']
        require(call_receipts and all(item['state'] == 'REMOVED' and item['exitVerified'] and item['cleanupConfirmed'] for item in call_receipts),
                'Actual MCP process exit and cleanup have not been proven')
        audit = self.db.one("SELECT JSON_OBJECT('n',COUNT(*)) FROM audit_event WHERE kind='MCP' AND action='CALL' AND outcome='COMPLETED' AND owner_user_id="
            + str(self.accounts[account]['userId']) + ' AND run_id=' + self.db.literal(run['runId']) + ';')
        require(audit['n'] >= 1, 'The real SDK tool did not successfully fetch the public page')
        durable = self.db.query("SELECT JSON_OBJECT('pool',mcp_pool_id,'image',mcp_image_id,'state',status) FROM workflow_instance WHERE kind='MCP_EXECUTION' AND owner_user_id="
            + str(self.accounts[account]['userId']) + ' AND run_id=' + self.db.literal(run['runId']) + ';')
        require(durable and all(item['pool'] == self.owner['mcpPoolId'] and item['image'] == self.owner['runtimeMcpImage']
                and item['state'] == 'REMOVED' for item in durable), 'Actual MCP execution pool/image differs from its private journal')
        reference = self.db.one("SELECT JSON_OBJECT('n',COUNT(*)) FROM workflow_instance WHERE kind='MCP_INSTALLATION' AND status='READY' AND mcp_writer_exit_verified=TRUE AND mcp_image_id="
            + self.db.literal(self.owner['runtimeMcpImage']) + ' AND owner_user_id=' + str(self.accounts[account]['userId']) + ';')
        require(reference['n'] == 1, 'Actual installed Fetch image lacks its retained immutable reader/writer proof')
        peer_after = self.request('peer', 'GET', route)
        require(not peer_after['enabled'] and peer_after['status'] == 'CANCELLED'
                and not peer_after['executionReceipts']['items'], 'Private MCP registration or receipts crossed owners')
        self.record('private-mcp-install-fetch-cancel-reconcile', {'runId': run['runId'],
            'installedImage': installed['manifest']['image'], 'cancelledOperationId': queued['operationId'],
            'ownerRole': self.accounts[account]['role'], 'journalPoolId': self.owner['mcpPoolId'], 'retainedInstallationReferences': reference['n'],
            'actualUnknownControlFault': fault,
            'actualCallExecutions': [item['executionId'] for item in call_receipts], 'exitAndCleanupVerified': True,
            'privateRegistrationVerified': True, 'durableQueue': 'DURABLE'})

    def cleanup_objects(self):
        prefix = self.owner.get('ossPrefixProvenEmpty')
        if not prefix or self.owner.get('objectsCleaned'):
            return
        require(prefix == 'runtime-acceptance/' + self.token + '/', 'The OSS cleanup prefix is not this attempt')
        row = self.row('detection-worker')
        require(row['Image'] == self.images['detection-worker'], 'OSS cleanup requires the exact candidate worker')
        if not row['State']['Running']:
            # A frozen worker must not resume its Kafka loop just for cleanup.
            # Use an owned, network-limited one-off with only its existing OSS
            # transport variables; no source credentials or foreign mounts.
            service = self.config['services']['detection-worker']
            env = {key: value for key, value in service['environment'].items() if key.startswith('ALIYUN_OSS_')}
            name = self.project + '-oss-cleanup'
            command = ['run', '--rm', '-i', '--name', name, '--pull', 'never', '--read-only',
                '--memory', '256m', '--memory-swap', '256m',
                '--label', 'io.doorhandle.rehearsal=' + self.project, '--network', self.config['networks']['worker-egress']['name']]
            for key, value in env.items():
                command.extend(['--env', key])
            executable = ['--entrypoint', 'python', self.images['detection-worker'], '-B', '-c']
            environment = dict(os.environ, **env)
        else:
            command, executable, environment = ['exec', '-i', row['Id']], ['python', '-B', '-c'], None
        code = """import json,os,sys,oss2,hashlib
v=json.load(sys.stdin); prefix=v['prefix']; assert prefix.startswith('runtime-acceptance/') and len(prefix.split('/'))==3
b=oss2.Bucket(oss2.Auth(os.environ['ALIYUN_OSS_ACCESS_KEY_ID'],os.environ['ALIYUN_OSS_ACCESS_KEY_SECRET']),os.environ['ALIYUN_OSS_ENDPOINT'],os.environ['ALIYUN_OSS_BUCKET'])
keys=[item.key for item in oss2.ObjectIterator(b,prefix=prefix)]; assert len(keys)<=100
for key in keys:
 assert key.startswith(prefix); b.delete_object(key)
assert not list(oss2.ObjectIterator(b,prefix=prefix,max_keys=1))
print(json.dumps({'deleted':len(keys),'keysSha256':hashlib.sha256(json.dumps(sorted(keys),separators=(',',':')).encode()).hexdigest(),'remaining':0}))
"""
        result = json.loads(self.ops.docker(*(command + executable + [code]), env=environment,
            data=json.dumps({'prefix': prefix}).encode(), timeout=90))
        require(result.get('remaining') == 0 and type(result.get('deleted')) is int, 'Owned OSS cleanup was not independently verified')
        self.owner['objectsCleaned'] = result; self.save()

    def cleanup(self):
        require(self.owner is not None, 'No runtime resource ownership journal exists')
        failures = []
        # Freeze creators before inventorying their children. A one-shot ps
        # taken while the backend/runner can dispatch would miss new processes.
        creators = self.ops.docker('ps', '-aq', '--no-trunc', '--filter', 'label=io.doorhandle.rehearsal=' + self.project).decode().split()
        if creators:
            rows = json.loads(self.ops.docker('inspect', *creators))
            for service in ('nginx', 'backend', 'mcp-runner', 'detection-worker', 'mem0'):
                for row in rows:
                    labels = row.get('Config', {}).get('Labels') or {}
                    if labels.get('com.docker.compose.service') != service:
                        continue
                    try:
                        require(labels.get('io.doorhandle.rehearsal') == self.project
                                and row['Id'] not in (self.settings['sourceMysqlContainerId'], self.owner['mysqlContainerId']),
                                'A creator is not owned by this runtime')
                        if row['State'].get('Paused'):
                            self.ops.docker('unpause', row['Id'])
                        self.ops.docker('update', '--restart=no', row['Id'])
                        self.ops.docker('stop', '--time', '30', row['Id'], timeout=90)
                        after = json.loads(self.ops.docker('inspect', row['Id']))[0]
                        require(not after['State']['Running'] and not after['State'].get('Restarting') and after['State']['Pid'] == 0
                                and after['HostConfig']['RestartPolicy']['Name'] == 'no', 'A runtime creator did not freeze')
                    except BaseException:
                        failures.append('creator-' + row['Id'])
        if self.config and self.owner.get('ossPrefixProvenEmpty'):
            try:
                self.cleanup_objects()
            except BaseException:
                failures.append('owned-oss-cleanup')
        ids = self.ops.docker('ps', '-aq', '--no-trunc', '--filter', 'label=io.doorhandle.rehearsal=' + self.project).decode().split()
        managed = set(ids)
        pool = self.owner.get('mcpPoolId')
        if pool:
            require(re.fullmatch(r'[a-f0-9]{32}', pool), 'The runtime MCP pool identity is invalid')
            managed.update(self.ops.docker('ps', '-aq', '--no-trunc', '--filter', 'label=doorhandle.mcp.pool=' + pool).decode().split())
        stopped = []
        for cid in sorted(managed):
            try:
                require(re.fullmatch(r'[a-f0-9]{64}', cid) and cid not in (self.settings['sourceMysqlContainerId'], self.owner['mysqlContainerId']),
                        'A source/shared database may never be stopped by runtime cleanup')
                row = json.loads(self.ops.docker('inspect', cid))[0]; labels = row.get('Config', {}).get('Labels') or {}
                ordinary = labels.get('io.doorhandle.rehearsal') == self.project
                child = pool and labels.get('doorhandle.mcp.managed') == 'true' and labels.get('doorhandle.mcp.pool') == pool
                require(ordinary or (child and row['Image'] == self.owner['runtimeMcpImage']
                    and labels.get('doorhandle.mcp.owner') in {str(v['userId']) for v in self.accounts.values()}),
                    'A process does not belong to this exact runtime attempt')
                if row['State'].get('Paused'):
                    self.ops.docker('unpause', cid)
                self.ops.docker('update', '--restart=no', cid)
                self.ops.docker('stop', '--time', '30', cid, timeout=90)
                current = json.loads(self.ops.docker('inspect', cid))[0]
                require(not current['State']['Running'] and not current['State'].get('Restarting') and current['State']['Pid'] == 0
                        and current['HostConfig']['RestartPolicy']['Name'] == 'no', 'An owned process did not actually stop')
                stopped.append(cid)
            except BaseException:
                failures.append('container-' + cid)
        network_id = self.owner.get('mysqlAttachedNetwork')
        if network_id:
            try:
                rows = json.loads(self.ops.docker('network', 'inspect', network_id))
                require(len(rows) == 1 and rows[0].get('Labels', {}).get('io.doorhandle.rehearsal') == self.project,
                        'The fixture network attachment no longer belongs to this runtime')
                if self.owner['mysqlContainerId'] in rows[0].get('Containers', {}):
                    self.ops.docker('network', 'disconnect', network_id, self.owner['mysqlContainerId'])
                node = json.loads(self.ops.docker('inspect', self.owner['mysqlContainerId']))[0]
                require(all(value.get('NetworkID') != network_id for value in node['NetworkSettings']['Networks'].values()),
                        'The shared fixture database remains attached to this runtime')
            except BaseException:
                failures.append('fixture-network-disconnect')
        # Independently enumerate again after every creator/helper operation.
        # Discovery is not a stop proof; all actual generations must read back
        # PID zero and restart=no before STOPPED is advertised.
        final_ids = set(self.ops.docker('ps', '-aq', '--no-trunc', '--filter', 'label=io.doorhandle.rehearsal=' + self.project).decode().split())
        if pool:
            final_ids.update(self.ops.docker('ps', '-aq', '--no-trunc', '--filter', 'label=doorhandle.mcp.pool=' + pool).decode().split())
        for cid in final_ids:
            current = json.loads(self.ops.docker('inspect', cid))[0]
            if current['State']['Running'] or current['State'].get('Restarting') or current['State']['Pid'] != 0 or current['HostConfig']['RestartPolicy']['Name'] != 'no':
                failures.append('late-or-running-' + cid)
        source_after = None
        try:
            if not hasattr(self, 'migration'):
                sys.path.insert(0, str(self.source / 'script/schema'))
                self.migration = module('runtime_cleanup_source_fingerprint', self.source / 'script/schema/compact_migration_runtime.py')
            source_after = self.source_observation()
            require(source_after == self.owner.get('sourceBefore'), 'An original source process, configuration or database identity changed')
        except BaseException:
            failures.append('original-source-readback')
        resource_evidence = self.resources.finish()
        result = {**self.context(), 'status': 'NEEDS_REVIEW' if failures else 'STOPPED', 'project': self.project,
            'stoppedContainers': stopped, 'preservedOwnedVolumes': True,
            'sourceResourcesChanged': source_after is None or source_after != self.owner.get('sourceBefore'),
            'sourceBeforeSha256': self.migration.sha_json(self.owner.get('sourceBefore')) if hasattr(self, 'migration') else None,
            'sourceAfterSha256': self.migration.sha_json(source_after) if hasattr(self, 'migration') else None,
            'objectsCleaned': self.owner.get('objectsCleaned'), 'unresolved': failures,
            'resourceEvidence': resource_evidence}
        file = self.directory / 'cleanup.json'; self.common.write_json(file, result)
        self.owner['cleanup'] = {'file': file.relative_to(self.attempt).as_posix(), 'sha256': sha_file(file), 'status': result['status']}
        self.save('NEEDS_REVIEW' if failures else 'STOPPED')
        failure_file = self.attempt / 'runtime-failure.json'
        if failure_file.exists():
            failure, _ = self.guard.read_private(failure_file)
            require(failure.get('kind') == 'doorhandle-compact-runtime-failure'
                    and all(failure.get(key) == value for key, value in self.context().items() if key != 'kind'),
                    'An existing runtime failure summary belongs to another attempt')
            failure['cleanup'] = self.owner['cleanup']; self.common.write_json(failure_file, failure)
        require(not failures, 'Runtime cleanup is incomplete; private owned resources require review')
        return {'status': 'STOPPED', 'release': self.args.tag, 'cleanupReceiptSha256': sha_file(file),
                'failureReceiptSha256': sha_file(failure_file) if failure_file.exists() else None}

    def failure(self, error, phase):
        file = self.attempt / 'runtime-failure.json'
        value = {**self.context(), 'kind': 'doorhandle-compact-runtime-failure', 'status': 'FAILED_OR_UNKNOWN',
            'project': self.project, 'failedPhase': phase, 'exceptionType': type(error).__name__,
            'completedScenarios': self.owner.get('scenarios', {}) if self.owner else {},
            'cleanup': self.owner.get('cleanup') if self.owner else None}
        if file.exists():
            previous, _ = self.guard.read_private(file)
            require(all(previous.get(key) == expected for key, expected in self.context().items() if key != 'kind'),
                    'A runtime failure summary belongs to another candidate')
            value = {**previous, 'cleanup': value['cleanup']}
        self.common.write_json(file, value)
        return sha_file(file)

    def run_sdk(self, account, steps, text, model=None, marker=None, *, session=None,
                expected_phase='COMPLETED', approve_plan=True):
        require(expected_phase in {'COMPLETED', 'WAITING_PLAN', 'WAITING_INPUT', 'WAITING_CHILD'},
                'Unsupported SDK scenario terminal expectation')
        marker = marker or 'runtime-' + uuid.uuid4().hex
        session = session or self.request(account, 'POST', '/api/chat-assistant/sessions')['sessionId']
        if model:
            selection = self.request(account, 'GET', '/api/agent/conversations/' + session + '/model-selection')
            self.request(account, 'POST', '/api/agent/conversations/' + session + '/model-selection',
                         {'modelId': model, 'revision': selection['revision'], 'requestId': uuid.uuid4().hex})
        # Preserve slash-command position and the actual user request. Ordinary
        # read-only requests retain their real read-only prefix; complex work
        # still passes the application's plan approval protocol.
        content = text + ' ' + marker
        simple = (not content.startswith('/plan') and len(content) < 160
            and re.match(r'^(查询|查看|列出|读取|获取|显示|统计|你好|谢谢|帮助|/help|/skills)', content)
            and not re.search(r'(然后|同时|并|生成|导出|分析|调研|比较|对比|以及|创建|修改|编辑|删除|移除|更新|写入|分配|分派|审批|安装|执行|发布|重试|恢复|取消)', content))
        script = list(steps)
        if not simple and not content.startswith('/') and (not script or script[0].get('tool') != 'submit_plan'):
            script.insert(0, {'tool': 'submit_plan', 'arguments': {
                'title': '本轮隔离验收请求', 'text': content,
                'tasks': [{'title': '按本轮请求调用原有工具并核对回执', 'status': 'pending'}]}})
        self.fixture('POST', '/__fixture/arm', {'marker': marker, 'steps': script})
        catalog = self.request(account, 'GET', '/agui/catalog')
        request_id = uuid.uuid4().hex
        stream = self.request(account, 'POST', '/agui/run', {'threadId': session, 'runId': request_id,
            'messages': [{'id': uuid.uuid4().hex, 'role': 'user', 'content': content}]},
            headers={'Accept': 'text/event-stream', 'X-Agent-Id': catalog['mainAgent']})
        require(isinstance(stream, bytes), 'Real SDK did not return AG-UI events')
        events = [json.loads(line[5:].strip()) for line in stream.decode('utf8').splitlines() if line.startswith('data:') and line[5:].strip()]
        require(any(item.get('type') == 'RUN_FINISHED' for item in events)
                and not any(item.get('type') == 'RUN_ERROR' for item in events), 'Actual SDK execution did not complete')
        metadata = [item['value'] for item in events
                    if item.get('type') == 'CUSTOM' and item.get('name') == 'doorhandle.execution.v1']
        require(len(metadata) == 1 and re.fullmatch(r'[a-f0-9-]{36}', metadata[0].get('runId', '')),
                'Actual SDK response lacks its durable execution metadata')
        initial_run = metadata[0]['runId']
        account_id = self.accounts[account]['userId']
        original = self.db.one("SELECT JSON_OBJECT('requestKey',request_key,'sessionId',session_id,'owner',user_id)"
            + ' FROM agent_run WHERE run_id=' + self.db.literal(initial_run) + ';')
        require(original == {'requestKey': request_id, 'sessionId': session, 'owner': account_id},
                'AG-UI request key does not bind the actual owner/session/durable run')
        path_prefix = '/api/agent/conversations/' + session + '/workbench'
        logical_task = None; approvals = []; end = time.monotonic() + 240
        while time.monotonic() < end:
            board = self.request(account, 'GET', path_prefix)
            executions = [item for item in board['items'] if item['kind'] == 'EXECUTION']
            require(len(executions) == 1, 'Actual SDK main execution is missing or ambiguous')
            execution = executions[0]
            task = execution['data'].get('logicalTaskId')
            require(task and (logical_task is None or logical_task == task),
                    'A continuation silently started another logical task')
            logical_task = task
            if execution['status'] == expected_phase:
                break
            require(execution['status'] not in {'CANCELLED', 'NEEDS_REVIEW', 'UNKNOWN'},
                    'Actual SDK work requires manual recovery or was cancelled')
            if execution['status'] == 'WAITING_PLAN' and approve_plan and expected_phase != 'WAITING_PLAN':
                pending = [item for item in board['items'] if item['kind'] == 'PLAN' and item['status'] == 'PENDING'
                           and item['data'].get('logicalTaskId') == task]
                require(len(pending) == 1, 'A waiting execution lacks its actual persisted plan')
                plan = pending[0]
                # The initial SSE has committed its checkpoint before returning.
                # Later automatic continuations may still be committing a wait.
                ready = self.db.one("SELECT JSON_OBJECT('ready',workbench_yield_ready) FROM workflow_instance"
                    + " WHERE kind='WORKBENCH_EXECUTION' AND owner_user_id=" + str(account_id)
                    + ' AND session_id=' + self.db.literal(session) + ';')
                if ready.get('ready') in (True, 1):
                    approved = self.request(account, 'POST', path_prefix + '/' + plan['id'], {
                        'requestId': uuid.uuid4().hex, 'revision': plan['revision'], 'action': 'approve-plan', 'input': {}})
                    require(approved['status'] == 'APPROVED', 'Actual HTTP plan approval was not persisted')
                    approvals.append(plan['id'])
            time.sleep(0.25)
        else:
            raise ValueError('Actual SDK work did not reach its required persisted phase')
        run_id = execution['data']['runId']
        settled_states = {'COMPLETED'} if expected_phase == 'COMPLETED' else {'INTERRUPTED', 'COMPLETED'}
        settlement_end = time.monotonic() + 20
        while time.monotonic() < settlement_end:
            run = self.request(account, 'GET', '/api/agent/runs/' + run_id)
            require(run['sessionId'] == session and run['status'] not in {'ERROR', 'CANCELLED'},
                    'Actual SDK journal did not settle with its real workbench state')
            saved = self.db.one("SELECT JSON_OBJECT('n',COUNT(*)) FROM chat_message WHERE execution_run_id="
                + self.db.literal(run_id) + ' AND execution_owner_user_id=' + str(account_id) + ';')
            if run['status'] in settled_states and saved['n'] == 1:
                break
            time.sleep(0.1)
        else:
            raise ValueError('Actual SDK journal and assistant message did not durably settle')
        runs = self.request(account, 'GET', '/api/agent/runs?sessionId=' + session + '&limit=100')
        path = self.directory / ('agui-' + request_id + '.json')
        self.common.write_json(path, {'runId': run_id, 'sessionId': session,
            'events': [{'type': item.get('type'), 'runId': item.get('runId')} for item in events],
            'streamSha256': hashlib.sha256(stream).hexdigest()})
        return {'runId': run_id, 'initialRunId': initial_run, 'requestKey': request_id,
                'runIds': [row['runId'] for row in runs], 'sessionId': session, 'logicalTaskId': logical_task,
                'phase': execution['status'], 'approvedPlans': approvals, 'marker': marker,
                'events': events, 'streamSha256': hashlib.sha256(stream).hexdigest()}

    def invoke_model(self, account, model):
        return self.run_sdk(account, [{'text': 'Owned runtime quota response'}], '返回一段本轮验收文字', model)

    def create_report_draft(self, account, task, title, narrative):
        marker = 'runtime-report-' + self.token
        result = self.run_sdk(account, [
            {'tool': 'delegate_report_assistant', 'arguments': {'question': marker + ' 为任务 ' + task + ' 保存私人草稿'}},
            {'tool': 'create_report_draft', 'arguments': {'taskId': task, 'title': title, 'narrative': narrative}},
            {'text': '候选报告草稿已保存 尚未审批'}, {'text': '报告草稿已保存 尚未审批'}],
            marker + ' 请为真实任务 ' + task + ' 保存报告草稿', marker=marker)
        rows = self.db.query("SELECT JSON_OBJECT('reportId',report_id) FROM quality_report WHERE task_id="
            + self.db.literal(task) + ' AND owner_user_id=' + str(self.accounts[account]['userId']) + ' AND title=' + self.db.literal(title) + ';')
        require(len(rows) == 1, 'Actual SDK did not persist exactly one report draft')
        return {**result, 'reportId': rows[0]['reportId']}

    def bridge(self, path, body):
        return self.rehearsal.Rehearsal.bridge(self, path, body)

    def seed_memory(self, owner, session):
        return self.rehearsal.Rehearsal.seed_memory(self, owner, session)

    def run(self):
        self.prepare(); self.start()
        self.publish_scripted_model()
        self.http.run_http_scenarios(self)
        self.worker_scenario()
        fence = self.worker_fence.run(self)
        self.record('detection-pth-worker-kafka-receipts', {**self.worker_observations, 'actualUnknownResultFence': fence})
        self.http.run_report_scenario(self)
        self.sdk_scenario(); self.mcp_scenario(); self.skill_scenario(); self.memory_scenario(); self.recovery_scenario()
        required = {item['id'] for item in self.profile['runtimeAcceptance']['scenarios']}
        require(set(self.owner['scenarios']) == required, 'Not every mandatory runtime scenario actually completed')
        state = self.fixture('GET', '/__fixture/state')
        require(state.get('kind') == 'doorhandle-owned-scripted-model' and state.get('modelRequests', 0) > 0
                and state.get('embeddingRequests', 0) > 0 and state.get('markers')
                and all(item.get('remainingSteps') == 0 and item.get('calls', 0) > 0 for item in state['markers']),
                'The actual model/embedding interactions did not consume their intended bounded scripts')
        self.owner['finalFixtureState'] = state
        self.save('ASSERTIONS_PASSED')
        self.cleanup()
        require(self.resources.error is None, 'Runtime resource observation failed; bounded acceptance cannot pass')
        daemons = set(self.config['services']) - {'kafka-init', 'kafka-storage-init', 'higress-seed', 'higress-config'}
        observed = {row['service'] for row in self.resources.summary['containers'].values() if row['peakBytes'] > 0}
        require(daemons <= observed, 'An actual service memory peak was not observed; retain the incomplete resource evidence')
        validate_resource_evidence(self.resources.summary, self.resources.raw.read_bytes(), self.context(), self.project)
        require(set(self.owner.get('nativeVerifications', {})) == {'after-start', 'after-restart', 'after-volume-restore'},
                'Complete native RAG startup/restart/new-volume recovery was not verified')
        proof = {**self.context(), 'status': 'PASS', 'project': self.project,
            'legacyData': {'candidateSha256': self.legacy_candidate_sha, 'ragManifestSha256': self.legacy_candidate['ragManifestSha256'],
                'legacyKafkaFiles': self.legacy_candidate['legacyKafkaFiles'], 'legacyKafkaBytes': self.legacy_candidate['legacyKafkaBytes'],
                'legacyKafkaReplay': self.legacy_candidate['legacyKafkaReplay'],
                'originalLocalMem0Records': 32, 'eligibleLocalMem0Records': 30, 'activatedLocalMem0Records': 0, 'archivedLocalMem0Records': 2,
                'localMem0SemanticStatus': 'NOT_ACTIVATED_SEMANTIC_NOT_VERIFIED', 'productionPromotionAllowed': False,
                'verifications': self.owner.get('nativeVerifications', {}), 'materialization': self.owner['nativeMaterialization']},
            'loadScope': {'profile': RUNTIME_PROFILE, 'productionPerformanceVerified': False,
                          'productionCapacityVerified': False, 'allMandatoryScenariosRequired': True},
            'resourceEvidence': {'file': (self.directory / 'resource-summary.json').relative_to(self.attempt).as_posix(),
                                 'sha256': sha_file(self.directory / 'resource-summary.json')},
            'migrationReceiptSha256': self.owner['migrationReceiptSha256'],
            'initialTargetSnapshotSha256': self.owner['initialTargetSnapshotSha256'],
            'actualServerUuid': self.owner['serverUuid'], 'actualMysqlPort': self.owner['mysqlPort'],
            'images': {key: self.images[key] for key in ('backend', 'nginx', 'mem0', 'detection-worker')},
            'scenarios': self.owner['scenarios'], 'cleanup': self.owner['cleanup'], 'paidModelCalls': 0,
            'modelIsolation': {'fixtureSourceSha256': self.owner['modelFixtureSourceSha256'],
                               'ossAdapterSourceSha256': self.owner['ossFixtureSourceSha256'],
                               'observedInternalNetworks': self.owner['observedModelNetworks'],
                               'fixtureState': self.owner['finalFixtureState'],
                               'activeModelRevision': self.owner['modelRevision'],
                               'internalNetworksVerified': True, 'providerCredentialsRemoved': True}}
        self.common.write_json(self.public_file, proof)
        self.save('VERIFIED')
        return {'status': 'PASS', 'release': self.args.tag, 'runtimeReceiptSha256': sha_file(self.public_file),
                'runtimeScenarios': len(required), 'ownedCleanup': 'STOPPED'}

    def publish_scripted_model(self):
        versions = self.request('supervisor', 'GET', '/api/agent/model-config')
        active = [row for row in versions['versions'] if row['revision'] == versions['activeRevision']]
        require(len(active) == 1, 'The active governed model revision is unavailable')
        document = copy.deepcopy(active[0]['document'])
        choices = [item['id'] for item in document['models'] if item['id'].startswith('deepseek:')]
        require(choices, 'This owned fixture requires an actually configured Chat Completions provider')
        self.model_id = choices[0]
        for item in document['models']:
            item['enabled'] = item['id'] == self.model_id
        document.update(defaultModel=self.model_id, memoryModel=self.model_id, fallbackModels=[], fallbackEnabled=False)
        draft = self.request('supervisor', 'POST', '/api/agent/model-config/drafts', {
            'baseRevision': versions['activeRevision'], 'requestId': 'runtime-model-' + self.token,
            'document': document, 'apiKeys': {'deepseek': 'runtime-fixture'}})
        revision = draft['revision']
        probe = self.request('supervisor', 'POST', '/api/agent/model-config/' + str(revision) + '/json-probe',
                             {'modelId': self.model_id, 'requestId': 'runtime-json-' + self.token})
        require(probe['status'] == 'PASSED', 'Actual local JSON compatibility probe did not pass')
        self.request('supervisor', 'POST', '/api/agent/model-config/' + str(revision) + '/validate',
                     {'requestId': 'runtime-model-validate-' + self.token})
        published = self.request('supervisor', 'POST', '/api/agent/model-config/' + str(revision) + '/publish',
                                 {'requestId': 'runtime-model-publish-' + self.token})
        require(published['status'] == 'PUBLISHED', 'Synthetic provider credential was not published by the real API')
        catalog = self.request('inspector', 'GET', '/agui/models')
        entries = catalog.get('models', catalog.get('entries', []))
        require([item['id'] for item in entries if item.get('configured')] == [self.model_id],
                'Runtime must expose only the actually published local Chat Completions model')
        self.owner['modelRevision'] = revision; self.owner['modelId'] = self.model_id; self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('run', 'cleanup', 'status'))
    for name in ('root', 'runtime', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id', 'settings'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(); instance = None
    try:
        instance = Runtime(args)
        if args.phase == 'run':
            result = instance.run()
        elif args.phase == 'cleanup':
            require(instance.owner, 'No runtime attempt was prepared'); result = instance.cleanup()
        else:
            result = {'status': instance.owner['phase'] if instance.owner else 'NOT_PREPARED', 'release': args.tag}
        print(json.dumps(result)); return 0
    except BaseException as error:
        failure_sha = None
        if instance:
            phase = instance.owner.get('phase', 'UNKNOWN') if instance.owner else 'NOT_PREPARED'
            if instance.owner:
                try:
                    instance.save('FAILED_OR_UNKNOWN'); instance.cleanup()
                except BaseException:
                    pass
            try:
                failure_sha = instance.failure(error, phase)
            except BaseException:
                pass
        if args.phase == 'cleanup':
            cleanup_sha = None
            if instance and instance.owner:
                try:
                    file = instance.directory / 'cleanup.json'
                    value, cleanup_sha = instance.guard.read_private(file)
                    require(all(value.get(key) == expected for key, expected in instance.context().items()),
                            'Cleanup artifact belongs to another candidate')
                except BaseException:
                    cleanup_sha = None
            print(json.dumps({'status': 'NEEDS_REVIEW', 'release': args.tag,
                'cleanupReceiptSha256': cleanup_sha, 'failureReceiptSha256': failure_sha}))
        print('Runtime acceptance did not pass. Keep production gates closed and preserve private ECS evidence.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
