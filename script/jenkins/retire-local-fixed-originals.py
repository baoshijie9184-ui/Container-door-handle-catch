"""Guarded retirement of fixed originals and explicit aliases, retaining directories.

Default plan captures current identities and byte hashes without deleting.
Only explicit Windows --apply and live authenticated custody authorize removal.
The C-drive history, transport packets and unknowns stay excluded.
PTH aliases require their independent explicit profile and fresh physical proof.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import ntpath
import os
from pathlib import Path
import re
import stat
import sys


SELF = Path(__file__).absolute()
ROOT = r'D:\AI\lunwen1\DoorHandleCatch'
RECIPES = {
    'legacy-project-originals-v1': {'manifestSha256': '56c1e60b441183dc9b06be99488b13ecd066a6ab8fbd0ad2f77f5632d6bea4d7',
        'members': 5599, 'selected': 5598, 'bytes': 1321785341, 'retained': 1},
    'additional-originals-v1': {'manifestSha256': 'b247f6f8bf0f5fc3e4d12b5bca008bb05786221d657262860de1ae6c479eec94',
        'members': 36, 'selected': 36, 'bytes': 465240718, 'retained': 0},
    'pth-aliases-v1': {'manifestSha256': 'b247f6f8bf0f5fc3e4d12b5bca008bb05786221d657262860de1ae6c479eec94',
        'members': 36, 'selected': 2, 'bytes': 465240718, 'retained': 0},
    'residual-project-originals-v1': {'manifestSha256': '471dedbba39f7220f760797ba1827040dd1cef7ac51af76daa8d7613117a6025',
        'members': 1968, 'selected': 1968, 'bytes': 8779830, 'retained': 0},
}
SHA = re.compile(r'[a-f0-9]{64}')
RETAINED_C_HISTORY = r'C:\Users\19771\.mem0\history.db'
PROTECTED = ('.git', 'work/jenkins', 'work/ecs-only-20261105/micro-followup/checkout')
MODEL_BYTES = 159274200
MODEL_SHA256 = 'eb10caf9fe5fa41e1ce0cfe2bcfaaa728ff44c4fa56f3c6994d6fadb66da434b'
MODEL_ORIGIN_MEMBER = 'work/cloud/pth-model/best_stg2.pth'
MODEL_ALIASES = ('best_stg2.pth', 'work/quality-platform-20261103/ecs-stage-04/model/best_stg2.pth')


def load(name):
    spec = importlib.util.spec_from_file_location('fixed_originals_' + name.replace('.', '_'), SELF.with_name(name))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def need(value, code):
    if not value: raise ValueError(code)


def sha(raw): return hashlib.sha256(raw).hexdigest()


def public_failure(error):
    value = {'status': 'REFUSED_OR_PARTIAL', 'errorType': type(error).__name__,
             'automaticResumeAllowed': False, 'scopeExpanded': False}
    if isinstance(error, ValueError) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}', str(error)):
        value['errorCode'] = str(error)
    return value


def relative_source(source):
    need(isinstance(source, str) and ntpath.isabs(source) and not source.startswith(('\\\\', '//')),
         'ABSOLUTE_PROJECT_SOURCE_REQUIRED')
    path = ntpath.normpath(source)
    need(ntpath.normcase(path).startswith(ntpath.normcase(ROOT) + '\\'), 'D_PROJECT_ORIGINAL_REQUIRED')
    name = ntpath.relpath(path, ROOT).replace('\\', '/')
    # Reject aliases before normalization can erase their evidence.
    original = source.replace('\\', '/').split('/')
    need(all(p not in ('.', '..') for p in original), 'SOURCE_TRAVERSAL_REFUSED')
    validate_relative(name)
    return name


def validate_relative(name):
    need(isinstance(name, str) and 0 < len(name) <= 2048 and not ntpath.isabs(name)
         and '\\' not in name and ':' not in name and '\x00' not in name
         and all(p not in ('', '.', '..') and not p.endswith((' ', '.'))
                     and not re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', p)
                 for p in name.split('/')), 'EXACT_UNALIASED_PROJECT_MEMBER_REQUIRED')
    lower = name.lower()
    need(not any(lower == p or lower.startswith(p + '/') for p in PROTECTED), 'PROTECTED_ORIGINAL_SCOPE')
    if lower == 'work/middlewares' or lower.startswith('work/middlewares/'):
        need(any(lower == p or lower.startswith(p + '/') for p in ('work/middlewares/chroma', 'work/middlewares/kafka-data')),
             'SHARED_MYSQL_REDIS_OR_UNKNOWN_MIDDLEWARE_REFUSED')
    return name


def select_manifest(profile, raw):
    need(profile in RECIPES and type(raw) is bytes and len(raw) <= 32 * 1024 ** 2, 'FIXED_PROFILE_MANIFEST_REQUIRED')
    recipe = RECIPES[profile]
    need(sha(raw) == recipe['manifestSha256'], 'FIXED_RAW_MANIFEST_SHA_REQUIRED')
    core = load('retire-local-cold-stores.py'); value = core.decode_control(raw)
    rows = value.get('files'); need(type(rows) is list and len(rows) == recipe['members'], 'COMPLETE_FIXED_MEMBERS_REQUIRED')
    if profile == 'pth-aliases-v1':
        origin = [r for r in rows if r.get('member') == MODEL_ORIGIN_MEMBER]
        need(len(origin) == 1 and origin[0].get('sourcePath') == ntpath.join(ROOT, *MODEL_ORIGIN_MEMBER.split('/'))
             and type(origin[0].get('bytes')) is int and origin[0]['bytes'] == MODEL_BYTES
             and origin[0].get('sha256') == MODEL_SHA256
             and sum(r['bytes'] for r in rows) == recipe['bytes'], 'EXACT_SEALED_MODEL_ORIGIN_REQUIRED')
        return [{'path': name, 'bytes': MODEL_BYTES, 'sha256': MODEL_SHA256} for name in MODEL_ALIASES], []
    selected, retained, seen = [], [], set()
    for row in rows:
        need(type(row) is dict and type(row.get('bytes')) is int and row['bytes'] >= 0
             and isinstance(row.get('sha256'), str) and SHA.fullmatch(row['sha256']), 'EXACT_SEALED_MEMBER_REQUIRED')
        source = row.get('sourcePath')
        if isinstance(source, str) and ntpath.normcase(source) == ntpath.normcase(RETAINED_C_HISTORY):
            need(profile == 'legacy-project-originals-v1' and row.get('path') == 'legacy_history/history.db',
                 'ONLY_FIXED_C_HISTORY_MAY_BE_RETAINED')
            retained.append({'sourcePath': RETAINED_C_HISTORY, 'reason': 'C_DRIVE_HISTORY_NEVER_ACCESSED', 'bytes': row['bytes']})
            continue
        name = relative_source(source)
        need(name.lower() not in seen, 'CASE_OR_SOURCE_ALIAS_REFUSED'); seen.add(name.lower())
        selected.append({'path': name, 'bytes': row['bytes'], 'sha256': row['sha256']})
    need(len(selected) == recipe['selected'] and len(retained) == recipe['retained']
         and sum(r['bytes'] for r in selected + retained) == recipe['bytes'], 'FIXED_SELECTED_OR_RETAINED_COUNTS_DRIFT')
    return sorted(selected, key=lambda r: r['path'].lower()), retained


class StrictResolver:
    """Exact selected files, their parents and one explicitly retained link."""
    def __init__(self, members, group=None):
        self.members = {row['path'] for row in members}
        need(len(self.members) == len(members), 'DUPLICATE_SELECTED_MEMBER')
        self.parents = {name.rsplit('/', 1)[0] for name in self.members if '/' in name}
        self.retained = set()
        if group is not None:
            validate_model_link_group('additional-originals-v1', members, group)
            self.retained.add(group['retained']['path'])

    def __call__(self, name):
        validate_relative(name)
        need(name in self.members or name in self.parents or name in self.retained, 'OUTSIDE_FIXED_SELECTED_FILES')
        return ntpath.join(ROOT, *name.split('/'))


def value_for(members):
    roots = sorted({r['path'].rsplit('/', 1)[0] if '/' in r['path'] else r['path'] for r in members})
    return {'members': members, 'directories': [], 'roots': [{'path': name} for name in roots]}


def original_info(path):
    for parent in (path, *path.parents):
        info = parent.lstat()
        need(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
             'ORIGINAL_ANCESTOR_LINK_OR_REPARSE_REFUSED')
    return path.lstat()


def fixed_link_source(profile, row):
    return (profile == 'additional-originals-v1' and row.get('path') == MODEL_ORIGIN_MEMBER
            and type(row.get('bytes')) is int and row['bytes'] == MODEL_BYTES and row.get('sha256') == MODEL_SHA256)


def validate_model_link_group(profile, members, group):
    linked = [row for row in members if row['fingerprint'][5] != 1]
    if not linked:
        need(group is None, 'UNEXPECTED_MODEL_HARDLINK_GROUP')
        return
    need(len(linked) == 1 and fixed_link_source(profile, linked[0])
         and type(linked[0]['fingerprint']) is list and len(linked[0]['fingerprint']) == 8
         and all(type(v) is int for v in linked[0]['fingerprint']) and linked[0]['fingerprint'][5] == 2,
         'ONLY_FIXED_ADDITIONAL_MODEL_TWO_LINK_GROUP_ALLOWED')
    need(type(group) is dict and set(group) == {'kind', 'source', 'retained'}
         and group['kind'] == 'fixed-model-two-name-hardlink-group' and group['source'] == MODEL_ORIGIN_MEMBER,
         'EXACT_CLOSED_MODEL_HARDLINK_GROUP_REQUIRED')
    retained = group['retained']
    need(type(retained) is dict and set(retained) == {'path', 'bytes', 'sha256', 'fingerprint'}
         and retained.get('path') == MODEL_ALIASES[0] and retained['path'] != group['source']
         and type(retained.get('bytes')) is int and retained['bytes'] == MODEL_BYTES
         and retained.get('sha256') == MODEL_SHA256
         and type(retained.get('fingerprint')) is list and len(retained['fingerprint']) == 8
         and all(type(v) is int for v in retained['fingerprint'])
         and retained['fingerprint'] == linked[0]['fingerprint'], 'MODEL_RETAINED_LINK_IDENTITY_OR_BYTES_DRIFT')


def model_link_paths(resolver):
    source = Path(resolver(MODEL_ORIGIN_MEMBER)); root = Path(ROOT)
    need(source == root.joinpath(*MODEL_ORIGIN_MEMBER.split('/')), 'FIXED_MODEL_SOURCE_RESOLVER_REQUIRED')
    return source, root / MODEL_ALIASES[0]


def observe_model_link_group(profile, members, cold, resolver):
    linked = [row for row in members if row['fingerprint'][5] != 1]
    if not linked: return None
    need(len(linked) == 1 and fixed_link_source(profile, linked[0]) and linked[0]['fingerprint'][5] == 2,
         'ONLY_FIXED_ADDITIONAL_MODEL_TWO_LINK_GROUP_ALLOWED')
    _, alias = model_link_paths(resolver)
    group = {'kind': 'fixed-model-two-name-hardlink-group', 'source': MODEL_ORIGIN_MEMBER,
             'retained': {'path': MODEL_ALIASES[0], 'bytes': MODEL_BYTES, 'sha256': MODEL_SHA256,
                          'fingerprint': cold.fingerprint(original_info(alias))}}
    validate_model_link_group(profile, members, group)
    return group


def verify_model_link_group(group, members, cold, resolver, backend):
    if group is None: return
    row = next(row for row in members if row['path'] == group['source'])
    # The original backend holds READ|DELETE with ShareMode=0 on the selected
    # name. Sharing applies to the file across links; no alias data handle is
    # opened. Two distinct fixed non-reparse names plus native link count 2
    # close the group, with unknown third links rejected by the same held FD.
    # MS-FSA 2.1.5.15.3 marks Open.Link, not every name of the underlying file:
    # https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/386d9ec5-e0f6-4853-b175-c05be01419e0
    # https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createhardlinkw
    backend.verify_file(row)
    source, alias = model_link_paths(resolver)
    need(cold.fingerprint(original_info(source)) == row['fingerprint']
         and cold.fingerprint(original_info(alias)) == group['retained']['fingerprint'],
         'CLOSED_MODEL_HARDLINK_GROUP_CHANGED_WHILE_HELD')


def verify_retained_model_link(group, cold, resolver):
    source, alias = model_link_paths(resolver)
    try:
        source.lstat()
    except FileNotFoundError:
        pass
    else:
        need(False, 'MODEL_SOURCE_NAME_STILL_PRESENT_AFTER_DISPOSITION')
    expected = list(group['retained']['fingerprint']); expected[5] = 1
    need(cold.fingerprint(original_info(alias)) == expected, 'MODEL_RETAINED_SINGLE_LINK_NOT_CONFIRMED')


def model_link_bindings(group):
    return {'closedModelHardlinkGroup': group} if group is not None else {}


def observed_members(selected, cold, resolver, profile=None):
    rows, identities = [], set()
    for row in selected:
        path = Path(resolver(row['path']))
        info = original_info(path); fingerprint = cold.fingerprint(info)
        if profile == 'pth-aliases-v1':
            need(info.st_nlink == 1, 'RETIRE_ADDITIONAL_MODEL_ORIGIN_BEFORE_ALIASES_OR_REVIEW_UNKNOWN_LINKS')
        allowed_links = info.st_nlink == 1 or (fixed_link_source(profile, row) and info.st_nlink == 2)
        need(stat.S_ISREG(info.st_mode) and allowed_links and info.st_ino != 0 and info.st_size == row['bytes']
             and tuple(fingerprint[:2]) not in identities, 'ORIGINAL_FILE_ID_OR_SIZE_NOT_ESTABLISHED')
        identities.add(tuple(fingerprint[:2])); rows.append({**row, 'fingerprint': fingerprint})
    return rows


def validate_observations(selected, observations, profile=None, group=None):
    need(type(observations) is list and len(selected) == len(observations), 'COMPLETE_IDENTITY_PLAN_REQUIRED')
    seen = set()
    for expected, actual in zip(selected, observations):
        need(type(actual) is dict and set(actual) == {'path', 'bytes', 'sha256', 'fingerprint'}
             and all(actual.get(k) == v for k, v in expected.items()), 'PLAN_MEMBER_OR_BYTE_BINDING_DRIFT')
        fp = actual['fingerprint']
        need(type(fp) is list and len(fp) == 8 and all(type(v) is int for v in fp)
             and fp[1] != 0 and fp[2] == actual['bytes']
             and (fp[5] == 1 or (fixed_link_source(profile, actual) and fp[5] == 2))
             and stat.S_ISREG(fp[6]) and not fp[7] & 0x400
             and tuple(fp[:2]) not in seen, 'PLAN_IDENTITY_OR_LINK_DRIFT')
        seen.add(tuple(fp[:2]))
    validate_model_link_group(profile, observations, group)


def bindings(core, proof, profile, current_file, custody_file):
    need(bool(current_file) == bool(custody_file), 'BOTH_CLOUD_CONTROL_RECEIPTS_REQUIRED')
    if not current_file: return None, None
    current, current_sha = core.control(current_file); public, public_sha = core.control(custody_file)
    need(current.get('kind') == 'doorhandle-ecs-ci' and current.get('schema') == 1
         and current.get('status') == 'PASS' and current.get('verificationExitCode') == 0 and current.get('finishedAt')
         and not current.get('evidenceOmissions') and current.get('identity') == core.IDENTITY,
         'ACTUAL_CURRENT_PASS_REQUIRED')
    now = {k: current[k] for k in ('release', 'commit', 'sourceSha256', 'identity')}
    now['verificationReceiptSha256'] = current_sha
    old = proof.custody_projection(profile, public, public_sha)
    need(old['identity'] == core.IDENTITY, 'SAME_FIXED_ECS_CUSTODY_REQUIRED')
    return now, old


def code_bindings(core, cold, proof):
    return {'executorSha256': sha(SELF.read_bytes()), 'retirementCoreSha256': sha(Path(core.__file__).read_bytes()),
            'heldSourcesSha256': sha(Path(cold.__file__).read_bytes()),
            'attestationHelperSha256': sha(Path(proof.__file__).read_bytes())}


def alias_bindings(profile, proof):
    if profile != 'pth-aliases-v1': return {}
    return {'aliasOrigin': {'member': MODEL_ORIGIN_MEMBER, 'sourceProfile': 'additional-originals-v1',
                            'bytes': MODEL_BYTES, 'sha256': MODEL_SHA256},
            'requiredServerModel': proof.model_expected_reference()}


def residual_bindings(profile):
    if profile != 'residual-project-originals-v1': return {}
    return {'residualScopeHelperSha256': sha(SELF.with_name('preserve-local-artifacts.py').read_bytes())}


def residual_source_guard(profile, members):
    if profile != 'residual-project-originals-v1': return
    # Reuse the same metadata-only scope policy as the fixed opaque producer.
    helper = load('preserve-local-artifacts.py')
    helper.residual_repository_guard([ROOT + '\\' + row['path'].replace('/', '\\') for row in members])


def make_plan(profile, manifest_file, current_file, custody_file, core, cold, proof, backend_factory):
    path = core.canonical_control(manifest_file); selected, retained = select_manifest(profile, path.read_bytes())
    residual_source_guard(profile, selected)
    resolver = StrictResolver(selected); members = observed_members(selected, cold, resolver, profile)
    group = observe_model_link_group(profile, members, cold, resolver)
    validate_observations(selected, members, profile, group)
    if group is not None: resolver = StrictResolver(members, group)
    backend = backend_factory(resolver); value = value_for(members)
    observed = members + ([group['retained']] if group is not None else [])
    tracked = backend.tracked_sources()
    need(not any(r['path'].lower() in tracked for r in observed), 'TRACKED_SOURCE_REFUSED')
    backend.active_references(value_for(observed))
    with backend.hold(value):
        verify_model_link_group(group, members, cold, resolver, backend)
        for row in members: backend.hash_file(row)
        for row in members: backend.verify_file(row)
        verify_model_link_group(group, members, cold, resolver, backend)
    current, custody = bindings(core, proof, profile, current_file, custody_file)
    return {'schemaVersion': 1, 'kind': 'doorhandle-fixed-originals-local-retirement', 'status': 'PLAN_ONLY',
        'profile': profile, 'projectRoot': ROOT, 'manifestFile': str(path), 'manifestSha256': RECIPES[profile]['manifestSha256'],
        'members': members, 'retained': retained, 'directoriesRemoved': 0,
        'currentReceiptFile': str(core.canonical_control(current_file)) if current_file else None,
        'custodyReceiptFile': str(core.canonical_control(custody_file)) if custody_file else None,
        'current': current, 'custody': custody, 'originalFilesDeleted': 0, **code_bindings(core, cold, proof),
        **alias_bindings(profile, proof), **residual_bindings(profile), **model_link_bindings(group)}


def load_plan(args, core, cold, proof):
    plan, checksum = core.control(args.plan); need(checksum == args.plan_sha256, 'EXACT_REVIEWED_PLAN_SHA_REQUIRED')
    path = core.canonical_control(args.manifest); selected, retained = select_manifest(args.profile, path.read_bytes())
    group = plan.get('closedModelHardlinkGroup')
    validate_observations(selected, plan.get('members'), args.profile, group)
    current, custody = bindings(core, proof, args.profile, args.current_receipt, args.custody_receipt)
    expected = {'schemaVersion': 1, 'kind': 'doorhandle-fixed-originals-local-retirement', 'status': 'PLAN_ONLY',
        'profile': args.profile, 'projectRoot': ROOT, 'manifestFile': str(path), 'manifestSha256': RECIPES[args.profile]['manifestSha256'],
        'members': plan['members'], 'retained': retained, 'directoriesRemoved': 0,
        'currentReceiptFile': str(core.canonical_control(args.current_receipt)),
        'custodyReceiptFile': str(core.canonical_control(args.custody_receipt)),
        'current': current, 'custody': custody, 'originalFilesDeleted': 0, **code_bindings(core, cold, proof),
        **alias_bindings(args.profile, proof), **residual_bindings(args.profile), **model_link_bindings(group)}
    need(plan == expected and current is not None and custody is not None, 'PLAN_SOURCE_OR_CLOUD_BINDING_DRIFT')
    return plan


def apply_plan(plan, core, proof, backend, attestor, audit):
    need(plan.get('current') is not None and plan.get('custody') is not None, 'CLOUD_RECEIPTS_REQUIRED')
    group = plan.get('closedModelHardlinkGroup')
    validate_model_link_group(plan['profile'], plan['members'], group)
    if plan['profile'] == 'residual-project-originals-v1':
        need(all(plan.get(key) == value for key, value in residual_bindings(plan['profile']).items()),
             'FIXED_RESIDUAL_SOURCE_GUARD_REQUIRED')
        residual_source_guard(plan['profile'], plan['members'])
    if plan['profile'] == 'pth-aliases-v1':
        aliases = [{'path': name, 'bytes': MODEL_BYTES, 'sha256': MODEL_SHA256} for name in MODEL_ALIASES]
        validate_observations(aliases, plan.get('members'))
        need(plan.get('manifestSha256') == RECIPES['pth-aliases-v1']['manifestSha256'] and plan.get('retained') == []
             and all(plan.get(key) == value for key, value in alias_bindings('pth-aliases-v1', proof).items()),
             'FIXED_ALIAS_SOURCE_AND_MODEL_REFERENCE_REQUIRED')
    members = plan['members']; value = value_for(members); resolver = StrictResolver(members, group)
    observed = members + ([group['retained']] if group is not None else [])
    tracked = backend.tracked_sources()
    need(not any(row['path'].lower() in tracked for row in observed), 'TRACKED_SOURCE_REFUSED')
    backend.active_references(value_for(observed)); deleted = attempts = 0
    audit.record('BEGIN', profile=plan['profile'], files=len(members), manifestSha256=plan['manifestSha256'])
    try:
        with backend.hold(value):
            verify_model_link_group(group, members, backend.cold if group is not None else None, resolver, backend)
            for row in members: backend.hash_file(row)
            for row in members: backend.verify_file(row)
            verify_model_link_group(group, members, backend.cold if group is not None else None, resolver, backend)
            fresh = core.FreshProof(proof, plan, attestor, audit); fresh.ensure()
            audit.record('PREFLIGHT_COMPLETE', files=len(members), proofRenewal=fresh.sequence)
            for row in members:
                selected_group = group if group is not None and row['path'] == group['source'] else None
                fresh.ensure(); backend.verify_file(row)
                verify_model_link_group(selected_group, members, backend.cold if group is not None else None, resolver, backend)
                audit.record('FILE_DELETE_INTENT', **row)
                fresh.ensure(); backend.verify_file(row)
                verify_model_link_group(selected_group, members, backend.cold if group is not None else None, resolver, backend)
                if selected_group is not None:
                    # Ancestor metadata reads must not spend the proof's TTL.
                    fresh.ensure(); backend.verify_file(row)
                attempts += 1
                backend.delete_file(row); deleted += 1
                audit.record('FILE_DELETED', path=row['path'])
                if selected_group is not None:
                    verify_retained_model_link(selected_group, backend.cold, resolver)
                    audit.record('MODEL_ALIAS_RETAINED', path=group['retained']['path'], remainingLinks=1)
        result = {'status': 'SELECTED_FIXED_ORIGINALS_RETIRED', 'profile': plan['profile'], 'filesDeleted': deleted,
                  'directoriesRemoved': 0, 'retained': plan['retained'], 'allDirectoriesRetained': True,
                  'manifestSha256': plan['manifestSha256'], 'unknownCandidatesTouched': False,
                  **({'retainedModelLink': {'path': group['retained']['path'], 'remainingLinks': 1}} if group is not None else {})}
        audit.record('COMPLETED', **result); return result
    except BaseException:
        audit.record('PARTIAL_OR_REFUSED', confirmedFilesDeleted=deleted, fileDispositionAttempts=attempts,
                     unconfirmedFileDispositions=attempts - deleted, automaticResumeAllowed=False)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('profile', 'manifest', 'output'): parser.add_argument('--' + flag, required=True, choices=tuple(RECIPES) if flag == 'profile' else None)
    for flag in ('current-receipt', 'custody-receipt', 'plan', 'plan-sha256', 'ssh-host'): parser.add_argument('--' + flag)
    parser.add_argument('--apply', action='store_true'); parser.add_argument('--ssh-user', default='ecs-user')
    parser.add_argument('--ssh-port', type=int, default=22); parser.add_argument('--remote-root', default='/home/ecs-user/doorhandle-ci')
    parser.add_argument('--ssh-key', default=ROOT + r'\work\cloud\doorhandle-demo-20261014.pem')
    parser.add_argument('--known-hosts', default=ROOT + r'\work\jenkins\known_hosts')
    args = parser.parse_args(argv); audit = None
    try:
        need(os.name == 'nt', 'LOCAL_ORIGINALS_PLAN_AND_APPLY_REQUIRE_WINDOWS')
        core = load('retire-local-cold-stores.py'); cold = load('preserve-cold-stores.py'); proof = load('attest-fixed-originals.py')
        if not args.apply:
            need(not args.plan and not args.plan_sha256, 'APPLY_ARGUMENTS_REQUIRE_EXPLICIT_APPLY')
            plan = make_plan(args.profile, args.manifest, args.current_receipt, args.custody_receipt, core, cold, proof,
                             lambda resolver: core.WindowsBackend(cold, source_resolver=resolver))
            audit = core.Audit(args.output, cold); cold.utility().write_json(audit.directory / 'plan.json', plan)
            audit.record('PLAN_ONLY', originalFilesDeleted=0, files=len(plan['members']), retained=plan['retained'])
            print(json.dumps({'status': 'PLAN_ONLY', 'planSha256': sha((audit.directory / 'plan.json').read_bytes()),
                              'files': len(plan['members']), 'originalFilesDeleted': 0})); return 0
        need(args.ssh_host and args.plan and args.plan_sha256 and args.current_receipt and args.custody_receipt,
             'EXPLICIT_CURRENT_HOST_PLAN_AND_CLOUD_CONTROLS_REQUIRED')
        plan = load_plan(args, core, cold, proof)
        resolver = StrictResolver(plan['members'], plan.get('closedModelHardlinkGroup'))
        audit = core.Audit(args.output, cold)
        result = apply_plan(plan, core, proof, core.WindowsBackend(cold, source_resolver=resolver),
                            core.LiveAttestor(proof, args, helper_name='attest-fixed-originals.py'), audit)
        cold.utility().write_json(audit.directory / 'result.json', result); print(json.dumps(result)); return 0
    except BaseException as error:
        print(json.dumps(public_failure(error)), file=sys.stderr); return 1
    finally:
        if audit is not None: audit.close()


if __name__ == '__main__': raise SystemExit(main())
