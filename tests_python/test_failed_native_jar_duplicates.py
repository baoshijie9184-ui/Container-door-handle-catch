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


@pytest.mark.parametrize(('tag', 'commit', 'action'), [
    ('ci-195-2c2e65a0daa9', '2c2e65a0daa94d96b327c59d720871ab70bff0a1', 'verify'),
    ('ci-198-7af0903ee840', '7af0903ee84011dc51f4abac4f4a4d9679db7322', 'verify'),
    ('ci-201-803baf401b5f', '803baf401b5f9566283a59cb6a885a794b9d7d85', 'verify-runtime'),
])
def test_recent_originals_only_authorize_the_closed_canonical_policy(bundle, tag, commit, action):
    context = {'release': tag, 'commit': commit, 'sourceSha256': 'b' * 64}
    xml = with_action(flow_xml(context), action)
    assert retirer.terminal_xml(xml, context, canonical_jar=True) == 'FAILURE'
    with pytest.raises(retirer.RetirementError, match='FAILED_NATIVE_PARAMETERS_REQUIRED'):
        retirer.terminal_xml(with_action(xml, 'verify-runtime' if action == 'verify' else 'verify'), context, canonical_jar=True)
    if action == 'verify':
        with pytest.raises(retirer.RetirementError, match='FAILED_NATIVE_PARAMETERS_REQUIRED'):
            retirer.terminal_xml(xml, context)
    current = {'release': 'ci-202-' + 'f' * 12, 'commit': 'f' * 40, 'sourceSha256': 'e' * 64}
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
        and ast.dump(node.test) == ast.dump(ast.parse("batch in ('Recent','RetiredCopies')", mode='eval').body))
    recent = next(ast.literal_eval(node.value) for node in selected.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'approved' for target in node.targets))
    assert len(original) == len(retirer.APPROVED_OLD) == 16 and len(recent) == 3
    assert {'ci-' + str(number) + '-' + commit[:12]: commit for number, commit, _sha in recent} == retirer.RECENT_CANONICAL_ONLY
    assert recent == [
        (195, '2c2e65a0daa94d96b327c59d720871ab70bff0a1', 'f923d108fd9c867f052f722fc0cef57231d2420928a881ca7780d16408dc5a8a'),
        (198, '7af0903ee84011dc51f4abac4f4a4d9679db7322', '054a2b4bdfda1c97a006c2b78d0877e06260b4cef6e0df4177f58eef8ddf8ffe'),
        (201, '803baf401b5f9566283a59cb6a885a794b9d7d85', 'baaddc7acf7eb643f68e2e0c104decb35a90a394564dc94f601914e6710e731b')]
    assert all(number != 190 for number, _commit, _sha in recent)
    assert re.search(r"ValidateSet\('Historical','Recent','RetiredCopies','ClosedRuntime','FailedNative','PublicCaches'\)\]\[string\]\$CanonicalBatch = 'Historical'", controller)
    assert "$CanonicalBatch -cne 'Recent' -or $Mode -ceq 'Maintenance'" in controller
    assert "{'capture-canonical-request'}else{'capture-request'}" in controller
    branch = controller.split("if($CanonicalBatch -ceq 'Recent') {", 1)[1].split('\n$builderPlanned=', 1)[0]
    assert "Invoke-NativeJarPhase 'plan-canonical'" in branch and "Invoke-NativeJarPhase 'apply-canonical'" in branch
    assert "finally {Copy-NativeJarEvidence (Invoke-NativeJarPhase 'inspect')}" in branch and '\n    return\n}' in branch
    assert all(phase not in branch for phase in ('plan-builders', 'apply-builders', 'plan-public-layers',
        'apply-public-layers', 'plan-generated-image-archives', 'apply-generated-image-archives'))
    pipeline = (root / 'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    assert re.search(r"retire-failed-native-jar-duplicates\.ps1 -Mode Maintenance -CanonicalBatch FailedNative ", pipeline)
    assert not re.search(r"retire-failed-native-jar-duplicates\.ps1 -Mode Maintenance -CanonicalBatch Recent ", pipeline)


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
              ('plan-recent-builders', 'apply-recent-builders', 'plan-recent-fixtures',
               'apply-recent-fixtures', 'plan-canonical', 'apply-canonical')]
    assert phases == sorted(phases)
    assert "$fixtureResult.status -cin @('REMOVED','NO_ACTION')" in branch
    assert "$fixtureResult.$flag -is [bool]" in branch and "$fixtureReceipt.$flag -is [bool]" in branch
    assert "$builderResult.$flag -is [bool]" in branch and "$builderReceipt.$flag -is [bool]" in branch
    assert "$builderReceipt.scope -ceq 'RECENT_201_BUILDER_ONLY'" in branch
    assert "finally {Copy-NativeJarEvidence (Invoke-NativeJarPhase 'inspect')}" in branch
    for name in ('plan.json', 'receipt.json', 'journal.jsonl'):
        assert 'native-jar-duplicate-fixture-object-' + name in script
    pipeline = (root / 'Jenkinsfile.ecs-monolith').read_text(encoding='utf8')
    assert 'artifacts/native-jar-duplicate-*.json' in pipeline and 'artifacts/native-jar-duplicate-*.jsonl' in pipeline


@pytest.fixture
def recent_builder_case(tmp_path, bundle, monkeypatch):
    root = tmp_path / 'ci'; root.mkdir(mode=0o700)
    tag, original = next(iter(retirer.RECENT_BUILDER_ONLY.items()))
    context = {'release': tag, 'commit': original['commit'], 'sourceSha256': original['sourceSha256']}
    current = {'release': 'ci-203-' + 'f' * 12, 'commit': 'f' * 40, 'sourceSha256': 'e' * 64}
    for name in (tag, current['release']): (root / 'inbox' / name).mkdir(mode=0o700, parents=True)
    directory = root / 'inbox' / tag / 'candidate-build-tools'; directory.mkdir(mode=0o700)
    work = root / 'verification' / tag / 'checkout/work/compact-fixtures'
    data = work / 'mysql-data'; data.mkdir(mode=0o700, parents=True)
    page = data / 'preserved-page'; page.write_bytes(b'original owned database evidence')
    jar = root / 'inbox' / tag / 'application.jar'; jar.write_bytes(b'canonical jar belongs to its later independent phase')
    cid, fid, production = original['containerId'], 'd' * 64, 'e' * 64
    token = '0123456789'
    rows = {key: {'Id': key, 'Name': name, 'HostConfig': {'NetworkMode': 'bridge', 'PidMode': '', 'IpcMode': 'private'}}
            for key, name in ((cid, '/doorhandle-builder-' + original['ownerToken']),
                              (fid, '/doorhandle-compact-fixture-' + token), (production, '/production'))}
    summary = {**context, 'status': 'PASS', 'ownerToken': original['ownerToken'],
               'cleanup': {'builderContainerId': cid, 'builderExitCode': 1,
                           'creatorStopped': True, 'builderStopped': True, 'daemonImportTerminated': True}}
    bodies = {'summary': encoded(summary), 'measurement': encoded({'synthetic': 'measured tool identity'})}
    bodies['tools'] = encoded({**context, 'status': 'PREPARED',
        'resourceEvidence': {'file': str(directory / 'resource-summary.json'), 'sha256': sha(bodies['summary'])},
        'imageMeasurementSha256': sha(bodies['measurement'])})
    paths = {}
    for role, filename in (('tools', 'tools.json'), ('summary', 'resource-summary.json'),
                            ('measurement', 'official-layer-measurements.json')):
        path = directory / filename; path.write_bytes(bodies[role]); path.chmod(0o600); paths[role] = path
    registered = {**original, **{role + 'Sha256': sha(body) for role, body in bodies.items()}}
    monkeypatch.setitem(retirer.RECENT_BUILDER_ONLY, tag, registered)
    source = {'builderHelperSha256': {'compact-build-resources.py': 'a' * 64, 'compact-image-inputs.py': 'b' * 64}}
    historical = {'context': context, 'evidence': {'ownerToken': token, 'work': str(work)}, 'sourceArchive': source,
        'fixtureOwner': {'containerId': fid, 'dataDirectory': str(data), 'token': token}, 'fixtureCleanup': {'status': 'STOPPED'}}
    def admitted(actual_root, request, row, **options):
        assert actual_root == root and row['release'] == tag and request['identity'] == bundle.identity
        assert options == {'builder_helpers': True, 'canonical_jar': True}
        return copy.deepcopy(historical)
    monkeypatch.setattr(retirer, 'admit_historical_controls', admitted)
    commands, reference_checks = [], []
    def docker(*args):
        if args[0] == 'inspect': return encoded([rows[args[1]]])
        assert len(args) == 2 and args[0] == 'rm' and args[1] in (cid, fid)
        commands.append(args); del rows[args[1]]; return args[1].encode()
    monkeypatch.setattr(retirer, 'builder_docker', docker)
    monkeypatch.setattr(retirer, 'builder_container_ids', lambda: list(rows))
    metadata = [1, data.stat().st_ino, stat.S_IFDIR | 0o700, 999, 1000]
    monkeypatch.setattr(retirer, 'fixture_data_metadata', lambda *_args: list(metadata))
    def descriptor(actual_root, actual_context, identity, tools, actual_summary, measurement, helpers, row):
        assert actual_root == root and actual_context == context and identity == bundle.identity
        assert (tools, actual_summary, measurement) == (bodies['tools'], bodies['summary'], bodies['measurement'])
        assert helpers == source['builderHelperSha256'] and row['Id'] == cid
        return {**context, 'containerId': cid, 'ownerToken': original['ownerToken'],
                'inspectSha256': sha(encoded(row)), 'imagesPreserved': True, 'volumesPreserved': True}
    def fixture_descriptor(actual_root, actual_context, identity, owner, cleanup, row, info, *, source_proof):
        assert actual_root == root and actual_context == context and identity == bundle.identity
        assert source_proof == source and info == metadata and row['Id'] == fid
        return {**context, 'containerId': fid, 'ownerToken': token, 'inspectSha256': sha(encoded(row)),
                'dataDirectory': str(data), 'dataMetadata': list(metadata)}
    def quiescent(properties, actual_tag, remaining, **options):
        assert actual_tag == tag and properties == {'checkout': work.parents[1], 'token': token}
        assert options == {'include_inbox': True}
        reference_checks.append([row[0] for row in remaining])
        if any(row[0] != production for row in remaining): raise ValueError('unclassified old object remains')
    def remove_fixture(selected, inspect_fn, remove_fn, list_fn, refs_fn, data_fn):
        assert sha(inspect_fn(fid)) == selected['rawInspectSha256'] and data_fn() == metadata
        refs_fn(fid); remove_fn(fid)
        assert fid not in list_fn() and data_fn() == metadata
        return {'status': 'REMOVED', 'containerId': fid, 'dataDirectoryPreserved': True}
    def remove_builder(selected, inspect_fn, remove_fn, list_fn, refs_fn):
        assert sha(encoded(inspect_fn(cid))) == selected['inspectSha256']
        refs_fn(cid); remove_fn(cid); assert cid not in list_fn()
        return {'status': 'REMOVED', 'containerId': cid, 'imagesPreserved': True, 'volumesPreserved': True}
    builder = SimpleNamespace(historical_builder_inspect=lambda raw: json.loads(raw)[0], encoded=encoded,
        historical_builder_descriptor=descriptor, historical_mysql_fixture_descriptor=fixture_descriptor,
        historical_mysql_fixture_remove=remove_fixture, historical_builder_remove=remove_builder)
    cleanup = SimpleNamespace(docker_snapshot=lambda: [(key,) for key in rows], quiescent=quiescent,
                              failure_guard_code=lambda _error: 'OLD_BUILD_CONTAINER_STILL_PRESENT')
    request = {'schemaVersion': 1, 'kind': retirer.KIND + '-request', 'current': current, 'identity': bundle.identity,
               'protectedReleases': [current['release']], 'candidates': [{**context, 'controls': {}}]}
    raw = encoded(request)
    options = {'request_sha256': sha(raw), 'expected_current': current, 'identity': bundle.identity,
               'modules': {'builder': builder, 'cleanup': cleanup}, 'recent': True}
    return SimpleNamespace(root=root, context=context, request=request, raw=raw, options=options, paths=paths,
        cid=cid, fid=fid, production=production, rows=rows, commands=commands, reference_checks=reference_checks,
        page=page, page_bytes=page.read_bytes(), data_inode=data.stat().st_ino, jar=jar, jar_bytes=jar.read_bytes())


@pytest.mark.parametrize('outcome', ['removed', 'unknown-object', 'late-control', 'late-inspection', 'already-absent'])
def test_recent_201_joint_builder_and_fixture_removal_keeps_every_data_file(recent_builder_case, outcome):
    state = recent_builder_case
    if outcome == 'already-absent': del state.rows[state.cid]
    if outcome == 'unknown-object':
        state.rows['a' * 64] = {'Id': 'a' * 64, 'Name': '/unknown-old-object', 'HostConfig': {}}
    prepared = retirer.plan_builders(state.root, state.raw, **state.options)
    assert prepared['scope'] == 'RECENT_201_BUILDER_ONLY'
    if outcome == 'unknown-object':
        assert prepared['candidates'] == [] and prepared['absent'] == []
        assert prepared['skipped'] == [{'release': state.context['release'],
            'reason': 'HISTORICAL_OBJECTS_NOT_QUIESCENT_OLD_BUILD_CONTAINER_STILL_PRESENT'}]
        with pytest.raises(retirer.RetirementError, match='COMPLETE_EXACT_RECENT_BUILDER_PLAN_REQUIRED'):
            retirer.apply_builders(state.root, state.raw, prepared, plan_sha256=sha(encoded(prepared)), **state.options)
    else:
        assert prepared['skipped'] == [] and len(prepared['absent']) == (1 if outcome == 'already-absent' else 0)
        if outcome == 'late-control':
            changed_plan = copy.deepcopy(prepared); changed_plan['scope'] = 'UNREVIEWED_POLICY'
            with pytest.raises(retirer.RetirementError, match='EXACT_HISTORICAL_BUILDER_PLAN_REQUIRED'):
                retirer.apply_builders(state.root, state.raw, changed_plan, plan_sha256=sha(encoded(prepared)), **state.options)
            assert state.commands == []
            state.paths['tools'].write_bytes(state.paths['tools'].read_bytes() + b' ')
        if outcome == 'late-inspection': state.rows[state.cid]['State'] = {'Running': True}
        result = retirer.apply_builders(state.root, state.raw, prepared, plan_sha256=sha(encoded(prepared)), **state.options)
        assert result['scope'] == 'RECENT_201_BUILDER_ONLY' and result['jarDeletionPerformed'] is False
        assert result['imagesPreserved'] is result['volumesPreserved'] is result['directoriesPreserved'] is True
        if outcome == 'removed':
            assert result['status'] == 'REMOVED' and state.commands == [('rm', state.fid), ('rm', state.cid)]
            assert len(result['removed']) == len(result['retiredMysqlObjects']) == 1 and result['alreadyAbsent'] == []
            assert state.reference_checks and all(row == [state.production] for row in state.reference_checks)
        elif outcome == 'already-absent':
            assert result['status'] == 'NO_ACTION' and result['alreadyAbsent'] == [state.cid]
            assert result['retiredMysqlObjects'] == [] and state.fid in state.rows
        else:
            assert result['status'] == 'FAILED_OR_UNKNOWN' and result['removed'] == result['retiredMysqlObjects'] == []
    if outcome != 'removed': assert state.commands == []
    assert state.page.read_bytes() == state.page_bytes and state.page.parent.stat().st_ino == state.data_inode
    assert state.jar.read_bytes() == state.jar_bytes


@pytest.mark.parametrize('role', ['tools', 'summary', 'measurement'])
def test_recent_201_builder_original_control_drift_prevents_any_plan(recent_builder_case, role):
    state = recent_builder_case; state.paths[role].write_bytes(state.paths[role].read_bytes() + b' ')
    prepared = retirer.plan_builders(state.root, state.raw, **state.options)
    assert prepared['candidates'] == prepared['absent'] == []
    assert prepared['skipped'] == [{'release': state.context['release'], 'reason': 'RECENT_BUILDER_ORIGINAL_CONTROL_SHA_DRIFT'}]
    assert state.commands == [] and state.page.read_bytes() == state.page_bytes and state.jar.read_bytes() == state.jar_bytes


@pytest.mark.parametrize('changed', ['commit', 'sourceSha256', 'other-recent'])
def test_recent_builder_permission_cannot_be_extended_by_the_input_document(bundle, changed):
    tag, registered = next(iter(retirer.RECENT_BUILDER_ONLY.items()))
    row = {'release': tag, 'commit': registered['commit'], 'sourceSha256': registered['sourceSha256'], 'controls': {}}
    if changed == 'other-recent':
        row.update(release='ci-198-7af0903ee840', commit=retirer.RECENT_CANONICAL_ONLY['ci-198-7af0903ee840'])
    else: row[changed] = '0' * (40 if changed == 'commit' else 64)
    with pytest.raises(retirer.RetirementError, match='ONLY_EXACT_REVIEWED_RECENT_BUILDER_ALLOWED'):
        retirer.recent_builder_registration(row)


def test_recent_builder_scope_does_not_expand_any_historical_permission():
    assert set(retirer.RECENT_BUILDER_ONLY) == {'ci-201-803baf401b5f'}
    assert set(retirer.RECENT_BUILDER_ONLY).isdisjoint(retirer.APPROVED_OLD)
    assert set(retirer.RECENT_BUILDER_ONLY).isdisjoint(retirer.APPROVED_BUILDER_TOOLS)
    assert set(retirer.RECENT_BUILDER_ONLY).isdisjoint(retirer.PUBLIC_LAYER_TAGS)
    assert set(retirer.RECENT_BUILDER_ONLY).isdisjoint(retirer.PYTHON_CACHE_APPROVED)


@pytest.fixture
def retired_copy_case(tmp_path, bundle, monkeypatch):
    root = tmp_path / 'ci'; root.mkdir(mode=0o700)
    current = {'release': 'ci-205-' + 'f' * 12, 'commit': 'f' * 40, 'sourceSha256': 'e' * 64}
    (root / 'inbox' / current['release']).mkdir(mode=0o700, parents=True)
    targets, originals, files, preserved = {}, {}, {}, {}
    for tag, actual in retirer.RETIRED_COPY_TARGETS.items():
        body = ('synthetic independently copied jar ' + tag).encode()
        targets[tag] = {**actual, 'jarSha256': sha(body), 'jarBytes': len(body)}
        work = root / 'verification' / tag / 'checkout/work/compact-fixtures'; work.mkdir(mode=0o700, parents=True)
        inbox = root / 'inbox' / tag; inbox.mkdir(mode=0o700, parents=True)
        path = work / 'candidate-app.jar'; path.write_bytes(body); path.chmod(0o600); files[tag] = path
        for path in (work / 'source.sql', work / 'original-report.xml', inbox / 'source.tar.gz'):
            path.write_bytes(('preserved original ' + str(path)).encode()); path.chmod(0o600); preserved[path] = path.read_bytes()
        context = {'release': tag, 'commit': actual['commit'], 'sourceSha256': actual['sourceSha256']}
        control_sha = {'buildXml': sha(tag.encode()), 'release': 'c' * 64}
        originals[tag] = {'context': context, 'evidence': {'jarSha256': sha(body), 'jarBytes': len(body),
            'ownerToken': '0123456789', 'controlSha256': control_sha}, 'controls': {},
            'sourceArchive': {'sha256': context['sourceSha256'], 'transportRecipeSha256': 'a' * 64}}
    monkeypatch.setattr(retirer, 'RETIRED_COPY_TARGETS', targets)
    helper = b'# synthetic original retirement policy is authenticated but never executed\n'
    archive = io.BytesIO()
    authority = {key: value for key, value in retirer.RETIRED_COPY_AUTHORITY.items() if key != 'files'}
    with tarfile.open(fileobj=archive, mode='w:gz', format=tarfile.PAX_FORMAT,
                      pax_headers={'comment': authority['commit']}) as tar:
        member = tarfile.TarInfo('script/jenkins/retire-failed-native-jar-duplicates.py'); member.size = len(helper)
        tar.addfile(member, io.BytesIO(helper))
    source = archive.getvalue(); authority.update(sourceSha256=sha(source), helperSha256=sha(helper))
    context = {key: authority[key] for key in ('release', 'commit', 'sourceSha256')}
    old_request = {'schemaVersion': 1, 'kind': retirer.KIND + '-request', 'current': context, 'identity': bundle.identity,
                   'protectedReleases': [context['release']],
                   'candidates': [{**item['context'], 'controls': {}} for item in originals.values()]}
    old_request_raw = encoded(old_request)
    old_candidates, deleted = [], []
    for tag, item in originals.items():
        registered = targets[tag]
        target = {'kind': retirer.CANONICAL_JAR_KIND, 'path': 'inbox/' + tag + '/application.jar',
                  'sha256': registered['jarSha256'], 'bytes': registered['jarBytes']}
        old_candidates.append({'context': item['context'], 'target': target,
            'controls': {key: {'sha256': value} for key, value in item['evidence']['controlSha256'].items()},
            'sourceArchive': item['sourceArchive']})
        deleted.append({**target, 'binaryDisposition': 'RETIRED', 'capturedInodeVerified': True})
    old_plan = {'kind': retirer.CANONICAL_KIND + '-plan', 'current': context, 'identity': bundle.identity,
        'requestSha256': sha(old_request_raw), 'deletionPerformed': False, 'skipped': [], 'candidates': old_candidates}
    old_plan_raw = encoded(old_plan)
    journal = [{'phase': 'STARTED', 'identity': bundle.identity,
                'requestSha256': sha(old_request_raw), 'planSha256': sha(old_plan_raw)}]
    for item in deleted: journal.extend([{'phase': 'DELETE_STARTED', **item}, {'phase': 'DELETE_FINISHED', **item}])
    journal.append({'phase': 'FINISHED', 'deletedFiles': 3})
    journal_raw = b''.join(encoded(item) + b'\n' for item in journal)
    old_receipt = {'kind': retirer.CANONICAL_KIND + '-receipt', 'current': context, 'identity': bundle.identity,
        'status': 'REMOVED', 'failure': None, 'skipped': [], 'retainedQuarantinePaths': [], 'binaryDisposition': 'RETIRED',
        'binaryRebuildByteIdentityClaimed': False, 'testsRunByRetirement': False,
        'sourceArchivesDataAndReportsHaveNoDeletionApi': True, 'planSha256': sha(old_plan_raw),
        'requestSha256': sha(old_request_raw), 'journalSha256': sha(journal_raw), 'deleted': deleted}
    terminal = ET.fromstring(flow_xml(context, result='SUCCESS'))
    for item in terminal.findall('.//hudson.model.ParametersAction/parameters/*'):
        if item.findtext('name') == 'ACTION': item.find('value').text = 'reclaim-build-outputs'
        if item.findtext('name') == 'DOORHANDLE_CI_SCOPE': item.find('value').text = 'source'
    bodies = {'buildXml': ET.tostring(terminal), 'source': source, 'request': old_request_raw,
        'plan': old_plan_raw, 'receipt': encoded(old_receipt), 'journal': journal_raw,
        'release': encoded({**context, 'schema': 1, 'kind': 'doorhandle-maintenance-source',
            'action': 'reclaim-build-outputs', 'maintenanceOnly': True, 'testsExecuted': False, 'applicationBuilt': False})}
    authority_files = {}; directory = root / 'inbox' / current['release'] / 'native-retired-candidate-controls' / context['release']
    directory.mkdir(mode=0o700, parents=True)
    authority['files'] = {}
    for role, (name, _size, _checksum) in retirer.RETIRED_COPY_AUTHORITY['files'].items():
        body = bodies[role]; path = directory / name; path.write_bytes(body); path.chmod(0o600)
        authority_files[role] = path; authority['files'][role] = (name, len(body), sha(body))
    monkeypatch.setattr(retirer, 'RETIRED_COPY_AUTHORITY', authority)
    checks, blocked = [], [False]
    def original(actual_root, request, row, **options):
        assert actual_root == root and options == {'canonical_jar': True}
        assert row['release'] in targets and request['identity'] == bundle.identity
        return copy.deepcopy(originals[row['release']])
    monkeypatch.setattr(retirer, 'admit_historical_controls', original)
    def quiescence(checkout, tag, token):
        assert checkout == root / 'verification' / tag / 'checkout' and token == '0123456789'
        checks.append(tag)
        if blocked[0]: raise retirer.RetirementError('SYNTHETIC_OTHER_CONTAINER_REFERENCE')
    request = {'schemaVersion': 1, 'kind': retirer.KIND + '-request', 'current': current, 'identity': bundle.identity,
        'protectedReleases': [current['release']], 'candidates': [{**item['context'], 'controls': {}} for item in originals.values()]}
    raw = encoded(request); options = {'request_sha256': sha(raw), 'expected_current': current,
                                      'identity': bundle.identity, 'quiescence': quiescence}
    return SimpleNamespace(root=root, current=current, identity=bundle.identity, authority=authority,
        authority_files=authority_files, files=files, originals=originals, preserved=preserved,
        bodies={tag: path.read_bytes() for tag, path in files.items()}, raw=raw, options=options, checks=checks, blocked=blocked)


