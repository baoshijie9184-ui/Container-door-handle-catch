"""Validate collected runtime resource bytes; never execute tests or containers."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import stat


PREFIX = 'checkout/work/runtime-acceptance/'
MIB = 1024 ** 2


def require(value, message):
    if not value:
        raise ValueError(message)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate resource evidence field')
        result[key] = value
    return result


def raw_file(path, maximum):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path and not path.is_symlink(),
            'Evidence must be an existing canonical regular file')
    metadata = path.stat()
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1 and 0 < metadata.st_size <= maximum,
            'Resource evidence file is absent, linked or oversized')
    raw = path.read_bytes()
    require(len(raw) == metadata.st_size, 'Resource evidence changed during reading')
    return raw, hashlib.sha256(raw).hexdigest()


def json_file(path):
    raw, digest = raw_file(path, 256 * 1024)
    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid JSON number')))
    require(isinstance(value, dict), 'Resource evidence must be an object')
    return value, digest


def validate_files(proof_file, cleanup_file, summary_file, probes_file, phase_directory):
    proof, _ = json_file(proof_file)
    scope = {'profile': 'bounded-single-ecs-v1', 'productionPerformanceVerified': False,
             'productionCapacityVerified': False, 'allMandatoryScenariosRequired': True}
    require(proof.get('loadScope') == scope
            and all(type(proof['loadScope'].get(key)) is bool for key in scope if key != 'profile')
            and proof.get('status') == 'PASS',
            'Runtime proof must describe the actual bounded acceptance scope')
    reference = proof.get('resourceEvidence')
    require(isinstance(reference, dict) and set(reference) == {'file', 'sha256'}
            and reference['file'] == PREFIX + 'resource-summary.json'
            and re.fullmatch(r'[a-f0-9]{64}', reference.get('sha256', '')),
            'Runtime resource reference is malformed or foreign')
    summary, summary_sha = json_file(summary_file)
    cleanup, _ = json_file(cleanup_file)
    require(summary_sha == reference['sha256'] and cleanup.get('resourceEvidence') == reference
            and cleanup.get('status') == 'STOPPED', 'Runtime cleanup and resource evidence are not bound together')
    context_keys = ('schemaVersion', 'kind', 'release', 'commit', 'sourceSha256', 'identity',
                    'acceptanceProfileSha256', 'candidateBuildSha256')
    context = {key: proof[key] for key in context_keys}
    require(all(cleanup.get(key) == value for key, value in context.items())
            and cleanup.get('project') == proof.get('project'), 'Resource cleanup belongs to another runtime')
    raw, raw_sha = raw_file(probes_file, 64 * MIB)
    runtime_file = Path(__file__).resolve().parents[1] / 'docker/compact-runtime-acceptance.py'
    spec = importlib.util.spec_from_file_location('runtime_resource_byte_contract', runtime_file)
    runtime = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)
    result = runtime.validate_resource_evidence(summary, raw, context, proof['project'])
    phases = summary['phases']
    require(len(phases) == (4 if proof.get('browserAcceptance') else 3), 'All measured runtime phases must be retained')
    for index, reference in enumerate(phases, 1):
        name = 'resource-phase-' + str(index) + '-' + reference['phase'] + '.json'
        require(reference['file'] == PREFIX + name, 'Runtime phase escaped its fixed evidence location')
        value, digest = json_file(Path(phase_directory) / name)
        require(digest == reference['sha256'] and value == summary['phasePlans'][reference['phase']],
                'Original runtime phase evidence differs from its bound measured plan')
    return {**result, 'resourceSummarySha256': summary_sha, 'rawProbeSha256': raw_sha}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('proof', 'cleanup', 'summary', 'probes', 'phase-directory'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    result = validate_files(args.proof, args.cleanup, args.summary, args.probes, args.phase_directory)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
