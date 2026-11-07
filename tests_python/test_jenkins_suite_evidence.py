"""ECS-run evidence contracts for serial suites and their unchanged original reports."""
import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
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