def test_retired_copies_require_the_real_authority_chain_and_preserve_originals(retired_copy_case):
    state = retired_copy_case
    prepared = retirer.plan_retired_candidate_copies(state.root, state.raw, **state.options)
    assert prepared['candidateTargetCount'] == 3 and prepared['skipped'] == []
    changed = copy.deepcopy(prepared); changed['candidateTargetCount'] = 2
    with pytest.raises(retirer.RetirementError, match='COMPLETE_EXACT_RETIRED_COPY_PLAN_REQUIRED'):
        retirer.apply_retired_candidate_copies(state.root, state.raw, changed, plan_sha256=sha(encoded(prepared)), **state.options)
    result = retirer.apply_retired_candidate_copies(state.root, state.raw, prepared, plan_sha256=sha(encoded(prepared)), **state.options)
    assert result['status'] == 'REMOVED' and result['candidateTargetCount'] == len(result['deleted']) == 3
    assert result['binaryDisposition'] == 'RETIRED' and result['inboxKeepersRecreated'] is False
    assert result['sourceArchivesDataAndReportsHaveNoDeletionApi'] is True and result['retainedQuarantinePaths'] == []
    assert all(not path.exists() for path in state.files.values())
    assert all(path.read_bytes() == body for path, body in state.preserved.items())
    assert all(not (state.root / 'inbox' / tag / 'application.jar').exists() for tag in state.files)
    assert set(state.checks) == set(state.files)


@pytest.mark.parametrize('role', ['buildXml', 'release', 'source', 'request', 'plan', 'receipt', 'journal'])
def test_each_original_retirement_authority_file_is_bound_before_copy_plan(retired_copy_case, role):
    state = retired_copy_case; path = state.authority_files[role]; path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(retirer.RetirementError, match='ORIGINAL_RETIREMENT_AUTHORITY_SHA_DRIFT'):
        retirer.plan_retired_candidate_copies(state.root, state.raw, **state.options)
    assert all(path.read_bytes() == state.bodies[tag] for tag, path in state.files.items())


@pytest.mark.parametrize('obstacle', ['candidate-bytes', 'keeper-reappeared', 'other-reference'])
def test_retired_copy_plan_is_all_three_or_no_mutation(retired_copy_case, obstacle):
    state = retired_copy_case; tag = next(iter(state.files))
    if obstacle == 'candidate-bytes': state.files[tag].write_bytes(b'unreviewed replacement')
    if obstacle == 'keeper-reappeared': (state.root / 'inbox' / tag / 'application.jar').write_bytes(b'new unexpected keeper')
    if obstacle == 'other-reference': state.blocked[0] = True
    prepared = retirer.plan_retired_candidate_copies(state.root, state.raw, **state.options)
    assert prepared['candidateTargetCount'] < 3 and prepared['skipped']
    with pytest.raises(retirer.RetirementError, match='COMPLETE_EXACT_RETIRED_COPY_PLAN_REQUIRED'):
        retirer.apply_retired_candidate_copies(state.root, state.raw, prepared, plan_sha256=sha(encoded(prepared)), **state.options)
    assert all(path.exists() for path in state.files.values())


@pytest.mark.parametrize('changed', ['candidate', 'authority', 'publication'])
def test_retired_copy_apply_rechecks_plan_authority_target_and_publication(retired_copy_case, changed):
    state = retired_copy_case; prepared = retirer.plan_retired_candidate_copies(state.root, state.raw, **state.options)
    tag = next(iter(state.files))
    if changed == 'candidate': state.files[tag].write_bytes(b'late candidate replacement')
    if changed == 'authority': state.authority_files['receipt'].write_bytes(b'late authority replacement')
    if changed == 'publication': (state.root / 'releases' / tag).mkdir(mode=0o700, parents=True)
    result = retirer.apply_retired_candidate_copies(state.root, state.raw, prepared, plan_sha256=sha(encoded(prepared)), **state.options)
    assert result['status'] == 'FAILED_OR_UNKNOWN' and result['deleted'] == []
    assert all(path.exists() for path in state.files.values())
    assert all(path.read_bytes() == body for path, body in state.preserved.items())


@pytest.mark.parametrize('changed', ['originals', 'reference', 'inbox-reappears', 'target-reappears'])
def test_retired_copy_changed_after_capture_is_retained_never_unlinked(retired_copy_case, monkeypatch, changed):
    state = retired_copy_case; prepared = retirer.plan_retired_candidate_copies(state.root, state.raw, **state.options)
    tag = next(iter(state.files)); capture = retirer._capture_no_replace
    def changed_capture(*args):
        capture(*args)
        if changed == 'originals': state.originals[tag]['evidence']['controlSha256']['release'] = '0' * 64
        if changed == 'reference': state.blocked[0] = True
        if changed == 'inbox-reappears': (state.root / 'inbox' / tag / 'application.jar').write_bytes(b'new unexpected inbox jar')
        if changed == 'target-reappears': state.files[tag].write_bytes(b'new unexpected target')
    monkeypatch.setattr(retirer, '_capture_no_replace', changed_capture)
    result = retirer.apply_retired_candidate_copies(state.root, state.raw, prepared, plan_sha256=sha(encoded(prepared)), **state.options)
    assert result['status'] == 'FAILED_OR_UNKNOWN' and result['deleted'] == []
    assert len(result['retainedQuarantinePaths']) == 1 and result['automaticResumeAllowed'] is False
    assert (state.root / result['retainedQuarantinePaths'][0]).read_bytes() == state.bodies[tag]
    if changed == 'target-reappears': assert state.files[tag].read_bytes() == b'new unexpected target'
    assert all(path.read_bytes() == body for path, body in state.preserved.items())


@pytest.mark.parametrize('changed', ['unknown-tag', 'old-kind'])
def test_retired_copy_single_file_api_does_not_expand_the_original_apis(retired_copy_case, changed):
    state = retired_copy_case; tag = next(iter(state.files)); registered = retirer.RETIRED_COPY_TARGETS[tag]
    descriptor = retirer.describe_retired_candidate_copy(state.root, tag, registered['jarSha256'], registered['jarBytes'])
    if changed == 'unknown-tag': descriptor['release'] = 'ci-204-' + 'a' * 12
    else: descriptor['kind'] = retirer.JAR_COPY_KIND
    with pytest.raises(retirer.RetirementError):
        retirer.remove_retired_candidate_copy(state.root, descriptor, {}, quiescence=lambda: None)
    assert state.files[tag].read_bytes() == state.bodies[tag]


@pytest.mark.parametrize('changed', ['result', 'ACTION', 'DOORHANDLE_CI_SCOPE'])
def test_retired_copy_authority_terminal_is_an_actual_successful_maintenance(retired_copy_case, changed):
    state = retired_copy_case; raw = state.authority_files['buildXml'].read_bytes(); tree = ET.fromstring(raw)
    if changed == 'result': tree.find('result').text = 'FAILURE'
    else:
        item = next(item for item in tree.findall('.//hudson.model.ParametersAction/parameters/*') if item.findtext('name') == changed)
        item.find('value').text = 'verify-runtime' if changed == 'ACTION' else 'mysql'
    with pytest.raises(retirer.RetirementError): retirer.retired_copy_terminal(ET.tostring(tree), state.authority)


