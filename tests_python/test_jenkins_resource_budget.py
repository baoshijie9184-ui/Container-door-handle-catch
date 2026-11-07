"""Resource safety contracts. Run on the admitted ECS, never on the workstation."""
import importlib.util
from pathlib import Path
import unittest


MODULE = Path(__file__).resolve().parents[1] / 'script' / 'jenkins' / 'ecs-resource-budget.py'
SPEC = importlib.util.spec_from_file_location('ecs_resource_budget', MODULE)
budget = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(budget)
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


if __name__ == '__main__':
    unittest.main()
