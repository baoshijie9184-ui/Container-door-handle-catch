#!/usr/bin/env python3
"""Provision or stop this Jenkins build's disposable compact MySQL fixtures on ECS.

This does not execute project tests, deploy applications, start ECS, write the
original database, or remove source dumps/data/evidence. Preparation is fail-stop;
an interrupted attempt is retained and cannot be reused by another build.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import threading
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener


GIB = 1024 ** 3
PROJECT = 'doorhandlecatch-monolith'
INSTANCE = 'i-2zeieuov2aum486jm1ek'
TAG = re.compile(r'ci-[1-9][0-9]*-[a-f0-9]{12}')
SHA = re.compile(r'[a-f0-9]{64}')
CID = re.compile(r'[a-f0-9]{64}')
IDENT = re.compile(r'[a-z][a-z0-9_]{0,63}')
LABEL = 'io.doorhandle.compact-fixtures'
MIB = 1024 ** 2
DISK_RESERVE = 2 * GIB
DISK_OVERSHOOT = 256 * MIB
CONTROLLER_AS = 3 * GIB
CONTROLLER_RSS = 2 * GIB
MYSQL_MEMORY = 1536 * MIB
SOURCE_CLIENT_AS_KIB = 512 * 1024
OWNER_ENV = 'DOORHANDLE_PREPARE_OWNER'
GROUP_ENV = 'DOORHANDLE_PREPARE_GROUP'
EXPORT_ENV = 'DOORHANDLE_CI_EXPORT_TOKEN'


class ResourceLimitExceeded(ValueError):
    pass


def controller_address_limit():
    import resource
    require(sys.platform == 'linux', 'Controlled preparation executes only on ECS Linux')
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    require((soft == resource.RLIM_INFINITY or soft >= CONTROLLER_AS)
            and (hard == resource.RLIM_INFINITY or hard >= CONTROLLER_AS), 'Controller needs a 3 GiB address-space boundary')
    resource.setrlimit(resource.RLIMIT_AS, (CONTROLLER_AS, CONTROLLER_AS))
    require(resource.getrlimit(resource.RLIMIT_AS) == (CONTROLLER_AS, CONTROLLER_AS), 'Controller address-space limit was not applied')
    return list(resource.getrlimit(resource.RLIMIT_AS))


def proc_identity(pid):
    try:
        text = Path('/proc/' + str(pid) + '/stat').read_text()
        fields = text[text.rindex(') ') + 2:].split()
        return {'pid': pid, 'parent': int(fields[1]), 'group': int(fields[2]),
                'session': int(fields[3]), 'startTicks': int(fields[19]),
                'rssBytes': int(fields[21]) * os.sysconf('SC_PAGE_SIZE')}
    except (FileNotFoundError, ProcessLookupError):
        return None


def owned_tree_memory(pid):
    records = {}
    for path in Path('/proc').iterdir():
        if path.name.isdecimal():
            try:
                record = proc_identity(int(path.name))
                if record:
                    records[record['pid']] = record
            except (PermissionError, ValueError):
                continue
    owned = {pid}
    while True:
        added = {key for key, value in records.items() if value['parent'] in owned}
        if added <= owned:
            break
        owned.update(added)
        require(len(owned) <= 256, 'Owned controller process tree exceeded its bound')
    return sum(records[key]['rssBytes'] for key in owned if key in records)


def group_members(group, owner, claim):
    result = []
    for path in Path('/proc').iterdir():
        if not path.name.isdecimal():
            continue
        try:
            identity = proc_identity(int(path.name))
            if identity is None or identity['group'] <= 1 or identity['group'] != identity['session']:
                continue
            if group is not None and identity['group'] != group:
                continue
            # Environments are inspected silently for exact ownership markers;
            # neither the environment nor any other value is returned/logged.
            environment = (path / 'environ').read_bytes().split(b'\0')
            if (OWNER_ENV + '=' + owner).encode() in environment and (GROUP_ENV + '=' + claim).encode() in environment:
                result.append(identity)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return result


def stop_owned_group(group, owner, claim):
    require(type(group) is int and group > 1 and group != os.getpgrp()
            and re.fullmatch(r'[a-f0-9]{32}', owner) and re.fullmatch(r'[a-f0-9]{32}', claim),
            'Explicit owned command session required')
    for operation in (signal.SIGTERM, signal.SIGKILL):
        members = group_members(group, owner, claim)
        if not members:
            return
        original = members[0]; current = proc_identity(original['pid'])
        require(current is not None and current['startTicks'] == original['startTicks']
                and current['group'] == current['session'] == group
                and any(item['pid'] == current['pid'] and item['startTicks'] == current['startTicks']
                        for item in group_members(group, owner, claim)),
                'Owned session changed during cancellation')
        os.killpg(group, operation)
        deadline = time.monotonic() + 2
        while group_members(group, owner, claim) and time.monotonic() < deadline:
            time.sleep(0.05)
    require(not group_members(group, owner, claim), 'Owned command group did not exit')


def archive_inventory(archive, commit, source_sha, own_script, block_bytes=4096):
    """Measure declared source allocation before extracting any member."""
    require(digest(archive) == source_sha, 'Git archive digest differs from Jenkins')
    require(type(block_bytes) is int and 512 <= block_bytes <= MIB and not block_bytes & (block_bytes - 1),
            'Actual filesystem block allocation unit required')
    seen, total, allocated, directories, own_sha, budget_bytes = set(), 0, 0, set(), None, None
    with tarfile.open(archive, 'r:gz') as package:
        for entry in package:
            path = Path(entry.name)
            require(not path.is_absolute() and '..' not in path.parts and '\\' not in entry.name
                    and path.parts and path.parts[0] not in ('work', '.git', 'artifacts')
                    and (entry.isfile() or entry.isdir()) and entry.name not in seen,
                    'Unsafe source archive member')
            seen.add(entry.name); total += entry.size
            require(len(seen) <= 50000 and 0 <= entry.size <= 32 * MIB and total <= 512 * MIB,
                    'Fixed source archive exceeds the bounded source contract')
            directories.update(str(parent) for parent in path.parents if str(parent) != '.')
            if entry.isdir():
                directories.add(str(path))
            else:
                allocated += ((entry.size + block_bytes - 1) // block_bytes) * block_bytes
            if entry.name in ('script/jenkins/prepare-compact-fixtures.py', 'script/jenkins/ecs-resource-budget.py'):
                require(entry.isfile() and entry.size <= MIB, 'Bounded fixed controller module required')
                content = package.extractfile(entry).read(MIB + 1)
                require(len(content) == entry.size, 'Controller member was truncated')
                if entry.name.endswith('/prepare-compact-fixtures.py'):
                    own_sha = hashlib.sha256(content).hexdigest()
                else:
                    budget_bytes = content
        require(package.pax_headers.get('comment') == commit, 'Archive PAX commit differs')
    require(own_sha == digest(own_script) and budget_bytes is not None,
            'Provisioner and budget module must be this fixed source archive')
    return {'archiveDeclaredBytes': total, 'archiveAllocatedBoundBytes': allocated + len(directories) * block_bytes,
            'archiveMemberCount': len(seen), 'directoryCount': len(directories)}, budget_bytes


SOURCE_CANCEL = r'''
set -eu
token=$1
case "$token" in *[!a-f0-9]*|'') exit 2;; esac
[ ${#token} -eq 32 ] || exit 2
matches() { [ -r "/proc/$1/environ" ] && tr '\000' '\n' < "/proc/$1/environ" 2>/dev/null | grep -Fqx -- "DOORHANDLE_CI_EXPORT_TOKEN=$token"; }
ticks() { IFS= read -r value < "/proc/$1/stat" || return 1; rest=${value##*) }; set -- $rest; [ $# -ge 20 ] || return 1; shift 19; printf '%s' "$1"; }
for round in TERM KILL CHECK; do
  count=0
  for entry in /proc/[0-9]*/environ; do
    pid=${entry#/proc/}; pid=${pid%/environ}
    [ "$pid" -gt 1 ] || continue
    matches "$pid" || continue
    IFS= read -r comm < "/proc/$pid/comm" || continue
    case "$comm" in mysql|mysqldump|sh) ;; *) exit 3;; esac
    first=$(ticks "$pid") || continue
    case "$first" in *[!0-9]*|'') exit 4;; esac
    matches "$pid" || continue
    second=$(ticks "$pid") || continue
    [ "$first" = "$second" ] || continue
    count=$((count+1)); [ "$count" -le 64 ] || exit 5
    [ "$round" != CHECK ] || exit 6
    kill -"$round" "$pid" 2>/dev/null || true
    printf '%s %s %s %s\n' "$round" "$pid" "$first" "$comm"
  done
  [ "$round" = CHECK ] || sleep 1
done
'''


class ControlledSubprocess:
    """A module-local subprocess proxy; it never monkeypatches other code."""
    def __init__(self, monitor):
        self.monitor = monitor
    def __getattr__(self, name):
        return getattr(subprocess, name)
    def Popen(self, arguments, **kwargs):
        return self.monitor.popen(arguments, **kwargs)
    def run(self, arguments, *, input=None, capture_output=False, timeout=None, check=False, **kwargs):
        if input is not None:
            require('stdin' not in kwargs, 'Controlled stdin is explicit')
            kwargs['stdin'] = subprocess.PIPE
        if capture_output:
            require('stdout' not in kwargs and 'stderr' not in kwargs, 'Controlled output capture is explicit')
            kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process = self.Popen(arguments, **kwargs)
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except BaseException:
            self.monitor.stop_group(process)
            process.wait(timeout=5)
            raise
        result = subprocess.CompletedProcess(arguments, process.returncode, stdout, stderr)
        if check and result.returncode:
            raise subprocess.CalledProcessError(result.returncode, arguments, stdout, stderr)
        return result


class PreparationMonitor:
    """Independent disk/memory pressure watcher and bounded owned measurement."""
    def __init__(self, preparation, budget, artifacts):
        import resource
        self.preparation, self.budget, self.artifacts = preparation, budget, artifacts
        require(sys.platform == 'linux' and threading.current_thread() is threading.main_thread(),
                'Resource controller must own the ECS main thread')
        controller_address_limit()
        self.token = secrets.token_hex(16); self.processes = {}; self.process_lock = threading.Lock()
        self.lock = threading.RLock(); self.measure_lock = threading.Lock()
        self.stop = threading.Event(); self.failed = threading.Event(); self.cleaning = False
        self.failure = None; self.current = None; self.previous = None; self.phase_index = 0
        self.phase_observations = None
        self.source = None; self.last = None; self.measured_at = 0.0
        self.sudo, self.timeout, self.du = [canonical(shutil.which(name)) for name in ('sudo', 'timeout', 'du')]
        self.file = preparation.work / 'resource-probes.jsonl'
        self.stream = self.file.open('x', encoding='utf8'); os.chmod(self.file, 0o600)
        self.group_file = preparation.work / 'owned-process-groups.jsonl'
        self.group_stream = self.group_file.open('x', encoding='utf8'); os.chmod(self.group_file, 0o600)
        self.claim_directory = preparation.work / 'owned-command-claims'
        self.claim_directory.mkdir(mode=0o700)
        self.proxy = ControlledSubprocess(self)
        self.old_signal = signal.getsignal(signal.SIGUSR1)
        signal.signal(signal.SIGUSR1, lambda *_: (_ for _ in ()).throw(ResourceLimitExceeded('Preparation resource supervision failed')))
        self.origin = self.measure()
        self.collector = threading.Thread(target=self.collect, name='owned-fixture-allocation', daemon=True)
        self.watcher = threading.Thread(target=self.watch, name='owned-fixture-pressure', daemon=True)
        self.collector.start(); self.watcher.start()
        self.enforcement = {'controllerRlimitAsBytes': CONTROLLER_AS, 'controllerRlimitReadback': list(resource.getrlimit(resource.RLIMIT_AS)),
            'hostTreeRssWatchLimitBytes': CONTROLLER_RSS, 'nativeSourceClientRlimitAsBytes': SOURCE_CLIENT_AS_KIB * 1024,
            'measurement': 'SUDO_TIMEOUT_DU_ALLOCATED_BYTES', 'duScope': str(preparation.attempt),
            'maxProbeIntervalSeconds': 2, 'diskReserveBytes': DISK_RESERVE, 'diskOvershootBytes': DISK_OVERSHOOT,
            'controllerSourceSha256': artifacts['sourceSha256'], 'ownerToken': self.token}
        write_json(preparation.work / 'resource-enforcement.json', self.enforcement)
        self.enforcement_sha = digest(preparation.work / 'resource-enforcement.json')
        preparation.journal.update(resourceOwnerToken=self.token, sourceExportToken=self.token,
                                   resourceEnforcementSha256=self.enforcement_sha)
        preparation.save('RESOURCE_CONTROLLER_READY')

    def popen(self, arguments, **kwargs):
        self.check()
        require(not kwargs.get('shell') and kwargs.get('start_new_session', True), 'Owned commands require their own process session')
        kwargs['start_new_session'] = True
        environment = dict(kwargs.get('env') or {key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')})
        claim = secrets.token_hex(16)
        environment[OWNER_ENV] = self.token; environment[GROUP_ENV] = claim; kwargs['env'] = environment
        # Persist the exact capability before spawning. A signal between exec
        # and PID registration must not orphan an owned command/session.
        intent = {'kind': 'doorhandle-owned-command-intent', 'ownerToken': self.token,
                  'sourceCommit': self.preparation.args.commit, 'groupToken': claim,
                  'argumentsSha256': hashlib.sha256(json.dumps(list(map(str, arguments))).encode()).hexdigest()}
        write_json(self.claim_directory / (claim + '.json'), intent)
        process = subprocess.Popen(arguments, **kwargs)
        identity = proc_identity(process.pid)
        with self.process_lock:
            self.processes[process.pid] = (process, identity, claim)
            require(len(self.processes) <= 20000, 'Owned command registry exceeded its bound')
            record = {'ownerToken': self.token, 'sourceCommit': self.preparation.args.commit,
                'pid': process.pid, 'groupToken': claim, 'process': identity,
                'argumentsSha256': hashlib.sha256(json.dumps(list(map(str, arguments))).encode()).hexdigest()}
            self.group_stream.write(json.dumps(record, sort_keys=True) + '\n'); self.group_stream.flush()
        return process

    def stop_group(self, process):
        with self.process_lock:
            registered = self.processes.get(process.pid)
        if registered is None:
            return
        stop_owned_group(process.pid, self.token, registered[2])
        if process.poll() is None:
            process.wait(timeout=5)
        require(process.poll() is not None, 'Owned command group did not exit')

    def check(self):
        if not self.cleaning:
            require(not self.failed.is_set(), 'Owned preparation supervision has failed')

    def fixture_memory(self):
        journal = self.preparation.journal
        if not journal.get('containerId'):
            return 0, 0
        row = self.preparation.inspect_owned()
        require(row['HostConfig'].get('Memory') == MYSQL_MEMORY and row['HostConfig'].get('MemorySwap') == MYSQL_MEMORY,
                'Owned fixture memory cgroup differs')
        if not row['State'].get('Pid'):
            return 0, int(bool(row['State'].get('OOMKilled')))
        relative = next(line.split(':', 2)[2] for line in Path('/proc/' + str(row['State']['Pid']) + '/cgroup').read_text().splitlines() if line.startswith('0::'))
        require(relative.startswith('/') and '..' not in Path(relative).parts, 'Owned fixture cgroup identity differs')
        path = Path('/sys/fs/cgroup') / relative.lstrip('/')
        events = dict(line.split() for line in (path / 'memory.events').read_text().splitlines())
        return int((path / 'memory.current').read_text()), int(events.get('oom_kill', 0))

    def measure(self):
        with self.measure_lock:
            # Native timeout owns/cancels its root du child. No arbitrary path or
            # shell is accepted, and no source/production data directory is read.
            result = subprocess.run([str(self.sudo), '-n', str(self.timeout), '--kill-after=0.2s', '1.2s',
                str(self.du), '-B1', '-x', '-s', '--', str(self.preparation.attempt)],
                capture_output=True, timeout=2, env={'PATH': os.environ.get('PATH', ''), 'LC_ALL': 'C'})
            require(result.returncode == 0 and len(result.stdout) < 4096, 'Owned physical allocation measurement failed or exceeded its deadline')
            number, path = result.stdout.decode().strip().split('\t', 1)
            require(number.isdecimal() and path == str(self.preparation.attempt), 'Allocation measurement escaped the owned attempt')
            memory = {line.split(':', 1)[0]: int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines()}
            disk = os.statvfs(self.preparation.attempt)
            fixture, oom = self.fixture_memory()
            value = {'ownerToken': self.token, 'sourceCommit': self.preparation.args.commit,
                'capturedAtUtc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'diskTotalBytes': disk.f_blocks * disk.f_frsize, 'diskAvailableBytes': disk.f_bavail * disk.f_frsize,
                'memoryAvailableBytes': memory['MemAvailable'], 'ownedDiskBytes': int(number),
                'ownedMemoryBytes': owned_tree_memory(os.getpid()) + fixture, 'oomKills': oom,
                'ownedDiskMeasurement': 'ALLOCATED_BLOCKS_DU', 'ownedFixtureMemoryBytes': fixture}
            with self.lock:
                self.last = value; self.measured_at = time.monotonic()
                if self.current is not None and self.phase_observations is not None:
                    observed = self.phase_observations
                    observed['probeCount'] += 1
                    observed['peakOwnedDiskBytes'] = max(observed['peakOwnedDiskBytes'], value['ownedDiskBytes'])
                    observed['peakOwnedMemoryBytes'] = max(observed['peakOwnedMemoryBytes'], value['ownedMemoryBytes'])
                    observed['minimumFreeDiskBytes'] = min(observed['minimumFreeDiskBytes'], value['diskAvailableBytes'])
                    observed['minimumAvailableMemoryBytes'] = min(observed['minimumAvailableMemoryBytes'], value['memoryAvailableBytes'])
                self.stream.write(json.dumps(value, sort_keys=True) + '\n'); self.stream.flush()
            return value

    def collect(self):
        try:
            while not self.stop.wait(0.5):
                self.measure()
        except BaseException as error:
            self.fail(error, worker='collector')

    def fail(self, error, *, worker):
        details = failure_details(error)
        with self.lock:
            if self.failed.is_set() or self.stop.is_set():
                return
            self.failure = {'status': 'FAILED_OR_UNKNOWN', 'reason': details['errorType'],
                            'worker': worker if worker in ('collector', 'watcher') else 'unknown',
                            **details, 'ownerToken': self.token,
                            'lastProbeAgeSeconds': max(0, time.monotonic() - self.measured_at),
                            'stopScope': 'OWNED_ATTEMPT_ONLY', 'evidenceRetained': True}
            self.failed.set()
        try:
            write_json(self.preparation.work / 'resource-failure.json', self.failure)
        except BaseException:
            pass
        if not self.stop.is_set():
            os.kill(os.getpid(), signal.SIGUSR1)

    def watch(self):
        try:
            previous = time.monotonic()
            while not self.stop.wait(0.5):
                current = time.monotonic()
                require(current - previous <= 2, 'Independent pressure monitor missed its deadline')
                previous = current
                with self.lock:
                    require(current - self.measured_at <= 2, 'Owned allocation/memory monitor is stale')
                    probe = dict(self.last); phase = self.current
                disk = os.statvfs(self.preparation.attempt)
                probe['diskAvailableBytes'] = disk.f_bavail * disk.f_frsize
                probe['memoryAvailableBytes'] = next(int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
                require(probe['diskAvailableBytes'] >= DISK_RESERVE + DISK_OVERSHOOT,
                        'Actual disk reserve or overshoot was consumed')
                require(probe['memoryAvailableBytes'] >= GIB, 'Actual host memory reserve was consumed')
                if phase:
                    result = self.budget.check_phase(phase, probe)
                    require(result['status'] == 'MEASUREMENT_ADMITTED', 'Current owned phase exceeded its admitted resource envelope')
        except BaseException as error:
            self.fail(error, worker='watcher')

    def admit(self, name, growth, inputs, *, mysql=False, java=False):
        self.check(); probe = self.measure(); self.phase_index += 1
        enforcement = {'independentMonitor': self.watcher.is_alive() and self.collector.is_alive(),
            'ownedPhysicalDiskMeasured': True, 'registeredProcessGroups': True, 'controllerAddressSpaceLimited': True,
            'maxProbeIntervalSeconds': 2, 'diskOvershootBytes': DISK_OVERSHOOT,
            'sourceExportCancellation': self.source is not None, 'mysqlCgroupLimitBytes': MYSQL_MEMORY if mysql else 0}
        specification = {'ownerToken': self.token, 'sourceCommit': self.preparation.args.commit,
            'sourceSha256': self.artifacts['sourceSha256'], 'applicationJarSha256': self.artifacts['applicationJarSha256'],
            'enforcementEvidenceSha256': self.enforcement_sha, 'phase': name,
            'baselineProbe': probe, 'attemptBaselineProbe': self.origin,
            'previousPhaseReceiptSha256': self.previous, 'growthEnvelopeBytes': growth,
            'memoryAdmissionBytes': CONTROLLER_AS + (MYSQL_MEMORY if mysql else 0) + (2 * GIB if java else 0)
                + (SOURCE_CLIENT_AS_KIB * 1024 if name.startswith('source-') else 0),
            'ownedMemoryLimitBytes': CONTROLLER_RSS + (MYSQL_MEMORY if mysql else 0),
            'measuredInputs': inputs, 'enforcement': enforcement}
        phase = self.budget.plan_phase(specification)
        admission = self.budget.check_phase(phase, probe)
        stem = 'resource-phase-' + str(self.phase_index).zfill(2) + '-' + name
        write_json(self.preparation.work / (stem + '-plan.json'), phase)
        write_json(self.preparation.work / (stem + '-admission.json'), admission)
        require(admission['status'] == 'MEASUREMENT_ADMITTED', 'Actual ECS cannot admit this controlled preparation phase')
        with self.lock:
            self.current = phase
            self.phase_observations = {'probeCount': 1, 'peakOwnedDiskBytes': probe['ownedDiskBytes'],
                'peakOwnedMemoryBytes': probe['ownedMemoryBytes'], 'minimumFreeDiskBytes': probe['diskAvailableBytes'],
                'minimumAvailableMemoryBytes': probe['memoryAvailableBytes']}
        self.preparation.journal['activeResourcePhase'] = name
        self.preparation.save('RESOURCE_PHASE_ADMITTED')

    def finish_phase(self):
        self.check(); probe = self.measure()
        with self.lock:
            phase = self.current
        require(phase is not None, 'No owned resource phase is active')
        result = self.budget.check_phase(phase, probe)
        require(result['status'] == 'MEASUREMENT_ADMITTED', 'Preparation phase ended outside its owned resource envelope')
        result.update(status='MEASURED_CURRENT_PHASE_ONLY', phasePlanSha256=self.budget_hash(phase),
                      previousPhaseReceiptSha256=self.previous, allAcceptanceResourcesMeasured=False)
        with self.lock:
            result['actualObservedPeak'] = dict(self.phase_observations)
        result['actualObservedPeak']['ownedGrowthBytes'] = max(0,
            result['actualObservedPeak']['peakOwnedDiskBytes'] - phase['spec']['baselineProbe']['ownedDiskBytes'])
        path = self.preparation.work / ('resource-phase-' + str(self.phase_index).zfill(2) + '-measured.json')
        write_json(path, result); self.previous = digest(path)
        with self.lock:
            self.current = None
        return result

    @staticmethod
    def budget_hash(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def close(self, failed):
        self.cleaning = True; self.stop.set()
        for worker in (self.watcher, self.collector):
            worker.join(timeout=5)
        errors = []
        if self.watcher.is_alive() or self.collector.is_alive():
            errors.append('Resource measurement workers did not stop')
        if failed or self.failed.is_set():
            with self.process_lock:
                processes = [item[0] for item in self.processes.values()]
            for process in processes:
                try:
                    self.stop_group(process)
                except BaseException:
                    errors.append('An owned process group did not stop')
            try:
                self.preparation.cancel_source_exports()
            except BaseException:
                errors.append('Owned source-export cancellation was not confirmed')
            try:
                self.preparation.cleanup_java_probe()
            except BaseException:
                errors.append('Owned Java probe cleanup was not confirmed')
            try:
                self.preparation.cleanup()
            except BaseException:
                errors.append('Owned fixture MySQL cleanup was not confirmed')
        with self.lock:
            self.stream.flush(); os.fsync(self.stream.fileno()); self.stream.close()
        with self.process_lock:
            self.group_stream.flush(); os.fsync(self.group_stream.fileno()); self.group_stream.close()
        signal.signal(signal.SIGUSR1, self.old_signal)
        if self.failed.is_set():
            errors.append('Independent resource supervision failed; no readiness marker is permitted')
        require(not errors, '; '.join(errors))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def failure_details(error):
    # Exception messages and external frames may contain SQL, credentials or
    # business data. Only this versioned controller's code locations are public.
    name = type(error).__name__
    result = {'errorType': name if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,99}', name) else 'Exception',
              'locations': []}
    frame = error.__traceback__
    for _ in range(1024):
        if frame is None:
            break
        if frame.tb_frame.f_code.co_filename == __file__:
            function = frame.tb_frame.f_code.co_name
            if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,99}', function):
                result['locations'].append({'function': function, 'line': frame.tb_lineno})
                result['locations'] = result['locations'][-8:]
        frame = frame.tb_next
    return result


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(part)
    return value.hexdigest()


def canonical(value):
    path = Path(value)
    require(path.is_absolute() and path.resolve(strict=True) == path
            and not any(item.is_symlink() for item in (path, *path.parents)), 'Canonical existing path required')
    return path


def private_json(path):
    path = canonical(path)
    metadata = path.stat()
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid()
            and metadata.st_nlink == 1 and not metadata.st_mode & 0o077
            and metadata.st_size <= 16 * 1024 * 1024, 'Private bounded owned JSON required')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Repeated private JSON field')
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=pairs)


def write_json(path, value, *, replace=False):
    require(not path.is_symlink() and (replace or not path.exists()), 'Refusing to replace unknown evidence')
    temporary = path.with_name(path.name + '.' + secrets.token_hex(6) + '.tmp')
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_DIRECTORY | os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def ecs_identity(args):
    require(sys.platform == 'linux' and args.instance_id == INSTANCE
            and re.fullmatch(r'[a-f0-9]{32}', args.machine_id), 'Only the original admitted monolith ECS is allowed')
    require(Path('/etc/machine-id').read_text().strip() == args.machine_id, 'Actual ECS machine differs')
    opener = build_opener(ProxyHandler({})); base = 'http://100.100.100.200/latest/'
    with opener.open(Request(base + 'api/token', data=b'', method='PUT', headers={
            'X-aliyun-ecs-metadata-token-ttl-seconds': '60'}), timeout=3) as response:
        token = response.read(4096).decode()
    with opener.open(Request(base + 'meta-data/instance-id', headers={
            'X-aliyun-ecs-metadata-token': token}), timeout=3) as response:
        require(response.read(256).decode().strip() == args.instance_id, 'Actual ECS instance differs')
    return {'instanceId': args.instance_id, 'machineId': args.machine_id, 'executionLocation': 'ECS'}


def run(arguments, *, data=None, timeout=60, diagnostics=None):
    result = subprocess.run(arguments, input=data, capture_output=True, timeout=timeout,
                            env={name: value for name, value in os.environ.items() if name in ('PATH', 'LANG', 'LC_ALL')})
    if result.returncode and diagnostics is not None:
        with diagnostics.open('xb') as stream:
            os.chmod(diagnostics, 0o600)
            stream.write(result.stderr[-256 * 1024:])
    require(result.returncode == 0, 'Owned fixture operation failed; private evidence is retained')
    require(len(result.stdout) <= 64 * 1024 * 1024, 'Fixture metadata exceeded its limit')
    return result.stdout


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


def archive_source(archive, destination, commit, source_sha):
    require(digest(archive) == source_sha, 'Git archive digest differs from Jenkins')
    seen, total, this_script = set(), 0, None
    with tarfile.open(archive, 'r:gz') as source:
        for entry in source:
            path = Path(entry.name)
            require(not path.is_absolute() and '..' not in path.parts and '\\' not in entry.name
                    and path.parts and path.parts[0] not in ('work', '.git', 'artifacts')
                    and (entry.isfile() or entry.isdir()) and entry.name not in seen,
                    'Unsafe fixed-source archive member')
            seen.add(entry.name); total += entry.size
            require(len(seen) <= 50000 and entry.size <= 32 * 1024 * 1024 and total <= 512 * 1024 * 1024,
                    'Fixed-source archive exceeds its budget')
            target = destination.joinpath(*path.parts)
            if entry.isdir():
                target.mkdir(parents=True, mode=0o700, exist_ok=True); continue
            target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            with source.extractfile(entry) as original, target.open('xb') as output:
                os.chmod(target, 0o700 if entry.mode & 0o100 else 0o600)
                shutil.copyfileobj(original, output, 1024 * 1024)
            if path.as_posix() == 'script/jenkins/prepare-compact-fixtures.py':
                this_script = digest(target)
        require(source.pax_headers.get('comment') == commit, 'Archive commit metadata differs')
    require(this_script == digest(Path(__file__).resolve()), 'Provisioner itself is not this fixed SCM source')


def registry(source):
    tree = ast.parse((source / 'script/jenkins/verify-ecs.py').read_text('utf8'))
    values = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id in ('FIXTURE_SCHEMAS', 'MIGRATION_PAIRS'):
                    values[target.id] = ast.literal_eval(statement.value)
    require(set(values) == {'FIXTURE_SCHEMAS', 'MIGRATION_PAIRS'}, 'Audited fixture registry is absent')
    return values


def fixture_java_executable(configured, *, root, inbox, archive, tag, commit, source_sha, identity, registration=None):
    if configured != 'ecs-tool-runtime':
        return canonical(configured)
    # This check precedes importing the uploaded executor and does not rely on a
    # previous prepare command's return flag or on an uncommitted host checkout.
    require(digest(archive) == source_sha and archive.stat().st_size <= 128 * 1024 ** 2,
            'Tool Java requires this fixed uploaded source archive')
    executor_sha, seen, total, count = None, set(), 0, 0
    with tarfile.open(archive, 'r:gz') as package:
        for entry in package:
            count += 1; total += entry.size
            require(count <= 50000 and 0 <= entry.size <= 32 * 1024 ** 2 and total <= 512 * 1024 ** 2
                    and entry.name not in seen, 'Tool source archive is duplicate or exceeds its bounds')
            seen.add(entry.name)
            if entry.name == 'script/jenkins/ecs-tool-runtime.py':
                require(entry.isfile() and 0 < entry.size <= 1024 ** 2, 'Pinned tool executor source is invalid')
                executor_sha = hashlib.sha256(package.extractfile(entry).read(1024 ** 2 + 1)).hexdigest()
        require(package.pax_headers.get('comment') == commit and executor_sha is not None,
                'Pinned executor is missing or belongs to another source commit')
    uploaded = canonical(inbox / 'ecs-tool-runtime.py')
    folder = canonical(inbox / 'tool-runtime')
    require(uploaded.stat().st_uid == os.getuid() and not uploaded.stat().st_mode & 0o022
            and digest(uploaded) == executor_sha and digest(canonical(folder / 'executor.py')) == executor_sha,
            'Uploaded tool executor bytes differ from this source archive')
    runtime = module('fixed_fixture_tool_runtime', uploaded)
    value, _ = runtime.admit(folder / 'manifest.json', root=root, tag=tag, commit=commit,
        source_sha=source_sha, identity=identity, source=folder)
    require(value['directory'] == str(folder), 'Fixture Java registration escaped its fixed build inbox')
    if registration is not None:
        registration.update(runtime=runtime, value=value)
    return canonical(folder / 'java')


class Preparation:
    def __init__(self, args):
        self.args = args; self.identity = ecs_identity(args)
        require(TAG.fullmatch(args.tag) and re.fullmatch(r'[a-f0-9]{40}', args.commit)
                and args.tag.endswith('-' + args.commit[:12]) and SHA.fullmatch(args.source_sha256),
                'Fixed Jenkins commit, release and source digest required')
        self.root = canonical(args.root)
        require(re.fullmatch(r'/(?:home|srv|opt)/[A-Za-z0-9_./-]+', str(self.root)), 'Existing admitted release root required')
        self.inbox = canonical(self.root / 'inbox' / args.tag)
        self.archive = canonical(self.inbox / 'source.tar.gz')
        require(digest(self.archive) == args.source_sha256, 'Source archive checksum differs')
        self.attempt = self.root / 'verification' / args.tag
        self.checkout = self.attempt / 'checkout'
        self.journal_file = self.checkout / 'work' / 'compact-fixtures-owner.json'
        self.docker = canonical(shutil.which('docker'))
        self.journal = None
        self.resources = None
        self.java_registration = {}

    def docker_call(self, *arguments, **kwargs):
        if self.journal is not None:
            kwargs['diagnostics'] = self.work / 'private' / ('docker-' + secrets.token_hex(6) + '.stderr')
        if self.resources is None:
            return run([str(self.docker), *arguments], **kwargs)
        diagnostics = kwargs.pop('diagnostics', None)
        data = kwargs.pop('data', None)
        result = self.resources.proxy.run([str(self.docker), *arguments], input=data,
            capture_output=True, timeout=kwargs.pop('timeout', 60), **kwargs)
        if result.returncode and diagnostics is not None:
            with diagnostics.open('xb') as stream:
                os.chmod(stream.name, 0o600); stream.write(result.stderr[-256 * 1024:])
        require(result.returncode == 0 and len(result.stdout) <= 64 * MIB,
                'Controlled fixture operation failed; retain private owned evidence')
        return result.stdout

    def save(self, phase):
        self.journal['phase'] = phase
        self.journal['updatedAtUtc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        write_json(self.journal_file, self.journal, replace=True)

    def retain_failure(self, error):
        if getattr(self, 'failure_origin', None) is not None:
            return self.failure_origin
        self.failure_origin = failure_details(error)
        if self.journal is not None:
            try:
                write_json(self.work / 'failure.json', {
                    'schemaVersion': 1, 'kind': 'doorhandle-compact-fixture-failure',
                    'release': self.args.tag, 'commit': self.args.commit, 'sourceSha256': self.args.source_sha256,
                    'phase': self.journal.get('phase'),
                    'resourcePhase': self.journal.get('activeResourcePhase'), **self.failure_origin})
            except BaseException:
                pass
        return self.failure_origin

    def bind_source_exports(self, original):
        source = {'containerId': original['Id'], 'imageId': original['Image'],
                  'project': PROJECT, 'service': 'mysql'}
        require(source['containerId'] == self.journal['sourceContainerId'] and original['State']['Running'],
                'Source cancellation identity differs from the read-only source')
        self.journal['sourceExportSource'] = source
        self.resources.source = source
        self.save('SOURCE_EXPORT_BOUND')
        # These fixed capabilities are checked before any tagged client starts.
        # No environment, password, business row or /proc contents are emitted.
        probe_token = secrets.token_hex(16)
        self.docker_call('exec', '--env', 'DOORHANDLE_CANCEL_PROBE=' + probe_token, original['Id'], 'sh', '-ec',
            'command -v tr >/dev/null; command -v grep >/dev/null; command -v sleep >/dev/null; '
            'ulimit -v ' + str(SOURCE_CLIENT_AS_KIB) + '; '
            '[ "$(ulimit -v)" = "' + str(SOURCE_CLIENT_AS_KIB) + '" ]; '
            '[ -r "/proc/$$/stat" ]; '
            'tr "\\000" "\\n" <"/proc/$$/environ" | grep -Fqx -- "DOORHANDLE_CANCEL_PROBE=$1"; '
            'IFS= read -r value <"/proc/$$/stat"; rest=${value##*) }; set -- $rest; '
            '[ "$#" -ge 20 ]; shift 19; case "$1" in *[!0-9]*|\'\') exit 2;; esac; '
            'kill -0 "$$"', '--', probe_token, timeout=15)
        self.journal['sourceExportCancellationVerified'] = True
        self.save('SOURCE_EXPORT_CANCELLATION_READY')

    def cancel_source_exports(self):
        source = self.journal.get('sourceExportSource')
        if not source:
            return {'status': 'NOT_STARTED'}
        token = self.journal.get('sourceExportToken', '')
        require(re.fullmatch(r'[a-f0-9]{32}', token), 'Owned source export token is missing')
        row = json.loads(self.docker_call('inspect', source['containerId'], timeout=15))[0]
        labels = row['Config'].get('Labels') or {}
        require(row['Id'] == self.journal['sourceContainerId'] == source['containerId']
                and row['Image'] == source['imageId'] and row['State']['Running']
                and labels.get('com.docker.compose.project') == PROJECT
                and labels.get('com.docker.compose.service') == 'mysql',
                'Original source identity changed; never stop or substitute a source container')
        output = self.docker_call('exec', source['containerId'], 'sh', '-ec', SOURCE_CANCEL, '--', token, timeout=20)
        lines = output.decode('ascii').splitlines()
        require(len(lines) <= 128 and all(re.fullmatch(r'(?:TERM|KILL) [1-9][0-9]* [0-9]+ (?:mysql|mysqldump|sh)', line) for line in lines),
                'Source cancellation emitted unexpected metadata; raw environments are never evidence')
        receipt = {'kind': 'doorhandle-owned-source-export-cancellation', 'status': 'EXIT_CONFIRMED',
                   'sourceContainerId': source['containerId'], 'sourceContainerStopped': False,
                   'ownerToken': token, 'pidStartTickCommOnly': lines, 'dataAndEvidenceRetained': True}
        write_json(self.work / ('source-export-cleanup-' + secrets.token_hex(5) + '.json'), receipt)
        return receipt

    def cleanup_java_probe(self):
        if self.java_registration:
            result = self.java_registration['runtime'].cleanup(self.java_registration['value'])
            require(result['status'] == 'STOPPED' and result['remaining'] == [], 'Owned Java probe cleanup was not confirmed')
            return result
        return {'status': 'NOT_STARTED'}

    def cancel_owned_groups(self):
        owner = self.journal.get('resourceOwnerToken', '')
        require(re.fullmatch(r'[a-f0-9]{32}', owner), 'Owned process registry has no fixed owner')
        stopped = []
        claims = self.work / 'owned-command-claims'
        if claims.exists():
            canonical(claims)
            require(claims.is_dir() and claims.stat().st_uid == os.getuid()
                    and not claims.stat().st_mode & 0o077, 'Owned command claims directory differs')
            entries = list(claims.iterdir())
            require(len(entries) <= 20001, 'Owned command intent registry exceeded its bound')
            for path in entries:
                if path.name.endswith('.tmp'):
                    # Atomic intent publication precedes spawn: unpublished
                    # intent fragments cannot correspond to started commands.
                    continue
                require(re.fullmatch(r'[a-f0-9]{32}\.json', path.name), 'Unknown command ownership file')
                claim = private_json(path)
                require(claim.get('kind') == 'doorhandle-owned-command-intent'
                        and claim.get('ownerToken') == owner and claim.get('sourceCommit') == self.args.commit
                        and claim.get('groupToken') == path.stem and SHA.fullmatch(claim.get('argumentsSha256', '')),
                        'Command intent belongs to another preparation')
                groups = {item['group'] for item in group_members(None, owner, path.stem)}
                for group in groups:
                    stop_owned_group(group, owner, path.stem)
                    stopped.append({'group': group, 'groupToken': path.stem})
        path = self.work / 'owned-process-groups.jsonl'
        if not path.exists():
            return stopped
        canonical(path); metadata = path.stat()
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid()
                and metadata.st_nlink == 1 and not metadata.st_mode & 0o077 and metadata.st_size <= 32 * MIB,
                'Owned process registry metadata differs')
        records = [json.loads(line) for line in path.read_text('utf8').splitlines()]
        require(len(records) <= 20000, 'Owned command registry exceeded its bound')
        for record in records:
            require(record.get('ownerToken') == owner and record.get('sourceCommit') == self.args.commit
                    and type(record.get('pid')) is int and record['pid'] > 1
                    and re.fullmatch(r'[a-f0-9]{32}', record.get('groupToken', '')),
                    'Refusing a process claim from another preparation')
            if group_members(record['pid'], owner, record['groupToken']):
                stop_owned_group(record['pid'], owner, record['groupToken'])
                stopped.append({'group': record['pid'], 'groupToken': record['groupToken']})
        return stopped

    def resource_gate(self, source, schema, suite_count):
        info = source.single("SELECT JSON_OBJECT('bytes',COALESCE(SUM(DATA_LENGTH+INDEX_LENGTH),0)) FROM information_schema.TABLES WHERE TABLE_SCHEMA=" + source.runtime.literal(schema) + ';')
        allocated = int(info['bytes'])
        require(allocated >= 0, 'Actual source allocation was not measured')
        self.resources.finish_phase()
        # This is an actively enforced measurement envelope, never a claimed
        # prediction of SQL expansion or complete acceptance peak.
        bound = min(2 * GIB, max(512 * MIB, 4 * allocated + 64 * MIB))
        evidence = {'sourceAllocatedBytes': allocated, 'exportGrowthEnvelopeBytes': bound,
                    'mode': 'ENFORCED_BOUND', 'diskReserveBytes': DISK_RESERVE,
                    'diskOvershootBytes': DISK_OVERSHOOT, 'mysqlMemoryLimitBytes': MYSQL_MEMORY,
                    'javaSuiteCount': suite_count, 'fullAcceptanceStatus': 'NOT_MEASURED'}
        write_json(self.work / 'resource-admission.json', evidence)
        self.resources.admit('source-export', bound, {'sourceAllocatedBytes': allocated})
        return evidence

    def prepare(self):
        succeeded = False
        try:
            result = self.prepare_controlled()
            succeeded = True
        except BaseException as error:
            self.retain_failure(error)
            raise
        finally:
            if self.resources is not None:
                self.resources.close(not succeeded)
        # No ready marker is published until both independent monitoring workers
        # have returned successfully and their evidence is durably closed.
        require(succeeded, 'Preparation did not complete')
        self.journal['resourceProbeSha256'] = digest(self.resources.file)
        self.journal['lastResourcePhaseReceiptSha256'] = self.resources.previous
        self.journal['fullAcceptanceResourcesMeasured'] = False
        self.save('PREPARED')
        write_json(self.attempt / '.fixtures-ready.json', {'schema': 1, 'kind': 'doorhandle-ci-fixtures',
            'release': self.args.tag, 'commit': self.args.commit,
            'instanceId': self.args.instance_id, 'machineId': self.args.machine_id})
        return result

    def prepare_controlled(self):
        require(not self.attempt.exists() and not self.attempt.is_symlink(), 'Use a new Jenkins build; fixture attempts cannot be reused')
        settings = private_json(self.args.settings)
        required = {'version', 'sourceMysqlContainerId', 'sourceSchema', 'sourceOffsets', 'java'}
        require(required <= set(settings) <= required | {'applicationJar', 'applicationJarSha256', 'legacyClockPolicy'}
                and settings['version'] == 1 and CID.fullmatch(settings['sourceMysqlContainerId'])
                and IDENT.fullmatch(settings['sourceSchema']), 'Unsupported explicit fixture settings')
        require(isinstance(settings['sourceOffsets'], dict) and settings['sourceOffsets'],
                'Explicit reviewed domain source clock settings required')
        java = fixture_java_executable(settings['java'], root=self.root, inbox=self.inbox,
            archive=self.archive, tag=self.args.tag, commit=self.args.commit,
            source_sha=self.args.source_sha256, identity=self.identity, registration=self.java_registration)
        jar = canonical(self.inbox / 'application.jar')
        plan = private_json(self.inbox / 'build-artifacts.json')
        require(isinstance(plan.get('applicationJarSha256'), str) and SHA.fullmatch(plan['applicationJarSha256'])
                and type(plan.get('applicationJarBytes')) is int and 0 < plan['applicationJarBytes'] <= 512 * 1024 * 1024
                and digest(jar) == plan['applicationJarSha256'] and jar.stat().st_size == plan['applicationJarBytes']
                and settings.get('applicationJar', str(jar)) == str(jar)
                and settings.get('applicationJarSha256', plan['applicationJarSha256']) == plan['applicationJarSha256'],
                'Fixed uploaded application jar differs from its Jenkins artifact plan')
        settings['applicationJarSha256'] = plan['applicationJarSha256']
        expected = {'schema': 1, 'kind': 'doorhandle-compact-fixture-artifacts', 'release': self.args.tag,
                    'commit': self.args.commit, 'sourceSha256': self.args.source_sha256,
                    'applicationJarSha256': settings['applicationJarSha256'], 'applicationJarBytes': jar.stat().st_size}
        require(all(plan.get(key) == value for key, value in expected.items()), 'Jenkins source/jar artifact plan differs')
        parent = self.root / 'verification'; parent.mkdir(mode=0o700, exist_ok=True); canonical(parent)
        require(parent.stat().st_uid == os.getuid() and not parent.stat().st_mode & 0o022, 'Verification parent is not owned/private')
        self.attempt.mkdir(mode=0o700); self.checkout.mkdir(mode=0o700)
        (self.checkout / 'work').mkdir(mode=0o700)
        token = secrets.token_hex(5); self.work = self.checkout / 'work' / 'compact-fixtures'
        self.work.mkdir(mode=0o700); (self.work / 'private').mkdir(mode=0o700)
        self.journal = {'schemaVersion': 1, 'kind': 'doorhandle-compact-fixture-owner', 'release': self.args.tag,
            'commit': self.args.commit, 'sourceSha256': self.args.source_sha256, 'identity': self.identity,
            'token': token, 'work': str(self.work), 'phase': 'PREPARING', 'containerId': None,
            'sourceContainerId': settings['sourceMysqlContainerId'], 'schemas': []}
        self.journal['javaToolRuntime'] = settings['java'] == 'ecs-tool-runtime'
        self.save('PREPARING')
        source_root = self.work / 'fixed-source'; source_root.mkdir(mode=0o700)
        preliminary = os.statvfs(self.work)
        inventory, budget_bytes = archive_inventory(self.archive, self.args.commit, self.args.source_sha256,
            Path(__file__).resolve(), preliminary.f_frsize)
        require(preliminary.f_bavail * preliminary.f_frsize >= DISK_RESERVE + DISK_OVERSHOOT + len(budget_bytes) + 2 * MIB,
                'Actual disk cannot retain the controller evidence reserve')
        budget_file = self.work / 'private' / 'ecs-resource-budget.py'
        budget_file.write_bytes(budget_bytes); os.chmod(budget_file, 0o600)
        budget = module('fixed_preparer_resource_budget', budget_file)
        self.resources = PreparationMonitor(self, budget, expected)
        inventory['jarCopyBytes'] = jar.stat().st_size
        block = preliminary.f_frsize
        extraction = inventory['archiveAllocatedBoundBytes'] + ((jar.stat().st_size + block - 1) // block) * block + 32 * MIB
        self.resources.admit('extraction', extraction, inventory, java=settings['java'] == 'ecs-tool-runtime')
        archive_source(self.archive, source_root, self.args.commit, self.args.source_sha256)
        uploaded = self.work / 'candidate-app.jar'; shutil.copyfile(jar, uploaded); os.chmod(uploaded, 0o600)
        require(digest(uploaded) == settings['applicationJarSha256'], 'Copied candidate jar differs')
        version = self.resources.proxy.run([str(java), '-version'], capture_output=True, cwd=str(self.checkout),
                                 timeout=90 if settings['java'] == 'ecs-tool-runtime' else 15)
        require(version.returncode == 0 and re.search(rb'version "17(?:[.\"]|$)', version.stderr + version.stdout),
                'An existing Java 17 executable is required; no JRE is installed')
        self.cleanup_java_probe()
        profile_file = source_root / 'script/jenkins/compact-acceptance.json'
        profile = json.loads(profile_file.read_text('utf8')); suites = profile.get('javaSuites')
        require(profile.get('schemaVersion') == 1 and profile.get('kind') == 'doorhandle-compact-acceptance-profile'
                and profile.get('sourceTableCount') == 131 and profile.get('targetTableCount') == 29
                and profile.get('externalModelPolicy', {}).get('paidCallsAllowed') is False
                and isinstance(suites, list) and suites, 'Versioned complete acceptance profile is required')
        self.registry = registry(source_root)
        self.validate_suites(suites)
        offsets = {'workbench'}
        for file in (source_root / 'sql/mysql/compact/copy').glob('*.sql'):
            offsets.update(key.lower() for key in re.findall(r'__SOURCE_([A-Z_]+)_OFFSET__', file.read_text('utf8')))
        require(set(settings['sourceOffsets']) == offsets, 'All and only the fixed copy plan domain offsets must be reviewed explicitly')
        sys.path.insert(0, str(source_root / 'script/schema'))
        self.runtime = module('fixture_migration_runtime', source_root / 'script/schema/compact_migration_runtime.py')
        self.runtime.subprocess = self.resources.proxy
        self.runtime.clocks.validate(settings['sourceOffsets'], settings.get('legacyClockPolicy'), expected_domains=offsets)
        self.runtime.ROOT = self.checkout
        # The verifier has not unpacked its source yet: checkout may contain only
        # work. Use the fixed archive's read-only metadata implementation while
        # keeping private migration paths admitted below the future checkout.
        schema_guard = module('fixture_metadata_guard', source_root / 'script/docker/compact-schema-guard.py')
        def metadata_snapshot(mysql, schema):
            value = schema_guard.metadata_snapshot(lambda sql: mysql.json_rows(sql, database=schema))
            return value, schema_guard.metadata_sha256(value)
        self.runtime.metadata_snapshot = metadata_snapshot
        original = json.loads(self.docker_call('inspect', settings['sourceMysqlContainerId']))[0]
        require(original['Id'] == settings['sourceMysqlContainerId'] and original['State']['Running']
                and original['Config']['Labels'].get('com.docker.compose.project') == PROJECT
                and original['Config']['Labels'].get('com.docker.compose.service') == 'mysql',
                'Source is not the existing original MySQL container')
        backends = self.docker_call('ps', '-aq', '--no-trunc', '--filter',
            'label=com.docker.compose.project=' + PROJECT, '--filter',
            'label=com.docker.compose.service=backend').decode().split()
        require(len(backends) == 1, 'Original application generation is missing or ambiguous')
        backend = json.loads(self.docker_call('inspect', backends[0]))[0]
        environment = dict(item.split('=', 1) for item in backend['Config'].get('Env', []) if '=' in item)
        jdbc = environment.get('DB_URL', '')
        require(jdbc.startswith('jdbc:mysql://'), 'Original application must declare its actual MySQL schema')
        endpoint = urlsplit(jdbc[5:])
        require(endpoint.hostname == 'mysql' and (endpoint.port or 3306) == 3306
                and not endpoint.username and not endpoint.password and endpoint.path == '/' + settings['sourceSchema'],
                'Fixture source is not the actual original application database')
        self.bind_source_exports(original)
        self.resources.finish_phase()
        self.resources.admit('source-inspection', 64 * MIB, {})
        self.source = readonly_source(self.runtime, self.docker, original['Id'], self.work, self.resources.token)
        actual = self.source.single("SELECT JSON_OBJECT('uuid',@@server_uuid,'version',@@version,'foreignKeys',@@foreign_key_checks);")
        require(actual['version'].startswith('8.4.') and actual['foreignKeys'] == 1, 'Existing MySQL 8.4 with FK enforcement required')
        self.source.config['serverUuid'] = actual['uuid']
        contract = json.loads((source_root / 'docs/database/compact-schema-contract.json').read_text('utf8'))
        sources = contract['sourceTables']
        require(len(sources) == len(set(sources)) == 131, 'Complete actual 131-table source contract required')
        require(not self.source.json_rows('SELECT JSON_OBJECT(\'name\',ROUTINE_NAME) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=' + self.runtime.literal(settings['sourceSchema']) + ';')
                and not self.source.json_rows('SELECT JSON_OBJECT(\'name\',EVENT_NAME) FROM information_schema.EVENTS WHERE EVENT_SCHEMA=' + self.runtime.literal(settings['sourceSchema']) + ';'),
                'Source routines/events need a separate reviewed restore plan; no facts will be silently omitted')
        self.journal['resources'] = self.resource_gate(self.source, settings['sourceSchema'], len(suites))
        _, original_metadata = self.runtime.metadata_snapshot(self.source, settings['sourceSchema'])
        snapshot = self.runtime.schema_snapshot(self.source, settings['sourceSchema'], sources)
        self.runtime.clocks.require_empty_sources(settings['sourceOffsets'], settings.get('legacyClockPolicy'), snapshot)
        require(sum(table['rows'] for table in snapshot['tables'].values()) > 0, 'An empty source cannot prove existing-data preservation')
        backup = self.runtime.backup_schema(self.source, snapshot, self.work / 'source-backup', purpose='source',
            migration_context={'kind': 'fixture-origin-copy', 'sourceCommit': self.args.commit, 'sourceSha256': self.args.source_sha256})
        after = self.runtime.schema_snapshot(self.source, settings['sourceSchema'], sources)
        _, final_metadata = self.runtime.metadata_snapshot(self.source, settings['sourceSchema'])
        require(after['snapshotSha256'] == snapshot['snapshotSha256']
                and private_json(backup)['metadataSha256'] == original_metadata == final_metadata,
                'Source changed during read-only export; retain evidence and prepare another build during a stable window')
        export = private_json(backup)
        dump = canonical(backup.parent / 'data.sql')
        require(export['data']['bytes'] == dump.stat().st_size and export['data']['sha256'] == digest(dump)
                and export['snapshotSha256'] == snapshot['snapshotSha256'], 'Completed source dump bytes or digest differs')
        self.cancel_source_exports()
        self.resources.finish_phase()
        clone_inputs = {'sourceAllocatedBytes': self.journal['resources']['sourceAllocatedBytes'],
            'dumpBytes': dump.stat().st_size, 'dumpSha256': digest(dump),
            'backupManifestSha256': digest(backup), 'sourceSnapshotSha256': snapshot['snapshotSha256']}
        clone_bound = max(768 * MIB, 3 * clone_inputs['sourceAllocatedBytes'] + 2 * clone_inputs['dumpBytes']
                          + 128 * MIB + len(suites) * 2 * MIB)
        self.resources.admit('fixture-clone', clone_bound, clone_inputs, mysql=True)
        self.start_mysql(original['Image'])
        self.clone_source(snapshot, backup)
        java_suites = self.provision_suites(suites)
        worker = self.fixture_config('doorhandle_worker_verify_', 'ecsit_', 'python-worker')
        self.create_account(worker)
        whole = self.whole_config(settings, str(java), str(uploaded))
        manifest = {'version': 2, 'javaSuites': java_suites, 'javaOnly': False, 'sourceRegression': True,
                    'workerMysqlConfig': str(self.write_config('python-worker', worker)),
                    'wholeMigrationConfig': str(self.work / 'whole-migration.json')}
        write_json(self.work / 'whole-migration.json', whole)
        write_json(self.work / 'manifest.json', manifest)
        self.journal.update(manifest=str(self.work / 'manifest.json'), manifestSha256=digest(self.work / 'manifest.json'),
            profileSha256=digest(profile_file), sourceServerUuid=actual['uuid'], sourceSnapshotSha256=snapshot['snapshotSha256'],
            sourceTableCount=131, sourceRows=sum(table['rows'] for table in snapshot['tables'].values()),
            sourceBackupSha256=digest(backup), javaSuiteCount=len(java_suites), fixtureConfigCount=len(self.journal['schemas']))
        self.inspect_owned()
        self.resources.finish_phase()
        return {'status': 'PREPARED', 'commit': self.args.commit, 'release': self.args.tag,
                'manifest': self.journal['manifest'], 'ownerReceipt': str(self.journal_file),
                'containerId': self.journal['containerId'], 'port': self.journal['port'], 'javaSuiteCount': len(java_suites)}

    def validate_suites(self, suites):
        seen, ids = set(), set()
        for suite in suites:
            require(isinstance(suite, dict) and isinstance(suite.get('id'), str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9-]{0,95}', suite['id'])
                    and isinstance(suite.get('className'), str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.]*', suite['className'])
                    and suite['className'].rsplit('.', 1)[-1] not in seen
                    and suite['id'] not in ids
                    and isinstance(suite.get('fixtureProperties'), list) and suite['fixtureProperties']
                    and len(suite['fixtureProperties']) == len(set(suite['fixtureProperties']))
                    and set(suite['fixtureProperties']) <= self.registry['FIXTURE_SCHEMAS'].keys(),
                    'Versioned Java suites must have unique exact classes and audited property lists')
            seen.add(suite['className'].rsplit('.', 1)[-1])
            ids.add(suite['id'])

    def start_mysql(self, image):
        require(re.fullmatch(r'sha256:[a-f0-9]{64}', image), 'Reuse an existing immutable MySQL image')
        require(json.loads(self.docker_call('image', 'inspect', image))[0]['Id'] == image, 'Existing MySQL image is unavailable')
        with socket.socket() as available:
            available.bind(('127.0.0.1', 0)); port = available.getsockname()[1]
        require(1024 < port <= 65535 and port != 3306, 'Owned non-default loopback port required')
        data = self.work / 'mysql-data'; data.mkdir(mode=0o700)
        password = secrets.token_hex(32)
        env = self.work / 'mysql.env'; env.write_text('MYSQL_ROOT_PASSWORD=' + password + '\n', encoding='utf8'); os.chmod(env, 0o600)
        name = 'doorhandle-compact-fixture-' + self.journal['token']
        self.journal.update(containerName=name, image=image, port=port, dataDirectory=str(data), rootPassword=password)
        self.save('STARTING_MYSQL')
        container = self.docker_call('run', '-d', '--pull=never', '--restart=no', '--name', name,
            '--label', LABEL + '=' + self.journal['token'], '--label', 'io.doorhandle.release=' + self.args.tag,
            '--label', 'io.doorhandle.source=' + self.args.source_sha256, '--env-file', str(env),
            '--publish', '127.0.0.1:' + str(port) + ':' + str(port), '--memory', str(1536 * 1024 ** 2),
            '--memory-swap', str(1536 * 1024 ** 2), '--cpus', '1', '--pids-limit', '256',
            '--mount', 'type=bind,source=' + str(data) + ',target=' + str(data),
            '--tmpfs', '/var/lib/mysql', image, '--datadir=' + str(data), '--port=' + str(port),
            '--bind-address=0.0.0.0', '--mysqlx=OFF', '--event-scheduler=OFF', '--local-infile=OFF',
            '--innodb-buffer-pool-size=268435456', '--max-connections=120', timeout=120).decode().strip()
        require(CID.fullmatch(container), 'Owned MySQL container identity unavailable')
        self.journal['containerId'] = container; self.save('MYSQL_STARTED')
        deadline = time.monotonic() + 240
        while True:
            try:
                row = self.admin_query("SELECT JSON_OBJECT('uuid',@@server_uuid,'version',@@version,'port',@@port,'data',@@datadir,'fk',@@foreign_key_checks);")
                require(row['version'].startswith('8.4.') and row['port'] == port and row['fk'] == 1
                        and row['data'].rstrip('/') == str(data), 'Owned MySQL actual storage/port/version differs')
                self.journal['serverUuid'] = row['uuid']; break
            except Exception:
                require(time.monotonic() < deadline and json.loads(self.docker_call('inspect', container))[0]['State']['Running'],
                        'Owned MySQL failed readiness; no other server or image will be substituted')
                time.sleep(2)
        self.save('MYSQL_READY'); self.inspect_owned()
        output = self.work / 'mysql-client'; output.mkdir(mode=0o700); (output / 'private').mkdir(mode=0o700)
        self.mysql = self.runtime.Mysql({'scope': 'ecs-disposable-migration', 'serverUuid': self.journal['serverUuid'],
            'dataDirectory': str(data), 'connection': {'host': '127.0.0.1', 'port': port, 'username': 'root', 'password': password},
            'client': {'kind': 'docker', 'executable': str(self.docker), 'containerId': container}}, output)
        self.mysql.admitted_server()

    def admin_query(self, sql):
        output = self.docker_call('exec', '-i', self.journal['containerId'], 'sh', '-ec',
            'MYSQL_PWD="${MYSQL_ROOT_PASSWORD:?}" exec mysql --no-defaults --no-login-paths -uroot --protocol=TCP -h127.0.0.1 --port="$1" --default-character-set=utf8mb4 --batch --raw --skip-column-names',
            '--', str(self.journal['port']), data=sql.encode('utf8'), timeout=15)
        return json.loads(output.decode().strip())

    def clone_source(self, snapshot, backup):
        manifest = private_json(backup)
        require(manifest['snapshotSha256'] == snapshot['snapshotSha256']
                and manifest['data']['file'] == 'data.sql'
                and (backup.parent / 'data.sql').stat().st_size == manifest['data']['bytes']
                and digest(backup.parent / 'data.sql') == manifest['data']['sha256'], 'Original private backup bytes changed')
        clone = 'doorhandle_migration_verify_' + self.journal['token']
        self.runtime.new_schema(self.mysql, clone); foreign = []
        for table, ddl in sorted(manifest['createTables'].items()):
            statement, relations = self.runtime.remove_inline_foreign_keys(self.runtime.normalize_self(ddl, snapshot['schema'], clone), clone)
            self.mysql.script(statement + ';', database=clone, label='clone-create'); foreign += relations
        self.runtime.restore_data(self.mysql, clone, manifest, backup.parent / 'data.sql')
        for table, detail in manifest['tables'].items():
            if detail['autoIncrement'] is not None:
                require(re.fullmatch(r'[0-9]{1,20}', detail['autoIncrement']), 'Invalid actual source high water')
                self.mysql.script('ALTER TABLE ' + self.runtime.quoted(table) + ' AUTO_INCREMENT=' + detail['autoIncrement'] + ';', database=clone, label='clone-hwm')
        self.runtime.install_relations(self.mysql, clone, foreign)
        self.runtime.install_triggers(self.mysql, clone, snapshot['schema'], manifest['triggers'])
        actual = self.runtime.schema_snapshot(self.mysql, clone, manifest['tables'])
        _, metadata_sha = self.runtime.metadata_snapshot(self.mysql, clone)
        require(actual['snapshotSha256'] == snapshot['snapshotSha256'] and metadata_sha == manifest['metadataSha256'],
                'Read-only actual source clone differs in rows/NULL/clocks/keys/triggers/DDL/high water')
        self.journal.update(sourceClone=clone, sourceCloneSnapshotSha256=actual['snapshotSha256'], sourceCollations={name: detail['collation'] for name, detail in actual['tables'].items()})
        self.save('SOURCE_CLONED')

    def fixture_config(self, prefix, account_prefix, description):
        suffix = secrets.token_hex(6 if prefix == 'doorhandle_feature_' else 5)
        schema = prefix + suffix
        require(schema not in {row['database'] for row in self.journal['schemas']}, 'Unexpected disposable identity collision')
        return {'scope': 'ecs-disposable-mysql', **{key: self.identity[key] for key in ('instanceId', 'machineId')},
            'database': schema, 'username': account_prefix + suffix, 'password': secrets.token_hex(32),
            'serverUuid': self.journal['serverUuid'], 'port': self.journal['port'], 'dataDirectory': self.journal['dataDirectory'],
            'url': f"jdbc:mysql://127.0.0.1:{self.journal['port']}/{schema}?sslMode=DISABLED&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai"}

    def create_account(self, config):
        self.runtime.new_schema(self.mysql, config['database'])
        self.mysql.script("CREATE USER '" + config['username'] + "'@'%' IDENTIFIED BY '" + config['password'] + "'; GRANT ALL PRIVILEGES ON "
            + self.runtime.quoted(config['database']) + ".* TO '" + config['username'] + "'@'%';", label='fixture-account')
        self.journal['schemas'].append({'database': config['database'], 'username': config['username']})
        self.save('CREATING_SCHEMAS')

    def write_config(self, name, config):
        require(re.fullmatch(r'[a-zA-Z0-9_.-]+', name), 'Invalid fixture configuration name')
        path = self.work / (name + '.json'); write_json(path, config); return path

    def provision_suites(self, suites):
        result = []
        for suite in suites:
            configs, properties = {}, {}
            for number, key in enumerate(suite['fixtureProperties']):
                prefix, account = self.registry['FIXTURE_SCHEMAS'][key]
                config = self.fixture_config(prefix, account, suite['id']); self.create_account(config); configs[key] = config
                properties[key] = str(self.write_config(suite['id'] + '-' + str(number), config))
            for source, target, strict in self.registry['MIGRATION_PAIRS']:
                if source in configs or strict and target in configs:
                    require(source in configs and target in configs, 'Versioned migration suite lacks one side')
                    self.mysql.script('GRANT SELECT,TRIGGER ON ' + self.runtime.quoted(configs[source]['database']) + ".* TO '" + configs[target]['username'] + "'@'%';", label='fixture-source-read')
            result.append({'javaTests': [suite['className']], 'fixtureProperties': properties})
        return result

    def whole_config(self, settings, java, jar):
        token = self.journal['token']; user = 'mig_' + token; secret = secrets.token_hex(32)
        target = 'doorhandle_compact_candidate_' + token
        recovery = {'source': 'doorhandle_legacy_restore_' + token, 'target': 'doorhandle_compact_restore_' + token}
        self.mysql.script("CREATE USER '" + user + "'@'%' IDENTIFIED BY '" + secret + "'; GRANT SELECT,TRIGGER,LOCK TABLES,EVENT,EXECUTE ON " + self.runtime.quoted(self.journal['sourceClone']) + ".* TO '" + user + "'@'%'; "
            + ' '.join('GRANT ALL PRIVILEGES ON ' + self.runtime.quoted(schema) + ".* TO '" + user + "'@'%';" for schema in (target, *recovery.values()))
            + " GRANT SET_ANY_DEFINER,SYSTEM_USER ON *.* TO '" + user + "'@'%';", label='whole-migration-account')
        result = {'version': 1, 'scope': 'ecs-disposable-migration', **{key: self.identity[key] for key in ('instanceId', 'machineId')},
            'serverUuid': self.journal['serverUuid'], 'sourceSchema': self.journal['sourceClone'], 'targetSchema': target,
            'connection': {'host': '127.0.0.1', 'port': self.journal['port'], 'username': user, 'password': secret},
            'client': {'kind': 'docker', 'executable': str(self.docker), 'containerId': self.journal['containerId']},
            'sourceOffsets': settings['sourceOffsets'], 'sourceCollations': self.journal['sourceCollations'],
            'workbench': {'java': java, 'applicationJar': jar, 'applicationJarSha256': settings['applicationJarSha256']},
            'recoverySchemas': recovery, 'dataDirectory': self.journal['dataDirectory']}
        if settings.get('legacyClockPolicy') is not None:
            result['legacyClockPolicy'] = settings['legacyClockPolicy']
        return result

    def inspect_owned(self):
        row = json.loads(self.docker_call('inspect', self.journal['containerId']))[0]
        require(row['Id'] != self.journal['sourceContainerId'] and row['Id'] == self.journal['containerId']
                and row['Image'] == self.journal['image'] and row['Config']['Labels'].get(LABEL) == self.journal['token']
                and row['Config']['Labels'].get('io.doorhandle.release') == self.args.tag
                and row['Config']['Labels'].get('io.doorhandle.source') == self.args.source_sha256,
                'Container does not belong to this fixture attempt')
        data = canonical(self.journal['dataDirectory'])
        require(data.is_relative_to(canonical(self.journal['work'])) and any(
            mount.get('Type') == 'bind' and mount.get('RW') is True and mount.get('Source') == str(data)
            and mount.get('Destination') == str(data) for mount in row['Mounts']), 'Owned same-path MySQL data bind differs')
        port = self.journal['port']; ports = row['HostConfig']['PortBindings']
        require(ports == {str(port) + '/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(port)}]}
                and row['HostConfig']['RestartPolicy']['Name'] == 'no'
                and row['Name'] == '/' + self.journal['containerName']
                and row['HostConfig'].get('Memory') == MYSQL_MEMORY
                and row['HostConfig'].get('MemorySwap') == MYSQL_MEMORY,
                'Owned loopback-only port, cgroup or restart policy differs')
        return row

    def load(self):
        self.journal = private_json(self.journal_file)
        require(all(self.journal.get(key) == value for key, value in {'schemaVersion': 1,
            'kind': 'doorhandle-compact-fixture-owner', 'release': self.args.tag, 'commit': self.args.commit,
            'sourceSha256': self.args.source_sha256, 'identity': self.identity}.items()), 'Fixture receipt belongs to another build/host')
        self.work = canonical(self.journal['work'])
        require(self.work.is_relative_to(canonical(self.checkout / 'work')), 'Fixture state escaped this checkout/work')

    def cleanup(self):
        self.load()
        if (self.attempt / '.verification-claimed').exists():
            verification = private_json(self.attempt / 'verification-receipt.json')
            require(verification.get('status') in ('PASS', 'FAILED') and all(verification.get(key) == value
                for key, value in {'release': self.args.tag, 'commit': self.args.commit,
                    'sourceSha256': self.args.source_sha256, 'identity': self.identity}.items()),
                    'Verification has not returned with matching private evidence; do not stop a running fixture')
        errors = []
        for operation in (self.cancel_owned_groups, self.cancel_source_exports):
            try:
                operation()
            except BaseException:
                errors.append(operation.__name__ + '_NOT_CONFIRMED')
        try:
            if self.journal.get('javaToolRuntime') and not self.java_registration:
                fixture_java_executable('ecs-tool-runtime', root=self.root, inbox=self.inbox, archive=self.archive,
                    tag=self.args.tag, commit=self.args.commit, source_sha=self.args.source_sha256,
                    identity=self.identity, registration=self.java_registration)
            self.cleanup_java_probe()
        except BaseException:
            errors.append('JAVA_PROBE_NOT_CONFIRMED')
        try:
            self.stop_fixture_only()
        except BaseException:
            errors.append('OWNED_MYSQL_NOT_CONFIRMED')
        receipt = {'schemaVersion': 1, 'kind': 'doorhandle-compact-fixture-cleanup',
            'status': 'FAILED_OR_UNKNOWN' if errors else 'STOPPED', 'errors': errors,
            'release': self.args.tag, 'commit': self.args.commit, 'sourceSha256': self.args.source_sha256, 'identity': self.identity,
            'containerId': self.journal.get('containerId'), 'sourceContainerUntouched': self.journal['sourceContainerId'],
            'dataDirectoryRetained': self.journal.get('dataDirectory'), 'sourceDumpAndEvidenceRetained': True}
        path = self.work / 'cleanup-receipt.json'; write_json(path, receipt, replace=True)
        self.save('FAILED_CLEANUP_EVIDENCE_RETAINED' if errors else 'OWNED_SERVER_STOPPED')
        require(not errors, 'Owned resource cleanup was not completely confirmed; retain all evidence')
        return {'status': receipt['status'], 'commit': self.args.commit, 'release': self.args.tag,
                'cleanupReceipt': str(path), 'cleanupReceiptSha256': digest(path)}

    def stop_fixture_only(self):
        if not self.journal.get('containerId') and self.journal.get('containerName'):
            # Docker may create a container and then time out before returning its
            # ID. Recover only the exact pre-recorded name and all ownership labels.
            candidates = self.docker_call('ps', '-aq', '--no-trunc', '--filter',
                'label=' + LABEL + '=' + self.journal['token']).decode().split()
            require(len(candidates) <= 1 and all(CID.fullmatch(value) for value in candidates),
                    'Unknown Docker create result requires manual review')
            if candidates:
                self.journal['containerId'] = candidates[0]
                owned = self.inspect_owned()
                require(owned['Name'] == '/' + self.journal['containerName'], 'The recorded owned container name changed')
                self.save('CLEANUP_IDENTITY_RECOVERED')
        if self.journal.get('containerId'):
            self.inspect_owned()
            self.docker_call('stop', '--time', '60', self.journal['containerId'], timeout=90)
            row = self.inspect_owned()
            require(not row['State']['Running'] and not row['State']['Restarting'] and row['State']['Pid'] == 0,
                    'Owned MySQL stop was not confirmed')


def readonly_source(runtime, docker, container, output, export_token=None):
    """Keep production root credentials inside its existing container; no write method is admitted."""
    class ReadonlySource(runtime.Mysql):
        def __init__(self):
            self.runtime = runtime; self.program = docker; self.container = container
            self.output = output; self.sequence = 0
            self.config = {'scope': 'production-migration', 'serverUuid': None}
        def command(self, database=None, *, dump=False, table_names=()):
            utility = 'mysqldump' if dump else 'mysql'
            arguments = ['--default-character-set=utf8mb4']
            if dump:
                arguments += ['--single-transaction', '--skip-lock-tables', '--skip-add-locks', '--skip-disable-keys',
                    '--skip-add-drop-table', '--no-create-info', '--skip-triggers', '--complete-insert', '--hex-blob',
                    '--skip-extended-insert', '--set-gtid-purged=OFF', '--no-tablespaces', '--skip-comments',
                    runtime.identifier(database), *[runtime.identifier(table) for table in table_names]]
            else:
                arguments += ['--batch', '--raw', '--skip-column-names', '--unbuffered', '--binary-mode', '--local-infile=0']
                if database:
                    arguments.append('--database=' + runtime.identifier(database))
            require(isinstance(export_token, str) and re.fullmatch(r'[a-f0-9]{32}', export_token),
                    'Source client requires this preparation own export token')
            return [str(docker), 'exec', '-i', '--env', EXPORT_ENV + '=' + export_token, container, 'sh', '-ec',
                'ulimit -v ' + str(SOURCE_CLIENT_AS_KIB) + '; MYSQL_PWD="${MYSQL_ROOT_PASSWORD:?}" exec '
                + utility + ' --no-defaults --no-login-paths --protocol=SOCKET -uroot "$@"', '--', *arguments], b''
        def script(self, sql, **kwargs):
            require(isinstance(sql, str) and all(re.match(r'(?:SELECT\b|SHOW CREATE TABLE\b|SHOW GRANTS\b|SET SESSION (?:time_zone|sql_mode)\b)', statement, re.I)
                for statement in runtime.split_top_level(runtime.without_comments(sql), ';')), 'Only fixed original-source read statements are admitted')
            return super().script(sql, **kwargs)
        def source_lock(self, *args, **kwargs):
            raise ValueError('Fixture preparation never locks or pauses the original production source')
    return ReadonlySource()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('prepare', 'cleanup', 'status'))
    for name in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--settings')
    args = parser.parse_args(); instance = None
    for event in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(event, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        controller_address_limit()
        instance = Preparation(args)
        if args.phase == 'prepare':
            require(args.settings, 'Explicit private preparation settings required'); result = instance.prepare()
        elif args.phase == 'cleanup':
            result = instance.cleanup()
        else:
            instance.load(); result = {'status': instance.journal['phase'], 'release': args.tag,
                                       'containerId': instance.journal.get('containerId')}
        print(json.dumps(result)); return 0
    except BaseException as error:
        details = failure_details(error)
        final_details = details
        if instance and instance.journal:
            if args.phase == 'prepare':
                details = instance.retain_failure(error)
            try:
                instance.save('FAILED_OR_UNKNOWN_RETAINED')
            except BaseException:
                pass
        print('Fixture preparation/control failed; do not use a readiness flag. Preserve private owned evidence on ECS.', file=sys.stderr)
        print(json.dumps(details, sort_keys=True), file=sys.stderr)
        if final_details != details:
            print(json.dumps({'cleanupOrControlFailure': final_details}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