def test_retired_copy_controller_archive_and_authority_contract_are_fully_wired():
    root = MODULE.parents[2]
    controller = (root / 'script/jenkins/retire-failed-native-jar-duplicates.ps1').read_text(encoding='utf8')
    reader = controller.split("$reader=@'\n", 1)[1].split("\n'@", 1)[0]; syntax = ast.parse(reader)
    branch = next(node for node in syntax.body if isinstance(node, ast.If)
                  and ast.dump(node.test) == ast.dump(ast.parse("batch=='RetiredCopies' and retired_batch=='retired-195-198-201'", mode='eval').body))
    originals = next(ast.literal_eval(node.value) for node in branch.body if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == 'originals' for target in node.targets))
    assert originals == {name: (length, checksum) for name, length, checksum in retirer.RETIRED_COPY_AUTHORITY['files'].values()}
    selected = controller.split("if($CanonicalBatch -ceq 'RetiredCopies') {", 2)[-1].split("if($CanonicalBatch -ceq 'Recent') {", 1)[0]
    assert selected.index("Invoke-NativeJarPhase 'plan-retired-candidate-copies'") < selected.index("Invoke-NativeJarPhase 'apply-retired-candidate-copies'")
    assert "finally {Copy-NativeJarEvidence (Invoke-NativeJarPhase 'inspect')}" in selected
    assert "candidateTargetCount -eq 3" in selected and "$copyResult.$flag -is [bool]" in selected
    assert "retiredCandidatePlan" in controller and "retiredCandidateReceipt" in controller and "retiredCandidateJournal" in controller
    pipeline = (root / 'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    assert '-Mode Maintenance -CanonicalBatch FailedNative ' in pipeline
    jenkinsfile = (root / 'Jenkinsfile.ecs-monolith').read_text(encoding='utf8')
    assert 'artifacts/native-retired-candidate-copy-*.json' in jenkinsfile
    assert 'artifacts/native-retired-candidate-copy-*.jsonl' in jenkinsfile


def retain_closed_phase(folder, stem, plan, receipt):
    plan_raw = retirer.canonical(plan)
    (folder / (stem + '-plan.json')).write_bytes(plan_raw); (folder / (stem + '-plan.json')).chmod(0o600)
    journal = folder / (stem + '-journal.jsonl')
    if not journal.exists(): journal.write_bytes(b'{"phase":"FINISHED"}\n'); journal.chmod(0o600)
    receipt.update(planSha256=sha(plan_raw), journalSha256=sha(journal.read_bytes()))
    file = folder / (stem + '-receipt.json')
    file.write_bytes(retirer.canonical(receipt)); file.chmod(0o600)
    return file


@pytest.fixture
def closed_runtime_case(tmp_path, bundle, monkeypatch):
    root = tmp_path / 'closed-ci'; root.mkdir(mode=0o700)
    current = {'release': 'ci-209-' + 'f' * 12, 'commit': 'f' * 40, 'sourceSha256': 'e' * 64}
    (root / 'inbox' / current['release']).mkdir(parents=True, mode=0o700)
    rows, binaries, originals, registered = [], {}, {}, copy.deepcopy(retirer.CLOSED_RUNTIME_JARS)
    for tag, fixed in registered.items():
        work = root / 'verification' / tag / 'checkout/work/compact-fixtures'; work.mkdir(parents=True, mode=0o700)
        inbox = root / 'inbox' / tag; inbox.mkdir(parents=True, mode=0o700)
        payload = ('synthetic closed binary ' + tag).encode()
        target, keeper = retirer.duplicate_paths(root, tag)
        for file in (target, keeper): file.write_bytes(payload); file.chmod(0o600)
        binaries[tag] = (target, keeper, payload)
        publication = {'Jenkinsfile.ecs-monolith': b'closed synthetic publication guard',
            'script/jenkins/pipeline.ps1': b'closed synthetic runtime return',
            'script/docker/compact-build-resources.py': b'original synthetic helper',
            'script/docker/compact-image-inputs.py': b'original synthetic inputs'}
        # Reviewed v1 producer excerpt: containerId is explicit; the name and
        # data directory are first assigned by start_mysql, after clone admission.
        recipe = b"def prepare(self):\n self.journal = {'schemaVersion': 1, 'kind': 'doorhandle-compact-fixture-owner', 'release': self.args.tag, 'commit': self.args.commit, 'sourceSha256': self.args.source_sha256, 'identity': self.identity, 'token': token, 'work': str(self.work), 'phase': 'PREPARING', 'containerId': None, 'sourceContainerId': settings['sourceMysqlContainerId'], 'schemas': []}\n jar = canonical(self.inbox / 'application.jar')\n uploaded = self.work / 'candidate-app.jar'\n shutil.copyfile(jar, uploaded)\n"
        source = source_archive(SimpleNamespace(keeper=keeper), comment=fixed['commit'], publication=publication, recipe=recipe)
        monkeypatch.setitem(retirer.APPROVED_CANONICAL_SOURCES, tag,
            (sha(publication['Jenkinsfile.ecs-monolith']), sha(publication['script/jenkins/pipeline.ps1'])))
        fixed.update(sourceSha256=sha(source.read_bytes()), jarSha256=sha(payload), jarBytes=len(payload))
        context = {key: fixed[key] for key in ('commit', 'sourceSha256')}; context['release'] = tag
        values = copy.deepcopy(bundle.values)
        for value in values.values(): value.update(context)
        values['release'].update(applicationJarSha256=sha(payload))
        values['artifactPlan'].update(applicationJarSha256=sha(payload), applicationJarBytes=len(payload))
        cid = fixed['containerId']
        token = '0123456789' if tag == 'ci-204-24f8eb4b02bf' else '9876543210'
        values['fixtureOwner'].update(work=str(work), containerId=cid, token=token,
            containerName='doorhandle-compact-fixture-' + token if cid else None,
            dataDirectory=str(work / 'mysql-data') if cid else None, schemas=[])
        values['fixtureCleanup'].update(containerId=cid, dataDirectoryRetained=str(work / 'mysql-data') if cid else None)
        paths = retirer.expected_control_paths(current['release'], tag); controls = {}
        for role, raw in {'buildXml': flow_xml(context), **{key: encoded(value) for key, value in values.items()}}.items():
            file = root / paths[role]; file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            file.write_bytes(raw); file.chmod(0o600)
            controls[role] = {'path': paths[role], 'bytes': len(raw), 'sha256': sha(raw)}
            originals[file] = raw
        for file in (source, work / 'source.sql', work / 'original-report.xml'):
            if not file.exists(): file.write_bytes(b'preserved original'); file.chmod(0o600)
            originals[file] = file.read_bytes()
        rows.append({**context, 'controls': controls})
    monkeypatch.setattr(retirer, 'CLOSED_RUNTIME_JARS', registered)
    request = {'schemaVersion': 1, 'kind': retirer.KIND + '-request', 'current': current, 'identity': bundle.identity,
        'protectedReleases': [current['release']], 'candidates': rows}
    raw = retirer.canonical(request); request_sha = sha(raw)
    builder_plan = {'kind': 'doorhandle-historical-builder-retirement-plan', 'current': current, 'identity': bundle.identity,
        'requestSha256': request_sha, 'closedJarBatch': retirer.CLOSED_RUNTIME_BATCH, 'skipped': [], 'deletionPerformed': False}
    builder_receipt = {'kind': 'doorhandle-historical-builder-retirement-receipt', 'current': current, 'identity': bundle.identity,
        'requestSha256': request_sha, 'closedJarBatch': retirer.CLOSED_RUNTIME_BATCH, 'scope': 'CLOSED_RUNTIME_BUILDERS',
        'status': 'REMOVED', 'removed': [{'containerId': row['containerId']} for row in retirer.CLOSED_RUNTIME_BUILDERS.values()],
        'alreadyAbsent': [], 'retiredMysqlObjects': [], 'failure': None, 'skipped': [], 'jarDeletionPerformed': False,
        'mysqlDataDirectoriesPreserved': True, 'imagesPreserved': True, 'volumesPreserved': True, 'directoriesPreserved': True}
    retain_closed_phase(root / 'inbox' / current['release'], 'native-builder-retirement', builder_plan, builder_receipt)
    fixture = {'kind': 'doorhandle-recent-mysql-fixture-object-receipt', 'current': current, 'identity': bundle.identity,
        'requestSha256': request_sha, 'closedJarBatch': retirer.CLOSED_RUNTIME_BATCH, 'status': 'REMOVED',
        'removed': [{'containerId': registered['ci-204-24f8eb4b02bf']['containerId']}], 'alreadyAbsent': [],
        'noObject': ['ci-207-eb286c623177'], 'skipped': [], 'failure': None, 'dataDirectoriesPreserved': True,
        'imagesPreserved': True, 'volumesPreserved': True, 'sourceArchivesAndReportsPreserved': True,
        'jarDeletionPerformed': False}
    receipt = root / 'inbox' / current['release'] / 'native-jar-duplicate-fixture-object-receipt.json'
    fixture_plan = {'kind': 'doorhandle-recent-mysql-fixture-object-plan', 'current': current, 'identity': bundle.identity, 'requestSha256': request_sha,
                    'closedJarBatch': retirer.CLOSED_RUNTIME_BATCH, 'skipped': [], 'deletionPerformed': False,
                    'prerequisite': retirer.closed_runtime_previous(root, request, canonical_jar=False, builder=True)}
    retain_closed_phase(receipt.parent, 'native-jar-duplicate-fixture-object', fixture_plan, fixture)
    observations = []
    def quiescence(checkout, tag, token):
        assert checkout == root / 'verification' / tag / 'checkout'
        assert token == ('0123456789' if tag == 'ci-204-24f8eb4b02bf' else '9876543210')
        # Every new command must keep the publication lock through capture.
        with pytest.raises(retirer.RetirementError):
            with retirer.publication_lock(root): pytest.fail('Publication lock was released during retirement')
        target, keeper, _ = binaries[tag]
        observations.append((tag, target.exists(), keeper.exists()))
    options = {'request_sha256': request_sha, 'expected_current': current, 'identity': bundle.identity,
               'quiescence': quiescence, 'closed_runtime': True}
    monkeypatch.setattr(retirer, 'builder_container_ids', lambda: [])
    return SimpleNamespace(root=root, request=request, raw=raw, options=options, originals=originals,
        binaries=binaries, fixture=fixture, fixture_receipt=receipt, observations=observations)


def test_closed_runtime_reuses_both_held_file_apis_in_order_for_exactly_four_originals(closed_runtime_case):
    state = closed_runtime_case
    first = retirer.plan(state.root, state.raw, **state.options)
    assert len(first['candidates']) == 2 and first['skipped'] == []
    copies = retirer.apply(state.root, state.raw, first, plan_sha256=sha(retirer.canonical(first)), **state.options)
    assert copies['status'] == 'REMOVED' and len(copies['deleted']) == 2 and copies['inboxKeepersPreserved'] is True
    assert all(not target.exists() and keeper.read_bytes() == payload for target, keeper, payload in state.binaries.values())
    file = retain_closed_phase(state.fixture_receipt.parent, 'native-jar-duplicate', first, copies)
    second = retirer.plan(state.root, state.raw, canonical_jar=True, **state.options)
    assert second['prerequisite']['sha256'] == sha(file.read_bytes()) and len(second['candidates']) == 2
    retired = retirer.apply(state.root, state.raw, second, plan_sha256=sha(retirer.canonical(second)),
                            canonical_jar=True, **state.options)
    assert retired['status'] == 'REMOVED' and len(retired['deleted']) == 2 and retired['binaryDisposition'] == 'RETIRED'
    assert all(not target.exists() and not keeper.exists() for target, keeper, _ in state.binaries.values())
    assert all(file.read_bytes() == raw for file, raw in state.originals.items())
    assert all(any(row == (tag, False, True) for row in state.observations) for tag in state.binaries)


@pytest.mark.parametrize('damage', ['missing-member', 'extra-206', 'source', 'commit'])
def test_closed_runtime_request_cannot_expand_or_reduce_the_reviewed_batch(closed_runtime_case, damage):
    state = closed_runtime_case; request = copy.deepcopy(state.request)
    if damage == 'missing-member': request['candidates'].pop()
    elif damage == 'extra-206': request['candidates'].append({**request['candidates'][0], 'release': 'ci-206-' + 'a' * 12, 'commit': 'a' * 40})
    else: request['candidates'][0]['sourceSha256' if damage == 'source' else 'commit'] = 'c' * (64 if damage == 'source' else 40)
    raw = retirer.canonical(request)
    with pytest.raises(retirer.RetirementError):
        retirer.closed_runtime_request(raw, sha(raw), state.request['current'], state.request['identity'])


@pytest.mark.parametrize('canonical_jar', [False, True])
def test_closed_runtime_tags_never_enter_the_legacy_default_permission(closed_runtime_case, canonical_jar):
    state = closed_runtime_case
    with pytest.raises(retirer.RetirementError, match='ONLY_REVIEWED_OLD_ATTEMPTS'):
        retirer.approved_request(state.raw, sha(state.raw), state.request['current'], state.request['identity'], canonical_jar=canonical_jar)


def test_default_canonical_plan_cannot_borrow_the_closed_runtime_registration(closed_runtime_case):
    state = closed_runtime_case; options = {key: value for key, value in state.options.items() if key != 'closed_runtime'}
    result = retirer.plan(state.root, state.raw, canonical_jar=True, **options)
    assert result['candidates'] == [] and len(result['skipped']) == 2
    assert all(row['reason'] == 'ONLY_REVIEWED_OLD_ATTEMPTS_ALLOWED' for row in result['skipped'])
    assert all(target.exists() and keeper.exists() for target, keeper, _ in state.binaries.values())


def test_default_canonical_apply_cannot_borrow_the_closed_runtime_registration(closed_runtime_case):
    state = closed_runtime_case; options = {key: value for key, value in state.options.items() if key != 'closed_runtime'}
    # An authentic-looking selection cannot activate the new registry through
    # the legacy API; admission must refuse before inspecting any target.
    plan = {'kind': retirer.CANONICAL_KIND + '-plan', 'requestSha256': sha(state.raw), 'current': state.request['current'],
        'identity': state.request['identity'], 'inboxKeepersPreserved': True, 'deletionPerformed': False, 'skipped': [],
        'candidates': [{'context': {key: row[key] for key in ('release', 'commit', 'sourceSha256')}}
                       for row in state.request['candidates']]}
    result = retirer.apply(state.root, state.raw, plan, plan_sha256=sha(retirer.canonical(plan)), canonical_jar=True, **options)
    assert result['status'] == 'FAILED_OR_UNKNOWN' and result['mutationAttempted'] is False and result['deleted'] == []
    assert result['failure'] == 'ONLY_REVIEWED_OLD_ATTEMPTS_ALLOWED'
    assert all(target.exists() and keeper.exists() for target, keeper, _ in state.binaries.values())


@pytest.mark.parametrize('damage', ['missing', 'partial-object', 'wrong-no-object', 'data-not-preserved'])
def test_closed_runtime_copies_wait_for_the_complete_original_fixture_receipt(closed_runtime_case, damage):
    state = closed_runtime_case; value = copy.deepcopy(state.fixture)
    if damage == 'missing': state.fixture_receipt.unlink()
    else:
        if damage == 'partial-object': value['removed'] = []
        elif damage == 'wrong-no-object': value['noObject'] = ['ci-206-' + 'a' * 12]
        else: value['dataDirectoriesPreserved'] = False
        state.fixture_receipt.write_bytes(retirer.canonical(value))
    with pytest.raises((retirer.RetirementError, FileNotFoundError)):
        retirer.plan(state.root, state.raw, **state.options)
    assert all(target.exists() and keeper.exists() for target, keeper, _ in state.binaries.values())


@pytest.mark.parametrize('damage', ['partial-plan', 'skip', 'previous-sha-drift'])
def test_closed_runtime_apply_cannot_mutate_a_partial_or_changed_batch(closed_runtime_case, damage):
    state = closed_runtime_case; prepared = retirer.plan(state.root, state.raw, **state.options)
    if damage == 'partial-plan': prepared['candidates'].pop()
    elif damage == 'skip': prepared['skipped'] = [{'release': 'ci-204-24f8eb4b02bf', 'reason': 'missing'}]
    else: state.fixture_receipt.write_bytes(state.fixture_receipt.read_bytes() + b' ')
    if damage == 'previous-sha-drift':
        result = retirer.apply(state.root, state.raw, prepared, plan_sha256=sha(retirer.canonical(prepared)), **state.options)
        assert result['status'] == 'FAILED_OR_UNKNOWN' and result['deleted'] == [] and result['mutationAttempted'] is False
    else:
        with pytest.raises(retirer.RetirementError):
            retirer.apply(state.root, state.raw, prepared, plan_sha256=sha(retirer.canonical(prepared)), **state.options)
    assert all(target.exists() and keeper.exists() for target, keeper, _ in state.binaries.values())


@pytest.mark.parametrize('damage', ['none', 'missing-null-key', 'container-name', 'data-directory'])
def test_closed_207_requires_the_actual_explicit_null_owner_before_no_object(closed_runtime_end_to_end, monkeypatch, damage):
    state = closed_runtime_end_to_end.state; row = state.request['candidates'][1]; ref = row['controls']['fixtureOwner']
    file = state.root / ref['path']; owner = json.loads(file.read_bytes())
    if damage == 'missing-null-key': del owner['containerId']
    elif damage == 'container-name': owner['containerName'] = 'unexpected-object'
    elif damage == 'data-directory': owner['dataDirectory'] = '/unexpected/data'
    raw = retirer.canonical(owner); file.write_bytes(raw); ref.update(bytes=len(raw), sha256=sha(raw))
    builder = closed_runtime_end_to_end.modules['builder']
    request = state.request
    if damage == 'none':
        result = retirer.capture_recent_fixture(state.root, request, row, builder, closed_runtime=True)
        assert result['absenceKind'] == 'NO_OBJECT' and result['fixture'] is result['containerId'] is result['dataDirectory'] is None
    else:
        with pytest.raises(retirer.RetirementError):
            retirer.capture_recent_fixture(state.root, request, row, builder, closed_runtime=True)


def test_new_reference_after_duplicate_capture_retains_quarantine_and_keeper(copies):
    descriptor = described(copies); reservation = retirer.reserve_quarantine(copies.root); calls = []
    def recheck():
        calls.append(copies.target.exists())
        if not copies.target.exists(): raise retirer.RetirementError('NEW_DUAL_ROOT_REFERENCE')
    with pytest.raises(retirer.RetirementError, match='NEW_DUAL_ROOT_REFERENCE'):
        retirer.remove_duplicate(copies.root, descriptor, quarantine=reservation, quiescence=recheck)
    assert calls == [True, False] and copies.keeper.read_bytes() == copies.payload
    assert (copies.root / reservation['path']).read_bytes() == copies.payload and not copies.target.exists()


@pytest.mark.parametrize('damage', ['missing', 'partial', 'keeper-not-verified', 'wrong-sha'])
def test_closed_inbox_retirement_cannot_skip_original_complete_copy_evidence(closed_runtime_case, damage):
    state = closed_runtime_case
    deleted = [{'path': f'verification/{tag}/checkout/work/compact-fixtures/candidate-app.jar',
        'sha256': sha(payload), 'bytes': len(payload), 'keeperVerifiedAfter': True, 'capturedInodeVerified': True}
        for tag, (_target, _keeper, payload) in state.binaries.items()]
    prior = {'kind': retirer.KIND + '-receipt', 'current': state.request['current'], 'identity': state.request['identity'],
        'requestSha256': sha(state.raw), 'closedJarBatch': retirer.CLOSED_RUNTIME_BATCH, 'status': 'REMOVED',
        'failure': None, 'skipped': [], 'deleted': deleted, 'inboxKeepersPreserved': True,
        'retainedQuarantinePaths': [], 'sourceArchivesDataAndReportsHaveNoDeletionApi': True}
    if damage == 'partial': prior['deleted'].pop()
    elif damage == 'keeper-not-verified': prior['deleted'][0]['keeperVerifiedAfter'] = False
    elif damage == 'wrong-sha': prior['deleted'][0]['sha256'] = '0' * 64
    if damage != 'missing':
        plan = {'kind': retirer.KIND + '-plan', 'current': state.request['current'], 'identity': state.request['identity'], 'requestSha256': sha(state.raw),
                'closedJarBatch': retirer.CLOSED_RUNTIME_BATCH, 'skipped': [], 'deletionPerformed': False}
        retain_closed_phase(state.fixture_receipt.parent, 'native-jar-duplicate', plan, prior)
    with pytest.raises((retirer.RetirementError, FileNotFoundError)):
        retirer.plan(state.root, state.raw, canonical_jar=True, **state.options)
    assert all(keeper.exists() for _target, keeper, _payload in state.binaries.values())


@pytest.mark.parametrize(('mode', 'phase'), [('Verified', 'plan'), ('Maintenance', 'plan-builders'),
    ('Maintenance', 'plan-public-layers'), ('Maintenance', 'plan-retired-candidate-copies')])
def test_closed_batch_cannot_enable_other_modes_or_cleanup_apis(mode, phase):
    with pytest.raises(retirer.RetirementError, match='CLOSED_RUNTIME_MAINTENANCE_PHASE'):
        retirer.closed_runtime_cli(SimpleNamespace(jar_batch=retirer.CLOSED_RUNTIME_BATCH, mode=mode, phase=phase))


def test_closed_runtime_controller_binds_capture_full_batches_and_all_original_receipts():
    script = MODULE.with_suffix('.ps1').read_text(encoding='utf8')
    branch = script.split("if($CanonicalBatch -ceq 'ClosedRuntime') {", 1)[1].split("if($CanonicalBatch -ceq 'RetiredCopies') {", 1)[0]
    phases = [branch.index("Invoke-NativeJarPhase '" + phase + "'") for phase in
        ('plan-closed-builders', 'apply-closed-builders', 'plan-recent-fixtures', 'apply-recent-fixtures', 'plan', 'apply', 'plan-canonical', 'apply-canonical')]
    assert phases == sorted(phases)
    assert "finally {Copy-NativeJarEvidence (Invoke-NativeJarPhase 'inspect')}" in branch
    for guard in ('candidateCount -eq 2', 'deletedFiles -eq 2', 'deletedFiles=4', '$proof.retainedQuarantinePaths',
                  '$proof.sourceArchivesDataAndReportsHaveNoDeletionApi', '$deleted[0].sha256', '$deleted[0].keeperVerifiedAfter'):
        assert guard in branch
    assert '--jar-batch failed-204-207' in script
    reader = script.split("$reader=@'\n", 1)[1].split("\n'@", 1)[0]; syntax = ast.parse(reader)
    selected = next(node for node in syntax.body if isinstance(node, ast.If)
        and ast.dump(node.test) == ast.dump(ast.parse("batch=='ClosedRuntime'", mode='eval').body))
    approved = ast.literal_eval(selected.body[0].value)
    assert [row[0] for row in approved] == [204, 207]
    assert {row[1] for row in approved} == {row['commit'] for row in retirer.CLOSED_RUNTIME_JARS.values()}


@pytest.fixture
def closed_runtime_end_to_end(closed_runtime_case, monkeypatch):
    # Reuse the existing full resource-contract fixtures, then exercise the real
    # parser, descriptor, reference audits, rm callbacks and all four CI stages.
    from tests_python import test_historical_builder_retirement as builder_contract
    from tests_python import test_historical_mysql_fixture_retirement as mysql_contract
    state = closed_runtime_case; resources = builder_contract.resources
    cleanup_spec = importlib.util.spec_from_file_location('closed_chain_cleanup', MODULE.with_name('cleanup-ecs-builds.py'))
    cleanup = importlib.util.module_from_spec(cleanup_spec); cleanup_spec.loader.exec_module(cleanup)
    objects, commands, snapshots = {}, [], []
    registry = copy.deepcopy(retirer.CLOSED_RUNTIME_BUILDERS)
    resource_registry = copy.deepcopy(resources.CLOSED_RUNTIME_BUILDER_CONTROLS)
    fixture_row = mysql_contract.fixture.__wrapped__()
    first = state.request['candidates'][0]; tag = first['release']; context = {k: first[k] for k in ('release','commit','sourceSha256')}
    work = state.binaries[tag][0].parent; data = work / 'mysql-data'; data.mkdir(mode=0o700)
    (data / 'original-page').write_bytes(b'private synthetic database page retained')
    old_data = fixture_row.owner['dataDirectory']; new_data = str(data)
    owner = json.loads((state.root / first['controls']['fixtureOwner']['path']).read_bytes())
    fixture_row.owner.update(owner); fixture_row.owner.update(dataDirectory=new_data, image='sha256:'+'f'*64,
        port=43127, binaryLoggingDisabled=True, rootPassword='synthetic-private-password')
    fixture_row.cleanup.update(context)
    fixture_row.cleanup.update(identity=state.request['identity'], containerId=owner['containerId'],
        sourceContainerUntouched=owner['sourceContainerId'], dataDirectoryRetained=new_data)
    fixture_row.row = json.loads(json.dumps(fixture_row.row).replace(old_data,new_data))
    fixture_row.row.update(Id=owner['containerId'], Name='/'+owner['containerName'])
    fixture_row.row['Config']['Labels'] = {'io.doorhandle.compact-fixtures':owner['token'],
        'io.doorhandle.release':tag,'io.doorhandle.source':context['sourceSha256']}
    fixture_row.row['Config']['Cmd'].insert(6,'--skip-log-bin')
    for role,value in [('fixtureOwner',fixture_row.owner),('fixtureCleanup',fixture_row.cleanup)]:
        ref=first['controls'][role]; body=encoded(value); (state.root/ref['path']).write_bytes(body)
        ref.update(bytes=len(body),sha256=sha(body))
    objects[owner['containerId']] = fixture_row.row
    metadata=[data.stat().st_dev,data.stat().st_ino,stat.S_IFDIR|0o700,999,999]
    monkeypatch.setattr(retirer,'fixture_data_metadata',lambda _root,path: list(metadata) if path==str(data) else pytest.fail('Unexpected database path'))
    for index,row in enumerate(state.request['candidates']):
        tag=row['release']; context={k:row[k] for k in ('release','commit','sourceSha256')}; fixed=registry[tag]
        # Synthetic IDs prevent these unit callbacks from addressing a live ECS object.
        fixed['containerId'] = ('a' if index==0 else 'b')*64
        model=builder_contract.fixture_state((tag,context['commit'],fixed['containerId'],fixed['ownerToken']))
        model.context.update(context); model.tools.update(context); model.summary.update(context)
        directory=state.root/'inbox'/tag/'candidate-build-tools';directory.mkdir(mode=0o700)
        proof=retirer.source_proof(state.root,tag,context['commit'],context['sourceSha256'],builder_helpers=True,canonical_jar=True)
        model.helpers=proof['builderHelperSha256']; model.tools.update(helperSha256=model.helpers['compact-build-resources.py'],
            imageInputsHelperSha256=model.helpers['compact-image-inputs.py'])
        model.row['Config']['Labels']['io.doorhandle.source']=context['sourceSha256']
        model.tools['resourceEvidence']['file']=str(directory/'resource-summary.json')
        model.row['State']['ExitCode']=model.summary['cleanup']['builderExitCode']=1
        model.row['Mounts']=model.row['Mounts'][:1];builder_contract.refresh_references(model)
        for role,name in [('tools','tools.json'),('summary','resource-summary.json'),('measurement','official-layer-measurements.json')]:
            body=builder_contract.raw(getattr(model,role));file=directory/name;file.write_bytes(body);file.chmod(0o600)
            fixed[role+'Sha256']=sha(body)
        for role,name in [('preparation','ecs-tool-preparation.json'),('transport','candidate-build-tools-transport.json')]:
            value={**context,'identity':state.request['identity'],'status':'PREPARED' if role=='preparation' else 'AVAILABLE'}
            if role=='preparation':value['candidateBuilderTools']={'file':str(directory/'tools.json'),'sha256':fixed['toolsSha256']}
            else:value.update(admission={'identity':state.request['identity']},buildkitArchive={'sha256':retirer.PUBLIC_ARCHIVE_SHA})
            body=encoded(value);file=state.root/'inbox'/state.request['current']['release']/'native-jar-duplicate-controls'/tag/name
            file.write_bytes(body);file.chmod(0o600);fixed[role+'Sha256']=sha(body)
        resource_registry[tag]={**{k:context[k] for k in ('commit','sourceSha256')},
            **{k:fixed[k] for k in ('toolsSha256','summarySha256','measurementSha256','containerId','ownerToken')}}
        objects[model.row['Id']]=model.row
    monkeypatch.setattr(retirer,'CLOSED_RUNTIME_BUILDERS',registry)
    monkeypatch.setattr(resources,'CLOSED_RUNTIME_BUILDER_CONTROLS',resource_registry)
    monkeypatch.setattr(resources,'CLOSED_RUNTIME_BUILDER_HELPERS',dict(proof['builderHelperSha256']))
    monkeypatch.setattr(resources,'CLOSED_RUNTIME_BUILDER_RECIPE_SHA256',proof['transportRecipeSha256'])
    monkeypatch.setitem(resources.RECENT_MYSQL_FIXTURE_SOURCES,first['release'],(first['commit'],proof['transportRecipeSha256']))
    monkeypatch.setitem(resources.RECENT_MYSQL_HELPERS,first['release'],dict(proof['builderHelperSha256']))
    monkeypatch.setitem(resources.RECENT_MYSQL_FIXTURE_ARCHIVE_SHA256,first['release'],first['sourceSha256'])
    second=state.request['candidates'][1]; ref=second['controls']['fixtureOwner']; file=state.root/ref['path']
    legacy=json.loads(file.read_bytes());legacy.pop('containerName');legacy.pop('dataDirectory')
    body=encoded(legacy);file.write_bytes(body);ref.update(bytes=len(body),sha256=sha(body))
    codec=copy.deepcopy(retirer.CLOSED_207_CODEC);codec.update(ownerSha256=sha(body),
        cleanupSha256=second['controls']['fixtureCleanup']['sha256'],producerSha256=proof['transportRecipeSha256'])
    for role,value in [('plan',{'kind':'doorhandle-controlled-preparer-phase'}),('admission',{'status':'FAIL_CLOSED',
        'phase':'fixture-clone','action':'STOP_OWNED_ATTEMPT','actualProbe':{'sourceCommit':second['commit']}})]:
        body=encoded(value);file=state.binaries[second['release']][0].parent/('resource-phase-04-fixture-clone-'+role+'.json')
        file.write_bytes(body);file.chmod(0o600);codec[role+'Sha256']=sha(body)
    monkeypatch.setattr(retirer,'CLOSED_207_CODEC',codec)
    def docker(*args):
        if args[0]=='inspect':return encoded([objects[args[1]]])
        assert args[0]=='rm' and len(args)==2 and args[1] in objects
        commands.append(args);del objects[args[1]];return args[1].encode()
    monkeypatch.setattr(retirer,'builder_container_ids',lambda:list(objects))
    monkeypatch.setattr(retirer,'builder_docker',docker)
    def snapshot():
        result=[(cid,row['State']['Running'],row['State']['Restarting'],row['State']['Pid'],
            row['Config']['Labels'].get('io.doorhandle.release'),None,row['Mounts']) for cid,row in objects.items()]
        snapshots.append(result);return result
    monkeypatch.setattr(cleanup,'docker_snapshot',snapshot)
    monkeypatch.setattr(cleanup,'process_references',lambda checkout,**kwargs:None)
    modules={'builder':resources,'cleanup':cleanup}
    state.raw=retirer.canonical(state.request);state.options['request_sha256']=sha(state.raw)
    # No pre-synthesized stage success survives this end-to-end attempt.
    for stem in ('native-builder-retirement','native-jar-duplicate-fixture-object'):
        for suffix in ('-plan.json','-receipt.json','-journal.jsonl'):(state.fixture_receipt.parent/(stem+suffix)).unlink()
    def quiescence(checkout,tag,token):cleanup.quiescent({'checkout':checkout,'token':token},tag,snapshot(),include_inbox=True)
    state.options['quiescence']=quiescence
    return SimpleNamespace(state=state,modules=modules,objects=objects,commands=commands,snapshots=snapshots,
        database=data,metadata=metadata,legacy=legacy)


@pytest.mark.parametrize('mode',['complete','builders-retained','fixture-restarted'])
def test_actual_v1_missing_fields_and_live_builder_inventory_cross_every_retirement_stage(closed_runtime_end_to_end,monkeypatch,mode):
    case=closed_runtime_end_to_end;state=case.state;folder=state.fixture_receipt.parent
    assert 'containerId' in case.legacy and case.legacy['containerId'] is None
    assert 'containerName' not in case.legacy and 'dataDirectory' not in case.legacy and case.legacy['schemas']==[]
    local=copy.deepcopy(state.request)
    for row in local['candidates']:row['controls']={k:v for k,v in row['controls'].items() if k in retirer.UPLOADED_NAMES}
    local_raw=retirer.canonical(local)
    captured,skipped=retirer.capture_request(state.root,local_raw,local_spec_sha256=sha(local_raw),
        expected_current=state.request['current'],identity=state.request['identity'],canonical_jar=True,closed_runtime=True)
    assert skipped==[] and captured==state.request
    options={k:v for k,v in state.options.items() if k!='quiescence'};options['modules']=case.modules
    if mode=='fixture-restarted':
        original=case.modules['cleanup'].docker_snapshot
        def restarted_snapshot():
            rows=original();cid=retirer.CLOSED_RUNTIME_JARS['ci-204-24f8eb4b02bf']['containerId']
            return [(row[0],True,row[2],123,*row[4:]) if row[0]==cid else row for row in rows]
        monkeypatch.setattr(case.modules['cleanup'],'docker_snapshot',restarted_snapshot)
    plan=retirer.plan_builders(state.root,state.raw,**options)
    if mode=='fixture-restarted':
        assert plan['skipped'] and case.commands==[]
        with pytest.raises(retirer.RetirementError):retirer.apply_builders(state.root,state.raw,plan,plan_sha256=sha(retirer.canonical(plan)),**options)
        assert all(target.exists() and keeper.exists() for target,keeper,_ in state.binaries.values());return
    assert len(plan['candidates'])==2 and plan['skipped']==[]
    if mode=='builders-retained':
        # A previous success receipt alone cannot waive a newly present builder.
        fake={'kind':'doorhandle-historical-builder-retirement-receipt','current':state.request['current'],
            'identity':state.request['identity'],'requestSha256':sha(state.raw),'closedJarBatch':retirer.CLOSED_RUNTIME_BATCH,
            'scope':'CLOSED_RUNTIME_BUILDERS','status':'REMOVED','failure':None,'skipped':[],
            'removed':[{'containerId':row['containerId']} for row in retirer.CLOSED_RUNTIME_BUILDERS.values()],
            'alreadyAbsent':[],'retiredMysqlObjects':[],'jarDeletionPerformed':False,'mysqlDataDirectoriesPreserved':True,
            'imagesPreserved':True,'volumesPreserved':True,'directoriesPreserved':True}
        retain_closed_phase(folder,'native-builder-retirement',plan,fake)
        fixture_plan=retirer.plan_recent_fixtures(state.root,state.raw,**options)
        assert fixture_plan['skipped'] and case.commands==[]
        with pytest.raises(retirer.RetirementError):retirer.apply_recent_fixtures(state.root,state.raw,fixture_plan,plan_sha256=sha(retirer.canonical(fixture_plan)),**options)
        assert all(target.exists() and keeper.exists() for target,keeper,_ in state.binaries.values());return
    result=retirer.apply_builders(state.root,state.raw,plan,plan_sha256=sha(retirer.canonical(plan)),**options)
    assert result['status']=='REMOVED' and len(result['removed'])==2 and result['retiredMysqlObjects']==[]
    retain_closed_phase(folder,'native-builder-retirement',plan,result)
    fixture_plan=retirer.plan_recent_fixtures(state.root,state.raw,**options)
    assert len(fixture_plan['candidates'])==1 and len(fixture_plan['absent'])==1 and fixture_plan['skipped']==[]
    fixture=retirer.apply_recent_fixtures(state.root,state.raw,fixture_plan,plan_sha256=sha(retirer.canonical(fixture_plan)),**options)
    assert fixture['status']=='REMOVED' and fixture['noObject']==['ci-207-eb286c623177']
    retain_closed_phase(folder,'native-jar-duplicate-fixture-object',fixture_plan,fixture)
    first=retirer.plan(state.root,state.raw,**state.options)
    copies=retirer.apply(state.root,state.raw,first,plan_sha256=sha(retirer.canonical(first)),**state.options)
    assert copies['status']=='REMOVED' and len(copies['deleted'])==2
    retain_closed_phase(folder,'native-jar-duplicate',first,copies)
    second=retirer.plan(state.root,state.raw,canonical_jar=True,**state.options)
    final=retirer.apply(state.root,state.raw,second,plan_sha256=sha(retirer.canonical(second)),canonical_jar=True,**state.options)
    assert final['status']=='REMOVED' and len(final['deleted'])==2 and len(case.commands)==3 and case.objects=={}
    assert [args[1] for args in case.commands[:2]]==[row['containerId'] for row in retirer.CLOSED_RUNTIME_BUILDERS.values()]
    assert case.database.is_dir() and (case.database/'original-page').read_bytes()==b'private synthetic database page retained'
    assert all(not target.exists() and not keeper.exists() for target,keeper,_ in state.binaries.values())


@pytest.mark.parametrize('damage',['plan-missing','receipt-missing','journal-missing','plan-sha-drift'])
def test_fixture_stage_requires_every_original_builder_predecessor(closed_runtime_case,damage):
    state=closed_runtime_case;folder=state.fixture_receipt.parent
    suffix='-plan.json' if damage.startswith('plan') else '-receipt.json' if damage.startswith('receipt') else '-journal.jsonl'
    file=folder/('native-builder-retirement'+suffix)
    if damage.endswith('missing'):file.unlink()
    else:file.write_bytes(file.read_bytes()+b' ')
    options={k:v for k,v in state.options.items() if k!='quiescence'};options['modules']={}
    with pytest.raises((retirer.RetirementError,OSError)):
        retirer.plan_recent_fixtures(state.root,state.raw,**options)
    assert all(target.exists() and keeper.exists() for target,keeper,_ in state.binaries.values())


@pytest.mark.parametrize('damage',['owner-drift','cleanup-drift','producer-drift','clone-plan-missing',
    'clone-admission-drift','same-tag-database','rewritten-explicit-nulls'])
def test_207_legacy_compatibility_cannot_admit_unknown_originals_or_database_objects(closed_runtime_end_to_end,monkeypatch,damage):
    case=closed_runtime_end_to_end;state=case.state;row=state.request['candidates'][1];work=state.binaries[row['release']][0].parent
    if damage in ('owner-drift','cleanup-drift','rewritten-explicit-nulls'):
        role='fixtureCleanup' if damage=='cleanup-drift' else 'fixtureOwner';ref=row['controls'][role];file=state.root/ref['path']
        body=file.read_bytes()+b' '
        if damage=='rewritten-explicit-nulls':
            value=json.loads(body);value.update(containerName=None,dataDirectory=None);body=encoded(value)
        file.write_bytes(body);ref.update(bytes=len(body),sha256=sha(body))
    elif damage=='producer-drift':monkeypatch.setitem(retirer.CLOSED_207_CODEC,'producerSha256','0'*64)
    elif damage=='clone-plan-missing':(work/'resource-phase-04-fixture-clone-plan.json').unlink()
    elif damage=='clone-admission-drift':
        file=work/'resource-phase-04-fixture-clone-admission.json';file.write_bytes(file.read_bytes()+b' ')
    else:
        cid='c'*64;case.objects[cid]={'Id':cid,'Name':'/unexpected-database','Config':{'Labels':{
            'io.doorhandle.release':row['release'],'io.doorhandle.compact-fixtures':case.legacy['token']}}}
    with pytest.raises((retirer.RetirementError,OSError)):
        retirer.capture_recent_fixture(state.root,state.request,row,case.modules['builder'],closed_runtime=True)
    assert case.commands==[] and all(target.exists() and keeper.exists() for target,keeper,_ in state.binaries.values())


@pytest.mark.parametrize('phase',['plan-closed-builders','apply-closed-builders'])
def test_closed_builder_cli_never_infers_the_explicit_batch_from_phase_name(phase):
    with pytest.raises(retirer.RetirementError,match='CLOSED_RUNTIME_EXPLICIT_POLICY'):
        retirer.closed_runtime_cli(SimpleNamespace(jar_batch=None,mode='Maintenance',phase=phase))

@pytest.fixture
def failed_native_case(canonical_case, monkeypatch):
    state = canonical_case
    monkeypatch.setattr(retirer, 'FAILED_NATIVE_FIRST_BUILD', 1)
    monkeypatch.delitem(retirer.APPROVED_OLD, state.copies.tag)
    monkeypatch.delitem(retirer.APPROVED_CANONICAL_SOURCES, state.copies.tag)
    monkeypatch.setattr(retirer, 'FAILED_NATIVE_PUBLICATION_RECIPES',
        frozenset({tuple(sha(raw) for raw in state.publication.values())}))
    recipe = b"def prepare(self):\n jar = canonical(self.inbox / 'application.jar')\n uploaded = self.work / 'candidate-app.jar'\n shutil.copyfile(jar, uploaded)\ndef start_mysql(self, image):\n return image\n"
    archive = source_archive(state.copies, recipe=recipe, publication=state.publication)
    state.bundle.context['sourceSha256'] = sha(archive.read_bytes())
    state.request['candidates'][0]['sourceSha256'] = state.bundle.context['sourceSha256']
    for value in state.bundle.values.values(): value.update(state.bundle.context)
    for role, raw in documents(state.bundle).items():
        path = state.copies.root / state.paths[role]; path.write_bytes(raw)
        state.request['candidates'][0]['controls'][role].update(bytes=len(raw), sha256=sha(raw))
    return state


@pytest.mark.parametrize('phase', ['capture-canonical-request', 'plan-recent-fixtures', 'apply-recent-fixtures',
                                  'plan-failed-native-builders', 'apply-failed-native-builders',
                                  'plan', 'apply', 'plan-canonical', 'apply-canonical', 'inspect'])
def test_failed_native_cli_is_one_reusable_maintenance_selection_not_a_numbered_batch(phase):
    args = SimpleNamespace(jar_batch=retirer.FAILED_NATIVE_BATCH, mode='Maintenance', phase=phase)
    assert retirer.failed_native_cli(args) is True and retirer.closed_runtime_cli(args) is False


@pytest.mark.parametrize('phase', ['capture-request', 'plan-builders', 'plan-closed-builders',
                                  'apply-public-layers', 'apply-generated-image-archives', 'apply-python-build-cache'])
def test_failed_native_selection_cannot_authorize_unrelated_old_resource_permissions(phase):
    with pytest.raises(retirer.RetirementError, match='MAINTENANCE_ONLY'):
        retirer.failed_native_cli(SimpleNamespace(jar_batch=retirer.FAILED_NATIVE_BATCH, mode='Maintenance', phase=phase))


def test_failed_native_selection_never_runs_as_a_verified_source_cleanup():
    with pytest.raises(retirer.RetirementError, match='MAINTENANCE_ONLY'):
        retirer.failed_native_cli(SimpleNamespace(jar_batch=retirer.FAILED_NATIVE_BATCH, mode='Verified', phase='plan'))


@pytest.mark.parametrize('epoch_build', [1, 204, 207, 220])
def test_failed_native_selection_never_reconsumes_retired_historical_epochs(canonical_case, epoch_build):
    state = canonical_case; request = copy.deepcopy(state.request)
    current = {**state.current, 'release': 'ci-300-' + 'f' * 12}
    request.update(current=current, protectedReleases=[current['release']])
    request['candidates'][0]['release'] = 'ci-' + str(epoch_build) + '-' + 'a' * 12
    raw = encoded(request)
    with pytest.raises(retirer.RetirementError, match='EPOCH_REQUIRED'):
        retirer.failed_native_request(raw, sha(raw), current, state.bundle.identity)


@pytest.mark.parametrize('canonical_first', [False, True])
def test_failed_native_policy_is_explicit_and_never_widens_default_historical_apis(failed_native_case, canonical_first):
    state = failed_native_case; raw, options = canonical_options(state)
    options['canonical_jar'] = canonical_first
    with pytest.raises(retirer.RetirementError, match='ONLY_REVIEWED'):
        retirer.approved_request(raw, sha(raw), state.current, state.bundle.identity, canonical_jar=canonical_first)
    assert state.copies.target.exists() and state.copies.keeper.exists()


@pytest.mark.parametrize('terminal', ['FAILURE', 'ABORTED'])
def test_failed_native_retention_deletes_copy_then_canonical_with_real_original_admission(failed_native_case, terminal):
    state = failed_native_case; path = state.copies.root / state.paths['buildXml']
    raw_terminal = flow_xml(state.bundle.context, result=terminal); path.write_bytes(raw_terminal)
    state.request['candidates'][0]['controls']['buildXml'].update(bytes=len(raw_terminal), sha256=sha(raw_terminal))
    raw, options = canonical_options(state); options.update(canonical_jar=False, failed_native=True)
    before_source = (state.copies.keeper.parent / 'source.tar.gz').read_bytes()
    prepared = retirer.plan(state.copies.root, raw, **options)
    assert prepared['failedNativePolicy'] == retirer.FAILED_NATIVE_BATCH and prepared['skipped'] == []
    result = retirer.apply(state.copies.root, raw, prepared, plan_sha256=sha(retirer.canonical(prepared)), **options)
    assert result['status'] == 'REMOVED' and result['inboxKeepersPreserved'] is True
    assert not state.copies.target.exists() and state.copies.keeper.read_bytes() == state.copies.payload
    options['canonical_jar'] = True
    prepared = retirer.plan(state.copies.root, raw, **options)
    assert prepared['skipped'] == []
    result = retirer.apply(state.copies.root, raw, prepared, plan_sha256=sha(retirer.canonical(prepared)), **options)
    assert result['status'] == 'REMOVED' and result['binaryDisposition'] == 'RETIRED'
    assert result['failedNativePolicy'] == retirer.FAILED_NATIVE_BATCH and not state.copies.keeper.exists()
    assert (state.copies.keeper.parent / 'source.tar.gz').read_bytes() == before_source
    assert result['sourceArchivesDataAndReportsHaveNoDeletionApi'] is True
    assert result['testsRunByRetirement'] is False and result['binaryRebuildByteIdentityClaimed'] is False


@pytest.mark.parametrize('role,field,value', [('fixtureOwner','phase','PREPARED'),
    ('fixtureCleanup','status','FAILED_OR_UNKNOWN'),('fixtureCleanup','sourceDumpAndEvidenceRetained',False)])
def test_failed_native_retention_requires_actual_final_cleanup_not_a_passing_post_claim(failed_native_case, role, field, value):
    state = failed_native_case; path = state.copies.root / state.paths[role]
    data = json.loads(path.read_bytes()); data[field] = value; raw_control = encoded(data); path.write_bytes(raw_control)
    state.request['candidates'][0]['controls'][role].update(bytes=len(raw_control), sha256=sha(raw_control))
    raw, options = canonical_options(state); options['failed_native'] = True
    prepared = retirer.plan(state.copies.root, raw, **options)
    assert prepared['candidates'] == [] and len(prepared['skipped']) == 1
    assert state.copies.target.exists() and state.copies.keeper.exists()


def test_failed_native_incomplete_plan_cannot_turn_rejected_ownership_into_success(failed_native_case):
    state = failed_native_case; raw, options = canonical_options(state); options['failed_native'] = True
    prepared = retirer.plan(state.copies.root, raw, **options)
    prepared['candidates'] = []
    with pytest.raises(retirer.RetirementError, match='COMPLETE_FAILED_NATIVE_PLAN'):
        retirer.apply(state.copies.root, raw, prepared, plan_sha256=sha(retirer.canonical(prepared)), **options)
    assert state.copies.target.exists() and state.copies.keeper.exists()


def test_failed_native_already_absent_copy_is_observed_not_counted_as_a_new_deletion(failed_native_case):
    state = failed_native_case; state.copies.target.unlink()
    raw, options = canonical_options(state); options.update(canonical_jar=False, failed_native=True)
    prepared = retirer.plan(state.copies.root, raw, **options)
    assert prepared['candidates'] == [] and prepared['candidateAllocatedBytes'] == 0
    assert prepared['skipped'] == [{'release':state.copies.tag,'reason':'FAILED_NATIVE_COPY_NOT_PRESENT'}]
    result = retirer.apply(state.copies.root, raw, prepared, plan_sha256=sha(retirer.canonical(prepared)), **options)
    assert result['status'] == 'NO_ACTION' and result['deleted'] == [] and state.copies.keeper.exists()


@pytest.mark.parametrize('source', ['Jenkinsfile.ecs-monolith','script/jenkins/pipeline.ps1'])
def test_failed_native_retention_only_accepts_reviewed_publication_behavior(failed_native_case, source):
    state = failed_native_case; publication = dict(state.publication); publication[source] += b'unknown side effect\n'
    archive = source_archive(state.copies, publication=publication)
    with pytest.raises(retirer.RetirementError, match='UNPUBLISHED_SOURCE'):
        retirer.source_proof(state.copies.root,state.copies.tag,state.bundle.context['commit'],sha(archive.read_bytes()),
                             canonical_jar=True,failed_native=True)


@pytest.mark.parametrize('changed', [None, 'jenkins', 'pipeline', 'mixed-reviewed', 'default-api'])
def test_failed_native_238_control_observer_recipe_requires_its_exact_reviewed_pair(tmp_path, monkeypatch, changed):
    # Isolate the reviewed-hash lookup with synthetic publication payloads; the
    # archive, fixed commit, copy recipe and producer are still read normally.
    # The two hashes were bound to #238's retained archive and fixed 73ce5aef bytes.
    commit = '73ce5aeff86201d9b2776159903acd5907c8420a'; tag = 'ci-238-' + commit[:12]
    root = tmp_path / 'ci'; folder = root / 'inbox' / tag; folder.mkdir(parents=True)
    publication = {'Jenkinsfile.ecs-monolith': b'synthetic retained 238 Jenkinsfile',
                   'script/jenkins/pipeline.ps1': b'synthetic retained 238 control-observer pipeline'}
    expected = dict(zip(publication, (
        '97690cb956375cb1e98f1f1f98a7b3a3ec0e8d73d99a8ee0f28b0f5634fde180',
        'ee04de044bf6c0516fdad24f1f960a29ddf9dbfe613321fd3f8c4f21c4177b05')))
    bound_hashes = {body: expected[name] for name, body in publication.items()}
    if changed == 'mixed-reviewed':
        bound_hashes[publication['Jenkinsfile.ecs-monolith']] = '7b6c1792393615eff3f0049868573c2d5bf247e0ad9dc150b79dfe9ca62741ca'
    if changed in ('jenkins', 'pipeline'):
        name = 'Jenkinsfile.ecs-monolith' if changed == 'jenkins' else 'script/jenkins/pipeline.ps1'
        publication[name] += b' unknown publication behavior'
    original_digest = retirer.digest_bytes
    monkeypatch.setattr(retirer, 'digest_bytes', lambda raw: bound_hashes.get(raw, original_digest(raw)))
    archive = source_archive(SimpleNamespace(keeper=folder / 'application.jar'), comment=commit,
                             recipe=(MODULE.parent / 'prepare-compact-fixtures.py').read_bytes(), publication=publication)
    options = dict(canonical_jar=True, failed_native=changed != 'default-api')
    if changed is not None:
        with pytest.raises(retirer.RetirementError, match='CLOSED_REVIEWED_UNPUBLISHED_SOURCE_REQUIRED'):
            retirer.source_proof(root, tag, commit, sha(archive.read_bytes()), **options)
    else:
        proof = retirer.source_proof(root, tag, commit, sha(archive.read_bytes()), **options)
        assert proof['unpublishedPipelineSourceSha256'] == expected
        assert proof['failedNativePolicy'] == 'failed-native-retention-v1'
        assert proof['mysqlFixtureStartSourceSha256'] == 'f4d667ed1532911ac835dd0e70b1d5ff41ca02ffdc012f9762b46220cd7123a4'
        assert proof['mysqlFixtureMemoryLimitBytes'] == 3 * 1024 ** 3
    assert archive.is_file() and tag not in retirer.APPROVED_OLD and tag not in retirer.PUBLIC_LAYER_TAGS


def test_failed_native_controller_uses_original_jenkins_terminal_and_honest_guarded_recovery_custody():
    script = (MODULE.parent / 'retire-failed-native-jar-duplicates.ps1').read_text()
    reader = script.split("$reader=@'",1)[1].split("\n'@",1)[0]; ast.parse(reader)
    assert "221<=int(p.name)<current_number" in reader and "('FAILURE','ABORTED')" in reader
    assert "'PRODUCTION_RELEASE_ENABLED':'false'" in reader and "'ACTION':'verify-runtime'" in reader
    assert "ACTUAL_GUARDED_RECOVERY_PUBLIC_RECEIPT" in reader
    assert "GUARDED_RECOVERY_PUBLIC_RECEIPT_DIFFERS" in reader and "RETAINED_JENKINS_BINARY_DIFFERS" in reader
    # Match the complete top-level dispatch line, not the earlier inline flag setup.
    branch = script.split("\nif($CanonicalBatch -ceq 'FailedNative') {\n",1)[1].split("\n}\nif($CanonicalBatch -ceq 'ClosedRuntime') {",1)[0]
    assert "@('fixtures','plan-recent-fixtures','apply-recent-fixtures')" in branch
    assert "@('copies','plan','apply')" in branch and "@('canonical','plan-canonical','apply-canonical')" in branch
    assert "plan-closed-builders" not in branch and "plan-public-layers" not in branch
    assert "finally {Copy-NativeJarEvidence (Invoke-NativeJarPhase 'inspect')}" in branch
    assert "$failedPlans[$step[0]].plan.sha256" in branch

@pytest.mark.parametrize('guarded', [False, True])
def test_actual_controller_reader_admits_failed_native_argument_and_preserves_guarded_receipt_origin(tmp_path, monkeypatch, capsys, guarded):
    source = (MODULE.parent / 'retire-failed-native-jar-duplicates.ps1').read_text()
    reader = source.split("$reader=@'\n",1)[1].split("\n'@",1)[0]
    jhome=tmp_path/'jhome'; builds=jhome/'jobs/doorhandle-java/builds'; builds.mkdir(parents=True)
    retained=tmp_path/'retained';retained.mkdir()
    commit='f'*40;current='ci-300-'+commit[:12];archive=tmp_path/'source.tar.gz'
    with tarfile.open(archive,'w:gz',format=tarfile.PAX_FORMAT,pax_headers={'comment':commit}) as out:
        for name in ('script/jenkins/retire-failed-native-jar-duplicates.py','script/jenkins/cleanup-ecs-builds.py',
                     'script/jenkins/verify-remote.py','script/docker/compact-build-resources.py'):
            item=tarfile.TarInfo(name);item.size=1;out.addfile(item,io.BytesIO(b'x'))
    if guarded:
        context={'release':'ci-224-'+'a'*12,'commit':'a'*40,'sourceSha256':'b'*64}
        build=builds/'224';artifacts=build/'archive/artifacts';artifacts.mkdir(parents=True)
        (build/'build.xml').write_bytes(flow_xml(context))
        jar=b'retained original Jenkins application';(artifacts/'application.jar').write_bytes(jar)
        (artifacts/'release.json').write_bytes(encoded({**context,'applicationJarSha256':sha(jar)}))
        (artifacts/'local-build.json').write_bytes(encoded({'kind':'synthetic-local-build'}))
        for name in ('ecs-tool-preparation.json','candidate-build-tools-transport.json'):
            (artifacts/name).write_bytes(encoded({**context,'kind':'synthetic-original-builder-reference'}))
        public={'status':'STOPPED','commit':context['commit'],'release':context['release'],
                'cleanupReceipt':CI_ROOT+'/verification/'+context['release']+'/checkout/work/compact-fixtures/cleanup-receipt.json',
                'cleanupReceiptSha256':'c'*64}
        (retained/'ci-224-recovery-cleanup-unit.json').write_bytes(encoded(public))
    monkeypatch.setattr(sys,'argv',['reader',str(archive),commit,str(retained),str(jhome),CI_ROOT,current,'FailedNative'])
    exec(compile(reader,'actual-controller-reader','exec'),{})
    result=json.loads(capsys.readouterr().out)
    assert result['skipped']==[] and len(result['rows'])==(1 if guarded else 0)
    if guarded:
        row=result['rows'][0]
        assert row['release']==context['release'] and row['commit']==context['commit']
        assert {value['file'] for value in result['builderFiles']}=={'ecs-tool-preparation.json','candidate-build-tools-transport.json'}
        assert result['custody'][0]['controls']['fixtureCleanupPublic']=={
            'origin':'ACTUAL_GUARDED_RECOVERY_PUBLIC_RECEIPT',
            'bytes':len(encoded(public)), 'sha256':sha(encoded(public))}
        assert Path(row['files']['fixtureCleanupPublic']['source']).parent==retained
        assert not (artifacts/'fixture-cleanup.json').exists()
        assert (artifacts/'application.jar').read_bytes()==jar


@pytest.fixture
def exact_failed_native_controller_reader(tmp_path, bundle, monkeypatch):
    controller = (MODULE.parent / 'retire-failed-native-jar-duplicates.ps1').read_text(encoding='utf8')
    reader = controller.split("$reader=@'\n", 1)[1].split("\n'@", 1)[0]
    root = tmp_path / 'ci'; root.mkdir(); jhome = tmp_path / 'jhome'
    retained = tmp_path / 'retained'; retained.mkdir()
    current = {'release': 'ci-300-' + 'f' * 12, 'commit': 'f' * 40, 'sourceSha256': 'e' * 64}
    contexts = {}; originals = {}; jars = {}; source = tmp_path / 'source.tar.gz'
    def store(path, raw):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw); path.chmod(0o600)
        return path
    with tarfile.open(source, 'w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': current['commit']}) as archive:
        for name in ('script/jenkins/retire-failed-native-jar-duplicates.py', 'script/jenkins/cleanup-ecs-builds.py',
                     'script/jenkins/verify-remote.py', 'script/docker/compact-build-resources.py'):
            member = tarfile.TarInfo(name); member.size = 1; archive.addfile(member, io.BytesIO(b'x'))
    publication = {'Jenkinsfile.ecs-monolith': b'synthetic reviewed no-publish recipe',
                   'script/jenkins/pipeline.ps1': b'synthetic reviewed native verifier return'}
    monkeypatch.setattr(retirer, 'FAILED_NATIVE_PUBLICATION_RECIPES', frozenset({tuple(sha(raw) for raw in publication.values())}))
    for number in (237, 238):
        context = {'release': 'ci-' + str(number) + '-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}
        inbox = root / 'inbox' / context['release']; inbox.mkdir(parents=True)
        keeper = store(inbox / 'application.jar', bundle.jar); jars[number] = keeper
        if number == 238:
            archive = source_archive(SimpleNamespace(keeper=keeper), publication=publication,
                recipe=b"def prepare(self):\n jar = canonical(self.inbox / 'application.jar')\n uploaded = self.work / 'candidate-app.jar'\n shutil.copyfile(jar, uploaded)\ndef start_mysql(self, image):\n return image\n")
            context['sourceSha256'] = sha(archive.read_bytes())
        values = copy.deepcopy(bundle.values)
        for value in values.values(): value.update(context)
        work = root / 'verification' / context['release'] / 'checkout/work/compact-fixtures'
        values['fixtureOwner']['work'] = str(work)
        values['fixtureCleanup']['dataDirectoryRetained'] = str(work / 'data')
        original = jhome / 'jobs/doorhandle-java/builds' / str(number)
        originals[number] = original; contexts[number] = context
        store(original / 'build.xml', flow_xml(context))
        store(original / 'archive/artifacts/release.json', encoded(values['release']))
        store(original / 'archive/artifacts/application.jar', bundle.jar)
        for name in ('ecs-tool-preparation.json', 'candidate-build-tools-transport.json'):
            store(original / 'archive/artifacts' / name, encoded(context))
        if number == 238:
            paths = retirer.expected_control_paths(current['release'], context['release'])
            for role in ('artifactPlan', 'fixtureOwner', 'fixtureCleanup'):
                store(root / paths[role], encoded(values[role]))
    return SimpleNamespace(reader=reader, root=root, jhome=jhome, retained=retained, source=source,
                           current=current, contexts=contexts, originals=originals, jars=jars, identity=bundle.identity, store=store)


def run_exact_failed_native_reader(value, monkeypatch, capsys, selected='', batch='FailedNative'):
    monkeypatch.setattr(sys, 'argv', ['reader', str(value.source), value.current['commit'], str(value.retained),
        str(value.jhome), str(value.root), value.current['release'], batch, 'retired-195-198-201', selected])
    exec(compile(value.reader, 'actual-exact-failed-native-reader', 'exec'), {})
    return json.loads(capsys.readouterr().out)


def capture_exact_failed_native_reader(value, result):
    rows = []
    for row in result['rows']:
        paths = retirer.expected_control_paths(value.current['release'], row['release']); controls = {}
        for role, original in row['files'].items():
            raw = Path(original['source']).read_bytes(); value.store(value.root / paths[role], raw)
            controls[role] = {'path': paths[role], 'bytes': len(raw), 'sha256': sha(raw)}
        rows.append({key: row[key] for key in ('release', 'commit', 'sourceSha256')} | {'controls': controls})
    request = {'schemaVersion': 1, 'kind': retirer.KIND + '-request', 'current': value.current,
               'identity': value.identity, 'protectedReleases': [value.current['release']], 'candidates': rows}
    if result['selectedFailedNativeBuild']:
        request['selectedFailedNativeBuild'] = result['selectedFailedNativeBuild']
    for original in result['builderFiles']:
        path = value.root / 'inbox' / value.current['release'] / 'native-jar-duplicate-controls' / original['release'] / original['file']
        value.store(path, Path(original['source']).read_bytes())
    raw = encoded(request)
    return retirer.capture_request(value.root, raw, local_spec_sha256=sha(raw), expected_current=value.current,
                                  identity=value.identity, canonical_jar=True, failed_native=True)


@pytest.mark.parametrize('selected', ['', '238'])
def test_exact_failed_native_selection_reaches_capture_without_waiving_incomplete_other_attempts(exact_failed_native_controller_reader, monkeypatch, capsys, selected):
    value = exact_failed_native_controller_reader
    result = run_exact_failed_native_reader(value, monkeypatch, capsys, selected)
    assert result['selectedFailedNativeBuild'] == selected and result['skipped'] == []
    assert [row['release'] for row in result['rows']] == [value.contexts[n]['release'] for n in ((238,) if selected else (238, 237))]
    request, skipped = capture_exact_failed_native_reader(value, result)
    assert [row['release'] for row in request['candidates']] == [value.contexts[238]['release']]
    assert skipped == ([] if selected else [{'release': value.contexts[237]['release'], 'reason': 'REQUIRED_ECS_CONTROL_MISSING_ARTIFACTPLAN'}])
    assert all(path.read_bytes() == b'synthetic reviewed candidate jar\x00\xff\n' for path in value.jars.values())


@pytest.mark.parametrize('selected', ['', '238'])
def test_actual_reader_database_verification_is_eligible_only_with_explicit_selection(exact_failed_native_controller_reader, monkeypatch, capsys, selected):
    value = exact_failed_native_controller_reader; original = value.originals[238]; context = value.contexts[238]
    (original / 'build.xml').write_bytes(with_action(flow_xml(context), 'verify'))
    folder = original / 'archive/artifacts'
    (folder / 'ecs-tool-preparation.json').write_bytes(encoded({**context, 'status': 'PREPARED'}))
    (folder / 'candidate-build-tools-transport.json').unlink()
    (folder / 'ecs-tool-preparation-transport.json').write_bytes(encoded({**context,
        'status': 'PREPARED', 'prepareCandidateBuilder': False, 'finalExitCode': 0}))
    result = run_exact_failed_native_reader(value, monkeypatch, capsys, selected)
    assert result['skipped'] == []
    assert [row['release'] for row in result['rows']] == [value.contexts[238 if selected else 237]['release']]
    assert {row['file'] for row in result['builderFiles']} == (
        {'ecs-tool-preparation.json', 'ecs-tool-preparation-transport.json'} if selected
        else {'ecs-tool-preparation.json', 'candidate-build-tools-transport.json'})


@pytest.mark.parametrize('flag', [True, 0, None])
def test_actual_reader_does_not_infer_no_builder_from_missing_or_nonboolean_transport_flag(exact_failed_native_controller_reader, monkeypatch, capsys, flag):
    value = exact_failed_native_controller_reader; original = value.originals[238]; context = value.contexts[238]
    (original / 'build.xml').write_bytes(with_action(flow_xml(context), 'verify'))
    folder = original / 'archive/artifacts'
    (folder / 'ecs-tool-preparation.json').write_bytes(encoded({**context, 'status': 'PREPARED'}))
    (folder / 'ecs-tool-preparation-transport.json').write_bytes(encoded({**context,
        'status': 'PREPARED', 'prepareCandidateBuilder': flag, 'finalExitCode': 0}))
    result = run_exact_failed_native_reader(value, monkeypatch, capsys, '238')
    assert result['rows'] == [] and result['skipped'] == [{'release': context['release'], 'reason': 'DATABASE_BUILDER_ORIGINAL_PREPARATION_REQUIRED'}]
    assert (folder / 'application.jar').is_file()


@pytest.mark.parametrize('selected,batch', [('0238','FailedNative'), ('238\n','FailedNative'), ('２３８','FailedNative'),
    ('220','FailedNative'), ('300','FailedNative'), ('301','FailedNative'), ('1000000000','FailedNative'), ('238','PublicCaches')])
def test_exact_failed_native_reader_rejects_noncanonical_wrong_epoch_current_or_other_policy(exact_failed_native_controller_reader, monkeypatch, capsys, selected, batch):
    with pytest.raises(ValueError, match='EXACT_FAILED_NATIVE_SELECTION_REQUIRED'):
        run_exact_failed_native_reader(exact_failed_native_controller_reader, monkeypatch, capsys, selected, batch)
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('changed', ['absent', 'successful', 'wrong-action', 'jar-drift'])
def test_exact_failed_native_selection_still_requires_the_selected_original_terminal_and_jar(exact_failed_native_controller_reader, monkeypatch, capsys, changed):
    value = exact_failed_native_controller_reader; original = value.originals[238]
    if changed == 'absent': selected = '239'
    else:
        selected = '238'
        if changed == 'successful': (original / 'build.xml').write_bytes(flow_xml(value.contexts[238], result='SUCCESS'))
        elif changed == 'wrong-action': (original / 'build.xml').write_bytes(with_action(flow_xml(value.contexts[238]), 'verify-controls'))
        else: (original / 'archive/artifacts/application.jar').write_bytes(b'changed retained original')
    guard = 'RETAINED_JENKINS_BINARY_DIFFERS' if changed == 'jar-drift' else 'EXACT_SELECTED_FAILED_NATIVE_BUILD_REQUIRED'
    with pytest.raises(ValueError, match=guard): run_exact_failed_native_reader(value, monkeypatch, capsys, selected)
    assert capsys.readouterr().out == '' and all(path.exists() for path in value.jars.values())


def test_exact_failed_native_selection_does_not_read_or_reclassify_an_unselected_original(exact_failed_native_controller_reader, monkeypatch, capsys):
    value = exact_failed_native_controller_reader
    unselected = value.originals[237] / 'build.xml'; unselected.write_bytes(b'incomplete unrelated original; retained unchanged')
    result = run_exact_failed_native_reader(value, monkeypatch, capsys, '238')
    assert result['skipped'] == [] and [row['release'] for row in result['rows']] == [value.contexts[238]['release']]
    with pytest.raises(ET.ParseError): run_exact_failed_native_reader(value, monkeypatch, capsys)
    assert unselected.read_bytes() == b'incomplete unrelated original; retained unchanged'


@pytest.mark.parametrize('blocked', ['publication', 'process'])
def test_exact_failed_native_capture_never_waives_later_publication_or_quiescence_guards(exact_failed_native_controller_reader, monkeypatch, capsys, blocked):
    value = exact_failed_native_controller_reader
    result = run_exact_failed_native_reader(value, monkeypatch, capsys, '238')
    request, skipped = capture_exact_failed_native_reader(value, result); assert skipped == []
    tag = value.contexts[238]['release']; raw = encoded(request); calls = []
    if blocked == 'publication': (value.root / 'releases' / tag).mkdir(parents=True)
    def quiet(checkout, actual_tag, token):
        calls.append((checkout, actual_tag, token))
        raise retirer.RetirementError('ACTIVE_FILE_DESCRIPTOR_REFERENCES_OLD_CHECKOUT')
    prepared = retirer.plan(value.root, raw, request_sha256=sha(raw), expected_current=value.current,
        identity=value.identity, quiescence=quiet, canonical_jar=True, failed_native=True)
    assert prepared['candidates'] == [] and len(prepared['skipped']) == 1
    assert bool(calls) is (blocked == 'process')
    assert all(path.exists() for path in value.jars.values())

@pytest.fixture
def real_failed_mysql_producer(tmp_path, monkeypatch):
    """Read the retained producer's real code, never import or execute it."""
    root=tmp_path/'root';folder=root/'inbox'/('ci-221-'+'a'*12);folder.mkdir(parents=True)
    recipe=(MODULE.parent/'prepare-compact-fixtures.py').read_bytes()
    publication={'Jenkinsfile.ecs-monolith':b'fixed synthetic nonpublishing workflow',
                 'script/jenkins/pipeline.ps1':b'fixed synthetic publication guard'}
    monkeypatch.setattr(retirer,'FAILED_NATIVE_PUBLICATION_RECIPES',
        frozenset({tuple(sha(raw) for raw in publication.values())}))
    artifact=SimpleNamespace(keeper=folder/'application.jar')
    context={'release':folder.name,'commit':'a'*40,'sourceSha256':None}
    spec=importlib.util.spec_from_file_location('failed_native_actual_producer_resource_tests',
        MODULE.parents[1]/'docker/compact-build-resources.py')
    resources=importlib.util.module_from_spec(spec);spec.loader.exec_module(resources)
    def prove(body):
        archive=source_archive(artifact,recipe=body,publication=publication)
        context['sourceSha256']=sha(archive.read_bytes())
        return retirer.source_proof(root,context['release'],context['commit'],context['sourceSha256'],
                                    canonical_jar=True,failed_native=True)
    return SimpleNamespace(recipe=recipe,context=context,prove=prove,resources=resources)


@pytest.mark.parametrize('parser_layout',['python39','python312'])
def test_real_failed_mysql_producer_source_binding_survives_python_function_ast_layout(real_failed_mysql_producer,monkeypatch,parser_layout):
    state=real_failed_mysql_producer
    fields=tuple(field for field in ast.FunctionDef._fields if field!='type_params')
    monkeypatch.setattr(ast.FunctionDef,'_fields',fields+(('type_params',) if parser_layout=='python312' else ()))
    original_parse=ast.parse
    def parsed(*args,**kwargs):
        tree=original_parse(*args,**kwargs)
        for node in ast.walk(tree):
            if isinstance(node,ast.FunctionDef):node.type_params=[]
        return tree
    monkeypatch.setattr(ast,'parse',parsed)
    proof=state.prove(state.recipe)
    assert proof['mysqlFixtureStartSourceSha256']==state.resources.WATCHED_MYSQL_START_SOURCE
    assert proof['mysqlFixtureMemoryLimitBytes']==3 * 1024 ** 3
    assert 'mysqlFixtureStartAstSha256' not in proof
    admitted=state.resources.recent_mysql_fixture_source(state.context,proof,failed_native=True)
    assert admitted['mysqlFixtureStartSourceSha256']==proof['mysqlFixtureStartSourceSha256']


@pytest.mark.parametrize('damage',['missing-producer','duplicate-producer','changed-command'])
def test_real_failed_mysql_producer_binding_rejects_missing_duplicate_or_changed_original_code(real_failed_mysql_producer,damage):
    state=real_failed_mysql_producer;recipe=state.recipe
    if damage=='missing-producer':recipe=recipe.replace(b'def start_mysql(self, image):',b'def different_mysql(self, image):')
    elif damage=='duplicate-producer':recipe+=b'\ndef start_mysql(self, image):\n    pass\n'
    else:recipe=recipe.replace(b"'--skip-log-bin'",b"'--log-bin'",1)
    assert recipe!=state.recipe
    if damage=='changed-command':
        proof=state.prove(recipe)
        with pytest.raises(ValueError,match='producer differs'):
            state.resources.recent_mysql_fixture_source(state.context,proof,failed_native=True)
    else:
        with pytest.raises(retirer.RetirementError,match='EXACT_FAILED_NATIVE_MYSQL_PRODUCER_REQUIRED'):
            state.prove(recipe)


@pytest.mark.parametrize('declaration', [b'MYSQL_MEMORY = 4 * GIB', b'MYSQL_MEMORY = 1536 * MIB'])
def test_watched_producer_external_memory_changes_cannot_borrow_its_registered_method(real_failed_mysql_producer, declaration):
    state = real_failed_mysql_producer
    changed = state.recipe.replace(b'MYSQL_MEMORY = 3 * GIB', declaration)
    assert changed != state.recipe
    proof = state.prove(changed)
    assert proof['mysqlFixtureStartSourceSha256'] == state.resources.WATCHED_MYSQL_START_SOURCE
    with pytest.raises(ValueError):
        state.resources.recent_mysql_fixture_source(state.context, proof, failed_native=True)


@pytest.fixture
def watched_retirement_controls(tmp_path, monkeypatch):
    root = tmp_path / 'ci'; root.mkdir(mode=0o700)
    context = {'release': 'ci-267-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}
    identity = {'instanceId': 'i-fixture', 'machineId': 'c' * 32, 'executionLocation': 'ECS'}
    work = root / 'verification' / context['release'] / 'checkout/work/compact-fixtures'
    work.mkdir(parents=True, mode=0o700); (work.parent / 'ci-evidence').mkdir(mode=0o700)
    for parent in work.parents:
        if parent == root: break
        parent.chmod(0o700)
    boot = '12345678-1234-1234-1234-123456789abc'
    process = {'pid': 10001, 'startTicks': 20001, 'group': 10001, 'session': 10001}
    kernel = {'pid': 30001, 'startTicks': 40001, 'relative': '/docker/' + 'd' * 64, 'directory': [29, 101]}
    config = {'tableOpenCacheInstances': 1, 'bufferPoolBytes': 268435456, 'maxConnections': 120}
    common = {**context, 'identity': identity, 'containerId': 'd' * 64, 'memoryLimitBytes': 3 * 1024 ** 3,
              'swapLimitBytes': 0, 'mysqlConfiguration': config}
    descriptor = {**common, 'version': 1, 'kind': 'doorhandle-fixture-watch-owner', 'process': process,
                  'kernelIdentity': kernel, 'bootId': boot, 'ownerToken': 'e' * 32, 'groupToken': 'f' * 32}
    probe = {'pid': kernel['pid'], 'startTicks': kernel['startTicks'], 'cgroup': kernel['relative'],
             'memoryLimitBytes': 3 * 1024 ** 3, 'swapLimitBytes': 0}
    status = {**common, 'version': 1, 'kind': 'doorhandle-fixture-runtime', 'process': process,
              'bootId': boot, 'ownerToken': 'e' * 32, 'status': 'STOPPED', 'watchStopped': True,
              'probeCount': 10, 'firstProbe': probe, 'lastProbe': dict(probe), 'capturedMonotonic': 10.0}
    owner = {**context, 'identity': identity, 'work': str(work), 'containerId': 'd' * 64,
             'rootPassword': 'private-password-must-not-project', 'mysqlRuntimeConfiguration': config,
             'fixtureWatch': {'file': str(work / 'fixture-watch-owner.json'), 'ownerToken': 'e' * 32, 'groupToken': 'f' * 32}}
    paths = {'original': work.parent / 'compact-fixtures-owner.json', 'owner': work / 'fixture-watch-owner.json',
             'status': work / 'fixture-watch-status.json', 'runtime': work.parent / 'ci-evidence/fixture-runtime.json'}
    values = {'original': owner, 'owner': descriptor, 'status': status,
              'runtime': {key: value for key, value in status.items() if key not in ('ownerToken', 'capturedMonotonic')}}
    for role, path in paths.items(): path.write_bytes(encoded(values[role])); path.chmod(0o600)
    spec = importlib.util.spec_from_file_location('watched_retirement_resource_contract', MODULE.parents[1] / 'docker/compact-build-resources.py')
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    historical = {'context': context, 'fixtureOwner': retirer.fixture_owner_projection(owner),
        'sourceArchive': {'mysqlFixtureMemoryLimitBytes': 3 * 1024 ** 3}, 'evidence': {'identity': identity},
        'controls': {'fixtureOwner': {'path': paths['original'].relative_to(root).as_posix(),
            'bytes': len(paths['original'].read_bytes()), 'sha256': sha(paths['original'].read_bytes()),
            'metadata': retirer.metadata(paths['original'].stat())}}}
    observed = []
    monkeypatch.setattr(retirer, 'stopped_fixture_watch_process', lambda p, b: observed.append((p, b)) or boot)
    return SimpleNamespace(root=root, context=context, identity=identity, work=work, descriptor=descriptor,
        status=status, owner=owner, values=values, paths=paths, historical=historical, builder=builder, observed=observed)


def test_watched_custody_projects_only_three_bound_terminal_originals(watched_retirement_controls):
    state = watched_retirement_controls
    proof = retirer.fixture_watch_controls(state.root, state.historical, state.builder)
    assert proof['watchStopped'] is True and proof['processAbsent'] is True
    assert set(proof['files']) == {'owner', 'status', 'runtime'}
    assert state.observed == [(state.descriptor['process'], state.descriptor['bootId'])]
    assert all(proof['files'][role]['metadata'] == retirer.metadata(state.paths[role].stat()) for role in proof['files'])
    projected = encoded(proof)
    assert b'private-password' not in projected and b'ownerToken' not in projected and b'groupToken' not in projected


@pytest.mark.parametrize('role', ['owner', 'status', 'runtime'])
def test_watched_custody_never_substitutes_a_missing_original(watched_retirement_controls, role):
    state = watched_retirement_controls; state.paths[role].unlink()
    with pytest.raises((OSError, retirer.RetirementError)):
        retirer.fixture_watch_controls(state.root, state.historical, state.builder)
    assert state.observed == []


@pytest.mark.parametrize('role,field,value', [('owner', 'containerId', '0' * 64),
    ('owner', 'ownerToken', '0' * 32), ('status', 'status', 'RUNNING'), ('status', 'watchStopped', False),
    ('status', 'bootId', '00000000-1234-1234-1234-123456789abc'), ('status', 'probeCount', 0),
    ('runtime', 'watchStopped', False), ('runtime', 'ownerToken', 'secret-must-not-be-public')])
def test_watched_custody_refuses_cross_identity_or_unstopped_originals(watched_retirement_controls, role, field, value):
    state = watched_retirement_controls; state.values[role][field] = value
    state.paths[role].write_bytes(encoded(state.values[role]))
    with pytest.raises(ValueError): retirer.fixture_watch_controls(state.root, state.historical, state.builder)
    assert state.observed == []


def test_watched_custody_does_not_accept_a_live_original_session(watched_retirement_controls, monkeypatch):
    state = watched_retirement_controls
    def active(*_args): raise retirer.RetirementError('FIXTURE_WATCH_PROCESS_STILL_PRESENT')
    monkeypatch.setattr(retirer, 'stopped_fixture_watch_process', active)
    with pytest.raises(retirer.RetirementError, match='STILL_PRESENT'):
        retirer.fixture_watch_controls(state.root, state.historical, state.builder)


@pytest.mark.parametrize('state', ['same-process', 'reused-pid', 'old-boot', 'absent'])
def test_watched_process_readback_never_stops_a_live_or_reused_process(tmp_path, monkeypatch, state):
    boot = '12345678-1234-1234-1234-123456789abc'; current = tmp_path / 'boot'; current.write_text(boot)
    process = {'pid': 10001, 'startTicks': 20001, 'group': 10001, 'session': 10001}
    fields = [b'S', b'1', b'10001', b'10001'] + [b'0'] * 15 + [b'20001' if state == 'same-process' else b'30001']
    stat_file = tmp_path / 'stat'
    if state != 'absent': stat_file.write_bytes(b'10001 (watcher) ' + b' '.join(fields))
    original_path = Path
    def mapped(path):
        if str(path) == '/proc/sys/kernel/random/boot_id': return current
        if str(path) == '/proc': return tmp_path / 'proc'
        return original_path(path)
    process_folder = tmp_path / 'proc/10001'; process_folder.mkdir(parents=True)
    if stat_file.exists(): stat_file.replace(process_folder / 'stat')
    monkeypatch.setattr(retirer, 'Path', mapped)
    if state == 'same-process':
        with pytest.raises(retirer.RetirementError, match='STILL_PRESENT'):
            retirer.stopped_fixture_watch_process(process, boot)
    else:
        original_boot = '00000000-1234-1234-1234-123456789abc' if state == 'old-boot' else boot
        assert retirer.stopped_fixture_watch_process(process, original_boot) == boot

@pytest.fixture
def failed_native_pair_plan(tmp_path,bundle,monkeypatch):
    """Real plan/admission/removal code; replace only OS Docker/process/UID probes."""
    from tests_python import test_historical_builder_retirement as builder_cases
    from tests_python import test_historical_mysql_fixture_retirement as mysql_cases
    root=tmp_path/'ci';tag='ci-221-'+'a'*12;context={'release':tag,'commit':'a'*40,'sourceSha256':'b'*64}
    current={'release':'ci-300-'+'f'*12,'commit':'f'*40,'sourceSha256':'e'*64}
    for value in (tag,current['release']):(root/'inbox'/value).mkdir(parents=True,mode=0o700)
    work=root/'verification'/tag/'checkout/work/compact-fixtures';data=work/'mysql-data';data.mkdir(parents=True,mode=0o700)
    page=data/'retained-original-page';page.write_bytes(b'private database bytes are retained')
    bcid='1'*64;fid='d'*64;production='e'*64;builder_token='c'*24
    bs=builder_cases.fixture_state((tag,context['commit'],bcid,builder_token))
    bs=SimpleNamespace(**json.loads(json.dumps(vars(bs),default=str).replace(str(builder_cases.CI_ROOT),str(root))))
    ms=mysql_cases.fixture.__wrapped__();old_context=dict(ms.context)
    ms=SimpleNamespace(**json.loads(json.dumps(vars(ms),default=str).replace(str(mysql_cases.ROOT),str(root))
        .replace(old_context['release'],tag).replace(old_context['commit'],context['commit'])))
    ms.owner['binaryLoggingDisabled']=True;ms.row['Config']['Cmd'].insert(6,'--skip-log-bin')
    pub={'Jenkinsfile.ecs-monolith':b'synthetic fixed no-publish pipeline',
         'script/jenkins/pipeline.ps1':b'synthetic publication guard',
         'script/docker/compact-build-resources.py':(MODULE.parents[1]/'docker/compact-build-resources.py').read_bytes(),
         'script/docker/compact-image-inputs.py':(MODULE.parents[1]/'docker/compact-image-inputs.py').read_bytes()}
    monkeypatch.setattr(retirer,'FAILED_NATIVE_PUBLICATION_RECIPES',frozenset({tuple(sha(pub[k]) for k in ('Jenkinsfile.ecs-monolith','script/jenkins/pipeline.ps1'))}))
    archive=source_archive(SimpleNamespace(keeper=root/'inbox'/tag/'application.jar'),
        recipe=(MODULE.parent/'prepare-compact-fixtures.py').read_bytes(),publication=pub)
    context['sourceSha256']=sha(archive.read_bytes())
    for value in (bs.context,bs.tools,bs.summary,ms.context,ms.owner,ms.cleanup):value.update(context)
    for row in (bs.row,ms.row):row['Config']['Labels']['io.doorhandle.source']=context['sourceSha256']
    bs.helpers={Path(name).name:sha(body) for name,body in pub.items() if name.startswith('script/docker/')}
    bs.tools['helperSha256']=bs.helpers['compact-build-resources.py'];bs.tools['imageInputsHelperSha256']=bs.helpers['compact-image-inputs.py']
    builder_cases.refresh_references(bs)
    directory=root/'inbox'/tag/'candidate-build-tools';directory.mkdir()
    raw_controls={}
    for role,name in (('tools','tools.json'),('summary','resource-summary.json'),('measurement','official-layer-measurements.json')):
        raw_controls[role]=builder_cases.raw(getattr(bs,role));path=directory/name;path.write_bytes(raw_controls[role]);path.chmod(0o600)
    jar=b'regeneratable failed native application';keeper=root/'inbox'/tag/'application.jar';copy_path=work/'candidate-app.jar'
    for p in (keeper,copy_path):p.write_bytes(jar);p.chmod(0o600)
    originals={'buildXml':flow_xml(context),'release':encoded({**context,'applicationJarSha256':sha(jar)}),
        'artifactPlan':encoded({'schema':1,'kind':'doorhandle-compact-fixture-artifacts',**context,'applicationJarSha256':sha(jar),'applicationJarBytes':len(jar)}),
        'fixtureOwner':encoded(ms.owner),'fixtureCleanup':encoded(ms.cleanup)}
    paths=retirer.expected_control_paths(current['release'],tag);refs={}
    for role,body in originals.items():
        p=root/paths[role];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body);p.chmod(0o600)
        refs[role]={'path':paths[role],'bytes':len(body),'sha256':sha(body)}
    preparation={**context,'identity':bundle.identity,'status':'PREPARED',
        'candidateBuilderTools':{'file':str(directory/'tools.json'),'sha256':sha(raw_controls['tools'])}}
    transport={**context,'status':'AVAILABLE','admission':{'identity':bundle.identity},'buildkitArchive':{'sha256':retirer.PUBLIC_ARCHIVE_SHA}}
    prep_path=root/'inbox'/current['release']/'native-jar-duplicate-controls'/tag/'ecs-tool-preparation.json'
    for p,value in ((prep_path,preparation),(prep_path.with_name('candidate-build-tools-transport.json'),transport)):
        p.write_bytes(encoded(value));p.chmod(0o600)
    request={'schemaVersion':1,'kind':retirer.KIND+'-request','current':current,'identity':bundle.identity,
        'protectedReleases':[current['release']],'candidates':[{**context,'controls':refs}]};raw=encoded(request)
    rows={bcid:bs.row,fid:ms.row,production:{'Id':production,'Name':'/unrelated-production','Config':{'Labels':{'io.doorhandle.release':'ci-43-production'}},
        'State':{'Running':True,'Restarting':False,'Pid':4567},'HostConfig':{'NetworkMode':'bridge','PidMode':'','IpcMode':'private'},'Mounts':[]}}
    commands=[];snapshots=[]
    def docker(*args):
        if args[0]=='inspect':return encoded([rows[args[1]]])
        assert args[0]=='rm' and len(args)==2 and args[1] in (bcid,fid)
        commands.append(args);del rows[args[1]];return b'removed'
    monkeypatch.setattr(retirer,'builder_docker',docker);monkeypatch.setattr(retirer,'builder_container_ids',lambda:list(rows))
    info=data.stat();metadata=[info.st_dev,info.st_ino,info.st_mode,999,999]
    def data_metadata(actual_root,path):
        assert Path(actual_root)==root and Path(path)==data
        return list(metadata)
    monkeypatch.setattr(retirer,'fixture_data_metadata',data_metadata)
    spec=importlib.util.spec_from_file_location('failed_native_real_snapshot_cleanup',MODULE.parent/'cleanup-ecs-builds.py')
    cleanup=importlib.util.module_from_spec(spec);spec.loader.exec_module(cleanup)
    def snapshot_command(command,**_options):
        assert command[0]=='/usr/bin/docker'
        if command[1:]==['ps','-aq','--no-trunc']:out='\n'.join(rows)+'\n'
        else:
            assert command[1:3]==['inspect','--format'] and set(command[4:])==set(rows)
            values=[]
            for cid in command[4:]:
                row=rows[cid];state=row['State'];labels=row['Config']['Labels']
                values.append([cid,state['Running'],state.get('Restarting',False),state['Pid'],labels.get('io.doorhandle.release'),labels.get('io.doorhandle.ci-tool-runtime'),row.get('Mounts',[])])
            snapshots.append(copy.deepcopy(values));out='\n'.join(json.dumps(v) for v in values)+'\n'
        return SimpleNamespace(returncode=0,stdout=out.encode(),stderr=b'')
    monkeypatch.setattr(cleanup,'subprocess',SimpleNamespace(run=snapshot_command))
    monkeypatch.setattr(cleanup,'process_references',lambda *_a,**_k:None)
    options={'request_sha256':sha(raw),'expected_current':current,'identity':bundle.identity,
             'modules':{'builder':builder_cases.resources,'cleanup':cleanup},'failed_native':True}
    return SimpleNamespace(root=root,tag=tag,current=current,context=context,raw=raw,request=request,options=options,
        rows=rows,commands=commands,snapshots=snapshots,bcid=bcid,fid=fid,production=production,page=page,page_bytes=page.read_bytes(),
        keeper=keeper,copy_path=copy_path,jar=jar,prep_path=prep_path,cleanup=cleanup,data=data,data_inode=data.stat().st_ino)


def test_failed_native_real_plan_pairs_stop_proof_then_builder_fixture_and_exact_jars(failed_native_pair_plan):
    s=failed_native_pair_plan
    prepared=retirer.plan_builders(s.root,s.raw,**s.options)
    assert prepared['skipped']==[] and prepared['scope']=='FAILED_NATIVE_BUILDERS' and len(prepared['candidates'])==1
    result=retirer.apply_builders(s.root,s.raw,prepared,plan_sha256=sha(encoded(prepared)),**s.options)
    assert result['status']=='REMOVED' and result['retiredMysqlObjects']==[]
    assert s.commands==[('rm',s.bcid)] and s.fid in s.rows and s.production in s.rows
    assert s.page.read_bytes()==s.page_bytes and s.keeper.read_bytes()==s.copy_path.read_bytes()==s.jar
    prepared=retirer.plan_recent_fixtures(s.root,s.raw,**s.options)
    assert prepared['skipped']==[] and len(prepared['candidates'])==1
    result=retirer.apply_recent_fixtures(s.root,s.raw,prepared,plan_sha256=sha(encoded(prepared)),**s.options)
    assert result['status']=='REMOVED' and s.commands==[('rm',s.bcid),('rm',s.fid)]
    def quiet(checkout,tag,token):s.cleanup.quiescent({'checkout':checkout,'token':token},tag,s.cleanup.docker_snapshot(),include_inbox=True)
    options={key:value for key,value in s.options.items() if key!='modules'};options['quiescence']=quiet
    for canonical in (False,True):
        prepared=retirer.plan(s.root,s.raw,canonical_jar=canonical,**options)
        assert prepared['skipped']==[] and len(prepared['candidates'])==1
        result=retirer.apply(s.root,s.raw,prepared,plan_sha256=sha(encoded(prepared)),canonical_jar=canonical,**options)
        assert result['status']=='REMOVED'
    assert not s.keeper.exists() and not s.copy_path.exists() and s.production in s.rows
    assert s.page.read_bytes()==s.page_bytes and s.data.stat().st_ino==s.data_inode
    assert any({s.bcid,s.fid}<={row[0] for row in snap} for snap in s.snapshots)


@pytest.fixture
def database_only_failed_native_pair(failed_native_pair_plan, monkeypatch):
    s = failed_native_pair_plan; old_sha = s.context['sourceSha256']
    archive = s.keeper.parent / 'source.tar.gz'
    with tarfile.open(archive, 'r:gz') as source:
        members = {member.name: source.extractfile(member).read() for member in source}
    recipe = members.pop('script/jenkins/prepare-compact-fixtures.py')
    preparation_source = (MODULE.parent / 'prepare-ecs-tools.py').read_bytes()
    members['script/jenkins/prepare-ecs-tools.py'] = preparation_source
    source_archive(SimpleNamespace(keeper=s.keeper), recipe=recipe, publication=members)
    s.context['sourceSha256'] = sha(archive.read_bytes())
    publication = tuple(sha(members[name]) for name in ('Jenkinsfile.ecs-monolith', 'script/jenkins/pipeline.ps1'))
    monkeypatch.setattr(retirer, 'DATABASE_VERIFY_PUBLICATION_RECIPES', frozenset({publication}))
    row = s.request['candidates'][0]; row.update(s.context)
    s.request['selectedFailedNativeBuild'] = s.tag.split('-')[1]
    for role, reference in row['controls'].items():
        path = s.root / reference['path']
        if role == 'buildXml': raw = with_action(flow_xml(s.context), 'verify')
        else: raw = path.read_bytes().replace(old_sha.encode(), s.context['sourceSha256'].encode())
        path.write_bytes(raw); reference.update(bytes=len(raw), sha256=sha(raw))
    s.rows.pop(s.bcid)
    s.rows[s.fid] = json.loads(json.dumps(s.rows[s.fid]).replace(old_sha, s.context['sourceSha256']))
    directory = s.keeper.parent / 'candidate-build-tools'
    for path in directory.iterdir(): path.unlink()
    directory.rmdir()
    preparation = {**s.context, 'identity': s.request['identity'], 'kind': 'doorhandle-ecs-tool-preparation',
        'status': 'PREPARED', 'sourceFiles': {'script/jenkins/prepare-ecs-tools.py': sha(preparation_source)}}
    transport = {**s.context, 'schema': 1, 'kind': 'doorhandle-ecs-tool-preparation-transport',
        'instanceId': s.request['identity']['instanceId'], 'machineId': s.request['identity']['machineId'],
        'status': 'PREPARED', 'prepareCandidateBuilder': False, 'originalExitCode': 0, 'finalExitCode': 0}
    s.prep_path.write_bytes(encoded(preparation))
    s.prep_path.with_name('candidate-build-tools-transport.json').unlink()
    s.transport_path = s.prep_path.with_name('ecs-tool-preparation-transport.json')
    s.transport_path.write_bytes(encoded(transport)); s.transport_path.chmod(0o600)
    s.raw = encoded(s.request); s.options['request_sha256'] = sha(s.raw)
    s.original_archive = archive.read_bytes(); s.database_directory = directory
    return s


def test_explicit_database_only_native_entry_retires_no_builder_then_exact_mysql_and_two_jars(database_only_failed_native_pair):
    s = database_only_failed_native_pair
    local = copy.deepcopy(s.request)
    for row in local['candidates']: row['controls'] = {key: ref for key, ref in row['controls'].items() if key in retirer.UPLOADED_NAMES}
    local_raw = encoded(local)
    request, skipped = retirer.capture_request(s.root, local_raw, local_spec_sha256=sha(local_raw),
        expected_current=s.current, identity=s.request['identity'], canonical_jar=True, failed_native=True)
    assert skipped == [] and request == s.request
    prepared = retirer.plan_builders(s.root, s.raw, **s.options)
    assert prepared['skipped'] == [] and prepared['candidates'] == [] and len(prepared['absent']) == 1
    assert prepared['absent'][0]['absenceKind'] == 'NOT_REQUESTED_BY_DATABASE_VERIFICATION'
    receipt = retirer.apply_builders(s.root, s.raw, prepared, plan_sha256=sha(encoded(prepared)), **s.options)
    assert receipt['status'] == 'NO_ACTION' and receipt['removed'] == receipt['alreadyAbsent'] == []
    assert receipt['buildersNotRequested'] == [s.tag] and s.commands == []
    journal = s.root / 'inbox' / s.current['release'] / 'native-builder-retirement-journal.jsonl'
    assert [json.loads(line)['phase'] for line in journal.read_bytes().splitlines()] == ['STARTED', 'BUILDER_NOT_REQUESTED', 'FINISHED']
    prepared = retirer.plan_recent_fixtures(s.root, s.raw, **s.options)
    assert prepared['skipped'] == [] and len(prepared['candidates']) == 1
    receipt = retirer.apply_recent_fixtures(s.root, s.raw, prepared, plan_sha256=sha(encoded(prepared)), **s.options)
    assert receipt['status'] == 'REMOVED' and s.commands == [('rm', s.fid)]
    def quiet(checkout, tag, token): s.cleanup.quiescent({'checkout': checkout, 'token': token}, tag, s.cleanup.docker_snapshot(), include_inbox=True)
    options = {key: value for key, value in s.options.items() if key != 'modules'}; options['quiescence'] = quiet
    for canonical in (False, True):
        prepared = retirer.plan(s.root, s.raw, canonical_jar=canonical, **options)
        assert prepared['skipped'] == [] and len(prepared['candidates']) == 1
        receipt = retirer.apply(s.root, s.raw, prepared, plan_sha256=sha(encoded(prepared)), canonical_jar=canonical, **options)
        assert receipt['status'] == 'REMOVED'
    assert not s.keeper.exists() and not s.copy_path.exists() and s.production in s.rows
    assert s.page.read_bytes() == s.page_bytes and s.data.stat().st_ino == s.data_inode
    assert (s.keeper.parent / 'source.tar.gz').read_bytes() == s.original_archive


def test_explicit_database_only_cli_keeps_request_selection_and_all_four_original_phases(database_only_failed_native_pair, monkeypatch, capsys):
    s = database_only_failed_native_pair
    def quiet(checkout, tag, token): s.cleanup.quiescent({'checkout': checkout, 'token': token}, tag, s.cleanup.docker_snapshot(), include_inbox=True)
    monkeypatch.setattr(retirer, 'admitted_current', lambda args: (s.root, s.current, s.request['identity'], quiet, s.options['modules']))
    local = copy.deepcopy(s.request)
    for row in local['candidates']: row['controls'] = {key: ref for key, ref in row['controls'].items() if key in retirer.UPLOADED_NAMES}
    raw = encoded(local); inbox = s.root / 'inbox' / s.current['release']
    path = inbox / 'native-jar-duplicate-local-spec.json'; path.write_bytes(raw); path.chmod(0o600)
    common = ['--mode', 'Maintenance', '--jar-batch', retirer.FAILED_NATIVE_BATCH,
        '--failed-native-build-number', s.tag.split('-')[1], '--root', str(s.root), '--tag', s.current['release'],
        '--commit', s.current['commit'], '--source-sha256', s.current['sourceSha256'],
        '--instance-id', s.request['identity']['instanceId'], '--machine-id', s.request['identity']['machineId'],
        '--current-receipt-sha256', '0' * 64]
    def phase(name, *flags):
        assert retirer.cli(['--phase', name, *common, *flags]) == 0
        return json.loads(capsys.readouterr().out)
    captured = phase('capture-canonical-request', '--local-spec-sha256', sha(raw))
    request_sha = captured['request']['sha256']; assert captured['skipped'] == []
    for plan, apply in (('plan-failed-native-builders', 'apply-failed-native-builders'),
                        ('plan-recent-fixtures', 'apply-recent-fixtures'), ('plan', 'apply'), ('plan-canonical', 'apply-canonical')):
        prepared = phase(plan, '--request-sha256', request_sha)
        assert prepared['skipped'] == []
        receipt = phase(apply, '--request-sha256', request_sha, '--plan-sha256', prepared['plan']['sha256'])
        assert receipt['status'] == ('NO_ACTION' if apply == 'apply-failed-native-builders' else 'REMOVED')
    result = phase('inspect')
    assert {'builderPlan', 'builderReceipt', 'builderJournal', 'recentFixturePlan', 'recentFixtureReceipt',
            'recentFixtureJournal', 'plan', 'receipt', 'journal', 'canonicalPlan', 'canonicalReceipt', 'canonicalJournal'} <= set(result['files'])
    assert s.commands == [('rm', s.fid)] and not s.keeper.exists() and not s.copy_path.exists()
    assert s.page.read_bytes() == s.page_bytes and s.production in s.rows


@pytest.mark.parametrize('changed', ['default', 'other-build', 'multiple-builds', 'wrong-sha', 'other-api'])
def test_database_only_native_permission_requires_exact_explicit_request_not_default_or_other_apis(database_only_failed_native_pair, changed):
    s = database_only_failed_native_pair; request = copy.deepcopy(s.request)
    if changed == 'default': request.pop('selectedFailedNativeBuild')
    elif changed == 'other-build': request['selectedFailedNativeBuild'] = '247'
    elif changed == 'multiple-builds': request['candidates'].append(copy.deepcopy(request['candidates'][0]))
    raw = encoded(request)
    if changed == 'default':
        prepared = retirer.plan_builders(s.root, raw, **{**s.options, 'request_sha256': sha(raw)})
        assert prepared['candidates'] == prepared['absent'] == [] and prepared['skipped']
    else:
        with pytest.raises(retirer.RetirementError):
            retirer.approved_request(raw, '0' * 64 if changed == 'wrong-sha' else sha(raw), s.current,
                s.request['identity'], canonical_jar=True, failed_native=changed != 'other-api')
    assert s.commands == [] and s.keeper.exists() and s.copy_path.exists()


@pytest.mark.parametrize('changed', ['transport-true', 'transport-integer', 'transport-unknown', 'wrong-identity',
    'wrong-source', 'preparation-builder', 'helper-drift', 'unreviewed-recipe', 'unreviewed-helper', 'builder-files', 'missing-transport'])
def test_database_only_no_builder_plan_requires_actual_originals_and_reviewed_source(database_only_failed_native_pair, monkeypatch, changed):
    s = database_only_failed_native_pair
    if changed == 'unreviewed-recipe': monkeypatch.setattr(retirer, 'DATABASE_VERIFY_PUBLICATION_RECIPES', frozenset())
    elif changed == 'unreviewed-helper': monkeypatch.setattr(retirer, 'DATABASE_VERIFY_TOOL_PREPARATION_SOURCE', '0' * 64)
    elif changed == 'builder-files': s.database_directory.mkdir()
    elif changed == 'missing-transport': s.transport_path.unlink()
    else:
        path = s.prep_path if changed in ('preparation-builder', 'helper-drift') else s.transport_path
        value = json.loads(path.read_bytes())
        if changed == 'preparation-builder': value['candidateBuilderTools'] = {}
        elif changed == 'helper-drift': value['sourceFiles']['script/jenkins/prepare-ecs-tools.py'] = '0' * 64
        elif changed == 'transport-true': value['prepareCandidateBuilder'] = True
        elif changed == 'transport-integer': value['prepareCandidateBuilder'] = 0
        elif changed == 'transport-unknown': value['status'] = 'FAILED_OR_UNKNOWN'
        elif changed == 'wrong-identity': value['machineId'] = '0' * 32
        else: value['sourceSha256'] = '0' * 64
        path.write_bytes(encoded(value))
    prepared = retirer.plan_builders(s.root, s.raw, **s.options)
    assert prepared['candidates'] == prepared['absent'] == [] and len(prepared['skipped']) == 1
    assert s.commands == [] and s.keeper.exists() and s.copy_path.exists() and s.page.read_bytes() == s.page_bytes


@pytest.mark.parametrize('changed', ['unknown-builder', 'foreign-bind', 'active-mysql', 'namespace-reference'])
def test_database_no_builder_plan_preserves_global_inventory_and_exact_stopped_mysql_guards(database_only_failed_native_pair, changed):
    s = database_only_failed_native_pair
    if changed == 'unknown-builder':
        s.rows['2' * 64] = {'Id': '2' * 64, 'Name': '/unknown-builder', 'Config': {'Labels': {'io.doorhandle.release': s.tag}},
            'State': {'Running': False, 'Restarting': False, 'Pid': 0}, 'HostConfig': {}, 'Mounts': []}
    elif changed == 'foreign-bind': s.rows[s.production]['Mounts'] = [{'Type': 'bind', 'Source': str(s.keeper.parent), 'Destination': '/foreign', 'RW': False}]
    elif changed == 'active-mysql': s.rows[s.fid]['State'].update(Status='running', Running=True, Pid=8901)
    else: s.rows[s.production]['HostConfig']['NetworkMode'] = 'container:' + s.fid
    prepared = retirer.plan_builders(s.root, s.raw, **s.options)
    assert prepared['candidates'] == prepared['absent'] == [] and len(prepared['skipped']) == 1
    assert s.commands == [] and s.page.read_bytes() == s.page_bytes and s.keeper.exists()


@pytest.mark.parametrize('changed', ['transport-drift', 'new-builder', 'mysql-start'])
def test_database_no_builder_apply_rechecks_originals_and_global_objects(database_only_failed_native_pair, changed):
    s = database_only_failed_native_pair; prepared = retirer.plan_builders(s.root, s.raw, **s.options)
    assert prepared['skipped'] == [] and len(prepared['absent']) == 1
    if changed == 'transport-drift': s.transport_path.write_bytes(s.transport_path.read_bytes() + b' ')
    elif changed == 'mysql-start': s.rows[s.fid]['State'].update(Status='running', Running=True, Pid=8901)
    else:
        s.rows['2' * 64] = {'Id': '2' * 64, 'Name': '/late-builder', 'Config': {'Labels': {'io.doorhandle.release': s.tag}},
            'State': {'Running': False, 'Restarting': False, 'Pid': 0}, 'HostConfig': {}, 'Mounts': []}
    receipt = retirer.apply_builders(s.root, s.raw, prepared, plan_sha256=sha(encoded(prepared)), **s.options)
    assert receipt['status'] == 'FAILED_OR_UNKNOWN' and receipt['removed'] == [] and s.commands == []
    assert s.fid in s.rows and s.keeper.exists() and s.copy_path.exists()


@pytest.mark.parametrize('selected', [None, '221'])
def test_cli_selection_is_bound_to_the_original_request_and_never_inferred(database_only_failed_native_pair, selected):
    s = database_only_failed_native_pair
    if selected is None:
        with pytest.raises(retirer.RetirementError, match='FAILED_NATIVE_CLI_SELECTION_DIFFERS'):
            retirer.bind_failed_native_cli_selection(s.raw, selected)
    else: retirer.bind_failed_native_cli_selection(s.raw, selected)


@pytest.mark.parametrize('stage', ['mysql', 'copy', 'canonical'])
def test_database_original_transport_drift_is_rejected_by_each_later_mutating_phase(database_only_failed_native_pair, stage):
    s = database_only_failed_native_pair
    if stage == 'mysql':
        prepared = retirer.plan_recent_fixtures(s.root, s.raw, **s.options)
        assert prepared['skipped'] == []
        s.transport_path.write_bytes(s.transport_path.read_bytes() + b' ')
        receipt = retirer.apply_recent_fixtures(s.root, s.raw, prepared, plan_sha256=sha(encoded(prepared)), **s.options)
    else:
        s.rows.pop(s.fid)
        def quiet(checkout, tag, token): s.cleanup.quiescent({'checkout': checkout, 'token': token}, tag, s.cleanup.docker_snapshot(), include_inbox=True)
        options = {key: value for key, value in s.options.items() if key != 'modules'}; options['quiescence'] = quiet
        canonical = stage == 'canonical'
        prepared = retirer.plan(s.root, s.raw, canonical_jar=canonical, **options)
        assert prepared['skipped'] == []
        s.transport_path.write_bytes(s.transport_path.read_bytes() + b' ')
        receipt = retirer.apply(s.root, s.raw, prepared, plan_sha256=sha(encoded(prepared)), canonical_jar=canonical, **options)
    assert receipt['status'] == 'FAILED_OR_UNKNOWN'
    assert s.commands == [] and s.keeper.exists() and s.copy_path.exists() and s.page.read_bytes() == s.page_bytes


@pytest.mark.parametrize('canonical', [False, True])
def test_database_transport_drift_after_jar_capture_retains_quarantine(database_only_failed_native_pair, monkeypatch, canonical):
    s = database_only_failed_native_pair; s.rows.pop(s.fid)
    def quiet(checkout, tag, token): s.cleanup.quiescent({'checkout': checkout, 'token': token}, tag, s.cleanup.docker_snapshot(), include_inbox=True)
    options = {key: value for key, value in s.options.items() if key != 'modules'}; options['quiescence'] = quiet
    prepared = retirer.plan(s.root, s.raw, canonical_jar=canonical, **options)
    assert prepared['skipped'] == []
    capture = retirer._capture_no_replace
    def drift(*args, **kwargs):
        capture(*args, **kwargs); s.transport_path.write_bytes(s.transport_path.read_bytes() + b' ')
    monkeypatch.setattr(retirer, '_capture_no_replace', drift)
    receipt = retirer.apply(s.root, s.raw, prepared, plan_sha256=sha(encoded(prepared)), canonical_jar=canonical, **options)
    assert receipt['status'] == 'FAILED_OR_UNKNOWN' and receipt['deleted'] == []
    assert len(receipt['retainedQuarantinePaths']) == 1
    assert (s.root / receipt['retainedQuarantinePaths'][0]).read_bytes() == s.jar
    assert (s.copy_path if canonical else s.keeper).read_bytes() == s.jar and s.commands == []


@pytest.mark.parametrize('conflict',['unknown-same-release','foreign-bind','namespace-reference','active-builder','active-peer'])
def test_failed_native_real_plan_keeps_unknown_active_and_occupying_containers_blocked(failed_native_pair_plan,conflict):
    s=failed_native_pair_plan
    if conflict=='unknown-same-release':
        s.rows['2'*64]={'Id':'2'*64,'Name':'/unknown-old-object','Config':{'Labels':{'io.doorhandle.release':s.tag}},
            'State':{'Running':False,'Restarting':False,'Pid':0},'HostConfig':{},'Mounts':[]}
    elif conflict=='foreign-bind':s.rows[s.production]['Mounts']=[{'Type':'bind','Source':str(s.keeper.parent),'Destination':'/foreign','RW':False}]
    elif conflict=='namespace-reference':s.rows[s.production]['HostConfig']['NetworkMode']='container:'+s.bcid
    else:s.rows[s.bcid if conflict=='active-builder' else s.fid]['State'].update(Status='running',Running=True,Pid=8901)
    prepared=retirer.plan_builders(s.root,s.raw,**s.options)
    assert prepared['candidates']==[] and prepared['absent']==[] and len(prepared['skipped'])==1
    assert s.commands==[] and s.page.read_bytes()==s.page_bytes and s.keeper.read_bytes()==s.copy_path.read_bytes()==s.jar


@pytest.mark.parametrize('changed',['builder-start','peer-start','new-foreign-bind','preparation-drift'])
def test_failed_native_real_apply_rechecks_the_pair_and_complete_original_chain_before_removing(failed_native_pair_plan,changed):
    s=failed_native_pair_plan;prepared=retirer.plan_builders(s.root,s.raw,**s.options)
    assert prepared['skipped']==[] and len(prepared['candidates'])==1
    if changed.endswith('-start'):s.rows[s.bcid if changed=='builder-start' else s.fid]['State'].update(Status='running',Running=True,Pid=8901)
    elif changed=='new-foreign-bind':s.rows[s.production]['Mounts']=[{'Type':'bind','Source':str(s.data),'Destination':'/occupied','RW':True}]
    else:
        value=json.loads(s.prep_path.read_bytes());value['candidateBuilderTools']['sha256']='0'*64;s.prep_path.write_bytes(encoded(value))
    result=retirer.apply_builders(s.root,s.raw,prepared,plan_sha256=sha(encoded(prepared)),**s.options)
    assert result['status']=='FAILED_OR_UNKNOWN' and result['removed']==[] and s.commands==[]
    assert s.bcid in s.rows and s.fid in s.rows and s.page.read_bytes()==s.page_bytes

@pytest.mark.parametrize('started',['builder','peer'])
def test_failed_native_plan_fresh_snapshot_cannot_ignore_an_admitted_pair_member_that_just_started(failed_native_pair_plan,monkeypatch,started):
    s=failed_native_pair_plan;original=s.cleanup.subprocess.run;changed=[]
    def observed(command,**options):
        if command[1:3]==['inspect','--format'] and not changed:
            s.rows[s.bcid if started=='builder' else s.fid]['State'].update(Status='running',Running=True,Pid=9901)
            changed.append(True)
        return original(command,**options)
    monkeypatch.setattr(s.cleanup.subprocess,'run',observed)
    prepared=retirer.plan_builders(s.root,s.raw,**s.options)
    assert changed==[True] and prepared['candidates']==[] and prepared['absent']==[]
    assert prepared['skipped']==[{'release':s.tag,'reason':'CLOSED_RUNTIME_RETIRING_OBJECT_BECAME_ACTIVE'}]
    assert s.commands==[] and s.bcid in s.rows and s.fid in s.rows and s.page.read_bytes()==s.page_bytes


@pytest.fixture
def legacy_retired_copy_entry(tmp_path, bundle, monkeypatch):
    """Exercise real capture/source/authority/reference/file APIs, not admit mocks."""
    root = tmp_path / 'legacy-ci'; root.mkdir(mode=0o700)
    current = {'release': 'ci-300-' + 'f' * 12, 'commit': 'f' * 40, 'sourceSha256': 'e' * 64}
    current_inbox = root / 'inbox' / current['release']; current_inbox.mkdir(parents=True, mode=0o700)
    publication = {'Jenkinsfile.ecs-monolith': b'reviewed synthetic nonpublishing workflow',
                   'script/jenkins/pipeline.ps1': b'reviewed synthetic source-only pipeline'}
    recipe = (b"def prepare(self):\n jar = canonical(self.inbox / 'application.jar')\n"
              b" uploaded = self.work / 'candidate-app.jar'\n shutil.copyfile(jar, uploaded)\n")
    targets, originals, controls, files, retained = {}, {}, {}, {}, {}
    def store(path, body):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(body); path.chmod(0o600); return path
    for ordinal, (tag, registered) in enumerate(retirer.RETIRED_COPY_194_TARGETS.items(), 1):
        work = root / 'verification' / tag / 'checkout/work/compact-fixtures'
        work.mkdir(parents=True, mode=0o700)
        inbox = root / 'inbox' / tag; inbox.mkdir(parents=True, mode=0o700)
        archive = source_archive(SimpleNamespace(keeper=inbox / 'application.jar'),
                                 comment=registered['commit'], recipe=recipe, publication=publication)
        context = {'release': tag, 'commit': registered['commit'], 'sourceSha256': sha(archive.read_bytes())}
        jar = ('synthetic regenerated legacy copy ' + tag).encode()
        targets[tag] = {**context, 'jarSha256': sha(jar), 'jarBytes': len(jar)}
        files[tag] = store(work / 'candidate-app.jar', jar)
        owner = {'schemaVersion': 1, 'kind': 'doorhandle-compact-fixture-owner', **context,
            'identity': bundle.identity, 'phase': 'OWNED_SERVER_STOPPED', 'token': format(ordinal, '010x'),
            'work': str(work), 'sourceContainerId': 'd' * 64, 'containerId': format(ordinal, '064x')}
        cleanup = {'schemaVersion': 1, 'kind': 'doorhandle-compact-fixture-cleanup', **context,
            'identity': bundle.identity, 'status': 'STOPPED', 'errors': [], 'containerId': owner['containerId'],
            'sourceContainerUntouched': owner['sourceContainerId'], 'dataDirectoryRetained': str(work / 'mysql-data'),
            'sourceDumpAndEvidenceRetained': True}
        local = {'schemaVersion': 1, **context, 'status': 'PASS', 'exitCode': 0, 'skipTests': True,
            'testsExecuted': False, 'applicationJarSha256': sha(jar), 'applicationJarBytes': len(jar)}
        bodies = {'buildXml': with_action(flow_xml(context), 'verify'), 'localBuild': encoded(local),
            'release': encoded({**context, 'applicationJarSha256': sha(jar), 'localBuildReceiptSha256': sha(encoded(local))}),
            'artifactPlan': encoded({'schema': 1, 'kind': 'doorhandle-compact-fixture-artifacts', **context,
                                    'applicationJarSha256': sha(jar), 'applicationJarBytes': len(jar)}),
            'fixtureOwner': encoded(owner), 'fixtureCleanup': encoded(cleanup),
            'fixtureCleanupPublic': encoded({'status': 'STOPPED', 'release': tag, 'commit': context['commit'],
                'cleanupReceipt': str(work / 'cleanup-receipt.json'), 'cleanupReceiptSha256': sha(encoded(cleanup))})}
        paths = retirer.expected_control_paths(current['release'], tag)
        refs = {role: {'path': paths[role], 'bytes': len(body), 'sha256': sha(body)} for role, body in bodies.items()}
        for role, body in bodies.items(): store(root / paths[role], body)
        controls[tag] = refs
        originals[tag] = {'context': context, 'bodies': bodies, 'source': archive,
                          'controlSha256': {role: sha(body) for role, body in bodies.items()}}
        for path in (archive, store(work / 'source.sql', b'original retained SQL'),
                     store(work / 'mysql-data/original-page', b'original retained database page'),
                     store(work / 'original-report.xml', b'original retained test report')):
            retained[path] = path.read_bytes()
    monkeypatch.setattr(retirer, 'RETIRED_COPY_194_TARGETS', targets)
    monkeypatch.setattr(retirer, 'RETIRED_COPY_194_PUBLICATION',
                        {tag: tuple(sha(raw) for raw in publication.values()) for tag in targets})
    authority = copy.deepcopy(retirer.RETIRED_COPY_194_AUTHORITY)
    helper = b'# authenticated original retirement helper; never executed\n'
    source = io.BytesIO()
    with tarfile.open(fileobj=source, mode='w:gz', format=tarfile.PAX_FORMAT,
                      pax_headers={'comment': authority['commit']}) as package:
        member = tarfile.TarInfo('script/jenkins/retire-failed-native-jar-duplicates.py'); member.size = len(helper)
        package.addfile(member, io.BytesIO(helper))
    authority.update(sourceSha256=sha(source.getvalue()), helperSha256=sha(helper))
    context = {key: authority[key] for key in ('release', 'commit', 'sourceSha256')}
    old_request = {'schemaVersion': 1, 'kind': retirer.KIND + '-request', 'current': context,
        'identity': bundle.identity, 'protectedReleases': [context['release']],
        'candidates': [{**value['context'], 'controls': controls[tag]} for tag, value in originals.items()]}
    old_request_raw = encoded(old_request); old_candidates, deleted = [], []
    for tag, original in originals.items():
        target = {'kind': retirer.CANONICAL_JAR_KIND, 'path': 'inbox/' + tag + '/application.jar',
                  'sha256': targets[tag]['jarSha256'], 'bytes': targets[tag]['jarBytes']}
        old_candidates.append({'context': original['context'], 'target': target,
            'controls': {role: {'sha256': checksum} for role, checksum in original['controlSha256'].items()},
            'sourceArchive': {'sha256': original['context']['sourceSha256'], 'transportRecipeSha256': sha(recipe)}})
        deleted.append({**target, 'capturedInodeVerified': True, 'binaryDisposition': 'RETIRED'})
    old_plan = {'kind': retirer.CANONICAL_KIND + '-plan', 'current': context, 'identity': bundle.identity,
        'requestSha256': sha(old_request_raw), 'candidates': old_candidates, 'deletionPerformed': False, 'skipped': []}
    old_plan_raw = encoded(old_plan)
    journal = [{'phase': 'STARTED', 'identity': bundle.identity,
                'requestSha256': sha(old_request_raw), 'planSha256': sha(old_plan_raw)}]
    for row in deleted: journal += [{'phase': 'DELETE_STARTED', **row}, {'phase': 'DELETE_FINISHED', **row}]
    journal.append({'phase': 'FINISHED', 'deletedFiles': 3})
    journal_raw = b''.join(encoded(row) + b'\n' for row in journal)
    receipt = {'kind': retirer.CANONICAL_KIND + '-receipt', 'current': context, 'identity': bundle.identity,
        'status': 'REMOVED', 'failure': None, 'skipped': [], 'retainedQuarantinePaths': [], 'binaryDisposition': 'RETIRED',
        'binaryRebuildByteIdentityClaimed': False, 'testsRunByRetirement': False,
        'sourceArchivesDataAndReportsHaveNoDeletionApi': True, 'planSha256': sha(old_plan_raw),
        'requestSha256': sha(old_request_raw), 'journalSha256': sha(journal_raw), 'deleted': deleted}
    terminal = ET.fromstring(flow_xml(context, result='SUCCESS'))
    for item in terminal.findall('.//hudson.model.ParametersAction/parameters/*'):
        if item.findtext('name') == 'ACTION': item.find('value').text = 'reclaim-build-outputs'
        if item.findtext('name') == 'DOORHANDLE_CI_SCOPE': item.find('value').text = 'source'
    bodies = {'buildXml': ET.tostring(terminal), 'source': source.getvalue(), 'request': old_request_raw,
        'plan': old_plan_raw, 'receipt': encoded(receipt), 'journal': journal_raw,
        'release': encoded({**context, 'schema': 1, 'kind': 'doorhandle-maintenance-source',
            'action': 'reclaim-build-outputs', 'maintenanceOnly': True, 'testsExecuted': False, 'applicationBuilt': False})}
    authority_files = {}; registered_files = {}
    for role, (name, _, _) in authority['files'].items():
        body = bodies[role]; path = current_inbox / 'native-retired-candidate-controls' / context['release'] / name
        authority_files[role] = store(path, body); registered_files[role] = (name, len(body), sha(body))
    authority['files'] = registered_files
    monkeypatch.setattr(retirer, 'RETIRED_COPY_194_AUTHORITY', authority)
    request = {**old_request, 'current': current, 'protectedReleases': [current['release']]}
    local_spec = copy.deepcopy(request)
    for row in local_spec['candidates']:
        row['controls'] = {role: ref for role, ref in row['controls'].items() if role in retirer.UPLOADED_NAMES}
    local_raw = encoded(local_spec)
    store(current_inbox / 'native-jar-duplicate-local-spec.json', local_raw)
    spec = importlib.util.spec_from_file_location('legacy_retired_actual_cleanup', MODULE.parent / 'cleanup-ecs-builds.py')
    cleanup = importlib.util.module_from_spec(spec); spec.loader.exec_module(cleanup)
    containers, snapshots = [], []
    def docker(command, **kwargs):
        assert command[0] == '/usr/bin/docker'
        if command[1:] == ['ps', '-aq', '--no-trunc']: output = '\n'.join(row[0] for row in containers)
        else:
            assert command[1:3] == ['inspect', '--format'] and command[4:] == [row[0] for row in containers]
            snapshots.append(copy.deepcopy(containers)); output = '\n'.join(json.dumps(row) for row in containers)
        return SimpleNamespace(returncode=0, stdout=output.encode(), stderr=b'')
    monkeypatch.setattr(cleanup, 'subprocess', SimpleNamespace(run=docker))
    proc = tmp_path / 'isolated-proc'; proc.mkdir(mode=0o700)
    scan = cleanup.process_references
    monkeypatch.setattr(cleanup, 'process_references', lambda checkout, **kwargs: scan(checkout, proc=proc, **kwargs))
    def quiet(checkout, tag, token):
        cleanup.quiescent({'checkout': checkout, 'token': token}, tag, cleanup.docker_snapshot(), include_inbox=True)
    options = {'request_sha256': sha(encoded(request)), 'expected_current': current, 'identity': bundle.identity,
               'quiescence': quiet, 'retired_copy_batch': retirer.RETIRED_COPY_BATCH_194}
    return SimpleNamespace(root=root, current=current, identity=bundle.identity, request=request, raw=encoded(request),
        local_raw=local_raw, files=files, originals=originals, controls=controls, retained=retained, authority=authority,
        authority_files=authority_files, options=options, cleanup=cleanup, quiet=quiet, containers=containers,
        snapshots=snapshots, proc=proc, store=store)


def test_legacy_retired_copy_actual_cli_capture_plan_apply_and_inspect_preserves_data(legacy_retired_copy_entry, monkeypatch, capsys):
    s = legacy_retired_copy_entry
    monkeypatch.setattr(retirer, 'admitted_current', lambda args: (s.root, s.current, s.identity, s.quiet, {'cleanup': s.cleanup}))
    common = ['--mode', 'Maintenance', '--retired-copy-batch', retirer.RETIRED_COPY_BATCH_194,
        '--root', str(s.root), '--tag', s.current['release'], '--commit', s.current['commit'],
        '--source-sha256', s.current['sourceSha256'], '--instance-id', s.identity['instanceId'],
        '--machine-id', s.identity['machineId'], '--current-receipt-sha256', 'a' * 64]
    def invoke(phase, *flags):
        assert retirer.cli(['--phase', phase, *common, *flags]) == 0
        return json.loads(capsys.readouterr().out)
    captured = invoke('capture-canonical-request', '--local-spec-sha256', sha(s.local_raw))
    assert captured['skipped'] == []
    planned = invoke('plan-retired-candidate-copies', '--request-sha256', captured['request']['sha256'])
    assert planned['skipped'] == [] and planned['candidateTargetCount'] == 3
    result = invoke('apply-retired-candidate-copies', '--request-sha256', captured['request']['sha256'],
                    '--plan-sha256', planned['plan']['sha256'])
    assert result['status'] == 'REMOVED' and result['deletedFiles'] == 3
    assert result['directoriesPreserved'] and result['volumesPreserved'] and result['imagesPreserved']
    inspected = invoke('inspect')
    assert {'retiredCandidatePlan', 'retiredCandidateReceipt', 'retiredCandidateJournal'} <= set(inspected['files'])
    assert all(not path.exists() for path in s.files.values())
    assert all(path.read_bytes() == raw for path, raw in s.retained.items())


@pytest.mark.parametrize('reference', ['same-tag-stopped', 'same-tag-running', 'checkout-bind', 'inbox-bind', 'ancestor-bind'])
def test_legacy_retired_actual_plan_enumerates_and_rejects_every_other_old_container(legacy_retired_copy_entry, reference):
    s = legacy_retired_copy_entry; tag = next(iter(s.files)); checkout = s.files[tag].parents[2]
    mounts = []; release = 'unrelated'; running = reference == 'same-tag-running'
    if reference.startswith('same-tag'): release = tag
    else:
        source = {'checkout-bind': checkout, 'inbox-bind': s.root / 'inbox' / tag,
                  'ancestor-bind': s.root}[reference]
        mounts = [{'Type': 'bind', 'Source': str(source)}]
    s.containers.append(['a' * 64, running, False, 9901 if running else 0, release, None, mounts])
    prepared = retirer.plan_retired_candidate_copies(s.root, s.raw, **s.options)
    assert prepared['skipped'] and prepared['candidateTargetCount'] < 3 and s.snapshots
    with pytest.raises(retirer.RetirementError, match='COMPLETE_EXACT_RETIRED_COPY_PLAN_REQUIRED'):
        retirer.apply_retired_candidate_copies(s.root, s.raw, prepared, plan_sha256=sha(retirer.canonical(prepared)), **s.options)
    assert all(path.exists() for path in s.files.values())


@pytest.mark.parametrize('role', ['buildXml', 'release', 'source', 'request', 'plan', 'receipt', 'journal'])
def test_legacy_retired_real_authority_requires_all_seven_originals(legacy_retired_copy_entry, role):
    s = legacy_retired_copy_entry; path = s.authority_files[role]; path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(retirer.RetirementError, match='ORIGINAL_RETIREMENT_AUTHORITY_SHA_DRIFT'):
        retirer.plan_retired_candidate_copies(s.root, s.raw, **s.options)
    assert all(path.exists() for path in s.files.values())


@pytest.mark.parametrize('changed', ['candidate', 'source', 'authority', 'publication', 'container'])
def test_legacy_retired_real_apply_rechecks_every_source_reference_and_container_before_capture(legacy_retired_copy_entry, changed):
    s = legacy_retired_copy_entry; tag = next(iter(s.files))
    prepared = retirer.plan_retired_candidate_copies(s.root, s.raw, **s.options)
    if changed == 'candidate': s.files[tag].write_bytes(b'changed candidate')
    elif changed == 'source': s.originals[tag]['source'].write_bytes(b'changed old source archive')
    elif changed == 'authority': s.authority_files['receipt'].write_bytes(b'changed original authority')
    elif changed == 'publication': (s.root / 'releases' / tag).mkdir(parents=True, mode=0o700)
    else: s.containers.append(['a' * 64, False, False, 0, tag, None, []])
    result = retirer.apply_retired_candidate_copies(s.root, s.raw, prepared, plan_sha256=sha(retirer.canonical(prepared)), **s.options)
    assert result['status'] == 'FAILED_OR_UNKNOWN' and result['deleted'] == []
    assert all(path.exists() for path in s.files.values())


@pytest.mark.parametrize('changed', ['authority', 'source', 'publication', 'container', 'keeper'])
def test_legacy_retired_after_capture_rechecks_same_batch_and_retains_changed_quarantine(legacy_retired_copy_entry, monkeypatch, changed):
    s = legacy_retired_copy_entry; tag = next(iter(s.files)); capture = retirer._capture_no_replace
    prepared = retirer.plan_retired_candidate_copies(s.root, s.raw, **s.options)
    def changed_capture(*args):
        capture(*args)
        if changed == 'authority': s.authority_files['receipt'].write_bytes(b'changed authority after capture')
        elif changed == 'source': s.originals[tag]['source'].write_bytes(b'changed source after capture')
        elif changed == 'publication': (s.root / 'releases' / tag).mkdir(parents=True, mode=0o700)
        elif changed == 'container': s.containers.append(['a' * 64, False, False, 0, tag, None, []])
        else: s.store(s.root / 'inbox' / tag / 'application.jar', b'reappeared keeper')
    monkeypatch.setattr(retirer, '_capture_no_replace', changed_capture)
    result = retirer.apply_retired_candidate_copies(s.root, s.raw, prepared, plan_sha256=sha(retirer.canonical(prepared)), **s.options)
    assert result['status'] == 'FAILED_OR_UNKNOWN' and result['deleted'] == []
    assert len(result['retainedQuarantinePaths']) == 1 and result['automaticResumeAllowed'] is False
    assert (s.root / result['retainedQuarantinePaths'][0]).exists()


def test_legacy_retired_candidate_permission_never_changes_default_canonical_or_other_copy_batches(legacy_retired_copy_entry):
    s = legacy_retired_copy_entry; tag = next(iter(s.files)); original = s.originals[tag]
    with pytest.raises(retirer.RetirementError, match='ONLY_REVIEWED_OLD_ATTEMPTS_ALLOWED'):
        retirer.approved_request(s.raw, sha(s.raw), s.current, s.identity, canonical_jar=True)
    with pytest.raises(retirer.RetirementError, match='EXACT_ORIGINAL_RETIRED_COPY_BYTES_REQUIRED'):
        retirer.describe_retired_candidate_copy(s.root, tag, sha(s.files[tag].read_bytes()), s.files[tag].stat().st_size)
    with pytest.raises(retirer.RetirementError, match='CLOSED_REVIEWED_UNPUBLISHED_SOURCE_REQUIRED'):
        retirer.source_proof(s.root, tag, original['context']['commit'], original['context']['sourceSha256'], canonical_jar=True)
    with pytest.raises(retirer.RetirementError, match='FAILED_NATIVE_PARAMETERS_REQUIRED'):
        retirer.terminal_xml(original['bodies']['buildXml'], original['context'], canonical_jar=True)


@pytest.mark.parametrize(('mode', 'phase', 'jar_batch'), [
    ('Verified', 'capture-canonical-request', None), ('Maintenance', 'plan-canonical', None),
    ('Maintenance', 'apply-canonical', None), ('Maintenance', 'plan-public-layers', None),
    ('Maintenance', 'apply-recent-fixtures', None), ('Maintenance', 'inspect', retirer.FAILED_NATIVE_BATCH)])
def test_legacy_copy_cli_policy_cannot_authorize_other_phases_or_combine_permissions(monkeypatch, capsys, mode, phase, jar_batch):
    def forbidden(args): raise AssertionError('Invalid policy must be refused before any ECS identity or source inspection')
    monkeypatch.setattr(retirer, 'admitted_current', forbidden)
    arguments = ['--phase', phase, '--mode', mode, '--retired-copy-batch', retirer.RETIRED_COPY_BATCH_194,
        '--root', CI_ROOT, '--tag', 'ci-300-' + 'f' * 12, '--commit', 'f' * 40,
        '--source-sha256', 'e' * 64, '--instance-id', 'i-fixture', '--machine-id', 'd' * 32,
        '--current-receipt-sha256', 'a' * 64]
    if jar_batch is not None: arguments += ['--jar-batch', jar_batch]
    assert retirer.cli(arguments) == 2
    assert json.loads(capsys.readouterr().out)['reason'] == 'RETIRED_COPY_BATCH_MAINTENANCE_PHASE_REQUIRED'


@pytest.mark.parametrize('batch', ['retired-204-207', 'retired-221-224'])
def test_retired_copy_registry_rejects_other_epochs_instead_of_inheriting_their_permissions(batch):
    with pytest.raises(retirer.RetirementError, match='EXACT_RETIRED_COPY_BATCH_REQUIRED'):
        retirer.retired_copy_policy(batch)


def test_legacy_retired_fixed_registration_has_exact_original_sources_and_no_default_api_expansion():
    assert set(retirer.RETIRED_COPY_194_TARGETS) == {'ci-187-8e90ba50c691', 'ci-188-df1e1a54d48e', 'ci-189-410506ad7c82'}
    assert retirer.RETIRED_COPY_194_AUTHORITY['release'] == 'ci-194-2c2e65a0daa9'
    assert retirer.RETIRED_COPY_194_AUTHORITY['files']['source'][1:] == (
        100300, 'c137fec1a5b8536d9b2a350104d6a5206cc1d1f2e8fb8eba2a240119258e87e9')
    assert all(retirer.canonical_commit(tag) is None and tag not in retirer.PUBLIC_LAYER_TAGS
               for tag in retirer.RETIRED_COPY_194_TARGETS)
    assert set(retirer.retired_copy_policy()[0]) == set(retirer.RETIRED_COPY_TARGETS)


@pytest.mark.parametrize('changed', ['copy-recipe', 'publication', 'archive-commit'])
def test_legacy_copy_selection_still_authenticates_actual_old_recipe_and_publication_members(legacy_retired_copy_entry, changed):
    s = legacy_retired_copy_entry; tag = next(iter(s.files)); original = s.originals[tag]
    with tarfile.open(original['source'], 'r:gz') as package:
        members = {member.name: package.extractfile(member).read() for member in package}
    publication = {name: members[name] for name in ('Jenkinsfile.ecs-monolith', 'script/jenkins/pipeline.ps1')}
    recipe = members['script/jenkins/prepare-compact-fixtures.py']
    if changed == 'copy-recipe': recipe = b'def prepare(self):\n pass\n'
    if changed == 'publication': publication['script/jenkins/pipeline.ps1'] += b'\nunknown side effect\n'
    archive = source_archive(SimpleNamespace(keeper=s.root / 'inbox' / tag / 'application.jar'), recipe=recipe,
        publication=publication, comment='f' * 40 if changed == 'archive-commit' else original['context']['commit'])
    guard = {'copy-recipe': 'EXACT_REVIEWED_JAR_COPY_RECIPE_REQUIRED', 'publication': 'CLOSED_REVIEWED_UNPUBLISHED_SOURCE_REQUIRED',
             'archive-commit': 'FIXED_OLD_SOURCE_COMMIT_REQUIRED'}[changed]
    with pytest.raises(retirer.RetirementError, match=guard):
        retirer.source_proof(s.root, tag, original['context']['commit'], sha(archive.read_bytes()),
                             canonical_jar=True, retired_copy_batch=retirer.RETIRED_COPY_BATCH_194)
    assert all(path.exists() for path in s.files.values())


@pytest.mark.parametrize('changed', ['missing-one', 'foreign-source', 'mixed-203'])
def test_legacy_copy_capture_requires_one_complete_exact_batch_not_a_union_of_old_permissions(legacy_retired_copy_entry, changed):
    s = legacy_retired_copy_entry; request = json.loads(s.local_raw)
    if changed == 'missing-one': request['candidates'].pop()
    elif changed == 'foreign-source': request['candidates'][0]['sourceSha256'] = '0' * 64
    else:
        tag, registered = next(iter(retirer.RETIRED_COPY_TARGETS.items()))
        request['candidates'][0] = {'release': tag, 'commit': registered['commit'],
                                  'sourceSha256': registered['sourceSha256'], 'controls': {}}
    raw = encoded(request)
    with pytest.raises(retirer.RetirementError, match='EXACT_RETIRED_COPY_BATCH_SOURCES_REQUIRED'):
        retirer.capture_request(s.root, raw, local_spec_sha256=sha(raw), expected_current=s.current,
            identity=s.identity, canonical_jar=True, retired_copy_batch=retirer.RETIRED_COPY_BATCH_194)
    assert all(path.exists() for path in s.files.values())

@pytest.fixture
def legacy_retired_controller_reader(tmp_path):
    """Run the actual PS reader with only its fixed evidence literals rebound."""
    controller = (MODULE.parent / 'retire-failed-native-jar-duplicates.ps1').read_text(encoding='utf8')
    reader = controller.split("$reader=@'\n", 1)[1].split("\n'@", 1)[0]
    syntax = ast.parse(reader)
    registrations = [node for node in ast.walk(syntax) if isinstance(node, ast.Assign)]
    approved = next(ast.literal_eval(node.value) for node in registrations
        if any(isinstance(name, ast.Name) and name.id == 'approved' for name in node.targets)
        and isinstance(node.value, ast.List) and len(node.value.elts) == 3
        and ast.literal_eval(node.value.elts[0])[0] == 187)
    originals = next(ast.literal_eval(node.value) for node in registrations
        if any(isinstance(name, ast.Name) and name.id == 'originals' for name in node.targets)
        and isinstance(node.value, ast.Dict) and ast.literal_eval(node.value)['build.xml'][0] == 298107)
    retained = tmp_path / 'retained'; retained.mkdir()
    jhome = tmp_path / 'jhome'; jhome.mkdir()
    commit = 'f' * 40; current = 'ci-300-' + commit[:12]
    authority = {'release': 'ci-194-2c2e65a0daa9', 'commit': '2c2e65a0daa94d96b327c59d720871ab70bff0a1'}
    replacements = {}; files = {}; old_rows = []
    def store(path, raw):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw); return path
    def archive_bytes(members, fixed_commit):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:gz', format=tarfile.PAX_FORMAT,
                          pax_headers={'comment': fixed_commit}) as package:
            for name, body in members.items():
                member = tarfile.TarInfo(name); member.size = len(body)
                package.addfile(member, io.BytesIO(body))
        return output.getvalue()
    helpers = {name: b'# opaque fixed helper; never imported by metadata reader\n' for name in (
        'script/jenkins/retire-failed-native-jar-duplicates.py', 'script/jenkins/cleanup-ecs-builds.py',
        'script/jenkins/verify-remote.py', 'script/docker/compact-build-resources.py')}
    archive = store(tmp_path / 'source.tar.gz', archive_bytes(helpers, commit))
    for number, old_commit, preservation_sha in approved:
        tag = 'ci-' + str(number) + '-' + old_commit[:12]
        folder = retained / ('ci-' + str(number) + '-raw-receipts')
        context = {'release': tag, 'commit': old_commit, 'sourceSha256': sha(('source ' + tag).encode())}
        bodies = {'build.xml': with_action(flow_xml(context), 'verify'),
            'release.json': encoded(context), 'local-build.json': encoded({'status': 'PASS'}),
            'fixture-cleanup.json': encoded({'status': 'STOPPED'})}
        entries = []
        for name, body in bodies.items():
            store(folder / name, body)
            original = '/synthetic-jenkins/jobs/doorhandle-java/builds/' + str(number) + (
                '/build.xml' if name == 'build.xml' else '/archive/artifacts/' + name)
            entries.append({'path': name, 'bytes': len(body), 'sha256': sha(body), 'original': original})
        proof = encoded({'build': number, 'files': entries,
            'summarySha256': sha(b'synthetic summary'), 'allOriginalCopiesByteEqual': True})
        store(folder / 'preservation.json', proof); replacements[preservation_sha] = sha(proof)
        old_rows.append(context)
    helper = b'# authenticated historical retirement helper; opaque metadata input\n'
    source_raw = archive_bytes({'script/jenkins/retire-failed-native-jar-duplicates.py': helper}, authority['commit'])
    authority['sourceSha256'] = sha(source_raw)
    folder = retained / 'ci-194-raw-receipts'
    identity = {'executionLocation': 'ECS', 'instanceId': 'i-synthetic',
                'machineId': '1ebe8f77e3104ab6a49a9386e38abd20'}
    request = encoded({'schemaVersion': 1, 'kind': 'doorhandle-failed-native-jar-duplicate-request',
        'current': authority, 'identity': identity, 'protectedReleases': [authority['release']], 'candidates': old_rows})
    plan = encoded({'schemaVersion': 1, 'kind': 'doorhandle-failed-native-canonical-jar-retirement-plan',
        'current': authority, 'identity': identity, 'requestSha256': sha(request),
        'candidates': [{'context': row} for row in old_rows], 'skipped': [], 'deletionPerformed': False})
    events = [{'phase': 'STARTED', 'identity': identity, 'planSha256': sha(plan), 'requestSha256': sha(request)}]
    for row in old_rows:
        path = 'inbox/' + row['release'] + '/application.jar'
        events += [{'phase': 'DELETE_STARTED', 'path': path}, {'phase': 'DELETE_FINISHED', 'path': path}]
    events.append({'phase': 'FINISHED', 'deletedFiles': 3})
    journal = b''.join(encoded(row) + b'\n' for row in events)
    receipt = encoded({'schemaVersion': 1, 'kind': 'doorhandle-failed-native-canonical-jar-retirement-receipt',
        'current': authority, 'identity': identity, 'status': 'REMOVED', 'failure': None, 'skipped': [],
        'planSha256': sha(plan), 'requestSha256': sha(request), 'journalSha256': sha(journal)})
    authority_xml = ET.fromstring(flow_xml(authority, result='SUCCESS'))
    params = authority_xml.findall('.//hudson.model.ParametersAction/parameters/*')
    next(item for item in params if item.findtext('name') == 'ACTION').find('value').text = 'reclaim-build-outputs'
    next(item for item in params if item.findtext('name') == 'DOORHANDLE_CI_SCOPE').find('value').text = 'source'
    bodies = {'build.xml': ET.tostring(authority_xml), 'release.json': encoded({'schema': 1,
        'kind': 'doorhandle-maintenance-source', 'action': 'reclaim-build-outputs', **authority,
        'maintenanceOnly': True, 'testsExecuted': False, 'applicationBuilt': False}),
        'source.tar.gz': source_raw, 'native-jar-duplicate-request.json': request,
        'native-jar-duplicate-canonical-plan.json': plan,
        'native-jar-duplicate-canonical-receipt.json': receipt,
        'native-jar-duplicate-canonical-journal.jsonl': journal}
    source_folder = retained / 'ci-194-remote-source-supplement'
    for name, body in bodies.items():
        files[name] = store((source_folder if name == 'source.tar.gz' else folder) / name, body)
        size, checksum = originals[name]
        replacements[size] = len(body); replacements[checksum] = sha(body)
    proof_entries = []
    for name, body in bodies.items():
        if name in ('source.tar.gz', 'native-jar-duplicate-canonical-journal.jsonl'): continue
        suffix = '/build.xml' if name == 'build.xml' else '/archive/artifacts/' + name
        proof_entries.append({'path': name, 'bytes': len(body), 'sha256': sha(body),
            'original': '/synthetic-jenkins/jobs/doorhandle-java/builds/194' + suffix})
    preservation = {'build': 194, 'files': proof_entries,
        'summarySha256': sha(b'synthetic authority summary'), 'allOriginalCopiesByteEqual': True}
    supplemental = {'build': 194, 'commit': authority['commit'], 'status': 'SUCCESS',
        'originalCMatchesD': True, 'testsExecuted': False, 'applicationBuilt': False,
        'inputs': [{'file': name, 'bytes': len(body), 'sha256': sha(body)} for name, body in bodies.items()
                   if name not in ('build.xml', 'source.tar.gz')]}
    provenance = {'kind': 'actual-ecs-retained-maintenance-source',
        'path': CI_ROOT + '/inbox/' + authority['release'] + '/cleanup-source.tar.gz',
        'bytes': len(source_raw), 'sha256': sha(source_raw), 'commit': authority['commit'],
        'machineId': identity['machineId'], 'uid': 1000, 'gid': 1000,
        'testsExecuted': False, 'deletionPerformed': False,
        'helper': {'path': 'script/jenkins/retire-failed-native-jar-duplicates.py', 'bytes': len(helper), 'sha256': sha(helper)}}
    pins = {
        'preservation': 'b0d395361bc5075267d64e558f793d154604558693866cd11113770bbc9b53ab',
        'supplement': 'c38bd7540d891b9c60c843c60b4e275206eb418c3e958bd6e22eab9a3eaed81b',
        'provenance': '2a1f8d7bee5a770f11ff7b02a1bde97101c67b217582cb99794c7019f6fb1ba7'}
    proofs = {'preservation': (folder / 'preservation.json', preservation),
              'supplement': (folder / 'maintenance-originals-verification.json', supplemental),
              'provenance': (source_folder / 'source-provenance.json', provenance)}
    for key, (path, document) in proofs.items():
        raw = encoded(document); store(path, raw); replacements[pins[key]] = sha(raw)
    replacements[165473] = len(helper)
    replacements['08aadae03037dd103c9706b07370b852f758f6ef05a2ae3a1d3aca7ea6453142'] = sha(helper)
    return SimpleNamespace(root=tmp_path, reader=reader, replacements=replacements, proofs=proofs, pins=pins,
        retained=retained, jhome=jhome, archive=archive, commit=commit, current=current,
        files=files, rows=old_rows, authority=authority)


