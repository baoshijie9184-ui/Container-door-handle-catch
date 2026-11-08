"""Resource safety contracts. Run on the admitted ECS, never on the workstation."""
import importlib.util
from contextlib import contextmanager
import io
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


MODULE = Path(__file__).resolve().parents[1] / 'script' / 'jenkins' / 'ecs-resource-budget.py'
SPEC = importlib.util.spec_from_file_location('ecs_resource_budget', MODULE)
budget = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(budget)
PREPARER_MODULE = MODULE.with_name('prepare-compact-fixtures.py')
PREPARER_SPEC = importlib.util.spec_from_file_location('fixture_resource_preparer', PREPARER_MODULE)
preparer = importlib.util.module_from_spec(PREPARER_SPEC)
PREPARER_SPEC.loader.exec_module(preparer)
MIB = 1024 ** 2
GIB = budget.GIB
DIGEST = 'a' * 64


def probe(**changes):
    value = {'ownerToken': 'ci-123-abcdef12', 'sourceCommit': 'b' * 40,
             'capturedAtUtc': '2026-11-07T04:00:00Z', 'diskTotalBytes': 40 * GIB,
             'diskAvailableBytes': 7 * GIB, 'memoryAvailableBytes': 12 * GIB,
             'ownedDiskBytes': 100 * MIB, 'ownedMemoryBytes': 0, 'oomKills': 0}
    value.update(changes)
    return value


def spec():
    components = {name: {'peakBytes': 10 * MIB, 'baselineBytes': 0,
                        'measurement': 'MEASURED', 'evidenceSha256': DIGEST,
                        'retention': 'OWNED_BUILD_OUTPUT' if name in budget.BUILD_OUTPUT_COMPONENTS else 'PROTECTED'}
                  for name in budget.REQUIRED_COMPONENTS}
    components['java-output']['peakBytes'] = 100 * MIB
    components['main-node-modules']['peakBytes'] = 200 * MIB
    components['agent-node-modules']['peakBytes'] = 300 * MIB
    retained = [name for name in budget.REQUIRED_COMPONENTS if name not in budget.BUILD_OUTPUT_COMPONENTS]
    return {'version': 1, 'ownerToken': 'ci-123-abcdef12', 'sourceCommit': 'b' * 40,
            'artifacts': {name: {'bytes': 1024, 'sha256': DIGEST}
                          for name in ('sourceArchive', 'applicationJar')},
            'source': {'allocatedBytes': 1024, 'dumpBytes': 2048, 'evidenceSha256': DIGEST},
            'components': components,
            'phases': [{'name': 'java', 'components': retained + ['java-output'], 'memoryLimitBytes': 2 * GIB},
                       {'name': 'frontend-main', 'components': retained + ['main-node-modules'], 'memoryLimitBytes': GIB},
                       {'name': 'frontend-agent', 'components': retained + ['agent-node-modules'], 'memoryLimitBytes': GIB}],
            'baselineProbe': probe()}


