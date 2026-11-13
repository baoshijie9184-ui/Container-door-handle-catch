"""Original XML must prove native Qdrant cases; execution is ECS-only."""
import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('middleware_evidence_verifier', ROOT / 'script/jenkins/verify-ecs.py')
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)
REMOTE_SPEC = importlib.util.spec_from_file_location('middleware_remote_verifier', ROOT / 'script/jenkins/verify-remote.py')
remote = importlib.util.module_from_spec(REMOTE_SPEC)
REMOTE_SPEC.loader.exec_module(remote)
JAVA = 'com.ruanzhu.doorhandle.framework.semantic.QdrantSemanticIntegrationTest'
PYTHON = 'test_real_native_qdrant_keeps_public_id_vector_direction_and_account_filters'


def reports(tmp_path, java_issue=None, python_issue=None, java_name=JAVA, python_name=PYTHON):
    folder = tmp_path / 'java/doorhandle-framework/surefire-reports'
    folder.mkdir(parents=True)
    for file, classname, name, issue in ((folder / ('TEST-' + JAVA + '.xml'), java_name, 'nativeSdkCase', java_issue),
            (tmp_path / 'python.xml', 'tests_python.test_memory_qdrant', python_name, python_issue)):
        suite = ET.Element('testsuite')
        case = ET.SubElement(suite, 'testcase', classname=classname, name=name)
        if issue:
            ET.SubElement(case, issue)
        ET.ElementTree(suite).write(file, encoding='utf8')


def test_native_reports_do_not_claim_bge_activation(tmp_path):
    reports(tmp_path)
    proof = verifier.middleware_protocol_reports(tmp_path)
    assert proof == {'status': 'PASS', 'javaNativeCases': 1, 'pythonNativeCases': 1,
                     'embeddingProfile': 'EXPLICIT_TEST_ONLY', 'providerCalls': 0,
                     'productionActivationVerified': False}


@pytest.mark.parametrize('language', ['java', 'python'])
@pytest.mark.parametrize('issue', ['failure', 'error', 'skipped'])
def test_native_failure_error_or_skip_cannot_pass(tmp_path, language, issue):
    reports(tmp_path, **{language + '_issue': issue})
    with pytest.raises(RuntimeError, match='missing, failed or skipped'):
        verifier.middleware_protocol_reports(tmp_path)


def test_adjacent_mock_transport_cannot_replace_python_native_case(tmp_path):
    reports(tmp_path, python_name='test_mock_transport_accepts_requests')
    with pytest.raises(RuntimeError, match='missing, failed or skipped'):
        verifier.middleware_protocol_reports(tmp_path)


def test_adjacent_java_unit_class_cannot_replace_native_case(tmp_path):
    reports(tmp_path, java_name='com.ruanzhu.doorhandle.framework.semantic.MockStoreTest')
    with pytest.raises(RuntimeError, match='missing, failed or skipped'):
        verifier.middleware_protocol_reports(tmp_path)


def observability_reports(tmp_path, issue=None):
    folder = tmp_path / 'source-regression/java/doorhandle-module-app/surefire-reports'
    folder.mkdir(parents=True)
    suite = ET.Element('testsuite')
    ET.SubElement(suite, 'testcase', classname='com.ruanzhu.doorhandle.module.app.config.PrometheusScrapeIntegrationTest', name='nativeScrape')
    ET.ElementTree(suite).write(folder / 'TEST-PrometheusScrapeIntegrationTest.xml', encoding='utf8')
    suite = ET.Element('testsuite')
    case = ET.SubElement(suite, 'testcase', classname='tests_python.test_observability_scrape', name='nativePythonMetrics')
    if issue:
        ET.SubElement(case, issue)
    ET.ElementTree(suite).write(tmp_path / 'python.xml', encoding='utf8')


def test_observability_native_reports_keep_langfuse_deferred(tmp_path):
    observability_reports(tmp_path)
    proof = verifier.observability_protocol_reports(tmp_path)
    assert proof['status'] == 'PASS' and proof['javaNativeCases'] == proof['pythonNativeCases'] == 1
    assert proof['langfuseRuntime'] == 'DEFERRED_BY_USER' and proof['providerCalls'] == 0


