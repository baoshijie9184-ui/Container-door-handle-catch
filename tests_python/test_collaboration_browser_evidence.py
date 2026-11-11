"""ECS-only source counterexamples. Synthetic bytes never count as browser acceptance."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from tests_python.browser_evidence_fixture import browser, install, write, report_value, observation, CID, IMAGE, ROOT

spec = importlib.util.spec_from_file_location('browser_adapter_contract', ROOT / 'script/docker/compact-collaboration-browser.py')
adapter = importlib.util.module_from_spec(spec); spec.loader.exec_module(adapter)


def fixture(tmp_path):
    context = {'schemaVersion': 1, 'kind': 'doorhandle-compact-runtime-acceptance', 'release': 'ci-101-'+'a'*12,
        'commit': 'a'*40, 'sourceSha256': 'b'*64, 'identity': {'instanceId': 'i-test', 'machineId': 'c'*32},
        'acceptanceProfileSha256': 'd'*64, 'candidateBuildSha256': 'e'*64}
    project = 'doorhandle-rehearsal-'+'f'*12
    proof, cleanup = {**context, 'project': project, 'status': 'PASS'}, {**context, 'project': project, 'status': 'STOPPED'}
    manifest, report = install(tmp_path, context, project, proof, cleanup)
    return SimpleNamespace(directory=tmp_path, context=context, project=project, proof=proof, cleanup=cleanup, manifest=manifest, report=report)


def resign(value):
    path = value.directory / 'browser-evidence/browser-evidence.json'
    digest = write(path, value.report)
    row = next(row for row in value.manifest['files'] if row['path'] == browser.REPORT)
    row.update(bytes=path.stat().st_size, sha256=digest)
    value.proof['browserAcceptance']['sha256'] = digest
    value.cleanup['browserEvidence']['sha256'] = write(value.directory / 'browser-manifest.json', value.manifest)


def verify(value, success=True):
    return browser.validate_files(value.directory, value.cleanup, value.proof if success else None, ROOT)


def test_actual_original_report_pngs_and_external_identity_pass_byte_validation(tmp_path):
    value = fixture(tmp_path)
    result = verify(value)
    assert result['status'] == 'VERIFIED' and result['checks'] == 19 and result['functionalAccounts'] == 4 and result['tabs'] == 8 and result['p95Ms'] == 100
    assert verify(value, False)['status'] == 'PRESERVED'


@pytest.mark.parametrize('damage', ['missing-stream', 'same-run', 'same-session', 'same-reply', 'no-content', 'finished-before-save',
    'negative-save-duration', 'same-connection', 'sse-reused', 'bad-cas', 'two-audits', 'gated-response', 'provider-unconsumed',
    'provider-unfinished', 'provider-delay', 'persisted-owner', 'persisted-run', 'persisted-session', 'persisted-message',
    'persisted-model', 'duplicate-marker', 'assistant-count', 'execution-link', 'content-hash'])
def test_nineteenth_check_requires_live_stream_saves_final_provider_and_real_message_persistence(tmp_path, damage):
    value = fixture(tmp_path); actual = value.report['checks']['model-stream-save-connection-budget']
    isolation = value.proof['modelIsolation']; persisted = isolation['modelStreamPersistence']
    if damage == 'missing-stream': actual['actualAgentStreams'].pop()
    elif damage.startswith('same-') and damage != 'same-connection':
        key = {'same-run': 'runId', 'same-session': 'sessionId', 'same-reply': 'messageId'}[damage]
        actual['actualAgentStreams'][1][key] = actual['actualAgentStreams'][0][key]
    elif damage == 'no-content': actual['actualAgentStreams'][0]['firstContent'] = False
    elif damage == 'finished-before-save': actual['actualAgentStreams'][0]['finishedEventAt'] = actual['ordinarySaves'][0]['saveResponseAt']
    elif damage == 'negative-save-duration': actual['ordinarySaves'][0]['saveMs'] = -1
    elif damage == 'same-connection': actual['ordinarySaves'][0]['actualConnectionId'] = actual['actualModelConnections'][0]['connectionId']
    elif damage == 'sse-reused': actual['actualSharedSseConnectionId'] = actual['actualModelConnections'][1]['connectionId']
    elif damage == 'bad-cas': actual['ordinarySaves'][1]['version'] = '7'
    elif damage == 'two-audits': actual['ordinarySaves'][0]['successfulAuditCount'] = 2
    elif damage == 'gated-response': actual['responseGatesUsed'] = True
    elif damage in ('provider-unconsumed', 'provider-unfinished', 'provider-delay'):
        key, number = {'provider-unconsumed': ('remainingSteps', 1), 'provider-unfinished': ('streamFinishes', 0), 'provider-delay': ('streamDelayMillisObserved', 14999)}[damage]
        isolation['fixtureState']['markers'][0][key] = number
    elif damage == 'assistant-count': persisted['streams'][0]['assistantRowsForRun'] = 2
    elif damage == 'execution-link': persisted['streams'][0]['executionEvidenceMatched'] = False
    elif damage == 'content-hash': persisted['streams'][0]['contentSha256'] = 'not-a-digest'
    elif damage == 'duplicate-marker': persisted['streams'][1]['marker'] = persisted['streams'][0]['marker']
    else:
        key = {'persisted-owner': 'ownerUserId', 'persisted-run': 'runId', 'persisted-session': 'sessionId',
               'persisted-message': 'messageId', 'persisted-model': 'modelId'}[damage]
        persisted['streams'][0][key] = 'different-actual-value'
    resign(value)
    with pytest.raises(ValueError): verify(value)


@pytest.mark.parametrize('damage', ['missing-check', 'failed-check', 'source-hash', 'commit', 'source', 'full-claim',
    'reused-id', 'missing-account', 'image', 'container', 'external-uid', 'external-network', 'external-running',
    'external-privileged', 'external-limit', 'p95-summary', 'raw-time', 'one-account', 'hidden-dom', 'duplicate-sample',
    'version', 'tool-version', 'no-resources', 'oom', 'pid-pressure', 'secret-artifacts',
    'wrong-role', 'extra-account', 'load-claimed', 'slo-claimed', 'missing-tab', 'missing-watcher',
    'missing-mutation-round', 'restore-missing', 'old-cookie-revived', 'shared-cookie-context'])
def test_passing_envelope_cannot_replace_independently_valid_actual_browser_facts(tmp_path, damage):
    value = fixture(tmp_path); report = value.report
    if damage == 'missing-check': report['checks'].pop('real-history-diff')
    if damage == 'failed-check': report['checks']['real-history-diff']['status'] = 'NOT_EXECUTED'
    if damage == 'source-hash': report['runnerSourceSha256']['collaboration-browser-runner.py'] = '0'*64
    if damage == 'commit': report['commit'] = '0'*40
    if damage == 'source': report['sourceSha256'] = '0'*64
    if damage == 'full-claim': report['fullA01A28AcceptanceClaimed'] = True
    if damage == 'reused-id': report['accounts']['peer']['userId'] = report['accounts']['inspector']['userId']
    if damage == 'missing-account': report['accounts'].pop('reviewer')
    if damage == 'wrong-role': report['accounts']['inspector']['role'] = 'SUPERVISOR'
    if damage == 'extra-account': report['accounts']['load_01'] = {'userId': '999', 'role': 'INSPECTOR'}
    if damage == 'load-claimed': report['loadTestStatus'] = 'PASS'
    if damage == 'slo-claimed': report['performanceSloVerified'] = True
    if damage == 'missing-tab': report['checks']['four-accounts-multi-tab']['actualTabs'] = 7
    if damage == 'missing-watcher': report['checks']['four-accounts-multi-tab']['visibleWatcherAccountsPerRound'] = 2
    if damage == 'missing-mutation-round': report['checks']['four-accounts-multi-tab']['actualMutationRounds'] = 1
    if damage == 'restore-missing': report['checks']['account-disable-revocation']['actualUiRestore'] = False
    if damage == 'old-cookie-revived': report['checks']['account-disable-revocation']['restoredOldCookieHttpStatus'] = 200
    if damage == 'shared-cookie-context': report['checks']['four-roles-real-ui']['independentCookieContexts'] = False
    if damage == 'image': report['runtime']['browserImageId'] = 'sha256:'+'0'*64
    if damage == 'container': report['runtime']['browserContainerId'] = '0'*64
    if damage.startswith('external-'):
        key, changed = {'external-uid': ('executionUid', 0), 'external-network': ('networkId', 'not-owned'),
            'external-running': ('running', True), 'external-privileged': ('privileged', True),
            'external-limit': ('memoryLimitBytes', browser.MEMORY*2)}[damage]
        value.manifest['externalContainerObservation']['after'][key] = changed
    if damage == 'p95-summary': report['latency']['p95Ms'] = 1
    if damage == 'raw-time': report['latencySamples'][0]['domAtEpochMs'] += 5000
    if damage == 'one-account':
        for sample in report['latencySamples']: sample['account'] = 'inspector'
    if damage == 'hidden-dom': report['latencySamples'][0]['visibility'] = 'hidden'
    if damage == 'duplicate-sample': report['latencySamples'][0] = copy.deepcopy(report['latencySamples'][1])
    if damage == 'version': report['latencySamples'][0]['resourceVersion'] = '01'
    if damage == 'tool-version': report['tool']['actualChromium'] = '1.0'
    if damage == 'no-resources': report['resourceSamples'] = []
    if damage == 'oom': report['resourceSamples'][0]['memory.events'] = 'oom 1\noom_kill 1\n'
    if damage == 'pid-pressure': report['resourceSamples'][0]['pids.events'] = 'max 1\n'
    if damage == 'secret-artifacts': report['checks']['artifact-secret-boundary']['cookiesTokensStorageStateHarTraceVideoWritten'] = True
    resign(value)
    with pytest.raises(ValueError): verify(value)


def test_slow_truthful_observation_does_not_claim_or_gate_deferred_performance_slo(tmp_path):
    value = fixture(tmp_path)
    for sample in value.report['latencySamples']:
        sample['domAtEpochMs'] += 2001; sample['eventOccurredToDomMs'] += 2001
    value.report['latency']['p95Ms'] = value.report['checks']['latency-observation']['p95Ms'] = 2101
    resign(value)
    result = verify(value)
    assert result['p95Ms'] == 2101 and result['performanceSloVerified'] is False
    assert result['loadTestStatus'] == 'DEFERRED_BY_USER'


def test_actual_save_during_both_live_streams_is_not_subject_to_deferred_two_second_slo(tmp_path):
    value = fixture(tmp_path)
    for row in value.report['checks']['model-stream-save-connection-budget']['ordinarySaves']:
        row['saveMs'] = 3000
        row['saveResponseAt'] += 3000
    resign(value)
    assert verify(value)['performanceSloVerified'] is False


@pytest.mark.parametrize('path', ['../users.json', browser.PREFIX+'browser-inputs/users.json',
    browser.PREFIX+'browser-evidence/users.json', browser.PREFIX+'browser-evidence/browser-descriptor.json',
    browser.PREFIX+'browser-evidence/browser-evidence.json.tmp', browser.PREFIX+'browser-evidence/screenshots/../users.png',
    browser.PREFIX+'browser-evidence/screenshots/a b.png', browser.PREFIX+'browser-evidence/screenshots/x;id.png',
    browser.PREFIX+'browser-evidence/screenshots/a/b.png', browser.PREFIX+'browser-evidence/screenshots/.png',
    browser.PREFIX+'browser-evidence/screenshots/a.PNG'])
def test_collection_never_admits_private_traversing_or_shell_sensitive_paths(tmp_path, path):
    value = fixture(tmp_path); value.manifest['files'][0]['path'] = path
    with pytest.raises(ValueError, match='unsafe'): browser.validate_manifest(value.manifest, value.context, value.project)


@pytest.mark.parametrize('damage', ['count', 'file-size', 'total-size', 'duplicate', 'foreign-context'])
def test_browser_catalog_bounds_are_checked_before_any_artifact_read(tmp_path, damage):
    value = fixture(tmp_path)
    if damage in ('count', 'total-size'):
        value.manifest['files'] = [{'path': browser.PREFIX+f'browser-evidence/screenshots/shot-{index}.png',
            'bytes': 32*browser.MIB if damage == 'total-size' else 1, 'sha256': '1'*64} for index in range(5 if damage == 'total-size' else 129)]
    if damage == 'file-size': value.manifest['files'][0]['bytes'] = 32*browser.MIB+1
    if damage == 'duplicate': value.manifest['files'].append(dict(value.manifest['files'][0]))
    if damage == 'foreign-context': value.manifest['commit'] = '0'*40
    with pytest.raises(ValueError): browser.validate_manifest(value.manifest, value.context, value.project)


def test_failed_browser_preserves_original_public_report_and_png_without_becoming_pass(tmp_path):
    value = fixture(tmp_path); value.report['status'] = 'FAIL'; value.report['checks']['real-history-diff']['status'] = 'FAIL'; resign(value)
    assert verify(value, False)['files'] == 2
    with pytest.raises(ValueError): verify(value)


def test_private_users_payload_cannot_be_archived_under_the_public_report_name(tmp_path):
    value=fixture(tmp_path)
    value.report['accounts']['inspector']['password']='private-fixture-password'
    resign(value)
    with pytest.raises(ValueError,match='Private users'):verify(value,False)


@pytest.mark.parametrize('damage',['manifest-reference','manifest-hash','report-reference','raw-extra','duplicate-json'])
def test_manifest_and_original_report_references_cannot_be_replaced_by_envelopes(tmp_path,damage):
    value=fixture(tmp_path)
    if damage=='manifest-reference':value.cleanup['browserEvidence']['file']=browser.PREFIX+'browser-inputs/users.json'
    if damage=='manifest-hash':value.cleanup['browserEvidence']['sha256']='0'*64
    if damage=='report-reference':value.proof['browserAcceptance']['sha256']='0'*64
    if damage=='raw-extra':(tmp_path/'browser-evidence/raw.log').write_bytes(b'not-public')
    if damage=='duplicate-json':
        file=tmp_path/'browser-evidence/browser-evidence.json';file.write_bytes(b'{"schemaVersion":1,'+file.read_bytes()[1:])
        row=value.manifest['files'][0];row.update(bytes=file.stat().st_size,sha256=hashlib.sha256(file.read_bytes()).hexdigest())
        value.proof['browserAcceptance']['sha256']=row['sha256']
        value.cleanup['browserEvidence']['sha256']=write(tmp_path/'browser-manifest.json',value.manifest)
    with pytest.raises(ValueError):verify(value)


@pytest.mark.parametrize('damage', ['report', 'png', 'png-magic', 'symlink', 'hardlink', 'missing'])
def test_changed_or_linked_original_bytes_are_rejected(tmp_path, damage):
    value = fixture(tmp_path); path = tmp_path/'browser-evidence/screenshots/actual-ui.png'
    if damage == 'report': (tmp_path/'browser-evidence/browser-evidence.json').write_bytes(b'{}')
    if damage == 'png': path.write_bytes(path.read_bytes()+b'changed')
    if damage == 'missing': path.unlink()
    if damage in ('symlink', 'hardlink'):
        original = tmp_path/'original.png'; path.rename(original)
        if damage == 'symlink': path.symlink_to(original)
        else: os.link(original, path)
    if damage == 'png-magic':
        path.write_bytes(b'not-a-png'*8); row=value.manifest['files'][1]
        row.update(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        value.cleanup['browserEvidence']['sha256'] = write(tmp_path/'browser-manifest.json', value.manifest)
    with pytest.raises((ValueError, OSError)): verify(value, False)


def container_row(tmp_path, project, network):
    return {'Id': CID, 'Image': IMAGE, 'Config': {'User': '1000:1000', 'Hostname': CID[:12],
        'Labels': {'io.doorhandle.rehearsal': project, 'io.doorhandle.collaboration-browser': 'f'*12}},
        'HostConfig': {'Memory': browser.MEMORY, 'MemorySwap': browser.MEMORY, 'NanoCpus': 2000000000, 'PidsLimit': 512,
            'ShmSize': 256*browser.MIB, 'Init': True, 'ReadonlyRootfs': True, 'Privileged': False,
            'RestartPolicy': {'Name': 'no'}, 'CapDrop': ['ALL'], 'CapAdd': None, 'Devices': [], 'Binds': None,
            'SecurityOpt': ['no-new-privileges=true'], 'PidMode': '', 'IpcMode': 'private', 'PortBindings': {},
            'NetworkMode': network, 'Tmpfs': {'/tmp': 'bounded'}},
        'Mounts': [{'Type': 'bind', 'Source': str(tmp_path/'browser-inputs'), 'Destination': '/run/doorhandle', 'RW': False},
                   {'Type': 'bind', 'Source': str(tmp_path/'browser-evidence'), 'Destination': '/evidence', 'RW': True}],
        'NetworkSettings': {'Networks': {network: {}}}, 'State': {'Running': False, 'ExitCode': 0, 'OOMKilled': False}}


@pytest.mark.parametrize('damage', ['none', 'tmpfs-row', 'uid', 'image', 'hostname', 'memory', 'swap', 'cpu', 'pids',
    'shm', 'init', 'rootfs', 'privileged', 'restart', 'capability', 'device', 'socket', 'pid', 'ipc', 'port',
    'network-mode', 'input-rw', 'input-source', 'tmpfs', 'extra-network', 'public-network', 'foreign-label'])
def test_actual_docker_inspect_must_match_the_exact_owned_browser_creation_boundary(tmp_path, damage):
    project, network = 'doorhandle-rehearsal-'+'f'*12, 'owned-internal'
    row = container_row(tmp_path, project, network)
    net = {'Id': '7'*64, 'Internal': True, 'Labels': {'io.doorhandle.rehearsal': project}}
    if damage == 'tmpfs-row': row['Mounts'].append({'Type': 'tmpfs', 'Destination': '/tmp', 'RW': True})
    if damage == 'uid': row['Config']['User'] = '0:0'
    if damage == 'image': row['Image'] = 'sha256:'+'0'*64
    if damage == 'hostname': row['Config']['Hostname'] = 'other'
    changed = {'memory': ('Memory', browser.MEMORY*2), 'swap': ('MemorySwap', -1), 'cpu': ('NanoCpus', 0), 'pids': ('PidsLimit', -1),
        'shm': ('ShmSize', browser.MIB), 'init': ('Init', False), 'rootfs': ('ReadonlyRootfs', False), 'privileged': ('Privileged', True),
        'restart': ('RestartPolicy', {'Name': 'always'}), 'capability': ('CapAdd', ['SYS_ADMIN']), 'device': ('Devices', ['/dev/sda']),
        'socket': ('Binds', ['/var/run/docker.sock:/var/run/docker.sock']), 'pid': ('PidMode', 'host'), 'ipc': ('IpcMode', 'host'),
        'port': ('PortBindings', {'80/tcp': []}), 'network-mode': ('NetworkMode', 'host'), 'tmpfs': ('Tmpfs', {'/tmp': '', '/cache': ''})}
    if damage in changed: key, value = changed[damage]; row['HostConfig'][key] = value
    if damage == 'input-rw': row['Mounts'][0]['RW'] = True
    if damage == 'input-source': row['Mounts'][0]['Source'] = '/production'
    if damage == 'extra-network': row['NetworkSettings']['Networks']['public'] = {}
    if damage == 'public-network': net['Internal'] = False
    if damage == 'foreign-label': net['Labels']['io.doorhandle.rehearsal'] = 'another-attempt'
    ctx = SimpleNamespace(project=project, token='f'*12, ops=SimpleNamespace(docker=lambda *args: json.dumps([row if args[0] == 'inspect' else net]).encode()))
    call = lambda: adapter.inspect(ctx, CID, IMAGE, network, tmp_path/'browser-inputs', tmp_path/'browser-evidence')
    if damage in ('none', 'tmpfs-row'): assert call()['executionUid'] == 1000
    else:
        with pytest.raises(ValueError): call()


def test_browser_creator_uses_private_uid1000_mounts_and_a_separate_bounded_phase(tmp_path, monkeypatch):
    value = fixture(tmp_path/'contract')
    attempt = tmp_path/'verification'/value.context['release']; directory=attempt/'checkout/work/runtime-acceptance'; directory.mkdir(parents=True)
    network='owned-internal'; commands=[]; plans=[]; installed={}
    ctx=SimpleNamespace(directory=directory, attempt=attempt, source=ROOT, project=value.project, token='f'*12,
        report_task_id='actual-worker-task', owner={'browserImage':IMAGE,'browserImageBytes':123,'browserSourceHashes':browser.source_contract(ROOT)[0],
            'modelStreamProbes': {'phase': 'ARMED', 'descriptor': {'schemaVersion': 1}}},
        accounts={alias:{**row,'username':alias,'password':'private-fixture-password'} for alias,row in value.report['accounts'].items()},
        args=SimpleNamespace(commit=value.context['commit'],source_sha256=value.context['sourceSha256']),
        config={'networks':{'doorhandle-network':{'name':network}}}, context=lambda:dict(value.context), save=lambda:None,
        common=SimpleNamespace(write_json=lambda path,data:write(path,data)), resources=SimpleNamespace(admit=lambda *args:plans.append(args)))
    def docker(*args,**kwargs):
        commands.append(args)
        if args[0]=='create':return CID.encode()
        if args[0]=='start':
            manifest,_=install(directory,value.context,value.project,{},{}); installed.update(manifest); return b''
        if args[0]=='wait':return b'0'
        if args[0]=='inspect':return json.dumps([container_row(directory,value.project,network)]).encode()
        if args[:2]==('network','inspect'):return json.dumps([{'Id':'7'*64,'Internal':True,'Labels':{'io.doorhandle.rehearsal':value.project}}]).encode()
        raise AssertionError('Unexpected Docker operation in source fixture')
    ctx.ops=SimpleNamespace(docker=docker)
    monkeypatch.setattr(adapter.os,'getuid',lambda:1000);monkeypatch.setattr(adapter.os,'getgid',lambda:1000)
    monkeypatch.setattr(adapter,'preserve',lambda _:installed)
    proof=adapter.run(ctx)
    creation=next(row for row in commands if row[0]=='create')
    assert creation[creation.index('--user')+1]=='1000:1000' and '--read-only' in creation and '--init' in creation
    assert 'type=bind,src='+str(directory/'browser-inputs')+',dst=/run/doorhandle,readonly' in creation
    assert not any('private-fixture-password' in part for part in creation)
    assert (directory/'browser-inputs/users.json').stat().st_mode & 0o777 == 0o600
    assert plans[0][0]=='runtime-browser' and plans[0][1]==512*browser.MIB and plans[0][-1]==browser.MEMORY
    assert proof['requiredBrowserChecksPassed']==19 and proof['allA01A28Verified'] is False


@pytest.mark.parametrize('damage',['none','source-link','source-size','foreign-image','foreign-label','platform'])
def test_browser_build_copies_only_bounded_fixed_source_and_binds_its_owned_immutable_image(tmp_path,damage):
    source=tmp_path/'source/script/docker';source.mkdir(parents=True)
    for name in adapter.FILES:(source/name).write_bytes((ROOT/'script/docker'/name).read_bytes())
    if damage=='source-link':
        original=tmp_path/'original';(source/adapter.FILES[1]).rename(original);(source/adapter.FILES[1]).symlink_to(original)
    if damage=='source-size':(source/adapter.FILES[1]).write_bytes(b'x'*(browser.MIB+1))
    row={'Id':IMAGE,'Os':'linux','Architecture':'amd64','Config':{'Labels':{'io.doorhandle.rehearsal':'doorhandle-rehearsal-'+'f'*12}},'Size':123}
    if damage=='foreign-image':row['Id']='floating-image'
    if damage=='foreign-label':row['Config']['Labels']['io.doorhandle.rehearsal']='other'
    if damage=='platform':row['Architecture']='arm64'
    ctx=SimpleNamespace(directory=tmp_path/'runtime',source=tmp_path/'source',root=tmp_path,args=SimpleNamespace(tag='ci-owned'),
        token='f'*12,project='doorhandle-rehearsal-'+'f'*12,identity={},owner={},save=lambda:None,
        build_resources=SimpleNamespace(runtime_image=lambda *args:{'file':'controlled','sha256':'a'*64}),
        ops=SimpleNamespace(docker=lambda *args:json.dumps([row]).encode()))
    if damage=='none':
        adapter.prepare_image(ctx);assert ctx.owner['browserImage']==IMAGE
        assert ctx.owner['browserSourceHashes']['collaboration-browser-runner.py']==browser.source_contract(ROOT)[0]['collaboration-browser-runner.py']
    else:
        with pytest.raises(ValueError):adapter.prepare_image(ctx)


@pytest.mark.parametrize('damage',['temporary','private','symlink'])
def test_failed_creator_preserves_valid_originals_before_rejecting_unapproved_private_artifacts(tmp_path,monkeypatch,damage):
    attempt=tmp_path/'attempt';directory=attempt/'checkout/work/runtime-acceptance';value=fixture(directory)
    evidence=directory/'browser-evidence'
    if damage=='temporary':(evidence/'browser-evidence.json.tmp').write_text('private-fixture-password')
    if damage=='private':(evidence/'users.json').write_text('private-fixture-password')
    if damage=='symlink':(evidence/'screenshots/private.png').symlink_to(evidence/'browser-evidence.json')
    real_stat=Path.stat
    def owned_stat(path,*args,**kwargs):
        info=real_stat(path,*args,**kwargs)
        if path.is_relative_to(evidence):
            fields=list(info);fields[4]=1000;fields[5]=1000;return os.stat_result(fields)
        return info
    monkeypatch.setattr(Path,'stat',owned_stat)
    ctx=SimpleNamespace(directory=directory,attempt=attempt,project=value.project,context=lambda:value.context,
        owner={'browserContainerId':CID,'browserImage':IMAGE},common=SimpleNamespace(write_json=write),save=lambda:None)
    with pytest.raises(ValueError,match='approved original evidence was preserved'):adapter.preserve(ctx)
    manifest_file=directory/'browser-manifest.json';manifest=json.loads(manifest_file.read_bytes())
    assert manifest['rejectedArtifactCount']==1 and len(manifest['files'])==2
    assert 'private-fixture-password' not in manifest_file.read_text()
    public=tmp_path/'public';public.mkdir();(public/'browser-manifest.json').write_bytes(manifest_file.read_bytes())
    for row in manifest['files']:
        relative=row['path'][len(browser.PREFIX):];target=public/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((directory/relative).read_bytes())
    cleanup={**value.cleanup,'browserEvidence':ctx.owner['browserEvidence']}
    assert browser.validate_files(public,cleanup)['status']=='PRESERVED'
