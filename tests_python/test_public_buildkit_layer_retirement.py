"""Synthetic public BuildKit byte copies; run only by Jenkins on ECS."""
from contextlib import contextmanager
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tarfile
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest


MODULE = Path(__file__).resolve().parents[1] / 'script/jenkins/retire-failed-native-jar-duplicates.py'
SPEC = importlib.util.spec_from_file_location('public_buildkit_layer_retirement_tests', MODULE)
retirer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = retirer
SPEC.loader.exec_module(retirer)

KEEPER = 'ci-117-8c898996cc28'
TARGET = 'ci-118-6481f7fa6021'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def private_file(root, relative, raw):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    for parent in (path.parent, *path.parent.parents):
        if parent == root or parent.is_relative_to(root): parent.chmod(0o700)
    path.write_bytes(raw); path.chmod(0o600)
    return path


@pytest.fixture
def copies(tmp_path, monkeypatch):
    root = tmp_path / 'ci'; root.mkdir(mode=0o700)
    payloads = [b'public synthetic layer ' + bytes([index]) for index in range(4)]
    layers = {sha(raw): len(raw) for raw in payloads}
    monkeypatch.setattr(retirer, 'PUBLIC_LAYERS', layers)
    for tag in (KEEPER, TARGET):
        for raw in payloads:
            private_file(root, 'inbox/' + tag + '/candidate-build-tools/official-oci/blobs/sha256/' + sha(raw), raw)
    raw = payloads[0]
    target, keeper = retirer.duplicate_paths(root, TARGET, kind=retirer.PUBLIC_LAYER_KIND, blob_sha=sha(raw))
    return SimpleNamespace(root=root, payload=raw, payloads=payloads, target=target, keeper=keeper,
                           checksum=sha(raw), size=len(raw))


def described(copies):
    return retirer.describe_duplicate(copies.root, TARGET, copies.checksum, copies.size, kind=retirer.PUBLIC_LAYER_KIND)


def test_public_paths_only_select_exact_blob_and_preserved_117(copies):
    descriptor = described(copies)
    assert descriptor['kind'] == retirer.PUBLIC_LAYER_KIND
    assert descriptor['path'] == copies.target.relative_to(copies.root).as_posix()
    assert descriptor['keeper']['path'] == copies.keeper.relative_to(copies.root).as_posix()
    assert descriptor['sha256'] == descriptor['keeper']['sha256'] == copies.checksum
    assert descriptor['metadata'][:2] != descriptor['keeper']['metadata'][:2]
    assert descriptor['metadata'][5] == descriptor['keeper']['metadata'][5] == 1


@pytest.mark.parametrize('tag,kind,checksum', [
    (KEEPER, retirer.PUBLIC_LAYER_KIND, None),
    ('ci-156-' + 'a' * 12, retirer.PUBLIC_LAYER_KIND, None),
    (TARGET, 'UNKNOWN_PUBLIC_KIND', None),
    (TARGET, retirer.PUBLIC_LAYER_KIND, 'f' * 64),
])
def test_keeper_current_unknown_tag_or_unknown_blob_has_no_public_delete_path(copies, tag, kind, checksum):
    with pytest.raises(retirer.RetirementError):
        retirer.duplicate_paths(copies.root, tag, kind=kind, blob_sha=checksum or copies.checksum)


def test_original_default_jar_paths_are_unchanged(copies):
    target, keeper = retirer.duplicate_paths(copies.root, TARGET)
    assert target == copies.root / 'verification' / TARGET / 'checkout/work/compact-fixtures/candidate-app.jar'
    assert keeper == copies.root / 'inbox' / TARGET / 'application.jar'


@pytest.mark.parametrize('mutation', ['length', 'same_length_bytes', 'keeper_bytes', 'target_symlink', 'keeper_hardlink'])
def test_only_independent_full_byte_equal_public_copies_are_admitted(copies, mutation):
    if mutation == 'length': copies.target.write_bytes(copies.payload + b'x')
    elif mutation == 'same_length_bytes': copies.target.write_bytes(b'x' * copies.size)
    elif mutation == 'keeper_bytes': copies.keeper.write_bytes(b'x' * copies.size)
    elif mutation == 'target_symlink':
        copies.target.unlink(); copies.target.symlink_to(copies.keeper)
    else: os.link(copies.keeper, copies.keeper.with_name('another-link'))
    with pytest.raises((retirer.RetirementError, OSError)):
        described(copies)