def run_legacy_retired_controller_reader(value, monkeypatch, *, batch='RetiredCopies', selected='retired-187-188-189'):
    class FixedEvidenceLiterals(ast.NodeTransformer):
        def visit_Constant(self, node):
            if type(node.value) in (str, int) and node.value in value.replacements:
                return ast.copy_location(ast.Constant(value.replacements[node.value]), node)
            return node
    syntax = FixedEvidenceLiterals().visit(ast.parse(value.reader))
    ast.fix_missing_locations(syntax)
    arguments = ['actual-retired-copy-reader', str(value.archive), value.commit, str(value.retained),
                 str(value.jhome), CI_ROOT, value.current, batch]
    if selected is not None: arguments.append(selected)
    monkeypatch.setattr(sys, 'argv', arguments)
    # Only registration SHA/size literals differ. Conditions, branches, source
    # selection and returned records execute directly from the versioned reader.
    exec(compile(syntax, 'actual-retired-copy-reader', 'exec'), {})


def retired_reader_files(value):
    return {path.relative_to(value.root).as_posix(): path.read_bytes()
            for path in value.root.rglob('*') if path.is_file()}


def test_retired_194_actual_eighth_argument_reads_old_schema_and_reports_real_ecs_source_origin(legacy_retired_controller_reader, monkeypatch, capsys):
    value = legacy_retired_controller_reader; before = retired_reader_files(value)
    run_legacy_retired_controller_reader(value, monkeypatch)
    result = json.loads(capsys.readouterr().out)
    assert result['skipped'] == [] and [row['release'] for row in result['rows']] == [row['release'] for row in value.rows]
    assert len(result['authorityFiles']) == len(result['authorityCustody']) == 7
    assert {row['file'] for row in result['authorityFiles']} == set(value.files)
    source = next(row for row in result['authorityCustody'] if row['file'] == 'source.tar.gz')
    assert source == {'file': 'source.tar.gz', 'origin': 'ACTUAL_ECS_RETAINED_MAINTENANCE_SOURCE',
        'bytes': value.files['source.tar.gz'].stat().st_size, 'sha256': sha(value.files['source.tar.gz'].read_bytes()),
        'provenanceSha256': sha(value.proofs['provenance'][0].read_bytes()),
        'originalEcsPath': CI_ROOT + '/inbox/ci-194-2c2e65a0daa9/cleanup-source.tar.gz'}
    assert all(row['origin'] == 'PINNED_PRESERVED_JENKINS_ORIGINAL'
               for row in result['authorityCustody'] if row['file'] != 'source.tar.gz')
    assert all(entry['origin'] == 'PINNED_PRESERVED_JENKINS_ORIGINAL'
               for row in result['custody'] for entry in row['controls'].values())
    assert {row['file']: row['source'] for row in result['authorityFiles']} == {name: str(path) for name, path in value.files.items()}
    assert 'source.tar.gz' not in {row['path'] for row in value.proofs['preservation'][1]['files']}
    assert retired_reader_files(value) == before


