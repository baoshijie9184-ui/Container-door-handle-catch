"""Synthetic preflight controls; execution belongs to Jenkins on ECS only."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('control_preflight_tests', ROOT / 'script/jenkins/control-preflight.py')
preflight = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = preflight
SPEC.loader.exec_module(preflight)


def test_current_fixed_profile_contains_every_focused_module():
    profile = json.loads((ROOT / 'script/jenkins/compact-acceptance.json').read_bytes())
    minimum = preflight.required_minimum(profile)
    assert set(minimum) == {
        'test_jenkins_resource_budget', 'test_jenkins_fixture_admission', 'test_jenkins_fixture_cgroup_probe',
        'test_derived_mysql_retirement', 'test_source_pytest_retirement',
        'test_jenkins_ecs_build_cleanup',
        'test_failed_native_jar_duplicates', 'test_historical_builder_retirement',
        'test_historical_mysql_fixture_retirement', 'test_public_buildkit_layer_retirement',
        'test_generated_public_image_archive_retirement',
        'test_historical_python_build_cache_retirement', 'test_local_artifact_custody',
        'test_compose_container_selection', 'test_compact_schema_source',
        'test_local_fixed_originals_retirement', 'test_fixed_originals_attestation',
        'test_local_mysql_custody', 'test_local_mysql_source_classification',
        'test_project_mysql_custody',
        'test_jenkins_suite_evidence', 'test_jenkins_maven_dependency_cache',
        'test_control_preflight', 'test_middleware_fixture', 'test_observability_fixture', 'test_semantic_mysql_fixture',
    }
    assert minimum['test_public_buildkit_layer_retirement'] >= 34
    assert minimum['test_local_mysql_source_classification'] >= 130
    assert minimum['test_project_mysql_custody'] >= 32
    assert minimum['test_derived_mysql_retirement'] >= 97
    controller = (ROOT / 'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    declaration = re.search(r'(?m)^\s*\$expected=@\(([^\r\n]+)\)\r?$', controller)
    assert declaration, 'Controller must declare its exact preflight module contract'
    controller_modules = ast.literal_eval('(' + declaration.group(1) + ')')
    assert len(controller_modules) == len(set(controller_modules)) and set(controller_modules) == set(minimum), \
        'Controller and ECS must agree on every preflight module before fixture preparation'
    assert minimum['test_control_preflight'] >= 8
    assert all(type(value) is int and value > 0 for value in minimum.values())
    for mutation in ('missing', 'boolean', 'zero'):
        changed = copy.deepcopy(profile); entries = changed['python']['requiredSuites']
        entry = next(value for value in entries if value['module'] == 'tests_python.test_control_preflight')
        if mutation == 'missing': entries.remove(entry)
        else: entry['minimumTests'] = True if mutation == 'boolean' else 0
        with pytest.raises(ValueError): preflight.required_minimum(changed)


def test_unclaimed_formal_verification_paths_are_available(tmp_path):
    preflight.require_fresh_verification_paths(tmp_path)


@pytest.mark.parametrize('name', ['verify-remote.py', '.verification-upload'])
@pytest.mark.parametrize('kind', ['file', 'dangling-link'])
def test_occupied_formal_verification_paths_fail_before_database_preparation(tmp_path, name, kind):
    path = tmp_path / name
    if kind == 'file': path.write_text('reserved by another phase')
    else: path.symlink_to(tmp_path / 'absent')
    with pytest.raises(ValueError, match='CONTROL_FORMAL_VERIFICATION_PATH_OCCUPIED'):
        preflight.require_fresh_verification_paths(tmp_path)


def report(tmp_path, mutation=None):
    minimum = {'test_control_preflight': 2, 'test_jenkins_fixture_admission': 1}
    root = ET.Element('testsuites'); suite = ET.SubElement(root, 'testsuite')
    cases = []
    for module, count in minimum.items():
        for index in range(count):
            cases.append(ET.SubElement(suite, 'testcase', {'classname': 'tests_python.' + module,
                                                          'name': 'synthetic_' + str(index)}))
    ET.SubElement(cases[0], 'system-out').text = 'ordinary safe test output'
    if mutation in ('error', 'skip'):
        ET.SubElement(cases[0], 'error' if mutation == 'error' else 'skipped')
    elif mutation == 'below_minimum': suite.remove(cases[0])
    elif mutation == 'unknown_module': cases[0].set('classname', 'tests_python.test_unexpected_module')
    elif mutation == 'missing_module': suite.remove(cases[-1])
    path = tmp_path / 'python.xml'; path.write_bytes(ET.tostring(root, encoding='utf8')); path.chmod(0o600)
    return path, minimum


def test_complete_report_allows_system_out_without_changing_pass_counts(tmp_path):
    path, minimum = report(tmp_path)
    result = preflight.tally_report(path, minimum)
    assert result == {name: {'passed': count, 'failed': 0, 'skipped': 0} for name, count in minimum.items()}


@pytest.mark.parametrize('mutation', ['error', 'skip', 'below_minimum', 'unknown_module', 'missing_module'])
def test_report_failure_skip_missing_or_foreign_module_refuses_admission(tmp_path, mutation):
    path, minimum = report(tmp_path, mutation)
    with pytest.raises(ValueError): preflight.tally_report(path, minimum)


def source_tree(tmp_path):
    path = tmp_path / 'control-checkout'; path.mkdir(mode=0o700)
    file = path / 'source.py'; file.write_bytes(b'original fixed source'); file.chmod(0o600)
    info = path.stat()
    return path, [info.st_dev, info.st_ino, info.st_uid]


def test_owned_scratch_cleanup_preserves_external_symlink_target(tmp_path):
    path, expected = source_tree(tmp_path)
    external = tmp_path / 'retained-report'; external.write_bytes(b'retained external original'); external.chmod(0o600)
    (path / 'outside-link').symlink_to(external)
    preflight.remove_owned_tree(path, expected)
    assert not path.exists() and external.read_bytes() == b'retained external original'


@pytest.mark.parametrize('mutation', ['root_symlink', 'inode_drift'])
def test_scratch_cleanup_refuses_link_or_changed_directory_identity(tmp_path, mutation):
    path, expected = source_tree(tmp_path)
    selected = path
    if mutation == 'root_symlink':
        selected = tmp_path / 'changed-source'; selected.symlink_to(path, target_is_directory=True)
    else: expected[1] += 1
    with pytest.raises(ValueError): preflight.remove_owned_tree(selected, expected)
    assert path.is_dir() and (path / 'source.py').read_bytes() == b'original fixed source'


@pytest.fixture
def container(tmp_path, monkeypatch):
    context = {'release': 'ci-999-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}
    cid, image, token = 'c' * 64, 'sha256:' + 'd' * 64, 'e' * 24
    source, output = tmp_path / 'control-checkout', tmp_path / 'output'
    row = {'Id': cid, 'Image': image, 'Config': {'User': '1000:1000', 'Entrypoint': ['/usr/local/bin/python'],
           'Labels': {preflight.LABEL: token, 'io.doorhandle.release': context['release'],
                      'io.doorhandle.source': context['sourceSha256'], 'io.doorhandle.commit': context['commit']}},
           'HostConfig': {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'AutoRemove': False,
                          'Memory': preflight.MEMORY, 'MemorySwap': preflight.MEMORY, 'NanoCpus': 2 * 10 ** 9,
                          'PidsLimit': 256, 'RestartPolicy': {'Name': 'no'}, 'CapDrop': ['ALL'],
                          'SecurityOpt': ['no-new-privileges:true']},
           'Mounts': [{'Type': 'bind', 'Source': str(source), 'Destination': str(source), 'RW': False},
                      {'Type': 'bind', 'Source': str(output), 'Destination': str(output), 'RW': True}],
           'State': {'Running': False, 'Status': 'exited', 'Pid': 0, 'Restarting': False, 'ExitCode': 0}}
    current = [row]; calls = []
    def fake_docker(*arguments, **_kwargs):
        assert arguments == ('inspect', cid)
        calls.append(arguments)
        return json.dumps([copy.deepcopy(current[0])]).encode('utf8')
    monkeypatch.setattr(preflight, 'docker', fake_docker)
    return SimpleNamespace(row=row, current=current, calls=calls, cid=cid, context=context,
                           token=token, image=image, source=source, output=output)


def admitted(container):
    return preflight.container_row(container.cid, container.context, container.token,
                                   container.image, container.source, container.output)


def test_exact_container_allows_only_fixed_owner_image_and_two_mounts(container):
    assert admitted(container) == container.row
    assert container.calls == [('inspect', container.cid)]


def test_container_owner_sandbox_resources_and_mount_changes_are_rejected(container):
    changes = [
        ('HostConfig', 'NetworkMode', 'host'), ('HostConfig', 'ReadonlyRootfs', False),
        ('HostConfig', 'Memory', preflight.MEMORY + 1), ('HostConfig', 'PidsLimit', 257),
        ('HostConfig', 'Privileged', True), ('Config', 'User', '0:0'),
    ]
    for section, field, value in changes:
        row = copy.deepcopy(container.row); row[section][field] = value; container.current[0] = row
        with pytest.raises(ValueError): admitted(container)
    for mutation in ('owner', 'image', 'source_rw', 'output_ro', 'extra_mount'):
        row = copy.deepcopy(container.row)
        if mutation == 'owner': row['Config']['Labels'][preflight.LABEL] = 'f' * 24
        elif mutation == 'image': row['Image'] = 'sha256:' + 'f' * 64
        elif mutation == 'source_rw': row['Mounts'][0]['RW'] = True
        elif mutation == 'output_ro': row['Mounts'][1]['RW'] = False
        else: row['Mounts'].append({'Type': 'bind', 'Source': '/extra', 'Destination': '/extra', 'RW': False})
        container.current[0] = row
        with pytest.raises(ValueError): admitted(container)


@pytest.fixture
def execution(tmp_path, monkeypatch):
    args = SimpleNamespace(root=str(tmp_path), tag='ci-999-' + 'a' * 12, commit='a' * 40,
                           source_sha256='b' * 64, tool_manifest_sha256='c' * 64,
                           instance_id='i-fixture', machine_id='d' * 32)
    identity = {'instanceId': args.instance_id, 'machineId': args.machine_id, 'executionLocation': 'ECS'}
    base = tmp_path / 'inbox' / args.tag / 'control-preflight'
    base.mkdir(mode=0o700, parents=True); output = base / 'output'; output.mkdir(mode=0o700)
    claim = {**preflight.execution_context(args, identity),
             'supervisor': {'pid': 4321, 'startTicks': '1234', 'bootId': 'fixture-boot'}}
    receipt = {'schemaVersion': 1, 'kind': 'doorhandle-control-preflight',
               **{key: value for key, value in preflight.execution_context(args, identity).items()
                  if key not in ('schemaVersion', 'kind')},
               'status': 'CONTROL_PREFLIGHT_PASS', 'fullProjectVerified': False,
               'businessRuntimeStarted': False, 'containerCleanupConfirmed': True,
               'sourceScratchCleanupConfirmed': True, 'reports': {}}
    claim_path, receipt_path = base / 'execution.json', output / 'receipt.json'
    preflight.write(claim_path, claim); preflight.write(receipt_path, receipt)
    clock, live, sleeps = [0], [False], []
    def start(pid):
        assert pid == 4321
        if not live[0]: raise FileNotFoundError('original process ended')
        return '1234'
    def sleep(seconds):
        sleeps.append(seconds); clock[0] += 240
    verifier = SimpleNamespace(supervisor_start=start)
    monkeypatch.setattr(preflight, 'admit_context', lambda requested:
                        (tmp_path, tmp_path / 'source.tar.gz', 0, {'verifier': verifier}, identity))
    monkeypatch.setattr(preflight, 'boot_id', lambda: 'fixture-boot')
    monkeypatch.setattr(preflight, 'time', SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep))
    producer = preflight.run
    monkeypatch.setattr(preflight, 'run', lambda _args: pytest.fail('An observer must never restart the tests'))
    return SimpleNamespace(args=args, identity=identity, base=base, claim=claim, receipt=receipt,
                           claim_path=claim_path, receipt_path=receipt_path,
                           live=live, clock=clock, sleeps=sleeps, verifier=verifier, producer=producer)


def test_observer_returns_the_same_completed_original_and_exact_receipt(execution):
    result = preflight.observe(execution.args)
    assert result['status'] == 'CONTROL_PREFLIGHT_PASS' and result['terminal'] is True
    assert result['cleanupConfirmed'] is True and result['receipt'] == str(execution.receipt_path)
    assert result['receiptSha256'] == preflight.digest(execution.receipt_path)
    assert execution.sleeps == []


def test_run_registers_the_original_supervisor_before_starting_any_test(execution, monkeypatch):
    root = execution.base.parents[2] / 'producer'
    inbox = root / 'inbox' / execution.args.tag; inbox.mkdir(parents=True, mode=0o700)
    real_os = preflight.os
    facade = {name: getattr(real_os, name) for name in dir(real_os) if not name.startswith('__')}
    facade.update(getpid=lambda: 4321,
                  statvfs=lambda _path: SimpleNamespace(f_bavail=8 * 1024 ** 3, f_frsize=1))
    monkeypatch.setattr(preflight, 'os', SimpleNamespace(**facade))
    original_signal = preflight.signal
    monkeypatch.setattr(preflight, 'signal', SimpleNamespace(SIGTERM=original_signal.SIGTERM,
        SIGHUP=original_signal.SIGHUP, SIGINT=original_signal.SIGINT, SIG_IGN=original_signal.SIG_IGN,
        signal=lambda *_args: None))
    def admitted_source(_archive, _checkout, _commit):
        claim = json.loads((inbox / 'control-preflight/execution.json').read_bytes())
        assert preflight.execution_supervisor(claim, execution.args, execution.identity) == execution.claim['supervisor']
        raise ValueError('CONTROL_SOURCE_SHA_DIFFERS')
    verifier = SimpleNamespace(supervisor_start=lambda _pid: '1234', unpack_source=admitted_source)
    monkeypatch.setattr(preflight, 'admit_context', lambda _args:
                        (root, root / 'source.tar.gz', 0, {'verifier': verifier}, execution.identity))
    monkeypatch.setattr(preflight, 'docker', lambda *_args, **_kwargs: pytest.fail('No tests may precede the claim'))
    receipt, path = execution.producer(execution.args)
    assert receipt['status'] == 'FAILED_OR_UNKNOWN' and receipt['failure']['code'] == 'CONTROL_SOURCE_SHA_DIFFERS'
    assert receipt['containerCleanupConfirmed'] is True and receipt['sourceScratchCleanupConfirmed'] is True
    assert path.is_file() and (inbox / 'control-preflight/execution.json').is_file()


def test_receipt_appearance_does_not_end_observation_while_original_process_is_live(execution, monkeypatch):
    execution.live[0] = True
    def ended(seconds):
        assert execution.receipt_path.exists()
        execution.sleeps.append(seconds); execution.clock[0] += 1; execution.live[0] = False
    monkeypatch.setattr(preflight.time, 'sleep', ended)
    assert preflight.observe(execution.args)['terminal'] is True
    assert execution.sleeps == [1]


@pytest.mark.parametrize('publication', ['missing', 'partial'])
def test_dispatch_without_a_complete_claim_waits_for_the_same_original(execution, monkeypatch, publication):
    if publication == 'missing': execution.claim_path.unlink()
    else: execution.claim_path.write_bytes(b'{')
    def published(seconds):
        execution.sleeps.append(seconds); execution.clock[0] += 1
        execution.claim_path.write_bytes(preflight.encoded(execution.claim))
    monkeypatch.setattr(preflight.time, 'sleep', published)
    assert preflight.observe(execution.args)['status'] == 'CONTROL_PREFLIGHT_PASS'
    assert execution.sleeps == [1]


def test_dispatch_without_a_claim_cannot_authorize_cleanup(execution):
    execution.claim_path.unlink()
    with pytest.raises(ValueError, match='CONTROL_EXECUTION_OBSERVATION_TIMEOUT'):
        preflight.observe(execution.args)
    assert execution.receipt_path.exists() and execution.sleeps


def test_live_original_times_out_without_stopping_or_restarting_it(execution):
    execution.live[0] = True
    with pytest.raises(ValueError, match='CONTROL_EXECUTION_OBSERVATION_TIMEOUT'):
        preflight.observe(execution.args)
    assert execution.live[0] is True and execution.receipt_path.exists()


@pytest.mark.parametrize('state', ['gone', 'reused'])
def test_stopped_or_reused_pid_without_terminal_receipt_retains_tools(execution, state):
    execution.receipt_path.unlink()
    if state == 'reused': execution.verifier.supervisor_start = lambda _pid: '5678'
    with pytest.raises(ValueError, match='CONTROL_EXECUTION_STOPPED_WITHOUT_RECEIPT'):
        preflight.observe(execution.args)


@pytest.mark.parametrize('mutation', ['release', 'commit', 'source', 'tool', 'identity', 'boot',
                                    'pid_bool', 'pid_one', 'pid_text', 'ticks_number', 'ticks_text', 'schema_bool'])
def test_foreign_or_invalid_original_claim_never_authorizes_cleanup(execution, mutation):
    claim = copy.deepcopy(execution.claim)
    fields = {'release': 'release', 'commit': 'commit', 'source': 'sourceSha256', 'tool': 'toolManifestSha256'}
    if mutation in fields: claim[fields[mutation]] = 'foreign'
    elif mutation == 'identity': claim['identity']['machineId'] = 'e' * 32
    elif mutation == 'boot': claim['supervisor']['bootId'] = 'previous-boot'
    elif mutation == 'pid_bool': claim['supervisor']['pid'] = True
    elif mutation == 'pid_one': claim['supervisor']['pid'] = 1
    elif mutation == 'pid_text': claim['supervisor']['pid'] = '4321'
    elif mutation == 'ticks_number': claim['supervisor']['startTicks'] = 1234
    elif mutation == 'ticks_text': claim['supervisor']['startTicks'] = 'unknown'
    else: claim['schemaVersion'] = True
    execution.claim_path.write_bytes(preflight.encoded(claim))
    with pytest.raises(ValueError, match='CONTROL_EXECUTION_CLAIM_DIFFERS'):
        preflight.observe(execution.args)


@pytest.mark.parametrize('mutation', ['kind', 'schemaVersion', 'release', 'commit', 'sourceSha256',
                                    'toolManifestSha256', 'identity', 'status',
                                    'fullProjectVerified', 'businessRuntimeStarted'])
def test_terminal_receipt_must_belong_to_this_control_execution(execution, mutation):
    receipt = copy.deepcopy(execution.receipt)
    receipt[mutation] = True if mutation in ('schemaVersion', 'fullProjectVerified', 'businessRuntimeStarted') else 'foreign'
    execution.receipt_path.write_bytes(preflight.encoded(receipt))
    with pytest.raises(ValueError, match='CONTROL_TERMINAL_RECEIPT_DIFFERS'):
        preflight.observe(execution.args)


@pytest.mark.parametrize('filename', ['execution.json', 'output/receipt.json'])
@pytest.mark.parametrize('shape', ['symlink', 'hardlink'])
def test_observation_refuses_redirected_originals(execution, filename, shape):
    path = execution.base / filename; retained = execution.base / ('retained-' + path.name)
    path.rename(retained)
    if shape == 'symlink': path.symlink_to(retained)
    else: preflight.os.link(retained, path)
    with pytest.raises(ValueError): preflight.observe(execution.args)
    assert retained.exists()


@pytest.mark.parametrize('field', ['containerCleanupConfirmed', 'sourceScratchCleanupConfirmed'])
def test_failed_original_with_unresolved_cleanup_is_terminal_but_cannot_release_tools(execution, field):
    receipt = copy.deepcopy(execution.receipt); receipt['status'] = 'FAILED_OR_UNKNOWN'; receipt[field] = False
    execution.receipt_path.write_bytes(preflight.encoded(receipt))
    result = preflight.observe(execution.args)
    assert result['status'] == 'FAILED_OR_UNKNOWN' and result['terminal'] is True
    assert result['cleanupConfirmed'] is False


def test_control_main_ignores_transport_hangup_but_keeps_explicit_cancellation(execution, monkeypatch):
    handlers, results = {}, []
    real_signal = preflight.signal
    monkeypatch.setattr(preflight, 'signal', SimpleNamespace(SIGTERM=real_signal.SIGTERM,
        SIGHUP=real_signal.SIGHUP, SIGINT=real_signal.SIGINT, SIG_IGN=real_signal.SIG_IGN,
        signal=lambda number, handler: handlers.__setitem__(number, handler)))
    argv = ['control-preflight.py']
    for name in ('root', 'tag', 'commit', 'source_sha256', 'instance_id', 'machine_id', 'tool_manifest_sha256'):
        argv += ['--' + name.replace('_', '-'), getattr(execution.args, name)]
    monkeypatch.setattr(preflight.sys, 'argv', argv)
    monkeypatch.setattr(preflight, 'run', lambda _args: (execution.receipt, execution.receipt_path))
    monkeypatch.setattr(preflight, 'progress', results.append)
    assert preflight.main() == 0 and results[-1]['terminal'] is True
    assert handlers[real_signal.SIGHUP] == real_signal.SIG_IGN
    for number in (real_signal.SIGTERM, real_signal.SIGINT):
        with pytest.raises(RuntimeError, match='CONTROL_PREFLIGHT_INTERRUPTED'): handlers[number](number, None)


def test_broken_stdout_does_not_cancel_the_completed_original(monkeypatch):
    calls = []
    def disconnected(*_args, **_kwargs): raise BrokenPipeError('SSH disconnected')
    monkeypatch.setattr('builtins.print', disconnected)
    monkeypatch.setattr(preflight, 'os', SimpleNamespace(devnull='/dev/null', O_WRONLY=1,
        open=lambda path, flags: 9, dup2=lambda source, target: calls.append((source, target)),
        close=lambda fd: calls.append(('close', fd))))
    preflight.progress({'status': 'CONTROL_PREFLIGHT_PASS'})
    assert calls == [(9, 1), ('close', 9)]


def test_controller_observes_original_before_scp_and_dependency_cleanup():
    source = (ROOT / 'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    run = source.split("if ($Action -eq 'Preflight') {", 1)[1].split('$remoteInbox =', 1)[0]
    assert run.index('execution-request.json') < run.index('$lines=@(& ssh.exe')
    assert '$controlExit -eq 255' in run
    assert run.index('$remoteResult=Wait-ExistingControlPreflight') < run.index('"${destination}:$remoteOutput/receipt.json"')
    assert 'originalExitCode=$originalControlExit' in run and 'transportRecovered=' in run
    observer = source.split('function Wait-ExistingControlPreflight {', 1)[1].split('function Wait-ExistingVerification', 1)[0]
    assert ' --observe"' in observer and 'Assert-ControlExecutionState $state $request' in observer
    assert 'if (-not $state.cleanupConfirmed)' in observer
    assert 'python3 -I -B' in observer and '$request.helperSha256' in observer
    cleanup = source.split("if ($Action -in @('PrepareTools', 'CleanupTools')) {", 1)[1].split("if ($Action -in @('PrepareFixtures'", 1)[0]
    assert cleanup.index('$null=Wait-ExistingControlPreflight') < cleanup.index("'$executor' cleanup")
