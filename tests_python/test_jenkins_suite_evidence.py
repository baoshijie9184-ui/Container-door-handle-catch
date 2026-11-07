"""ECS-run evidence contracts for serial suites and their unchanged original reports."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
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


def test_old_owned_staging_parent_is_private_without_reclaiming_an_attempt(tmp_path):
    parent = tmp_path / 'verification'
    parent.mkdir(mode=0o775)
    os.chmod(parent, 0o775)
    args = SimpleNamespace(tag='ci-57-' + 'a' * 12, scope='source',
                           attempt='b' * 32, commit='a' * 40, source_sha256='c' * 64)
    attempt, checkout = remote.prepare_checkout(tmp_path, args, {'instanceId': 'i-fixture'})
    assert stat.S_IMODE(parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(checkout.stat().st_mode) == 0o700
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
