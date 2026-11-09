"""Pure metadata checks for canonical Compose selection with stopped CI objects."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[1] / 'script/docker/assignment-compat.py'
SPEC = importlib.util.spec_from_file_location('compose_container_selection_guard', SOURCE)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)
PROJECT = guard.PROJECT


def node(letter, *, canonical=False, running=False):
    labels = {'com.docker.compose.project': PROJECT, 'com.docker.compose.service': 'mem0'}
    if canonical:
        labels.update({'com.docker.compose.container-number': '1', 'com.docker.compose.oneoff': 'False'})
    return {'Id': letter * 64, 'Image': 'sha256:' + 'f' * 64,
            'Name': '/' + PROJECT + '-mem0-1' if canonical else '/doorhandle-ci-python-' + letter,
            'Config': {'Labels': labels},
            'State': {'Running': running, 'Pid': 200 if running else 0,
                      'Status': 'running' if running else 'exited', 'Paused': False, 'Restarting': False, 'Dead': False}}


def install(monkeypatch, rows, ids=None):
    ids = [row['Id'] for row in rows] if ids is None else ids
    calls = []
    def docker(*args):
        calls.append(args)
        if args[0] == 'ps':
            assert args == ('ps', '-aq', '--no-trunc', '--filter', 'label=com.docker.compose.project=' + PROJECT,
                            '--filter', 'label=com.docker.compose.service=mem0')
            return ('\n'.join(ids) + '\n').encode()
        assert args == ('inspect', *ids)
        return json.dumps(rows).encode()
    monkeypatch.setattr(guard, 'docker', docker)
    return calls


@pytest.mark.parametrize('running', [True, False])
def test_single_object_keeps_existing_behavior_without_canonical_name(monkeypatch, running):
    row = node('a', running=running)
    install(monkeypatch, [row])
    assert guard.container(PROJECT, 'mem0') == row


@pytest.mark.parametrize('running', [True, False])
def test_unique_canonical_is_selected_with_only_stopped_historical_objects(monkeypatch, running):
    selected = node('a', canonical=True, running=running)
    rows = [node('b'), selected, node('c')]
    install(monkeypatch, rows)
    assert guard.container(PROJECT, 'mem0') == selected


@pytest.mark.parametrize('change', [
    {'Running': True, 'Pid': 301, 'Status': 'running'},
    {'Paused': True}, {'Restarting': True}, {'Dead': True},
    {'Pid': 301}, {'Status': 'removing'}, {'Pid': False},
])
def test_other_active_or_uncertain_object_is_never_ignored(monkeypatch, change):
    historical = node('b'); historical['State'].update(change)
    install(monkeypatch, [node('a', canonical=True, running=True), historical])
    with pytest.raises(guard.GuardError, match='Competing active or uncertain'):
        guard.container(PROJECT, 'mem0')


@pytest.mark.parametrize('change', [
    {'Running': False, 'Pid': 301, 'Status': 'exited'},
    {'Running': True, 'Pid': 0, 'Status': 'running'}, {'Paused': True},
])
def test_canonical_object_must_have_a_consistent_running_or_stopped_state(monkeypatch, change):
    selected = node('a', canonical=True, running=True); selected['State'].update(change)
    install(monkeypatch, [selected, node('b')])
    with pytest.raises(guard.GuardError, match='Competing active or uncertain'):
        guard.container(PROJECT, 'mem0')


@pytest.mark.parametrize('canonical_count', [0, 2])
def test_multiple_objects_require_exactly_one_canonical_name(monkeypatch, canonical_count):
    install(monkeypatch, [node('a', canonical=canonical_count == 2), node('b', canonical=canonical_count == 2)])
    with pytest.raises(guard.GuardError, match='Ambiguous canonical'):
        guard.container(PROJECT, 'mem0')


@pytest.mark.parametrize('key,value', [
    ('com.docker.compose.container-number', None), ('com.docker.compose.oneoff', 'True'),
])
def test_canonical_name_alone_cannot_replace_compose_identity_labels(monkeypatch, key, value):
    selected = node('a', canonical=True); selected['Config']['Labels'][key] = value
    install(monkeypatch, [selected, node('b')])
    with pytest.raises(guard.GuardError, match='Canonical Compose service labels differ'):
        guard.container(PROJECT, 'mem0')


@pytest.mark.parametrize('optional', [True, False])
def test_empty_optional_service_and_required_service_keep_their_semantics(monkeypatch, optional):
    calls = install(monkeypatch, [])
    if optional:
        assert guard.container(PROJECT, 'mem0', optional=True) is None
    else:
        with pytest.raises(guard.GuardError):
            guard.container(PROJECT, 'mem0')
    assert len(calls) == 1


@pytest.mark.parametrize('ids', [['a' * 64, 'a' * 64], ['a' * 12]])
def test_duplicate_or_partial_discovered_identity_is_rejected_before_inspect(monkeypatch, ids):
    calls = install(monkeypatch, [], ids)
    with pytest.raises(guard.GuardError):
        guard.container(PROJECT, 'mem0')
    assert len(calls) == 1


@pytest.mark.parametrize('defect', ['missing', 'duplicate', 'changed_id'])
def test_inspection_must_close_exactly_to_discovered_full_ids(monkeypatch, defect):
    rows = [node('a', canonical=True), node('b')]
    if defect == 'missing': rows.pop()
    elif defect == 'duplicate': rows[1] = copy.deepcopy(rows[0])
    else: rows[1]['Id'] = 'c' * 64
    install(monkeypatch, rows, ['a' * 64, 'b' * 64])
    with pytest.raises(guard.GuardError, match='Container metadata changed'):
        guard.container(PROJECT, 'mem0')


@pytest.mark.parametrize('defect', ['project', 'service', 'image'])
def test_every_inspected_object_retains_exact_project_service_and_image_checks(monkeypatch, defect):
    historical = node('b')
    if defect == 'image': historical['Image'] = 'unversioned:latest'
    else: historical['Config']['Labels']['com.docker.compose.' + defect] = 'another'
    install(monkeypatch, [node('a', canonical=True, running=True), historical])
    with pytest.raises(guard.GuardError, match='does not belong'):
        guard.container(PROJECT, 'mem0')