def test_retired_controller_old_seven_argument_historical_entry_remains_usable(legacy_retired_controller_reader, monkeypatch, capsys):
    value = legacy_retired_controller_reader
    run_legacy_retired_controller_reader(value, monkeypatch, batch='Historical', selected=None)
    result = json.loads(capsys.readouterr().out)
    assert result['rows'] == [] and len(result['skipped']) == 16
    assert result['authorityFiles'] == result['authorityCustody'] == []
    assert len(result['helpers']) == 4


@pytest.mark.parametrize('selected', ['retired-187-188-189', 'retired-unknown'])
def test_retired_reader_rejects_wrong_policy_before_reading_any_original(legacy_retired_controller_reader, monkeypatch, capsys, selected):
    value = legacy_retired_controller_reader; value.archive.unlink()
    expected = 'RETIRED_COPY_BATCH_REQUIRES_RETIRED_COPIES' if selected == 'retired-187-188-189' else 'EXACT_RETIRED_COPY_BATCH_REQUIRED'
    with pytest.raises(ValueError, match=expected):
        run_legacy_retired_controller_reader(value, monkeypatch, batch='Historical', selected=selected)
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('missing', ['source', 'provenance', 'journal'])
def test_retired_194_reader_requires_the_separate_source_provenance_and_original_journal(legacy_retired_controller_reader, monkeypatch, capsys, missing):
    value = legacy_retired_controller_reader
    path = (value.files['source.tar.gz'] if missing == 'source' else value.proofs['provenance'][0]
            if missing == 'provenance' else value.files['native-jar-duplicate-canonical-journal.jsonl'])
    path.unlink(); before = retired_reader_files(value)
    with pytest.raises(FileNotFoundError): run_legacy_retired_controller_reader(value, monkeypatch)
    assert capsys.readouterr().out == '' and retired_reader_files(value) == before


