"""Clock preservation policy contracts; execute in Jenkins on the admitted ECS."""
import importlib.util
from pathlib import Path

import pytest


FILE = Path(__file__).resolve().parents[1] / 'script/schema/compact_clock_policy.py'
SPEC = importlib.util.spec_from_file_location('compact_clock_policy_contract', FILE)
clock = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(clock)


def policy(*names):
    return {'version': 1, 'kind': clock.POLICY_KIND, 'unresolvedDomains': sorted(names)}


def test_fixed_only_callers_keep_explicit_offsets_without_a_policy():
    assert clock.validate({'workspace': '+08:00', 'digest': '+00:00'}) == []
    assert clock.offset_literal_value('workspace', {'workspace': '+08:00'}) == '+08:00'


@pytest.mark.parametrize('value', ['', 'UTC', 'Asia/Shanghai', 'UNRESOLVED', '+14:01', '-15:00', 0, False])
def test_fixed_offsets_cannot_hide_a_default_or_unresolved_value(value):
    with pytest.raises(ValueError):
        clock.validate({'workspace': value})


def test_null_cannot_be_silently_replaced_by_utc():
    with pytest.raises(ValueError, match='explicit preservation policy'):
        clock.validate({'workspace': None})
    assert clock.offset_literal_value('workspace', {'workspace': None}, policy('workspace')) == 'UNRESOLVED'


@pytest.mark.parametrize('document', [policy('agent'), policy('agent', 'workspace'),
    {'version': True, 'kind': clock.POLICY_KIND, 'unresolvedDomains': ['workspace']},
    {'version': 1, 'kind': clock.POLICY_KIND, 'unresolvedDomains': ['workspace'], 'defaultOffset': '+08:00'},
    {'version': 1, 'kind': clock.POLICY_KIND, 'unresolvedDomains': ['workspace', 'workspace']}])
def test_policy_must_be_exact_canonical_and_match_the_actual_nulls(document):
    with pytest.raises(ValueError):
        clock.validate({'workspace': None}, document)


def test_unimplemented_domains_and_incomplete_copy_coverage_fail_closed():
    with pytest.raises(ValueError):
        clock.validate({'digest': None}, policy('digest'))
    with pytest.raises(ValueError):
        clock.validate({'workspace': '+08:00'}, expected_domains={'workspace', 'action'})
    with pytest.raises(ValueError):
        clock.validate({'not_registered': '+08:00'})


def test_policy_digest_binds_known_offsets_and_unknown_domains():
    first = {'workspace': None, 'action': '+08:00'}
    assert clock.policy_digest(first, policy('workspace')) == clock.policy_digest(dict(reversed(list(first.items()))), policy('workspace'))
    assert clock.policy_digest(first, policy('workspace')) != clock.policy_digest({**first, 'action': '+00:00'}, policy('workspace'))


def test_workbench_v2_requires_a_real_snapshot_shape_and_never_default_offset():
    offsets = {'workbench': None}
    with pytest.raises(ValueError):
        clock.workbench_fields(offsets, policy('workbench'), None)
    fields = clock.workbench_fields(offsets, policy('workbench'), 'a' * 64)
    assert fields == {'legacyClockPolicy': policy('workbench'), 'sourceSnapshotSha256': 'a' * 64}
    assert clock.workbench_fields({'workbench': '+08:00'}, None, None) == {}