class ResourceBudgetTests(unittest.TestCase):
    def test_serial_peak_does_not_sum_56_reactor_builds_or_two_node_trees(self):
        value = spec()
        value['phases'][1:1] = [dict(value['phases'][0], name='mysql-suite-' + str(i)) for i in range(56)]
        result = budget.plan(value)
        self.assertEqual('READY', result['status'])
        self.assertEqual(410 * MIB, result['peakAdditionalDiskBytes'])
        self.assertEqual('PASS', budget.check(result, probe(), 'java')['status'])

    def test_estimate_and_missing_cold_cache_do_not_claim_measured_fit(self):
        value = spec()
        value['components']['maven-cache']['measurement'] = 'ESTIMATED'
        self.assertEqual('INVALID', budget.plan(value)['status'])
        value['components']['maven-cache']['measurement'] = 'NOT_MEASURED'
        result = budget.plan(value)
        self.assertEqual('NOT_MEASURED', result['status'])
        self.assertEqual('FAIL_CLOSED', budget.check(result, probe(), 'java')['status'])

    def test_bounded_measurement_admits_only_current_phase_and_never_full_proof(self):
        value = spec()
        component = value['components']['java-output']
        component['measurement'] = 'ENFORCED_BOUND'
        value['phases'][0]['enforcement'] = {
            'ownedProcessGroup': True, 'growthMonitor': True, 'memoryLimitEnforced': True,
            'maxProbeIntervalSeconds': 1, 'diskOvershootBytes': 128 * MIB}
        value['components']['agent-node-modules'].update(peakBytes=None, measurement='NOT_MEASURED')
        result = budget.plan(value)
        admitted = budget.check(result, probe(), 'java')
        self.assertEqual('NOT_MEASURED', budget.validate(result)['status'])
        self.assertEqual('MEASUREMENT_ADMITTED', admitted['status'])
        self.assertFalse(admitted['allResourceMeasurementsPresent'])
        self.assertEqual('FAIL_CLOSED', budget.check(result, probe(), 'frontend-agent')['status'])

    def test_bound_without_real_enforcement_cannot_start(self):
        value = spec()
        value['components']['java-output']['measurement'] = 'ENFORCED_BOUND'
        result = budget.check(budget.plan(value), probe(), 'java')
        self.assertEqual('FAIL_CLOSED', result['status'])
        self.assertTrue(any('growthMonitor' in reason for reason in result['reasons']))

    def test_unknown_future_does_not_block_measured_current_phase(self):
        value = spec()
        value['components']['agent-node-modules'].update(peakBytes=None, measurement='NOT_MEASURED')
        result = budget.check(budget.plan(value), probe(), 'java')
        self.assertEqual('PHASE_ADMITTED', result['status'])
        self.assertEqual('NOT_MEASURED', result['fullPlanStatus'])

    def test_two_gib_real_disk_reserve_is_never_borrowed(self):
        result = budget.check(budget.plan(spec()), probe(diskAvailableBytes=2 * GIB - 1), 'java')
        self.assertEqual('STOP_OWNED_ATTEMPT', result['action'])
        self.assertEqual('OWNED_ATTEMPT_ONLY', result['stopScope'])
        self.assertTrue(result['preserveEvidence'])

    def test_growth_over_phase_envelope_stops_even_with_free_disk(self):
        result = budget.check(budget.plan(spec()), probe(ownedDiskBytes=4 * GIB), 'java')
        self.assertEqual('FAIL_CLOSED', result['status'])
        self.assertTrue(any('exceeds' in reason for reason in result['reasons']))

    def test_observed_owned_growth_is_not_counted_twice(self):
        value = spec()
        original = budget.check(budget.plan(value), probe(), 'java')
        current = probe(diskAvailableBytes=7 * GIB - 100 * MIB, ownedDiskBytes=200 * MIB)
        result = budget.check(budget.plan(value), current, 'java')
        self.assertEqual('PASS', result['status'])
        self.assertEqual(original['requiredFreeDiskBytes'] - 100 * MIB, result['requiredFreeDiskBytes'])
        self.assertEqual(0, result['externalDiskLossBytes'])

    def test_real_external_disk_pressure_is_seen(self):
        result = budget.check(budget.plan(spec()), probe(diskAvailableBytes=2 * GIB), 'java')
        self.assertEqual(5 * GIB, result['externalDiskLossBytes'])
        self.assertEqual('FAIL_CLOSED', result['status'])

    def test_baseline_storage_is_not_billed_again(self):
        value = spec()
        value['components']['maven-cache']['baselineBytes'] = 10 * MIB
        result = budget.plan(value)
        self.assertEqual(400 * MIB, result['peakAdditionalDiskBytes'])

    def test_no_ownership_rebase_or_plan_tampering(self):
        result = budget.plan(spec())
        self.assertEqual('FAIL_CLOSED', budget.check(result, probe(ownerToken='other-attempt'), 'java')['status'])
        self.assertEqual('FAIL_CLOSED', budget.check(result, probe(), 'java', probe(ownedDiskBytes=0))['status'])
        result['diskReserveBytes'] = 0
        self.assertEqual('INVALID', budget.validate(result)['status'])

    def test_memory_is_remaining_owned_limit_and_oom_fails_closed(self):
        value = spec()
        running = probe(memoryAvailableBytes=2 * GIB, ownedMemoryBytes=GIB)
        self.assertEqual('PASS', budget.check(budget.plan(value), running, 'java')['status'])
        running['oomKills'] = 1
        self.assertEqual('FAIL_CLOSED', budget.check(budget.plan(value), running, 'java')['status'])

    def test_protected_database_reports_sources_and_cache_cannot_be_dropped(self):
        value = spec()
        value['phases'][1]['components'].remove('fixture-mysql')
        self.assertEqual('INVALID', budget.plan(value)['status'])
        value = spec()
        value['components']['runtime-backups']['retention'] = 'OWNED_BUILD_OUTPUT'
        self.assertEqual('INVALID', budget.plan(value)['status'])

    def test_parallel_frontend_dependency_trees_are_rejected(self):
        value = spec()
        value['phases'][0]['components'] += ['main-node-modules', 'agent-node-modules']
        self.assertEqual('INVALID', budget.plan(value)['status'])

    def test_zero_still_requires_measurement_and_evidence(self):
        value = spec()
        value['components']['runtime-images']['peakBytes'] = 0
        value['components']['runtime-images']['evidenceSha256'] = None
        self.assertEqual('NOT_MEASURED', budget.plan(value)['status'])

    def test_source_measurement_needed_before_fixture_stage(self):
        value = spec()
        del value['source']['dumpBytes']
        self.assertEqual('FAIL_CLOSED', budget.check(budget.plan(value), probe(), 'java')['status'])

    def test_inconsistent_probe_capacity_timestamp_and_boolean_bytes_rejected(self):
        for changes in ({'diskAvailableBytes': 41 * GIB}, {'diskTotalBytes': 50 * GIB},
                        {'ownedDiskBytes': True}, {'capturedAtUtc': '2026-11-07T03:59:59Z'}):
            with self.subTest(changes=changes):
                self.assertEqual('FAIL_CLOSED', budget.check(budget.plan(spec()), probe(**changes), 'java')['status'])

    def test_unknown_or_missing_baseline_does_not_crash(self):
        value = spec()
        del value['baselineProbe']
        self.assertEqual('FAIL_CLOSED', budget.check(budget.plan(value), probe(), 'java')['status'])
        self.assertEqual('FAIL_CLOSED', budget.check(budget.plan(spec()), probe(), 'not-a-phase')['status'])


def phase_spec(phase='extraction', **changes):
    value = {'ownerToken': 'ci-123-abcdef12', 'sourceCommit': 'b' * 40,
             'sourceSha256': DIGEST, 'applicationJarSha256': DIGEST,
             'enforcementEvidenceSha256': DIGEST, 'phase': phase,
             'baselineProbe': probe(), 'attemptBaselineProbe': probe(),
             'previousPhaseReceiptSha256': None if phase == 'extraction' else DIGEST,
             'growthEnvelopeBytes': 600 * MIB, 'memoryAdmissionBytes': 3 * GIB,
             'ownedMemoryLimitBytes': 2 * GIB,
             'measuredInputs': {'archiveDeclaredBytes': 1024, 'archiveAllocatedBoundBytes': 8192,
                                'archiveMemberCount': 2, 'jarCopyBytes': 2048,
                                'sourceAllocatedBytes': 300 * MIB, 'dumpBytes': 100 * MIB,
                                'dumpSha256': DIGEST, 'backupManifestSha256': DIGEST,
                                'sourceSnapshotSha256': DIGEST},
             'enforcement': {'independentMonitor': True, 'ownedPhysicalDiskMeasured': True,
                 'registeredProcessGroups': True, 'controllerAddressSpaceLimited': True,
                 'maxProbeIntervalSeconds': 2, 'diskOvershootBytes': 256 * MIB,
                 'sourceExportCancellation': True, 'mysqlCgroupLimitBytes': 1536 * MIB}}
    value.update(changes)
    return value