@pytest.mark.parametrize(('changed', 'guard'), [
    ('source.tar.gz', 'RETIRED_AUTHORITY_ORIGINAL_BYTES_DRIFT'),
    ('native-jar-duplicate-canonical-journal.jsonl', 'RETIRED_AUTHORITY_ORIGINAL_BYTES_DRIFT'),
    ('provenance', 'RETIRED_AUTHORITY_SOURCE_PROVENANCE_SHA_DRIFT')])
def test_retired_194_reader_rechecks_actual_bytes_not_only_manifest_claims(legacy_retired_controller_reader, monkeypatch, capsys, changed, guard):
    value = legacy_retired_controller_reader
    path = value.proofs['provenance'][0] if changed == 'provenance' else value.files[changed]
    path.write_bytes(path.read_bytes() + b' '); before = retired_reader_files(value)
    with pytest.raises(ValueError, match=guard): run_legacy_retired_controller_reader(value, monkeypatch)
    assert capsys.readouterr().out == '' and retired_reader_files(value) == before


@pytest.mark.parametrize(('changed', 'guard'), [
    ('old-proof-schema', 'RETIRED_AUTHORITY_CUSTODY_CONTEXT_DRIFT'),
    ('old-original-path', 'RETIRED_AUTHORITY_CUSTODY_MEMBER_DRIFT'),
    ('journal-supplement', 'RETIRED_AUTHORITY_SUPPLEMENT_MEMBER_DRIFT'),
    ('source-origin', 'RETIRED_AUTHORITY_SOURCE_PROVENANCE_CONTEXT_DRIFT'),
    ('source-path', 'RETIRED_AUTHORITY_SOURCE_PROVENANCE_CONTEXT_DRIFT'),
    ('source-helper', 'RETIRED_AUTHORITY_SOURCE_PROVENANCE_CONTEXT_DRIFT')])
