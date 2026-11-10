"""Evidence and held-file guards for retiring one failed native JAR copy.

All files and control documents here are synthetic. Tests run only through
Jenkins on ECS; local AST parsing does not execute the retirement helper.
"""
import copy
import ast
from contextlib import contextmanager
import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import re
import tarfile
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest


MODULE = Path(__file__).resolve().parents[1] / 'script/jenkins/retire-failed-native-jar-duplicates.py'
SPEC = importlib.util.spec_from_file_location('failed_native_jar_retirement_tests', MODULE)
retirer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = retirer
SPEC.loader.exec_module(retirer)

CI_ROOT = '/home/ecs-user/doorhandle-ci'


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf8')


def sha(value):
    return hashlib.sha256(value).hexdigest()


def flow_xml(context, *, result='FAILURE', completed='true', done='true'):
    root = ET.Element('flow-build', {'plugin': 'workflow-job@fixture'})
    parameters = ET.SubElement(ET.SubElement(ET.SubElement(root, 'actions'), 'hudson.model.ParametersAction'), 'parameters')
    for name, value in [('ACTION', 'verify-runtime'), ('DOORHANDLE_CI_SCOPE', 'mysql'),
                        ('TRUSTED_COMMIT', context['commit']), ('PRODUCTION_RELEASE_ENABLED', 'false'),
                        ('DOORHANDLE_CI_AUTO_COMPACT_FIXTURES', 'true')]:
        tag = 'hudson.model.BooleanParameterValue' if name.startswith(('PRODUCTION_', 'DOORHANDLE_CI_AUTO_')) else 'hudson.model.StringParameterValue'
        item = ET.SubElement(parameters, tag)
        ET.SubElement(item, 'name').text = name
        ET.SubElement(item, 'value').text = value
    ET.SubElement(root, 'result').text = result
    ET.SubElement(root, 'completed').text = completed
    execution = ET.SubElement(root, 'execution', {'class': 'org.jenkinsci.plugins.workflow.cps.CpsFlowExecution'})
    ET.SubElement(execution, 'done').text = done
    # Actual persisted Jenkins flow-build originals use this declaration.
    return b"<?xml version='1.1' encoding='UTF-8'?>\n" + ET.tostring(root, encoding='utf-8', xml_declaration=False)


