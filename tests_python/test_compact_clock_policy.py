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


def test_empty_sources_use_zero_only_as_an_unused_placeholder_and_require_frozen_exact_counts():
    offsets = {'workbench': None, 'binding': '+00:00'}
    document = {**policy('workbench'), 'emptyDomains': ['binding']}
    snapshot = {'snapshotSha256': 'a' * 64, 'tables': {'organization_binding_audit': {'rows': 0}}}
    clock.require_empty_sources(offsets, document, snapshot)
    for count in (1, None, False, '0'):
        bad = {**snapshot, 'tables': {'organization_binding_audit': {'rows': count}}}
        with pytest.raises(ValueError, match='exact zero rows'):
            clock.require_empty_sources(offsets, document, bad)
    with pytest.raises(ValueError, match='exact zero rows'):
        clock.require_empty_sources(offsets, document, {**snapshot, 'tables': {}})


def test_empty_domain_policy_rejects_guessed_offsets_duplicates_and_unregistered_tables():
    offsets = {'workbench': None, 'binding': '+00:00'}
    for domains in ([], ['binding', 'binding'], ['other'], ['research', 'binding']):
        with pytest.raises(ValueError):
            clock.validate(offsets, {**policy('workbench'), 'emptyDomains': domains})
    with pytest.raises(ValueError):
        clock.validate({**offsets, 'binding': '+08:00'}, {**policy('workbench'), 'emptyDomains': ['binding']})


def test_empty_domain_policy_is_bound_globally_while_workbench_receives_its_own_strict_protocol():
    offsets = {'workbench': None, 'binding': '+00:00'}
    document = {**policy('workbench'), 'emptyDomains': ['binding']}
    assert clock.policy_digest(offsets, document) != clock.policy_digest(offsets, policy('workbench'))
    assert clock.workbench_fields(offsets, document, 'a' * 64)['legacyClockPolicy'] == policy('workbench')


def test_complete_source_policy_never_guesses_offsets_and_keeps_timeless_control_rows():
    offsets = {name: None if name in clock.UNRESOLVED_DOMAINS else '+00:00' for name in clock.DOMAINS}
    document = {**policy(*clock.UNRESOLVED_DOMAINS), 'emptyDomains': sorted(clock.EMPTY_DOMAIN_TABLES)}
    assert set(document['emptyDomains']) | set(document['unresolvedDomains']) == clock.DOMAINS
    tables = {table: {'rows': 0} for names in clock.EMPTY_DOMAIN_TABLES.values() for table in names}
    # A time-free control record is ordinary business data and remains eligible
    # for copying. The empty fence applies only to the reviewed clock inputs.
    tables['agent_context_head'] = {'rows': 4}
    snapshot = {'snapshotSha256': 'a' * 64, 'tables': tables}
    clock.require_empty_sources(offsets, document, snapshot)
    tables['agent_model_config_command']['rows'] = 1
    with pytest.raises(ValueError, match='exact zero rows'):
        clock.require_empty_sources(offsets, document, snapshot)