def test_retired_194_reader_validates_real_custody_structure_after_fixed_proof_binding(legacy_retired_controller_reader, monkeypatch, capsys, changed, guard):
    value = legacy_retired_controller_reader
    key = 'preservation' if changed.startswith('old-') else 'supplement' if changed == 'journal-supplement' else 'provenance'
    path, document = value.proofs[key]
    if changed == 'old-proof-schema': document['allOriginalCopiesByteEqual'] = False
    elif changed == 'old-original-path': document['files'][0]['original'] = '/another-build/build.xml'
    elif changed == 'journal-supplement':
        next(row for row in document['inputs'] if row['file'].endswith('journal.jsonl'))['sha256'] = '0' * 64
    elif changed == 'source-origin': document['kind'] = 'preserved-jenkins-archive'
    elif changed == 'source-path': document['path'] = document['path'].replace('/cleanup-source.tar.gz', '/source.tar.gz')
    else: document['helper']['sha256'] = '0' * 64
    raw = encoded(document); path.write_bytes(raw); value.replacements[value.pins[key]] = sha(raw)
    before = retired_reader_files(value)
    with pytest.raises(ValueError, match=guard): run_legacy_retired_controller_reader(value, monkeypatch)
    assert capsys.readouterr().out == '' and retired_reader_files(value) == before


