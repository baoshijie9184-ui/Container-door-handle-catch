#!/usr/bin/env python3
"""Stage fixed worker sources and bind ECS-built candidate images to CI artifacts.

Invoked under deploy.lock by deploy-remote build-only. It never starts an
application, mutates source datasets, or copies credentials to Jenkins.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import stat
import sys
import tarfile
import uuid


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


def runtime_dockerfile(body):
    """Retain the reviewed runtime stage; package the exact Jenkins jar without Maven."""
    stages = list(re.finditer(r'^FROM [^\r\n]+@sha256:[a-f0-9]{64} AS runtime\s*$', body, re.M))
    if len(stages) != 1:
        raise ValueError('The versioned backend must declare one pinned runtime stage')
    runtime = body[stages[0].start():]
    original = 'COPY --from=build --chown=app:app /out/app.jar /app/app.jar'
    if runtime.count(original) != 1 or len(re.findall(r'^FROM ', runtime, re.M)) != 1:
        raise ValueError('The runtime jar copy is not uniquely bound to the reviewed Dockerfile')
    return '# syntax=docker/dockerfile:1\n' + runtime.replace(original, 'COPY --chown=app:app app.jar /app/app.jar')


def stage_backend(source, work, jar, common, cutover):
    context = work / 'compact-backend-build'; context.mkdir(mode=0o700)
    original = source / 'deploy/backend/Dockerfile'
    body = runtime_dockerfile(original.read_text(encoding='utf8'))
    copies = {}
    for line in body.splitlines():
        if not line.startswith('COPY '):
            continue
        values = [item for item in shlex.split(line)[1:] if not item.startswith('--')]
        common.require(len(values) >= 2, 'A runtime COPY declaration is unsupported')
        for name in values[:-1]:
            common.require(name == 'app.jar' or re.fullmatch(r'[A-Za-z0-9_./-]+', name)
                           and '..' not in Path(name).parts and not Path(name).is_absolute(),
                           'A runtime COPY input is not a fixed source file')
            original_file = jar if name == 'app.jar' else cutover.canonical(source / name)
            common.require(original_file.is_file(), 'A runtime COPY input is missing')
            destination = context / name; destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(original_file, destination)
            # Runtime source scripts/docs retain readable image permissions;
            # their host context remains below an owner-only work directory.
            os.chmod(destination, 0o600 if name == 'app.jar' else 0o755 if original_file.stat().st_mode & 0o111 else 0o644)
            copies[name] = cutover.sha_file(destination)
    dockerfile = context / 'Dockerfile'; dockerfile.write_text(body, encoding='utf8'); os.chmod(dockerfile, 0o600)
    common.write_json(work / 'backend-build-source.json', {'sourceDockerfileSha256': cutover.sha_file(original),
        'runtimeDockerfileSha256': cutover.sha_file(dockerfile), 'contextFiles': copies,
        'applicationJarSha256': cutover.sha_file(jar)})
    return context


def dependency_versions(requirements):
    result = {}
    for line in requirements.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([A-Za-z0-9.+_-]+)', line.strip())
        if not match or match[1].lower() in result:
            raise ValueError('Worker dependencies must use unique exact versions')
        result[match[1].lower()] = match[2]
    return result


def frontend_inventory(path):
    files, size = 0, 0
    binding = hashlib.sha256()
    if path.resolve(strict=True) != path or not path.is_dir():
        raise ValueError('Frontend artifact must be a canonical directory')
    for current, directories, names in os.walk(path, followlinks=False):
        for name in sorted(directories + names):
            entry = Path(current) / name
            if entry.is_symlink():
                raise ValueError('Frontend artifact contains a link')
            if entry.is_file():
                length = entry.stat().st_size; files += 1; size += length
                checksum = hashlib.sha256()
                with entry.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''): checksum.update(block)
                binding.update(json.dumps([entry.relative_to(path).as_posix(), length, checksum.hexdigest()],
                    ensure_ascii=True, separators=(',', ':')).encode() + b'\n')
        directories.sort()
    return {'files': files, 'bytes': size, 'links': 0, 'sha256': binding.hexdigest()}


def stage_web(source, work, verification_file, verification_sha, common, cutover):
    verification_file = cutover.canonical(verification_file)
    common.require(cutover.sha_file(verification_file) == verification_sha, 'Passing frontend verification envelope changed')
    envelope = json.loads(verification_file.read_text())
    common.require(envelope.get('status') == 'PASS' and envelope.get('verificationExitCode') == 0
                   and envelope.get('release') == source.name, 'Frontend build lacks its passing same-build verification')
    checkout = cutover.canonical(verification_file.parent / 'checkout')
    result_file = cutover.canonical(checkout / 'work/ci-evidence/receipt.json')
    descriptors = [item for item in envelope['reportFiles'] if item['path'] == 'reports/receipt.json']
    common.require(len(descriptors) == 1 and descriptors[0]['bytes'] == result_file.stat().st_size
                   and descriptors[0]['sha256'] == cutover.sha_file(result_file), 'Executed frontend result receipt changed')
    result = json.loads(result_file.read_text())
    common.require(result.get('status') == 'PASS' and result.get('identity') == envelope.get('identity'),
                   'Frontend results belong to another execution or failed build')
    artifacts = {}
    for frontend in ('frontend', 'frontend-agent'):
        receipt = result.get('frontendResults', {}).get(frontend, {})
        dependencies = checkout / frontend / 'node_modules'
        common.require(all(receipt.get(key) == 0 for key in ('installExitCode', 'testExitCode', 'buildExitCode'))
                       and receipt.get('tests', {}).get('passed', 0) > 0
                       and receipt['tests'].get('failed') == receipt['tests'].get('skipped') == 0
                       and receipt.get('dependenciesCleanup', {}).get('status') == 'REMOVED'
                       and receipt['dependenciesCleanup'].get('relativePath') == frontend + '/node_modules'
                       and not dependencies.exists() and not dependencies.is_symlink(),
                       'Both frontends must have passed and removed only their own dependencies')
        distribution = cutover.canonical(checkout / frontend / 'dist')
        actual = frontend_inventory(distribution)
        common.require(actual == receipt.get('artifact') and actual['files'] > 0 and actual['bytes'] > 0
                       and (distribution / 'index.html').is_file(), 'The tested frontend artifact changed or is empty')
        artifacts[frontend] = actual
    # Preserve the pinned Nginx runtime, source template and healthcheck. Node
    # stages are omitted; this context contains only already-tested static files.
    original = source / 'deploy/nginx/Dockerfile'; original_body = original.read_text()
    stages = list(re.finditer(r'^FROM nginx:[^\r\n]+@sha256:[a-f0-9]{64}\s*$', original_body, re.M))
    common.require(len(stages) == 1, 'Nginx runtime must have one pinned final stage')
    body = original_body[stages[0].start():]
    substitutions = {
        'ARG NGINX_CONFIG=deploy/nginx/nginx.conf\n': '',
        'COPY ${NGINX_CONFIG} /etc/nginx/templates/default.conf.template': 'COPY nginx.conf /etc/nginx/templates/default.conf.template',
        'COPY --from=frontend-build /workspace/frontend/dist /usr/share/nginx/html': 'COPY frontend-dist/ /usr/share/nginx/html/',
        'COPY --from=agent-build /workspace/frontend-agent/dist /usr/share/nginx/html/agent-ui': 'COPY agent-dist/ /usr/share/nginx/html/agent-ui/'}
    for before, after in substitutions.items():
        common.require(body.count(before) == 1, 'Nginx artifact COPY/runtime declaration changed')
        body = body.replace(before, after)
    common.require(len(re.findall(r'^FROM ', body, re.M)) == 1 and 'node:' not in body and 'npm ' not in body,
                   'Candidate web must package the tested outputs without another Node build')
    context = work / 'compact-web-build'; context.mkdir(mode=0o700)
    for frontend, destination in (('frontend', 'frontend-dist'), ('frontend-agent', 'agent-dist')):
        shutil.copytree(checkout / frontend / 'dist', context / destination)
        common.require(frontend_inventory(context / destination) == artifacts[frontend], 'Frontend artifact changed during packaging')
    configuration = cutover.canonical(source / 'deploy/nginx/nginx.monolith.conf')
    shutil.copyfile(configuration, context / 'nginx.conf'); os.chmod(context / 'nginx.conf', 0o644)
    dockerfile = context / 'Dockerfile'; dockerfile.write_text(body, encoding='utf8'); os.chmod(dockerfile, 0o600)
    common.write_json(work / 'web-build-source.json', {'sourceDockerfileSha256': cutover.sha_file(original),
        'runtimeDockerfileSha256': cutover.sha_file(dockerfile), 'nginxConfigurationSha256': cutover.sha_file(configuration),
        'verificationReceiptSha256': verification_sha, 'testResultReceiptSha256': cutover.sha_file(result_file),
        'frontendArtifacts': artifacts})
    return context


WORKER_PYTHON_FILES = ('kafka_detection_worker.py', 'kafka_event_models.py', 'kafka_settings.py',
    'detection_worker_receipts.py', 'oss_result_uploader.py', 'pth_detection_engine.py',
    'detection_image.py', 'worker_health.py', 'tenant_detection_authority.py', 'tenant_execution_security.py',
    'runtime_telemetry.py')


def worker_source_files(source):
    return {'Dockerfile': source / 'deploy/worker/Dockerfile',
        'requirements.txt': source / 'deploy/worker/requirements.txt',
        'DINOv3-LICENSE.md': source / 'deploy/worker/licenses/DINOv3-LICENSE.md',
        'PyMySQL-LICENSE.txt': source / 'deploy/worker/licenses/PyMySQL-LICENSE.txt',
        'LICENSE': source / 'LICENSE', **{name: source / name for name in WORKER_PYTHON_FILES}}


def worker_runtime_dockerfile(body, image, *, add_pymysql, telemetry_pins=(), verify_versions=None):
    """One source overlay preserves the current runtime and optional no-deps fix."""
    supplement = ('RUN pip install --no-cache-dir --no-deps --index-url https://pypi.org/simple PyMySQL==1.1.2 && pip check\n'
                  if add_pymysql else '')
    if telemetry_pins:
        allowed = {'opentelemetry-api==1.45.2', 'opentelemetry-sdk==1.45.2',
                   'opentelemetry-exporter-otlp-proto-http==1.45.2', 'prometheus-client==0.26.0'}
        if not set(telemetry_pins) <= allowed or len(set(telemetry_pins)) != len(telemetry_pins) or not verify_versions:
            raise ValueError('Only the fixed telemetry additions may supplement the immutable Torch base')
        pins = list(telemetry_pins) + (['PyMySQL==1.1.2'] if add_pymysql else [])
        # Resolver constraints preserve every previously reviewed scientific pin.
        # New OTel transitive packages may resolve; the complete 19 direct pins
        # and pip dependency graph are checked inside this controlled build.
        expected = base64.b64encode(json.dumps(verify_versions, sort_keys=True).encode()).decode()
        check = "import base64,json,importlib.metadata as m; expected=json.loads(base64.b64decode('" + expected + "')); actual={x.metadata['Name'].lower().replace('_','-'):x.version for x in m.distributions()}; assert all(actual.get(k)==v for k,v in expected.items()); print(json.dumps({'verifiedDirectPins':expected},sort_keys=True))"
        supplement = ('RUN pip install --disable-pip-version-check --no-cache-dir --no-compile --timeout 120 --retries 0 '
            '--index-url https://pypi.org/simple --constraint /app/runtime-base-constraints.txt '
            '--report /app/worker-telemetry-install.json ' + ' '.join(pins) + ' && pip check && python -c "' + check + '"\n')
    install = ('RUN --mount=type=cache,target=/root/.cache/pip \\\n'
        '    --mount=type=bind,source=cpu-wheels,target=/wheels,ro \\\n'
        '    pip install --find-links /wheels --index-url "$PIP_INDEX_URL" -r requirements.txt && pip check \\\n'
        '    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app\n')
    replacements = {'ARG PYTHON_BASE_IMAGE=python:3.12-slim\n': '',
        'FROM ${PYTHON_BASE_IMAGE}\n': 'FROM ' + image + '\nUSER root\n',
        'ARG PIP_INDEX_URL=https://pypi.org/simple\n': '',
        'COPY requirements.txt /app/requirements.txt\n': ('COPY rootfs/ /\n' + supplement if telemetry_pins else supplement + 'COPY rootfs/ /\n'), install: '',
        'COPY ' + ' '.join(WORKER_PYTHON_FILES[:8]) + ' LICENSE /app/\n': '',
        'COPY ' + ' '.join(WORKER_PYTHON_FILES[8:]) + ' /app/\n': '',
        'COPY model-source/ /opt/model-source/\n': '',
        'COPY DINOv3-LICENSE.md BUILD_PROVENANCE.json /opt/model-source/\n': '',
        'COPY PyMySQL-LICENSE.txt /app/licenses/PyMySQL-LICENSE.txt\n': ''}
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', image) or type(add_pymysql) is not bool:
        raise ValueError('Worker reuse requires an immutable image and an explicit dependency decision')
    for before, after in replacements.items():
        if body.count(before) != 1:
            raise ValueError('Worker installation or complete fixed source closure changed')
        body = body.replace(before, after, 1)
    statements = [line.strip().split(None, 1) for line in re.sub(r'\\\n[ \t]*', ' ', body).splitlines()
                  if line.strip() and not line.lstrip().startswith('#')]
    instructions = [line[0].upper() for line in statements]
    if (set(instructions) - {'FROM', 'LABEL', 'WORKDIR', 'ENV', 'RUN', 'COPY', 'USER', 'HEALTHCHECK', 'CMD'}
            or instructions.count('COPY') != 1 or instructions.count('RUN') != int(add_pymysql or bool(telemetry_pins))
            or instructions.count('FROM') != 1
            or [line[1] for line in statements if line[0].upper() == 'USER'] != ['root', 'app']
            or [line[1] for line in statements if line[0].upper() == 'WORKDIR'] != ['/app']
            or len(re.findall(r'^LABEL io\.doorhandle\.business-schema=(?:"compact29-v1"|compact29-v1)\s*$', body, re.M)) != 1):
        raise ValueError('Worker reuse must retain the current compact app runtime with one source COPY')
    return body


def stage_worker_rootfs(source, context, old_context, common, cutover):
    rootfs = context / 'rootfs'
    for directory in (rootfs, rootfs / 'app', rootfs / 'app/licenses', rootfs / 'opt'):
        directory.mkdir(mode=0o755); os.chmod(directory, 0o755)
    model = cutover.canonical(old_context / 'model-source')
    common.require(model.is_dir(), 'Existing validated worker model sources are missing')
    model_entries = 0
    for current, directories, files in os.walk(model, followlinks=False):
        for path in (Path(current), *(Path(current) / name for name in directories + files)):
            info = path.lstat()
            common.require(not path.is_symlink() and (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)),
                           'Worker model source contains a link or special file')
            common.require(info.st_mode & (0o005 if stat.S_ISDIR(info.st_mode) else 0o004)
                           == (0o005 if stat.S_ISDIR(info.st_mode) else 0o004),
                           'Preserved worker model sources must remain readable by the image app user')
        model_entries += len(directories) + len(files)
    # Only the new directory entries are copied. Never chmod the linked model
    # files: their inodes still belong to the original retained source tree.
    shutil.copytree(model, rootfs / 'opt/model-source', copy_function=os.link)
    destinations = {name: 'app/' + name for name in (*WORKER_PYTHON_FILES, 'requirements.txt', 'LICENSE')}
    destinations.update({'DINOv3-LICENSE.md': 'opt/model-source/DINOv3-LICENSE.md',
        'BUILD_PROVENANCE.json': 'opt/model-source/BUILD_PROVENANCE.json',
        'PyMySQL-LICENSE.txt': 'app/licenses/PyMySQL-LICENSE.txt'})
    inputs = worker_source_files(source)
    inputs['BUILD_PROVENANCE.json'] = cutover.canonical(old_context / 'BUILD_PROVENANCE.json')
    for name, relative in destinations.items():
        original = cutover.canonical(inputs[name]); common.require(original.is_file(), 'Missing worker fixed source input')
        destination = rootfs / relative
        common.require(not destination.exists() or destination.is_file(), 'Worker overlay destination is not a regular file')
        temporary = destination.with_name('.' + destination.name + '-' + uuid.uuid4().hex)
        shutil.copyfile(original, temporary); os.chmod(temporary, 0o644)
        # A license/provenance file may already be linked from model-source.
        # Replace that owned directory entry, never write through the keeper.
        os.replace(temporary, destination)
    return {'sourceCopyInstructions': 1, 'runtimeSourceLayout': destinations,
        'modelSourceEntries': model_entries, 'modelSourceModePreservation': 'COMPLETE_HARDLINKED_TREE'}


def stage_worker_dependencies(source, context, old_context, args, ops, common, cutover):
    """Reuse proven immutable dependencies while replacing every runtime source."""
    previous = common.container(common.PROJECT, 'detection-worker')
    image = previous['Image']
    common.require(re.fullmatch(r'sha256:[a-f0-9]{64}', image), 'Worker base must be an immutable existing image')
    row = json.loads(ops.docker('image', 'inspect', image))[0]
    common.require(row['Id'] == image and not row['Config'].get('Volumes'), 'Unexpected worker base storage')
    code = """import importlib.metadata,json,hashlib
