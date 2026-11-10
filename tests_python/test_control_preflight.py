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
        'test_jenkins_resource_budget', 'test_jenkins_fixture_admission',
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
        'test_control_preflight',
    }
    assert minimum['test_public_buildkit_layer_retirement'] >= 34
    assert minimum['test_local_mysql_source_classification'] >= 130
    assert minimum['test_project_mysql_custody'] >= 32
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