def test_native_retention_jenkins_and_seed_choices_have_the_same_safe_default_and_action_guard():
    root = MODULE.parents[2]
    workflow = (root / 'Jenkinsfile.ecs-monolith').read_text(encoding='utf8')
    seed = (root / 'script/jenkins/configure-local.groovy').read_text(encoding='utf8')
    pipeline = (root / 'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    workflow_choices = re.search(r"choice\(name: 'NATIVE_RETENTION_POLICY', choices: (\[[^\]]+\])", workflow)
    seed_choices = re.search(r"ChoiceParameterDefinition\('NATIVE_RETENTION_POLICY', (\[[^\]]+\]) as String\[\]", seed)
    assert workflow_choices and seed_choices
    assert ast.literal_eval(workflow_choices[1]) == ast.literal_eval(seed_choices[1]) == ['FailedNative', 'RetiredCopies194', 'RetiredCopies203', 'PublicCaches221224235']
    assert "env.NATIVE_RETENTION_POLICY = params.NATIVE_RETENTION_POLICY ?: 'FailedNative'" in workflow
    assert "env.NATIVE_RETENTION_POLICY != 'FailedNative' && params.ACTION != 'reclaim-build-outputs'" in workflow
    assert "$nativeRetentionPolicy -cne 'FailedNative' -and $env:ACTION -cne 'reclaim-build-outputs'" in pipeline
    assert "if ([string]::IsNullOrWhiteSpace($nativeRetentionPolicy)) {$nativeRetentionPolicy='FailedNative'}" in pipeline


def test_exact_failed_native_selector_is_optional_scoped_and_bound_through_every_controller_entry():
    root = MODULE.parents[2]
    workflow = (root / 'Jenkinsfile.ecs-monolith').read_text(encoding='utf8')
    seed = (root / 'script/jenkins/configure-local.groovy').read_text(encoding='utf8')
    pipeline = (root / 'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    controller = (MODULE.parent / 'retire-failed-native-jar-duplicates.ps1').read_text(encoding='utf8')
    assert "string(name: 'FAILED_NATIVE_BUILD_NUMBER', defaultValue: '', trim: true" in workflow
    assert "new StringParameterDefinition('FAILED_NATIVE_BUILD_NUMBER', ''," in seed
    assert "').with { setTrim(true); it }" in next(line for line in seed.splitlines() if "StringParameterDefinition('FAILED_NATIVE_BUILD_NUMBER'" in line)
    assert "env.FAILED_NATIVE_BUILD_NUMBER = params.FAILED_NATIVE_BUILD_NUMBER?.trim() ?: ''" in workflow
    assert "params.ACTION != 'reclaim-build-outputs' || env.NATIVE_RETENTION_POLICY != 'FailedNative'" in workflow
    assert "selectedBuild < 221 || selectedBuild >= env.BUILD_NUMBER.toLong() || selectedBuild >= env.RELEASE_TAG.tokenize('-')[1].toLong()" in workflow
    assert "$failedNativeBuildNumber=[string]$env:FAILED_NATIVE_BUILD_NUMBER" in pipeline
    assert "$env:ACTION -cne 'reclaim-build-outputs' -or $nativeRetentionPolicy -cne 'FailedNative'" in pipeline
    assert "[long]$failedNativeBuildNumber -lt 221" in pipeline and "[long]$failedNativeBuildNumber -ge [long]$currentBuildNumber" in pipeline
    assert pipeline.index('if ($failedNativeBuildNumber -cne') < pipeline.index("if ($env:ACTION -ceq 'reclaim-build-outputs') {")
    call = next(line for line in pipeline.splitlines() if '-CanonicalBatch FailedNative -SshOptions' in line)
    assert call.endswith('-FailedNativeBuildNumber $failedNativeBuildNumber')
    assert "[string]$FailedNativeBuildNumber = ''" in controller
    assert "$Mode -ceq 'Maintenance' -and $CanonicalBatch -ceq 'FailedNative'" in controller
    assert "'\\A[1-9][0-9]{0,8}\\z'" in controller
    assert '$local.selectedFailedNativeBuild -ceq $FailedNativeBuildNumber' in controller
    assert "$spec.Add('selectedFailedNativeBuild',$FailedNativeBuildNumber)" in controller
    assert "--failed-native-build-number '$FailedNativeBuildNumber'" in controller
    assert "@($captured.skipped | Where-Object {$_.reason -cne 'FAILED_NATIVE_BINARIES_NOT_PRESENT'}).Count -eq 0" in controller
    assert 'include_inbox=True' in MODULE.read_text(encoding='utf8')


def test_native_retention_pipeline_selects_one_batch_after_ordinary_cleanup_and_preserves_203_default():
    root = MODULE.parents[2]
    pipeline = (root / 'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    branch = pipeline.split("if ($Action -ceq 'ReclaimBuildOutputs' -and $env:ACTION -ceq 'reclaim-build-outputs') {", 1)[1].split("if ($Action -eq 'Preflight')", 1)[0]
    assert branch.index('reclaim-build-outputs.ps1 -Mode Maintenance') < branch.index("if ($nativeRetentionPolicy -ceq 'PublicCaches221224235')")
    selector = branch.split("if ($nativeRetentionPolicy -ceq 'PublicCaches221224235')", 1)[1]
    public, selector = selector.split("} elseif ($nativeRetentionPolicy -ceq 'RetiredCopies194')", 1)
    assert '-CanonicalBatch PublicCaches -SshOptions' in public and '-RetiredCopyBatch' not in public
    older, remainder = selector.split("} elseif ($nativeRetentionPolicy -ceq 'RetiredCopies203')", 1)
    recent, default = remainder.split('} else {', 1)
    calls = re.findall(r'& ./script/jenkins/retire-failed-native-jar-duplicates\.ps1[^\n]+', public + selector)
    assert len(calls) == 4
    assert '-CanonicalBatch RetiredCopies -RetiredCopyBatch retired-187-188-189' in older
    assert '-CanonicalBatch RetiredCopies -SshOptions' in recent and '-RetiredCopyBatch' not in recent
    assert '-CanonicalBatch FailedNative -SshOptions' in default and '-RetiredCopyBatch' not in default
    controller = (MODULE.parent / 'retire-failed-native-jar-duplicates.ps1').read_text(encoding='utf8')
    assert "[string]$CanonicalBatch = 'Historical'" in controller
    assert "[ValidateSet('retired-195-198-201','retired-187-188-189')][string]$RetiredCopyBatch = 'retired-195-198-201'" in controller
    assert "$RetiredCopyBatch -ceq 'retired-195-198-201' -or $CanonicalBatch -ceq 'RetiredCopies'" in controller
    assert "$Tag,$CanonicalBatch,$RetiredCopyBatch,$FailedNativeBuildNumber)" in controller
    assert "if($CanonicalBatch -ceq 'RetiredCopies' -and $RetiredCopyBatch -ceq 'retired-187-188-189') {$common+=\" --retired-copy-batch retired-187-188-189\"}" in controller
    assert '$retiredAuthorityTag=if ($RetiredCopyBatch' in controller
    assert 'native-retired-candidate-controls/$retiredAuthorityTag/$($binding.file)' in controller

@pytest.fixture
def public_cache_controller_reader(legacy_retired_controller_reader):
    value = legacy_retired_controller_reader
    approved = next(ast.literal_eval(node.value) for node in ast.walk(ast.parse(value.reader))
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.List) and len(node.value.elts) == 6
        and any(isinstance(name, ast.Name) and name.id == 'approved' for name in node.targets))
    public_rows = []; proof_paths = {}
    for number, commit, preservation_sha in approved:
        tag = 'ci-' + str(number) + '-' + commit[:12]; folder = value.retained / ('ci-' + str(number) + '-raw-receipts')
        folder.mkdir(exist_ok=True)
        context = {'release': tag, 'commit': commit, 'sourceSha256': sha(('public source ' + tag).encode())}
        result = 'ABORTED' if number == 223 else 'FAILURE'
        bodies = {'build.xml': flow_xml(context, result=result), 'release.json': encoded(context),
                  'local-build.json': encoded({'status': 'PASS'}), 'fixture-cleanup.json': encoded({'status': 'STOPPED'})}
        entries = []
        for name, raw in bodies.items():
            (folder / name).write_bytes(raw)
            if name == 'build.xml' and number != 117: continue
            suffix = '/build.xml' if name == 'build.xml' else '/archive/artifacts/' + name
            entries.append({'path': name, 'bytes': len(raw), 'sha256': sha(raw),
                'original': '/synthetic-jenkins/jobs/doorhandle-java/builds/' + str(number) + suffix})
        proof = {'build': number, 'files': entries}
        if number == 117: proof.update(allOriginalCopiesByteEqual=True, summarySha256=sha(b'keeper summary'))
        else: proof.update(commit=commit, result=result, buildXmlSha256=sha(bodies['build.xml']), binaryRetention='synthetic')
        raw = encoded(proof); path = folder / 'preservation.json'; path.write_bytes(raw)
        value.replacements[preservation_sha] = sha(raw); proof_paths[number] = (path, proof, preservation_sha)
        public_rows.append(context)
    value.public_rows = public_rows; value.public_proofs = proof_paths
    return value


def test_public_cache_actual_reader_uses_117_and_five_modern_d_fallbacks_without_reading_any_jar(public_cache_controller_reader, monkeypatch, capsys):
    value = public_cache_controller_reader; original_open = Path.open
    def no_jar(path, *args, **kwargs):
        assert path.name not in ('application.jar', 'candidate-app.jar'), 'Public-only capture may not depend on a retired JAR'
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', no_jar)
    before = retired_reader_files(value)
    run_legacy_retired_controller_reader(value, monkeypatch, batch='PublicCaches', selected=None)
    result = json.loads(capsys.readouterr().out)
    assert result['skipped'] == [] and [row['release'] for row in result['rows']] == [row['release'] for row in value.public_rows]
    assert len(result['rows']) == 6 and result['builderFiles'] == [] and result['authorityFiles'] == []
    assert all(control['origin'] == 'PINNED_PRESERVED_JENKINS_ORIGINAL'
               for row in result['custody'] for control in row['controls'].values())
    assert all('build.xml' not in {row['path'] for row in proof['files']}
               for number, (path, proof, pin) in value.public_proofs.items() if number != 117)
    assert retired_reader_files(value) == before


@pytest.mark.parametrize('changed', ['terminal-top-level-digest', 'missing-release'])
def test_public_cache_reader_does_not_accept_partial_or_unbound_modern_d_originals(public_cache_controller_reader, monkeypatch, capsys, changed):
    value = public_cache_controller_reader; path, proof, pin = value.public_proofs[221]
    if changed == 'terminal-top-level-digest':
        proof['buildXmlSha256'] = '0' * 64; raw = encoded(proof); path.write_bytes(raw); value.replacements[pin] = sha(raw)
    else: (path.parent / 'release.json').unlink()
    run_legacy_retired_controller_reader(value, monkeypatch, batch='PublicCaches', selected=None)
    result = json.loads(capsys.readouterr().out)
    assert len(result['rows']) == 5 and len(result['skipped']) == 1
    assert result['skipped'][0]['release'] == 'ci-221-8c30776fcd95'
    if changed == 'terminal-top-level-digest':
        assert result['skipped'][0]['reason'] == 'PRESERVED_PUBLIC_TERMINAL_CONTROL_DRIFT'
    assert result['authorityFiles'] == []


def test_public_cache_controller_has_an_independent_capture_complete_counts_and_no_jar_or_builder_phase():
    controller = (MODULE.parent / 'retire-failed-native-jar-duplicates.ps1').read_text(encoding='utf8')
    assert "if($CanonicalBatch -ceq 'PublicCaches'){'capture-public-cache-request'}" in controller
    assert "if($CanonicalBatch -ceq 'PublicCaches') {$common+=\" --public-cache-batch failed-native-public-221-224-235\"}" in controller
    assert "@($local.rows).Count -eq 6 -and @($local.skipped).Count -eq 0" in controller
    branch = controller.split("if($CanonicalBatch -ceq 'PublicCaches') {\n    $publicCacheBatch=", 1)[1].split("if($CanonicalBatch -ceq 'FailedNative') {", 1)[0]
    for phase in ('plan-public-layers', 'apply-public-layers', 'plan-generated-image-archives', 'apply-generated-image-archives'):
        assert phase in branch
    assert "count=20" in branch and "count=5" in branch and '$plannedPublic.candidateAttemptCount -eq 5' in branch
    assert "$plannedPublic.candidateTargetCount -eq $step.count" in branch and '@($plannedPublic.skipped).Count -eq 0' in branch
    assert "finally {Copy-NativeJarEvidence (Invoke-NativeJarPhase 'inspect')}" in branch
    assert 'journalSha256' in branch and 'df -B1 --output=avail' in branch and 'sameBytesAsSeedClaimed' in branch
    assert 'deletedFiles=25' in branch and branch.rstrip().endswith('}') and '    return\n}' in branch
    for forbidden in ('plan-builders', 'apply-builders', 'plan-canonical', 'apply-canonical', 'plan-python-build-cache', 'apply-python-build-cache'):
        assert forbidden not in branch