from pathlib import Path
versions={x.metadata['Name'].lower().replace('_','-'):x.version for x in importlib.metadata.distributions()}
print(json.dumps({'versions':versions,'requirements':Path('/app/requirements.txt').read_text(),
 'requirementsSha256':hashlib.sha256(Path('/app/requirements.txt').read_bytes()).hexdigest(),
 'provenanceSha256':hashlib.sha256(Path('/opt/model-source/BUILD_PROVENANCE.json').read_bytes()).hexdigest()}))
"""
    actual = json.loads(ops.docker('run', '--rm', '--network', 'none', '--read-only', '--pull', 'never',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--memory', '128m', '--memory-swap', '128m',
        '--label', 'io.doorhandle.candidate-build=' + args.tag, '--entrypoint', 'python', image,
        '-I', '-B', '-c', code, timeout=45))
    original = cutover.canonical(old_context / 'requirements.txt')
    provenance = cutover.canonical(old_context / 'BUILD_PROVENANCE.json')
    legacy_requirements_sha = cutover.sha_file(original)
    common.require(actual['provenanceSha256'] == cutover.sha_file(provenance),
                   'Immutable worker provenance differs from retained original build inputs')
    provenance_value = json.loads(provenance.read_text())
    common.require(set(provenance_value) == {'sourceZipSha256', 'verifiedSourceFiles', 'wheelSha256'}
                   and re.fullmatch(r'[a-f0-9]{64}', provenance_value['sourceZipSha256'])
                   and type(provenance_value['verifiedSourceFiles']) is int and provenance_value['verifiedSourceFiles'] > 0
                   and len(provenance_value['wheelSha256']) == 2, 'Original worker upstream provenance is incomplete')
    for name, expected in provenance_value['wheelSha256'].items():
        common.require(Path(name).name == name and name.endswith('.whl')
                       and cutover.sha_file(cutover.canonical(old_context / 'cpu-wheels' / name)) == expected,
                       'Retained CPU dependency wheel differs from its immutable upstream provenance')
    requirements = cutover.canonical(source / 'deploy/worker/requirements.txt')
    fixed_requirements_sha = cutover.sha_file(requirements)
    required = dependency_versions(requirements.read_text(encoding='utf8'))
    former = dependency_versions(actual['requirements'])
    common.require(actual['requirementsSha256'] == hashlib.sha256(actual['requirements'].encode('utf8')).hexdigest(),
                   'Worker installed requirements bytes differ from the dependency proof')
    normalize = lambda name: re.sub(r'[-_.]+', '-', name).lower()
    common.require(required.get('pymysql') == '1.1.2' and actual['versions'].get('pymysql') in (None, '1.1.2'),
                   'Only the reviewed no-deps PyMySQL supplement is permitted')
    telemetry = {'opentelemetry-api', 'opentelemetry-sdk', 'opentelemetry-exporter-otlp-proto-http', 'prometheus-client'}
    additions = telemetry | {'pymysql'}
    legacy = actual['requirementsSha256'] == legacy_requirements_sha \
        and set(required) - additions <= set(former) <= set(required) \
        and all(required.get(name) == version for name, version in former.items())
    current = actual['requirementsSha256'] == fixed_requirements_sha and former == required \
        and actual['versions'].get('pymysql') == '1.1.2'
    common.require((legacy or current)
                   and all(actual['versions'].get(normalize(name)) == version for name, version in former.items()),
                   'Existing worker dependencies cannot be safely reused for this candidate')
    closure_mode = 'LEGACY_UPSTREAM_WITH_OPTIONAL_PYMYSQL' if legacy else 'EXACT_FIXED_SOURCE_REQUIREMENTS'
    add_pymysql = legacy and actual['versions'].get('pymysql') is None
    telemetry_pins = tuple(name + '==' + required[name] for name in sorted(telemetry)
                           if actual['versions'].get(name) != required[name])
    if telemetry_pins: closure_mode = 'LEGACY_UPSTREAM_WITH_BOUNDED_TELEMETRY'
    body = worker_runtime_dockerfile((source / 'deploy/worker/Dockerfile').read_text(encoding='utf8'), image,
                                    add_pymysql=add_pymysql, telemetry_pins=telemetry_pins, verify_versions=required)
    overlay = stage_worker_rootfs(source, context, old_context, common, cutover)
    if telemetry_pins:
        constraints = context / 'rootfs/app/runtime-base-constraints.txt'
        constraints.write_text(''.join(name + '==' + version + '\n' for name, version in sorted(former.items())), encoding='utf8')
        os.chmod(constraints, 0o644)
    dockerfile = context / 'Dockerfile'; dockerfile.write_text(body, encoding='utf8'); os.chmod(dockerfile, 0o600)
    return {'mode': 'IMMUTABLE_DEPENDENCY_BASE_WITH_FIXED_SOURCE', 'baseImage': image,
        'baseImageBytes': row['Size'], 'originalRequirementsSha256': actual['requirementsSha256'],
        'originalProvenanceSha256': actual['provenanceSha256'], 'requiredVersions': required,
        'verifiedExistingVersions': {name: actual['versions'].get(normalize(name)) for name in required},
        'requirementsClosure': {'mode': closure_mode, 'baseRequirementsSha256': actual['requirementsSha256'],
            'legacyRequirementsSha256': legacy_requirements_sha, 'fixedSourceRequirementsSha256': fixed_requirements_sha},
        'addedNoDeps': ['PyMySQL==1.1.2'] if add_pymysql and not telemetry_pins else [],
        'addedDirectPins': [*telemetry_pins, *(['PyMySQL==1.1.2'] if add_pymysql else [])],
        'telemetrySupplementPins': list(telemetry_pins),
        'runtimeDependencyVerification': 'CONTROLLED_BUILD_PIP_CHECK_AND_ALL_DIRECT_PIN_READBACK' if telemetry_pins else 'PREEXISTING_ALL_DIRECT_PIN_READBACK',
        'runtimeDockerfileSha256': cutover.sha_file(dockerfile), **overlay}


MEM0_SOURCE_FILES = ('deploy/mem0/requirements.txt', 'memory_service/main.py',
    'memory_service/write_receipts.py', 'memory_service/lifecycle.py', 'memory_service/duplicate_review.py',
    'memory_service/model_config.py', 'memory_service/embedding_config.py', 'memory_service/qdrant_store.py',
    'runtime_telemetry.py', 'LICENSE')


def mem0_runtime_dockerfile(body, image):
    """Keep current runtime declarations, replacing only the proven installation."""
    base = re.findall(r'^FROM python:3\.12-slim@sha256:[a-f0-9]{64}\s*$', body, re.M)
    install = ('RUN --mount=type=cache,target=/root/.cache/pip \\\n'
        '    pip install --disable-pip-version-check --progress-bar off --timeout 120 --retries 5 \\\n'
        '      --index-url "$PIP_INDEX_URL" -r requirements.txt \\\n'
        '    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app \\\n'
        '    && mkdir /data && chown app:app /data\n')
    replacements = {
        'ARG PIP_INDEX_URL=https://pypi.org/simple\n': '',
        'COPY deploy/mem0/requirements.txt ./requirements.txt\n':
            'COPY --chmod=0644 ' + ' '.join(Path(name).name for name in MEM0_SOURCE_FILES) + ' /app/\n',
        install: '',
        'COPY --chmod=0644 ' + ' '.join(MEM0_SOURCE_FILES[1:-1]) + ' /app/\n': '',
        'COPY --chmod=0644 LICENSE /app/LICENSE\n': ''}
    if len(base) != 1 or not re.fullmatch(r'sha256:[a-f0-9]{64}', image):
        raise ValueError('Mem0 requires its reviewed Python runtime and an immutable dependency base')
    body = body.replace(base[0], 'FROM ' + image, 1)
    for before, after in replacements.items():
        if body.count(before) != 1:
            raise ValueError('Mem0 installation or fixed source closure changed')
        body = body.replace(before, after, 1)
    statements = [line.strip().split(None, 1) for line in re.sub(r'\\\n[ \t]*', ' ', body).splitlines()
                  if line.strip() and not line.lstrip().startswith('#')]
    instructions = [line[0].upper() for line in statements]
    if (set(instructions) - {'FROM', 'LABEL', 'WORKDIR', 'ENV', 'COPY', 'USER', 'EXPOSE', 'HEALTHCHECK', 'CMD'}
            or instructions.count('COPY') != 1 or instructions.count('FROM') != 1
            or [line[1] for line in statements if line[0].upper() == 'USER'] != ['app']
            or [line[1] for line in statements if line[0].upper() == 'WORKDIR'] != ['/app']):
        raise ValueError('Mem0 reuse must be source-only with the current app runtime')
    return body


def stage_mem0(source, work, args, ops, common, cutover):
    # A changed dependency closure needs an independently prepared, admitted base;
    # source-only reuse must never disguise an old Chroma-only image as Qdrant.
    explicit = getattr(args, 'mem0_dependency_image', None)
    tool_proof = None
    if explicit:
        image = explicit
    else:
        checkout = Path(args.root) / 'verification' / args.tag / 'checkout'
        tools = module('candidate_mem0_tool_base', checkout / 'script/jenkins/ecs-tool-runtime.py')
        tool_proof, tool_sha = tools.admit(Path(args.root) / 'inbox' / args.tag / 'tool-runtime/manifest.json',
            root=Path(args.root), tag=args.tag, commit=args.commit, source_sha=args.source_sha256,
            identity={'instanceId': args.instance_id, 'machineId': args.machine_id, 'executionLocation': 'ECS'}, source=checkout)
        image = tool_proof['images']['python']
    common.require(re.fullmatch(r'sha256:[a-f0-9]{64}', image), 'Mem0 base must be an immutable existing image')
    row = json.loads(ops.docker('image', 'inspect', image))[0]
    common.require(row['Id'] == image and not any(row['Config'].get(name) for name in ('Volumes', 'OnBuild'))
                   and (not row['Config'].get('Entrypoint') if explicit else row['Config'].get('Entrypoint') == ['/usr/local/bin/python']),
                   'Unexpected Mem0 dependency base storage or startup hooks')
    code = """import importlib.metadata,json,hashlib,os,pwd,subprocess,sys
