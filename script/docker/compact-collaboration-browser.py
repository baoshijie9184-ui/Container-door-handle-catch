"""Runtime-owned browser image and real UI acceptance; no host installation."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re

MIB = 1024 ** 2
MEMORY = 2 * 1024 ** 3
FILES = ('Dockerfile.collaboration-browser', 'collaboration-browser-runner.py',
         'collaboration-browser-proxy.py', 'collaboration-browser-requirements.txt',
         'collaboration-browser-sources.json')


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evidence_contract():
    spec = importlib.util.spec_from_file_location('owned_browser_evidence_bytes', Path(__file__).with_name('collaboration-browser-evidence.py'))
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def prepare_image(ctx):
    context = ctx.directory / 'browser-image'
    (context / 'script/docker').mkdir(parents=True, mode=0o700)
    catalog = {}
    for name in FILES:
        source = ctx.source / 'script/docker' / name
        require(source.is_file() and not source.is_symlink() and source.stat().st_size <= MIB,
                'Browser recipe must come from bounded fixed source')
        destination = context / ('Dockerfile' if name.startswith('Dockerfile') else 'script/docker/' + name)
        destination.write_bytes(source.read_bytes()); os.chmod(destination, 0o600)
        catalog[name] = sha(source)
    tag = 'doorhandlecatch/runtime-browser:' + ctx.args.tag + '-' + ctx.token
    proof = ctx.build_resources.runtime_image(ctx.root, ctx.source, ctx.args, ctx.identity,
                                              context, tag, 'browser', ctx.project)
    image = json.loads(ctx.ops.docker('image', 'inspect', tag))[0]
    require(re.fullmatch(r'sha256:[a-f0-9]{64}', image['Id'])
            and image['Os'] == 'linux' and image['Architecture'] == 'amd64'
            and image['Config'].get('Labels', {}).get('io.doorhandle.rehearsal') == ctx.project,
            'Browser image ownership/platform differs from its measured build')
    ctx.owner.update(browserImage=image['Id'], browserSourceHashes=catalog,
                     browserImageBytes=image['Size'], browserBuildResourceEvidence=proof)
    ctx.save()


def inspect(ctx, cid, image, network, inputs, evidence):
    row = json.loads(ctx.ops.docker('inspect', cid))[0]
    host, config = row['HostConfig'], row['Config']
    labels = config.get('Labels') or {}
    require(row['Id'] == cid and row['Image'] == image and config.get('User') == '1000:1000'
            and config.get('Hostname') == cid[:12]
            and labels.get('io.doorhandle.rehearsal') == ctx.project
            and labels.get('io.doorhandle.collaboration-browser') == ctx.token,
            'Browser container identity is not owned by this runtime')
    require(host['Memory'] == MEMORY and host['MemorySwap'] == MEMORY and host['NanoCpus'] == 2_000_000_000
            and host['PidsLimit'] == 512 and host['ShmSize'] == 256 * MIB and host['Init'] is True
            and host['ReadonlyRootfs'] is True and host['Privileged'] is False
            and host['RestartPolicy']['Name'] == 'no' and host.get('CapDrop') == ['ALL']
            and not host.get('CapAdd') and not host.get('Devices') and not host.get('Binds')
            and any(value in ('no-new-privileges', 'no-new-privileges=true') for value in host.get('SecurityOpt') or [])
            and host.get('PidMode', '') == '' and host.get('IpcMode') == 'private'
            and not host.get('PortBindings') and host['NetworkMode'] == network,
            'Browser execution exceeded its resource or namespace boundary')
    observed_mounts = row.get('Mounts', [])
    mounts = {(value['Type'], value.get('Source'), value['Destination'], value['RW'])
              for value in observed_mounts if value['Type'] == 'bind'}
    require(mounts == {('bind', str(inputs), '/run/doorhandle', False), ('bind', str(evidence), '/evidence', True)}
            and all(value['Type'] == 'bind' or value['Type'] == 'tmpfs' and value['Destination'] == '/tmp' for value in observed_mounts)
            and set(host.get('Tmpfs') or {}) == {'/tmp'}, 'Browser mounts escaped the exact owned inputs/evidence')
    networks = row['NetworkSettings']['Networks']
    require(set(networks) == {network}, 'Browser must use only the owned internal application network')
    net = json.loads(ctx.ops.docker('network', 'inspect', network))[0]
    require(net['Internal'] is True and net.get('Labels', {}).get('io.doorhandle.rehearsal') == ctx.project,
            'Browser application network is not isolated')
    return {'containerId': cid, 'imageId': image, 'networkId': net['Id'], 'executionUid': 1000,
            'memoryLimitBytes': MEMORY, 'cpuLimit': 2, 'pidsLimit': 512, 'shmBytes': 256 * MIB,
            'readOnlyRoot': True, 'ownedMountsVerified': True, 'internalNetworkVerified': True,
            'privileged': False, 'hostNamespaces': False, 'running': row['State']['Running'],
            'exitCode': row['State']['ExitCode'], 'oomKilled': row['State']['OOMKilled']}


def run(ctx):
    require(os.getuid() == 1000 and os.getgid() == 1000, 'Reuse the admitted non-root ECS execution identity')
    require(isinstance(getattr(ctx, 'report_task_id', None), str), 'Browser needs the actual worker-completed task')
    image = ctx.owner['browserImage']
    inputs, evidence = ctx.directory / 'browser-inputs', ctx.directory / 'browser-evidence'
    inputs.mkdir(mode=0o700); evidence.mkdir(mode=0o700)
    # The browser uses the existing non-root ECS UID; private inputs remain 0600.
    ctx.common.write_json(inputs / 'users.json', {'accounts': ctx.accounts})
    network = ctx.config['networks']['doorhandle-network']['name']
    descriptor = {'schemaVersion': 1, 'commit': ctx.args.commit, 'sourceSha256': ctx.args.source_sha256,
        'ownership': {'project': ctx.project, 'network': network, 'token': ctx.token}, 'upstream': 'http://ui:80',
        'runtime': {'browserImageId': image, 'browserContainerId': '', 'cpuLimit': 2,
                    'memoryLimitBytes': MEMORY, 'pidsLimit': 512},
        'fixtures': {'reportTaskId': ctx.report_task_id},
        'budgets': {'accounts': 20, 'tabsPerAccount': 2, 'p95MaxMs': 2000,
                    'minimumLatencySamples': 20, 'timeoutSeconds': 600}}
    # Build layers are retained in the measured baseline, not credited as free space.
    ctx.resources.admit('runtime-browser', 512 * MIB, {'browserImageId': image,
        'measuredRetainedImageBytes': ctx.owner['browserImageBytes'], 'evidenceBoundBytes': 128 * MIB,
        'containerWritableAndLogEnvelopeBytes': 384 * MIB}, MEMORY)
    ctx.owner['browserContainerName'] = ctx.project + '-collaboration-browser'; ctx.save()
    command = ['create', '--name', ctx.owner['browserContainerName'], '--pull', 'never', '--init',
        '--network', network, '--restart', 'no', '--user', '1000:1000', '--read-only',
        '--memory', str(MEMORY), '--memory-swap', str(MEMORY), '--cpus', '2', '--pids-limit', '512',
        '--shm-size', '256m', '--ipc', 'private', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--log-opt', 'max-size=5m', '--log-opt', 'max-file=1',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=536870912,uid=1000,gid=1000,mode=0700',
        '--label', 'io.doorhandle.rehearsal=' + ctx.project,
        '--label', 'io.doorhandle.collaboration-browser=' + ctx.token,
        '--mount', 'type=bind,src=' + str(inputs) + ',dst=/run/doorhandle,readonly',
        '--mount', 'type=bind,src=' + str(evidence) + ',dst=/evidence', image,
        '--descriptor', '/run/doorhandle/browser-descriptor.json', '--accounts', '/run/doorhandle/users.json', '--output', '/evidence']
    cid = ctx.ops.docker(*command).decode().strip()
    require(re.fullmatch(r'[a-f0-9]{64}', cid), 'Browser container ID is unavailable')
    ctx.owner['browserContainerId'] = cid; ctx.save()
    descriptor['runtime']['browserContainerId'] = cid
    ctx.common.write_json(inputs / 'browser-descriptor.json', descriptor)
    before = inspect(ctx, cid, image, network, inputs, evidence)
    ctx.ops.docker('start', cid, timeout=30)
    try:
        exit_code = ctx.ops.docker('wait', cid, timeout=660).decode().strip()
    finally:
        row = json.loads(ctx.ops.docker('inspect', cid))[0]
        if row['State']['Running']:
            ctx.ops.docker('stop', '--time', '15', cid, timeout=45)
    after = inspect(ctx, cid, image, network, inputs, evidence)
    public = evidence / 'browser-evidence.json'
    catalog = preserve(ctx)['files']
    ctx.owner['browserExternalObservation'] = {'before': before, 'after': after, 'files': catalog}; ctx.save()
    require(exit_code == '0' and after['exitCode'] == 0 and not after['running'] and not after['oomKilled'],
            'Real browser acceptance did not finish successfully; retain the owned failure evidence')
    result = json.loads(public.read_bytes())
    require(all(result.get(key) == descriptor[key] for key in ('schemaVersion', 'commit', 'sourceSha256'))
            and result.get('runtime') == descriptor['runtime'] and result.get('status') == 'PASS'
            and result.get('fullA01A28AcceptanceClaimed') is False
            and len(result.get('checks', {})) >= 18
            and all(row.get('status') == 'PASS' for row in result['checks'].values()),
            'Real browser source/identity/check evidence is incomplete')
    for name in ('collaboration-browser-runner.py', 'collaboration-browser-proxy.py', 'collaboration-browser-sources.json'):
        require(result.get('runnerSourceSha256', {}).get(name) == ctx.owner['browserSourceHashes'][name],
                'Actual browser runner source differs from the fixed build')
    proof = {'file': public.relative_to(ctx.attempt).as_posix(), 'sha256': sha(public),
             'externalContainerObservation': ctx.owner['browserExternalObservation'],
             'allA01A28Verified': False, 'requiredBrowserChecksPassed': len(result['checks'])}
    evidence_contract().validate_report(result, ctx.context(),
        {'browserImageId': image, 'browserContainerId': cid, 'files': catalog,
         'externalContainerObservation': ctx.owner['browserExternalObservation']}, proof, ctx.source)
    ctx.owner['browserAcceptance'] = proof; ctx.save()
    return proof


def preserve(ctx):
    """After creators stop, bind only bounded public JSON/PNGs, including failures."""
    evidence = ctx.directory / 'browser-evidence'
    if not evidence.exists(): return {'files': []}
    require(evidence.is_dir() and not evidence.is_symlink() and evidence.resolve() == evidence,
            'Browser evidence directory escaped its owned runtime')
    public = evidence / 'browser-evidence.json'
    catalog, rejected, total = [], 0, 0
    for path in sorted(evidence.rglob('*')):
        if path.is_symlink(): rejected += 1; continue
        if path.is_dir():
            if path != evidence / 'screenshots': rejected += 1; continue
            os.chmod(path, 0o700); continue
        stat = path.stat()
        if not (path.is_file() and stat.st_nlink == 1 and stat.st_uid == 1000 and 0 < stat.st_size <= 32 * MIB
                and evidence_contract().public_path(path.relative_to(ctx.attempt).as_posix())):
            rejected += 1; continue
        if len(catalog) == 128 or total + stat.st_size > 128 * MIB:
            rejected += 1; continue
        os.chmod(path, 0o600)
        total += stat.st_size
        catalog.append({'path': path.relative_to(ctx.attempt).as_posix(), 'bytes': stat.st_size, 'sha256': sha(path)})
    require(len(catalog) <= 128 and sum(row['bytes'] for row in catalog) <= 128 * MIB,
            'Browser evidence collection exceeded its retained bound')
    result = {**ctx.context(), 'project': ctx.project, 'status': 'EVIDENCE_PRESERVED', 'files': catalog,
              'rejectedArtifactCount': rejected,
              'browserContainerId': ctx.owner.get('browserContainerId'), 'browserImageId': ctx.owner.get('browserImage'),
              'externalContainerObservation': ctx.owner.get('browserExternalObservation')}
    evidence_contract().validate_manifest(result, ctx.context(), ctx.project)
    path = ctx.directory / 'browser-manifest.json'; ctx.common.write_json(path, result)
    ctx.owner['browserEvidence'] = {'file': path.relative_to(ctx.attempt).as_posix(), 'sha256': sha(path)}; ctx.save()
    require(rejected == 0, 'Unapproved browser artifacts remain private; approved original evidence was preserved')
    return result