@pytest.mark.parametrize('issue', ['failure', 'error', 'skipped'])
def test_observability_requires_actual_unskipped_python_scrape(tmp_path, issue):
    observability_reports(tmp_path, issue)
    with pytest.raises(RuntimeError, match='missing, failed or skipped'):
        verifier.observability_protocol_reports(tmp_path)


@pytest.mark.parametrize('count,issue,accepted', [(15, None, True), (14, None, False), (15, 'skipped', False), (15, 'failure', False)])
def test_mysql_fence_proof_requires_all_native_cases_not_source_skips(tmp_path, count, issue, accepted):
    folder = tmp_path / 'java/doorhandle-module-app/surefire-reports'
    folder.mkdir(parents=True)
    suite = ET.Element('testsuite')
    for number in range(count):
        case = ET.SubElement(suite, 'testcase', classname='com.ruanzhu.doorhandle.module.app.service.knowledge.QualityKnowledgeMySqlTest', name='case' + str(number))
        if number == 0 and issue:
            ET.SubElement(case, issue)
    ET.ElementTree(suite).write(folder / 'TEST-QualityKnowledgeMySqlTest.xml', encoding='utf8')
    if accepted:
        proof = verifier.semantic_mysql_protocol_reports(tmp_path)
        assert proof['nativeCases'] == 15 and proof['wholeDatabaseMigrationVerified'] is False
    else:
        with pytest.raises(RuntimeError, match='all 15 actual isolated MySQL cases'):
            verifier.semantic_mysql_protocol_reports(tmp_path)


def test_source_mysql_component_uses_existing_native_suite_then_unflagged_regression(monkeypatch):
    monkeypatch.setenv('DOORHANDLE_REQUIRE_SEMANTIC_MYSQL_TESTS', 'true')
    monkeypatch.setenv('DOORHANDLE_TEST_SEMANTIC_MYSQL_CONFIG', '/source/work/semantic-mysql/feature.json')
    args = SimpleNamespace(fixture_manifest=None, java_tests=None, java_only=False, fixture_property=[],
                           java_suites=[], source_regression=False)
    with mock.patch.object(verifier, 'admit_fixture_suite', return_value=(['-Ddoorhandle.feature.mysql.config=/private'], {}, {'/private': 'digest'})) as admission:
        name = verifier.semantic_mysql_source_suite(args, {'executionLocation': 'ECS'})
    assert name.endswith('.QualityKnowledgeMySqlTest') and args.source_regression is True
    assert args.java_suites[0]['javaSelection'] == [name]
    assert args.java_suites[0]['fixtureProperties'] == ['doorhandle.feature.mysql.config']
    assert admission.call_args.args[1] == {'doorhandle.feature.mysql.config': '/source/work/semantic-mysql/feature.json'}
    assert not hasattr(args, 'compact_migration_config')


def test_source_mysql_component_does_not_override_existing_explicit_scope(monkeypatch):
    monkeypatch.setenv('DOORHANDLE_REQUIRE_SEMANTIC_MYSQL_TESTS', 'true')
    args = SimpleNamespace(fixture_manifest=Path('/existing.json'), java_tests=None, java_only=False, fixture_property=[])
    with mock.patch.object(verifier, 'admit_fixture_suite') as admission, pytest.raises(ValueError, match='another explicit fixture scope'):
        verifier.semantic_mysql_source_suite(args, {'executionLocation': 'ECS'})
    admission.assert_not_called()


@pytest.mark.parametrize('status,metrics,expected', [
    ('PASS', 'PASS', 'PASS'), ('PASS', 'FAILED', 'FAILED'), ('PASS', 'NOT_RUN', 'FAILED'),
    ('FAILED', 'PASS', 'FAILED'), ('FAILED', 'FAILED', 'FAILED'),
])
def test_metric_acceptance_failure_is_not_an_owned_cleanup_failure(status, metrics, expected):
    record = {'status': status}
    remote.record_observability_acceptance(record, {'metricsAcceptance': metrics})
    assert record['status'] == expected
    assert 'observabilityCleanupErrorType' not in record
    assert ('observabilityAcceptanceErrorType' in record) is (status == 'PASS' and metrics != 'PASS')