from pathlib import Path
requirements=Path('/app/requirements.txt').read_bytes() if Path('/app/requirements.txt').is_file() else b''
versions={x.metadata['Name'].lower().replace('_','-'):x.version for x in importlib.metadata.distributions()}
check=subprocess.run([sys.executable,'-B','-m','pip','check'],capture_output=True,timeout=30)
data=Path('/data').stat() if Path('/data').is_dir() else None
try: app=pwd.getpwnam('app')
except KeyError: app=None
entries=list(Path('/app').iterdir()) if Path('/app').is_dir() else []
print(json.dumps({'versions':versions,'requirements':requirements.decode('utf8'),
 'requirementsSha256':hashlib.sha256(requirements).hexdigest(),'pipCheckReturnCode':check.returncode,
 'pythonVersion':list(sys.version_info[:2]),'uid':os.getuid(),'gid':os.getgid(),
 'dataUid':None if data is None else data.st_uid,'dataGid':None if data is None else data.st_gid,
 'appUid':None if app is None else app.pw_uid,'appGid':None if app is None else app.pw_gid,
 'sourceFiles':sorted(path.name for path in entries if path.suffix=='.py'),
 'appFiles':sorted(path.name for path in entries if path.is_file()),
 'sourceDirectories':sorted(path.name for path in entries if path.is_dir()),
 'sourceLinks':any(path.is_symlink() for path in entries)}))
