"""Explicit legacy wall-clock policy; never infer an instant from a wall value.

This module is pure validation/serialization. Live migration binds its SQL to the
reviewed source snapshot and subsequently proves that snapshot under its lock.
"""
from __future__ import annotations

import hashlib
import json
import re


PROTOCOL = 'doorhandle-legacy-clock-v1'
POLICY_KIND = 'doorhandle-legacy-clock-policy'
UNRESOLVED = 'UNRESOLVED'
DOMAINS = frozenset(('action', 'agent', 'binding', 'chat', 'context', 'detection',
    'digest', 'export', 'identity', 'inbox', 'infra_log', 'mcp', 'memory', 'model',
    'model_file', 'model_log', 'operations', 'report', 'research', 'sdk', 'skill',
    'workbench', 'workspace'))
# Only the copy/read protocols with a reviewed unknown-clock branch may opt in.
UNRESOLVED_DOMAINS = frozenset(('action', 'agent', 'inbox', 'infra_log', 'mcp',
    'memory', 'model_log', 'report', 'sdk', 'skill', 'workbench', 'workspace'))
OFFSET = re.compile(r'[+-](?:0[0-9]|1[0-4]):[0-5][0-9]')
SHA = re.compile(r'[a-f0-9]{64}')
EMPTY_DOMAIN_TABLES = {
    'binding': ('organization_binding_audit',),
    'export': ('agent_research_export_audit', 'agent_research_export_limit'),
    'research': ('agent_research_content_purge', 'agent_research_source'),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fixed_offset(value):
    return (isinstance(value, str) and OFFSET.fullmatch(value) is not None
            and (value[1:3] != '14' or value[4:] == '00'))


def validate(offsets, policy=None, *, expected_domains=None):
    """Return explicit unresolved domains, rejecting a missing or broader opt-in.

    A null offset denotes an unresolved absolute instant, never UTC or a default
    timezone. Fixed-only callers keep their v1 behavior without a policy field.
    """
    require(isinstance(offsets, dict) and offsets and set(offsets) <= DOMAINS,
            'All source clock domains must be explicitly registered')
    if expected_domains is not None:
        require(set(offsets) == set(expected_domains), 'Source clock domain coverage differs from the copy plan')
    require(all(value is None or fixed_offset(value) for value in offsets.values()),
            'Source offsets must be reviewed fixed offsets or explicit unresolved nulls')
    unresolved = sorted(name for name, value in offsets.items() if value is None)
    require(set(unresolved) <= UNRESOLVED_DOMAINS,
            'This source domain has no accepted unresolved-clock copy/read protocol')
    if policy is None:
        require(not unresolved, 'Unresolved source clocks require an explicit preservation policy')
        return []
    require(isinstance(policy, dict)
            and {'version', 'kind', 'unresolvedDomains'} <= set(policy)
            <= {'version', 'kind', 'unresolvedDomains', 'emptyDomains'}
            and type(policy.get('version')) is int and policy['version'] == 1
            and policy.get('kind') == POLICY_KIND,
            'Unsupported explicit legacy clock preservation policy')
    names = policy['unresolvedDomains']
    require(isinstance(names, list) and names and all(isinstance(name, str) for name in names)
            and names == sorted(set(names)) and names == unresolved,
            'Clock policy must name all and only the unresolved source domains in canonical order')
    if 'emptyDomains' in policy:
        empty = policy['emptyDomains']
        require(isinstance(empty, list) and empty and all(isinstance(name, str) for name in empty)
                and empty == sorted(set(empty)) and set(empty) <= EMPTY_DOMAIN_TABLES.keys()
                and all(offsets.get(name) == '+00:00' for name in empty),
                'Empty clock domains need canonical names and an unused zero-offset placeholder')
    return unresolved


def require_empty_sources(offsets, policy, source_snapshot):
    """An empty table proves no conversion is needed, never a UTC offset."""
    validate(offsets, policy)
    empty = policy.get('emptyDomains', []) if policy else []
    if not empty:
        return
    require(isinstance(source_snapshot, dict), 'A complete frozen source snapshot is required for empty clock domains')
    snapshot_binding(source_snapshot.get('snapshotSha256'))
    tables = source_snapshot.get('tables', {})
    require(isinstance(tables, dict) and all(isinstance(tables.get(table), dict)
            and type(tables[table].get('rows')) is int and tables[table]['rows'] == 0
            for domain in empty for table in EMPTY_DOMAIN_TABLES[domain]),
            'Every declared empty clock domain must have exact zero rows in the frozen source snapshot')


def offset_literal_value(domain, offsets, policy=None):
    """Return a validated template value; caller owns the SQL literal quoting."""
    validate(offsets, policy)
    require(domain in offsets, 'A copy domain is absent from the reviewed clock policy')
    return UNRESOLVED if offsets[domain] is None else offsets[domain]


def snapshot_binding(value):
    require(isinstance(value, str) and SHA.fullmatch(value),
            'Legacy clock evidence requires the actual reviewed source snapshot digest')
    return value


def policy_digest(offsets, policy=None):
    validate(offsets, policy)
    document = {'sourceOffsets': offsets, 'legacyClockPolicy': policy}
    data = json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('utf8')
    return hashlib.sha256(data).hexdigest()


def evidence(offsets, policy=None):
    validate(offsets, policy)
    return json.loads(json.dumps({'sourceOffsets': offsets, 'legacyClockPolicy': policy,
                                 'sha256': policy_digest(offsets, policy)}, sort_keys=True))


def validate_evidence(value):
    require(isinstance(value, dict) and set(value) == {'sourceOffsets', 'legacyClockPolicy', 'sha256'},
            'Invalid source clock policy evidence')
    require(value['sha256'] == policy_digest(value['sourceOffsets'], value['legacyClockPolicy']),
            'Source clock policy evidence digest differs')
    return value


def workbench_fields(offsets, policy, source_snapshot_sha256):
    """Add v2 fields only to an explicitly unresolved Workbench CLI input."""
    unresolved = validate(offsets, policy)
    if 'workbench' not in unresolved:
        return {}
    # The Java CLI owns only Workbench; empty-source checks belong to the
    # whole-source controller and are independently proved before target DDL.
    workbench_policy = {key: policy[key] for key in ('version', 'kind', 'unresolvedDomains')}
    return {'legacyClockPolicy': workbench_policy,
            'sourceSnapshotSha256': snapshot_binding(source_snapshot_sha256)}
