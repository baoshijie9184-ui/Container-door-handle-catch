"""ECS-run evidence contracts for serial suites and their unchanged original reports."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'script/jenkins' / file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


remote = module('serial_suite_remote_evidence', 'verify-remote.py')
inner = module('serial_suite_ecs_evidence', 'verify-ecs.py')
cleanup = module('serial_suite_original_custody', 'cleanup-ecs-builds.py')


@pytest.fixture
def java_workspace(tmp_path, monkeypatch):
    root = tmp_path / 'checkout'; root.mkdir()
    (root / 'pom.xml').write_text('<project><modules><module>module</module></modules></project>')
    (root / 'module').mkdir(); (root / 'module/pom.xml').write_text('<project/>')
    for name, raw in (('src/main/java/A.java', b'fixed source'), ('src/test/java/T.java', b'fixed test source'),
                      ('src/main/resources/schema.sql', b'fixed SQL resource')):
        path = root / 'module' / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    output = root / 'work/ci-evidence'; build = output / 'java-suites/suite-001'
    for name, raw in (('classes/A.class', b'compiled main'), ('test-classes/T.class', b'compiled tests'),
                      ('classes/schema.sql', b'fixed SQL resource')):
        path = build / 'module' / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    monkeypatch.setattr(inner, 'ROOT', root)
    return SimpleNamespace(root=root, output=output, build=build,
                           sources=inner.java_source_inventory(root), compiled=inner.java_compiled_inventory(build, output))


@pytest.mark.parametrize('initial', [True, False])
def test_java_reuse_keeps_the_full_lifecycle_and_each_exact_fixture_switch(tmp_path, initial):
    tools = {'MAVEN_CMD': '/fixed/mvn', 'MAVEN_REPOSITORY': '/fixed/repository'}
    first = {'javaSelection': ['org.example.OneTest'], 'fixtureProperties': ['first.fixture'],
             'fixtureOptions': ['-Dfirst.fixture=/private/first.json']}
    second = {'javaSelection': ['org.example.TwoTest'], 'fixtureProperties': ['second.fixture'],
              'fixtureOptions': ['-Dsecond.fixture=/private/second.json']}
    a = inner.java_maven_arguments(first, tools, tmp_path, initial=initial)
    b = inner.java_maven_arguments(second, tools, tmp_path, initial=initial)
    assert ('clean' in a) is initial and ('clean' in b) is initial
    assert 'test' in a and 'test' in b and not any('skipTests' in value or value == 'surefire:test' for value in a + b)
    assert '-Dtest=org.example.OneTest' in a and first['fixtureOptions'][0] in a and second['fixtureOptions'][0] not in a
    assert '-Dtest=org.example.TwoTest' in b and second['fixtureOptions'][0] in b and first['fixtureOptions'][0] not in b
    assert '-Ddoorhandle.verification-root=' + str(tmp_path) in a and '-Dmaven.repo.local=/fixed/repository' in a


def test_warm_source_regression_runs_the_ordinary_reactor_without_fixture_or_selected_test_flags(tmp_path):
    suite = {'javaSelection': ['org.example.RequiredPureTest'], 'fixtureProperties': [], 'fixtureOptions': []}
    arguments = inner.java_maven_arguments(suite, {'MAVEN_CMD': '/fixed/mvn'}, tmp_path,
                                           initial=False, source_regression=True)
    assert 'verify' in arguments and 'clean' not in arguments and 'test' not in arguments
    assert not any(value.startswith('-Dtest=') or 'skipTests' in value for value in arguments)


def test_two_suites_reuse_only_compiled_bytes_and_archive_distinct_fresh_xml(java_workspace):
    state = java_workspace; archived = []
    for name in ('org.example.OneTest', 'org.example.TwoTest'):
        inner.require_java_reuse(state.build, state.output, state.sources, state.compiled)
        raw = ('<testsuite><testcase classname="' + name + '" name="fresh-execution"/></testsuite>').encode()
        report = state.build / 'module/surefire-reports' / ('TEST-' + name + '.xml')
        report.parent.mkdir(); report.write_bytes(raw)
        catalog = inner.archive_java_reports(state.build, state.output / 'java', state.output)
        counts, selected = inner.java_report_counts(state.output, catalog, [name])
        inner.require_java_pass(counts, selected, fixture=True)
        assert (state.output / catalog[0]['path']).read_bytes() == raw
        archived.extend(catalog)
        result = inner.clear_java_reports(state.build, state.output)
        assert len(result) == 1 and result[0]['status'] == 'REMOVED'
        assert inner.java_compiled_inventory(state.build, state.output) == state.compiled
    assert len({row['path'] for row in archived}) == 2
    assert not list(state.build.glob('*/surefire-reports'))


@pytest.mark.parametrize('damage', ['reactor-pom', 'module-pom', 'source', 'source-resource', 'class', 'test-class', 'compiled-resource', 'extra-class'])
def test_java_reuse_refuses_changed_fixed_sources_classes_or_resources(java_workspace, damage):
    state = java_workspace
    path = {'reactor-pom': state.root / 'pom.xml', 'module-pom': state.root / 'module/pom.xml',
            'source': state.root / 'module/src/main/java/A.java',
            'source-resource': state.root / 'module/src/main/resources/schema.sql',
            'class': state.build / 'module/classes/A.class', 'test-class': state.build / 'module/test-classes/T.class',
            'compiled-resource': state.build / 'module/classes/schema.sql',
            'extra-class': state.build / 'module/classes/Injected.class'}[damage]
    path.write_bytes((path.read_bytes() if path.exists() else b'') + b' ')
    with pytest.raises(ValueError, match='changed before'):
        inner.require_java_reuse(state.build, state.output, state.sources, state.compiled)


def test_previous_surefire_xml_cannot_count_as_a_new_java_invocation(java_workspace):
    state = java_workspace; reports = state.build / 'module/surefire-reports'; reports.mkdir()
    stale = reports / 'TEST-org.example.PreviousTest.xml'; stale.write_bytes(b'<testsuite/>')
    with pytest.raises(ValueError, match='Previous Java reports'):
        inner.require_java_reuse(state.build, state.output, state.sources, state.compiled)
    assert stale.read_bytes() == b'<testsuite/>'


@pytest.mark.parametrize('where', ['source', 'compiled', 'reports'])
def test_shared_java_paths_cannot_follow_links_into_other_sources_or_reports(java_workspace, where):
    state = java_workspace; outside = state.root / 'outside'; outside.mkdir(); marker = outside / 'preserved.bin'; marker.write_bytes(b'keep')
    if where == 'source': target = state.root / 'module/src/redirected'
    elif where == 'compiled': target = state.build / 'module/classes/redirected'
    else: target = state.build / 'module/surefire-reports'
    target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        if where == 'reports': inner.clear_java_reports(state.build, state.output)
        else: inner.require_java_reuse(state.build, state.output, state.sources, state.compiled)
    assert marker.read_bytes() == b'keep' and target.is_symlink()


def assertion_group(state):
    names = ['org.example.OneTest', 'org.example.TwoTest']
    directory = state.build / 'module/surefire-reports'; directory.mkdir()
    raw = ('<testsuite><testcase classname="' + names[0] + '" name="first"/>'
        '<testcase classname="' + names[0] + '" name="business-assertion">'
        '<failure type="org.opentest4j.AssertionFailedError">expected 200, observed 500</failure></testcase>'
        '<testcase classname="' + names[1] + '" name="independent"/></testsuite>').encode()
    (directory / 'TEST-org.example.OneTest.xml').write_bytes(raw)
    catalog = inner.archive_java_reports(state.build, state.output / 'java', state.output)
    counts, classes = inner.java_report_counts(state.output, catalog, names)
    suite = {'id': 'suite-002', 'javaSelection': names, 'fixtureProperties': ['audited.fixture'], 'privateInputs': {}}
    (state.output / 'java-suite-002.log').write_bytes(b'Original Maven output: complete business assertion failure\n')
    entry = {**suite, 'status': 'FAILED', 'reportFiles': catalog, 'javaTests': counts, 'selectedJavaClasses': classes}
    profile = {'javaSuites': [{'className': name, 'minimumTests': minimum} for name, minimum in zip(names, (2, 1))]}
    return suite, entry, profile


def test_complete_assertions_preserve_failed_originals_and_release_only_previous_shared_reports(java_workspace):
    state = java_workspace; suite, entry, profile = assertion_group(state)
    original = {item['path']: (state.output / item['path']).read_bytes() for item in entry['reportFiles']}
    command = ['/fixed/mvn', 'test']; stopped = []
    def stop(actual):
        stopped.append(actual)
        return {'cleanup': {'status': 'STOPPED', 'remaining': []}, 'command': {'exitCode': 1}}
    assert inner.continue_native_assertions(suite, entry, profile, state.output, state.build, state.sources,
        state.compiled, command, inner.VerificationCommandFailure('java-suite-002', 1), stop) is False
    assert stopped == [command] and entry['status'] == 'FAILED'
    assert entry['failureKind'] == 'COMPLETE_ASSERTION_FAILURES' and entry['javaTests']['failed'] == 1
    assert original == {item['path']: (state.output / item['path']).read_bytes() for item in entry['reportFiles']}
    assert not list(state.build.glob('*/surefire-reports'))
    inner.require_java_reuse(state.build, state.output, state.sources, state.compiled)


@pytest.mark.parametrize('mutation', ['missing-report', 'tampered-bytes', 'under-minimum', 'skip', 'error',
    'non-assertion-failure', 'blank-case', 'omitted-class', 'wrong-counts', 'all-pass', 'foreign-class',
    'duplicate-report', 'duplicate-profile-class', 'global-error'])
def test_assertion_batching_refuses_incomplete_or_ambiguous_original_xml(java_workspace, mutation):
    state = java_workspace; _, entry, profile = assertion_group(state)
    reference = entry['reportFiles'][0]; path = state.output / reference['path']; raw = path.read_bytes()
    if mutation == 'missing-report': path.unlink()
    elif mutation == 'tampered-bytes': path.write_bytes(raw + b' ')
    elif mutation == 'under-minimum': profile['javaSuites'][0]['minimumTests'] = 3
    elif mutation == 'omitted-class': entry['javaSelection'].append('org.example.MissingTest')
    elif mutation == 'wrong-counts': entry['javaTests']['passed'] += 1
    elif mutation == 'duplicate-report': entry['reportFiles'].append(dict(reference))
    elif mutation == 'duplicate-profile-class': profile['javaSuites'].append(dict(profile['javaSuites'][0]))
    else:
        if mutation == 'skip': raw = raw.replace(b'name="first"/>', b'name="first"><skipped/></testcase>')
        elif mutation == 'error': raw = raw.replace(b'<failure ', b'<error ').replace(b'</failure>', b'</error>')
        elif mutation == 'non-assertion-failure': raw = raw.replace(b'org.opentest4j.AssertionFailedError', b'java.lang.RuntimeException')
        elif mutation == 'blank-case': raw = raw.replace(b'name="business-assertion"', b'name=""')
        elif mutation == 'all-pass': raw = re.sub(b'<failure[^>]*>.*?</failure>', b'', raw)
        elif mutation == 'foreign-class': raw = raw.replace(b'org.example.TwoTest', b'org.example.UnselectedTest')
        elif mutation == 'global-error': raw = raw.replace(b'<testsuite>', b'<testsuite errors="1"><error/>')
        path.write_bytes(raw); reference.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError): inner.require_complete_assertion_reports(state.output, entry, profile)


def assertion_runtime():
    command = ['/owned/tools/mvn', '-B', 'test', '-Dtest=org.example.OneTest']
    manifest = 'a' * 64
    stopped = {'status': 'STOPPED', 'remaining': [], 'manifestSha256': manifest}
    record = {'tool': 'mvn', 'argumentsSha256': hashlib.sha256(json.dumps(command[1:], ensure_ascii=True).encode()).hexdigest(),
        'status': 'EXITED', 'exitCode': 1, 'resourceLimitTriggered': False,
        'cleanup': {'removed': True, 'pid': 0, 'exitCode': 1}, 'mavenDependencyCache': {'status': 'READY'},
        'resourceMonitoring': {'capacityVerdict': 'CONTROLLED_MEASUREMENT', 'diskFloorBytes': 100,
            'memoryFloorBytes': 200, 'samples': 2, 'minimumDiskAvailableBytes': 1000, 'minimumMemoryAvailableBytes': 2000}}
    proof = {'manifestSha256': manifest, 'commands': [record]}
    runtime = SimpleNamespace(DISK_FLOOR=100, MEMORY_FLOOR=200, cleanup=lambda value: stopped,
                              evidence=lambda value, cleanup: proof)
    return command, manifest, stopped, record, proof, runtime


def test_assertion_batching_binds_the_real_oci_exit_cleanup_and_safety_observations():
    command, manifest, stopped, record, _, runtime = assertion_runtime()
    proof = inner.assertion_tool_cleanup(runtime, {'directory': '/owned/tools'}, manifest, command)
    assert proof == {'cleanup': stopped, 'command': record} and proof['command']['status'] == 'EXITED'


@pytest.mark.parametrize('mutation', ['unknown-exit', 'resource-limit', 'cache-unknown', 'not-removed', 'boolean-pid',
    'manifest-drift', 'duplicate-command', 'another-command', 'remaining-tool', 'disk-floor', 'memory-floor', 'boolean-samples'])
def test_assertion_batching_never_turns_executor_or_resource_failure_into_a_test_failure(mutation):
    command, manifest, stopped, record, proof, runtime = assertion_runtime()
    if mutation == 'unknown-exit': record['status'] = 'FAILED_OR_UNKNOWN'
    elif mutation == 'resource-limit': record['resourceLimitTriggered'] = True
    elif mutation == 'cache-unknown': record['mavenDependencyCache']['status'] = 'FAILED_OR_UNKNOWN'
    elif mutation == 'not-removed': record['cleanup']['removed'] = False
    elif mutation == 'boolean-pid': record['cleanup']['pid'] = False
    elif mutation == 'manifest-drift': proof['manifestSha256'] = 'b' * 64
    elif mutation == 'duplicate-command': proof['commands'].append(dict(record))
    elif mutation == 'another-command': record['argumentsSha256'] = 'b' * 64
    elif mutation == 'remaining-tool': stopped['remaining'].append('owned-but-running')
    elif mutation == 'disk-floor': record['resourceMonitoring']['minimumDiskAvailableBytes'] = 99
    elif mutation == 'memory-floor': record['resourceMonitoring']['minimumMemoryAvailableBytes'] = 199
    elif mutation == 'boolean-samples': record['resourceMonitoring']['samples'] = True
    with pytest.raises(ValueError): inner.assertion_tool_cleanup(runtime, {'directory': '/owned/tools'}, manifest, command)


@pytest.mark.parametrize('mutation', ['no-compiled-baseline', 'signal-exit', 'unknown-failure', 'wrong-command',
    'source-drift', 'compiled-drift', 'cleanup-unknown', 'private-input-drift'])
def test_assertion_batching_rechecks_inputs_and_compilation_before_advancing(java_workspace, mutation, monkeypatch):
    state = java_workspace; suite, entry, profile = assertion_group(state)
    compiled = state.compiled; error = inner.VerificationCommandFailure('java-suite-002', 1)
    def stop(_command): return {'cleanup': {'status': 'STOPPED', 'remaining': []}}
    if mutation == 'no-compiled-baseline': compiled = None
    elif mutation == 'signal-exit': error = inner.VerificationCommandFailure('java-suite-002', 137)
    elif mutation == 'unknown-failure': error = RuntimeError('executor admission failed')
    elif mutation == 'wrong-command': error = inner.VerificationCommandFailure('java-another-suite', 1)
    elif mutation == 'source-drift': (state.root / 'module/src/main/java/A.java').write_bytes(b'changed source')
    elif mutation == 'compiled-drift': (state.build / 'module/classes/A.class').write_bytes(b'changed compiled bytes')
    elif mutation == 'cleanup-unknown':
        def stop(_command): return {'cleanup': {'status': 'FAILED_OR_UNKNOWN', 'remaining': []}}
    elif mutation == 'private-input-drift':
        monkeypatch.setattr(inner, 'require_unchanged_inputs', lambda inputs: (_ for _ in ()).throw(ValueError('private input drift')))
    with pytest.raises((RuntimeError, ValueError)):
        inner.continue_native_assertions(suite, entry, profile, state.output, state.build, state.sources, compiled,
            ['/fixed/mvn', 'test'], error, stop)
    assert (state.build / 'module/surefire-reports').is_dir()
    assert (state.output / entry['reportFiles'][0]['path']).is_file()


@pytest.mark.parametrize('diagnostic', [b'java.lang.OutOfMemoryError', b'Java heap space', b'Could not reserve enough space',
    b'unable to create native thread', b'There was an error in the forked process', b'Process Exit Code: 137',
    b'The forked VM terminated without properly saying goodbye', b'A fatal error has been detected by the Java Runtime Environment'])
def test_http_assertion_cannot_hide_a_logged_jvm_or_fork_resource_failure(java_workspace, diagnostic):
    state = java_workspace; suite, entry, profile = assertion_group(state)
    (state.output / 'java-suite-002.log').write_bytes(diagnostic)
    calls = []
    with pytest.raises(ValueError, match='resource failure'):
        inner.continue_native_assertions(suite, entry, profile, state.output, state.build, state.sources, state.compiled,
            ['/fixed/mvn', 'test'], inner.VerificationCommandFailure('java-suite-002', 1), lambda command: calls.append(command))
    assert calls == [] and (state.build / 'module/surefire-reports').is_dir()


def test_verification_jvms_exit_on_real_heap_oom_before_a_servlet_can_mask_it_as_http_500():
    import ast
    tree = ast.parse((ROOT / 'script/jenkins/verify-ecs.py').read_text(encoding='utf8'))
    options = [keyword.value.value for node in ast.walk(tree) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
               and node.func.value.id == 'env' and node.func.attr == 'update'
               for keyword in node.keywords if keyword.arg == 'JAVA_TOOL_OPTIONS' and isinstance(keyword.value, ast.Constant)]
    assert len(options) == 1 and set(options[0].split()) == {
        '-Xmx1536m', '-XX:MaxMetaspaceSize=512m', '-XX:+ExitOnOutOfMemoryError'}


@pytest.mark.parametrize('damage', ['missing-log', 'changed-after-cleanup'])
def test_assertion_continuation_keeps_its_original_command_log_binding(java_workspace, damage):
    state = java_workspace; suite, entry, profile = assertion_group(state)
    path = state.output / 'java-suite-002.log'
    if damage == 'missing-log': path.unlink()
    def stop(_command):
        path.write_bytes(b'replaced command output')
        return {'cleanup': {'status': 'STOPPED', 'remaining': []}}
    with pytest.raises(ValueError):
        inner.continue_native_assertions(suite, entry, profile, state.output, state.build, state.sources, state.compiled,
            ['/fixed/mvn', 'test'], inner.VerificationCommandFailure('java-suite-002', 1), stop)
    assert (state.build / 'module/surefire-reports').is_dir()


@pytest.mark.parametrize('mode', ['all-pass', 'assertions', 'unsafe-abort', 'unknown-outcome'])
def test_independent_native_groups_collect_only_safe_assertions_and_block_all_later_stages(mode):
    suites = [{'id': 'one'}, {'id': 'two'}, {'id': 'three'}]; visited = []; receipt = {}
    def run(suite):
        visited.append(suite['id'])
        if suite['id'] == 'two':
            if mode == 'unsafe-abort': raise ValueError('unsafe resource or input state')
            if mode == 'assertions': return False
            if mode == 'unknown-outcome': return None
        return True
    if mode == 'all-pass':
        inner.run_native_java_groups(suites, run, receipt); visited.append('later-source-python-migration')
        assert visited == ['one', 'two', 'three', 'later-source-python-migration']
        assert 'nativeAssertionFailures' not in receipt
    else:
        with pytest.raises((RuntimeError, ValueError)):
            inner.run_native_java_groups(suites, run, receipt); visited.append('later-source-python-migration')
        assert visited == (['one', 'two', 'three'] if mode == 'assertions' else ['one', 'two'])
        assert receipt.get('nativeAssertionFailures') == (['two'] if mode == 'assertions' else None)


def preparation_transport_source():
    source = (ROOT / 'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    begin = source.index('        $prepareCommand = ')
    end = source.index('        $prepared | ConvertTo-Json -Depth 12', begin)
    return source[begin:end]


def test_preparation_disconnect_recovers_only_by_reading_the_same_fixed_command():
    source = preparation_transport_source()
    assert '$prepareCommand = "python3 -B \'$remoteInbox/prepare-ecs-tools.py\' $prepareArguments"' in source
    gate = source.index('if ($prepareExit -eq 255)')
    loop = source.index('for ($prepareReadback = 1; $prepareReadback -le 3; $prepareReadback++)')
    terminal = source.index('if (-not $prepareRecovered)', loop)
    assert source.index("& 'ssh.exe' @prepareSshArguments") < gate < loop
    readback = source[loop:terminal]
    assert "& 'ssh.exe'" not in readback
    assert readback.count("[Diagnostics.ProcessStartInfo]::new('ssh.exe')") == 1
    assert '$prepareReadArguments = $sshOptions + @' in readback
    assert '$prepareReadProcess.StartInfo.ArgumentList.Add([string]$prepareReadArgument)' in readback
    assert '"$prepareCommand --read-prepared"' in readback
    assert 'prepare-ecs-tools.py' not in readback and 'Invoke-Checked' not in readback
    assert 'elseif ($prepareExit -ne 0)' in source[terminal:]
    assert 'throw "ssh.exe failed with exit $prepareExit"' in source[terminal:]


def test_preparation_readback_has_bounded_wait_and_stops_on_semantic_failure():
    source = preparation_transport_source()
    assert 'maximumReadbacks=3; recoveryWindowSeconds=180; readbackIntervalSeconds=60' in source
    assert '[Diagnostics.Stopwatch]::StartNew()' in source
    assert '[Math]::Min(60, [Math]::Max(0, 180 - $prepareRecoveryTimer.Elapsed.TotalSeconds))' in source
    assert "if ($prepareRecoveryTimer.Elapsed.TotalSeconds -ge 180) { $prepareTransport.failureReason = 'DEADLINE_EXCEEDED'; break }" in source
    assert source.index("failureReason = 'DEADLINE_EXCEEDED'; break") < source.index('$prepareReadProcess.Start()')
    assert 'if ($prepareReadExit -eq 0) { $prepareOutput = $prepareReadOut; $prepareRecovered = $true; break }' in source
    assert 'if ($prepareReadExit -notin @(75, 255)) { throw ' in source
    assert 'if (-not $prepareRecovered) { throw ' in source


def test_preparation_transport_retains_actual_exits_hashes_and_source_validation():
    source = preparation_transport_source()
    assert re.search(r"& 'ssh.exe' @prepareSshArguments 1> \$prepareFirstOut 2> \$prepareFirstErr\s+"
                     r'\$prepareExit = \$LASTEXITCODE', source)
    assert '$prepareReadExit = $prepareReadProcess.ExitCode' in source
    assert 'originalExitCode = $prepareExit' in source
    assert 'attempt=$prepareReadback; exitCode=$prepareReadExit; outcome=$prepareReadOutcome' in source
    assert '$prepareReadOutSha = (Get-FileHash -LiteralPath $prepareReadOut -Algorithm SHA256)' in source
    assert '$prepareReadErrSha = (Get-FileHash -LiteralPath $prepareReadErr -Algorithm SHA256)' in source
    assert 'stdoutFile=$prepareReadOut; stdoutSha256=$prepareReadOutSha' in source
    assert 'stderrFile=$prepareReadErr; stderrSha256=$prepareReadErrSha' in source
    assert "} finally {" in source and 'artifacts/ecs-tool-preparation-transport.json' in source
    assert "'Sha256'] = (Get-FileHash -LiteralPath $prepareStream[1] -Algorithm SHA256)" in source
    assert 'release=$tag; commit=$commit; sourceSha256=$sha' in source
    assert 'instanceId=$instance; machineId=$machine; prepareCandidateBuilder=' in source
    success = source.index('$prepareTransport.transportRecovered = $prepareRecovered')
    assert source.index("throw 'ECS tool image preparation did not return matching source evidence.'") < success
    assert source.index("throw 'Prepared ECS tools require immutable image IDs.'") < success
    assert source.index("throw 'Candidate BuildKit was not automatically prepared for this fixed attempt.'") < success


def test_preparation_reader_enforces_the_remaining_deadline_on_the_local_ssh_process():
    source = preparation_transport_source()
    assert 'StartInfo.UseShellExecute = $false' in source and 'StartInfo.CreateNoWindow = $true' in source
    assert 'StandardOutput.BaseStream.CopyToAsync($prepareReadOutStream)' in source
    assert 'StandardError.BaseStream.CopyToAsync($prepareReadErrStream)' in source
    remaining = '[Math]::Floor((180 - $prepareRecoveryTimer.Elapsed.TotalSeconds) * 1000)'
    assert source.count(remaining) == 2
    assert '$prepareReadProcess.WaitForExit($prepareReadRemaining)' in source
    assert '[Threading.Tasks.Task]::WaitAll($prepareReadCopies, $prepareReadRemaining)' in source
    assert '$prepareReadProcess.Kill($true)' in source and '$prepareReadProcess.WaitForExit(1000)' in source
    assert '$prepareReadDeadline = $prepareReadDeadline -or $prepareRecoveryTimer.Elapsed.TotalSeconds -ge 180' in source
    assert "if ($prepareReadDeadline) { 'DEADLINE_EXCEEDED' }" in source
    deadline_gate = source.index('if ($prepareReadDeadline -or $prepareRecoveryTimer.Elapsed.TotalSeconds -ge 180)')
    success_gate = source.index('if ($prepareReadExit -eq 0)')
    assert deadline_gate < success_gate
    assert "failureReason = 'DEADLINE_EXCEEDED'" in source[deadline_gate:success_gate]


def test_old_owned_staging_parent_is_private_without_reclaiming_an_attempt(tmp_path):
    parent = tmp_path / 'verification'
    parent.mkdir(mode=0o775)
    os.chmod(parent, 0o775)
    args = SimpleNamespace(tag='ci-57-' + 'a' * 12, scope='source',
                           attempt='b' * 32, commit='a' * 40, source_sha256='c' * 64)
    previous_umask = os.umask(0o002)
    try:
        attempt, checkout = remote.prepare_checkout(tmp_path, args, {'instanceId': 'i-fixture'})
    finally:
        os.umask(previous_umask)
    assert stat.S_IMODE(parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(checkout.stat().st_mode) == 0o700
    assert stat.S_IMODE((checkout / 'work').stat().st_mode) == 0o700
    claim = (attempt / '.verification-claimed/claim.json').read_bytes()
    with pytest.raises(remote.VerificationError, match='already has a verification directory'):
        remote.prepare_checkout(tmp_path, args, {'instanceId': 'i-fixture'})
    assert (attempt / '.verification-claimed/claim.json').read_bytes() == claim


def test_staging_parent_link_does_not_change_another_directory_permissions(tmp_path):
    outside = tmp_path / 'other'
    outside.mkdir(mode=0o755)
    before = stat.S_IMODE(outside.stat().st_mode)
    (tmp_path / 'verification').symlink_to(outside, target_is_directory=True)
    with pytest.raises(remote.VerificationError, match='cannot be a link'):
        remote.prepare_checkout(tmp_path, SimpleNamespace(), {})
    assert stat.S_IMODE(outside.stat().st_mode) == before


@pytest.mark.parametrize('interrupt', [False, True])
def test_verifier_creates_private_reports_and_restores_login_umask(tmp_path, interrupt):
    previous = os.umask(0o002)
    try:
        try:
            with inner.private_process_umask():
                directory = tmp_path / 'java' / 'module' / 'surefire-reports'
                directory.mkdir(parents=True)
                (directory / 'native.log').write_bytes(b'original report bytes')
                child = subprocess.run([sys.executable, '-B', '-c',
                    'import sys;from pathlib import Path;Path(sys.argv[1]).write_bytes(b"original child bytes")',
                    str(directory / 'child.xml')], stdin=subprocess.DEVNULL, capture_output=True)
                assert child.returncode == 0
                if interrupt:
                    raise RuntimeError('synthetic verifier interruption')
        except RuntimeError:
            assert interrupt
        observed = os.umask(0o002)
        assert observed == 0o002
        for path in (tmp_path / 'java', tmp_path / 'java/module', directory):
            assert stat.S_IMODE(path.stat().st_mode) == 0o700
        for name in ('native.log', 'child.xml'):
            assert stat.S_IMODE((directory / name).stat().st_mode) == 0o600
        assert (directory / 'native.log').read_bytes() == b'original report bytes'
        assert (directory / 'child.xml').read_bytes() == b'original child bytes'
    finally:
        os.umask(previous)


def report(root, class_name, *, prefix='java', skipped=False):
    name = prefix + '/module/surefire-reports/TEST-' + class_name + '.xml'
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = ('<?xml version="1.0"?>\r\n<testsuite name="' + class_name + '"><testcase classname="'
           + class_name + '" name="actual">' + ('<skipped/>' if skipped else '') + '</testcase></testsuite>\r\n').encode()
    path.write_bytes(raw)
    return {'path': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def fixture(root):
    suites, counts, selected, references = [], dict(found=0, passed=0, failed=0, skipped=0), {}, []
    for number, name in enumerate(('org.example.OneTest', 'org.example.TwoTest'), 1):
        reference = report(root, name)
        tally = dict(found=1, passed=1, failed=0, skipped=0)
        suites.append({'id': 'suite-' + str(number).zfill(3), 'status': 'PASS', 'javaSelection': [name],
                       'fixtureProperties': ['audited.fixture.config'], 'javaTests': dict(tally),
                       'selectedJavaClasses': {name: dict(tally)}, 'reportFiles': [reference]})
        selected[name] = dict(tally); references.append(reference)
        counts['found'] += 1; counts['passed'] += 1
    return {'javaSuites': suites, 'javaTests': counts, 'selectedJavaClasses': selected, 'javaReportFiles': references}


def test_v2_evidence_counts_every_independent_original_xml(tmp_path):
    result = fixture(tmp_path)
    before = {(tmp_path / item['path']).read_bytes() for item in result['javaReportFiles']}
    remote.validate_java_suites(result, tmp_path, mysql=True)
    assert before == {(tmp_path / item['path']).read_bytes() for item in result['javaReportFiles']}


def test_a_suite_pass_flag_cannot_replace_its_skipped_xml(tmp_path):
    result = fixture(tmp_path)
    reference = report(tmp_path, 'org.example.TwoTest', skipped=True)
    result['javaSuites'][1]['reportFiles'] = [reference]
    result['javaReportFiles'][1] = reference
    with pytest.raises(remote.VerificationError, match='count differs'):
        remote.validate_java_suites(result, tmp_path, mysql=True)


def test_one_original_report_cannot_be_attributed_to_two_invocations(tmp_path):
    result = fixture(tmp_path)
    result['javaSuites'][1] = copy.deepcopy(result['javaSuites'][0])
    result['javaSuites'][1]['id'] = 'suite-002'
    with pytest.raises(remote.VerificationError, match='repeat between invocations'):
        remote.validate_java_suites(result, tmp_path, mysql=True)


def test_original_report_tampering_is_detected_before_acceptance(tmp_path):
    result = fixture(tmp_path)
    path = tmp_path / result['javaReportFiles'][0]['path']
    path.write_bytes(path.read_bytes().replace(b'actual', b'edited'))
    with pytest.raises(remote.VerificationError, match='XML bytes differ'):
        remote.validate_java_suites(result, tmp_path, mysql=True)


def test_source_regression_has_a_separate_original_xml_namespace(tmp_path):
    result = fixture(tmp_path)
    name = 'org.example.OneTest'
    reference = report(tmp_path, name, prefix='source-regression/java')
    tally = dict(found=1, passed=1, failed=0, skipped=0)
    result['sourceRegression'] = {'id': 'source-regression', 'status': 'PASS', 'fixtureProperties': [],
        'javaSelection': [name], 'javaTests': tally, 'selectedJavaClasses': {name: tally}, 'reportFiles': [reference]}
    remote.validate_java_suites(result, tmp_path, mysql=True)
    result['sourceRegression']['reportFiles'] = result['javaSuites'][0]['reportFiles']
    with pytest.raises(remote.VerificationError, match='independently owned suite archive'):
        remote.validate_java_suites(result, tmp_path, mysql=True)


@pytest.mark.parametrize('name', ['reports/java-suite-001.log', 'reports/java-source-regression.log',
    'reports/source-regression/java/module/surefire-reports/TEST-org.example.OneTest.xml'])
def test_only_fixed_suite_logs_and_original_xml_are_collectable(name):
    assert remote.allowed_evidence(name)


@pytest.mark.parametrize('name', ['reports/java-suite-password.log', 'reports/java-suites/suite-001/mysql-config.json',
    'reports/source-regression/build/module/surefire-reports/TEST-Example.xml', 'reports/java-suite-001.log/secret',
    'reports/source-regression/java/module/../private.json'])
def test_private_suite_inputs_and_build_output_never_enter_archive(name):
    assert not remote.allowed_evidence(name)


def test_tap_requires_real_complete_test_counts(tmp_path):
    path = tmp_path / 'frontend.log'
    path.write_text('TAP version 13\n# tests 3\n# pass 3\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n')
    assert inner.node_tap_counts(path) == {'found': 3, 'passed': 3, 'failed': 0, 'skipped': 0}
    path.write_text('# tests 0\n# pass 0\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n')
    with pytest.raises(ValueError, match='empty or inconsistent'):inner.node_tap_counts(path)
    path.write_text('build finished successfully\n')
    with pytest.raises(ValueError, match='one complete final testcase tally'):inner.node_tap_counts(path)


def collector_archive(root, representation='crlf', mutation=None):
    archive = root / 'verification-evidence.tar.gz'
    output = root / 'artifacts/ecs/evidence'
    args = SimpleNamespace(archive=str(archive), output=str(output), tag='ci-90-' + 'a' * 12,
        attempt='b' * 32, commit='a' * 40, source_sha256='c' * 64, scope='source',
        instance_id='i-fixture123', machine_id='d' * 32)
    report_name = 'reports/java/module/surefire-reports/TEST-org.example.OneTest.xml'
    report_bytes = b'<?xml version="1.0"?>\r\n<testsuite><testcase name="original"/></testsuite>\r\n'
    record = {'schema': 1, 'kind': 'doorhandle-ecs-ci', 'release': args.tag, 'attempt': args.attempt,
        'commit': args.commit, 'sourceSha256': args.source_sha256, 'scope': args.scope,
        'identity': {'instanceId': args.instance_id, 'machineId': args.machine_id, 'executionLocation': 'ECS'},
        'status': 'PASS', 'verificationExitCode': 0, 'lifecycle': 'managed-outside-jenkins',
        'finishedAt': '2026-11-08T00:00:00+00:00',
        'reportFiles': [{'path': report_name, 'bytes': len(report_bytes), 'sha256': hashlib.sha256(report_bytes).hexdigest()}]}
    if representation == 'crlf':
        receipt_bytes = (json.dumps(record, sort_keys=True, indent='\t').replace('\n', '\r\n') + '\r\n').encode()
    else:
        receipt_bytes = (json.dumps(record, sort_keys=True, separators=(', ', ' : ')) + '\n').encode()
    if mutation == 'oversize-receipt':
        receipt_bytes += b' ' * (remote.MAX_RECEIPT_BYTES + 1 - len(receipt_bytes))
    members = [('verification-receipt.json', receipt_bytes), (report_name, report_bytes)]
    if mutation == 'duplicate': members.append(members[0])
    if mutation == 'unlisted': members.append(('reports/private.env', b'not admitted'))
    with tarfile.open(archive, 'w:gz') as package:
        for name, raw in members:
            entry = tarfile.TarInfo(name); entry.size = len(raw)
            package.addfile(entry, io.BytesIO(raw))
    return args, record, receipt_bytes, report_name, report_bytes


@pytest.mark.parametrize('representation', ['crlf', 'spaced-lf'])
def test_collector_preserves_original_receipt_bytes_and_their_custody_sha(tmp_path, monkeypatch, representation):
    args, record, receipt_bytes, report_name, report_bytes = collector_archive(tmp_path, representation)
    monkeypatch.chdir(tmp_path)
    assert remote.collect(args) == 0
    output = Path(args.output); receipt_file = output / 'verification-receipt.json'
    assert receipt_file.read_bytes() == receipt_bytes
    assert json.loads(receipt_file.read_bytes()) == record
    assert stat.S_IMODE(receipt_file.stat().st_mode) == 0o600
    assert (output / report_name).read_bytes() == report_bytes
    assert {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()} == {
        'verification-receipt.json', report_name}
    archive_bytes = Path(args.archive).read_bytes()
    archive_proof = {'bytes': len(archive_bytes), 'sha256': hashlib.sha256(archive_bytes).hexdigest()}
    retained_archive = output / 'verification-evidence.tar.gz'
    retained_archive.write_bytes(archive_bytes); retained_archive.chmod(0o600)
    cleanup.write_json(output / 'preservation.json', {'kind': 'doorhandle-retained-original-ci-evidence',
        'files': [{'path': 'verification-receipt.json', 'bytes': len(receipt_bytes),
                   'sha256': hashlib.sha256(receipt_bytes).hexdigest()}, *record['reportFiles']],
        'testsExecutedLocally': False, 'originalEvidenceArchive': archive_proof})
    custody = cleanup.local_custody(output, remote)
    assert custody['verificationReceiptSha256'] == hashlib.sha256(receipt_bytes).hexdigest()
    assert custody['originalEvidenceArchive'] == archive_proof
    with tarfile.open(args.archive, 'r:gz') as package:
        assert package.extractfile('verification-receipt.json').read() == receipt_file.read_bytes()


@pytest.mark.parametrize('mutation,message', [
    ('duplicate', 'Non-regular or duplicate evidence entry'),
    ('unlisted', 'Unlisted evidence archive entry'),
    ('oversize-receipt', 'bounded verification receipt')])
def test_collector_keeps_the_closed_member_set_and_receipt_bound(tmp_path, monkeypatch, mutation, message):
    args, _, _, _, _ = collector_archive(tmp_path, mutation=mutation)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(remote.VerificationError, match=message): remote.collect(args)


@pytest.mark.parametrize('kind', ['native-single', 'native-multi', 'source-regression'])
def test_only_grouped_native_commands_fork_a_fresh_serial_jvm_for_each_class(tmp_path, kind):
    source = kind == 'source-regression'
    selected = ['org.example.OneTest', 'org.example.TwoTest'] if kind != 'native-single' else ['org.example.OneTest']
    suite = {'javaSelection': selected, 'fixtureProperties': [] if source else ['one.fixture'],
             'fixtureOptions': [] if source else ['-Done.fixture=/owned/one.json']}
    arguments = inner.java_maven_arguments(suite, {'MAVEN_CMD': '/fixed/mvn'}, tmp_path,
                                           initial=False, source_regression=source)
    isolation = ['-DforkCount=1', '-DreuseForks=false', '-Djunit.jupiter.execution.parallel.enabled=false']
    assert all((argument in arguments) is (kind == 'native-multi') for argument in isolation)
    assert 'clean' not in arguments and ('verify' in arguments) is source and ('test' in arguments) is not source
    assert not any('skipTests' in argument or argument == '-T' for argument in arguments)
    if not source: assert '-Dtest=' + ','.join(selected) in arguments


def grouped_mysql_evidence(root):
    names = ['org.example.OneTest', 'org.example.TwoTest', 'org.example.ThreeTest']
    references = [report(root, name) for name in names]
    count = lambda number: dict(found=number, passed=number, failed=0, skipped=0)
    requirements = [{'className': name, 'minimumTests': 1, 'fixtureProperties': ['fixture.' + str(index)]}
                    for index, name in enumerate(names)]
    suites = []
    for ordinal, indexes in enumerate(((0, 1), (2,)), 1):
        suites.append({'id': 'suite-' + str(ordinal).zfill(3), 'status': 'PASS',
            'javaSelection': [names[index] for index in indexes],
            'fixtureProperties': [requirements[index]['fixtureProperties'][0] for index in indexes],
            'javaTests': count(len(indexes)), 'selectedJavaClasses': {names[index]: count(1) for index in indexes},
            'reportFiles': [references[index] for index in indexes]})
    result = {'javaSuites': suites, 'javaTests': count(3), 'javaReportFiles': references,
              'selectedJavaClasses': {name: count(1) for name in names}}
    return result, {'javaSuites': requirements}, {'reports/' + item['path']: item for item in references}


def test_grouped_mysql_coverage_still_counts_each_profile_class_from_its_original_xml(tmp_path):
    coverage = module('grouped_native_profile_coverage', 'compact-acceptance.py')
    result, profile, catalog = grouped_mysql_evidence(tmp_path)
    original = {item['path']: (tmp_path / item['path']).read_bytes() for item in result['javaReportFiles']}
    assert coverage.validate_mysql_suites(result, profile, tmp_path, catalog) == 3
    remote.validate_java_suites(result, tmp_path, mysql=True)
    assert original == {item['path']: (tmp_path / item['path']).read_bytes() for item in result['javaReportFiles']}


@pytest.mark.parametrize('mutation', ['omitted-class', 'repeated-class', 'unknown-class', 'missing-property',
    'extra-property', 'repeated-property', 'profile-property-collision', 'under-minimum', 'skipped', 'failed',
    'extra-xml-class', 'reused-report', 'wrong-class-tally', 'wrong-total', 'top-repeated-report', 'top-class-tally'])
def test_grouping_cannot_weaken_profile_counts_scope_or_original_xml_checks(tmp_path, mutation):
    coverage = module('grouped_native_profile_refusals', 'compact-acceptance.py')
    result, profile, catalog = grouped_mysql_evidence(tmp_path)
    first, second = result['javaSuites']
    if mutation == 'omitted-class': result['javaSuites'].pop()
    elif mutation == 'repeated-class': second['javaSelection'] = first['javaSelection'][:1]
    elif mutation == 'unknown-class': first['javaSelection'].append('org.example.UnreviewedTest')
    elif mutation == 'missing-property': first['fixtureProperties'].pop()
    elif mutation == 'extra-property': first['fixtureProperties'].append('unreviewed.fixture')
    elif mutation == 'repeated-property': first['fixtureProperties'].append(first['fixtureProperties'][0])
    elif mutation == 'profile-property-collision': profile['javaSuites'][1]['fixtureProperties'] = profile['javaSuites'][0]['fixtureProperties'][:]
    elif mutation == 'under-minimum': profile['javaSuites'][0]['minimumTests'] = 2
    elif mutation == 'reused-report': second['reportFiles'].append(first['reportFiles'][0])
    elif mutation == 'wrong-class-tally': first['selectedJavaClasses'][first['javaSelection'][0]].update(found=2, passed=2)
    elif mutation == 'wrong-total': result['javaTests'].update(found=4, passed=4)
    elif mutation == 'top-repeated-report': result['javaReportFiles'].append(result['javaReportFiles'][0])
    elif mutation == 'top-class-tally': result['selectedJavaClasses'][first['javaSelection'][0]].update(found=2, passed=2)
    else:
        reference = first['reportFiles'][0]; path = tmp_path / reference['path']
        raw = path.read_bytes()
        if mutation == 'extra-xml-class':
            raw = raw.replace(b'</testsuite>', b'<testcase classname="org.example.UnselectedTest" name="extra"/></testsuite>')
            first['javaTests'].update(found=3, passed=3); result['javaTests'].update(found=4, passed=4)
        else:
            raw = raw.replace(b'name="actual">', b'name="actual"><' + (b'skipped' if mutation == 'skipped' else b'failure') + b'/>')
        path.write_bytes(raw)
        reference.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError): coverage.validate_mysql_suites(result, profile, tmp_path, catalog)
