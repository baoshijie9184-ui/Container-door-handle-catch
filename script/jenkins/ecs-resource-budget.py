"""Pure resource accounting for one owned ECS acceptance attempt.

This module never probes a host, starts/stops a process, removes a path, or grants
permission to alter a production resource. Callers supply measured, archived
evidence and host probes. Unknown stages cannot claim to fit; a caller may admit
an explicitly bounded current measurement phase with active owned monitoring.
"""
from copy import deepcopy
from datetime import datetime
import argparse
import json
from pathlib import Path
import re


VERSION = 1
GIB = 1024 ** 3
DISK_RESERVE_BYTES = 2 * GIB
MEMORY_RESERVE_BYTES = GIB
REQUIRED_COMPONENTS = (
    'extraction', 'maven-cache', 'java-output', 'suite-evidence',
    'main-node-modules', 'main-frontend-output', 'agent-node-modules',
    'agent-frontend-output', 'fixture-mysql', 'double-restore',
    'runtime-images', 'runtime-writable', 'runtime-backups', 'logs-receipts',
)
BUILD_OUTPUT_COMPONENTS = frozenset(('java-output', 'main-node-modules', 'agent-node-modules'))
HASH = re.compile(r'^[0-9a-f]{64}$')
COMMIT = re.compile(r'^[0-9a-f]{40}$')
TOKEN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$')


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _timestamp(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    except ValueError:
        return False


def _probe_errors(probe, owner, commit, total=None):
    errors = []
    if not isinstance(probe, dict):
        return ['actualProbe must be an object']
    if probe.get('ownerToken') != owner or probe.get('sourceCommit') != commit:
        errors.append('Probe ownership or fixed commit differs')
    if not _timestamp(probe.get('capturedAtUtc')):
        errors.append('Probe capturedAtUtc requires an explicit timezone')
    for key in ('diskTotalBytes', 'diskAvailableBytes', 'memoryAvailableBytes',
                'ownedDiskBytes', 'ownedMemoryBytes', 'oomKills'):
        if not _integer(probe.get(key)):
            errors.append('Invalid probe ' + key)
    if errors:
        return errors
    if probe['diskTotalBytes'] == 0 or probe['diskAvailableBytes'] > probe['diskTotalBytes']:
        errors.append('Probe disk capacity is inconsistent')
    if total is not None and probe['diskTotalBytes'] != total:
        errors.append('Probe filesystem capacity changed; replan before continuing')
    return errors


def _derive(spec):
    errors, missing, phases = [], [], []
    if not isinstance(spec, dict):
        return {'status': 'INVALID', 'errors': ['Budget spec must be an object'],
                'missingMeasurements': [], 'phases': [], 'peakAdditionalDiskBytes': None}
    if spec.get('version') != VERSION:
        errors.append('Unsupported resource budget version')
    owner, commit = spec.get('ownerToken'), spec.get('sourceCommit')
    if not isinstance(owner, str) or not TOKEN.fullmatch(owner):
        errors.append('ownerToken requires a unique attempt identifier')
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        errors.append('sourceCommit requires a full fixed Git commit')
    artifacts = spec.get('artifacts', {})
    if not isinstance(artifacts, dict):
        artifacts = {}
        errors.append('artifacts must be an object')
    for name in ('sourceArchive', 'applicationJar'):
        value = artifacts.get(name, {})
        if not isinstance(value, dict):
            value = {}
        if not _integer(value.get('bytes')) or value.get('bytes') == 0:
            missing.append('artifacts.' + name + '.bytes')
        if not isinstance(value.get('sha256'), str) or not HASH.fullmatch(value['sha256']):
            missing.append('artifacts.' + name + '.sha256')
    source = spec.get('source', {})
    if not isinstance(source, dict):
        source = {}
    for key in ('allocatedBytes', 'dumpBytes'):
        if not _integer(source.get(key)):
            missing.append('source.' + key)
    if not isinstance(source.get('evidenceSha256'), str) or not HASH.fullmatch(source['evidenceSha256']):
        missing.append('source.evidenceSha256')

    components = spec.get('components', {})
    if not isinstance(components, dict):
        components = {}
        errors.append('components must be an object')
    for name in REQUIRED_COMPONENTS:
        if name not in components:
            missing.append('components.' + name)
    measured = {}
    for name, value in components.items():
        if not isinstance(name, str) or not name or not isinstance(value, dict):
            errors.append('Component names and measurements must be objects')
            continue
        prefix = 'components.' + name + '.'
        for field in ('peakBytes', 'baselineBytes'):
            if not _integer(value.get(field)):
                missing.append(prefix + field)
        if value.get('measurement') not in ('MEASURED', 'ENFORCED_BOUND', 'NOT_MEASURED', None):
            errors.append(name + ' has an unsupported measurement mode')
        if value.get('measurement') != 'MEASURED':
            missing.append(prefix + 'measurement')
        if not isinstance(value.get('evidenceSha256'), str) or not HASH.fullmatch(value['evidenceSha256']):
            missing.append(prefix + 'evidenceSha256')
        expected = 'OWNED_BUILD_OUTPUT' if name in BUILD_OUTPUT_COMPONENTS else 'PROTECTED'
        if value.get('retention') != expected:
            errors.append(name + ' retention must be ' + expected)
        if _integer(value.get('peakBytes')) and _integer(value.get('baselineBytes')):
            if value['peakBytes'] < value['baselineBytes']:
                errors.append(name + ' peakBytes is smaller than its measured baseline')
            elif value.get('measurement') in ('MEASURED', 'ENFORCED_BOUND'):
                measured[name] = value['peakBytes'] - value['baselineBytes']

    raw_phases = spec.get('phases')
    if not isinstance(raw_phases, list) or not raw_phases:
        missing.append('phases')
        raw_phases = []
    seen_names, referenced, protected = set(), set(), set()
    for item in raw_phases:
        if not isinstance(item, dict):
            errors.append('A phase must be an object')
            continue
        name = item.get('name')
        if not isinstance(name, str) or not name or name in seen_names:
            errors.append('Phase names must be unique nonempty strings')
            continue
        seen_names.add(name)
        names = item.get('components')
        if (not isinstance(names, list) or not all(isinstance(key, str) for key in names)
                or len(names) != len(set(names))):
            errors.append(name + ' components must be a unique string list')
            continue
        current = set(names)
        referenced.update(current)
        unknown = current - set(components)
        if unknown:
            missing.extend('components.' + key for key in sorted(unknown))
        if protected - current:
            errors.append(name + ' drops protected data: ' + ', '.join(sorted(protected - current)))
        protected.update(current - BUILD_OUTPUT_COMPONENTS)
        if {'main-node-modules', 'agent-node-modules'} <= current:
            errors.append(name + ' retains both frontend dependency trees; use serial phases')
        memory = item.get('memoryLimitBytes')
        if not _integer(memory):
            missing.append('phases.' + name + '.memoryLimitBytes')
        amount = sum(measured[key] for key in names) if current <= set(measured) else None
        bounded = [key for key in names if isinstance(components.get(key), dict)
                   and components[key].get('measurement') == 'ENFORCED_BOUND']
        enforcement = item.get('enforcement', {})
        if bounded:
            if not isinstance(enforcement, dict):
                enforcement = {}
            for field in ('ownedProcessGroup', 'growthMonitor', 'memoryLimitEnforced'):
                if enforcement.get(field) is not True:
                    missing.append('phases.' + name + '.enforcement.' + field)
            interval = enforcement.get('maxProbeIntervalSeconds')
            if not isinstance(interval, (int, float)) or isinstance(interval, bool) or not 0 < interval <= 5:
                missing.append('phases.' + name + '.enforcement.maxProbeIntervalSeconds')
            if not _integer(enforcement.get('diskOvershootBytes')) or enforcement.get('diskOvershootBytes') == 0:
                missing.append('phases.' + name + '.enforcement.diskOvershootBytes')
        phases.append({'name': name, 'components': names, 'additionalDiskBytes': amount,
                       'memoryLimitBytes': memory if _integer(memory) else None,
                       'mode': 'ENFORCED_BOUND' if bounded else 'MEASURED' if amount is not None else 'NOT_MEASURED',
                       'enforcement': deepcopy(enforcement)})
    for key in REQUIRED_COMPONENTS:
        if key in components and key not in referenced:
            errors.append('Required component is absent from every phase: ' + key)
    probe = spec.get('baselineProbe')
    if probe is None:
        missing.append('baselineProbe')
    else:
        errors.extend(_probe_errors(probe, owner, commit))
    peak = (max((row['additionalDiskBytes'] for row in phases), default=0)
            if all(row['additionalDiskBytes'] is not None for row in phases) else None)
    return {'status': 'INVALID' if errors else 'NOT_MEASURED' if missing else 'READY',
            'errors': errors, 'missingMeasurements': sorted(set(missing)), 'phases': phases,
            'peakAdditionalDiskBytes': peak}


def plan(spec):
    """Serialize an evidence-bound serial plan; no host actions are performed.

    Components describe physical allocated bytes, including Docker *incremental
    unique* layers. A phase lists only components that coexist then. Baseline
    bytes already consume the actual probe's free space and are not charged twice.
    A measured zero still requires a real evidence digest; estimates are unmeasured.
    """
    derived = _derive(spec)
    return {'version': VERSION, 'spec': deepcopy(spec), **derived,
            'diskReserveBytes': DISK_RESERVE_BYTES, 'memoryReserveBytes': MEMORY_RESERVE_BYTES,
            'mode': 'MEASURED' if derived['status'] == 'READY' else 'PROGRESSIVE',
            'stopScope': 'OWNED_ATTEMPT_ONLY', 'preserveEvidence': True,
            'cleanupPolicy': 'VERIFIED_RAW_REPORT_ARCHIVE_BEFORE_OWNED_BUILD_OUTPUT_ONLY'}


def validate(resource_plan):
    """Validate the saved plan and reject changed/tampered derived quantities."""
    if not isinstance(resource_plan, dict) or 'spec' not in resource_plan:
        return {'status': 'INVALID', 'errors': ['Expected the result of plan(spec)'],
                'missingMeasurements': []}
    expected = plan(resource_plan['spec'])
    errors = list(expected['errors'])
    if resource_plan != expected:
        errors.append('Saved resource plan differs from its evidence-bound derivation')
    return {'status': 'INVALID' if errors else expected['status'], 'errors': errors,
            'missingMeasurements': expected['missingMeasurements']}


def check(resource_plan, actualProbe, phase, baselineProbe=None):
    """Check admission/growth; a failed result may stop only this owned attempt.

    Future unknown phases do not block a bounded measurement of the current
    phase. Such admission never proves that the complete acceptance fits.
    The caller samples physical free space and the owned attempt's allocated
    bytes while its command runs. ownedMemoryBytes is the owned cgroup's current
    use, and oomKills is its cumulative kill count. Original processes are never
    in this ownership set. An OOM, unmeasured plan, or lost reserve fails closed.
    """
    result = {'status': 'FAIL_CLOSED', 'action': 'STOP_OWNED_ATTEMPT',
              'stopScope': 'OWNED_ATTEMPT_ONLY', 'preserveEvidence': True,
              'phase': phase, 'actualProbe': deepcopy(actualProbe), 'reasons': []}
    validation = validate(resource_plan)
    result['fullPlanStatus'] = validation['status']
    result['allResourceMeasurementsPresent'] = validation['status'] == 'READY'
    if validation['status'] == 'INVALID':
        result['reasons'] = validation['errors']
        return result
    spec = resource_plan['spec']
    baseline = spec.get('baselineProbe') if baselineProbe is None else baselineProbe
    if not isinstance(baseline, dict):
        result['reasons'].append('NOT_MEASURED: baselineProbe')
        return result
    # A runtime caller cannot silently move the accounting origin after growth.
    if baseline != spec['baselineProbe']:
        result['reasons'].append('Accounting baseline changed; create a new measured plan')
        return result
    probe_errors = _probe_errors(actualProbe, spec['ownerToken'], spec['sourceCommit'], baseline['diskTotalBytes'])
    if probe_errors:
        result['reasons'] = probe_errors
        return result
    if datetime.fromisoformat(actualProbe['capturedAtUtc'].replace('Z', '+00:00')) < datetime.fromisoformat(baseline['capturedAtUtc'].replace('Z', '+00:00')):
        result['reasons'].append('Actual probe predates the accounting baseline')
        return result
    index = next((i for i, row in enumerate(resource_plan['phases']) if row['name'] == phase), None)
    if index is None:
        result['reasons'].append('Unknown phase')
        return result
    current = resource_plan['phases'][index]
    # Unknown future data is allowed only as a transparent, unproven plan. The
    # current phase still requires all its physical bytes and enforcement.
    missing = [key for key in validation['missingMeasurements']
               if key.startswith(('artifacts.', 'baselineProbe'))
               or key.startswith('phases.' + phase + '.')]
    if {'fixture-mysql', 'double-restore'} & set(current['components']):
        missing.extend(key for key in validation['missingMeasurements'] if key.startswith('source.'))
    for key in current['components']:
        value = spec.get('components', {}).get(key, {})
        for field in ('peakBytes', 'baselineBytes'):
            if not _integer(value.get(field)):
                missing.append('components.' + key + '.' + field)
        if value.get('measurement') not in ('MEASURED', 'ENFORCED_BOUND'):
            missing.append('components.' + key + '.measurement')
        if not isinstance(value.get('evidenceSha256'), str) or not HASH.fullmatch(value['evidenceSha256']):
            missing.append('components.' + key + '.evidenceSha256')
    if missing or current['additionalDiskBytes'] is None or current['memoryLimitBytes'] is None:
        result['reasons'] = ['NOT_MEASURED: ' + key for key in sorted(set(missing))]
        if not result['reasons']:
            result['reasons'] = ['Current phase has no complete measured envelope or enforced bound']
        return result
    growth = max(0, actualProbe['ownedDiskBytes'] - baseline['ownedDiskBytes'])
    memory_growth = max(0, actualProbe['ownedMemoryBytes'] - baseline['ownedMemoryBytes'])
    remaining = max(0, current['additionalDiskBytes'] - growth)
    overshoot = current['enforcement'].get('diskOvershootBytes', 0) if current['mode'] == 'ENFORCED_BOUND' else 0
    memory_remaining = max(0, current['memoryLimitBytes'] - memory_growth)
    result.update({'observedOwnedGrowthBytes': growth, 'phaseBudgetBytes': current['additionalDiskBytes'],
                   'mode': current['mode'], 'remainingPeakGrowthBytes': remaining,
                   'requiredFreeDiskBytes': remaining + DISK_RESERVE_BYTES + overshoot,
                   'requiredAvailableMemoryBytes': memory_remaining + MEMORY_RESERVE_BYTES,
                   'externalDiskLossBytes': max(0, baseline['diskAvailableBytes'] - actualProbe['diskAvailableBytes'] - growth)})
    if growth > current['additionalDiskBytes']:
        result['reasons'].append('Owned disk growth exceeds this measured phase envelope')
    if actualProbe['diskAvailableBytes'] < remaining + DISK_RESERVE_BYTES + overshoot:
        result['reasons'].append('Current phase growth would consume the real 2 GiB disk reserve or monitor overshoot allowance')
    if actualProbe['memoryAvailableBytes'] < memory_remaining + MEMORY_RESERVE_BYTES:
        result['reasons'].append('Owned memory limit would consume the 1 GiB host memory reserve')
    if memory_growth > current['memoryLimitBytes']:
        result['reasons'].append('Owned memory growth exceeds this phase limit')
    if actualProbe['oomKills'] > baseline['oomKills']:
        result['reasons'].append('An owned attempt cgroup has recorded an OOM kill')
    if actualProbe['oomKills'] < baseline['oomKills']:
        result['reasons'].append('Owned OOM counter decreased; cgroup evidence changed')
    if not result['reasons']:
        result.update({'status': 'MEASUREMENT_ADMITTED' if current['mode'] == 'ENFORCED_BOUND'
                       else 'PASS' if validation['status'] == 'READY' else 'PHASE_ADMITTED',
                       'action': 'MEASURE_OWNED_ATTEMPT' if current['mode'] == 'ENFORCED_BOUND'
                       else 'CONTINUE_OWNED_ATTEMPT'})
    return result


def plan_phase(spec):
    """Plan only the next controlled preparer measurement, never full acceptance.

    Physical ownedDiskBytes must be measured independently of host free-space
    changes. The immutable attempt baseline and earlier phase receipt digest are
    retained, so a new phase cannot hide earlier protected data or claim a peak
    measurement that has not happened.
    """
    errors, missing = [], []
    if not isinstance(spec, dict):
        spec = {}
        errors.append('Phase spec must be an object')
    owner, commit = spec.get('ownerToken'), spec.get('sourceCommit')
    if not isinstance(owner, str) or not TOKEN.fullmatch(owner):
        errors.append('Invalid phase ownerToken')
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        errors.append('Invalid fixed phase sourceCommit')
    phase = spec.get('phase')
    if phase not in ('extraction', 'source-inspection', 'source-export', 'fixture-clone'):
        errors.append('Unregistered controlled preparation phase')
    predecessor = spec.get('previousPhaseReceiptSha256')
    if phase == 'extraction' and predecessor is not None:
        errors.append('Extraction must start the fixed attempt receipt chain')
    elif phase != 'extraction' and (not isinstance(predecessor, str) or not HASH.fullmatch(predecessor)):
        missing.append('previousPhaseReceiptSha256')
    for key in ('sourceSha256', 'applicationJarSha256', 'enforcementEvidenceSha256'):
        if not isinstance(spec.get(key), str) or not HASH.fullmatch(spec[key]):
            missing.append(key)
    for key in ('growthEnvelopeBytes', 'memoryAdmissionBytes', 'ownedMemoryLimitBytes'):
        if not _integer(spec.get(key)) or spec.get(key) == 0:
            missing.append(key)
    baseline = spec.get('baselineProbe')
    origin = spec.get('attemptBaselineProbe')
    errors.extend(_probe_errors(baseline, owner, commit))
    errors.extend(_probe_errors(origin, owner, commit))
    if not errors and baseline['diskTotalBytes'] != origin['diskTotalBytes']:
        errors.append('Phase and attempt filesystem differ')
    if not errors and datetime.fromisoformat(baseline['capturedAtUtc'].replace('Z', '+00:00')) < datetime.fromisoformat(origin['capturedAtUtc'].replace('Z', '+00:00')):
        errors.append('Current phase baseline predates the immutable attempt baseline')
    enforcement = spec.get('enforcement', {})
    if not isinstance(enforcement, dict):
        enforcement = {}
    for key in ('independentMonitor', 'ownedPhysicalDiskMeasured', 'registeredProcessGroups', 'controllerAddressSpaceLimited'):
        if enforcement.get(key) is not True:
            missing.append('enforcement.' + key)
    interval = enforcement.get('maxProbeIntervalSeconds')
    if not isinstance(interval, (int, float)) or isinstance(interval, bool) or not 0 < interval <= 2:
        missing.append('enforcement.maxProbeIntervalSeconds')
    overshoot = enforcement.get('diskOvershootBytes')
    if not _integer(overshoot) or overshoot < 256 * 1024 ** 2:
        missing.append('enforcement.diskOvershootBytes')
    if phase in ('source-inspection', 'source-export') and enforcement.get('sourceExportCancellation') is not True:
        missing.append('enforcement.sourceExportCancellation')
    inputs = spec.get('measuredInputs', {})
    if not isinstance(inputs, dict):
        inputs = {}
    if phase == 'extraction':
        for key in ('archiveDeclaredBytes', 'archiveAllocatedBoundBytes', 'archiveMemberCount', 'jarCopyBytes'):
            if not _integer(inputs.get(key)):
                missing.append('measuredInputs.' + key)
    if phase in ('source-export', 'fixture-clone') and not _integer(inputs.get('sourceAllocatedBytes')):
        missing.append('measuredInputs.sourceAllocatedBytes')
    if phase == 'fixture-clone':
        if enforcement.get('mysqlCgroupLimitBytes') != 3 * 1024 ** 3:
            missing.append('enforcement.mysqlCgroupLimitBytes')
        if not _integer(inputs.get('dumpBytes')) or inputs.get('dumpBytes') == 0:
            missing.append('measuredInputs.dumpBytes')
        for key in ('dumpSha256', 'backupManifestSha256', 'sourceSnapshotSha256'):
            if not isinstance(inputs.get(key), str) or not HASH.fullmatch(inputs[key]):
                missing.append('measuredInputs.' + key)
    return {'version': 1, 'kind': 'doorhandle-controlled-preparer-phase', 'spec': deepcopy(spec),
            'status': 'INVALID' if errors else 'NOT_MEASURED' if missing else 'MEASUREMENT_PLANNED',
            'mode': 'ENFORCED_BOUND', 'errors': errors, 'missingMeasurements': sorted(set(missing)),
            'diskReserveBytes': DISK_RESERVE_BYTES, 'memoryReserveBytes': MEMORY_RESERVE_BYTES,
            'allAcceptanceResourcesMeasured': False, 'fullAcceptanceStatus': 'NOT_MEASURED',
            'stopScope': 'OWNED_ATTEMPT_ONLY', 'preserveEvidence': True}


def check_phase(resource_phase, actualProbe):
    """Check a preparer phase against real owned allocation and current pressure."""
    result = {'status': 'FAIL_CLOSED', 'action': 'STOP_OWNED_ATTEMPT',
              'stopScope': 'OWNED_ATTEMPT_ONLY', 'preserveEvidence': True,
              'fullAcceptanceStatus': 'NOT_MEASURED', 'allAcceptanceResourcesMeasured': False,
              'actualProbe': deepcopy(actualProbe), 'reasons': []}
    if not isinstance(resource_phase, dict) or 'spec' not in resource_phase:
        result['reasons'] = ['Missing controlled phase plan']
        return result
    expected = plan_phase(resource_phase['spec'])
    if resource_phase != expected:
        result['reasons'] = ['Controlled phase plan was changed after derivation']
        return result
    if expected['status'] != 'MEASUREMENT_PLANNED':
        result['reasons'] = expected['errors'] + ['NOT_MEASURED: ' + key for key in expected['missingMeasurements']]
        return result
    spec = resource_phase['spec']; baseline = spec['baselineProbe']
    errors = _probe_errors(actualProbe, spec['ownerToken'], spec['sourceCommit'], baseline['diskTotalBytes'])
    if errors:
        result['reasons'] = errors
        return result
    if datetime.fromisoformat(actualProbe['capturedAtUtc'].replace('Z', '+00:00')) < datetime.fromisoformat(baseline['capturedAtUtc'].replace('Z', '+00:00')):
        result['reasons'] = ['Current phase probe predates its fixed baseline']
        return result
    growth = max(0, actualProbe['ownedDiskBytes'] - baseline['ownedDiskBytes'])
    memory_growth = max(0, actualProbe['ownedMemoryBytes'] - baseline['ownedMemoryBytes'])
    remaining = max(0, spec['growthEnvelopeBytes'] - growth)
    required_disk = remaining + DISK_RESERVE_BYTES + spec['enforcement']['diskOvershootBytes']
    required_memory = max(MEMORY_RESERVE_BYTES, spec['memoryAdmissionBytes'] - memory_growth + MEMORY_RESERVE_BYTES)
    result.update(phase=spec['phase'], observedOwnedGrowthBytes=growth,
        remainingGrowthEnvelopeBytes=remaining, requiredFreeDiskBytes=required_disk,
        requiredAvailableMemoryBytes=required_memory,
        hostDiskLossObservation={'kind': 'HOST_DISK_LOSS_UPPER_BOUND',
            'bytes': max(0, baseline['diskAvailableBytes'] - actualProbe['diskAvailableBytes']),
            'ownershipProof': False})
    if growth > spec['growthEnvelopeBytes']:
        result['reasons'].append('Owned physical allocation exceeded this controlled phase envelope')
    if actualProbe['diskAvailableBytes'] < required_disk:
        result['reasons'].append('Actual free space cannot retain the phase envelope plus real 2 GiB reserve and overshoot')
    if actualProbe['memoryAvailableBytes'] < required_memory:
        result['reasons'].append('Host memory pressure would consume the controlled phase memory reserve')
    if actualProbe['ownedMemoryBytes'] > spec['ownedMemoryLimitBytes']:
        result['reasons'].append('Owned process tree and fixture memory exceeded the monitored limit')
    if actualProbe['oomKills'] != baseline['oomKills']:
        result['reasons'].append('Owned cgroup OOM evidence changed')
    if not result['reasons']:
        result.update(status='MEASUREMENT_ADMITTED', action='CONTINUE_OWNED_ATTEMPT')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('plan', 'validate', 'check'))
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--actual-probe', type=Path)
    parser.add_argument('--phase')
    args = parser.parse_args(argv)
    value = json.loads(args.input.read_text(encoding='utf-8'))
    if args.operation == 'plan':
        result = plan(value)
    elif args.operation == 'validate':
        result = validate(value)
    else:
        if not args.actual_probe or not args.phase:
            parser.error('check requires --actual-probe and --phase')
        result = check(value, json.loads(args.actual_probe.read_text(encoding='utf-8')), args.phase)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result['status'] in ('READY', 'PASS', 'PHASE_ADMITTED', 'MEASUREMENT_ADMITTED') else 2


if __name__ == '__main__':
    raise SystemExit(main())
