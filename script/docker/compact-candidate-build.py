#!/usr/bin/env python3
"""Stage fixed worker sources and bind ECS-built candidate images to CI artifacts.

Invoked under deploy.lock by deploy-remote build-only. It never starts an
application, mutates source datasets, or copies credentials to Jenkins.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('stage', 'capture'))
    for name in ('root', 'runtime', 'tag', 'source-sha256', 'settings', 'instance-id', 'machine-id', 'commit'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    source = Path(args.root) / 'releases' / args.tag
    common = module('candidate_common', source / 'script/docker/assignment-compat.py')
    schema = module('candidate_schema', source / 'script/docker/compact-schema-guard.py')
    cutover = module('candidate_cutover', source / 'script/docker/compact-cutover.py')
    ops = module('candidate_ops', source / 'script/docker/monolith-ops.py')
    require = common.require
    try:
        require(sys.platform == 'linux' and source.resolve(strict=True) == source, 'Canonical ECS candidate release required')
        identity = schema.ecs_identity({'instanceId': args.instance_id, 'machineId': args.machine_id})
        tag = cutover.TAG.fullmatch(args.tag)
        require(tag and re.fullmatch('[a-f0-9]{40}', args.commit) and args.commit.startswith(tag[2]), 'Fixed SCM build identity required')
        verification_sha = cutover.admitted_verification(args.root, args.tag, args.commit,
                                                        args.source_sha256, identity, schema)
        cutover.fixed_source(Path(args.root) / 'inbox' / args.tag / 'source.tar.gz', source, args.source_sha256, args.commit)
        settings_path = cutover.canonical(args.settings)
        settings, settings_sha = schema.read_private(settings_path)
        require(set(settings) == {'version', 'sourceOffsets', 'java'} and settings['version'] == 1,
                'Reviewed private ECS settings require only version, sourceOffsets and existing Java path')
        domains = {'workbench'}
        for file in (source / 'sql/mysql/compact/copy').glob('*.sql'):
            domains.update(name.lower() for name in re.findall(r'__SOURCE_([A-Z_]+)_OFFSET__', file.read_text(encoding='utf8')))
        require(isinstance(settings['sourceOffsets'], dict) and set(settings['sourceOffsets']) == domains
                and all(isinstance(value, str) and re.fullmatch(r'[+-](?:0\d|1[0-4]):[0-5]\d', value)
                        and (value[1:3] != '14' or value[4:] == '00') for value in settings['sourceOffsets'].values()),
                'Every migration domain needs its explicitly reviewed source time offset')
        java = cutover.canonical(settings['java'])
        require(os.access(java, os.X_OK), 'Existing Java executable is unavailable')
        work = source / 'work'; work.mkdir(mode=0o700, exist_ok=True)
        if args.phase == 'stage':
            context = work / 'compact-worker-build'
            context.mkdir(mode=0o700)
            old_context = cutover.canonical(Path(args.runtime) / 'work/cloud/pth-worker-build')
            # Large downloaded wheels/model sources stay on ECS. Hardlinks are
            # immutable inputs to Docker; the existing runtime files are untouched.
            for name in ('cpu-wheels', 'model-source'):
                original = cutover.canonical(old_context / name)
                require(original.is_dir(), 'Existing validated worker build inputs are missing')
                for current, folders, files in os.walk(original, followlinks=False):
                    require(not any((Path(current) / item).is_symlink() for item in folders + files),
                            'Worker dependency input contains an unpinned link')
                shutil.copytree(original, context / name, copy_function=os.link)
            copies = {'Dockerfile': source / 'deploy/worker/Dockerfile',
                      'requirements.txt': source / 'deploy/worker/requirements.txt',
                      'DINOv3-LICENSE.md': source / 'deploy/worker/licenses/DINOv3-LICENSE.md',
                      'PyMySQL-LICENSE.txt': source / 'deploy/worker/licenses/PyMySQL-LICENSE.txt',
                      'LICENSE': source / 'LICENSE'}
            for name in ('kafka_detection_worker.py', 'kafka_event_models.py', 'kafka_settings.py',
                         'detection_worker_receipts.py', 'oss_result_uploader.py', 'pth_detection_engine.py',
                         'detection_image.py', 'worker_health.py', 'tenant_detection_authority.py',
                         'tenant_execution_security.py'):
                copies[name] = source / name
            for name, original in copies.items():
                shutil.copyfile(original, context / name)
            provenance = cutover.canonical(old_context / 'BUILD_PROVENANCE.json')
            shutil.copyfile(provenance, context / 'BUILD_PROVENANCE.json')
            common.write_json(work / 'worker-build-source.json', {'commit': args.commit,
                'sourceSha256': args.source_sha256, 'settingsSha256': settings_sha,
                'upstreamProvenanceSha256': cutover.sha_file(provenance),
                'sourceFiles': {name: cutover.sha_file(original) for name, original in copies.items()}})
            # Runtime image pinning preserves infrastructure but the first compact
            # worker must be built from this fixed source, rather than the old image.
            runtime_file = source / 'runtime-images.yml'
            images = json.loads(runtime_file.read_text())
            images['services'].pop('detection-worker', None)
            common.write_json(runtime_file, images)
        else:
            pinned = json.loads((source / 'previous-images.yml').read_text())['services']
            images = {name: item['image'] for name, item in pinned.items()}
            for service, repository in (('backend', 'backend'), ('nginx', 'web'), ('mem0', 'mem0'),
                                        ('detection-worker', 'detection-worker')):
                result = json.loads(ops.docker('image', 'inspect', 'doorhandlecatch/' + repository + ':' + args.tag))
                require(len(result) == 1 and cutover.DIGEST.fullmatch(result[0]['Id']), 'Candidate build image is unavailable')
                images[service] = result[0]['Id']
            for service in ('backend', 'detection-worker'):
                schema.compact_image(images[service], common)
            # Extract, never execute, the exact migration jar embedded in the
            # immutable backend image that will be admitted for activation.
            name = 'doorhandle-candidate-artifact-' + uuid.uuid4().hex[:12]
            container = None
            jar = work / 'candidate-app.jar'
            try:
                container = ops.docker('create', '--name', name, '--network', 'none', '--read-only',
                                       '--label', 'io.doorhandle.candidate=' + args.tag,
                                       '--entrypoint', '/bin/true', images['backend']).decode().strip()
                require(re.fullmatch('[a-f0-9]{64}', container), 'Owned extraction container identity unavailable')
                ops.docker('cp', container + ':/app/app.jar', str(jar))
                os.chmod(jar, 0o600)
            finally:
                if container:
                    ops.docker('rm', container)
            value = {'version': 1, 'ecs': identity, 'gitCommit': args.commit, 'buildNumber': int(tag[1]),
                     'sourceOffsets': settings['sourceOffsets'], 'candidateImages': images,
                     'workbench': {'java': str(java), 'applicationJar': str(jar),
                                   'applicationJarSha256': cutover.sha_file(jar)}}
            input_file = work / 'private-cutover-input.json'
            common.write_json(input_file, value)
            runtime = {'services': {name: {**item, 'image': images[name]} for name, item in pinned.items()}}
            for name, image in images.items():
                runtime['services'].setdefault(name, {'image': image})
            runtime_file = work / 'candidate-runtime.json'
            common.write_json(runtime_file, runtime)
            receipt = {'schemaVersion': 1, 'kind': 'doorhandle-compact-candidate-build', 'status': 'BUILT',
                       'ecs': identity, 'release': args.tag, 'commit': args.commit,
                       'sourceSha256': args.source_sha256, 'settingsSha256': settings_sha,
                       'verificationReceiptSha256': verification_sha,
                       'inputSha256': cutover.sha_file(input_file), 'images': images,
                       'runtimeOverlaySha256': cutover.sha_file(runtime_file),
                       'applicationJarSha256': value['workbench']['applicationJarSha256'],
                       'workerSourceReceiptSha256': cutover.sha_file(work / 'worker-build-source.json')}
            common.write_json(source / 'candidate-build.json', receipt)
            print(json.dumps(receipt))
        return 0
    except BaseException:
        print('Candidate artifact build binding failed; no source writer was changed.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