class ControlledPreparationBudgetTests(unittest.TestCase):
    def test_seven_gib_can_admit_measured_current_phase_without_claiming_full_fit(self):
        planned = budget.plan_phase(phase_spec())
        result = budget.check_phase(planned, probe())
        self.assertEqual('MEASUREMENT_ADMITTED', result['status'])
        self.assertEqual(2 * GIB + 856 * MIB, result['requiredFreeDiskBytes'])
        self.assertEqual('NOT_MEASURED', result['fullAcceptanceStatus'])
        self.assertFalse(result['allAcceptanceResourcesMeasured'])

    def test_other_tasks_freeing_disk_cannot_hide_our_excess_allocation(self):
        result = budget.check_phase(budget.plan_phase(phase_spec()),
            probe(ownedDiskBytes=701 * MIB, diskAvailableBytes=8 * GIB))
        self.assertEqual('FAIL_CLOSED', result['status'])
        self.assertEqual(601 * MIB, result['observedOwnedGrowthBytes'])
        self.assertEqual(0, result['hostDiskLossObservation']['bytes'])
        self.assertFalse(result['hostDiskLossObservation']['ownershipProof'])

    def test_clone_needs_completed_dump_and_snapshot_digests(self):
        for key in ('dumpBytes', 'dumpSha256', 'backupManifestSha256', 'sourceSnapshotSha256'):
            with self.subTest(key=key):
                value = phase_spec('fixture-clone')
                del value['measuredInputs'][key]
                self.assertEqual('NOT_MEASURED', budget.plan_phase(value)['status'])
                self.assertEqual('FAIL_CLOSED', budget.check_phase(budget.plan_phase(value), probe())['status'])

    def test_current_phase_receipt_chain_cannot_silently_rebase(self):
        value = phase_spec('source-export', previousPhaseReceiptSha256=None)
        self.assertEqual('NOT_MEASURED', budget.plan_phase(value)['status'])
        value = phase_spec(previousPhaseReceiptSha256=DIGEST)
        self.assertEqual('INVALID', budget.plan_phase(value)['status'])

    def test_real_disk_floor_and_overshoot_cannot_be_borrowed(self):
        result = budget.check_phase(budget.plan_phase(phase_spec()),
            probe(ownedDiskBytes=700 * MIB, diskAvailableBytes=2 * GIB + 256 * MIB - 1))
        self.assertEqual('FAIL_CLOSED', result['status'])
        self.assertEqual('OWNED_ATTEMPT_ONLY', result['stopScope'])
        self.assertTrue(result['preserveEvidence'])

    def test_observed_owned_growth_reduces_remaining_envelope_once(self):
        result = budget.check_phase(budget.plan_phase(phase_spec()), probe(ownedDiskBytes=300 * MIB))
        self.assertEqual('MEASUREMENT_ADMITTED', result['status'])
        self.assertEqual(400 * MIB, result['remainingGrowthEnvelopeBytes'])
        self.assertEqual(2 * GIB + 656 * MIB, result['requiredFreeDiskBytes'])

    def test_missing_actual_monitor_or_limits_is_not_enforced_bound(self):
        for key in ('independentMonitor', 'ownedPhysicalDiskMeasured', 'registeredProcessGroups',
                    'controllerAddressSpaceLimited', 'maxProbeIntervalSeconds', 'diskOvershootBytes'):
            with self.subTest(key=key):
                value = phase_spec(); del value['enforcement'][key]
                self.assertEqual('FAIL_CLOSED', budget.check_phase(budget.plan_phase(value), probe())['status'])

    def test_source_cancellation_and_fixture_cgroup_are_required_only_where_applicable(self):
        value = phase_spec('source-export'); value['enforcement']['sourceExportCancellation'] = False
        self.assertEqual('NOT_MEASURED', budget.plan_phase(value)['status'])
        value = phase_spec('fixture-clone'); value['enforcement']['mysqlCgroupLimitBytes'] = GIB
        self.assertEqual('NOT_MEASURED', budget.plan_phase(value)['status'])

    def test_timestamp_filesystem_commit_owner_oom_and_memory_fail_closed(self):
        for change in ({'capturedAtUtc': '2026-11-07T03:59:59Z'}, {'diskTotalBytes': 41 * GIB},
                       {'sourceCommit': 'c' * 40}, {'ownerToken': 'ci-other-attempt'}, {'oomKills': 1},
                       {'memoryAvailableBytes': 3 * GIB}, {'ownedMemoryBytes': 2 * GIB + 1}):
            with self.subTest(change=change):
                self.assertEqual('FAIL_CLOSED', budget.check_phase(budget.plan_phase(phase_spec()), probe(**change))['status'])

    def test_derived_plan_tampering_does_not_lower_reserve(self):
        planned = budget.plan_phase(phase_spec()); planned['diskReserveBytes'] = 0
        self.assertEqual('FAIL_CLOSED', budget.check_phase(planned, probe())['status'])


class PreparationEnforcementTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'linux', 'Private failure retention is verified only on ECS Linux')
    def test_primary_failure_is_preserved_before_cleanup_and_never_replaced_by_it(self):
        with tempfile.TemporaryDirectory() as temp:
            preparation = preparer.Preparation.__new__(preparer.Preparation)
            preparation.work = Path(temp)
            preparation.attempt = preparation.work / 'attempt'
            preparation.args = SimpleNamespace(tag='ci-123-' + 'b' * 12, commit='b' * 40, source_sha256='a' * 64)
            preparation.journal = {'phase': 'SOURCE_EXPORT_BOUND', 'activeResourcePhase': 'source-export'}
            def prepare_controlled():
                preparer.require(False, 'MYSQL_PWD=synthetic-primary-secret')
            def close(failed):
                self.assertTrue(failed)
                self.assertTrue((preparation.work / 'failure.json').is_file())
                preparation.journal['phase'] = 'OWNED_SERVER_STOPPED'
                raise ValueError('synthetic-secondary-cleanup-secret')
            preparation.prepare_controlled = prepare_controlled
            preparation.resources = SimpleNamespace(close=close)
            with self.assertRaisesRegex(ValueError, 'synthetic-secondary-cleanup-secret'):
                preparation.prepare()
            file = preparation.work / 'failure.json'
            raw = file.read_bytes(); value = json.loads(raw)
            self.assertEqual('SOURCE_EXPORT_BOUND', value['phase'])
            self.assertEqual('source-export', value['resourcePhase'])
            self.assertEqual('ValueError', value['errorType'])
            self.assertTrue(any(v['function'] == 'require' for v in value['locations']))
            self.assertEqual(preparation.failure_origin, preparation.retain_failure(KeyError('later secret')))
            self.assertEqual(raw, file.read_bytes())
            self.assertNotIn(b'secret', raw)
            self.assertFalse((preparation.attempt / '.fixtures-ready.json').exists())

    def failed_monitor(self, folder):
        monitor = preparer.PreparationMonitor.__new__(preparer.PreparationMonitor)
        monitor.lock = threading.Lock(); monitor.failed = threading.Event(); monitor.stop = threading.Event()
        monitor.token = 'e' * 32; monitor.measured_at = time.monotonic()
        monitor.preparation = SimpleNamespace(work=folder)
        return monitor

    @unittest.skipUnless(sys.platform == 'linux', 'Native monitoring failure evidence is verified only on ECS Linux')
    def test_collector_retains_its_source_location_without_error_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            monitor = self.failed_monitor(Path(temp))
            def measure():
                preparer.require(False, 'MYSQL_PWD=synthetic-measure-secret')
            monitor.measure = measure
            with patch.object(preparer.os, 'kill') as kill:
                monitor.collect()
                kill.assert_called_once_with(os.getpid(), signal.SIGUSR1)
            raw = (Path(temp) / 'resource-failure.json').read_bytes(); value = json.loads(raw)
            self.assertTrue(monitor.failed.is_set())
            self.assertEqual('collector', value['worker'])
            self.assertEqual('ValueError', value['errorType'])
            self.assertTrue(any(v['function'] == 'collect' for v in value['locations']))
            self.assertGreaterEqual(value['lastProbeAgeSeconds'], 0)
            self.assertNotIn(b'synthetic-measure-secret', raw)

    @unittest.skipUnless(sys.platform == 'linux', 'Monotonic monitoring gates are verified only on ECS Linux')
    def test_watcher_distinguishes_missed_schedule_from_stale_measurement_without_weakening_either(self):
        locations = []
        for case, ticks, measured in (('schedule', [10, 13, 14], 10), ('stale', [10, 11, 12], 8)):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                monitor = self.failed_monitor(Path(temp)); monitor.measured_at = measured
                with patch.object(preparer.time, 'monotonic', side_effect=ticks), patch.object(preparer.os, 'kill') as kill:
                    monitor.watch()
                    kill.assert_called_once_with(os.getpid(), signal.SIGUSR1)
                value = json.loads((Path(temp) / 'resource-failure.json').read_bytes())
                self.assertTrue(monitor.failed.is_set())
                self.assertEqual('watcher', value['worker'])
                self.assertEqual(4, value['lastProbeAgeSeconds'])
                frames = [v for v in value['locations'] if v['function'] == 'watch']
                self.assertEqual(1, len(frames)); locations.append(frames[0]['line'])
        self.assertNotEqual(locations[0], locations[1])

    @unittest.skipUnless(sys.platform == 'linux', 'The real source-capability shell runs only on ECS Linux')
    def test_source_capability_reads_the_explicit_shell_pid_and_only_publishes_after_success(self):
        source_id = 'c' * 64
        original = {'Id': source_id, 'Image': 'sha256:' + 'd' * 64, 'State': {'Running': True}}
        for case in ('correct', 'missing', 'mismatch'):
            with self.subTest(case=case):
                preparation = preparer.Preparation.__new__(preparer.Preparation)
                preparation.journal = {'sourceContainerId': source_id}
                preparation.resources = SimpleNamespace(source=None)
                phases, captured = [], []
                def save(phase):
                    phases.append(phase); preparation.journal['phase'] = phase
                preparation.save = save
                def docker_call(*arguments, **kwargs):
                    captured.append(arguments)
                    self.assertEqual(9, len(arguments))
                    self.assertEqual(('exec', '--env'), arguments[:2])
                    self.assertEqual((source_id, 'sh', '-ec'), arguments[3:6])
                    self.assertEqual('--', arguments[7]); self.assertEqual({'timeout': 15}, kwargs)
                    key, _, nonce = arguments[2].partition('=')
                    self.assertEqual('DOORHANDLE_CANCEL_PROBE', key)
                    self.assertEqual(nonce, arguments[8])
                    self.assertEqual(32, len(nonce)); self.assertTrue(all(c in '0123456789abcdef' for c in nonce))
                    script = arguments[6]
                    self.assertNotIn('/proc/self', script)
                    self.assertEqual(2, script.count('"/proc/$$/stat"'))
                    self.assertEqual(1, script.count('"/proc/$$/environ"'))
                    self.assertEqual(['SOURCE_EXPORT_BOUND'], phases)
                    self.assertIsNot(True, preparation.journal.get('sourceExportCancellationVerified'))
                    environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C'}
                    if case == 'correct': environment[key] = nonce
                    if case == 'mismatch': environment[key] = '0' * 32 if nonce != '0' * 32 else '1' * 32
                    child = subprocess.run(['/bin/sh', '-ec', script, '--', nonce], env=environment,
                                           capture_output=True, timeout=5)
                    self.assertTrue(child.stdout == b'', 'The capability probe must not emit environment or proc bytes')
                    self.assertTrue(child.stderr == b'', 'The capability probe must not expose its synthetic nonce')
                    if child.returncode:
                        raise ValueError('Controlled synthetic capability probe failed')
                    return child.stdout
                preparation.docker_call = docker_call
                if case == 'correct':
                    preparation.bind_source_exports(original)
                    self.assertIs(True, preparation.journal.get('sourceExportCancellationVerified'))
                    self.assertEqual('SOURCE_EXPORT_CANCELLATION_READY', phases[-1])
                else:
                    with self.assertRaises(ValueError): preparation.bind_source_exports(original)
                    self.assertIsNot(True, preparation.journal.get('sourceExportCancellationVerified'))
                    self.assertNotIn('SOURCE_EXPORT_CANCELLATION_READY', phases)
                self.assertEqual(1, len(captured))

    def test_fixture_failure_details_only_export_own_locations_without_exception_payload(self):
        secret = 'MYSQL_PWD=synthetic-secret-never-exported'
        try:
            preparer.require(False, secret)
        except ValueError as error:
            details = preparer.failure_details(error)
        else:
            self.fail('The real controller require must raise')
        self.assertEqual({'errorType', 'locations'}, set(details))
        self.assertEqual('ValueError', details['errorType'])
        self.assertEqual(1, len(details['locations']))
        for location in details['locations']:
            self.assertEqual({'function', 'line'}, set(location))
            self.assertEqual('require', location['function'])
            self.assertIs(type(location['line']), int); self.assertGreater(location['line'], 0)
        raw = json.dumps(details)
        self.assertNotIn(secret, raw)
        self.assertNotIn(str(Path(__file__).resolve()), raw)
        self.assertNotIn(Path(__file__).name, raw)
        self.assertNotIn('test_fixture_failure_details', raw)

    @unittest.skipUnless(sys.platform == 'linux', 'Native signal restoration is verified only on ECS Linux')
    def test_late_monitor_failure_cannot_close_successfully_and_publish_readiness(self):
        controller = self.controller()
        controller.lock = threading.RLock(); controller.stop = threading.Event(); controller.failed.set()
        controller.old_signal = signal.getsignal(signal.SIGUSR1)
        worker = SimpleNamespace(join=lambda **_: None, is_alive=lambda: False)
        controller.watcher = controller.collector = worker
        controller.preparation.cancel_source_exports = lambda: None
        controller.preparation.cleanup_java_probe = lambda: None
        controller.preparation.cleanup = lambda: None
        with tempfile.TemporaryDirectory() as temp:
            controller.stream = (Path(temp) / 'probes').open('w')
            controller.group_stream = (Path(temp) / 'groups').open('w')
            with self.assertRaisesRegex(ValueError, 'no readiness marker'):
                controller.close(False)
            self.assertTrue(controller.stream.closed and controller.group_stream.closed)

    def archive(self, folder, extra=()):
        target = folder / 'source.tar.gz'
        with tarfile.open(target, 'w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': 'b' * 40}) as package:
            for name, content in (('script/jenkins/prepare-compact-fixtures.py', PREPARER_MODULE.read_bytes()),
                                  ('script/jenkins/ecs-resource-budget.py', MODULE.read_bytes())):
                info = tarfile.TarInfo(name); info.size = len(content)
                package.addfile(info, io.BytesIO(content))
            for info, content in extra:
                package.addfile(info, io.BytesIO(content) if content is not None else None)
        return target, hashlib.sha256(target.read_bytes()).hexdigest()

    def test_archive_allocation_uses_actual_filesystem_blocks_and_fixed_self_source(self):
        with tempfile.TemporaryDirectory() as temp:
            archive, digest = self.archive(Path(temp))
            result, raw = preparer.archive_inventory(archive, 'b' * 40, digest, PREPARER_MODULE, 4096)
            sizes = [PREPARER_MODULE.stat().st_size, MODULE.stat().st_size]
            self.assertEqual(sum(sizes), result['archiveDeclaredBytes'])
            self.assertEqual(sum(((size + 4095) // 4096) * 4096 for size in sizes) + 2 * 4096,
                             result['archiveAllocatedBoundBytes'])
            self.assertEqual(MODULE.read_bytes(), raw)

    def test_archive_rejects_links_duplicate_members_and_escaping_paths(self):
        bad = []
        symlink = tarfile.TarInfo('link'); symlink.type = tarfile.SYMTYPE; symlink.linkname = '/tmp'
        bad.append((symlink, None))
        for name in ('../escape', 'work/old-data', 'script/jenkins/ecs-resource-budget.py', 'bad\\name'):
            item = tarfile.TarInfo(name); item.size = 1; bad.append((item, b'x'))
        for item in bad:
            with self.subTest(member=item[0].name), tempfile.TemporaryDirectory() as temp:
                archive, digest = self.archive(Path(temp), [item])
                with self.assertRaises(ValueError):
                    preparer.archive_inventory(archive, 'b' * 40, digest, PREPARER_MODULE)

    def test_archive_rejects_wrong_commit_digest_self_recipe_and_block_size(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); archive, digest = self.archive(folder)
            other = folder / 'other.py'; other.write_bytes(b'wrong recipe')
            for changes in ({'commit': 'c' * 40}, {'source_sha': '0' * 64},
                            {'own_script': other}, {'block_bytes': 3000}):
                arguments = dict(archive=archive, commit='b' * 40, source_sha=digest, own_script=PREPARER_MODULE)
                arguments.update(changes)
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    preparer.archive_inventory(**arguments)

    def controller(self):
        monitor = preparer.PreparationMonitor.__new__(preparer.PreparationMonitor)
        monitor.token = 'd' * 32; monitor.processes = {}; monitor.process_lock = threading.Lock()
        monitor.cleaning = False; monitor.failed = threading.Event(); monitor.group_stream = io.StringIO()
        monitor.preparation = SimpleNamespace(args=SimpleNamespace(commit='b' * 40))
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        monitor.claim_directory = Path(directory.name) / 'owned-command-claims'
        monitor.claim_directory.mkdir(mode=0o700)
        return monitor

    @unittest.skipUnless(sys.platform == 'linux', 'Native process ownership is verified only on ECS Linux')
    def test_real_owned_process_group_stops_without_touching_an_unrelated_session(self):
        controller = self.controller()
        unrelated = subprocess.Popen([sys.executable, '-I', '-B', '-c', 'import time; time.sleep(30)'],
                                     start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        owned = None
        try:
            owned = controller.popen([sys.executable, '-I', '-B', '-c', 'import time; time.sleep(30)'],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            controller.stop_group(owned)
            self.assertIsNotNone(owned.poll())
            self.assertIsNone(unrelated.poll())
            receipt = controller.group_stream.getvalue()
            self.assertIn('argumentsSha256', receipt)
            self.assertNotIn('PATH=', receipt)
        finally:
            if owned is not None and owned.poll() is None:
                controller.stop_group(owned)
            unrelated.terminate(); unrelated.wait(timeout=5)

    @unittest.skipUnless(sys.platform == 'linux', 'Native process ownership is verified only on ECS Linux')
    def test_owned_descendant_remains_cancellable_after_its_group_leader_exits(self):
        controller = self.controller()
        script = ('import subprocess,sys; '
                  'subprocess.Popen([sys.executable,"-I","-B","-c","import time; time.sleep(30)"],'
                  'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)')
        leader = controller.popen([sys.executable, '-I', '-B', '-c', script],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        claim = controller.processes[leader.pid][2]
        try:
            leader.wait(timeout=5)
            deadline = time.monotonic() + 2
            while not preparer.group_members(leader.pid, controller.token, claim) and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(preparer.group_members(leader.pid, controller.token, claim))
            controller.stop_group(leader)
            self.assertEqual([], preparer.group_members(leader.pid, controller.token, claim))
        finally:
            controller.stop_group(leader)

    @unittest.skipUnless(sys.platform == 'linux', 'Native process ownership is verified only on ECS Linux')
    def test_foreign_session_cannot_be_claimed_by_only_its_pid(self):
        child = subprocess.Popen([sys.executable, '-I', '-B', '-c', 'import time; time.sleep(30)'],
                                 start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            preparer.stop_owned_group(child.pid, 'd' * 32, 'e' * 32)
            self.assertIsNone(child.poll())
            with self.assertRaises(ValueError):
                preparer.stop_owned_group(os.getpgrp(), 'd' * 32, 'e' * 32)
        finally:
            child.terminate(); child.wait(timeout=5)

    @unittest.skipUnless(sys.platform == 'linux', 'Native process ownership is verified only on ECS Linux')
    def test_persisted_spawn_intent_cleans_a_child_missing_from_the_pid_registry(self):
        controller = self.controller()
        child = controller.popen([sys.executable, '-I', '-B', '-c', 'import time; time.sleep(30)'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            # Simulate interruption after Popen but before the PID receipt was
            # appended: only the durable pre-spawn capability remains.
            preparation = preparer.Preparation.__new__(preparer.Preparation)
            preparation.work = controller.claim_directory.parent
            preparation.journal = {'resourceOwnerToken': controller.token}
            preparation.args = SimpleNamespace(commit='b' * 40)
            stopped = preparation.cancel_owned_groups()
            child.wait(timeout=5)
            self.assertEqual([child.pid], [entry['group'] for entry in stopped])
        finally:
            if child.poll() is None:
                controller.stop_group(child)

    @unittest.skipUnless(sys.platform == 'linux', 'Native watchdog signals are verified only on ECS Linux')
    def test_stale_real_watchdog_signals_its_controller_and_preserves_failure_evidence(self):
        # A dedicated child proves the real watchdog/signal path without changing
        # pytest's own signal handlers, rlimits or any runtime container.
        script = '''
import importlib.util,json,signal,sys,threading,time
from pathlib import Path
from types import SimpleNamespace
spec=importlib.util.spec_from_file_location('preparer_watchdog_child',sys.argv[1])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
monitor=module.PreparationMonitor.__new__(module.PreparationMonitor)
monitor.token='d'*32; monitor.stop=threading.Event(); monitor.failed=threading.Event()
monitor.lock=threading.RLock(); monitor.measured_at=time.monotonic()-10
monitor.current=None; monitor.failure=None; monitor.last={}
monitor.preparation=SimpleNamespace(work=Path(sys.argv[2]),attempt=Path(sys.argv[2]))
def interrupted(*_): raise module.ResourceLimitExceeded('owned watcher signalled')
signal.signal(signal.SIGUSR1,interrupted)
worker=threading.Thread(target=monitor.watch,daemon=True)
interrupted_by_watcher=False
try:
    worker.start(); time.sleep(5)
except module.ResourceLimitExceeded:
    interrupted_by_watcher=True
finally:
    monitor.stop.set(); worker.join(timeout=2)
receipt=json.loads((Path(sys.argv[2])/'resource-failure.json').read_text())
assert interrupted_by_watcher and monitor.failed.is_set() and not worker.is_alive()
assert receipt['stopScope']=='OWNED_ATTEMPT_ONLY' and receipt['evidenceRetained']
'''
        with tempfile.TemporaryDirectory() as temp:
            child = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(PREPARER_MODULE), temp],
                                   capture_output=True, timeout=10)
            self.assertEqual(0, child.returncode, child.stderr.decode('utf8', errors='replace'))


@unittest.skipUnless(sys.platform == 'linux', 'Bounded fixture measurement is verified only on ECS Linux')
class DuMeasurementTests(unittest.TestCase):
    @contextmanager
    def measurement(self, folder, command, clock):
        monitor = preparer.PreparationMonitor.__new__(preparer.PreparationMonitor)
        monitor.measure_lock = threading.Lock(); monitor.lock = threading.RLock()
        monitor.failed = threading.Event(); monitor.stop = threading.Event()
        monitor.token = 'e' * 32; monitor.du_failure = None; monitor.measured_at = 9.0
        monitor.last = {'retained': True}; monitor.current = None; monitor.phase_observations = None
        monitor.stream = io.StringIO(); monitor.sudo = Path('/usr/bin/sudo')
        monitor.timeout = Path('/usr/bin/timeout'); monitor.du = Path('/usr/bin/du')
        monitor.preparation = SimpleNamespace(work=folder, attempt=folder / 'attempt',
                                              args=SimpleNamespace(commit='b' * 40))
        monitor.fixture_memory = lambda: (0, 0)
        filesystem = SimpleNamespace(f_blocks=100000, f_frsize=4096, f_bavail=90000)
        with patch.object(preparer.subprocess, 'run', side_effect=command) as run, \
                patch.object(preparer.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(preparer.Path, 'read_text', return_value='MemAvailable: 123456 kB\n'), \
                patch.object(preparer.os, 'statvfs', return_value=filesystem), \
                patch.object(preparer, 'owned_tree_memory', return_value=64):
            yield monitor, run

    @staticmethod
    def output(folder, number=b'8192'):
        return number + b'\t' + str(folder / 'attempt').encode() + b'\n'

    def assert_unpublished(self, monitor):
        self.assertEqual({'retained': True}, monitor.last)
        self.assertEqual(9.0, monitor.measured_at)
        self.assertEqual('', monitor.stream.getvalue())

    def test_one_exit_one_retry_uses_remaining_deadlines_and_only_publishes_complete_result(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); clock = [10.0]; calls = []
            def command(arguments, **kwargs):
                calls.append((arguments, kwargs))
                self.assert_unpublished(monitor)
                clock[0] += .3 if len(calls) == 1 else .2
                return subprocess.CompletedProcess(arguments, 1 if len(calls) == 1 else 0,
                    b'partial' if len(calls) == 1 else self.output(folder),
                    b'du: opaque-secret: No such file or directory' if len(calls) == 1 else b'')
            with self.measurement(folder, command, clock) as (monitor, run):
                monitor.du_failure = (ValueError('obsolete'), {'attempts': ['obsolete']})
                value = monitor.measure()
                self.assertEqual(2, run.call_count)
                self.assertEqual('1.200000000s', calls[0][0][4])
                self.assertEqual('0.900000000s', calls[1][0][4])
                self.assertEqual('--kill-after=0.2s', calls[1][0][3])
                self.assertEqual([str(monitor.du), '-B1', '-x', '-s', '--', str(folder / 'attempt')], calls[1][0][5:])
                self.assertEqual(2, calls[0][1]['timeout'])
                self.assertAlmostEqual(1.7, calls[1][1]['timeout'])
                self.assertEqual('C', calls[1][1]['env']['LC_ALL'])
                self.assertEqual(8192, value['ownedDiskBytes'])
                self.assertEqual([value], [json.loads(line) for line in monitor.stream.getvalue().splitlines()])
                self.assertEqual(10.5, monitor.measured_at)
                self.assertIsNone(monitor.du_failure)
                self.assertNotIn('duFailure', value)

    def test_persistent_exit_one_retains_only_bounded_hashed_attempts_for_exact_exception(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); clock = [10.0]
            stdout = b'partial MYSQL_PWD=opaque-secret'; stderr = b'/private/opaque-secret: No such file or directory'
            def command(arguments, **kwargs):
                clock[0] += .1
                return subprocess.CompletedProcess(arguments, 1, stdout, stderr)
            with self.measurement(folder, command, clock) as (monitor, run):
                with self.assertRaises(ValueError) as caught:
                    monitor.measure()
                self.assertEqual(2, run.call_count); self.assert_unpublished(monitor)
                self.assertIs(caught.exception, monitor.du_failure[0])
                with patch.object(preparer.os, 'kill') as kill:
                    monitor.fail(caught.exception, worker='collector')
                    kill.assert_called_once_with(os.getpid(), signal.SIGUSR1)
                raw = (folder / 'resource-failure.json').read_bytes(); value = json.loads(raw)
                rows = value['duFailure']['attempts']; self.assertEqual(2, len(rows))
                for row in rows:
                    self.assertEqual({'exitCode', 'elapsedSeconds', 'stdoutBytes', 'stdoutSha256',
                                      'stderrBytes', 'stderrSha256', 'stderrMentionsMissingPath'}, set(row))
                    self.assertEqual(1, row['exitCode']); self.assertAlmostEqual(.1, row['elapsedSeconds'])
                    self.assertEqual(len(stdout), row['stdoutBytes']); self.assertEqual(len(stderr), row['stderrBytes'])
                    self.assertEqual(hashlib.sha256(stdout).hexdigest(), row['stdoutSha256'])
                    self.assertEqual(hashlib.sha256(stderr).hexdigest(), row['stderrSha256'])
                    self.assertIs(True, row['stderrMentionsMissingPath'])
                self.assertNotIn(b'opaque-secret', raw); self.assertNotIn(str(folder).encode(), raw)

    def test_special_exit_codes_and_signals_never_start_a_second_du(self):
        for code in (2, 124, 125, 126, 127, 137, -9, -15):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp); clock = [10.0]
                def command(arguments, **kwargs):
                    clock[0] += .1
                    return subprocess.CompletedProcess(arguments, code, self.output(folder), b'opaque-secret')
                with self.measurement(folder, command, clock) as (monitor, run):
                    with self.assertRaises(ValueError): monitor.measure()
                    self.assertEqual(1, run.call_count); self.assert_unpublished(monitor)
                    self.assertEqual(code, monitor.du_failure[1]['attempts'][0]['exitCode'])

    def test_python_launch_and_timeout_errors_never_retry_or_export_exception_payload(self):
        errors = (subprocess.TimeoutExpired(['opaque-secret'], 2),
                  subprocess.TimeoutExpired(['opaque-secret'], 2, output=b'opaque-secret', stderr=b'opaque-secret'),
                  OSError('MYSQL_PWD=opaque-secret'))
        for error in errors:
            with self.subTest(error=type(error).__name__, output=getattr(error, 'output', None) is not None), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp); clock = [10.0]
                def command(arguments, **kwargs):
                    clock[0] += .1
                    raise error
                with self.measurement(folder, command, clock) as (monitor, run):
                    with self.assertRaises(type(error)) as caught: monitor.measure()
                    self.assertIs(error, caught.exception); self.assertEqual(1, run.call_count)
                    self.assert_unpublished(monitor)
                    metadata = monitor.du_failure[1]['attempts'][0]
                    self.assertIsNone(metadata['exitCode'])
                    self.assertEqual(len(getattr(error, 'stdout', None) or b''), metadata['stdoutBytes'])
                    self.assertEqual(len(getattr(error, 'stderr', None) or b''), metadata['stderrBytes'])
                    with patch.object(preparer.os, 'kill'):
                        monitor.fail(error, worker='collector')
                    self.assertNotIn(b'opaque-secret', (folder / 'resource-failure.json').read_bytes())

    def test_invalid_success_output_is_terminal_instead_of_retrying_or_publishing(self):
        for case in ('oversize', 'utf8', 'separator', 'decimal', 'negative', 'path'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp); clock = [10.0]
                outputs = {'oversize': b'x' * 4096, 'utf8': b'\xff\t' + str(folder / 'attempt').encode(),
                           'separator': b'8192', 'decimal': self.output(folder, b'8x'),
                           'negative': self.output(folder, b'-1'), 'path': b'8192\t/private/opaque-secret\n'}
                def command(arguments, **kwargs):
                    clock[0] += .1
                    return subprocess.CompletedProcess(arguments, 0, outputs[case], b'')
                with self.measurement(folder, command, clock) as (monitor, run):
                    with self.assertRaises((ValueError, UnicodeError)): monitor.measure()
                    self.assertEqual(1, run.call_count); self.assert_unpublished(monitor)
                    self.assertEqual(0, monitor.du_failure[1]['attempts'][0]['exitCode'])

    def test_exit_one_at_deadline_has_no_second_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); clock = [10.0]
            def command(arguments, **kwargs):
                clock[0] = 11.2
                return subprocess.CompletedProcess(arguments, 1, b'partial', b'')
            with self.measurement(folder, command, clock) as (monitor, run):
                with self.assertRaises(ValueError): monitor.measure()
                self.assertEqual(1, run.call_count); self.assert_unpublished(monitor)

    def test_positive_remainder_rounded_to_zero_never_launches_unbounded_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); clock = [10.0]
            with self.measurement(folder, lambda *_a, **_k: None, clock) as (monitor, run), \
                    patch.object(preparer.time, 'monotonic', side_effect=[10.0, 11.1999999999]):
                with self.assertRaises(ValueError): monitor.measure()
                run.assert_not_called(); self.assert_unpublished(monitor)
                self.assertEqual([], monitor.du_failure[1]['attempts'])

    def test_complete_zero_after_native_deadline_cannot_publish_a_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); clock = [10.0]
            def command(arguments, **kwargs):
                clock[0] = 11.200001
                return subprocess.CompletedProcess(arguments, 0, self.output(folder), b'')
            with self.measurement(folder, command, clock) as (monitor, run):
                with self.assertRaises(ValueError): monitor.measure()
                self.assertEqual(1, run.call_count); self.assert_unpublished(monitor)

    def test_other_metrics_may_exceed_du_deadline_within_fresh_whole_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); clock = [10.0]
            def command(arguments, **kwargs):
                clock[0] += .1
                return subprocess.CompletedProcess(arguments, 0, self.output(folder), b'')
            def memory(_pid):
                clock[0] = 11.3
                return 64
            with self.measurement(folder, command, clock) as (monitor, run), \
                    patch.object(preparer, 'owned_tree_memory', side_effect=memory):
                monitor.measured_at = 10.0
                value = monitor.measure()
                self.assertEqual(1, run.call_count)
                self.assertEqual(11.3, monitor.measured_at)
                self.assertAlmostEqual(1.3, value['measurementElapsedSeconds'])
                self.assertAlmostEqual(1.2, value['measurementTimingsSeconds']['ownedProcessMemory'])
                self.assertIsNone(monitor.du_failure)
                self.assertIsNone(monitor.measurement_failure)

    def test_whole_probe_deadline_is_rechecked_after_other_metrics_before_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); clock = [10.0]
            def command(arguments, **kwargs):
                clock[0] += .1
                return subprocess.CompletedProcess(arguments, 0, self.output(folder), b'')
            def memory(_pid):
                clock[0] = 12.000001
                return 64
            with self.measurement(folder, command, clock) as (monitor, run), \
                    patch.object(preparer, 'owned_tree_memory', side_effect=memory):
                with self.assertRaises(ValueError) as caught: monitor.measure()
                self.assertEqual(1, run.call_count); self.assert_unpublished(monitor)
                self.assertIsNone(monitor.du_failure)
                self.assertIs(caught.exception, monitor.measurement_failure[0])
                with patch.object(preparer.os, 'kill'):
                    monitor.fail(caught.exception, worker='collector')
                raw = (folder / 'resource-failure.json').read_bytes(); failure = json.loads(raw)
                self.assertNotIn('duFailure', failure)
                self.assertEqual('publication', failure['measurementFailure']['stage'])
                self.assertEqual({'du', 'hostMetrics', 'fixtureMemory', 'ownedProcessMemory', 'publication'},
                                 set(failure['measurementFailure']['timingsSeconds']))
                self.assertNotIn(str(folder).encode(), raw)

    def test_fast_whole_probe_cannot_publish_after_previous_probe_became_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); clock = [10.0]
            def command(arguments, **kwargs):
                clock[0] = 11.01
                return subprocess.CompletedProcess(arguments, 0, self.output(folder), b'')
            with self.measurement(folder, command, clock) as (monitor, run):
                with self.assertRaisesRegex(ValueError, 'monitor is stale') as caught:
                    monitor.measure()
                self.assertEqual(1, run.call_count); self.assert_unpublished(monitor)
                self.assertIsNone(monitor.du_failure)
                self.assertIs(caught.exception, monitor.measurement_failure[0])

    def test_first_probe_has_bounded_deadline_without_a_previous_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); clock = [10.0]
            def command(arguments, **kwargs):
                clock[0] = 10.1
                return subprocess.CompletedProcess(arguments, 0, self.output(folder), b'')
            with self.measurement(folder, command, clock) as (monitor, run):
                monitor.last = None; monitor.measured_at = 0.0
                self.assertEqual(8192, monitor.measure()['ownedDiskBytes'])
                self.assertEqual(10.1, monitor.measured_at)

    def test_unrelated_same_type_and_message_failure_cannot_inherit_du_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); clock = [10.0]
            def command(arguments, **kwargs):
                clock[0] += .1
                return subprocess.CompletedProcess(arguments, 127, b'', b'opaque-secret')
            with self.measurement(folder, command, clock) as (monitor, run):
                with self.assertRaises(ValueError) as caught: monitor.measure()
                other = ValueError(str(caught.exception))
                with patch.object(preparer.os, 'kill'):
                    monitor.fail(other, worker='watcher')
                value = json.loads((folder / 'resource-failure.json').read_bytes())
                self.assertNotIn('duFailure', value)
                self.assertEqual('watcher', value['worker'])

    def test_recovered_du_does_not_contaminate_later_non_du_metric_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); clock = [10.0]; calls = []
            def command(arguments, **kwargs):
                calls.append(arguments); clock[0] += .1
                return subprocess.CompletedProcess(arguments, 1 if len(calls) == 1 else 0,
                    self.output(folder), b'opaque-secret')
            with self.measurement(folder, command, clock) as (monitor, run), \
                    patch.object(preparer.os, 'statvfs', side_effect=OSError('opaque-secret')):
                with self.assertRaises(OSError) as caught: monitor.measure()
                self.assertEqual(2, run.call_count); self.assert_unpublished(monitor)
                self.assertIsNone(monitor.du_failure)
                with patch.object(preparer.os, 'kill'):
                    monitor.fail(caught.exception, worker='collector')
                raw = (folder / 'resource-failure.json').read_bytes()
                self.assertNotIn('duFailure', json.loads(raw)); self.assertNotIn(b'opaque-secret', raw)

    def test_unrelated_exception_cannot_inherit_metric_timings(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); clock = [10.0]
            def command(arguments, **kwargs):
                return subprocess.CompletedProcess(arguments, 0, self.output(folder), b'')
            with self.measurement(folder, command, clock) as (monitor, run), \
                    patch.object(preparer.os, 'statvfs', side_effect=OSError('opaque-secret')):
                with self.assertRaises(OSError) as caught: monitor.measure()
                other = OSError(str(caught.exception))
                with patch.object(preparer.os, 'kill'):
                    monitor.fail(other, worker='watcher')
                raw = (folder / 'resource-failure.json').read_bytes()
                self.assertNotIn('measurementFailure', json.loads(raw))
                self.assertNotIn(b'opaque-secret', raw)

    def test_watcher_retains_current_immutable_measurement_stage_without_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); clock = [11.2]
            with self.measurement(folder, lambda *_a, **_k: None, clock) as (monitor, run):
                snapshot = {'stage': 'ownedProcessMemory', 'started': 10.0, 'stageStarted': 10.5,
                    'timingsSeconds': {'du': .1, 'hostMetrics': .01, 'fixtureMemory': .02},
                    'extra': 'opaque-secret'}
                monitor.active_measurement = snapshot
                with patch.object(preparer.os, 'kill'):
                    monitor.fail(ValueError('opaque-secret'), worker='watcher')
                raw = (folder / 'resource-failure.json').read_bytes(); value = json.loads(raw)
                active = value['activeMeasurement']
                self.assertEqual({'stage', 'elapsedSeconds', 'stageElapsedSeconds', 'timingsSeconds'}, set(active))
                self.assertEqual('ownedProcessMemory', active['stage'])
                self.assertAlmostEqual(1.2, active['elapsedSeconds'])
                self.assertAlmostEqual(.7, active['stageElapsedSeconds'])
                snapshot['timingsSeconds']['du'] = 99
                self.assertEqual(.1, monitor.failure['activeMeasurement']['timingsSeconds']['du'])
                self.assertNotIn(b'opaque-secret', raw)
                self.assertNotIn(str(folder).encode(), raw)
                run.assert_not_called()

    def test_successful_measurement_clears_active_stage_before_unrelated_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); clock = [10.0]
            def command(arguments, **kwargs):
                return subprocess.CompletedProcess(arguments, 0, self.output(folder), b'')
            with self.measurement(folder, command, clock) as (monitor, run):
                monitor.active_measurement = {'extra': 'obsolete-secret'}
                monitor.measure()
                self.assertIsNone(monitor.active_measurement)
                with patch.object(preparer.os, 'kill'):
                    monitor.fail(ValueError('unrelated'), worker='watcher')
                raw = (folder / 'resource-failure.json').read_bytes()
                self.assertNotIn('activeMeasurement', json.loads(raw))
                self.assertNotIn(b'obsolete-secret', raw)


if __name__ == '__main__':
    unittest.main()