@pytest.mark.parametrize('mutation', ['path', 'keeper', 'kind', 'bytes'])
def test_public_descriptor_cannot_select_any_other_file(copies, mutation):
    descriptor = described(copies)
    if mutation == 'path': descriptor['path'] = descriptor['keeper']['path']
    elif mutation == 'keeper': descriptor['keeper']['path'] = descriptor['path']
    elif mutation == 'kind': descriptor['kind'] = retirer.JAR_COPY_KIND
    else: descriptor['bytes'] += 1
    with pytest.raises((retirer.RetirementError, OSError)):
        retirer.remove_duplicate(copies.root, descriptor)
    assert copies.target.read_bytes() == copies.keeper.read_bytes() == copies.payload


def test_public_remove_retains_keeper_tar_index_config_and_directories(copies):
    directory = copies.target.parent
    index = private_file(copies.root, 'inbox/' + TARGET + '/candidate-build-tools/official-oci/index.json', b'original index')
    config = private_file(copies.root, str(directory.relative_to(copies.root) / ('a' * 64)), b'distinct config')
    source_tar = private_file(copies.root, 'build-inputs/buildkit-v0.34.2/retained.tar', b'original upstream tar')
    keeper_before = retirer.metadata(copies.keeper.stat())
    result = retirer.remove_duplicate(copies.root, described(copies))
    assert not copies.target.exists() and directory.is_dir()
    assert copies.keeper.read_bytes() == copies.payload
    assert retirer.metadata(copies.keeper.stat()) == keeper_before
    assert index.read_bytes() == b'original index' and config.read_bytes() == b'distinct config'
    assert source_tar.read_bytes() == b'original upstream tar'
    assert result['keeperVerifiedAfter'] and result['capturedInodeVerified']
    assert not list((copies.root / result['quarantinePath']).parent.iterdir())


def test_changed_public_keeper_rejects_before_capture(copies):
    descriptor = described(copies); copies.keeper.write_bytes(b'x' * copies.size)
    with pytest.raises(retirer.RetirementError): retirer.remove_duplicate(copies.root, descriptor)
    assert copies.target.read_bytes() == copies.payload


def test_public_capture_of_replaced_keeper_is_retained_never_unlinked(copies, monkeypatch):
    descriptor = described(copies); reservation = retirer.reserve_quarantine(copies.root)
    keeper_inode = copies.keeper.stat().st_ino; capture = retirer._capture_no_replace
    def swap_before_capture(*args, **kwargs):
        os.replace(copies.keeper, copies.target)
        return capture(*args, **kwargs)
    monkeypatch.setattr(retirer, '_capture_no_replace', swap_before_capture)
    with pytest.raises((retirer.RetirementError, OSError)):
        retirer.remove_duplicate(copies.root, descriptor, quarantine=reservation)
    captured = copies.root / reservation['path']
    assert captured.stat().st_ino == keeper_inode and captured.read_bytes() == copies.payload
    assert not copies.keeper.exists()