@pytest.fixture
def bundle():
    context = {'release': 'ci-143-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}
    identity = {'instanceId': 'i-2zeieuov2aum486jm1ek', 'machineId': '1ebe8f77e3104ab6a49a9386e38abd20',
                'executionLocation': 'ECS'}
    jar = b'synthetic reviewed candidate jar\x00\xff\n'
    work = CI_ROOT + '/verification/' + context['release'] + '/checkout/work/compact-fixtures'
    values = {
        'release': {**context, 'applicationJarSha256': sha(jar), 'localBuildReceiptSha256': 'c' * 64},
        'artifactPlan': {'schema': 1, 'kind': 'doorhandle-compact-fixture-artifacts', **context,
                         'applicationJarSha256': sha(jar), 'applicationJarBytes': len(jar)},
        'fixtureOwner': {'schemaVersion': 1, 'kind': 'doorhandle-compact-fixture-owner', **context,
                         'identity': identity, 'phase': 'OWNED_SERVER_STOPPED', 'token': '0123456789',
                         'work': work, 'sourceContainerId': 'd' * 64, 'containerId': 'e' * 64},
        'fixtureCleanup': {'schemaVersion': 1, 'kind': 'doorhandle-compact-fixture-cleanup', **context,
                           'identity': identity, 'status': 'STOPPED', 'errors': [], 'containerId': 'e' * 64,
                           'sourceContainerUntouched': 'd' * 64, 'dataDirectoryRetained': work + '/data',
                           'sourceDumpAndEvidenceRetained': True},
    }
    return SimpleNamespace(context=context, identity=identity, values=values, xml=flow_xml(context), jar=jar)


def documents(bundle):
    return {'buildXml': bundle.xml, **{key: encoded(value) for key, value in bundle.values.items()}}


def validate(bundle):
    return retirer.validate_control_documents(documents(bundle), bundle.context, bundle.identity)


@pytest.mark.parametrize(('present', 'flag'), [(False, None), (True, True), (True, False),
    (True, 1), (True, 'true'), (True, None)],
    ids=['legacy-absent', 'bool-true', 'bool-false', 'integer', 'string', 'null'])
def test_authenticated_owner_projection_preserves_only_original_nonsecret_binlog_fact(bundle, monkeypatch, present, flag):
    owner = bundle.values['fixtureOwner']
    owner['rootPassword'] = 'synthetic-private-password'
    owner['unreviewedPrivateField'] = {'secret': 'synthetic-private-payload'}
    if present:
        owner['binaryLoggingDisabled'] = flag
    raw_docs = documents(bundle)
    current = {'release': 'ci-200-' + 'f' * 12, 'commit': 'f' * 40, 'sourceSha256': 'e' * 64}
    paths = retirer.expected_control_paths(current['release'], bundle.context['release'])
    originals = {str(Path(CI_ROOT) / paths[role]): raw for role, raw in raw_docs.items()}
    controls = {role: {'path': paths[role], 'bytes': len(raw), 'sha256': sha(raw)}
                for role, raw in raw_docs.items()}

    class ExistingControlPath(type(Path())):
        def exists(self): return str(self) in originals
        def is_symlink(self): return False

    @contextmanager
    def held_control(root, path, maximum):
        assert str(root) == CI_ROOT
        raw = originals[str(path)]
        assert len(raw) <= maximum
        with io.BytesIO(raw) as stream:
            yield stream, [1, 2, stat.S_IFREG | 0o600, 1000, 1000, 1, len(raw), 0, 0, len(raw)]

    source_calls = []
    def source_proof(root, tag, commit, source_sha, *, builder_helpers=False):
        assert str(root) == CI_ROOT and tag == bundle.context['release']
        assert commit == bundle.context['commit'] and source_sha == bundle.context['sourceSha256']
        source_calls.append(builder_helpers)
        return {'sha256': source_sha}

    monkeypatch.setattr(retirer, 'Path', ExistingControlPath)
    monkeypatch.setattr(retirer, 'held_file', held_control)
    monkeypatch.setattr(retirer, 'source_proof', source_proof)
    result = retirer.admit_historical_controls(CI_ROOT, {'current': current, 'identity': bundle.identity},
        {**bundle.context, 'controls': controls}, builder_helpers=True)
    assert source_calls == [True]
    projected = result['fixtureOwner']
    assert ('binaryLoggingDisabled' in projected) is present
    if present:
        assert type(projected['binaryLoggingDisabled']) is type(flag)
        assert projected['binaryLoggingDisabled'] == flag
    assert 'rootPassword' not in projected and 'unreviewedPrivateField' not in projected
    public = encoded(result)
    assert b'synthetic-private-password' not in public and b'synthetic-private-payload' not in public
    assert result['controls']['fixtureOwner']['sha256'] == sha(raw_docs['fixtureOwner'])


@pytest.mark.parametrize('result', ['FAILURE', 'ABORTED'])
def test_real_jenkins_terminal_failure_is_valid_without_a_local_build_copy(bundle, result):
    bundle.xml = flow_xml(bundle.context, result=result)
    assert 'localBuild' not in documents(bundle)
    assert isinstance(validate(bundle), dict)


def test_equal_jar_digest_and_valid_controls_do_not_perform_file_or_process_operations(bundle, monkeypatch):
    frozen = copy.deepcopy(bundle.values)
    def refuse(*_args, **_kwargs):
        pytest.fail('Pure evidence validation must not inspect or retire filesystem objects')
    class EvidencePath(type(Path())):
        open = read_bytes = stat = unlink = rename = refuse
    # Patch only this module's aliases. Pytest still needs pathlib and os to
    # render a regression failure and write its original report.
    monkeypatch.setattr(retirer, 'Path', EvidencePath)
    monkeypatch.setattr(retirer, 'os', SimpleNamespace(open=refuse, stat=refuse, unlink=refuse, remove=refuse))
    monkeypatch.setattr(retirer, 'subprocess', SimpleNamespace(run=refuse, Popen=refuse))
    assert isinstance(validate(bundle), dict)
    assert bundle.values == frozen


@pytest.mark.parametrize('result', ['SUCCESS', 'UNSTABLE', 'NOT_BUILT', 'BUILDING', '', None])
def test_success_or_nonfailure_terminal_state_is_never_retirement_evidence(bundle, result):
    bundle.xml = flow_xml(bundle.context, result=result)
    with pytest.raises(retirer.RetirementError):
        validate(bundle)


@pytest.mark.parametrize(('completed', 'done'), [('false', 'true'), ('true', 'false'), ('', 'true'), ('true', '')])
def test_result_without_both_actual_completion_flags_is_refused(bundle, completed, done):
    bundle.xml = flow_xml(bundle.context, completed=completed, done=done)
    with pytest.raises(retirer.RetirementError):
        validate(bundle)


@pytest.mark.parametrize(('name', 'value'), [('ACTION', 'verify'), ('ACTION', 'compact-cutover'),
    ('DOORHANDLE_CI_SCOPE', 'source'), ('TRUSTED_COMMIT', 'f' * 40), ('PRODUCTION_RELEASE_ENABLED', 'true')])
def test_failed_build_must_be_this_unpublished_mysql_runtime_attempt(bundle, name, value):
    xml = ET.fromstring(bundle.xml)
    parameter = next(item for item in xml.findall('./actions/hudson.model.ParametersAction/parameters/*')
                     if item.findtext('name') == name)
    parameter.find('value').text = value
    bundle.xml = ET.tostring(xml)
    with pytest.raises(retirer.RetirementError):
        validate(bundle)


def test_conflicting_duplicate_jenkins_parameters_are_rejected(bundle):
    xml = ET.fromstring(bundle.xml)
    parameters = xml.find('./actions/hudson.model.ParametersAction/parameters')
    duplicate = ET.SubElement(parameters, 'hudson.model.StringParameterValue')
    ET.SubElement(duplicate, 'name').text = 'ACTION'
    ET.SubElement(duplicate, 'value').text = 'verify'
    bundle.xml = ET.tostring(xml)
    with pytest.raises(retirer.RetirementError):
        validate(bundle)


@pytest.mark.parametrize('role', ['buildXml', 'release', 'artifactPlan', 'fixtureOwner', 'fixtureCleanup'])
def test_all_original_control_roles_are_required(bundle, role):
    raw = documents(bundle); raw.pop(role)
    with pytest.raises(retirer.RetirementError):
        retirer.validate_control_documents(raw, bundle.context, bundle.identity)


@pytest.mark.parametrize('role', ['release', 'artifactPlan', 'fixtureOwner', 'fixtureCleanup'])
@pytest.mark.parametrize('field', ['release', 'commit', 'sourceSha256'])
def test_each_control_document_is_bound_to_the_exact_failed_attempt(bundle, role, field):
    bundle.values[role][field] = {'release': 'ci-144-' + 'a' * 12, 'commit': 'f' * 40, 'sourceSha256': 'f' * 64}[field]
    with pytest.raises(retirer.RetirementError):
        validate(bundle)


@pytest.mark.parametrize('role', ['release', 'artifactPlan'])
def test_jar_digest_mismatch_is_refused_before_any_file_eligibility(bundle, role):
    bundle.values[role]['applicationJarSha256'] = 'f' * 64
    with pytest.raises(retirer.RetirementError):
        validate(bundle)


@pytest.mark.parametrize('size', [0, -1, True, '34'])
def test_artifact_plan_requires_positive_exact_integer_jar_size(bundle, size):
    bundle.values['artifactPlan']['applicationJarBytes'] = size
    with pytest.raises(retirer.RetirementError):
        validate(bundle)


@pytest.mark.parametrize(('role', 'field', 'value'), [
    ('artifactPlan', 'kind', 'other-artifact-plan'), ('artifactPlan', 'schema', 2),
    ('fixtureOwner', 'kind', 'other-owner'), ('fixtureOwner', 'schemaVersion', 2),
    ('fixtureOwner', 'phase', 'PREPARING'), ('fixtureOwner', 'phase', 'PREPARED'),
    ('fixtureOwner', 'phase', 'FAILED_CLEANUP_EVIDENCE_RETAINED'),
    ('fixtureOwner', 'token', 'not-a-ten-hex-token'), ('fixtureOwner', 'work', '/tmp/unowned-fixture'),
    ('fixtureCleanup', 'kind', 'other-cleanup'), ('fixtureCleanup', 'schemaVersion', 2),
    ('fixtureCleanup', 'status', 'FAILED_OR_UNKNOWN'), ('fixtureCleanup', 'errors', ['OWNED_MYSQL_NOT_CONFIRMED']),
    ('fixtureCleanup', 'sourceDumpAndEvidenceRetained', False),
    ('fixtureCleanup', 'sourceContainerUntouched', 'f' * 64), ('fixtureCleanup', 'containerId', 'f' * 64),
])
def test_cleanup_and_owner_must_describe_one_stopped_retained_attempt(bundle, role, field, value):
    bundle.values[role][field] = value
    with pytest.raises(retirer.RetirementError):
        validate(bundle)


@pytest.mark.parametrize('role', ['fixtureOwner', 'fixtureCleanup'])
def test_foreign_machine_control_cannot_authorize_retirement(bundle, role):
    bundle.values[role]['identity'] = {**bundle.identity, 'machineId': 'f' * 32}
    with pytest.raises(retirer.RetirementError):
        validate(bundle)


def test_fixture_that_failed_before_mysql_creation_can_retain_a_safe_jar_duplicate(bundle):
    bundle.values['fixtureOwner']['containerId'] = None
    bundle.values['fixtureCleanup']['containerId'] = None
    bundle.values['fixtureCleanup']['dataDirectoryRetained'] = None
    assert isinstance(validate(bundle), dict)


def test_optional_local_build_is_checked_if_present_but_is_not_required(bundle):
    local = {'schemaVersion': 1, **bundle.context, 'scope': 'local compilation and packaging only',
             'status': 'PASS', 'exitCode': 0, 'skipTests': True, 'testsExecuted': False,
             'applicationJar': 'artifacts/application.jar', 'applicationJarSha256': sha(bundle.jar),
             'applicationJarBytes': len(bundle.jar)}
    bundle.values['localBuild'] = local
    bundle.values['release']['localBuildReceiptSha256'] = sha(encoded(local))
    assert isinstance(validate(bundle), dict)
    local['applicationJarSha256'] = 'f' * 64
    with pytest.raises(retirer.RetirementError):
        validate(bundle)


def test_optional_cleanup_transport_must_bind_the_actual_original_receipt(bundle):
    work = bundle.values['fixtureOwner']['work']
    transport = {key: bundle.context[key] for key in ('release', 'commit')}
    transport.update(status='STOPPED', cleanupReceipt=work + '/cleanup-receipt.json',
                     cleanupReceiptSha256=sha(encoded(bundle.values['fixtureCleanup'])))
    bundle.values['fixtureCleanupPublic'] = transport
    assert isinstance(validate(bundle), dict)
    transport['cleanupReceiptSha256'] = 'f' * 64
    with pytest.raises(retirer.RetirementError):
        validate(bundle)


def test_control_json_duplicate_fields_are_rejected(bundle):
    raw = documents(bundle)
    raw['release'] = raw['release'][:-1] + b',"commit":"' + bundle.context['commit'].encode() + b'"}'
    with pytest.raises(retirer.RetirementError):
        retirer.validate_control_documents(raw, bundle.context, bundle.identity)


@pytest.mark.parametrize('body', [b'', b'<flow-build>', b'<project><result>FAILURE</result></project>'])
def test_incomplete_or_foreign_xml_is_not_a_terminal_jenkins_receipt(bundle, body):
    bundle.xml = body
    with pytest.raises(retirer.RetirementError):
        validate(bundle)


def test_hash_helpers_preserve_complete_binary_control_bytes():
    payload = b'\x00private synthetic bytes\xff\n'
    assert retirer.digest_bytes(payload) == hashlib.sha256(payload).hexdigest()
    assert retirer.canonical({'b': 2, 'a': 'text'}) == b'{"a":"text","b":2}'


@pytest.fixture
def copies(tmp_path, bundle):
    root = tmp_path / 'ci'; root.mkdir(mode=0o700)
    target, keeper = retirer.duplicate_paths(root, bundle.context['release'])
    for path in (target, keeper):
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        path.write_bytes(bundle.jar); path.chmod(0o600)
    return SimpleNamespace(root=root, tag=bundle.context['release'], target=target, keeper=keeper,
                           payload=bundle.jar, sha=sha(bundle.jar), size=len(bundle.jar))


def described(copies):
    return retirer.describe_duplicate(copies.root, copies.tag, copies.sha, copies.size)


def test_exact_transport_copy_can_be_unlinked_while_original_inbox_bytes_remain(copies, monkeypatch):
    original_keeper = copies.keeper.stat()
    reserved = []
    reserve = retirer.reserve_quarantine
    def remember_reservation(*args, **kwargs):
        result = reserve(*args, **kwargs); reserved.append(result)
        return result
    monkeypatch.setattr(retirer, 'reserve_quarantine', remember_reservation)
    result = retirer.remove_duplicate(copies.root, described(copies))
    assert not copies.target.exists() and copies.keeper.read_bytes() == copies.payload
    assert copies.keeper.stat().st_ino == original_keeper.st_ino
    assert result['keeperVerifiedAfter'] is True and result['bytes'] == copies.size
    assert len(reserved) == 1
    assert list((copies.root / reserved[0]['directory']).iterdir()) == []


@pytest.mark.parametrize('scoped_to_current', [False, True])
def test_quarantine_reservation_is_a_fresh_private_directory_with_no_file(copies, scoped_to_current):
    current = copies.tag if scoped_to_current else None
    first = retirer.reserve_quarantine(copies.root, current)
    second = retirer.reserve_quarantine(copies.root, current)
    assert first['directory'] != second['directory']
    for reservation in (first, second):
        assert set(reservation) == {'directory', 'path', 'directoryIdentity'}
        directory = copies.root / reservation['directory']; path = copies.root / reservation['path']
        observed = directory.lstat()
        assert directory.resolve(strict=True) == directory and directory.is_relative_to(copies.root)
        assert stat.S_ISDIR(observed.st_mode) and stat.S_IMODE(observed.st_mode) == 0o700
        assert reservation['directoryIdentity'] == [observed.st_dev, observed.st_ino, observed.st_mode,
                                                    observed.st_uid, observed.st_gid]
        assert path.parent == directory and path.name == 'candidate-app.jar'
        assert not path.exists() and not path.is_symlink() and list(directory.iterdir()) == []
        if scoped_to_current:
            assert directory.is_relative_to(copies.keeper.parent)


def test_keeper_swapped_into_target_at_capture_is_quarantined_never_unlinked(copies, monkeypatch):
    descriptor = described(copies); reservation = retirer.reserve_quarantine(copies.root)
    captured = copies.root / reservation['path']; keeper_inode = copies.keeper.stat().st_ino
    capture = retirer._capture_no_replace; calls = []
    def substitute_keeper(*args, **kwargs):
        calls.append(True)
        os.replace(copies.keeper, copies.target)
        return capture(*args, **kwargs)
    def refuse_unlink(*_args, **_kwargs):
        pytest.fail('An unrecognized captured inode must be retained, never unlinked')
    monkeypatch.setattr(retirer, '_capture_no_replace', substitute_keeper)
    monkeypatch.setattr(retirer.os, 'unlink', refuse_unlink)
    with pytest.raises((retirer.RetirementError, OSError)):
        retirer.remove_duplicate(copies.root, descriptor, quarantine=reservation)
    assert calls == [True]
    assert captured.is_file() and captured.stat().st_ino == keeper_inode
    assert captured.read_bytes() == copies.payload
    assert not copies.keeper.exists() and not copies.target.exists()


def test_keeper_moved_to_old_target_at_quarantine_unlink_keeps_its_bytes(copies, monkeypatch):
    descriptor = described(copies); reservation = retirer.reserve_quarantine(copies.root)
    captured = copies.root / reservation['path']; directory = captured.parent
    keeper_inode = copies.keeper.stat().st_ino; unlink = os.unlink; calls = []
    def substitute_keeper_at_unlink(name, *args, **kwargs):
        assert Path(name).name == captured.name
        if 'dir_fd' in kwargs:
            assert os.fstat(kwargs['dir_fd']).st_ino == directory.stat().st_ino
        else:
            assert Path(name) == captured
        calls.append(True)
        os.replace(copies.keeper, copies.target)
        return unlink(name, *args, **kwargs)
    monkeypatch.setattr(retirer.os, 'unlink', substitute_keeper_at_unlink)
    with pytest.raises((retirer.RetirementError, OSError)):
        retirer.remove_duplicate(copies.root, descriptor, quarantine=reservation)
    assert calls == [True]
    assert copies.target.is_file() and copies.target.stat().st_ino == keeper_inode
    assert copies.target.read_bytes() == copies.payload
    assert not copies.keeper.exists() and not captured.exists()


@pytest.mark.parametrize('appears_at_capture', [False, True])
def test_unknown_quarantine_file_is_never_replaced_or_deleted(copies, monkeypatch, appears_at_capture):
    descriptor = described(copies); reservation = retirer.reserve_quarantine(copies.root)
    captured = copies.root / reservation['path']; unrecognized = b'unrecognized retained original\x00\xff'
    initial_target_inode = copies.target.stat().st_ino
    def insert_unrecognized():
        captured.write_bytes(unrecognized); captured.chmod(0o600)
    if appears_at_capture:
        capture = retirer._capture_no_replace
        def insert_before_capture(*args, **kwargs):
            insert_unrecognized()
            return capture(*args, **kwargs)
        monkeypatch.setattr(retirer, '_capture_no_replace', insert_before_capture)
    else:
        insert_unrecognized()
    with pytest.raises((retirer.RetirementError, OSError)):
        retirer.remove_duplicate(copies.root, descriptor, quarantine=reservation)
    assert captured.read_bytes() == unrecognized
    assert copies.target.stat().st_ino == initial_target_inode
    assert copies.target.read_bytes() == copies.keeper.read_bytes() == copies.payload


@pytest.mark.parametrize('which', ['target', 'keeper'])
def test_missing_copy_or_keeper_never_authorizes_deletion(copies, which):
    getattr(copies, which).unlink()
    with pytest.raises(retirer.RetirementError, match='MISSING'):
        described(copies)
    remaining = copies.keeper if which == 'target' else copies.target
    assert remaining.read_bytes() == copies.payload


@pytest.mark.parametrize('which', ['target', 'keeper'])
def test_same_size_different_complete_bytes_are_refused(copies, which):
    getattr(copies, which).write_bytes(b'X' * copies.size)
    with pytest.raises(retirer.RetirementError, match='ACTUAL_KEEPER_BYTES_MUST_EQUAL_TARGET'):
        described(copies)
    assert copies.target.exists() and copies.keeper.exists()


@pytest.mark.parametrize('which', ['target', 'keeper'])
def test_after_plan_path_replacement_retains_the_unrecognized_file(copies, which):
    descriptor = described(copies); path = getattr(copies, which)
    path.rename(path.with_name(path.name + '.old'))
    path.write_bytes(copies.payload); path.chmod(0o600)
    with pytest.raises(retirer.RetirementError, match='CHANGED_AFTER_PLAN'):
        retirer.remove_duplicate(copies.root, descriptor)
    assert copies.target.exists() and copies.keeper.exists()


@pytest.mark.parametrize('field', ['path', 'keeper'])
def test_an_inbox_artifact_or_unbound_keeper_has_no_deletion_api(copies, field):
    descriptor = described(copies)
    if field == 'path': descriptor['path'] = descriptor['keeper']['path']
    else: descriptor['keeper']['path'] = descriptor['path']
    with pytest.raises(retirer.RetirementError, match='INBOX_KEEPER_HAS_NO_DELETION_API'):
        retirer.remove_duplicate(copies.root, descriptor)
    assert copies.target.read_bytes() == copies.keeper.read_bytes() == copies.payload


def test_hardlinked_copies_do_not_count_as_two_independent_original_files(copies):
    copies.target.unlink(); os.link(copies.keeper, copies.target)
    with pytest.raises(retirer.RetirementError): described(copies)
    assert copies.target.exists() and copies.keeper.exists()


@pytest.mark.parametrize('which', ['target', 'keeper'])
def test_symlink_replacement_cannot_redirect_the_descriptor(copies, which):
    path = getattr(copies, which); sibling = path.with_name(path.name + '.original')
    path.rename(sibling); path.symlink_to(sibling)
    with pytest.raises(retirer.RetirementError): described(copies)
    assert sibling.read_bytes() == copies.payload


def test_modified_keeper_during_unlink_is_unknown_never_a_success(copies, monkeypatch):
    descriptor = described(copies); original = os.unlink
    reservation = retirer.reserve_quarantine(copies.root); captured = copies.root / reservation['path']
    def mutate_keeper(name, *args, **kwargs):
        assert Path(name).name == captured.name
        if 'dir_fd' in kwargs:
            assert os.fstat(kwargs['dir_fd']).st_ino == captured.parent.stat().st_ino
        copies.keeper.write_bytes(b'Y' * copies.size)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(retirer.os, 'unlink', mutate_keeper)
    with pytest.raises(retirer.RetirementError, match='KEEPER_CHANGED_AFTER_UNLINK'):
        retirer.remove_duplicate(copies.root, descriptor, quarantine=reservation)
    # The authorized copy may already be gone. The API must not claim keeper
    # verification or retry a deletion against an unrelated replacement.
    assert copies.keeper.is_file() and not copies.target.exists() and not captured.exists()


def test_small_declared_jar_limit_does_not_read_or_delete_an_oversize_file(copies, monkeypatch):
    monkeypatch.setattr(retirer, 'MAX_JAR', copies.size - 1)
    with pytest.raises(retirer.RetirementError): described(copies)
    assert copies.target.exists() and copies.keeper.exists()


def source_archive(copies, *, comment=None, recipe=None, publication=None):
    archive = copies.keeper.parent / 'source.tar.gz'
    body = recipe if recipe is not None else b"def prepare(self):\n jar = canonical(self.inbox / 'application.jar')\n uploaded = self.work / 'candidate-app.jar'\n shutil.copyfile(jar, uploaded)\n"
    with tarfile.open(archive, 'w:gz', format=tarfile.PAX_FORMAT,
                      pax_headers={'comment': comment or 'a' * 40}) as output:
        member = tarfile.TarInfo('script/jenkins/prepare-compact-fixtures.py'); member.size = len(body)
        output.addfile(member, io.BytesIO(body))
        for name, raw in (publication or {}).items():
            member = tarfile.TarInfo(name); member.size = len(raw)
            output.addfile(member, io.BytesIO(raw))
    archive.chmod(0o600)
    return archive


def test_real_retained_source_archive_is_hashed_and_inspected_without_execution(copies):
    archive = source_archive(copies)
    proof = retirer.source_proof(copies.root, copies.tag, 'a' * 40, sha(archive.read_bytes()))
    assert proof['sha256'] == sha(archive.read_bytes()) and proof['transportRecipeSha256']
    assert copies.target.exists() and copies.keeper.exists()


@pytest.mark.parametrize('damage', ['commit', 'recipe', 'hash'])
def test_wrong_source_commit_or_generic_copy_recipe_cannot_authorize_a_transport_target(copies, damage):
    archive = source_archive(copies, comment='f' * 40 if damage == 'commit' else None,
                             recipe=b"def prepare(self):\n pass\n" if damage == 'recipe' else None)
    expected = 'f' * 64 if damage == 'hash' else sha(archive.read_bytes())
    with pytest.raises(retirer.RetirementError):
        retirer.source_proof(copies.root, copies.tag, 'a' * 40, expected)
    assert copies.target.exists() and copies.keeper.exists()


def test_request_digest_and_protected_releases_are_independent_gate_inputs(bundle):
    current = {'release': 'ci-200-' + 'f' * 12, 'commit': 'f' * 40, 'sourceSha256': 'e' * 64}
    request = {'schemaVersion': 1, 'kind': retirer.KIND + '-request', 'current': current, 'identity': bundle.identity,
               'protectedReleases': [current['release']], 'candidates': [{**bundle.context, 'controls': {}}]}
    raw = encoded(request)
    assert retirer.validate_request(raw, sha(raw), current, bundle.identity) == request
    with pytest.raises(retirer.RetirementError, match='AUTHENTICATED_REQUEST_SHA'):
        retirer.validate_request(raw, '0' * 64, current, bundle.identity)
    request['protectedReleases'].append(bundle.context['release']); raw = encoded(request)
    with pytest.raises(retirer.RetirementError, match='PROTECTED_NATIVE_BUILD'):
        retirer.validate_request(raw, sha(raw), current, bundle.identity)


def retirement_request(copies, bundle):
    current = {'release': 'ci-200-' + 'f' * 12, 'commit': 'f' * 40, 'sourceSha256': 'e' * 64}
    inbox = copies.root / 'inbox' / current['release']; inbox.mkdir(mode=0o700)
    value = {'schemaVersion': 1, 'kind': retirer.KIND + '-request', 'current': current, 'identity': bundle.identity,
             'protectedReleases': [current['release']], 'candidates': [{**bundle.context, 'controls': {}}]}
    return current, encoded(value)


def test_missing_original_controls_are_an_explicit_skip_and_never_a_deletion(copies, bundle):
    current, raw = retirement_request(copies, bundle)
    result = retirer.plan(copies.root, raw, request_sha256=sha(raw), expected_current=current,
                          identity=bundle.identity, quiescence=lambda *_args: None)
    assert result['candidates'] == [] and result['candidateBytes'] == 0
    assert result['skipped'] == [{'release': copies.tag, 'reason': 'COMPLETE_AUTHENTICATED_CONTROL_REFERENCES_REQUIRED'}]
    assert result['deletionPerformed'] is False and copies.target.exists() and copies.keeper.exists()


def lifecycle_admission(copies, bundle):
    # Evidence authentication has separate raw-document/archive tests. This
    # controlled stub isolates apply's re-admission, locking and durable journal
    # against real synthetic files, not any deployed data or native process.
    def admitted(root, request, row, quiescence):
        quiescence(Path(root) / 'verification' / row['release'] / 'checkout', row['release'], '0123456789')
        return {'context': bundle.context, 'ownerToken': '0123456789', 'target': described(copies)}
    return admitted


def test_apply_rechecks_a_fixed_plan_and_journals_only_the_exact_duplicate(copies, bundle, monkeypatch):
    current, raw = retirement_request(copies, bundle)
    monkeypatch.setattr(retirer, 'admit_candidate', lifecycle_admission(copies, bundle))
    options = dict(request_sha256=sha(raw), expected_current=current, identity=bundle.identity, quiescence=lambda *_a: None)
    plan = retirer.plan(copies.root, raw, **options)
    result = retirer.apply(copies.root, raw, plan, plan_sha256=sha(retirer.canonical(plan)), **options)
    assert result['status'] == 'REMOVED' and result['inboxKeepersPreserved'] is True
    assert len(result['deleted']) == 1 and copies.keeper.read_bytes() == copies.payload and not copies.target.exists()
    journal = copies.root / 'inbox' / current['release'] / 'native-jar-duplicate-journal.jsonl'
    events = [json.loads(line) for line in journal.read_bytes().splitlines()]
    assert [row['phase'] for row in events] == ['STARTED', 'DELETE_STARTED', 'DELETE_FINISHED', 'FINISHED']
    quarantine_path = events[1]['quarantinePath']
    quarantine = copies.root / quarantine_path
    assert quarantine.is_relative_to(copies.root / 'inbox' / current['release'])
    assert quarantine.name == 'candidate-app.jar' and list(quarantine.parent.iterdir()) == []
    assert events[2]['quarantinePath'] == result['lastQuarantinePath'] == quarantine_path
    assert result['retainedQuarantinePaths'] == []


def test_apply_journals_the_retained_keeper_capture_before_reporting_failure(copies, bundle, monkeypatch):
    current, raw = retirement_request(copies, bundle)
    monkeypatch.setattr(retirer, 'admit_candidate', lifecycle_admission(copies, bundle))
    options = dict(request_sha256=sha(raw), expected_current=current, identity=bundle.identity, quiescence=lambda *_a: None)
    plan = retirer.plan(copies.root, raw, **options)
    keeper_inode = copies.keeper.stat().st_ino; capture = retirer._capture_no_replace
    def substitute_keeper(*args, **kwargs):
        os.replace(copies.keeper, copies.target)
        return capture(*args, **kwargs)
    monkeypatch.setattr(retirer, '_capture_no_replace', substitute_keeper)
    result = retirer.apply(copies.root, raw, plan, plan_sha256=sha(retirer.canonical(plan)), **options)
    assert result['status'] == 'FAILED_OR_UNKNOWN' and result['deleted'] == []
    assert result['mutationAttempted'] is True and result['inboxKeepersPreserved'] is False
    journal = copies.root / 'inbox' / current['release'] / 'native-jar-duplicate-journal.jsonl'
    events = [json.loads(line) for line in journal.read_bytes().splitlines()]
    assert [row['phase'] for row in events] == ['STARTED', 'DELETE_STARTED', 'FAILED_OR_UNKNOWN']
    quarantine_path = events[1]['quarantinePath']
    assert result['lastQuarantinePath'] == quarantine_path
    assert result['retainedQuarantinePaths'] == [quarantine_path]
    retained = copies.root / quarantine_path
    assert retained.is_relative_to(copies.root / 'inbox' / current['release'])
    assert retained.name == 'candidate-app.jar' and retained.stat().st_ino == keeper_inode
    assert retained.read_bytes() == copies.payload
    assert not copies.keeper.exists() and not copies.target.exists()


def test_apply_rejects_drift_and_records_failure_without_deleting_files(copies, bundle, monkeypatch):
    current, raw = retirement_request(copies, bundle)
    monkeypatch.setattr(retirer, 'admit_candidate', lifecycle_admission(copies, bundle))
    options = dict(request_sha256=sha(raw), expected_current=current, identity=bundle.identity, quiescence=lambda *_a: None)
    plan = retirer.plan(copies.root, raw, **options)
    copies.target.write_bytes(b'Z' * copies.size)
    result = retirer.apply(copies.root, raw, plan, plan_sha256=sha(retirer.canonical(plan)), **options)
    assert result['status'] == 'FAILED_OR_UNKNOWN' and result['mutationAttempted'] is False and result['deleted'] == []
    assert copies.target.exists() and copies.keeper.read_bytes() == copies.payload


def test_strict_quiescence_refusal_is_not_replaced_by_stopped_container_exceptions(copies, bundle, monkeypatch):
    current, raw = retirement_request(copies, bundle)
    monkeypatch.setattr(retirer, 'admit_candidate', lifecycle_admission(copies, bundle))
    def refuse(*_args): raise retirer.RetirementError('OLD_BUILD_CONTAINER_STILL_PRESENT')
    result = retirer.plan(copies.root, raw, request_sha256=sha(raw), expected_current=current,
                          identity=bundle.identity, quiescence=refuse)
    assert result['candidates'] == [] and result['skipped'][0]['reason'] == 'OLD_BUILD_CONTAINER_STILL_PRESENT'
    assert copies.target.exists() and copies.keeper.exists()


def test_an_active_controller_lock_cannot_be_bypassed_by_another_plan(copies, bundle):
    current, raw = retirement_request(copies, bundle)
    with retirer.controller_lock(copies.root):
        with pytest.raises(retirer.RetirementError, match='RETIREMENT_CONTROLLER_LOCK_HELD'):
            retirer.plan(copies.root, raw, request_sha256=sha(raw), expected_current=current,
                          identity=bundle.identity, quiescence=lambda *_a: None)
    assert copies.target.exists() and copies.keeper.exists()


def approved_spec(tmp_path, bundle):
    root=tmp_path/'ci';root.mkdir(mode=0o700)
    current={'release':'ci-200-'+'f'*12,'commit':'f'*40,'sourceSha256':'e'*64}
    tag,commit=next(iter(retirer.APPROVED_OLD.items()))
    context={'release':tag,'commit':commit,'sourceSha256':'b'*64}
    paths=retirer.expected_control_paths(current['release'],tag);refs={}
    for role in ('buildXml','release','artifactPlan','fixtureOwner','fixtureCleanup'):
        path=root/paths[role];path.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
        body=flow_xml(context) if role=='buildXml' else encoded({**context,'role':role})
        path.write_bytes(body);path.chmod(0o600)
        if role in ('buildXml','release'):refs[role]={'path':paths[role],'bytes':len(body),'sha256':sha(body)}
    spec={'schemaVersion':1,'kind':retirer.KIND+'-request','current':current,'identity':bundle.identity,
          'protectedReleases':[current['release']],'candidates':[{**context,'controls':refs}]}
    return SimpleNamespace(root=root,current=current,spec=spec,paths=paths,tag=tag)


def test_cli_capture_binds_actual_ecs_controls_without_returning_their_contents(tmp_path,bundle):
    state=approved_spec(tmp_path,bundle);raw=encoded(state.spec)
    request,skipped=retirer.capture_request(state.root,raw,local_spec_sha256=sha(raw),expected_current=state.current,identity=bundle.identity)
    assert skipped==[] and len(request['candidates'])==1
    refs=request['candidates'][0]['controls']
    for role in ('artifactPlan','fixtureOwner','fixtureCleanup'):
        original=(state.root/state.paths[role]).read_bytes()
        assert refs[role]=={'path':state.paths[role],'bytes':len(original),'sha256':sha(original)}
        assert 'role' not in refs[role]


@pytest.mark.parametrize('role',['artifactPlan','fixtureOwner','fixtureCleanup'])
def test_cli_capture_missing_actual_ecs_evidence_is_an_explicit_skip(tmp_path,bundle,role):
    state=approved_spec(tmp_path,bundle);(state.root/state.paths[role]).unlink();raw=encoded(state.spec)
    request,skipped=retirer.capture_request(state.root,raw,local_spec_sha256=sha(raw),expected_current=state.current,identity=bundle.identity)
    assert request['candidates']==[] and skipped==[{'release':state.tag,'reason':'REQUIRED_ECS_CONTROL_MISSING_'+role.upper()}]


def test_cli_cannot_extend_reviewed_candidates_through_an_input_document(bundle):
    current={'release':'ci-200-'+'f'*12,'commit':'f'*40,'sourceSha256':'e'*64}
    spec={'schemaVersion':1,'kind':retirer.KIND+'-request','current':current,'identity':bundle.identity,
          'protectedReleases':[current['release']],'candidates':[{**bundle.context,'release':'ci-131-'+'a'*12,'controls':{}}]}
    raw=encoded(spec)
    with pytest.raises(retirer.RetirementError,match='ONLY_REVIEWED_OLD_ATTEMPTS_ALLOWED'):
        retirer.approved_request(raw,sha(raw),current,bundle.identity)


def test_current_source_hash_is_checked_before_any_deployed_dependency_import(tmp_path,monkeypatch):
    root=tmp_path/'ci';inbox=root/'inbox'/('ci-200-'+'f'*12);inbox.mkdir(parents=True,mode=0o700)
    for name in ('retire-failed-native-jar-duplicates.py','cleanup-ecs-builds.py','verify-remote.py','compact-build-resources.py','source.tar.gz'):
        path=inbox/name;path.write_bytes(b'never execute this synthetic helper');path.chmod(0o600)
    monkeypatch.setattr(retirer,'__file__',str(inbox/'retire-failed-native-jar-duplicates.py'))
    monkeypatch.setattr(retirer.importlib.util,'spec_from_file_location',lambda *_a,**_k:pytest.fail('Imported helper before fixed archive validation'))
    args=SimpleNamespace(tag=inbox.name,mode='Verified',source_sha256='0'*64,commit='f'*40)
    with pytest.raises(retirer.RetirementError,match='FIXED_CURRENT_SOURCE_SHA_DRIFT'):
        retirer.fixed_current_source(root,args)


def test_cli_unsafe_execution_uid_is_rejected_before_current_source_or_imds(monkeypatch):
    monkeypatch.setattr(retirer.os,'getuid',lambda:999)
    monkeypatch.setattr(retirer.os,'geteuid',lambda:999)
    monkeypatch.setattr(retirer,'fixed_current_source',lambda *_a,**_k:pytest.fail('Admitted wrong UID before source validation'))
    with pytest.raises(retirer.RetirementError,match='ACTUAL_ECS_UID_1000_REQUIRED'):
        retirer.admitted_current(SimpleNamespace())


@pytest.fixture
def canonical_case(copies, bundle, monkeypatch):
    publication = {'Jenkinsfile.ecs-monolith': b'synthetic reviewed publish guard\n',
                   'script/jenkins/pipeline.ps1': b'synthetic reviewed VerifyRuntime return\n'}
    # A closed synthetic registry is isolated from the production registry. The
    # complete actual archive and original controls are still read and hashed.
    monkeypatch.setitem(retirer.APPROVED_OLD, copies.tag, bundle.context['commit'])
    monkeypatch.setitem(retirer.APPROVED_CANONICAL_SOURCES, copies.tag, tuple(sha(raw) for raw in publication.values()))
    source = source_archive(copies, publication=publication)
    bundle.context['sourceSha256'] = sha(source.read_bytes())
    for value in bundle.values.values(): value.update(bundle.context)
    work = copies.root / 'verification' / copies.tag / 'checkout/work/compact-fixtures'
    bundle.values['fixtureOwner']['work'] = str(work)
    bundle.values['fixtureCleanup']['dataDirectoryRetained'] = str(work / 'data')
    bundle.xml = flow_xml(bundle.context)
    current, raw = retirement_request(copies, bundle); request = json.loads(raw)
    refs = request['candidates'][0]['controls']; originals = [source, copies.target]
    paths = retirer.expected_control_paths(current['release'], copies.tag)
    for role, raw in documents(bundle).items():
        path = copies.root / paths[role]; path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        path.write_bytes(raw); path.chmod(0o600); originals.append(path)
        refs[role] = {'path': paths[role], 'bytes': len(raw), 'sha256': sha(raw)}
    for name in ('original-source.sql', 'original-test-report.xml'):
        path = work / name; path.write_bytes(b'original evidence or business bytes'); path.chmod(0o600); originals.append(path)
    calls = []
    def quiescence(checkout, tag, token): calls.append((checkout, tag, token))
    return SimpleNamespace(copies=copies, bundle=bundle, current=current, request=request, paths=paths,
                           originals=originals, publication=publication, calls=calls, quiescence=quiescence)


def canonical_options(state):
    raw = encoded(state.request)
    return raw, dict(request_sha256=sha(raw), expected_current=state.current, identity=state.bundle.identity,
                     quiescence=state.quiescence, canonical_jar=True)


@pytest.mark.parametrize('result', ['FAILURE', 'ABORTED'])
def test_canonical_retirement_authenticates_originals_and_reports_deliberate_binary_disposition(canonical_case, result):
    state = canonical_case; path = state.copies.root / state.paths['buildXml']
    xml = flow_xml(state.bundle.context, result=result); path.write_bytes(xml)
    state.request['candidates'][0]['controls']['buildXml'].update(bytes=len(xml), sha256=sha(xml))
    original_bytes = {path: path.read_bytes() for path in state.originals}
    raw, options = canonical_options(state); prepared = retirer.plan(state.copies.root, raw, **options)
    assert len(prepared['candidates']) == 1 and prepared['skipped'] == []
    assert prepared['kind'] == retirer.CANONICAL_KIND + '-plan'
    assert prepared['candidates'][0]['jenkinsResult'] == result
    receipt = retirer.apply(state.copies.root, raw, prepared, plan_sha256=sha(encoded(prepared)), **options)
    assert receipt['status'] == 'REMOVED' and receipt['binaryDisposition'] == 'RETIRED'
    assert receipt['inboxKeepersPreserved'] is False and receipt['binaryRebuildByteIdentityClaimed'] is False
    assert not state.copies.keeper.exists() and len(receipt['deleted']) == 1 and len(state.calls) >= 4
    assert all(path.read_bytes() == body for path, body in original_bytes.items())
    assert (state.copies.root / receipt['lastQuarantinePath']).parent.parent == state.copies.keeper.parent
    assert receipt['retainedQuarantinePaths'] == []


@pytest.mark.parametrize('reference', ['release-directory', 'current-directory', 'previous-directory', 'release-publication.json'])
def test_canonical_actual_published_or_rollback_reference_is_an_explicit_skip(canonical_case, reference):
    state = canonical_case; root = state.copies.root
    if reference == 'release-directory': (root / 'releases' / state.copies.tag).mkdir(parents=True)
    else:
        (root / 'state').mkdir(mode=0o700)
        raw = (encoded({'schema': 1, 'project': 'doorhandlecatch-monolith', 'current': str(state.copies.keeper.parent),
                        'previous': str(state.copies.keeper.parent)}) if reference.endswith('.json')
               else str(state.copies.keeper.parent).encode())
        path = root / 'state' / reference; path.write_bytes(raw); path.chmod(0o600)
    raw, options = canonical_options(state); prepared = retirer.plan(root, raw, **options)
    assert prepared['candidates'] == [] and prepared['candidateBytes'] == 0 and prepared['skipped']
    assert 'REFERENCE' in prepared['skipped'][0]['reason'] or 'RETAINED_RELEASE' in prepared['skipped'][0]['reason']
    assert state.copies.keeper.read_bytes() == state.copies.payload


def test_canonical_archive_must_authenticate_the_closed_reviewed_publication_source(canonical_case):
    state = canonical_case; damaged = {**state.publication, 'script/jenkins/pipeline.ps1': b'unknown publication behavior'}
    archive = source_archive(state.copies, publication=damaged)
    with pytest.raises(retirer.RetirementError, match='CLOSED_REVIEWED_UNPUBLISHED_SOURCE'):
        retirer.source_proof(state.copies.root, state.copies.tag, state.bundle.context['commit'], sha(archive.read_bytes()), canonical_jar=True)
    assert state.copies.keeper.exists()


def test_canonical_plan_cannot_be_applied_with_the_old_duplicate_api(canonical_case):
    state = canonical_case; raw, options = canonical_options(state); prepared = retirer.plan(state.copies.root, raw, **options)
    with pytest.raises(retirer.RetirementError, match='EXACT_SINGLE_FILE_DESCRIPTOR'):
        retirer.remove_duplicate(state.copies.root, prepared['candidates'][0]['target'])
    options.pop('canonical_jar')
    with pytest.raises(retirer.RetirementError, match='EXACT_APPROVED_PLAN_SHA'):
        retirer.apply(state.copies.root, raw, prepared, plan_sha256=sha(encoded(prepared)), **options)
    assert state.copies.keeper.exists() and state.copies.target.exists()


def test_canonical_late_inbox_reference_keeps_captured_bytes_and_records_unknown(canonical_case):
    state = canonical_case; raw, options = canonical_options(state); prepared = retirer.plan(state.copies.root, raw, **options)
    def late_reference(*args):
        if not state.copies.keeper.exists(): raise retirer.RetirementError('ACTIVE_FILE_DESCRIPTOR_REFERENCES_OLD_CHECKOUT')
    options['quiescence'] = late_reference
    receipt = retirer.apply(state.copies.root, raw, prepared, plan_sha256=sha(encoded(prepared)), **options)
    assert receipt['status'] == 'FAILED_OR_UNKNOWN' and receipt['deleted'] == []
    assert receipt['retainedQuarantinePaths'] == [receipt['lastQuarantinePath']]
    retained = state.copies.root / receipt['lastQuarantinePath']
    assert retained.read_bytes() == state.copies.payload and retained.parent.parent == state.copies.keeper.parent
    assert all(path.is_file() for path in state.originals)


def test_canonical_quarantine_can_only_be_inside_the_same_old_inbox(canonical_case):
    state = canonical_case
    descriptor = retirer.describe_canonical_jar(state.copies.root, state.copies.tag, state.copies.sha, state.copies.size)
    wrong = retirer.reserve_quarantine(state.copies.root, state.current['release'])
    with pytest.raises(retirer.RetirementError, match='CANONICAL_QUARANTINE_MUST_STAY_IN_OLD_INBOX'):
        retirer.remove_canonical_jar(state.copies.root, descriptor, wrong, quiescence=lambda: None)
    assert state.copies.keeper.exists()


def with_action(raw, action):
    value = ET.fromstring(raw)
    parameters = value.findall('.//hudson.model.ParametersAction/parameters/*')
    next(item for item in parameters if item.findtext('name') == 'ACTION').find('value').text = action
    return ET.tostring(value)


@pytest.mark.parametrize(('tag', 'commit'), [
    ('ci-187-8e90ba50c691', '8e90ba50c691d561bd26b23f037fec1600e5e9de'),
    ('ci-188-df1e1a54d48e', 'df1e1a54d48e5005185f53459068fbe9efffe333'),
    ('ci-189-410506ad7c82', '410506ad7c82e302e623a2ac27b63dc345fcd131'),
])
def test_recent_verify_originals_only_authorize_the_closed_canonical_policy(bundle, tag, commit):
    context = {'release': tag, 'commit': commit, 'sourceSha256': 'b' * 64}
    xml = with_action(flow_xml(context), 'verify')
    assert retirer.terminal_xml(xml, context, canonical_jar=True) == 'FAILURE'
    with pytest.raises(retirer.RetirementError, match='FAILED_NATIVE_PARAMETERS_REQUIRED'):
        retirer.terminal_xml(xml, context)
    current = {'release': 'ci-200-' + 'f' * 12, 'commit': 'f' * 40, 'sourceSha256': 'e' * 64}
    request = {'schemaVersion': 1, 'kind': retirer.KIND + '-request', 'current': current,
        'identity': bundle.identity, 'protectedReleases': [current['release']], 'candidates': [{**context, 'controls': {}}]}
    raw = encoded(request)
    assert retirer.approved_request(raw, sha(raw), current, bundle.identity, canonical_jar=True) == request
    with pytest.raises(retirer.RetirementError, match='ONLY_REVIEWED_OLD_ATTEMPTS_ALLOWED'):
        retirer.approved_request(raw, sha(raw), current, bundle.identity)
    assert tag not in retirer.APPROVED_OLD and tag not in retirer.PUBLIC_LAYER_TAGS
    assert tag not in retirer.APPROVED_BUILDER_TOOLS


def test_unreviewed_verify_attempt_still_cannot_enter_the_canonical_api(bundle):
    with pytest.raises(retirer.RetirementError, match='FAILED_NATIVE_PARAMETERS_REQUIRED'):
        retirer.terminal_xml(with_action(bundle.xml, 'verify'), bundle.context, canonical_jar=True)


def test_recent_verify_canonical_uses_full_originals_and_the_same_single_file_api(canonical_case, monkeypatch):
    state = canonical_case
    monkeypatch.delitem(retirer.APPROVED_OLD, state.copies.tag)
    monkeypatch.setitem(retirer.RECENT_CANONICAL_ONLY, state.copies.tag, state.bundle.context['commit'])
    path = state.copies.root / state.paths['buildXml']
    xml = with_action(path.read_bytes(), 'verify'); path.write_bytes(xml)
    state.request['candidates'][0]['controls']['buildXml'].update(bytes=len(xml), sha256=sha(xml))
    protected_originals = {path: path.read_bytes() for path in state.originals}
    raw, options = canonical_options(state)
    prepared = retirer.plan(state.copies.root, raw, **options)
    assert len(prepared['candidates']) == 1 and prepared['skipped'] == []
    assert prepared['candidates'][0]['jenkinsResult'] == 'FAILURE'
    receipt = retirer.apply(state.copies.root, raw, prepared, plan_sha256=sha(encoded(prepared)), **options)
    assert receipt['status'] == 'REMOVED' and len(receipt['deleted']) == 1
    assert receipt['binaryDisposition'] == 'RETIRED' and receipt['binaryRebuildByteIdentityClaimed'] is False
    assert not state.copies.keeper.exists()
    assert all(path.read_bytes() == body for path, body in protected_originals.items())


def test_recent_controller_is_an_independent_three_row_canonical_only_batch():
    root = MODULE.parents[2]
    controller = (root / 'script/jenkins/retire-failed-native-jar-duplicates.ps1').read_text(encoding='utf8')
    reader = controller.split("$reader=@'\n", 1)[1].split("\n'@", 1)[0]
    syntax = ast.parse(reader)
    original = next(ast.literal_eval(node.value) for node in syntax.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'approved' for target in node.targets))
    selected = next(node for node in syntax.body if isinstance(node, ast.If)
        and ast.dump(node.test) == ast.dump(ast.parse("batch=='Recent'", mode='eval').body))
    recent = ast.literal_eval(selected.body[0].value)
    assert len(original) == len(retirer.APPROVED_OLD) == 16 and len(recent) == 3
    assert {'ci-' + str(number) + '-' + commit[:12]: commit for number, commit, _sha in recent} == retirer.RECENT_CANONICAL_ONLY
    assert all(retirer.SHA.fullmatch(checksum) for _number, _commit, checksum in recent)
    assert all(number != 190 for number, _commit, _sha in recent)
    assert re.search(r"ValidateSet\('Historical','Recent'\)\]\[string\]\$CanonicalBatch = 'Historical'", controller)
    assert "$CanonicalBatch -cne 'Recent' -or $Mode -ceq 'Maintenance'" in controller
    assert "{'capture-canonical-request'}else{'capture-request'}" in controller
    branch = controller.split("if($CanonicalBatch -ceq 'Recent') {", 1)[1].split('\n$builderPlanned=', 1)[0]
    assert "Invoke-NativeJarPhase 'plan-canonical'" in branch and "Invoke-NativeJarPhase 'apply-canonical'" in branch
    assert "finally {Copy-NativeJarEvidence (Invoke-NativeJarPhase 'inspect')}" in branch and '\n    return\n}' in branch
    assert all(phase not in branch for phase in ('plan-builders', 'apply-builders', 'plan-public-layers',
        'apply-public-layers', 'plan-generated-image-archives', 'apply-generated-image-archives'))
    pipeline = (root / 'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    assert re.search(r"retire-failed-native-jar-duplicates\.ps1 -Mode Maintenance -CanonicalBatch Recent ", pipeline)


def test_recent_fixture_capture_authenticates_both_original_source_modes_before_projection(canonical_case, monkeypatch):
    state = canonical_case; tag = state.copies.tag; context = state.bundle.context
    monkeypatch.setitem(retirer.RECENT_CANONICAL_ONLY, tag, context['commit'])
    owner = state.bundle.values['fixtureOwner']; owner.update(dataDirectory=owner['work'] + '/mysql-data',
        rootPassword='synthetic-private-owner-secret', binaryLoggingDisabled=True,
        containerName='doorhandle-compact-fixture-' + owner['token'], image='sha256:' + 'f' * 64, port=43127)
    state.bundle.values['fixtureCleanup']['dataDirectoryRetained'] = owner['dataDirectory']
    xml = with_action(state.bundle.xml, 'verify')
    for role, body in [('buildXml', xml), ('fixtureOwner', encoded(owner)), ('fixtureCleanup', encoded(state.bundle.values['fixtureCleanup']))]:
        path = state.copies.root / state.paths[role]; path.write_bytes(body)
        state.request['candidates'][0]['controls'][role].update(bytes=len(body), sha256=sha(body))
    proof = {'path': 'inbox/' + tag + '/source.tar.gz', 'sha256': context['sourceSha256'],
             'transportRecipeSha256': 'c' * 64, 'builderHelperSha256': {'tool': 'd' * 64}}
    calls = []
    def original_source(root, actual_tag, commit, source_sha, **options):
        assert root == state.copies.root and actual_tag == tag
        assert commit == context['commit'] and source_sha == context['sourceSha256']
        calls.append(options); return proof
    monkeypatch.setattr(retirer, 'source_proof', original_source)
    monkeypatch.setattr(retirer, 'builder_container_ids', lambda: [owner['containerId']])
    inspected = encoded([{'Id': owner['containerId'], 'Config': {'Env': ['MYSQL_ROOT_PASSWORD=private-inspect-secret']}}])
    monkeypatch.setattr(retirer, 'builder_docker', lambda *args: inspected if args == ('inspect', owner['containerId']) else pytest.fail('Unexpected Docker operation'))
    data = [1, 2, stat.S_IFDIR | 0o700, 999, 1000]
    monkeypatch.setattr(retirer, 'fixture_data_metadata', lambda *_args: list(data))
    def descriptor(root, actual, identity, projected, cleanup, row, metadata, *, source_proof):
        assert root == state.copies.root and actual == context and identity == state.bundle.identity
        assert projected.get('binaryLoggingDisabled') is True and 'rootPassword' not in projected
        assert cleanup['dataDirectoryRetained'] == projected['dataDirectory']
        assert source_proof == proof and metadata == data and row['Id'] == owner['containerId']
        return {'containerId': row['Id'], 'inspectProjection': {'Id': row['Id']}, 'dataMetadata': metadata}
    builder = SimpleNamespace(recent_mysql_fixture_source=lambda _context, actual: actual == proof or pytest.fail('Source proof lost'),
        historical_builder_inspect=lambda raw: json.loads(raw)[0], historical_mysql_fixture_descriptor=descriptor)
    result = retirer.capture_recent_fixture(state.copies.root,
        {'current': state.current, 'identity': state.bundle.identity}, state.request['candidates'][0], builder)
    assert calls == [{'builder_helpers': True, 'canonical_jar': True}]
    assert result['fixture']['rawInspectSha256'] == sha(inspected)
    assert b'private-owner-secret' not in encoded(result) and b'private-inspect-secret' not in encoded(result)


@pytest.mark.parametrize('outcome', ['removed', 'reference-blocked', 'already-absent'])
def test_recent_fixture_phases_preserve_data_and_stop_before_jar_retirement(tmp_path, bundle, monkeypatch, outcome):
    root = tmp_path / 'ci'; root.mkdir(mode=0o700)
    tag, commit = next(iter(retirer.RECENT_CANONICAL_ONLY.items()))
    current = {'release': 'ci-200-' + 'f' * 12, 'commit': 'f' * 40, 'sourceSha256': 'e' * 64}
    context = {'release': tag, 'commit': commit, 'sourceSha256': 'b' * 64}
    for name in (tag, current['release']): (root / 'inbox' / name).mkdir(mode=0o700, parents=True)
    data = root / 'verification' / tag / 'checkout/work/compact-fixtures/mysql-data'; data.mkdir(mode=0o700, parents=True)
    page = data / 'original-private-page'; page.write_bytes(b'database evidence is never opened by maintenance')
    jar = root / 'inbox' / tag / 'application.jar'; jar.write_bytes(b'canonical jar remains for the next independent phase')
    inode = data.stat().st_ino; cid, production = 'd' * 64, 'e' * 64; token = '0123456789'
    metadata = [1, inode, stat.S_IFDIR | 0o700, 999, 1000]
    rows = {production: {'Id': production, 'HostConfig': {'NetworkMode': 'bridge', 'PidMode': '', 'IpcMode': 'private'}}}
    if outcome != 'already-absent':
        rows[cid] = {'Id': cid, 'Config': {'Env': ['MYSQL_ROOT_PASSWORD=private-inspect-secret']},
                     'HostConfig': {'NetworkMode': 'bridge', 'PidMode': '', 'IpcMode': 'private'}}
    descriptor = None if outcome == 'already-absent' else {'containerId': cid, 'ownerToken': token,
        'rawInspectSha256': sha(encoded([rows[cid]])), 'dataDirectory': str(data), 'dataMetadata': metadata}
    candidate = {'historical': {'context': context, 'evidence': {'ownerToken': token}}, 'fixture': descriptor,
                 'containerId': cid, 'dataDirectory': str(data), 'dataMetadata': metadata}
    monkeypatch.setattr(retirer, 'capture_recent_fixture', lambda *_args: copy.deepcopy(candidate))
    commands, checks = [], []; deny = [False]
    def docker(*args):
        if args[0] == 'inspect': return encoded([rows[args[1]]])
        assert args == ('rm', cid), 'Only ordinary exact-ID rm is allowed'
        commands.append(args); del rows[cid]; return cid.encode()
    monkeypatch.setattr(retirer, 'builder_docker', docker)
    monkeypatch.setattr(retirer, 'builder_container_ids', lambda: list(rows))
    monkeypatch.setattr(retirer, 'fixture_data_metadata', lambda *_args: list(metadata))
    def quiescent(_properties, actual_tag, remaining, **options):
        assert actual_tag == tag and options == {'include_inbox': True}
        assert cid not in [row[0] for row in remaining] and production in [row[0] for row in remaining]
        checks.append(actual_tag)
        if deny[0]: raise ValueError('synthetic active reference')
    cleanup = SimpleNamespace(docker_snapshot=lambda: [(key,) for key in rows], quiescent=quiescent)
    def remove(selected, inspect_fn, remove_fn, list_fn, refs_fn, data_fn):
        assert selected == descriptor and sha(inspect_fn(cid)) == selected['rawInspectSha256']
        refs_fn(cid); assert data_fn() == metadata
        remove_fn(cid); assert cid not in list_fn() and data_fn() == metadata
        return {'status': 'REMOVED', 'containerId': cid, 'dataDirectoryPreserved': True}
    builder = SimpleNamespace(historical_builder_inspect=lambda raw: json.loads(raw)[0],
                              historical_mysql_fixture_remove=remove)
    modules = {'cleanup': cleanup, 'builder': builder}
    request = {'schemaVersion': 1, 'kind': retirer.KIND + '-request', 'current': current, 'identity': bundle.identity,
        'protectedReleases': [current['release']], 'candidates': [{**context, 'controls': {}}]}
    raw_request = encoded(request); options = {'request_sha256': sha(raw_request), 'expected_current': current,
                                             'identity': bundle.identity, 'modules': modules}
    prepared = retirer.plan_recent_fixtures(root, raw_request, **options)
    assert prepared['skipped'] == [] and len(prepared['absent']) == (1 if outcome == 'already-absent' else 0)
    deny[0] = outcome == 'reference-blocked'
    result = retirer.apply_recent_fixtures(root, raw_request, prepared, plan_sha256=sha(encoded(prepared)), **options)
    assert result['status'] == {'removed': 'REMOVED', 'reference-blocked': 'FAILED_OR_UNKNOWN', 'already-absent': 'NO_ACTION'}[outcome]
    assert commands == ([('rm', cid)] if outcome == 'removed' else [])
    assert result['jarDeletionPerformed'] is False and result['volumesPreserved'] is True
    assert result['dataDirectoriesPreserved'] is (outcome != 'reference-blocked')
    assert len(result['removed']) == (1 if outcome == 'removed' else 0)
    assert result['alreadyAbsent'] == ([cid] if outcome == 'already-absent' else [])
    assert jar.read_bytes() == b'canonical jar remains for the next independent phase'
    assert page.read_bytes() == b'database evidence is never opened by maintenance' and data.stat().st_ino == inode
    assert b'private-inspect-secret' not in encoded(prepared) + encoded(result)
    if outcome == 'reference-blocked':
        assert result['failure']['reason'] == 'HISTORICAL_OBJECTS_NOT_QUIESCENT_UNCLASSIFIED_VALUE_ERROR'


def test_recent_fixture_cli_order_failure_booleans_and_original_artifacts_are_wired():
    root = MODULE.parents[2]
    script = (root / 'script/jenkins/retire-failed-native-jar-duplicates.ps1').read_text(encoding='utf8')
    branch = script.split("if($CanonicalBatch -ceq 'Recent') {", 1)[1].split('\n$builderPlanned=', 1)[0]
    phases = [branch.index("Invoke-NativeJarPhase '" + phase + "'") for phase in
              ('plan-recent-fixtures', 'apply-recent-fixtures', 'plan-canonical', 'apply-canonical')]
    assert phases == sorted(phases)
    assert "$fixtureResult.status -cin @('REMOVED','NO_ACTION')" in branch
    assert "$fixtureResult.$flag -is [bool]" in branch and "$fixtureReceipt.$flag -is [bool]" in branch
    assert "finally {Copy-NativeJarEvidence (Invoke-NativeJarPhase 'inspect')}" in branch
    for name in ('plan.json', 'receipt.json', 'journal.jsonl'):
        assert 'native-jar-duplicate-fixture-object-' + name in script
    pipeline = (root / 'Jenkinsfile.ecs-monolith').read_text(encoding='utf8')
    assert 'artifacts/native-jar-duplicate-*.json' in pipeline and 'artifacts/native-jar-duplicate-*.jsonl' in pipeline