"""
    actual = json.loads(ops.docker('run', '--rm', '--network', 'none', '--read-only', '--pull', 'never',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--pids-limit', '32',
        '--memory', '256m', '--memory-swap', '256m', '--label', 'io.doorhandle.candidate-build=' + args.tag,
        '--entrypoint', 'python', image, '-I', '-B', '-c', code, timeout=45))
    requirements = cutover.canonical(source / MEM0_SOURCE_FILES[0])
    required = dependency_versions(requirements.read_text(encoding='utf8'))
    former = dependency_versions(actual['requirements']) if explicit else required
    common.require(set(required) == {'mem0ai', 'chromadb', 'fastapi', 'uvicorn', 'python-dotenv', 'openai', 'pydantic', 'cryptography',
                       'qdrant-client', 'opentelemetry-api', 'opentelemetry-sdk',
                       'opentelemetry-exporter-otlp-proto-http', 'prometheus-client'}
                   and required == former and all(actual['versions'].get(name) == version for name, version in required.items())
                   and actual['requirementsSha256'] == hashlib.sha256(actual['requirements'].encode('utf8')).hexdigest(),
                   'Existing Mem0 dependencies cannot be safely reused for this candidate')
    common.require(type(actual['pipCheckReturnCode']) is int and actual['pipCheckReturnCode'] == 0
                   and actual['pythonVersion'] == [3, 12]
                   and (all(actual[name] == 10001 for name in ('uid', 'gid', 'dataUid', 'dataGid', 'appUid', 'appGid'))
                        if explicit else actual['uid'] == actual['gid'] == 1000 and actual['appUid'] is None),
                   'Existing Mem0 dependencies or app identity are incompatible')
    common.require(not actual['sourceLinks'] and not actual['sourceDirectories']
                   and set(actual['appFiles']) <= {Path(name).name for name in MEM0_SOURCE_FILES}
                   and set(actual['sourceFiles']) <= {Path(name).name for name in MEM0_SOURCE_FILES[1:-1]},
                   'Existing Mem0 base contains runtime Python outside the fixed replacement closure')
    original = source / 'deploy/mem0/Dockerfile'
    body = mem0_runtime_dockerfile(original.read_text(encoding='utf8'), image)
    if not explicit:
        common.require(not actual['appFiles'] and not actual['sourceDirectories'],
                       'The admitted tool dependency base must not contain replacement runtime source')
        body = body.replace('WORKDIR /app\n', 'USER root\nWORKDIR /app\n', 1)
        body = body.replace('USER app\n', 'USER app\nENV HOME=/home/app XDG_CACHE_HOME=/home/app/.cache\nENTRYPOINT []\n', 1)
        body = body.replace('COPY --chmod=0644 ',
            'RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app '
            '&& mkdir -p /data && chown app:app /data\nCOPY --chmod=0644 ', 1)
    context = work / 'compact-mem0-build'; context.mkdir(mode=0o700)
    files = {}
    for name in MEM0_SOURCE_FILES:
        original_file = cutover.canonical(source / name)
        common.require(original_file.is_file(), 'Missing Mem0 fixed source input')
        target = context / Path(name).name
        shutil.copyfile(original_file, target); os.chmod(target, 0o644); files[name] = cutover.sha_file(target)
    dockerfile = context / 'Dockerfile'; dockerfile.write_text(body, encoding='utf8'); os.chmod(dockerfile, 0o600)
    common.write_json(work / 'mem0-build-source.json', {'sourceDockerfileSha256': cutover.sha_file(original),
        'runtimeDockerfileSha256': cutover.sha_file(dockerfile), 'files': files,
        'dependencyReuse': {'mode': 'IMMUTABLE_DEPENDENCY_BASE_WITH_FIXED_SOURCE' if explicit else 'IMMUTABLE_TOOL_DEPENDENCY_BASE_WITH_APP_IDENTITY_AND_FIXED_SOURCE',
            'toolManifestSha256': None if explicit else tool_sha, 'appIdentityRunInstructions': 0 if explicit else 1,
            'baseImage': image,
            'baseImageBytes': row['Size'], 'originalRequirementsSha256': actual['requirementsSha256'],
            'requiredVersions': required, 'verifiedExistingVersions': {name: actual['versions'][name] for name in required},
            'pipCheckReturnCode': 0, 'addedDependencies': [], 'replacedBaseSourceFiles': actual['sourceFiles'],
            'sourceCopyInstructions': 1}})
    return context


def main(argv=None, actor=None, controlled_build=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('stage', 'capture', 'build'))
    for name in ('root', 'runtime', 'tag', 'source-sha256', 'settings', 'instance-id', 'machine-id', 'commit'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
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
        settings_fields = {'version', 'sourceOffsets', 'java', 'sourceMysqlContainerId', 'sourceSchema'}
        require(settings_fields <= set(settings) <= settings_fields | {'legacyClockPolicy', 'mem0DependencyImage', 'qdrantImage'} and settings['version'] == 1
                and ('qdrantImage' not in settings or re.fullmatch(r'sha256:[a-f0-9]{64}', settings['qdrantImage']))
                and ('mem0DependencyImage' not in settings or re.fullmatch(r'sha256:[a-f0-9]{64}', settings['mem0DependencyImage']))
                and re.fullmatch(r'[a-f0-9]{64}', settings.get('sourceMysqlContainerId', ''))
                and re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,63}', settings.get('sourceSchema', '')),
                'Reviewed private ECS settings require the exact source MySQL/schema, domain offsets and existing Java path')
        args.mem0_dependency_image = settings.get('mem0DependencyImage')
        vector_admission = module('candidate_vector_image_admission', source / 'script/jenkins/prepare-legacy-candidate.py')
        qdrant_image = vector_admission.admit_target_image(args.root, args.tag, args.commit, args.source_sha256, identity, settings)
        original_mysql = common.container(common.PROJECT, 'mysql')
        require(original_mysql['Id'] == settings['sourceMysqlContainerId'] and original_mysql['State']['Running']
                and common.db(original_mysql, 'SELECT DATABASE();') == settings['sourceSchema'],
                'The reviewed source server/database differs from the actual existing deployment')
        domains = {'workbench'}
        for file in (source / 'sql/mysql/compact/copy').glob('*.sql'):
            domains.update(name.lower() for name in re.findall(r'__SOURCE_([A-Z_]+)_OFFSET__', file.read_text(encoding='utf8')))
        clocks = module('candidate_clock_policy', source / 'script/schema/compact_clock_policy.py')
        clocks.validate(settings['sourceOffsets'], settings.get('legacyClockPolicy'), expected_domains=domains)
        java_registration = {}
        fixture_tools = module('candidate_fixture_tool_admission', source / 'script/jenkins/prepare-compact-fixtures.py')
        inbox = Path(args.root) / 'inbox' / args.tag
        java = fixture_tools.fixture_java_executable(settings['java'], root=Path(args.root), inbox=inbox,
            archive=inbox / 'source.tar.gz', tag=args.tag, commit=args.commit, source_sha=args.source_sha256,
            identity=identity, registration=java_registration)
        require(os.access(java, os.X_OK), 'Existing Java executable is unavailable')
        work = source / 'work'; work.mkdir(mode=0o700, exist_ok=True)
        inbox = Path(args.root) / 'inbox' / args.tag
        artifact, artifact_sha = schema.read_private(inbox / 'build-artifacts.json')
        jar_input = cutover.canonical(inbox / 'application.jar')
        require(all(artifact.get(key) == value for key, value in {
            'schema': 1, 'kind': 'doorhandle-compact-fixture-artifacts', 'release': args.tag,
            'commit': args.commit, 'sourceSha256': args.source_sha256}.items())
            and type(artifact.get('applicationJarBytes')) is int and 0 < artifact['applicationJarBytes'] <= 512 * 1024 * 1024
            and jar_input.stat().st_size == artifact['applicationJarBytes']
            and cutover.sha_file(jar_input) == artifact.get('applicationJarSha256'),
            'Candidate must package the exact fixed-commit Jenkins application jar')
        if args.phase == 'build':
            resources = module('candidate_build_resources', source / 'script/docker/compact-build-resources.py')
            require(actor is not None and actor.directory == work / 'candidate-build-resources',
                    'Candidate build must enter through the owned source-extraction controller')
            with tarfile.open(inbox / 'source.tar.gz', 'r:gz') as package:
                members = package.getmembers(); source_bytes = sum(item.size for item in members if item.isfile())
            checkout = Path(args.root) / 'verification' / args.tag / 'checkout'
            frontends = {name: frontend_inventory(checkout / name / 'dist') for name in ('frontend', 'frontend-agent')}
            old_context = cutover.canonical(Path(args.runtime) / 'work/cloud/pth-worker-build/model-source')
            links = 0
            for current, directories, files in os.walk(old_context, followlinks=False):
                require(not any((Path(current) / name).is_symlink() for name in directories + files), 'Linked worker source is not closed')
                links += len(directories) + len(files)
            growth = artifact['applicationJarBytes'] + source_bytes + sum(item['bytes'] for item in frontends.values()) + (links + len(members)) * 4096 + 64 * resources.MIB
            actor.begin('stage-contexts', growth, {'applicationJarBytes': artifact['applicationJarBytes'], 'sourceBytes': source_bytes,
                'sourceMembers': len(members), 'frontendArtifacts': frontends, 'hardlinkedDependencyEntries': links}, 512 * resources.MIB)
        if args.phase in ('stage', 'build'):
            backend_context = stage_backend(source, work, jar_input, common, cutover)
            web_context = stage_web(source, work, Path(args.root) / 'verification' / args.tag / 'verification-receipt.json',
                                    verification_sha, common, cutover)
            context = work / 'compact-worker-build'
            context.mkdir(mode=0o700)
            old_context = cutover.canonical(Path(args.runtime) / 'work/cloud/pth-worker-build')
            copies = worker_source_files(source)
            provenance = cutover.canonical(old_context / 'BUILD_PROVENANCE.json')
            dependencies = stage_worker_dependencies(source, context, old_context, args, ops, common, cutover)
            mem0_context = stage_mem0(source, work, args, ops, common, cutover)
            common.write_json(work / 'worker-build-source.json', {'commit': args.commit,
                'sourceSha256': args.source_sha256, 'settingsSha256': settings_sha,
                'upstreamProvenanceSha256': cutover.sha_file(provenance),
                'dependencyReuse': dependencies,
                'sourceFiles': {name: cutover.sha_file(original) for name, original in copies.items()}})
            # Runtime image pinning preserves infrastructure but the first compact
            # worker must be built from this fixed source, rather than the old image.
            runtime_file = source / 'runtime-images.yml'
            images = json.loads(runtime_file.read_text())
            images['services'].pop('chroma', None)
            images['services']['qdrant'] = {'image': qdrant_image}
            images['services'].pop('detection-worker', None)
            images['services']['backend'] = {'build': {'context': str(backend_context), 'dockerfile': 'Dockerfile'}}
            images['services']['nginx'] = {'build': {'context': str(web_context), 'dockerfile': 'Dockerfile'}}
            images['services']['mem0'] = {'build': {'context': str(mem0_context), 'dockerfile': 'Dockerfile'}}
            common.write_json(runtime_file, images)
            if args.phase == 'build':
                require(re.search(r'^\s+PIP_INDEX_URL: https://mirrors\.aliyun\.com/pypi/simple\s*$', (source / 'compose.cloud.yml').read_text(), re.M),
                        'Reviewed cloud pip build index changed')
                specifications = [
                    {'service': 'backend', 'context': backend_context, 'tag': 'doorhandlecatch/backend:' + args.tag, 'runWriteEnvelopeBytes': 512 * resources.MIB},
                    {'service': 'nginx', 'context': web_context, 'tag': 'doorhandlecatch/web:' + args.tag},
                    {'service': 'mem0', 'context': mem0_context, 'tag': 'doorhandlecatch/mem0:' + args.tag,
                     'runWriteEnvelopeBytes': 0 if args.mem0_dependency_image else 8 * resources.MIB},
                    {'service': 'detection-worker', 'context': context, 'tag': 'doorhandlecatch/detection-worker:' + args.tag,
                     'runWriteEnvelopeBytes': 512 * resources.MIB if dependencies['telemetrySupplementPins']
                                              else 64 * resources.MIB if dependencies['addedNoDeps'] else 0}]
                controlled_build = resources.build_images(actor, Path(args.root), source, specifications)
                actor.stop_owned()
                actor.begin('candidate-jar-readback', artifact['applicationJarBytes'] + 16 * resources.MIB,
                            {'applicationJarBytes': artifact['applicationJarBytes'], 'images': {key: item['imageId'] for key, item in controlled_build['images'].items()}}, 128 * resources.MIB)
                capture = ['capture', *[value for name in ('root', 'runtime', 'tag', 'source_sha256', 'settings', 'instance_id', 'machine_id', 'commit')
                    for value in ('--' + name.replace('_', '-'), getattr(args, name))]]
                if main(capture, actor=actor, controlled_build=controlled_build) != 0:
                    raise ValueError('Controlled candidate capture failed')
        else:
            require(actor is not None and controlled_build is not None, 'Candidate capture requires this invocation owned resource controller')
            pinned = json.loads((source / 'previous-images.yml').read_text())['services']
            images = {name: item['image'] for name, item in pinned.items()}
            images.pop('chroma', None)
            images['qdrant'] = qdrant_image
            images['qdrant-storage-init'] = qdrant_image
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
            require(cutover.sha_file(jar) == artifact['applicationJarSha256']
                    and jar.stat().st_size == artifact['applicationJarBytes'],
                    'The actual backend image does not contain the tested Jenkins jar')
            value = {'version': 1, 'ecs': identity, 'gitCommit': args.commit, 'buildNumber': int(tag[1]),
                     'sourceOffsets': settings['sourceOffsets'], 'candidateImages': images,
                     'workbench': {'java': str(java), 'applicationJar': str(jar),
                                   'applicationJarSha256': cutover.sha_file(jar)}}
            if settings.get('legacyClockPolicy') is not None:
                value['legacyClockPolicy'] = settings['legacyClockPolicy']
            input_file = work / 'private-cutover-input.json'
            common.write_json(input_file, value)
            runtime = {'services': {name: {**item, 'image': images[name]} for name, item in pinned.items() if name in images}}
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
                       'applicationJarBytes': artifact['applicationJarBytes'], 'buildArtifactPlanSha256': artifact_sha,
                       'backendSourceReceiptSha256': cutover.sha_file(work / 'backend-build-source.json'),
                       'webSourceReceiptSha256': cutover.sha_file(work / 'web-build-source.json'),
                       'frontendArtifacts': schema.read_private(work / 'web-build-source.json')[0]['frontendArtifacts'],
                       'workerSourceReceiptSha256': cutover.sha_file(work / 'worker-build-source.json')}
            receipt['mem0SourceReceiptSha256'] = cutover.sha_file(work / 'mem0-build-source.json')
            evidence = actor.finish('PASS', build=controlled_build,
                applicationJar={'sha256': artifact['applicationJarSha256'], 'bytes': artifact['applicationJarBytes']})
            resources = module('candidate_resource_validation', source / 'script/docker/compact-build-resources.py')
            receipt['buildResourceEvidence'] = resources.validate_files(work / 'candidate-build-resources',
                {'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256, 'identity': identity})
            require(receipt['buildResourceEvidence']['sha256'] == evidence['sha256'], 'Candidate resource finalization changed')
            resources.validate_candidate(receipt, source, {'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256, 'identity': identity})
            common.write_json(source / 'candidate-build.json', receipt)
            if java_registration:
                java_registration['runtime'].admit_release(java_registration['value'], source / 'candidate-build.json')
            print(json.dumps(receipt))
        return 0
    except BaseException:
        if actor is not None and not (actor.directory / 'resource-summary.json').exists():
            try: actor.finish('FAILED')
            except BaseException: pass
        print('Candidate artifact build binding failed; no source writer was changed.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