def upstream(copies, monkeypatch, *, mutation=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:') as archive:
        for index, raw in enumerate(copies.payloads):
            name = 'blobs/sha256/' + sha(raw)
            info = tarfile.TarInfo(name)
            if mutation == 'unsafe' and index == 0: info.name = '../' + name
            if mutation == 'duplicate' and index == 1: info.name = 'blobs/sha256/' + sha(copies.payloads[0])
            if mutation == 'symlink' and index == 0:
                info.type = tarfile.SYMTYPE; info.linkname = 'somewhere'; archive.addfile(info); continue
            if mutation == 'missing' and index == 0: continue
            data = b'x' * len(raw) if mutation == 'wrong_bytes' and index == 0 else raw
            info.size = len(data); archive.addfile(info, io.BytesIO(data))
    raw = output.getvalue(); checksum = sha(raw)
    monkeypatch.setattr(retirer, 'PUBLIC_ARCHIVE_SHA', checksum)
    monkeypatch.setattr(retirer, 'PUBLIC_ARCHIVE_BYTES', len(raw))
    return private_file(copies.root, 'build-inputs/buildkit-v0.34.2/' + checksum + '.tar', raw)


def test_upstream_tar_requires_real_full_file_and_four_member_hashes(copies, monkeypatch):
    path = upstream(copies, monkeypatch)
    proof = retirer.public_layer_archive(copies.root)
    assert proof['sha256'] == sha(path.read_bytes()) and proof['bytes'] == path.stat().st_size
    assert {row['sha256']: row['bytes'] for row in proof['layers']} == retirer.PUBLIC_LAYERS
    assert proof['metadata'] == retirer.metadata(path.stat())


@pytest.mark.parametrize('mutation', ['unsafe', 'duplicate', 'symlink', 'missing', 'wrong_bytes', 'full_sha'])
def test_invalid_public_upstream_does_not_authorize_layers(copies, monkeypatch, mutation):
    path = upstream(copies, monkeypatch, mutation=None if mutation == 'full_sha' else mutation)
    if mutation == 'full_sha':
        raw = path.read_bytes(); path.write_bytes(b'x' + raw[1:])
    with pytest.raises((retirer.RetirementError, tarfile.TarError, OSError)):
        retirer.public_layer_archive(copies.root)
    assert copies.target.read_bytes() == copies.keeper.read_bytes() == copies.payload


def test_upstream_file_must_stay_identical_while_action_runs(copies, monkeypatch):
    path = upstream(copies, monkeypatch)
    with pytest.raises(retirer.RetirementError):
        with retirer.held_public_layer_archive(copies.root):
            raw = path.read_bytes(); path.write_bytes(raw[:-1] + b'x')


@pytest.fixture
def planning(copies, monkeypatch):
    current = {'release': 'ci-999-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}
    identity = {'executionLocation': 'ECS', 'instanceId': 'synthetic', 'machineId': 'c' * 32}
    rows = [{'release': tag, 'commit': retirer.APPROVED_OLD[tag], 'sourceSha256': 'd' * 64, 'controls': {}}
            for tag in (KEEPER, TARGET)]
    request = {'schemaVersion': 1, 'kind': retirer.KIND + '-request', 'current': current, 'identity': identity,
               'protectedReleases': [current['release']], 'candidates': rows}
    raw = retirer.canonical(request)
    private_file(copies.root, 'inbox/' + current['release'] + '/retained-control', b'synthetic')
    # Keep the real old-attempt directory locks: even a synthetic admission
    # needs each precise verification/<tag> directory, separately from inbox.
    for tag in (KEEPER, TARGET):
        private_file(copies.root, 'verification/' + tag + '/checkout/retained-source.py', b'synthetic fixed source')
    proof = {'path': 'global-original-public.tar', 'sha256': 'e' * 64, 'metadata': [1], 'bytes': 1, 'layers': []}
    @contextmanager
    def archive(_root): yield copy.deepcopy(proof)
    calls = []
    def admit(_root, actual_request, row, quiescence):
        assert actual_request == request
        quiescence(copies.root / 'verification' / row['release'] / 'checkout', row['release'], '0123456789')
        return {'context': {key: row[key] for key in ('release', 'commit', 'sourceSha256')},
                'ownerToken': '0123456789', 'controls': {}, 'sourceArchive': {}, 'tools': {}, 'jenkinsResult': 'FAILURE'}
    monkeypatch.setattr(retirer, 'held_public_layer_archive', archive)
    monkeypatch.setattr(retirer, 'admit_public_layer_attempt', admit)
    return SimpleNamespace(copies=copies, current=current, identity=identity, rows=rows, request=request, raw=raw,
                           checksum=sha(raw), proof=proof, calls=calls,
                           quiescence=lambda _checkout, tag, _token: calls.append(tag))


def planned(planning):
    return retirer.plan_public_layers(planning.copies.root, planning.raw, request_sha256=planning.checksum,
        expected_current=planning.current, identity=planning.identity, quiescence=planning.quiescence)


def applied(planning, plan):
    return retirer.apply_public_layers(planning.copies.root, planning.raw, plan, request_sha256=planning.checksum,
        plan_sha256=sha(retirer.canonical(plan)), expected_current=planning.current,
        identity=planning.identity, quiescence=planning.quiescence)


def test_public_plan_has_four_targets_and_no_keeper_deletion(planning):
    plan = planned(planning)
    assert not plan['skipped'], plan['skipped']
    assert len(plan['candidates']) == 1 and len(plan['candidates'][0]['targets']) == 4
    assert plan['candidateBytes'] == sum(len(raw) for raw in planning.copies.payloads)
    assert plan['keeper']['context']['release'] == KEEPER
    assert {row['release'] for row in plan['candidates'][0]['targets']} == {TARGET}
    assert not plan['deletionPerformed'] and plan['upstreamTarAndKeeper117Preserved']
    assert set(planning.calls) == {KEEPER, TARGET}


def test_public_apply_uses_same_quarantine_core_and_retains_all_real_keepers(planning):
    plan = planned(planning); receipt = applied(planning, plan)
    assert receipt['status'] == 'REMOVED' and len(receipt['deleted']) == 4
    assert not receipt['retainedQuarantinePaths'] and receipt['upstreamTarAndKeeper117Preserved']
    assert not receipt['testsRunByRetirement'] and receipt['directoriesImagesAndBusinessDataPreserved']
    for raw in planning.copies.payloads:
        target, keeper = retirer.duplicate_paths(planning.copies.root, TARGET, kind=retirer.PUBLIC_LAYER_KIND, blob_sha=sha(raw))
        assert not target.exists() and keeper.read_bytes() == raw
    journal = planning.copies.root / 'inbox' / planning.current['release'] / 'native-public-layer-duplicate-journal.jsonl'
    assert sha(journal.read_bytes()) == receipt['journalSha256']
    phases = [json.loads(row)['phase'] for row in journal.read_bytes().splitlines()]
    assert phases.count('DELETE_STARTED') == phases.count('DELETE_FINISHED') == 4


def test_missing_one_keeper_or_target_skips_whole_attempt_without_deletion(planning):
    planning.copies.keeper.unlink()
    plan = planned(planning)
    assert not plan['candidates'] and plan['skipped'] and plan['archive'] is None
    receipt = applied(planning, plan)
    assert receipt['status'] == 'NO_ACTION' and not receipt['deleted']
    assert planning.copies.target.read_bytes() == planning.copies.payload


def test_changed_archive_after_plan_produces_unknown_receipt_without_mutation(planning):
    plan = planned(planning); planning.proof['bytes'] += 1
    receipt = applied(planning, plan)
    assert receipt['status'] == 'FAILED_OR_UNKNOWN' and not receipt['deleted'] and not receipt['mutationAttempted']
    assert planning.copies.target.read_bytes() == planning.copies.keeper.read_bytes() == planning.copies.payload


def test_changed_public_target_after_plan_is_not_deleted(planning):
    plan = planned(planning); planning.copies.target.write_bytes(b'x' * planning.copies.size)
    receipt = applied(planning, plan)
    assert receipt['status'] == 'FAILED_OR_UNKNOWN' and not receipt['deleted']
    assert planning.copies.target.read_bytes() == b'x' * planning.copies.size
    assert planning.copies.keeper.read_bytes() == planning.copies.payload


@pytest.mark.parametrize('source', ['same', 'ancestor', 'descendant'])
def test_public_quiescence_rejects_any_tag_bind_to_old_inbox_tools(copies, source):
    tools = copies.root / 'inbox' / TARGET / 'candidate-build-tools'
    path = tools if source == 'same' else tools.parent if source == 'ancestor' else tools / 'official-oci'
    cleanup = SimpleNamespace(docker_snapshot=lambda: [('x', False, False, 0, 'other-tag', 'other-token',
                                                        [{'Type': 'bind', 'Source': str(path)}])])
    original_calls = []
    check = retirer.public_layer_quiescence(copies.root, cleanup, lambda *args: original_calls.append(args))
    with pytest.raises(retirer.RetirementError): check(copies.root / 'verification' / TARGET / 'checkout', TARGET, 'token')
    assert len(original_calls) == 1


@pytest.fixture
def recent_public_case(tmp_path, monkeypatch):
    """Six authenticated sources, no JARs, real capture and public deletion APIs."""
    root = tmp_path / 'recent-public'; root.mkdir(mode=0o700)
    current = {'release': 'ci-999-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}
    identity = {'executionLocation': 'ECS', 'instanceId': 'i-fixture123', 'machineId': 'c' * 32}
    private_file(root, 'inbox/' + current['release'] + '/original-current-control', b'retained current source')
    payloads = [b'immutable synthetic public layer ' + bytes([i]) for i in range(4)]
    layers = {sha(body): len(body) for body in payloads}
    def tar_bytes(mtime):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:') as archive:
            for body in payloads:
                member = tarfile.TarInfo('blobs/sha256/' + sha(body)); member.size = len(body); member.mtime = mtime
                archive.addfile(member, io.BytesIO(body))
        return output.getvalue()
    seed_raw = tar_bytes(0)
    monkeypatch.setattr(retirer, 'PUBLIC_LAYERS', layers)
    monkeypatch.setattr(retirer, 'PUBLIC_ARCHIVE_SHA', sha(seed_raw)); monkeypatch.setattr(retirer, 'PUBLIC_ARCHIVE_BYTES', len(seed_raw))
    seed = private_file(root, 'build-inputs/buildkit-v0.34.2/' + sha(seed_raw) + '.tar', seed_raw)
    publication = {'Jenkinsfile.ecs-monolith': b'reviewed synthetic unpublished workflow',
                   'script/jenkins/pipeline.ps1': b'reviewed synthetic source-only pipeline'}
    helpers = {'compact-build-resources.py': b'reviewed prepare_tools/archive_layout/monitored_tar_file producer',
               'compact-image-inputs.py': b'reviewed fixed public OCI inputs'}
    recipe = (b"def prepare(self):\n jar = canonical(self.inbox / 'application.jar')\n"
              b" uploaded = self.work / 'candidate-app.jar'\n shutil.copyfile(jar, uploaded)\n"
              b"def start_mysql(self, image):\n return image\n")
    monkeypatch.setattr(retirer, 'FAILED_NATIVE_PUBLICATION_RECIPES', frozenset({tuple(sha(v) for v in publication.values())}))
    registry, rows, layer_paths, tar_paths, original_paths = {}, [], [], [], {}
    commits = {KEEPER: retirer.APPROVED_OLD[KEEPER], **{tag: row['commit'] for tag, row in retirer.PUBLIC_CACHE_TARGETS.items()}}
    for number, (tag, commit) in enumerate(commits.items()):
        work = root / 'verification' / tag / 'checkout/work/compact-fixtures'
        private_file(root, work.relative_to(root).as_posix() + '/source.sql', b'retained original SQL')
        original_paths[work / 'source.sql'] = b'retained original SQL'
        source = io.BytesIO()
        with tarfile.open(fileobj=source, mode='w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': commit}) as archive:
            for name, body in {'script/jenkins/prepare-compact-fixtures.py': recipe, **publication,
                               **{'script/docker/' + name: body for name, body in helpers.items()}}.items():
                member = tarfile.TarInfo(name); member.size = len(body); archive.addfile(member, io.BytesIO(body))
        source_raw = source.getvalue(); context = {'release': tag, 'commit': commit, 'sourceSha256': sha(source_raw)}
        path = private_file(root, 'inbox/' + tag + '/source.tar.gz', source_raw); original_paths[path] = source_raw
        terminal = ET.Element('flow-build'); params = ET.SubElement(ET.SubElement(ET.SubElement(terminal, 'actions'),
            'hudson.model.ParametersAction'), 'parameters')
        for name, value in {'ACTION': 'verify-runtime', 'DOORHANDLE_CI_SCOPE': 'mysql',
                            'TRUSTED_COMMIT': commit, 'PRODUCTION_RELEASE_ENABLED': 'false'}.items():
            member = ET.SubElement(params, 'parameter'); ET.SubElement(member, 'name').text = name; ET.SubElement(member, 'value').text = value
        ET.SubElement(terminal, 'result').text = 'ABORTED' if 'ci-223-' in tag else 'FAILURE'
        ET.SubElement(terminal, 'completed').text = 'true'; ET.SubElement(ET.SubElement(terminal, 'execution'), 'done').text = 'true'
        owner = {'schemaVersion': 1, 'kind': 'doorhandle-compact-fixture-owner', **context, 'identity': identity,
            'phase': 'OWNED_SERVER_STOPPED', 'token': format(number + 1, '010x'), 'work': str(work),
            'sourceContainerId': 'd' * 64, 'containerId': format(number + 1, '064x')}
        cleanup = {'schemaVersion': 1, 'kind': 'doorhandle-compact-fixture-cleanup', **context, 'identity': identity,
            'status': 'STOPPED', 'errors': [], 'containerId': owner['containerId'], 'sourceContainerUntouched': owner['sourceContainerId'],
            'sourceDumpAndEvidenceRetained': True}
        documents = {'buildXml': ET.tostring(terminal), 'release': retirer.canonical({**context, 'applicationJarSha256': '1' * 64}),
            'artifactPlan': retirer.canonical({'schema': 1, 'kind': 'doorhandle-compact-fixture-artifacts', **context,
                'applicationJarSha256': '1' * 64, 'applicationJarBytes': 123}),
            'fixtureOwner': retirer.canonical(owner), 'fixtureCleanup': retirer.canonical(cleanup)}
        paths = retirer.expected_control_paths(current['release'], tag); controls = {}
        for role, body in documents.items():
            path = private_file(root, paths[role], body); original_paths[path] = body
            controls[role] = {'path': paths[role], 'bytes': len(body), 'sha256': sha(body)}
        rows.append({**context, 'controls': controls})
        directory = root / 'inbox' / tag / 'candidate-build-tools'
        engine = {'engineImageId': 'sha256:' + '2' * 64}
        measurement_raw = retirer.canonical({'imageId': 'sha256:' + '3' * 64,
            'archiveSha256': '4' * 64, 'archiveBytes': 10240})  # Deliberately NOT official-image.tar.
        summary_raw = retirer.canonical({**context, 'identity': identity, 'status': 'PASS', 'engineIdentity': engine})
        tools_raw = retirer.canonical({**context, 'identity': identity, 'kind': 'doorhandle-candidate-build-tools', 'status': 'PREPARED',
            'helperSha256': sha(helpers['compact-build-resources.py']), 'imageInputsHelperSha256': sha(helpers['compact-image-inputs.py']),
            'imageMeasurementSha256': sha(measurement_raw), 'resourceEvidence': {'file': str(directory / 'resource-summary.json'), 'sha256': sha(summary_raw)},
            'imageId': 'sha256:' + '3' * 64, 'engineIdentity': engine})
        prepared = {'tools': ('tools.json', tools_raw), 'summary': ('resource-summary.json', summary_raw),
                    'measurement': ('official-layer-measurements.json', measurement_raw)}
        for name, body in prepared.values():
            path = private_file(root, (directory / name).relative_to(root).as_posix(), body); original_paths[path] = body
        for body in payloads:
            path = private_file(root, (directory / 'official-oci/blobs/sha256' / sha(body)).relative_to(root).as_posix(), body)
            if tag == KEEPER: original_paths[path] = body
            else: layer_paths.append(path)
        if tag == KEEPER:
            monkeypatch.setitem(retirer.APPROVED_BUILDER_TOOLS, tag, sha(tools_raw))
        else:
            generated = tar_bytes(number * 100)
            path = private_file(root, (directory / 'official-image.tar').relative_to(root).as_posix(), generated); tar_paths.append(path)
            registry[tag] = {**context, 'controls': {role: (len(body), sha(body)) for role, (_, body) in prepared.items()},
                'builderHelperSha256': {name: sha(body) for name, body in helpers.items()}, 'tarSha256': sha(generated), 'tarBytes': len(generated)}
    monkeypatch.setattr(retirer, 'PUBLIC_CACHE_TARGETS', registry)
    request = {'schemaVersion': 1, 'kind': retirer.KIND + '-request', 'current': current, 'identity': identity,
               'protectedReleases': [current['release']], 'candidates': rows}
    local_spec = copy.deepcopy(request)
    for row in local_spec['candidates']: row['controls'] = {k: v for k, v in row['controls'].items() if k in retirer.UPLOADED_NAMES}
    local_raw = retirer.canonical(local_spec)
    private_file(root, 'inbox/' + current['release'] + '/native-jar-duplicate-local-spec.json', local_raw)
    spec = importlib.util.spec_from_file_location('recent_public_actual_cleanup', MODULE.parent / 'cleanup-ecs-builds.py')
    cleanup = importlib.util.module_from_spec(spec); spec.loader.exec_module(cleanup)
    containers = []
    def docker(command, **kwargs):
        assert command[0] == '/usr/bin/docker'
        if command[1:] == ['ps', '-aq', '--no-trunc']: output = '\n'.join(row[0] for row in containers)
        else:
            assert command[1:3] == ['inspect', '--format'] and command[4:] == [row[0] for row in containers]
            output = '\n'.join(json.dumps(row) for row in containers)
        return SimpleNamespace(returncode=0, stdout=output.encode(), stderr=b'')
    monkeypatch.setattr(cleanup, 'subprocess', SimpleNamespace(run=docker))
    proc = tmp_path / 'synthetic-proc'; proc.mkdir(mode=0o700)
    scanner = cleanup.process_references
    monkeypatch.setattr(cleanup, 'process_references', lambda checkout, **kwargs: scanner(checkout, proc=proc, **kwargs))
    def quiet(checkout, tag, token):
        cleanup.quiescent({'checkout': checkout, 'token': token}, tag, cleanup.docker_snapshot(), include_inbox=True)
    options = {'request_sha256': sha(retirer.canonical(request)), 'expected_current': current, 'identity': identity,
        'quiescence': quiet, 'public_cache_batch': retirer.PUBLIC_CACHE_BATCH}
    original_paths[seed] = seed_raw
    return SimpleNamespace(retirer=retirer, root=root, current=current, identity=identity, request=request, raw=retirer.canonical(request),
        local_raw=local_raw, options=options, cleanup=cleanup, quiet=quiet, containers=containers, proc=proc,
        layers=layer_paths, tars=tar_paths, originals=original_paths, seed=seed)


def test_public_only_actual_cli_capture_twenty_layers_then_five_generated_tars_without_any_jar(recent_public_case, monkeypatch, capsys):
    s = recent_public_case
    monkeypatch.setattr(retirer, 'admitted_current', lambda args: (s.root, s.current, s.identity, s.quiet, {'cleanup': s.cleanup}))
    common = ['--mode', 'Maintenance', '--public-cache-batch', retirer.PUBLIC_CACHE_BATCH,
        '--root', str(s.root), '--tag', s.current['release'], '--commit', s.current['commit'],
        '--source-sha256', s.current['sourceSha256'], '--instance-id', s.identity['instanceId'],
        '--machine-id', s.identity['machineId'], '--current-receipt-sha256', 'a' * 64]
    def invoke(phase, *flags):
        assert retirer.cli(['--phase', phase, *common, *flags]) == 0
        return json.loads(capsys.readouterr().out)
    captured = invoke('capture-public-cache-request', '--local-spec-sha256', sha(s.local_raw))
    assert captured['skipped'] == [] and captured['publicCacheBatch'] == retirer.PUBLIC_CACHE_BATCH
    for phase, count in [('public-layers', 20), ('generated-image-archives', 5)]:
        planned = invoke('plan-' + phase, '--request-sha256', captured['request']['sha256'])
        assert planned['candidateAttemptCount'] == 5 and planned['candidateTargetCount'] == count and planned['skipped'] == []
        result = invoke('apply-' + phase, '--request-sha256', captured['request']['sha256'], '--plan-sha256', planned['plan']['sha256'])
        assert result['status'] == 'REMOVED' and result['deletedFiles'] == count
        assert result['testsRunByRetirement'] is False
    inspected = invoke('inspect')
    assert {'publicLayerPlan', 'publicLayerReceipt', 'publicLayerJournal', 'generatedArchivePlan', 'generatedArchiveReceipt', 'generatedArchiveJournal'} <= set(inspected['files'])
    assert all(not path.exists() for path in s.layers + s.tars)
    assert all(path.read_bytes() == body for path, body in s.originals.items())
    assert not list(s.root.glob('inbox/*/application.jar')) and not list(s.root.glob('verification/*/checkout/work/compact-fixtures/candidate-app.jar'))


@pytest.mark.parametrize('reference', ['same-tag-stopped', 'same-tag-running', 'checkout-bind', 'inbox-bind', 'ancestor-bind'])
def test_public_only_real_docker_enumeration_refuses_every_old_container_reference(recent_public_case, reference):
    s = recent_public_case; tag = next(iter(retirer.PUBLIC_CACHE_TARGETS)); release = 'unrelated'; mounts = []
    if reference.startswith('same-tag'): release = tag
    else:
        path = {'checkout-bind': s.root / 'verification' / tag / 'checkout', 'inbox-bind': s.root / 'inbox' / tag,
                'ancestor-bind': s.root}[reference]
        mounts = [{'Type': 'bind', 'Source': str(path)}]
    s.containers.append(['a' * 64, reference == 'same-tag-running', False, 1234 if reference == 'same-tag-running' else 0, release, None, mounts])
    value = retirer.plan_public_layers(s.root, s.raw, **s.options)
    assert value['skipped'] and len(value['candidates']) < 5
    with pytest.raises(retirer.RetirementError, match='COMPLETE_TWENTY_PUBLIC_LAYER_PLAN_REQUIRED'):
        retirer.apply_public_layers(s.root, s.raw, value, plan_sha256=sha(retirer.canonical(value)), **s.options)
    assert all(path.exists() for path in s.layers + s.tars)


@pytest.mark.parametrize('damage', ['missing-row', 'foreign-source', 'jar-policy', 'other-batch'])
def test_public_only_capture_never_inherits_jar_or_other_epoch_authority(recent_public_case, damage):
    s = recent_public_case; request = json.loads(s.local_raw); options = {'public_cache_batch': retirer.PUBLIC_CACHE_BATCH}
    if damage == 'missing-row': request['candidates'].pop()
    elif damage == 'foreign-source': request['candidates'][-1]['sourceSha256'] = '0' * 64
    elif damage == 'jar-policy': options['canonical_jar'] = True
    else: options['public_cache_batch'] = 'other-public-batch'
    raw = retirer.canonical(request)
    with pytest.raises(retirer.RetirementError):
        retirer.capture_request(s.root, raw, local_spec_sha256=sha(raw), expected_current=s.current, identity=s.identity, **options)
    assert all(path.exists() for path in s.layers + s.tars)


@pytest.mark.parametrize('changed', ['prepared-control', 'source', 'keeper', 'container', 'publication'])
def test_public_layer_capture_rechecks_real_originals_and_quiescence_before_unlink(recent_public_case, monkeypatch, changed):
    s = recent_public_case; tag = next(iter(retirer.PUBLIC_CACHE_TARGETS)); capture = retirer._capture_no_replace
    value = retirer.plan_public_layers(s.root, s.raw, **s.options)
    def mutate(*args):
        capture(*args)
        if changed == 'prepared-control': (s.root / 'inbox' / tag / 'candidate-build-tools/tools.json').write_bytes(b'changed prepared control')
        elif changed == 'source': (s.root / 'inbox' / tag / 'source.tar.gz').write_bytes(b'changed old source')
        elif changed == 'keeper': next(path for path in s.originals if 'official-oci' in str(path)).write_bytes(b'changed keeper')
        elif changed == 'publication': (s.root / 'releases' / tag).mkdir(parents=True, mode=0o700)
        else: s.containers.append(['a' * 64, False, False, 0, tag, None, []])
    monkeypatch.setattr(retirer, '_capture_no_replace', mutate)
    result = retirer.apply_public_layers(s.root, s.raw, value, plan_sha256=sha(retirer.canonical(value)), **s.options)
    assert result['status'] == 'FAILED_OR_UNKNOWN' and result['deleted'] == [] and len(result['retainedQuarantinePaths']) == 1
    assert (s.root / result['retainedQuarantinePaths'][0]).exists() and all(path.exists() for path in s.tars)


def test_public_new_targets_do_not_enter_default_paths_or_jar_permissions(recent_public_case):
    s = recent_public_case; tag = next(iter(retirer.PUBLIC_CACHE_TARGETS)); checksum, length = next(iter(retirer.PUBLIC_LAYERS.items()))
    with pytest.raises(retirer.RetirementError): retirer.duplicate_paths(s.root, tag, kind=retirer.PUBLIC_LAYER_KIND, blob_sha=checksum)
    with pytest.raises(retirer.RetirementError): retirer.generated_image_archive_path(s.root, tag)
    with pytest.raises(retirer.RetirementError, match='PUBLIC_CACHE_POLICY_HAS_NO_JAR_API'):
        retirer.duplicate_paths(s.root, tag, public_cache_batch=retirer.PUBLIC_CACHE_BATCH)
    assert all(tag not in retirer.APPROVED_OLD for tag in retirer.PUBLIC_CACHE_TARGETS)
