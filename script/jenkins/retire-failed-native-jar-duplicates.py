"""Retire exact, proven failed native build binaries under distinct policies.

The CLI authenticates fixed current source and ECS identity before importing
the existing strict cleanup admission library. The local Jenkins controller
authenticates the request SHA and the original C/D control-file byte provenance.
The default duplicate API never deletes its inbox keeper. A separate Maintenance
policy can retire only the closed, failed unpublished canonical JARs after fresh
publication and dual-root reference checks. Sources, databases and reports never
have a deletion API; retiring a binary does not promise a byte-identical rebuild.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import argparse
import ast
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tarfile
from types import SimpleNamespace
import xml.etree.ElementTree as ET


TAG = re.compile(r'ci-([1-9][0-9]*)-([a-f0-9]{12})')
SHA = re.compile(r'[a-f0-9]{64}')
COMMIT = re.compile(r'[a-f0-9]{40}')
MAX_CONTROL = 2 * 1024 ** 2
MAX_JAR = 512 * 1024 ** 2
MAX_SOURCE_ARCHIVE = 128 * 1024 ** 2
MAX_EXPANDED_SOURCE = 512 * 1024 ** 2
REQUIRED_CONTROLS = {'buildXml', 'release', 'artifactPlan', 'fixtureOwner', 'fixtureCleanup'}
OPTIONAL_CONTROLS = {'localBuild', 'fixtureCleanupPublic'}
UPLOADED_NAMES = {'buildXml': 'build.xml', 'release': 'release.json', 'localBuild': 'local-build.json',
                  'fixtureCleanupPublic': 'fixture-cleanup.json'}
KIND = 'doorhandle-failed-native-jar-duplicate'
JAR_COPY_KIND = 'FAILED_NATIVE_CANDIDATE_JAR_COPY'
CANONICAL_KIND = 'doorhandle-failed-native-canonical-jar-retirement'
CANONICAL_JAR_KIND = 'FAILED_UNPUBLISHED_CANONICAL_JAR'
PUBLIC_LAYER_KIND = 'FAILED_NATIVE_PUBLIC_BUILDKIT_LAYER_COPY'
PUBLIC_LAYER_KEEPER = 'ci-117-8c898996cc28'
# A separate, closed set: adding another historical JAR does not authorize
# deleting any of its public tool files.
PUBLIC_LAYER_TAGS = frozenset((
    'ci-117-8c898996cc28', 'ci-118-6481f7fa6021', 'ci-130-9a588271dadb',
    'ci-132-69f2ef0fb309', 'ci-134-df30e17036de', 'ci-137-facc2ed94047',
    'ci-139-384439388a8c', 'ci-141-56da3c4f7800', 'ci-143-f4b5c8d9e39b',
    'ci-145-dd85b09748a9', 'ci-154-38293aa306b3', 'ci-156-9e1927880595',
    'ci-160-9d011d9d5ed8', 'ci-166-a3c084e1cf56', 'ci-168-a40c779d03a4',
    'ci-173-45465e873d92'))
PUBLIC_LAYERS = {
    '4aa1a2a1517cd8ba9f5afb587e3c14ec7d2d8bd815bdc3fc78399136e481960c': 12178906,
    '5e9b4a97f6395abf54a5c584be133078deb2295e280dd0b9e77638874d07b637': 3852227,
    'd27f550f8c61406359cf1cdfcf92148f25f78420785f1bb168998a793201ab05': 93368900,
    'ee5a8219dd90c7f5048bc9378431acfe6b8863dadf3620acc1d171d7033484b9': 10466584,
}
PUBLIC_ARCHIVE_SHA = 'f706cb2289c61a04311882a3abbba15d56928a91d3fe9e13b96e1a8d44f378c8'
PUBLIC_ARCHIVE_BYTES = 119889920
PUBLIC_KIND = 'doorhandle-failed-native-public-layer-duplicate'
GENERATED_CACHE_KIND = 'GENERATED_PUBLIC_IMAGE_ARCHIVE_CACHE'
GENERATED_KIND = 'doorhandle-generated-public-image-archive-cache'
APPROVED_OLD = {
    'ci-117-8c898996cc28': '8c898996cc28ce30fd6531710511f833cccb4864',
    'ci-118-6481f7fa6021': '6481f7fa6021eb36592a081d04f385886c03412a',
    'ci-130-9a588271dadb': '9a588271dadb135ec4284392ef7b9c9c55ea511d',
    'ci-132-69f2ef0fb309': '69f2ef0fb3091cc204b75194aa6da96c696136f0',
    'ci-134-df30e17036de': 'df30e17036de96863957b13e57f12b129bbfa951',
    'ci-137-facc2ed94047': 'facc2ed94047d7cc01da8072195e6d769c6f1385',
    'ci-139-384439388a8c': '384439388a8c6de52ca90be62722c382ff8973bb',
    'ci-141-56da3c4f7800': '56da3c4f780055e4f1f1ae835888189e85807bec',
    'ci-143-f4b5c8d9e39b': 'f4b5c8d9e39bfe621c97fb1d9e82aea667bab08f',
    'ci-145-dd85b09748a9': 'dd85b09748a996f68e909fa54bc9412110e78134',
    'ci-154-38293aa306b3': '38293aa306b368964bbc2a7f66bb6a6b5c414016',
    'ci-156-9e1927880595': '9e1927880595e78c778288e45423bdd27bd818a8',
    'ci-160-9d011d9d5ed8': '9d011d9d5ed8ef1b6e5526c0964ee5f405ed421b',
    'ci-166-a3c084e1cf56': 'a3c084e1cf568206baca89908542537ad825fef8',
    'ci-168-a40c779d03a4': 'a40c779d03a43b894ead5569b8eb26ee7dc22a2e',
    'ci-173-45465e873d92': '45465e873d92822abe446fd7be3f9f00b7816f70',
}
# These three closed MySQL attempts authorize only the separate canonical JAR
# API. They never enter the old builder, public-layer or generated-cache sets.
RECENT_CANONICAL_ONLY = {
    'ci-195-2c2e65a0daa9': '2c2e65a0daa94d96b327c59d720871ab70bff0a1',
    'ci-198-7af0903ee840': '7af0903ee84011dc51f4abac4f4a4d9679db7322',
    'ci-201-803baf401b5f': '803baf401b5f9566283a59cb6a885a794b9d7d85',
}
# Reviewed historical publication predicates, authenticated against actual
# retained archive members (not the current checkout or a synthesized report).
# Each pair is Jenkinsfile.ecs-monolith, script/jenkins/pipeline.ps1. All these
# sources restrict publishing to verify-deploy/rollback or compact-cutover and
# return from VerifyRuntime. The terminal original XML must independently match.
APPROVED_CANONICAL_SOURCES = {
    'ci-117-8c898996cc28': ('4f8b3274861c913955ca716482fd183d9796d7c0d418da9527ca923e30fe4e37', '8a337d098a5715a3804116ba45fd0f127b339710605d3a3ed959294f4d988765'),
    'ci-118-6481f7fa6021': ('4f8b3274861c913955ca716482fd183d9796d7c0d418da9527ca923e30fe4e37', '8a337d098a5715a3804116ba45fd0f127b339710605d3a3ed959294f4d988765'),
    'ci-130-9a588271dadb': ('d1dcfa1277111c5535e59cf315e14a74670ad1f3b187d36debda9e55951f9e12', '0e528f57dfab5dca6f76a90991f26619477dac1a4e85d223447fa02593a892a4'),
    'ci-132-69f2ef0fb309': ('d1dcfa1277111c5535e59cf315e14a74670ad1f3b187d36debda9e55951f9e12', '0e528f57dfab5dca6f76a90991f26619477dac1a4e85d223447fa02593a892a4'),
    'ci-134-df30e17036de': ('d1dcfa1277111c5535e59cf315e14a74670ad1f3b187d36debda9e55951f9e12', '0e528f57dfab5dca6f76a90991f26619477dac1a4e85d223447fa02593a892a4'),
    'ci-137-facc2ed94047': ('d1dcfa1277111c5535e59cf315e14a74670ad1f3b187d36debda9e55951f9e12', '0e528f57dfab5dca6f76a90991f26619477dac1a4e85d223447fa02593a892a4'),
    'ci-139-384439388a8c': ('d1dcfa1277111c5535e59cf315e14a74670ad1f3b187d36debda9e55951f9e12', '0e528f57dfab5dca6f76a90991f26619477dac1a4e85d223447fa02593a892a4'),
    'ci-141-56da3c4f7800': ('d1dcfa1277111c5535e59cf315e14a74670ad1f3b187d36debda9e55951f9e12', '0e528f57dfab5dca6f76a90991f26619477dac1a4e85d223447fa02593a892a4'),
    'ci-143-f4b5c8d9e39b': ('d1dcfa1277111c5535e59cf315e14a74670ad1f3b187d36debda9e55951f9e12', '0e528f57dfab5dca6f76a90991f26619477dac1a4e85d223447fa02593a892a4'),
    'ci-145-dd85b09748a9': ('71e7d874bc38de370179eeda9675b1fe5c74e613ddec394d2540dea1a4c3c054', 'a77ecf39d00a2debccbf2c646aa1ec02cc62b58ce72157f25ffac452610fbab8'),
    'ci-154-38293aa306b3': ('71e7d874bc38de370179eeda9675b1fe5c74e613ddec394d2540dea1a4c3c054', '91acb59fcd4ecdcb331d01914d0b79eac5b95b48e18e937d5b4f8578cb28c364'),
    'ci-156-9e1927880595': ('71e7d874bc38de370179eeda9675b1fe5c74e613ddec394d2540dea1a4c3c054', '91acb59fcd4ecdcb331d01914d0b79eac5b95b48e18e937d5b4f8578cb28c364'),
    'ci-160-9d011d9d5ed8': ('b6a326526abceba1ffea41ccc4d21b14e5215cf9bdfe24ae50d0c9086d634033', '462c7fb838342cb1a0506c5d00bfde78c3537d2090087df8624d7e40e91cd479'),
    'ci-166-a3c084e1cf56': ('aaae4dbdc779fe665efc0b02fc8123f8fa562280177c424f40c68c225376e64a', '83a937f54c651747b19c53b59053550ba0c1c8ed3c7b223e5f277ca7bd92590f'),
    'ci-168-a40c779d03a4': ('aaae4dbdc779fe665efc0b02fc8123f8fa562280177c424f40c68c225376e64a', '83a937f54c651747b19c53b59053550ba0c1c8ed3c7b223e5f277ca7bd92590f'),
    'ci-173-45465e873d92': ('aaae4dbdc779fe665efc0b02fc8123f8fa562280177c424f40c68c225376e64a', 'da877add8d55d160bb4a9f005f096879c5607167bc0b34f3c343d0f6309b3952'),
    'ci-195-2c2e65a0daa9': ('ef8373c5b28d6ce8394d05017cf08b8db12a27a7fff507bc4c3f10367d6480b0', '25d0f06947fa2fef23d2857aa2f2dc51358ca1981f6e425ec8150cc5b42e40f3'),
    'ci-198-7af0903ee840': ('ef8373c5b28d6ce8394d05017cf08b8db12a27a7fff507bc4c3f10367d6480b0', '25d0f06947fa2fef23d2857aa2f2dc51358ca1981f6e425ec8150cc5b42e40f3'),
    'ci-201-803baf401b5f': ('ef8373c5b28d6ce8394d05017cf08b8db12a27a7fff507bc4c3f10367d6480b0', 'c9ef58f60e0be6f9a198039da7a9cd7f03bd544a93294a254765cde2ba789d85'),
}
# Original tool bytes recorded by the retained Jenkins preparation receipts.
# These values authenticate the owner chain; matching self-described fields
# alone never authorize retiring an old container.
APPROVED_BUILDER_TOOLS = {
    'ci-117-8c898996cc28': 'da96602b35fc023d3b07ea853026dcc311739c1c3903e086f81af3d7e912a9e4',
    'ci-118-6481f7fa6021': 'ff6df0c9f30b38d66f6bc6bbfd42c2fae86d6fe75a7906fafbe19ce10fcb326a',
    'ci-130-9a588271dadb': '805a2a101db89e26ef54224cd4f1456f4f4b545675485a114374cacbc2bc3fb1',
    'ci-132-69f2ef0fb309': '3123890d98586741cb14d2c2af0d269337b04243d985665b7e46a2c7b2a490d5',
    'ci-134-df30e17036de': 'f8cf1deacead2aad74b133409813bd4448218a68231fda43e3cf1c0088b29252',
    'ci-137-facc2ed94047': 'c8499b18b72497ec1d46d239ebbfcdbf5b2c1a24b6989a194f79eff9685e6313',
    'ci-139-384439388a8c': '0d01a488d105dca27e5926b2ff0fb0070c8a50ce615b79ab4ac1032ca4d6bf9a',
    'ci-141-56da3c4f7800': '332eaa16ca7c39154ff4f81dc9956ad6cf51f1ee3fda8075787c2067a255b87b',
    'ci-143-f4b5c8d9e39b': '74d9b97fbaaa8d5af0cea2d3cfa32df7b5f831e392bcca39340eac02d46cac04',
    'ci-145-dd85b09748a9': '7e55b094d7b558fd66d299a6c872749d6cb87071b50bb031ce2a5d71d03283d4',
    'ci-154-38293aa306b3': 'eb0d82fc9983279390d467849029786648a1dbceda53371924e3894232e25c27',
    'ci-156-9e1927880595': '8ef758580e6ef99418a040ff902b69836ed48c6968da6716da535ddf61d914a4',
    'ci-160-9d011d9d5ed8': '14eb0f10f654b843eb09678d87b1b56dc04478f9b6c1151390cf07496a4747bb',
    'ci-166-a3c084e1cf56': '505328c60fa3f2d92361686eb8114477d1350ceb0d3d6dcf728e2b970e444886',
    'ci-168-a40c779d03a4': '005ae7aa23900ca7bcbf4e72d51c8fef814208a7d55b279a3b0cb34ea0c93131',
    'ci-173-45465e873d92': '45bad0430d3cb6ef8f216690e5ab263c7c143dea8899b7811b201a0254d0746d',
}


class RetirementError(ValueError):
    pass


def need(value, code):
    if not value: raise RetirementError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def digest_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def metadata(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_blocks * 512]


def decode(raw):
    need(type(raw) is bytes and 0 < len(raw) <= MAX_CONTROL, 'BOUNDED_RAW_CONTROL_REQUIRED')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'DUPLICATE_CONTROL_FIELD'); result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _v: need(False, 'NONFINITE_CONTROL'))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise RetirementError('INVALID_CONTROL_JSON') from None
    need(type(value) is dict, 'CONTROL_OBJECT_REQUIRED')
    return value


def validate_context(context):
    need(type(context) is dict and set(context) == {'release', 'commit', 'sourceSha256'}
         and type(context['release']) is str and TAG.fullmatch(context['release'])
         and type(context['commit']) is str and COMMIT.fullmatch(context['commit'])
         and context['release'].endswith('-' + context['commit'][:12])
         and type(context['sourceSha256']) is str and SHA.fullmatch(context['sourceSha256']), 'FIXED_BUILD_CONTEXT_REQUIRED')


def same_context(value, context):
    need(all(value.get(key) == expected for key, expected in context.items()), 'CROSS_BUILD_CONTROL')


def canonical_commit(tag):
    return APPROVED_OLD.get(tag) or RECENT_CANONICAL_ONLY.get(tag)


def terminal_xml(raw, context, *, canonical_jar=False):
    need(type(canonical_jar) is bool, 'EXACT_RETIREMENT_POLICY_REQUIRED')
    need(type(raw) is bytes and 0 < len(raw) <= MAX_CONTROL
         and b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(), 'BOUNDED_ENTITY_FREE_TERMINAL_XML_REQUIRED')
    try: root = ET.fromstring(raw)
    except ET.ParseError: raise RetirementError('INVALID_TERMINAL_XML') from None
    need(root.tag == 'flow-build' and len(root.findall('result')) == len(root.findall('completed')) == 1
         and root.findtext('result') in ('FAILURE', 'ABORTED') and root.findtext('completed') == 'true'
         and len(root.findall('execution/done')) == 1 and root.findtext('execution/done') == 'true',
         'ACTUAL_FAILED_NATIVE_TERMINAL_REQUIRED')
    parameters = {}
    for item in root.findall('.//hudson.model.ParametersAction/parameters/*'):
        name, value = item.findtext('name'), item.findtext('value')
        need(name and name not in parameters, 'DUPLICATE_TERMINAL_PARAMETER')
        parameters[name] = value
    # 195/198 were verify/mysql; only the exact registered 201 was verify-runtime.
    expected_action = ('verify' if canonical_jar and RECENT_CANONICAL_ONLY.get(context['release']) == context['commit']
                       and context['release'] != 'ci-201-803baf401b5f'
                       else 'verify-runtime')
    need(all(parameters.get(key) == value for key, value in {'ACTION': expected_action, 'DOORHANDLE_CI_SCOPE': 'mysql',
        'TRUSTED_COMMIT': context['commit'], 'PRODUCTION_RELEASE_ENABLED': 'false'}.items()), 'FAILED_NATIVE_PARAMETERS_REQUIRED')
    return root.findtext('result')


def validate_control_documents(raw_docs, context, identity, *, canonical_jar=False):
    """Pure validation of actual raw controls already authenticated by Jenkins."""
    validate_context(context)
    need(type(identity) is dict and set(identity) == {'instanceId', 'machineId', 'executionLocation'}
         and identity['executionLocation'] == 'ECS' and type(identity['instanceId']) is str
         and re.fullmatch(r'i-[a-z0-9]+', identity['instanceId']) and type(identity['machineId']) is str
         and re.fullmatch(r'[a-f0-9]{32}', identity['machineId']), 'EXACT_ECS_IDENTITY_REQUIRED')
    need(type(raw_docs) is dict and REQUIRED_CONTROLS <= set(raw_docs) <= REQUIRED_CONTROLS | OPTIONAL_CONTROLS,
         'COMPLETE_ACTUAL_CONTROL_BUNDLE_REQUIRED')
    result = terminal_xml(raw_docs['buildXml'], context, canonical_jar=canonical_jar)
    docs = {name: decode(raw) for name, raw in raw_docs.items() if name != 'buildXml'}
    release, plan, owner, cleanup = (docs[name] for name in ('release', 'artifactPlan', 'fixtureOwner', 'fixtureCleanup'))
    for value in (release, plan, owner, cleanup): same_context(value, context)
    jar_sha, jar_bytes = release.get('applicationJarSha256'), plan.get('applicationJarBytes')
    need(type(jar_sha) is str and SHA.fullmatch(jar_sha) and type(jar_bytes) is int and 0 < jar_bytes <= MAX_JAR
         and plan.get('schema') == 1 and type(plan['schema']) is int
         and plan.get('kind') == 'doorhandle-compact-fixture-artifacts' and plan.get('applicationJarSha256') == jar_sha,
         'RELEASE_AND_NATIVE_ARTIFACT_PLAN_REQUIRED')
    suffix = '/verification/' + context['release'] + '/checkout/work/compact-fixtures'
    need(type(owner.get('schemaVersion')) is int and owner['schemaVersion'] == 1
         and owner.get('kind') == 'doorhandle-compact-fixture-owner' and owner.get('identity') == identity
         and owner.get('phase') == 'OWNED_SERVER_STOPPED' and type(owner.get('token')) is str
         and re.fullmatch(r'[a-f0-9]{10}', owner['token']) and type(owner.get('work')) is str
         and owner['work'].startswith(('/home/', '/srv/', '/opt/')) and owner['work'].endswith(suffix)
         and '..' not in Path(owner['work']).parts and '//' not in owner['work']
         and type(owner.get('sourceContainerId')) is str and SHA.fullmatch(owner['sourceContainerId'])
         and (owner.get('containerId') is None or type(owner['containerId']) is str and SHA.fullmatch(owner['containerId'])),
         'ORIGINAL_STOPPED_FIXTURE_OWNER_REQUIRED')
    need(type(cleanup.get('schemaVersion')) is int and cleanup['schemaVersion'] == 1
         and cleanup.get('kind') == 'doorhandle-compact-fixture-cleanup' and cleanup.get('identity') == identity
         and cleanup.get('status') == 'STOPPED' and cleanup.get('errors') == []
         and cleanup.get('containerId') == owner.get('containerId')
         and cleanup.get('sourceContainerUntouched') == owner['sourceContainerId']
         and cleanup.get('sourceDumpAndEvidenceRetained') is True, 'ORIGINAL_NATIVE_CLEANUP_NOT_CONFIRMED')
    if 'localBuild' in docs:
        local = docs['localBuild']
        need(local.get('release') == context['release'] and local.get('commit') == context['commit']
             and ('sourceSha256' not in local or local['sourceSha256'] == context['sourceSha256']), 'OPTIONAL_LOCAL_BUILD_CONTEXT_DRIFT')
        need(type(local.get('schemaVersion')) is int and local['schemaVersion'] == 1
             and local.get('status') == 'PASS' and type(local.get('exitCode')) is int and local['exitCode'] == 0
             and local.get('testsExecuted') is False and local.get('skipTests') is True
             and local.get('applicationJarSha256') == jar_sha and type(local.get('applicationJarBytes')) is int
             and local['applicationJarBytes'] == jar_bytes
             and release.get('localBuildReceiptSha256') == digest_bytes(raw_docs['localBuild']), 'OPTIONAL_LOCAL_BUILD_BINDING_DRIFT')
    if 'fixtureCleanupPublic' in docs:
        public = docs['fixtureCleanupPublic']
        need(public.get('release') == context['release'] and public.get('commit') == context['commit']
             and public.get('status') == 'STOPPED' and public.get('cleanupReceipt') == owner['work'] + '/cleanup-receipt.json'
             and public.get('cleanupReceiptSha256') == digest_bytes(raw_docs['fixtureCleanup']), 'OPTIONAL_CLEANUP_WRAPPER_DRIFT')
    return {'context': dict(context), 'identity': dict(identity), 'jenkinsResult': result,
            'jarSha256': jar_sha, 'jarBytes': jar_bytes, 'ownerToken': owner['token'], 'work': owner['work'],
            'controlSha256': {name: digest_bytes(raw) for name, raw in raw_docs.items()}}


def owned_path(root, path, *, directory=False):
    root, path = Path(root), Path(path)
    need(root.is_absolute() and root.resolve(strict=True) == root and path.is_absolute()
         and path.is_relative_to(root) and '..' not in path.parts and path.resolve(strict=True) == path,
         'CANONICAL_SAME_CI_ROOT_REQUIRED')
    for parent in (path, *path.parents):
        info = parent.lstat(); need(not stat.S_ISLNK(info.st_mode), 'LINK_NOT_ALLOWED')
        if parent == root or parent.is_relative_to(root):
            need(info.st_uid == os.getuid() and not info.st_mode & 0o022, 'OWNER_OR_MODE_CHANGED')
    info = path.lstat()
    need(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
         'REGULAR_SINGLE_LINK_REQUIRED')
    return path


@contextmanager
def held_file(root, path, maximum):
    path = owned_path(root, path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = metadata(os.fstat(stream.fileno()))
        need(before == metadata(path.lstat()) and 0 <= before[6] <= maximum, 'STABLE_BOUNDED_FILE_REQUIRED')
        yield stream, before
        need(before == metadata(os.fstat(stream.fileno())) == metadata(path.lstat()), 'FILE_CHANGED_DURING_READ')


def hash_stream(stream, maximum=MAX_JAR):
    stream.seek(0); checksum = hashlib.sha256(); total = 0
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        total += len(block); need(total <= maximum, 'STREAM_BYTE_LIMIT_EXCEEDED'); checksum.update(block)
    return checksum.hexdigest()


def duplicate_paths(root, tag, *, kind=JAR_COPY_KIND, blob_sha=None):
    need(type(tag) is str and TAG.fullmatch(tag), 'EXACT_OLD_TAG_REQUIRED')
    root = Path(root)
    if kind == PUBLIC_LAYER_KIND:
        need(tag in PUBLIC_LAYER_TAGS and tag != PUBLIC_LAYER_KEEPER and blob_sha in PUBLIC_LAYERS,
             'ONLY_FIXED_PUBLIC_LAYER_COPIES_HAVE_A_DELETION_API')
        suffix = Path('candidate-build-tools/official-oci/blobs/sha256') / blob_sha
        return root / 'inbox' / tag / suffix, root / 'inbox' / PUBLIC_LAYER_KEEPER / suffix
    need(kind == JAR_COPY_KIND and blob_sha is None, 'EXACT_DUPLICATE_KIND_REQUIRED')
    return (root / 'verification' / tag / 'checkout/work/compact-fixtures/candidate-app.jar',
            root / 'inbox' / tag / 'application.jar')


def describe_duplicate(root, tag, jar_sha, jar_bytes, *, kind=JAR_COPY_KIND):
    need(type(jar_sha) is str and SHA.fullmatch(jar_sha) and type(jar_bytes) is int and 0 < jar_bytes <= MAX_JAR,
         'EXACT_DECLARED_JAR_REQUIRED')
    need(kind != PUBLIC_LAYER_KIND or PUBLIC_LAYERS.get(jar_sha) == jar_bytes, 'EXACT_FIXED_PUBLIC_LAYER_REQUIRED')
    root = Path(root); target, keeper = duplicate_paths(root, tag, kind=kind,
        blob_sha=jar_sha if kind == PUBLIC_LAYER_KIND else None)
    need(target.exists() or target.is_symlink(), 'EXACT_CANDIDATE_COPY_MISSING')
    need(keeper.exists() or keeper.is_symlink(), 'EXACT_ECS_KEEPER_MISSING')
    with held_file(root, target, MAX_JAR) as (target_stream, target_info), held_file(root, keeper, MAX_JAR) as (keeper_stream, keeper_info):
        need(target_info[:2] != keeper_info[:2] and target_info[0] == keeper_info[0]
             and target_info[6] == keeper_info[6] == jar_bytes, 'INDEPENDENT_SAME_SIZE_DUPLICATE_REQUIRED')
        need(hash_stream(target_stream) == hash_stream(keeper_stream) == jar_sha, 'ACTUAL_KEEPER_BYTES_MUST_EQUAL_TARGET')
        return {'kind': kind, 'release': tag,
            'path': target.relative_to(root).as_posix(), 'metadata': target_info, 'sha256': jar_sha, 'bytes': jar_bytes,
            'allocatedBytes': target_info[9], 'keeper': {'path': keeper.relative_to(root).as_posix(),
                'metadata': keeper_info, 'sha256': jar_sha, 'bytes': jar_bytes}}


def reserve_quarantine(root, current_tag=None):
    """Reserve a new, private, helper-owned directory; never reuse a path."""
    root=Path(root)
    need(current_tag is None or type(current_tag) is str and TAG.fullmatch(current_tag), 'EXACT_CURRENT_QUARANTINE_TAG_REQUIRED')
    parent=root if current_tag is None else root/'inbox'/current_tag
    owned_path(root,parent,directory=True)
    name='native-jar-quarantine-'+secrets.token_hex(12)
    parent_fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        need(metadata(os.fstat(parent_fd))==metadata(parent.lstat()), 'QUARANTINE_PARENT_MOVED')
        os.mkdir(name,0o700,dir_fd=parent_fd);os.fsync(parent_fd)
        directory=parent/name;info=directory.lstat()
        need(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode)==0o700 and info.st_uid==os.getuid(),
             'PRIVATE_NEW_QUARANTINE_REQUIRED')
        return {'directory':directory.relative_to(root).as_posix(),
                'path':(directory/'candidate-app.jar').relative_to(root).as_posix(),
                'directoryIdentity':[info.st_dev,info.st_ino,info.st_mode,info.st_uid,info.st_gid]}
    finally:os.close(parent_fd)


def _capture_no_replace(source_fd, source_name, destination_fd, destination_name):
    """Linux atomic rename with NOREPLACE, never an overwriting rename fallback."""
    import ctypes
    import errno
    library=ctypes.CDLL(None,use_errno=True)
    operation=getattr(library,'renameat2',None)
    need(operation is not None, 'ATOMIC_NOREPLACE_RENAME_REQUIRED')
    operation.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    operation.restype=ctypes.c_int
    result=operation(source_fd,os.fsencode(source_name),destination_fd,os.fsencode(destination_name),1)
    if result!=0:
        number=ctypes.get_errno()
        need(number!=errno.EEXIST,'PRIVATE_QUARANTINE_ALREADY_OCCUPIED')
        raise OSError(number,os.strerror(number))


def _renamed_copy_matches(before, after):
    # rename may change ctime only. Ownership, mode, links, full length, mtime,
    # allocation and the exact device/inode must remain those of the held copy.
    return (after[:8]==before[:8] and after[9:]==before[9:]
            and type(after[8]) is int and after[8]>=before[8])


def remove_duplicate(root, descriptor, quarantine=None):
    """Capture the old path privately, prove its inode, then unlink only that copy.

    A race replacing the old path can only move an unexpected file into this
    fresh directory. An unexpected capture is retained, never unlinked or
    automatically moved back over a possibly new original path.
    """
    need(type(descriptor) is dict and set(descriptor) == {'kind', 'release', 'path', 'metadata', 'sha256', 'bytes', 'allocatedBytes', 'keeper'}
         and descriptor['kind'] in (JAR_COPY_KIND, PUBLIC_LAYER_KIND), 'EXACT_SINGLE_FILE_DESCRIPTOR_REQUIRED')
    kind = descriptor['kind']
    root = Path(root); target, keeper = duplicate_paths(root, descriptor['release'], kind=kind,
        blob_sha=descriptor['sha256'] if kind == PUBLIC_LAYER_KIND else None)
    need(descriptor['path'] == target.relative_to(root).as_posix() and type(descriptor['keeper']) is dict
         and set(descriptor['keeper']) == {'path', 'metadata', 'sha256', 'bytes'}
         and descriptor['keeper']['path'] == keeper.relative_to(root).as_posix(), 'INBOX_KEEPER_HAS_NO_DELETION_API')
    need(describe_duplicate(root, descriptor['release'], descriptor['sha256'], descriptor['bytes'], **(
        {'kind': kind} if kind != JAR_COPY_KIND else {})) == descriptor,
         'DUPLICATE_CHANGED_AFTER_PLAN')
    quarantine=reserve_quarantine(root) if quarantine is None else quarantine
    need(type(quarantine) is dict and set(quarantine)=={'directory','path','directoryIdentity'}, 'EXACT_PRIVATE_QUARANTINE_REQUIRED')
    relative=Path(quarantine['directory']);parts=relative.parts
    need((len(parts)==1 or len(parts)==3 and parts[0]=='inbox' and TAG.fullmatch(parts[1]))
         and re.fullmatch(r'native-jar-quarantine-[a-f0-9]{24}',parts[-1])
         and quarantine['path']==(relative/'candidate-app.jar').as_posix(), 'QUARANTINE_OUTSIDE_PRIVATE_ALLOWLIST')
    private=owned_path(root,root/relative,directory=True)
    info=private.lstat()
    need([info.st_dev,info.st_ino,info.st_mode,info.st_uid,info.st_gid]==quarantine['directoryIdentity']
         and stat.S_IMODE(info.st_mode)==0o700,'PRIVATE_QUARANTINE_IDENTITY_CHANGED')
    with held_file(root, keeper, MAX_JAR) as (kept, keeper_info), os.fdopen(os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as copy:
        copy_info = metadata(os.fstat(copy.fileno()))
        need(keeper_info == descriptor['keeper']['metadata'] and copy_info == descriptor['metadata']
             and hash_stream(kept) == hash_stream(copy) == descriptor['sha256'], 'DUPLICATE_CHANGED_BEFORE_UNLINK')
        stack = [os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]
        quarantine_fd=None
        try:
            quarantine_fd=os.open(private,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            def private_identity():
                value=os.fstat(quarantine_fd);linked=private.lstat()
                need([value.st_dev,value.st_ino,value.st_mode,value.st_uid,value.st_gid]
                     ==[linked.st_dev,linked.st_ino,linked.st_mode,linked.st_uid,linked.st_gid]
                     ==quarantine['directoryIdentity'],'PRIVATE_QUARANTINE_MOVED')
            private_identity()
            need(not os.listdir(quarantine_fd),'PRIVATE_QUARANTINE_ALREADY_OCCUPIED')
            device = os.fstat(stack[0]).st_dev
            for part in target.relative_to(root).parts[:-1]:
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=stack[-1]); stack.append(fd)
                info = os.fstat(fd)
                need(info.st_uid == os.getuid() and info.st_dev == device and not info.st_mode & 0o022,
                     'DELETION_ANCESTOR_CHANGED')
            need(metadata(os.stat(target.name, dir_fd=stack[-1], follow_symlinks=False)) == copy_info
                 and metadata(os.fstat(copy.fileno())) == copy_info and metadata(keeper.lstat()) == keeper_info,
                 'TARGET_OR_KEEPER_MOVED_BEFORE_UNLINK')
            _capture_no_replace(stack[-1],target.name,quarantine_fd,'candidate-app.jar')
            os.fsync(stack[-1]);os.fsync(quarantine_fd)
            captured=metadata(os.stat('candidate-app.jar',dir_fd=quarantine_fd,follow_symlinks=False))
            held_copy=metadata(os.fstat(copy.fileno()))
            need(captured[:2]==copy_info[:2] and captured[:2]!=keeper_info[:2]
                 and captured==held_copy and _renamed_copy_matches(copy_info,captured),
                 'UNEXPECTED_CAPTURED_INODE_RETAINED')
            need(metadata(os.fstat(kept.fileno()))==keeper_info==metadata(keeper.lstat())
                 and hash_stream(kept)==hash_stream(copy)==descriptor['sha256'],
                 'KEEPER_OR_CAPTURE_CHANGED_RETAIN_QUARANTINE')
            need(not target.exists() and not target.is_symlink(),'ORIGINAL_TARGET_REAPPEARED_RETAIN_QUARANTINE')
            private_identity()
            need(os.listdir(quarantine_fd)==['candidate-app.jar']
                 and metadata(os.stat('candidate-app.jar',dir_fd=quarantine_fd,follow_symlinks=False))==captured
                 and metadata(os.fstat(copy.fileno()))==captured
                 and metadata(keeper.lstat())==keeper_info,'CAPTURE_OR_KEEPER_MOVED_RETAIN_QUARANTINE')
            os.unlink('candidate-app.jar',dir_fd=quarantine_fd);os.fsync(quarantine_fd)
            need(not os.listdir(quarantine_fd),'QUARANTINE_REMOVAL_NOT_CONFIRMED')
            need(not target.exists() and not target.is_symlink(), 'EXACT_DUPLICATE_REMOVAL_NOT_CONFIRMED')
            need(metadata(os.fstat(kept.fileno())) == keeper_info == metadata(keeper.lstat())
                 and hash_stream(kept) == descriptor['sha256'], 'KEEPER_CHANGED_AFTER_UNLINK_REVIEW_REQUIRED')
        finally:
            if quarantine_fd is not None:os.close(quarantine_fd)
            for fd in reversed(stack): os.close(fd)
        return {'path': descriptor['path'], 'bytes': descriptor['bytes'], 'allocatedBytes': descriptor['allocatedBytes'],
                'sha256': descriptor['sha256'], 'keeperPath': descriptor['keeper']['path'], 'keeperVerifiedAfter': True,
                'quarantinePath':quarantine['path'],'capturedInodeVerified':True}


def source_proof(root, tag, commit, source_sha, *, builder_helpers=False, canonical_jar=False):
    """Read and authenticate the retained archive; never extract or run it."""
    path = Path(root) / 'inbox' / tag / 'source.tar.gz'
    need(path.exists() or path.is_symlink(), 'OLD_SOURCE_ARCHIVE_MISSING')
    with held_file(root, path, MAX_SOURCE_ARCHIVE) as (stream, signature):
        need(hash_stream(stream, MAX_SOURCE_ARCHIVE) == source_sha, 'OLD_SOURCE_ARCHIVE_SHA_DRIFT')
        stream.seek(0); recipe = None; builder_shas = {}; publication_shas = {}
        publication_names = ('Jenkinsfile.ecs-monolith', 'script/jenkins/pipeline.ps1')
        builder_names = {'script/docker/compact-build-resources.py', 'script/docker/compact-image-inputs.py'}
        class Bounded:
            def __init__(self, source): self.source, self.total = source, 0
            def read(self, size=-1):
                remaining = MAX_EXPANDED_SOURCE - self.total
                block = self.source.read(remaining + 1 if size < 0 else min(size, remaining + 1))
                self.total += len(block); need(self.total <= MAX_EXPANDED_SOURCE, 'SOURCE_EXPANSION_BOUND_EXCEEDED')
                return block
        with gzip.GzipFile(fileobj=stream, mode='rb') as expanded, tarfile.open(fileobj=Bounded(expanded), mode='r|') as archive:
            count = 0
            for member in archive:
                count += 1; need(count <= 50_000 and 0 <= member.size <= 32 * 1024 ** 2, 'SOURCE_MEMBER_BOUND_EXCEEDED')
                if canonical_jar and member.name in publication_names:
                    need(member.name not in publication_shas and member.isfile() and 0 < member.size <= 1024 ** 2,
                         'UNIQUE_OLD_PUBLICATION_SOURCE_REQUIRED')
                    raw = archive.extractfile(member).read(1024 ** 2 + 1)
                    need(len(raw) == member.size, 'OLD_PUBLICATION_SOURCE_TRUNCATED')
                    publication_shas[member.name] = digest_bytes(raw)
                if builder_helpers and member.name in builder_names:
                    key = Path(member.name).name
                    need(key not in builder_shas and member.isfile() and 0 < member.size <= 1024 ** 2,
                         'UNIQUE_OLD_BUILDER_HELPER_REQUIRED')
                    raw = archive.extractfile(member).read(1024 ** 2 + 1)
                    need(len(raw) == member.size, 'OLD_BUILDER_HELPER_TRUNCATED'); builder_shas[key] = digest_bytes(raw)
                if member.name != 'script/jenkins/prepare-compact-fixtures.py': continue
                need(recipe is None and member.isfile() and 0 < member.size <= 1024 ** 2, 'UNIQUE_TRANSPORT_RECIPE_REQUIRED')
                recipe = archive.extractfile(member).read(1024 ** 2 + 1)
                need(len(recipe) == member.size, 'TRANSPORT_RECIPE_TRUNCATED')
            need(archive.pax_headers.get('comment') == commit and recipe is not None, 'FIXED_OLD_SOURCE_COMMIT_REQUIRED')
        try: syntax = ast.parse(recipe)
        except (SyntaxError, RecursionError): raise RetirementError('INVALID_OLD_TRANSPORT_RECIPE') from None
        # This proves the precise reviewed copy location without executing an
        # old script, inferring an arbitrary JAR path or deleting build trees.
        expected_target = ast.dump(ast.parse("uploaded = self.work / 'candidate-app.jar'").body[0], include_attributes=False)
        expected_keeper = ast.dump(ast.parse("jar = canonical(self.inbox / 'application.jar')").body[0], include_attributes=False)
        expected_copy = ast.dump(ast.parse('shutil.copyfile(jar, uploaded)').body[0].value, include_attributes=False)
        proven = False
        for node in ast.walk(syntax):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
            statements = {ast.dump(item, include_attributes=False) for item in ast.walk(node) if isinstance(item, ast.Assign)}
            calls = {ast.dump(item, include_attributes=False) for item in ast.walk(node) if isinstance(item, ast.Call)}
            if expected_target in statements and expected_keeper in statements and expected_copy in calls: proven = True
        need(proven, 'EXACT_REVIEWED_JAR_COPY_RECIPE_REQUIRED')
        proof = {'path': path.relative_to(root).as_posix(), 'metadata': signature, 'bytes': signature[6],
                 'sha256': source_sha, 'transportRecipeSha256': digest_bytes(recipe)}
        if builder_helpers:
            need(set(builder_shas) == {Path(name).name for name in builder_names}, 'ORIGINAL_BUILDER_HELPER_CLOSURE_MISSING')
            proof['builderHelperSha256'] = builder_shas
        if canonical_jar:
            need(canonical_commit(tag) == commit and set(publication_shas) == set(publication_names)
                 and tuple(publication_shas[name] for name in publication_names) == APPROVED_CANONICAL_SOURCES.get(tag),
                 'CLOSED_REVIEWED_UNPUBLISHED_SOURCE_REQUIRED')
            proof['unpublishedPipelineSourceSha256'] = publication_shas
        return proof


def validate_request(raw_request, request_sha256, expected_current, identity):
    need(type(raw_request) is bytes and type(request_sha256) is str and SHA.fullmatch(request_sha256)
         and digest_bytes(raw_request) == request_sha256, 'AUTHENTICATED_REQUEST_SHA_REQUIRED')
    validate_context(expected_current); request = decode(raw_request)
    need(set(request) == {'schemaVersion', 'kind', 'current', 'identity', 'protectedReleases', 'candidates'}
         and type(request['schemaVersion']) is int and request['schemaVersion'] == 1
         and request['kind'] == KIND + '-request' and request['current'] == expected_current
         and request['identity'] == identity and identity.get('executionLocation') == 'ECS', 'EXACT_CURRENT_REQUEST_REQUIRED')
    protected = request['protectedReleases']; candidates = request['candidates']
    need(type(protected) is list and all(type(tag) is str and TAG.fullmatch(tag) for tag in protected)
         and len(protected) == len(set(protected)) and expected_current['release'] in protected,
         'CURRENT_AND_ROLLBACK_PROTECTION_REQUIRED')
    need(type(candidates) is list and len(candidates) <= 16 and all(type(row) is dict for row in candidates), 'BOUNDED_EXACT_CANDIDATES_REQUIRED')
    tags = []
    for row in candidates:
        need(set(row) == {'release', 'commit', 'sourceSha256', 'controls'}, 'EXACT_NATIVE_CANDIDATE_REQUIRED')
        validate_context({key: row[key] for key in ('release', 'commit', 'sourceSha256')})
        need(row['release'] not in protected and int(TAG.fullmatch(row['release'])[1]) < int(TAG.fullmatch(expected_current['release'])[1]),
             'CURRENT_OR_PROTECTED_NATIVE_BUILD')
        tags.append(row['release'])
    need(len(tags) == len(set(tags)), 'DUPLICATE_CANDIDATE_TAG')
    return request


def expected_control_paths(current_tag, old_tag):
    paths = {role: 'inbox/' + current_tag + '/native-jar-duplicate-controls/' + old_tag + '/' + name
             for role, name in UPLOADED_NAMES.items()}
    base = 'verification/' + old_tag + '/checkout/work/'
    paths.update(artifactPlan='inbox/' + old_tag + '/build-artifacts.json',
                 fixtureOwner=base + 'compact-fixtures-owner.json', fixtureCleanup=base + 'compact-fixtures/cleanup-receipt.json')
    return paths


def fixture_owner_projection(owner):
    """Project authenticated nonsecret owner facts without inventing old fields."""
    projected = {key: owner.get(key) for key in ('schemaVersion', 'kind', 'release', 'commit',
        'sourceSha256', 'identity', 'phase', 'token', 'work', 'containerId', 'sourceContainerId',
        'dataDirectory', 'containerName', 'image', 'port')}
    if 'binaryLoggingDisabled' in owner:
        projected['binaryLoggingDisabled'] = owner['binaryLoggingDisabled']
    return projected


def admit_historical_controls(root, request, row, *, builder_helpers=False, canonical_jar=False):
    context = {key: row[key] for key in ('release', 'commit', 'sourceSha256')}; tag = row['release']
    controls = row['controls']; names = expected_control_paths(request['current']['release'], tag)
    need(type(controls) is dict and REQUIRED_CONTROLS <= set(controls) <= REQUIRED_CONTROLS | OPTIONAL_CONTROLS,
         'COMPLETE_AUTHENTICATED_CONTROL_REFERENCES_REQUIRED')
    raw_docs, bindings = {}, {}
    for role, reference in controls.items():
        need(type(reference) is dict and set(reference) == {'path', 'bytes', 'sha256'} and reference['path'] == names[role]
             and type(reference['bytes']) is int and 0 < reference['bytes'] <= MAX_CONTROL
             and type(reference['sha256']) is str and SHA.fullmatch(reference['sha256']), 'EXACT_CONTROL_PATH_AND_SHA_REQUIRED')
        need((Path(root) / reference['path']).exists() or (Path(root) / reference['path']).is_symlink(),
             'REQUIRED_CONTROL_MISSING_' + role.upper())
        with held_file(root, Path(root) / reference['path'], MAX_CONTROL) as (stream, signature):
            raw = stream.read(MAX_CONTROL + 1)
            need(len(raw) == reference['bytes'] and digest_bytes(raw) == reference['sha256'], 'RAW_CONTROL_BYTES_DRIFT')
            raw_docs[role] = raw; bindings[role] = {**reference, 'metadata': signature}
    evidence = validate_control_documents(raw_docs, context, request['identity'], canonical_jar=canonical_jar)
    need(evidence['work'] == str(Path(root) / 'verification' / tag / 'checkout/work/compact-fixtures'), 'FIXTURE_OWNER_OUTSIDE_EXACT_OLD_ATTEMPT')
    if canonical_jar:
        original_source = source_proof(root, tag, context['commit'], context['sourceSha256'],
                                       builder_helpers=builder_helpers, canonical_jar=True)
    else:
        original_source = (source_proof(root, tag, context['commit'], context['sourceSha256'], builder_helpers=True)
                           if builder_helpers else source_proof(root, tag, context['commit'], context['sourceSha256']))
    result = {'context': context, 'evidence': evidence, 'controls': bindings, 'sourceArchive': original_source}
    if builder_helpers:
        # Original owner contains a root password. Only these nonsecret control
        # fields may enter a plan or receipt; original bytes remain private.
        owner, cleanup = decode(raw_docs['fixtureOwner']), decode(raw_docs['fixtureCleanup'])
        result['fixtureOwner'] = fixture_owner_projection(owner)
        result['fixtureCleanup'] = {key: cleanup.get(key) for key in ('schemaVersion', 'kind', 'release', 'commit',
            'sourceSha256', 'identity', 'status', 'errors', 'containerId', 'sourceContainerUntouched',
            'dataDirectoryRetained', 'sourceDumpAndEvidenceRetained')}
    return result


def admit_candidate(root, request, row, quiescence):
    admitted = admit_historical_controls(root, request, row)
    context, evidence = admitted['context'], admitted['evidence']; tag = row['release']
    # The adapter must call the existing fixed cleanup.quiescent with a fresh
    # docker_snapshot. No weaker path-only or stopped-container exception is
    # implemented by this new library.
    need(callable(quiescence), 'ACTUAL_STRICT_QUIESCENCE_ADAPTER_REQUIRED')
    need(quiescence(Path(root) / 'verification' / tag / 'checkout', tag, evidence['ownerToken']) is None,
         'STRICT_QUIESCENCE_MUST_RETURN_ONLY_AFTER_SUCCESS')
    target = describe_duplicate(root, tag, evidence['jarSha256'], evidence['jarBytes'])
    return {'context': context, 'jenkinsResult': evidence['jenkinsResult'], 'controls': admitted['controls'],
            'sourceArchive': admitted['sourceArchive'], 'ownerToken': evidence['ownerToken'], 'target': target}


@contextmanager
def publication_lock(root):
    """Use the deployment's own lock while reading its live/rollback pointers."""
    import fcntl
    root = owned_path(root, Path(root), directory=True); state = root / 'state'
    try: state.mkdir(mode=0o700)
    except FileExistsError: pass
    owned_path(root, state, directory=True); path = state / 'deploy.lock'
    with os.fdopen(os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600), 'r+b') as stream:
        info = os.fstat(stream.fileno())
        need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
             and not info.st_mode & 0o022 and metadata(info) == metadata(path.lstat()), 'PUBLICATION_LOCK_IDENTITY_CHANGED')
        try: fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise RetirementError('PUBLICATION_IN_PROGRESS') from None
        yield


def canonical_publication_refs(root, tag):
    root = Path(root); release = root / 'releases' / tag
    need(not release.exists() and not release.is_symlink(), 'BUILD_HAS_RETAINED_RELEASE_OR_ROLLBACK_ARTIFACTS')
    references = []
    for name in ('current-directory', 'previous-directory', 'release-publication.json'):
        path = root / 'state' / name
        if not path.exists() and not path.is_symlink():
            references.append({'path': path.relative_to(root).as_posix(), 'absent': True}); continue
        with held_file(root, path, MAX_CONTROL) as (stream, signature):
            raw = stream.read(MAX_CONTROL + 1)
            if name.endswith('.json'):
                value = decode(raw)
                need(value.get('schema') == 1 and value.get('project') == 'doorhandlecatch-monolith',
                     'CURRENT_PUBLICATION_RECORD_INVALID')
                paths = [value.get('current'), value.get('previous')]
            else:
                paths = [raw.decode('utf-8').strip()]
            for value in paths:
                need(type(value) is str and value and Path(value).is_absolute() and '..' not in Path(value).parts,
                     'CURRENT_PUBLICATION_POINTER_INVALID')
                pointer = Path(value)
                need(pointer.resolve(strict=True) == pointer and pointer.is_dir(), 'CURRENT_PUBLICATION_POINTER_INVALID')
                roots = (root / 'inbox' / tag, root / 'verification' / tag / 'checkout')
                need(tag not in pointer.parts and not any(pointer == item or item.is_relative_to(pointer) for item in roots),
                     'CANONICAL_JAR_HAS_CURRENT_OR_ROLLBACK_REFERENCE')
            references.append({'path': path.relative_to(root).as_posix(), 'metadata': signature, 'sha256': digest_bytes(raw)})
    return references


def describe_canonical_jar(root, tag, jar_sha, jar_bytes):
    need(canonical_commit(tag) is not None and type(jar_sha) is str and SHA.fullmatch(jar_sha)
         and type(jar_bytes) is int and 0 < jar_bytes <= MAX_JAR, 'EXACT_CLOSED_CANONICAL_JAR_REQUIRED')
    path = Path(root) / 'inbox' / tag / 'application.jar'
    with held_file(root, path, MAX_JAR) as (stream, signature):
        need(signature[6] == jar_bytes and hash_stream(stream) == jar_sha, 'ACTUAL_CANONICAL_JAR_BYTES_DRIFT')
        return {'kind': CANONICAL_JAR_KIND, 'release': tag, 'path': path.relative_to(root).as_posix(),
                'metadata': signature, 'sha256': jar_sha, 'bytes': jar_bytes, 'allocatedBytes': signature[9]}


def admit_canonical_candidate(root, request, row, quiescence):
    need(canonical_commit(row['release']) == row['commit'], 'ONLY_REVIEWED_OLD_ATTEMPTS_ALLOWED')
    admitted = admit_historical_controls(root, request, row, canonical_jar=True)
    evidence = admitted['evidence']; tag = row['release']
    references = canonical_publication_refs(root, tag)
    need(callable(quiescence) and quiescence(Path(root) / 'verification' / tag / 'checkout', tag, evidence['ownerToken']) is None,
         'ACTUAL_DUAL_ROOT_QUIESCENCE_REQUIRED')
    target = describe_canonical_jar(root, tag, evidence['jarSha256'], evidence['jarBytes'])
    return {'context': admitted['context'], 'jenkinsResult': evidence['jenkinsResult'], 'controls': admitted['controls'],
            'sourceArchive': admitted['sourceArchive'], 'publicationReferences': references,
            'ownerToken': evidence['ownerToken'], 'target': target}


def remove_canonical_jar(root, descriptor, quarantine, *, quiescence):
    """A separate closed single-file API; the duplicate keeper API stays closed."""
    need(type(descriptor) is dict and set(descriptor) == {'kind', 'release', 'path', 'metadata', 'sha256', 'bytes', 'allocatedBytes'}
         and descriptor['kind'] == CANONICAL_JAR_KIND, 'EXACT_CANONICAL_SINGLE_FILE_DESCRIPTOR_REQUIRED')
    root = Path(root); tag = descriptor['release']; target = root / 'inbox' / tag / 'application.jar'
    need(describe_canonical_jar(root, tag, descriptor['sha256'], descriptor['bytes']) == descriptor,
         'CANONICAL_JAR_CHANGED_AFTER_PLAN')
    need(type(quarantine) is dict and set(quarantine) == {'directory', 'path', 'directoryIdentity'}, 'EXACT_PRIVATE_QUARANTINE_REQUIRED')
    relative = Path(quarantine['directory']); parts = relative.parts
    need(len(parts) == 3 and parts[:2] == ('inbox', tag)
         and re.fullmatch(r'native-jar-quarantine-[a-f0-9]{24}', parts[2])
         and quarantine['path'] == (relative / 'candidate-app.jar').as_posix(), 'CANONICAL_QUARANTINE_MUST_STAY_IN_OLD_INBOX')
    private = owned_path(root, root / relative, directory=True)
    with os.fdopen(os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as copy:
        original = metadata(os.fstat(copy.fileno()))
        need(original == descriptor['metadata'] == metadata(target.lstat()) and hash_stream(copy) == descriptor['sha256'],
             'CANONICAL_JAR_CHANGED_BEFORE_CAPTURE')
        stack = [os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]; private_fd = None
        try:
            private_fd = os.open(private, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            def private_identity():
                info = os.fstat(private_fd); linked = private.lstat()
                need([info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid]
                     == [linked.st_dev, linked.st_ino, linked.st_mode, linked.st_uid, linked.st_gid]
                     == quarantine['directoryIdentity'] and stat.S_IMODE(info.st_mode) == 0o700, 'PRIVATE_QUARANTINE_MOVED')
            private_identity(); need(not os.listdir(private_fd), 'PRIVATE_QUARANTINE_ALREADY_OCCUPIED')
            for part in target.relative_to(root).parts[:-1]:
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=stack[-1]); stack.append(fd)
                info = os.fstat(fd)
                need(info.st_uid == os.getuid() and info.st_dev == original[0] and not info.st_mode & 0o022, 'DELETION_ANCESTOR_CHANGED')
            need(metadata(os.stat(target.name, dir_fd=stack[-1], follow_symlinks=False)) == original
                 == metadata(os.fstat(copy.fileno())), 'CANONICAL_JAR_MOVED_BEFORE_CAPTURE')
            _capture_no_replace(stack[-1], target.name, private_fd, 'candidate-app.jar')
            os.fsync(stack[-1]); os.fsync(private_fd)
            captured = metadata(os.stat('candidate-app.jar', dir_fd=private_fd, follow_symlinks=False))
            need(captured == metadata(os.fstat(copy.fileno())) and _renamed_copy_matches(original, captured)
                 and hash_stream(copy) == descriptor['sha256'], 'UNEXPECTED_CAPTURED_INODE_RETAINED')
            need(callable(quiescence) and quiescence() is None, 'ACTUAL_DUAL_ROOT_QUIESCENCE_REQUIRED')
            need(not target.exists() and not target.is_symlink(), 'ORIGINAL_TARGET_REAPPEARED_RETAIN_QUARANTINE')
            private_identity()
            need(os.listdir(private_fd) == ['candidate-app.jar']
                 and metadata(os.stat('candidate-app.jar', dir_fd=private_fd, follow_symlinks=False)) == captured
                 == metadata(os.fstat(copy.fileno())), 'CAPTURE_CHANGED_RETAIN_QUARANTINE')
            os.unlink('candidate-app.jar', dir_fd=private_fd); os.fsync(private_fd)
            need(not os.listdir(private_fd) and not target.exists() and not target.is_symlink(), 'CANONICAL_REMOVAL_NOT_CONFIRMED')
        finally:
            if private_fd is not None: os.close(private_fd)
            for fd in reversed(stack): os.close(fd)
    return {'kind': CANONICAL_JAR_KIND, 'path': descriptor['path'], 'bytes': descriptor['bytes'],
            'allocatedBytes': descriptor['allocatedBytes'], 'sha256': descriptor['sha256'],
            'quarantinePath': quarantine['path'], 'capturedInodeVerified': True, 'binaryDisposition': 'RETIRED'}


@contextmanager
def attempt_lock(root, tag):
    import fcntl
    directory = owned_path(root, Path(root) / 'verification' / tag, directory=True)
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        need(metadata(os.fstat(fd)) == metadata(directory.lstat()), 'OLD_ATTEMPT_MOVED_BEFORE_LOCK')
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise RetirementError('OLD_ATTEMPT_LOCK_HELD') from None
        yield
    finally: os.close(fd)


@contextmanager
def controller_lock(root):
    import fcntl
    root = owned_path(root, Path(root), directory=True)
    path = root / '.native-jar-duplicate-retirement.lock'
    with os.fdopen(os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600), 'r+b') as stream:
        info = os.fstat(stream.fileno())
        need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
             and stat.S_IMODE(info.st_mode) == 0o600 and metadata(info) == metadata(path.lstat()), 'PRIVATE_RETIREMENT_LOCK_REQUIRED')
        try: fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise RetirementError('RETIREMENT_CONTROLLER_LOCK_HELD') from None
        yield


def plan(root, raw_request, *, request_sha256, expected_current, identity, quiescence, canonical_jar=False):
    """Discover admitted single files; the default remains keeper-preserving."""
    request = validate_request(raw_request, request_sha256, expected_current, identity)
    need(type(canonical_jar) is bool, 'EXACT_RETIREMENT_POLICY_REQUIRED')
    admit = admit_canonical_candidate if canonical_jar else admit_candidate
    kind = CANONICAL_KIND if canonical_jar else KIND
    accepted, skipped = [], []
    with controller_lock(root), publication_lock(root) if canonical_jar else nullcontext():
        for row in request['candidates']:
            try:
                with attempt_lock(root, row['release']): accepted.append(admit(root, request, row, quiescence))
            except (RetirementError, OSError, ValueError, KeyError, TypeError, tarfile.TarError, EOFError) as error:
                skipped.append({'release': row['release'], 'reason': str(error) if isinstance(error, RetirementError) else type(error).__name__})
    result = {'schemaVersion': 1, 'kind': kind + '-plan', 'requestSha256': request_sha256,
              'current': expected_current, 'identity': identity, 'candidates': accepted, 'skipped': skipped,
              'candidateBytes': sum(row['target']['bytes'] for row in accepted),
              'candidateAllocatedBytes': sum(row['target']['allocatedBytes'] for row in accepted),
              'inboxKeepersPreserved': True, 'deletionPerformed': False}
    need(len(canonical(result)) <= MAX_CONTROL, 'BOUNDED_RETIREMENT_PLAN_REQUIRED')
    return result


def apply(root, raw_request, prepared_plan, *, request_sha256, plan_sha256, expected_current, identity, quiescence, canonical_jar=False):
    """Re-admit every selected input before exact single-file mutation.

    An interrupted/partial result must be reviewed; retry requires a newly
    prepared plan. A prior success is never synthesized for a missing file.
    """
    request = validate_request(raw_request, request_sha256, expected_current, identity)
    need(type(canonical_jar) is bool, 'EXACT_RETIREMENT_POLICY_REQUIRED')
    admit = admit_canonical_candidate if canonical_jar else admit_candidate
    kind = CANONICAL_KIND if canonical_jar else KIND
    need(type(prepared_plan) is dict and type(plan_sha256) is str and SHA.fullmatch(plan_sha256)
         and digest_bytes(canonical(prepared_plan)) == plan_sha256
         and prepared_plan.get('kind') == kind + '-plan' and prepared_plan.get('requestSha256') == request_sha256
         and prepared_plan.get('current') == expected_current and prepared_plan.get('identity') == identity
         and prepared_plan.get('inboxKeepersPreserved') is True and prepared_plan.get('deletionPerformed') is False,
         'EXACT_APPROVED_PLAN_SHA_REQUIRED')
    selected = prepared_plan.get('candidates')
    need(type(selected) is list and len(selected) <= len(request['candidates'])
         and all(type(row) is dict and type(row.get('context')) is dict for row in selected), 'BOUNDED_SELECTED_PLAN_REQUIRED')
    tags = [row['context']['release'] for row in selected]
    need(len(tags) == len(set(tags)) and set(tags) <= {row['release'] for row in request['candidates']}, 'SELECTED_PLAN_TAG_DRIFT')
    journal_path = Path(root) / 'inbox' / expected_current['release'] / (
        'native-jar-duplicate-canonical-journal.jsonl' if canonical_jar else 'native-jar-duplicate-journal.jsonl')
    owned_path(root, journal_path.parent, directory=True)
    deleted, failure, active, mutation_attempted = [], None, None, False
    active_quarantine=None;quarantines=[]
    with controller_lock(root), publication_lock(root) if canonical_jar else nullcontext(), os.fdopen(os.open(journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as journal:
        total = 0
        def record(value):
            nonlocal total
            data = canonical(value) + b'\n'; total += len(data)
            need(total <= MAX_CONTROL, 'RETIREMENT_JOURNAL_LIMIT_EXCEEDED')
            journal.write(data); journal.flush(); os.fsync(journal.fileno())
        before = os.statvfs(root)
        record({'phase': 'STARTED', 'planSha256': plan_sha256, 'requestSha256': request_sha256, 'identity': identity})
        try:
            for candidate in selected:
                active = candidate['context']['release']
                active_quarantine=None
                row = next(row for row in request['candidates'] if row['release'] == active)
                with attempt_lock(root, active):
                    need(admit(root, request, row, quiescence) == candidate, 'CANDIDATE_CHANGED_AFTER_PLAN')
                    need(quiescence(Path(root) / 'verification' / active / 'checkout', active, candidate['ownerToken']) is None,
                         'STRICT_QUIESCENCE_MUST_RETURN_ONLY_AFTER_SUCCESS')
                    active_quarantine=reserve_quarantine(root,active if canonical_jar else expected_current['release']);quarantines.append(active_quarantine)
                    record({'phase': 'DELETE_STARTED', 'release': active, 'path': candidate['target']['path'],
                            **({'kind': CANONICAL_JAR_KIND} if canonical_jar else {'keeperPath': candidate['target']['keeper']['path']}),
                            'sha256': candidate['target']['sha256'],
                            'quarantinePath':active_quarantine['path']})
                    mutation_attempted = True
                    if canonical_jar:
                        def captured_quiescence():
                            need(canonical_publication_refs(root, active) == candidate['publicationReferences'],
                                 'PUBLICATION_REFERENCE_CHANGED_RETAIN_QUARANTINE')
                            return quiescence(Path(root) / 'verification' / active / 'checkout', active, candidate['ownerToken'])
                        result = remove_canonical_jar(root, candidate['target'], active_quarantine, quiescence=captured_quiescence)
                    else:
                        result = remove_duplicate(root, candidate['target'],quarantine=active_quarantine)
                    deleted.append(result)
                    record({'phase': 'DELETE_FINISHED', **result})
            record({'phase': 'FINISHED', 'deletedFiles': len(deleted)})
        except (RetirementError, OSError, ValueError, KeyError, TypeError, tarfile.TarError, EOFError) as error:
            failure = str(error) if isinstance(error, RetirementError) else type(error).__name__
            record({'phase': 'FAILED_OR_UNKNOWN', 'release': active, 'reason': failure,
                    'completedDeletions': len(deleted), 'mutationAttempted': mutation_attempted,
                    'quarantinePath':active_quarantine['path'] if active_quarantine else None})
        after = os.statvfs(root)
    return {'schemaVersion': 1, 'kind': kind + '-receipt', 'current': expected_current, 'identity': identity,
            'status': 'FAILED_OR_UNKNOWN' if failure else 'REMOVED' if deleted else 'NO_ACTION',
            'requestSha256': request_sha256, 'planSha256': plan_sha256, 'deleted': deleted, 'failure': failure,
            'mutationAttempted': mutation_attempted, 'lastAttemptedRelease': active,
            'lastQuarantinePath':active_quarantine['path'] if active_quarantine else None,
            'retainedQuarantinePaths':[row['path'] for row in quarantines
                                       if (Path(root)/row['path']).exists() or (Path(root)/row['path']).is_symlink()],
            'journalSha256': digest_bytes(journal_path.read_bytes()),
            'availableBytesBefore': before.f_bavail * before.f_frsize, 'availableBytesAfter': after.f_bavail * after.f_frsize,
            'inboxKeepersPreserved': not mutation_attempted if canonical_jar else failure is None,
            **({'binaryDisposition': 'FAILED_OR_UNKNOWN' if failure else 'RETIRED' if deleted else 'UNCHANGED',
                'binaryRebuildByteIdentityClaimed': False, 'skipped': prepared_plan['skipped'],
                'testsRunByRetirement': False} if canonical_jar else {}),
            'sourceArchivesDataAndReportsHaveNoDeletionApi': True}


@contextmanager
def held_public_layer_archive(root):
    """Authenticate the public upstream tar without extracting or deleting it."""
    root = Path(root)
    path = root / 'build-inputs/buildkit-v0.34.2' / (PUBLIC_ARCHIVE_SHA + '.tar')
    with held_file(root, path, PUBLIC_ARCHIVE_BYTES) as (stream, signature):
        need(signature[6] == PUBLIC_ARCHIVE_BYTES and hash_stream(stream, PUBLIC_ARCHIVE_BYTES) == PUBLIC_ARCHIVE_SHA,
             'EXACT_PUBLIC_UPSTREAM_ARCHIVE_REQUIRED')
        stream.seek(0); seen, layers, total = set(), {}, 0
        with tarfile.open(fileobj=stream, mode='r:') as archive:
            for member in archive:
                name = Path(member.name); total += member.size
                need(len(seen) < 256 and member.name not in seen and member.isfile()
                     and not name.is_absolute() and '..' not in name.parts and '\\' not in member.name
                     and name.as_posix() == member.name and 0 <= member.size <= PUBLIC_ARCHIVE_BYTES
                     and total <= PUBLIC_ARCHIVE_BYTES, 'BOUNDED_REGULAR_PUBLIC_ARCHIVE_MEMBERS_REQUIRED')
                seen.add(member.name)
                if len(name.parts) != 3 or name.parts[:2] != ('blobs', 'sha256') or name.name not in PUBLIC_LAYERS:
                    continue
                need(member.size == PUBLIC_LAYERS[name.name], 'PUBLIC_LAYER_TAR_SIZE_CHANGED')
                checksum = hashlib.sha256(); count = 0
                with archive.extractfile(member) as layer:
                    for block in iter(lambda: layer.read(1024 * 1024), b''):
                        count += len(block); need(count <= member.size, 'PUBLIC_LAYER_TAR_BYTE_LIMIT'); checksum.update(block)
                need(count == member.size and checksum.hexdigest() == name.name, 'PUBLIC_LAYER_TAR_BYTES_CHANGED')
                layers[name.name] = member.size
        need(layers == PUBLIC_LAYERS, 'ALL_FOUR_PUBLIC_UPSTREAM_LAYERS_REQUIRED')
        proof = {'path': path.relative_to(root).as_posix(), 'metadata': signature,
                 'sha256': PUBLIC_ARCHIVE_SHA, 'bytes': PUBLIC_ARCHIVE_BYTES,
                 'layers': [{'sha256': sha, 'bytes': size} for sha, size in sorted(layers.items())]}
        yield proof
        need(hash_stream(stream, PUBLIC_ARCHIVE_BYTES) == PUBLIC_ARCHIVE_SHA, 'PUBLIC_UPSTREAM_ARCHIVE_CHANGED_AFTER_ACTION')


def public_layer_archive(root):
    with held_public_layer_archive(root) as proof:
        return proof


def admit_public_layer_attempt(root, request, row, quiescence):
    tag = row['release']
    need(tag in PUBLIC_LAYER_TAGS and APPROVED_OLD.get(tag) == row['commit'], 'FIXED_PUBLIC_LAYER_ATTEMPT_REQUIRED')
    admitted = admit_historical_controls(root, request, row)
    need(callable(quiescence) and quiescence(Path(root) / 'verification' / tag / 'checkout', tag,
         admitted['evidence']['ownerToken']) is None, 'STRICT_PUBLIC_LAYER_QUIESCENCE_REQUIRED')
    tools = Path(root) / 'inbox' / tag / 'candidate-build-tools/tools.json'
    with held_file(root, tools, MAX_CONTROL) as (stream, signature):
        raw = stream.read(MAX_CONTROL + 1)
        need(digest_bytes(raw) == APPROVED_BUILDER_TOOLS[tag], 'ORIGINAL_PUBLIC_LAYER_TOOL_OWNER_REQUIRED')
        tools_proof = {'path': tools.relative_to(root).as_posix(), 'metadata': signature,
                       'bytes': len(raw), 'sha256': digest_bytes(raw)}
    return {'context': admitted['context'], 'jenkinsResult': admitted['evidence']['jenkinsResult'],
            'controls': admitted['controls'], 'sourceArchive': admitted['sourceArchive'],
            'ownerToken': admitted['evidence']['ownerToken'], 'tools': tools_proof}


def public_layer_quiescence(root, cleanup, original):
    """Keep the original process gate and also exclude inbox tool bind mounts."""
    def check(checkout, tag, token):
        need(original(checkout, tag, token) is None, 'STRICT_PUBLIC_LAYER_QUIESCENCE_REQUIRED')
        public = Path(root) / 'inbox' / tag / 'candidate-build-tools'
        for _cid, _running, _restarting, _pid, _release, _token, mounts in cleanup.docker_snapshot():
            for mount in mounts:
                if mount.get('Type') != 'bind' or not mount.get('Source'): continue
                source = Path(mount['Source'])
                need(not (source == public or source.is_relative_to(public) or public.is_relative_to(source)),
                     'CONTAINER_REFERENCES_PUBLIC_TOOL_INPUTS')
    return check


def plan_public_layers(root, raw_request, *, request_sha256, expected_current, identity, quiescence):
    request = approved_request(raw_request, request_sha256, expected_current, identity)
    accepted, skipped, archive_proof, keeper = [], [], None, None
    rows = {row['release']: row for row in request['candidates'] if row['release'] in PUBLIC_LAYER_TAGS}
    with controller_lock(root):
        try:
            need(PUBLIC_LAYER_KEEPER in rows, 'AUTHENTICATED_PUBLIC_LAYER_KEEPER_ATTEMPT_REQUIRED')
            with attempt_lock(root, PUBLIC_LAYER_KEEPER), held_public_layer_archive(root) as archive:
                keeper = admit_public_layer_attempt(root, request, rows[PUBLIC_LAYER_KEEPER], quiescence)
                # All four real ECS keepers must exist and match upstream first.
                for sha, size in PUBLIC_LAYERS.items():
                    path = Path(root) / 'inbox' / PUBLIC_LAYER_KEEPER / 'candidate-build-tools/official-oci/blobs/sha256' / sha
                    with held_file(root, path, MAX_JAR) as (stream, signature):
                        need(signature[6] == size and hash_stream(stream) == sha, 'ALL_FOUR_REAL_ECS_LAYER_KEEPERS_REQUIRED')
                archive_proof = archive
                for tag, row in rows.items():
                    if tag == PUBLIC_LAYER_KEEPER: continue
                    try:
                        with attempt_lock(root, tag):
                            attempt = admit_public_layer_attempt(root, request, row, quiescence)
                            targets = [describe_duplicate(root, tag, sha, size, kind=PUBLIC_LAYER_KIND)
                                       for sha, size in PUBLIC_LAYERS.items()]
                            accepted.append({**attempt, 'targets': targets})
                    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, EOFError) as error:
                        skipped.append({'release': tag, 'reason': str(error) if isinstance(error, RetirementError) else type(error).__name__})
        except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, EOFError) as error:
            # No target is usable if the complete archive/keeper proof failed.
            accepted, archive_proof, keeper = [], None, None
            skipped.append({'release': PUBLIC_LAYER_KEEPER, 'reason': str(error) if isinstance(error, RetirementError) else type(error).__name__})
    result = {'schemaVersion': 1, 'kind': PUBLIC_KIND + '-plan', 'current': expected_current, 'identity': identity,
              'requestSha256': request_sha256, 'archive': archive_proof, 'keeper': keeper,
              'candidates': accepted, 'skipped': skipped, 'deletionPerformed': False,
              'candidateBytes': sum(target['bytes'] for row in accepted for target in row['targets']),
              'candidateAllocatedBytes': sum(target['allocatedBytes'] for row in accepted for target in row['targets']),
              'upstreamTarAndKeeper117Preserved': True, 'directoriesImagesAndBusinessDataPreserved': True}
    need(len(canonical(result)) <= MAX_CONTROL, 'BOUNDED_PUBLIC_LAYER_PLAN_REQUIRED')
    return result


def apply_public_layers(root, raw_request, prepared, *, request_sha256, plan_sha256, expected_current, identity, quiescence):
    request = approved_request(raw_request, request_sha256, expected_current, identity)
    need(type(prepared) is dict and digest_bytes(canonical(prepared)) == plan_sha256
         and prepared.get('kind') == PUBLIC_KIND + '-plan' and prepared.get('current') == expected_current
         and prepared.get('identity') == identity and prepared.get('requestSha256') == request_sha256
         and prepared.get('deletionPerformed') is False and prepared.get('upstreamTarAndKeeper117Preserved') is True,
         'EXACT_PUBLIC_LAYER_PLAN_REQUIRED')
    selected = prepared.get('candidates'); rows = {row['release']: row for row in request['candidates']}
    need(type(selected) is list and len(selected) <= len(PUBLIC_LAYER_TAGS) - 1
         and all(type(row) is dict and type(row.get('context')) is dict for row in selected), 'BOUNDED_PUBLIC_LAYER_SELECTION_REQUIRED')
    tags = [row['context']['release'] for row in selected]
    need(len(tags) == len(set(tags)) and set(tags) <= (set(rows) & PUBLIC_LAYER_TAGS) - {PUBLIC_LAYER_KEEPER}
         and all(type(row.get('targets')) is list and len(row['targets']) == len(PUBLIC_LAYERS)
                 and {target.get('sha256') for target in row['targets']} == set(PUBLIC_LAYERS)
                 and all(target.get('kind') == PUBLIC_LAYER_KIND for target in row['targets']) for row in selected),
         'ONLY_FOUR_FIXED_PUBLIC_LAYERS_PER_ATTEMPT')
    journal_path = Path(root) / 'inbox' / expected_current['release'] / 'native-public-layer-duplicate-journal.jsonl'
    owned_path(root, journal_path.parent, directory=True)
    deleted, quarantines, failure, active, active_quarantine, mutation_attempted = [], [], None, None, None, False
    with controller_lock(root), os.fdopen(os.open(journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as journal:
        total = 0
        def record(value):
            nonlocal total
            raw = canonical(value) + b'\n'; total += len(raw)
            need(total <= MAX_CONTROL, 'PUBLIC_LAYER_JOURNAL_LIMIT_EXCEEDED')
            journal.write(raw); journal.flush(); os.fsync(journal.fileno())
        before = os.statvfs(root)
        record({'phase': 'STARTED', 'planSha256': plan_sha256, 'requestSha256': request_sha256, 'identity': identity})
        try:
            if selected:
                need(PUBLIC_LAYER_KEEPER in rows, 'AUTHENTICATED_PUBLIC_LAYER_KEEPER_ATTEMPT_REQUIRED')
                with attempt_lock(root, PUBLIC_LAYER_KEEPER), held_public_layer_archive(root) as archive:
                    need(archive == prepared['archive'] and admit_public_layer_attempt(root, request,
                         rows[PUBLIC_LAYER_KEEPER], quiescence) == prepared['keeper'], 'PUBLIC_LAYER_KEEPER_OR_ARCHIVE_CHANGED_AFTER_PLAN')
                    for candidate in selected:
                        active, active_quarantine = candidate['context']['release'], None
                        with attempt_lock(root, active):
                            need(admit_public_layer_attempt(root, request, rows[active], quiescence)
                                 == {key: value for key, value in candidate.items() if key != 'targets'}, 'PUBLIC_LAYER_ATTEMPT_CHANGED_AFTER_PLAN')
                            need([describe_duplicate(root, active, target['sha256'], target['bytes'], kind=PUBLIC_LAYER_KIND)
                                  for target in candidate['targets']] == candidate['targets'], 'ALL_FOUR_PUBLIC_LAYER_COPIES_CHANGED_AFTER_PLAN')
                            for target in candidate['targets']:
                                active_quarantine = None
                                need(quiescence(Path(root) / 'verification' / active / 'checkout', active, candidate['ownerToken']) is None
                                     and quiescence(Path(root) / 'verification' / PUBLIC_LAYER_KEEPER / 'checkout',
                                         PUBLIC_LAYER_KEEPER, prepared['keeper']['ownerToken']) is None, 'STRICT_PUBLIC_LAYER_QUIESCENCE_REQUIRED')
                                need(describe_duplicate(root, active, target['sha256'], target['bytes'], kind=PUBLIC_LAYER_KIND) == target,
                                     'PUBLIC_LAYER_BYTES_CHANGED_AFTER_PLAN')
                                active_quarantine = reserve_quarantine(root, expected_current['release']); quarantines.append(active_quarantine)
                                record({'phase': 'DELETE_STARTED', 'release': active, 'path': target['path'],
                                        'keeperPath': target['keeper']['path'], 'sha256': target['sha256'], 'quarantinePath': active_quarantine['path']})
                                mutation_attempted = True
                                result = remove_duplicate(root, target, quarantine=active_quarantine); deleted.append(result)
                                record({'phase': 'DELETE_FINISHED', **result})
            record({'phase': 'FINISHED', 'deletedFiles': len(deleted)})
        except Exception as error:
            failure = str(error) if isinstance(error, RetirementError) else type(error).__name__
            record({'phase': 'FAILED_OR_UNKNOWN', 'release': active, 'reason': failure,
                    'completedDeletions': len(deleted), 'mutationAttempted': mutation_attempted,
                    'quarantinePath': active_quarantine['path'] if active_quarantine else None})
        after = os.statvfs(root)
    return {'schemaVersion': 1, 'kind': PUBLIC_KIND + '-receipt', 'current': expected_current, 'identity': identity,
            'status': 'FAILED_OR_UNKNOWN' if failure else 'REMOVED' if deleted else 'NO_ACTION',
            'requestSha256': request_sha256, 'planSha256': plan_sha256, 'deleted': deleted, 'failure': failure,
            'mutationAttempted': mutation_attempted, 'lastAttemptedRelease': active,
            'lastQuarantinePath': active_quarantine['path'] if active_quarantine else None,
            'retainedQuarantinePaths': [row['path'] for row in quarantines if (Path(root) / row['path']).exists() or (Path(root) / row['path']).is_symlink()],
            'journalSha256': digest_bytes(journal_path.read_bytes()), 'skipped': prepared['skipped'],
            'availableBytesBefore': before.f_bavail * before.f_frsize, 'availableBytesAfter': after.f_bavail * after.f_frsize,
            'upstreamTarAndKeeper117Preserved': failure is None, 'directoriesImagesAndBusinessDataPreserved': True,
            'testsRunByRetirement': False}


def generated_image_archive_path(root, tag):
    need(type(tag) is str and tag in APPROVED_OLD, 'ONLY_REVIEWED_GENERATED_PUBLIC_ARCHIVE_PATHS_ALLOWED')
    return Path(root) / 'inbox' / tag / 'candidate-build-tools/official-image.tar'


def describe_generated_image_archive_cache(root, tag):
    path = generated_image_archive_path(root, tag)
    with held_file(root, path, MAX_SOURCE_ARCHIVE) as (stream, signature):
        need(0 < signature[6] <= MAX_SOURCE_ARCHIVE, 'BOUNDED_GENERATED_PUBLIC_ARCHIVE_REQUIRED')
        return {'kind': GENERATED_CACHE_KIND, 'release': tag, 'path': path.relative_to(root).as_posix(),
                'metadata': signature, 'sha256': hash_stream(stream, MAX_SOURCE_ARCHIVE),
                'bytes': signature[6], 'allocatedBytes': signature[9]}


def remove_generated_image_archive_cache(root, descriptor, seed, quarantine=None):
    """Retire a rebuildable import cache, NOT a byte-identical seed copy."""
    need(type(descriptor) is dict and set(descriptor) == {'kind', 'release', 'path', 'metadata', 'sha256', 'bytes', 'allocatedBytes'}
         and descriptor['kind'] == GENERATED_CACHE_KIND, 'EXACT_GENERATED_CACHE_DESCRIPTOR_REQUIRED')
    root = Path(root); target = generated_image_archive_path(root, descriptor['release'])
    need(describe_generated_image_archive_cache(root, descriptor['release']) == descriptor, 'GENERATED_CACHE_CHANGED_AFTER_PLAN')
    quarantine = reserve_quarantine(root) if quarantine is None else quarantine
    need(type(quarantine) is dict and set(quarantine) == {'directory', 'path', 'directoryIdentity'}, 'EXACT_PRIVATE_QUARANTINE_REQUIRED')
    relative = Path(quarantine['directory']); parts = relative.parts
    need((len(parts) == 1 or len(parts) == 3 and parts[0] == 'inbox' and TAG.fullmatch(parts[1]))
         and re.fullmatch(r'native-jar-quarantine-[a-f0-9]{24}', parts[-1])
         and quarantine['path'] == (relative / 'candidate-app.jar').as_posix(), 'QUARANTINE_OUTSIDE_PRIVATE_ALLOWLIST')
    private = owned_path(root, root / relative, directory=True)
    with held_public_layer_archive(root) as actual_seed, os.fdopen(os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as copy:
        need(actual_seed == seed, 'FIXED_PUBLIC_SEED_CHANGED_AFTER_PLAN')
        copy_info = metadata(os.fstat(copy.fileno()))
        need(copy_info == descriptor['metadata'] and copy_info[:2] != seed['metadata'][:2]
             and hash_stream(copy, MAX_SOURCE_ARCHIVE) == descriptor['sha256'], 'GENERATED_CACHE_CHANGED_BEFORE_CAPTURE')
        stack = [os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]; qfd = None
        try:
            qfd = os.open(private, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            def private_identity():
                value, linked = os.fstat(qfd), private.lstat()
                need([value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid]
                     == [linked.st_dev, linked.st_ino, linked.st_mode, linked.st_uid, linked.st_gid]
                     == quarantine['directoryIdentity'] and stat.S_IMODE(value.st_mode) == 0o700,
                     'PRIVATE_QUARANTINE_MOVED')
            private_identity(); need(not os.listdir(qfd), 'PRIVATE_QUARANTINE_ALREADY_OCCUPIED')
            device = os.fstat(stack[0]).st_dev
            for part in target.relative_to(root).parts[:-1]:
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=stack[-1]); stack.append(fd)
                info = os.fstat(fd)
                need(info.st_uid == os.getuid() and info.st_dev == device and not info.st_mode & 0o022, 'DELETION_ANCESTOR_CHANGED')
            need(metadata(os.stat(target.name, dir_fd=stack[-1], follow_symlinks=False)) == copy_info
                 == metadata(os.fstat(copy.fileno())), 'GENERATED_CACHE_MOVED_BEFORE_CAPTURE')
            _capture_no_replace(stack[-1], target.name, qfd, 'candidate-app.jar'); os.fsync(stack[-1]); os.fsync(qfd)
            captured = metadata(os.stat('candidate-app.jar', dir_fd=qfd, follow_symlinks=False))
            need(captured == metadata(os.fstat(copy.fileno())) and captured[:2] == copy_info[:2]
                 and captured[:2] != seed['metadata'][:2] and _renamed_copy_matches(copy_info, captured), 'UNEXPECTED_CAPTURED_INODE_RETAINED')
            need(hash_stream(copy, MAX_SOURCE_ARCHIVE) == descriptor['sha256']
                 and metadata((root / seed['path']).lstat()) == seed['metadata'], 'PUBLIC_SEED_OR_CAPTURE_CHANGED_RETAIN_QUARANTINE')
            need(not target.exists() and not target.is_symlink(), 'ORIGINAL_TARGET_REAPPEARED_RETAIN_QUARANTINE')
            private_identity()
            need(os.listdir(qfd) == ['candidate-app.jar'] and metadata(os.stat('candidate-app.jar', dir_fd=qfd, follow_symlinks=False))
                 == captured == metadata(os.fstat(copy.fileno())), 'CAPTURE_MOVED_RETAIN_QUARANTINE')
            os.unlink('candidate-app.jar', dir_fd=qfd); os.fsync(qfd)
            need(not os.listdir(qfd) and not target.exists() and not target.is_symlink(), 'GENERATED_CACHE_REMOVAL_NOT_CONFIRMED')
        finally:
            if qfd is not None: os.close(qfd)
            for fd in reversed(stack): os.close(fd)
    return {'path': descriptor['path'], 'bytes': descriptor['bytes'], 'allocatedBytes': descriptor['allocatedBytes'],
            'sha256': descriptor['sha256'], 'quarantinePath': quarantine['path'], 'capturedInodeVerified': True,
            'publicSeedVerifiedAfter': True, 'sameBytesAsSeedClaimed': False}


def admit_generated_image_archive_attempt(root, request, row, quiescence):
    admitted = admit_historical_controls(root, request, row, builder_helpers=True)
    context, evidence = admitted['context'], admitted['evidence']; tag = context['release']
    need(APPROVED_OLD.get(tag) == context['commit'] and callable(quiescence)
         and quiescence(Path(root) / 'verification' / tag / 'checkout', tag, evidence['ownerToken']) is None,
         'STRICT_GENERATED_PUBLIC_CACHE_QUIESCENCE_REQUIRED')
    path = Path(root) / 'inbox' / tag / 'candidate-build-tools/tools.json'
    with held_file(root, path, MAX_CONTROL) as (stream, signature):
        raw = stream.read(MAX_CONTROL + 1); tools = decode(raw)
        need(digest_bytes(raw) == APPROVED_BUILDER_TOOLS.get(tag), 'ORIGINAL_GENERATED_CACHE_TOOL_OWNER_REQUIRED')
        same_context(tools, context)
        helpers = admitted['sourceArchive']['builderHelperSha256']
        need(tools.get('status') == 'PREPARED' and tools.get('identity') == request['identity']
             and tools.get('helperSha256') == helpers['compact-build-resources.py']
             and tools.get('imageInputsHelperSha256') == helpers['compact-image-inputs.py'], 'FIXED_GENERATED_CACHE_PRODUCER_REQUIRED')
        tool_proof = {'path': path.relative_to(root).as_posix(), 'bytes': len(raw), 'sha256': digest_bytes(raw), 'metadata': signature}
    return {'context': context, 'ownerToken': evidence['ownerToken'], 'jenkinsResult': evidence['jenkinsResult'],
            'controls': admitted['controls'], 'sourceArchive': admitted['sourceArchive'], 'tools': tool_proof,
            'rebuildBasis': {'protocol': 'FIXED_SOURCE_PUBLIC_OCI_IMPORT_CACHE_V1',
                'producer': 'script/docker/compact-build-resources.py:monitored_tar_file',
                'producerSha256': helpers['compact-build-resources.py'],
                'inputHelperSha256': helpers['compact-image-inputs.py'], 'publicInputSha256': PUBLIC_ARCHIVE_SHA,
                'publicInputBytes': PUBLIC_ARCHIVE_BYTES, 'sameBytesAsSeedClaimed': False},
            'target': describe_generated_image_archive_cache(root, tag)}


def plan_generated_image_archives(root, raw_request, *, request_sha256, expected_current, identity, quiescence):
    request = approved_request(raw_request, request_sha256, expected_current, identity)
    accepted, skipped, seed = [], [], None
    with controller_lock(root):
        try:
            with held_public_layer_archive(root) as actual_seed:
                seed = actual_seed
                for row in request['candidates']:
                    try:
                        with attempt_lock(root, row['release']):
                            accepted.append(admit_generated_image_archive_attempt(root, request, row, quiescence))
                    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, EOFError) as error:
                        skipped.append({'release': row['release'], 'reason': str(error) if isinstance(error, RetirementError) else type(error).__name__})
        except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, EOFError) as error:
            accepted, seed = [], None
            skipped.append({'release': None, 'reason': str(error) if isinstance(error, RetirementError) else type(error).__name__})
    result = {'schemaVersion': 1, 'kind': GENERATED_KIND + '-plan', 'current': expected_current, 'identity': identity,
              'requestSha256': request_sha256, 'seed': seed, 'candidates': accepted, 'skipped': skipped,
              'candidateBytes': sum(row['target']['bytes'] for row in accepted),
              'candidateAllocatedBytes': sum(row['target']['allocatedBytes'] for row in accepted),
              'deletionPerformed': False, 'publicInputsDirectoriesImagesAndBusinessDataPreserved': True, 'sameBytesAsSeedClaimed': False}
    need(len(canonical(result)) <= MAX_CONTROL, 'BOUNDED_GENERATED_PUBLIC_CACHE_PLAN_REQUIRED')
    return result


def apply_generated_image_archives(root, raw_request, prepared, *, request_sha256, plan_sha256, expected_current, identity, quiescence):
    request = approved_request(raw_request, request_sha256, expected_current, identity)
    need(type(prepared) is dict and digest_bytes(canonical(prepared)) == plan_sha256
         and prepared.get('kind') == GENERATED_KIND + '-plan' and prepared.get('current') == expected_current
         and prepared.get('identity') == identity and prepared.get('requestSha256') == request_sha256
         and prepared.get('deletionPerformed') is False and prepared.get('sameBytesAsSeedClaimed') is False,
         'EXACT_GENERATED_PUBLIC_CACHE_PLAN_REQUIRED')
    rows = {row['release']: row for row in request['candidates']}; selected = prepared.get('candidates')
    need(type(selected) is list and len(selected) <= len(rows)
         and all(type(row) is dict and type(row.get('context')) is dict for row in selected), 'BOUNDED_GENERATED_CACHE_SELECTION_REQUIRED')
    tags = [row['context']['release'] for row in selected]
    need(len(tags) == len(set(tags)) and set(tags) <= set(rows), 'GENERATED_CACHE_SELECTED_TAG_DRIFT')
    journal_path = Path(root) / 'inbox' / expected_current['release'] / 'native-generated-public-image-archive-journal.jsonl'
    owned_path(root, journal_path.parent, directory=True)
    deleted, quarantines, failure, active, current_q, mutation_attempted = [], [], None, None, None, False
    with controller_lock(root), os.fdopen(os.open(journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as journal:
        total = 0
        def record(value):
            nonlocal total
            raw = canonical(value) + b'\n'; total += len(raw); need(total <= MAX_CONTROL, 'GENERATED_CACHE_JOURNAL_LIMIT_EXCEEDED')
            journal.write(raw); journal.flush(); os.fsync(journal.fileno())
        before = os.statvfs(root)
        record({'phase': 'STARTED', 'planSha256': plan_sha256, 'requestSha256': request_sha256})
        try:
            for candidate in selected:
                active, current_q = candidate['context']['release'], None
                with attempt_lock(root, active):
                    need(admit_generated_image_archive_attempt(root, request, rows[active], quiescence) == candidate,
                         'GENERATED_PUBLIC_CACHE_CHANGED_AFTER_PLAN')
                    current_q = reserve_quarantine(root, expected_current['release']); quarantines.append(current_q)
                    record({'phase': 'DELETE_STARTED', 'release': active, 'path': candidate['target']['path'],
                            'sha256': candidate['target']['sha256'], 'quarantinePath': current_q['path']})
                    mutation_attempted = True
                    value = remove_generated_image_archive_cache(root, candidate['target'], prepared['seed'], quarantine=current_q)
                    deleted.append(value); record({'phase': 'DELETE_FINISHED', **value})
            record({'phase': 'FINISHED', 'deletedFiles': len(deleted)})
        except Exception as error:
            failure = str(error) if isinstance(error, RetirementError) else type(error).__name__
            record({'phase': 'FAILED_OR_UNKNOWN', 'release': active, 'reason': failure,
                    'quarantinePath': current_q['path'] if current_q else None, 'completedDeletions': len(deleted)})
        after = os.statvfs(root)
    return {'schemaVersion': 1, 'kind': GENERATED_KIND + '-receipt', 'current': expected_current, 'identity': identity,
            'status': 'FAILED_OR_UNKNOWN' if failure else 'REMOVED' if deleted else 'NO_ACTION', 'deleted': deleted,
            'requestSha256': request_sha256, 'planSha256': plan_sha256, 'failure': failure, 'mutationAttempted': mutation_attempted,
            'lastAttemptedRelease': active, 'lastQuarantinePath': current_q['path'] if current_q else None,
            'retainedQuarantinePaths': [row['path'] for row in quarantines if (Path(root) / row['path']).exists() or (Path(root) / row['path']).is_symlink()],
            'journalSha256': digest_bytes(journal_path.read_bytes()), 'skipped': prepared['skipped'],
            'availableBytesBefore': before.f_bavail * before.f_frsize, 'availableBytesAfter': after.f_bavail * after.f_frsize,
            'publicInputsDirectoriesImagesAndBusinessDataPreserved': failure is None, 'sameBytesAsSeedClaimed': False,
            'testsRunByRetirement': False}


def private_bytes(root, path, maximum=MAX_CONTROL):
    with held_file(root, path, maximum) as (stream, info):
        need(stat.S_IMODE(info[2]) == 0o600, 'PRIVATE_CONTROL_MODE_REQUIRED')
        raw = stream.read(maximum + 1)
        need(len(raw) == info[6], 'CONTROL_READ_SIZE_DRIFT')
        return raw


def write_new(path, value):
    need(not path.exists() and not path.is_symlink() and path.parent.resolve(strict=True) == path.parent,
         'FRESH_CONTROL_OUTPUT_REQUIRED')
    raw = canonical(value); need(0 < len(raw) <= MAX_CONTROL, 'CONTROL_OUTPUT_BOUND_EXCEEDED')
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return {'file': path.name, 'bytes': len(raw), 'sha256': digest_bytes(raw)}


def fixed_current_source(root, args):
    """Authenticate every import against the current committed source archive."""
    root = Path(root); inbox = root / 'inbox' / args.tag
    source = inbox / ('source.tar.gz' if args.mode == 'Verified' else 'cleanup-source.tar.gz')
    own = Path(__file__).absolute()
    need(own == inbox / 'retire-failed-native-jar-duplicates.py', 'FIXED_CURRENT_INBOX_EXECUTOR_REQUIRED')
    paths = {'script/jenkins/retire-failed-native-jar-duplicates.py': own,
             'script/jenkins/cleanup-ecs-builds.py': inbox / 'cleanup-ecs-builds.py',
             'script/jenkins/verify-remote.py': inbox / 'verify-remote.py',
             'script/docker/compact-build-resources.py': inbox / 'compact-build-resources.py'}
    expected = {}
    for name, path in paths.items():
        raw = private_bytes(root, path, 1024 ** 2); expected[name] = digest_bytes(raw)
    with held_file(root, source, MAX_SOURCE_ARCHIVE) as (stream, _info):
        need(hash_stream(stream, MAX_SOURCE_ARCHIVE) == args.source_sha256, 'FIXED_CURRENT_SOURCE_SHA_DRIFT')
        stream.seek(0)
        class Bounded:
            def __init__(self, source): self.source, self.total = source, 0
            def read(self, size=-1):
                remain = MAX_EXPANDED_SOURCE - self.total
                raw = self.source.read(remain + 1 if size < 0 else min(size, remain + 1)); self.total += len(raw)
                need(self.total <= MAX_EXPANDED_SOURCE, 'CURRENT_SOURCE_EXPANSION_EXCEEDED'); return raw
        seen = set(); count = 0
        with gzip.GzipFile(fileobj=stream, mode='rb') as expanded, tarfile.open(fileobj=Bounded(expanded), mode='r|') as archive:
            for member in archive:
                count += 1; need(count <= 50_000 and 0 <= member.size <= 32 * 1024 ** 2, 'CURRENT_SOURCE_MEMBER_BOUND_EXCEEDED')
                if member.name not in paths: continue
                need(member.name not in seen and member.isfile() and 0 < member.size <= 1024 ** 2,
                     'UNIQUE_CURRENT_SOURCE_HELPER_REQUIRED')
                raw = archive.extractfile(member).read(1024 ** 2 + 1)
                need(len(raw) == member.size and digest_bytes(raw) == expected[member.name], 'CURRENT_HELPER_DIFFERS_FROM_FIXED_SOURCE')
                seen.add(member.name)
            need(archive.pax_headers.get('comment') == args.commit and seen == set(paths), 'CURRENT_SOURCE_COMMIT_AND_CLOSURE_REQUIRED')
    modules = {}
    for name, filename in (('cleanup', 'cleanup-ecs-builds.py'), ('verifier', 'verify-remote.py'),
                           ('builder', 'compact-build-resources.py')):
        spec = importlib.util.spec_from_file_location('native_jar_fixed_' + name, inbox / filename)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); modules[name] = module
    return modules


def admitted_current(args):
    need(sys.platform == 'linux' and os.getuid() == os.geteuid() == 1000, 'ACTUAL_ECS_UID_1000_REQUIRED')
    current = {'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256}; validate_context(current)
    root = Path(args.root)
    need(root.is_absolute() and len(root.parts) > 2 and root.parts[1] in ('home', 'srv', 'opt'), 'FIXED_ECS_CI_ROOT_REQUIRED')
    modules = fixed_current_source(root, args); cleanup, verifier = modules['cleanup'], modules['verifier']
    identity = verifier.ecs_identity(args.instance_id, args.machine_id)
    need(type(args.current_receipt_sha256) is str and SHA.fullmatch(args.current_receipt_sha256), 'CURRENT_RECEIPT_SHA_REQUIRED')
    if args.mode == 'Verified':
        path = root / 'verification' / args.tag / 'verification-receipt.json'
        raw = private_bytes(root, path); need(digest_bytes(raw) == args.current_receipt_sha256, 'CURRENT_PASS_RAW_SHA_DRIFT')
        record = decode(raw)
        need(all(record.get(key) == value for key, value in {**current, 'identity': identity, 'scope': 'source',
             'status': 'PASS', 'verificationExitCode': 0}.items()) and record.get('finishedAt'), 'CURRENT_SOURCE_PASS_REQUIRED')
        custody = {'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256, 'identity': identity,
                   'verificationReceiptSha256': digest_bytes(raw), 'reportCatalogSha256': cleanup.sha(cleanup.canonical(record['reportFiles'])),
                   'reportFiles': len(record['reportFiles']), 'reportBytes': sum(row['bytes'] for row in record['reportFiles']),
                   'originalEvidenceArchive': None}
        cleanup.evidence_binding(root, custody, identity, verifier)
    else:
        path = root / 'inbox' / args.tag / 'native-jar-duplicate-maintenance-package.json'
        raw = private_bytes(root, path); need(digest_bytes(raw) == args.current_receipt_sha256, 'MAINTENANCE_PACKAGE_RAW_SHA_DRIFT')
        package = decode(raw)
        expected = {'schema': 1, 'kind': 'doorhandle-maintenance-source', 'action': 'reclaim-build-outputs',
                    'maintenanceOnly': True, 'testsExecuted': False, 'applicationBuilt': False, **current}
        need(set(package) == set(expected) | {'sourceBytes'} and all(package.get(key) == value for key, value in expected.items())
             and type(package['schema']) is int and all(type(package[key]) is bool for key in ('maintenanceOnly', 'testsExecuted', 'applicationBuilt'))
             and type(package['sourceBytes']) is int and package['sourceBytes'] == (root / 'inbox' / args.tag / 'cleanup-source.tar.gz').stat().st_size
             and not (root / 'verification' / args.tag / 'verification-receipt.json').exists(), 'EXACT_SOURCE_ONLY_MAINTENANCE_REQUIRED')
    def quiescence(checkout, tag, token):
        cleanup.quiescent({'checkout': checkout, 'token': token}, tag, cleanup.docker_snapshot())
    return root, current, identity, quiescence, modules


def approved_request(raw, checksum, current, identity, *, canonical_jar=False):
    request = validate_request(raw, checksum, current, identity)
    need(type(canonical_jar) is bool, 'EXACT_RETIREMENT_POLICY_REQUIRED')
    approved = canonical_commit if canonical_jar else APPROVED_OLD.get
    need(all(approved(row['release']) == row['commit'] for row in request['candidates']), 'ONLY_REVIEWED_OLD_ATTEMPTS_ALLOWED')
    return request


def builder_docker(*arguments):
    result = subprocess.run(['/usr/bin/docker', *arguments], capture_output=True, timeout=20,
                            env={key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')})
    need(result.returncode == 0 and len(result.stdout) <= MAX_CONTROL, 'HISTORICAL_BUILDER_DOCKER_OPERATION_FAILED')
    return result.stdout


def builder_container_ids():
    ids = builder_docker('ps', '-aq', '--no-trunc').decode('ascii').split()
    need(len(ids) <= 256 and len(ids) == len(set(ids)) and all(SHA.fullmatch(cid) for cid in ids),
         'BOUNDED_ACTUAL_CONTAINER_IDS_REQUIRED')
    return ids


def builder_references(root, historical, descriptor, cleanup, builder, fixture=None):
    """Exclude only the fully admitted objects about to retire, never JAR guards."""
    cid = descriptor['containerId']; tag = historical['context']['release']
    retiring = {cid: 'doorhandle-builder-' + descriptor['ownerToken']}
    if fixture is not None:
        need(fixture['containerId'] != cid, 'MYSQL_FIXTURE_AND_BUILDER_ID_COLLISION')
        retiring[fixture['containerId']] = 'doorhandle-compact-fixture-' + fixture['ownerToken']
    return historical_object_references(root, historical, retiring, cleanup, builder)


def historical_object_references(root, historical, retiring, cleanup, builder, *, include_inbox=False):
    """Filter only complete admitted CID/name pairs, retaining every other guard."""
    tag = historical['context']['release']
    containers = cleanup.docker_snapshot()
    need(all(sum(row[0] == selected for row in containers) == 1 for selected in retiring), 'EXACT_HISTORICAL_RETIRING_OBJECT_MISSING')
    try:
        cleanup.quiescent({'checkout': Path(root) / 'verification' / tag / 'checkout',
                           'token': historical['evidence']['ownerToken']}, tag,
                          [row for row in containers if row[0] not in retiring],
                          **({'include_inbox': True} if include_inbox else {}))
    except ValueError as error:
        code = cleanup.failure_guard_code(error) if callable(getattr(cleanup, 'failure_guard_code', None)) else 'UNCLASSIFIED_VALUE_ERROR'
        raise RetirementError('HISTORICAL_OBJECTS_NOT_QUIESCENT_' + code) from None
    for other in builder_container_ids():
        row = builder.historical_builder_inspect(builder_docker('inspect', other)); host = row.get('HostConfig') or {}
        values = [host.get(key, '') for key in ('NetworkMode', 'PidMode', 'IpcMode')]
        values += list(host.get('VolumesFrom') or []) + list(host.get('Links') or [])
        for value in values:
            need(type(value) is str, 'CONTAINER_REFERENCE_METADATA_INVALID')
            parts = value.replace('/', ':').split(':')
            need(not any(item == name or re.fullmatch(r'[a-f0-9]+', item) and selected.startswith(item)
                         for item in parts for selected, name in retiring.items()),
                 'ANOTHER_CONTAINER_REFERENCES_HISTORICAL_BUILDER')
    # No fallback kills or cgroup writes. A still-populated retained group stops
    # maintenance even if Docker reports an exited root process.
    for selected in retiring:
        for group in (Path('/sys/fs/cgroup/system.slice') / ('docker-' + selected + '.scope'), Path('/sys/fs/cgroup/docker') / selected):
            if group.exists():
                need(group.resolve(strict=True) == group and not group.is_symlink(), 'BUILDER_CGROUP_LINK_REJECTED')
                value = (group / 'cgroup.events').read_bytes()
                need(len(value) <= 4096 and dict(line.split() for line in value.decode('ascii').splitlines()).get('populated') == '0',
                     'HISTORICAL_BUILDER_CGROUP_REMAINS_POPULATED')


def fixture_data_metadata(root, path):
    """Stat the UID999 directory entry only; never open its private contents."""
    path = Path(path); parent = owned_path(root, path.parent, directory=True)
    need(path.name == 'mysql-data' and path.resolve(strict=True) == path, 'EXACT_RETAINED_MYSQL_DIRECTORY_REQUIRED')
    fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        need(metadata(os.fstat(fd)) == metadata(parent.lstat()), 'MYSQL_DIRECTORY_PARENT_MOVED')
        value = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
        need(stat.S_ISDIR(value.st_mode) and not stat.S_ISLNK(value.st_mode), 'RETAINED_MYSQL_DATA_DIRECTORY_LINK_REJECTED')
        return [value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid]
    finally: os.close(fd)


def capture_fixture(root, request, historical, builder):
    owner, cleanup = historical['fixtureOwner'], historical['fixtureCleanup']; cid = owner.get('containerId')
    if cid is None: return None
    need(type(cid) is str and SHA.fullmatch(cid), 'ORIGINAL_MYSQL_FIXTURE_ID_REQUIRED')
    if cid not in builder_container_ids(): return None
    raw = builder_docker('inspect', cid)
    descriptor = builder.historical_mysql_fixture_descriptor(root, historical['context'], request['identity'], owner, cleanup,
        builder.historical_builder_inspect(raw), fixture_data_metadata(root, owner['dataDirectory']))
    descriptor['rawInspectSha256'] = digest_bytes(raw)
    return descriptor


def capture_recent_fixture(root, request, row, builder):
    need(RECENT_CANONICAL_ONLY.get(row['release']) == row['commit'], 'ONLY_REVIEWED_RECENT_FIXTURES_ALLOWED')
    historical = admit_historical_controls(root, request, row, builder_helpers=True, canonical_jar=True)
    source = historical['sourceArchive']; builder.recent_mysql_fixture_source(historical['context'], source)
    owner = historical['fixtureOwner']; cid = owner.get('containerId')
    need(type(cid) is str and SHA.fullmatch(cid) and cid != owner.get('sourceContainerId')
         and owner.get('dataDirectory') == historical['evidence']['work'] + '/mysql-data', 'EXACT_RECENT_MYSQL_OBJECT_REQUIRED')
    data = fixture_data_metadata(root, owner['dataDirectory'])
    need(stat.S_IMODE(data[2]) == 0o700 and data[3] == 999, 'RECENT_MYSQL_DATA_ENTRY_DIFFERS')
    fixture = None
    if cid in builder_container_ids():
        raw = builder_docker('inspect', cid)
        fixture = builder.historical_mysql_fixture_descriptor(root, historical['context'], request['identity'], owner,
            historical['fixtureCleanup'], builder.historical_builder_inspect(raw), data, source_proof=source)
        fixture['rawInspectSha256'] = digest_bytes(raw)
    return {'historical': historical, 'fixture': fixture, 'containerId': cid,
            'dataDirectory': owner['dataDirectory'], 'dataMetadata': data}


def recent_fixture_references(root, candidate, cleanup, builder):
    fixture = candidate['fixture']; tag = candidate['historical']['context']['release']
    canonical_publication_refs(root, tag)
    return historical_object_references(root, candidate['historical'],
        {fixture['containerId']: 'doorhandle-compact-fixture-' + fixture['ownerToken']}, cleanup, builder, include_inbox=True)


def plan_recent_fixtures(root, raw_request, *, request_sha256, expected_current, identity, modules):
    request = approved_request(raw_request, request_sha256, expected_current, identity, canonical_jar=True)
    accepted, absent, skipped = [], [], []
    with controller_lock(root), publication_lock(root):
        for row in request['candidates']:
            try:
                with attempt_lock(root, row['release']):
                    candidate = capture_recent_fixture(root, request, row, modules['builder'])
                    if candidate['fixture'] is None: absent.append(candidate)
                    else:
                        recent_fixture_references(root, candidate, modules['cleanup'], modules['builder'])
                        accepted.append(candidate)
            except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, EOFError) as error:
                skipped.append({'release': row['release'], 'reason': str(error) if isinstance(error, RetirementError)
                                or getattr(error, 'doorhandle_public_resource_error', False) else type(error).__name__})
    value = {'schemaVersion': 1, 'kind': 'doorhandle-recent-mysql-fixture-object-plan', 'current': expected_current,
        'identity': identity, 'requestSha256': request_sha256, 'candidates': accepted, 'absent': absent,
        'skipped': skipped, 'deletionPerformed': False, 'dataDirectoriesAndVolumesPreserved': True}
    need(len(canonical(value)) <= MAX_CONTROL, 'BOUNDED_RECENT_MYSQL_PLAN_REQUIRED')
    return value


def apply_recent_fixtures(root, raw_request, prepared, *, request_sha256, plan_sha256, expected_current, identity, modules):
    request = approved_request(raw_request, request_sha256, expected_current, identity, canonical_jar=True)
    need(digest_bytes(canonical(prepared)) == plan_sha256 and prepared.get('kind') == 'doorhandle-recent-mysql-fixture-object-plan'
         and prepared.get('current') == expected_current and prepared.get('identity') == identity
         and prepared.get('requestSha256') == request_sha256 and prepared.get('deletionPerformed') is False
         and prepared.get('skipped') == [], 'EXACT_RECENT_MYSQL_PLAN_REQUIRED')
    selected, absent = prepared.get('candidates'), prepared.get('absent'); rows = {row['release']: row for row in request['candidates']}
    need(type(selected) is list and type(absent) is list and len(selected) + len(absent) == len(rows) <= 3
         and all(type(item) is dict and type(item.get('historical')) is dict for item in selected + absent),
         'BOUNDED_RECENT_MYSQL_OBJECTS_REQUIRED')
    tags = [item['historical']['context']['release'] for item in selected + absent]
    need(len(tags) == len(set(tags)) and set(tags) == set(rows), 'RECENT_MYSQL_PLAN_TAGS_DIFFER')
    removed, failure, active = [], None, None
    journal_path = Path(root) / 'inbox' / expected_current['release'] / 'native-jar-duplicate-fixture-object-journal.jsonl'
    with controller_lock(root), publication_lock(root), os.fdopen(os.open(journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as journal:
        def record(value):
            body = canonical(value) + b'\n'; need(len(body) <= MAX_CONTROL, 'BOUNDED_RECENT_MYSQL_JOURNAL_REQUIRED')
            journal.write(body); journal.flush(); os.fsync(journal.fileno())
        record({'phase': 'STARTED', 'requestSha256': request_sha256, 'planSha256': plan_sha256})
        try:
            for candidate in absent + selected:
                active = candidate['historical']['context']['release']
                with attempt_lock(root, active):
                    observed = capture_recent_fixture(root, request, rows[active], modules['builder'])
                    need(observed == candidate, 'RECENT_MYSQL_OBJECT_OR_ORIGINALS_CHANGED_AFTER_PLAN')
                    if candidate['fixture'] is None: continue
                    fixture = candidate['fixture']
                    record({'phase': 'MYSQL_OBJECT_REMOVE_STARTED', 'release': active, 'containerId': fixture['containerId'],
                            'rawInspectSha256': fixture['rawInspectSha256'], 'dataDirectory': fixture['dataDirectory'],
                            'dataMetadata': fixture['dataMetadata']})
                    value = modules['builder'].historical_mysql_fixture_remove(fixture,
                        lambda cid: builder_docker('inspect', cid), lambda cid: builder_docker('rm', cid), builder_container_ids,
                        lambda _cid: recent_fixture_references(root, observed, modules['cleanup'], modules['builder']),
                        lambda: fixture_data_metadata(root, fixture['dataDirectory']))
                    removed.append(value); record({'phase': 'MYSQL_OBJECT_REMOVED', **value})
        except Exception as error:
            failure = {'release': active, 'reason': str(error) if isinstance(error, RetirementError)
                       or getattr(error, 'doorhandle_public_resource_error', False) else type(error).__name__}
            record({'phase': 'FAILED_OR_UNKNOWN', **failure})
        record({'phase': 'FINISHED', 'removedContainers': len(removed)})
    return {'schemaVersion': 1, 'kind': 'doorhandle-recent-mysql-fixture-object-receipt', 'current': expected_current,
        'identity': identity, 'requestSha256': request_sha256, 'planSha256': plan_sha256,
        'status': 'FAILED_OR_UNKNOWN' if failure else 'REMOVED' if removed else 'NO_ACTION',
        'removed': removed, 'alreadyAbsent': [item['containerId'] for item in absent], 'failure': failure,
        'dataDirectoriesPreserved': failure is None, 'imagesPreserved': True, 'volumesPreserved': True,
        'sourceArchivesAndReportsPreserved': True, 'jarDeletionPerformed': False, 'automaticResumeAllowed': False,
        'journalSha256': digest_bytes(private_bytes(root, journal_path))}


def capture_builder(root, request, row, builder):
    historical = admit_historical_controls(root, request, row, builder_helpers=True)
    directory = Path(root) / 'inbox' / row['release'] / 'candidate-build-tools'
    controls, raw = {}, {}
    for role, filename in (('tools', 'tools.json'), ('summary', 'resource-summary.json'),
                            ('measurement', 'official-layer-measurements.json')):
        path = directory / filename
        with held_file(root, path, MAX_CONTROL) as (stream, signature):
            content = stream.read(MAX_CONTROL + 1)
            need(0 < len(content) <= MAX_CONTROL, 'BOUNDED_ORIGINAL_BUILDER_CONTROL_REQUIRED')
            raw[role] = content
            controls[role] = {'path': path.relative_to(root).as_posix(), 'bytes': len(content),
                              'sha256': digest_bytes(content), 'metadata': signature}
    need(digest_bytes(raw['tools']) == APPROVED_BUILDER_TOOLS.get(row['release']),
         'HISTORICAL_BUILDER_TOOLS_DIFFERS_FROM_ORIGINAL_JENKINS_REFERENCE')
    summary = decode(raw['summary']); cid = summary.get('cleanup', {}).get('builderContainerId')
    need(type(cid) is str and SHA.fullmatch(cid), 'ORIGINAL_BUILDER_CONTAINER_ID_REQUIRED')
    inspected = builder_docker('inspect', cid); actual = builder.historical_builder_inspect(inspected)
    descriptor = builder.historical_builder_descriptor(root, historical['context'], request['identity'],
        raw['tools'], raw['summary'], raw['measurement'], historical['sourceArchive']['builderHelperSha256'], actual)
    fixture = capture_fixture(root, request, historical, builder)
    return {'historical': historical, 'builderControls': controls, 'descriptor': descriptor, 'fixture': fixture}, inspected


def plan_builders(root, raw_request, *, request_sha256, expected_current, identity, modules):
    request = approved_request(raw_request, request_sha256, expected_current, identity)
    accepted, skipped = [], []; builder, cleanup = modules['builder'], modules['cleanup']
    directory = Path(root) / 'inbox' / expected_current['release'] / 'native-builder-retirement-inspect'
    with controller_lock(root):
        for row in request['candidates']:
            try:
                with attempt_lock(root, row['release']):
                    value, inspected = capture_builder(root, request, row, builder)
                    builder_references(root, value['historical'], value['descriptor'], cleanup, builder, value['fixture'])
                    if not directory.exists(): directory.mkdir(mode=0o700)
                    owned_path(root, directory, directory=True)
                    path = directory / (row['release'] + '.json')
                    need(not path.exists() and not path.is_symlink(), 'FRESH_ORIGINAL_BUILDER_INSPECTION_REQUIRED')
                    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as stream:
                        stream.write(inspected); stream.flush(); os.fsync(stream.fileno())
                    value['inspection'] = {'path': path.relative_to(root).as_posix(), 'bytes': len(inspected),
                                           'sha256': digest_bytes(inspected), 'metadata': metadata(path.lstat())}
                    accepted.append(value)
            except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, EOFError) as error:
                skipped.append({'release': row['release'], 'reason': str(error) if isinstance(error, RetirementError)
                                or getattr(error, 'doorhandle_public_resource_error', False) else type(error).__name__})
    return {'schemaVersion': 1, 'kind': 'doorhandle-historical-builder-retirement-plan', 'current': expected_current,
            'identity': identity, 'requestSha256': request_sha256, 'candidates': accepted, 'skipped': skipped,
            'deletionPerformed': False, 'imagesPreserved': True, 'volumesPreserved': True, 'directoriesPreserved': True}


def apply_builders(root, raw_request, prepared, *, request_sha256, plan_sha256, expected_current, identity, modules):
    request = approved_request(raw_request, request_sha256, expected_current, identity)
    need(digest_bytes(canonical(prepared)) == plan_sha256 and prepared.get('kind') == 'doorhandle-historical-builder-retirement-plan'
         and prepared.get('current') == expected_current and prepared.get('identity') == identity
         and prepared.get('requestSha256') == request_sha256 and prepared.get('deletionPerformed') is False,
         'EXACT_HISTORICAL_BUILDER_PLAN_REQUIRED')
    selected = prepared.get('candidates'); rows = {row['release']: row for row in request['candidates']}
    need(type(selected) is list and len(selected) <= len(rows)
         and len({row['descriptor']['release'] for row in selected}) == len(selected)
         and all(row['descriptor']['release'] in rows for row in selected), 'BOUNDED_HISTORICAL_BUILDER_SELECTION_REQUIRED')
    builder, cleanup = modules['builder'], modules['cleanup']; removed, retired_fixtures, failure = [], [], None
    journal_path = Path(root) / 'inbox' / expected_current['release'] / 'native-builder-retirement-journal.jsonl'
    with controller_lock(root), os.fdopen(os.open(journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as journal:
        def record(value):
            journal.write(canonical(value) + b'\n'); journal.flush(); os.fsync(journal.fileno())
        record({'phase': 'STARTED', 'planSha256': plan_sha256, 'requestSha256': request_sha256})
        active = None
        try:
            for candidate in selected:
                active = candidate['descriptor']['release']
                with attempt_lock(root, active):
                    current, _inspected = capture_builder(root, request, rows[active], builder)
                    need(current == {key: value for key, value in candidate.items() if key != 'inspection'},
                         'HISTORICAL_BUILDER_OR_CONTROLS_CHANGED_AFTER_PLAN')
                    reference = candidate['inspection']; path = Path(root) / reference['path']
                    with held_file(root, path, MAX_CONTROL) as (stream, signature):
                        raw = stream.read(MAX_CONTROL + 1)
                        need(signature == reference['metadata'] and len(raw) == reference['bytes']
                             and digest_bytes(raw) == reference['sha256']
                             and digest_bytes(builder.encoded(builder.historical_builder_inspect(raw))) == candidate['descriptor']['inspectSha256'],
                             'FROZEN_HISTORICAL_BUILDER_INSPECTION_DRIFT')
                    fixture = current['fixture']
                    if fixture is not None:
                        record({'phase': 'MYSQL_OBJECT_REMOVE_STARTED', 'release': active, 'containerId': fixture['containerId'],
                                'inspectSha256': fixture['inspectSha256'], 'rawInspectSha256': fixture['rawInspectSha256'],
                                'dataDirectory': fixture['dataDirectory'], 'dataMetadata': fixture['dataMetadata']})
                        retired = builder.historical_mysql_fixture_remove(fixture, lambda cid: builder_docker('inspect', cid),
                            lambda cid: builder_docker('rm', cid), builder_container_ids,
                            lambda _cid: builder_references(root, current['historical'], current['descriptor'], cleanup, builder, fixture),
                            lambda: fixture_data_metadata(root, fixture['dataDirectory']))
                        retired_fixtures.append(retired); record({'phase': 'MYSQL_OBJECT_REMOVED', **retired})
                    record({'phase': 'REMOVE_STARTED', 'release': active, 'containerId': candidate['descriptor']['containerId'],
                            'inspection': reference})
                    value = builder.historical_builder_remove(candidate['descriptor'],
                        lambda cid: builder.historical_builder_inspect(builder_docker('inspect', cid)),
                        lambda cid: builder_docker('rm', cid), builder_container_ids,
                        lambda _cid: builder_references(root, current['historical'], current['descriptor'], cleanup, builder))
                    removed.append(value); record({'phase': 'REMOVED', **value})
        except Exception as error:
            failure = {'release': active, 'reason': str(error) if isinstance(error, RetirementError)
                       or getattr(error, 'doorhandle_public_resource_error', False) else type(error).__name__}
            record({'phase': 'FAILED_OR_UNKNOWN', **failure})
        record({'phase': 'FINISHED', 'removedContainers': len(removed)})
    return {'schemaVersion': 1, 'kind': 'doorhandle-historical-builder-retirement-receipt',
            'status': 'FAILED_OR_UNKNOWN' if failure else 'REMOVED' if removed else 'NO_ACTION',
            'current': expected_current, 'identity': identity, 'requestSha256': request_sha256, 'planSha256': plan_sha256,
            'removed': removed, 'retiredMysqlObjects': retired_fixtures, 'mysqlDataDirectoriesPreserved': True,
            'failure': failure, 'skipped': prepared['skipped'], 'imagesPreserved': True,
            'volumesPreserved': True, 'directoriesPreserved': True, 'jarDeletionPerformed': False}


def capture_request(root, raw_local_spec, *, local_spec_sha256, expected_current, identity, canonical_jar=False):
    spec = approved_request(raw_local_spec, local_spec_sha256, expected_current, identity, canonical_jar=canonical_jar)
    accepted, skipped = [], []
    for row in spec['candidates']:
        try:
            names = expected_control_paths(expected_current['release'], row['release']); refs = row['controls']
            need(type(refs) is dict and {'buildXml', 'release'} <= set(refs) <= set(UPLOADED_NAMES), 'ACTUAL_LOCAL_TERMINAL_AND_RELEASE_REQUIRED')
            merged = dict(refs)
            for role, ref in refs.items():
                need(type(ref) is dict and set(ref) == {'path', 'bytes', 'sha256'} and ref['path'] == names[role], 'FIXED_LOCAL_CONTROL_LOCATION_REQUIRED')
                raw = private_bytes(root, Path(root) / ref['path'])
                need(len(raw) == ref['bytes'] and digest_bytes(raw) == ref['sha256'], 'UPLOADED_ORIGINAL_LOCAL_CONTROL_DRIFT')
            for role in ('artifactPlan', 'fixtureOwner', 'fixtureCleanup'):
                path = Path(root) / names[role]
                need(path.exists() or path.is_symlink(), 'REQUIRED_ECS_CONTROL_MISSING_' + role.upper())
                raw = private_bytes(root, path)
                merged[role] = {'path': names[role], 'bytes': len(raw), 'sha256': digest_bytes(raw)}
            accepted.append({**row, 'controls': merged})
        except (RetirementError, OSError, ValueError, KeyError, TypeError) as error:
            skipped.append({'release': row['release'], 'reason': str(error) if isinstance(error, RetirementError) else type(error).__name__})
    request = {**spec, 'candidates': accepted}
    return request, skipped


# This independent allowlist never inherits the failed-native JAR candidates.
# Immutable IDs and names were observed read-only on the admitted ECS.
PYTHON_CACHE_APPROVED = {
    'ci-88-eee02f041acc': ('sha256:bb13a047fc8eef3a6f39bee137a42cc09cb43d04a56baea3ec96d049e400f0de',
        'doorhandlecatch/ci-python:ci-88-eee02f041acc-0114554bdab3',
        '6af65eac7235fc24fc8b98f7c3f8a6f86b3d27a9901400e9f9c299452a67af6f'),
    'ci-89-02644b8cabb0': ('sha256:4142687d827dac19dcb0567dce738abf59b51ece6b007db090cdc337504f2d57',
        'doorhandlecatch/ci-python:ci-89-02644b8cabb0-39d4480521f2',
        'a5140d02a3bfa235cefa388ae33e8bd3d0ba1eedbb57052ff845a617eb2f350f'),
    'ci-90-5dec4a42ba4f': ('sha256:ff99a08bb9f6e0b75f9844504ab802159004ae4dfd2135537f8411b99d8dfab6',
        'doorhandlecatch/ci-python:ci-90-5dec4a42ba4f-e8f33679de1c',
        '6f46600b75e1b494ef4ebd4fda4838d9565efacc4ebaa38ecab7b3db920e0300'),
    'ci-92-6ce63d55f407': ('sha256:345cbb7c263cbc4606fdbe17b36e6a3e7ed378fda72ff7e11e1b2588c0508cfc',
        'doorhandlecatch/ci-python:ci-92-6ce63d55f407-7250de57d776',
        'fccde5be4ed5d417ad2faa6d145c4047c19c17f34170ec3b9a1966666b1e5480'),
    'ci-94-0f482e27eacf': ('sha256:37c6b3836a0576ef8abc8af2f57d63bc5a4dd85952b8575164b6f5c325db958c',
        'doorhandlecatch/ci-python:ci-94-0f482e27eacf-3732c8e87b8d',
        'ae0a83c49f7477ff9abdda140dcb6c17e9dc311f2d4add31204eb390d7017d83'),
    'ci-95-8d8e6e3d26e9': ('sha256:51074899578138f8e8d4d3a2ff9ec214230b3bb95a436cfae59bfe29b520f1d1',
        'doorhandlecatch/ci-python:ci-95-8d8e6e3d26e9-ec29e7eb29bc',
        'cec422153bb655cb5281c946ee49cf3cfd17db19bd7bbff264938e24be9fd041'),
    'ci-96-32ee1215f215': ('sha256:c897c613928983868f829bd9dc37cec1c2ed8aad9f2764fe9e81aa2b6df2cbff',
        'doorhandlecatch/ci-python:ci-96-32ee1215f215-0a1eb0ae9d21',
        '01aa6cbc3c08f2168480afd1022b326e20eb7de4b348b4b1d5e0d776106a5c37'),
}
PYTHON_CACHE_BASE = 'sha256:d9489c281e69291fec34ee6bd470197c4c41d06fdc29a822d3a5aaad66f1b2fa'
PYTHON_CACHE_PROTECTED_IMAGES = frozenset((PYTHON_CACHE_BASE,
    'sha256:f58d59b6273e785ac0a4477f6e9b5ba1d7731c75b906c0f7b34076f1851318cc',
    'sha256:44fce696f38ba8c987c4db89954051000bbd05ffd8d8659ba15ed4a8602e937f',
    'sha256:4e8c4a575022713b56227dbf8a4df04e37bf6659e7d1828cd29a884368a1c66d'))
PYTHON_CACHE_PROTECTED_CONTAINER = 'a44d54b9a56f6d5d0e1a0f1fb6dd34c441ae424824e17fa24dc807675c629c2a'
PYTHON_CACHE_RECIPE = 'script/jenkins/prepare-ecs-tools.py'
PYTHON_CACHE_REQUIREMENTS = 'script/jenkins/python-test-requirements.txt'
PYTHON_CACHE_KIND = 'doorhandle-historical-python-build-cache'


def python_cache_owner(owner, release, identity):
    """Pure admission of the actual older pip producer, never metadata reuse."""
    need(release in PYTHON_CACHE_APPROVED and int(TAG.fullmatch(release)[1]) < 97,
         'PYTHON_CACHE_CLOSED_OLD_RELEASE_REQUIRED')
    validate_context({key: owner.get(key) for key in ('release', 'commit', 'sourceSha256')})
    need(owner['release'] == release and owner.get('identity') == identity
         and owner.get('baseImageId') == PYTHON_CACHE_BASE
         and type(owner.get('ownerToken')) is str and re.fullmatch(r'[a-f0-9]{24}', owner['ownerToken'])
         and owner.get('containerName') == 'doorhandle-ci-python-' + owner['ownerToken']
         and owner.get('diskReserveBytes') == 2 * 1024 ** 3
         and owner.get('diskOvershootBytes') == 256 * 1024 ** 2
         and owner.get('maximumGrowthBytes') == 2 * 1024 ** 3
         and type(owner.get('sourceFiles')) is dict
         and set(owner['sourceFiles']) == {PYTHON_CACHE_RECIPE, PYTHON_CACHE_REQUIREMENTS}
         and all(type(value) is str and SHA.fullmatch(value) for value in owner['sourceFiles'].values()),
         'PYTHON_CACHE_ORIGINAL_OWNER_REQUIRED')
    return owner


def python_cache_source_proof(root, owner):
    """Hash the whole retained source, and read two members without executing it."""
    root = Path(root); release = owner['release']; archive_path = root / 'inbox' / release / 'source.tar.gz'
    wanted = {}; source_signature = None
    with held_file(root, archive_path, MAX_SOURCE_ARCHIVE) as (stream, signature):
        need(hash_stream(stream, MAX_SOURCE_ARCHIVE) == owner['sourceSha256'], 'PYTHON_CACHE_SOURCE_SHA_DRIFT')
        source_signature = signature; stream.seek(0)
        class Bounded:
            def __init__(self, source): self.source, self.total = source, 0
            def read(self, size=-1):
                remaining = MAX_EXPANDED_SOURCE - self.total
                raw = self.source.read(remaining + 1 if size < 0 else min(size, remaining + 1))
                self.total += len(raw); need(self.total <= MAX_EXPANDED_SOURCE, 'PYTHON_CACHE_SOURCE_EXPANSION_BOUND')
                return raw
        with gzip.GzipFile(fileobj=stream, mode='rb') as expanded, tarfile.open(fileobj=Bounded(expanded), mode='r|') as archive:
            count = 0
            for member in archive:
                count += 1
                need(count <= 50_000 and 0 <= member.size <= 32 * 1024 ** 2, 'PYTHON_CACHE_SOURCE_MEMBER_BOUND')
                if member.name not in owner['sourceFiles']: continue
                need(member.name not in wanted and member.isfile() and 0 < member.size <= 1024 ** 2,
                     'PYTHON_CACHE_UNIQUE_SOURCE_MEMBERS_REQUIRED')
                raw = archive.extractfile(member).read(1024 ** 2 + 1)
                need(len(raw) == member.size and digest_bytes(raw) == owner['sourceFiles'][member.name],
                     'PYTHON_CACHE_SOURCE_MEMBER_SHA_DRIFT')
                wanted[member.name] = raw
            need(archive.pax_headers.get('comment') == owner['commit'] and set(wanted) == set(owner['sourceFiles']),
                 'PYTHON_CACHE_SOURCE_COMMIT_AND_CLOSURE_REQUIRED')
    files = {}
    for name, raw in wanted.items():
        path = root / 'inbox' / release / 'python-tools' / Path(name).name
        with held_file(root, path, 1024 ** 2) as (stream, signature):
            need(stream.read(1024 ** 2 + 1) == raw, 'PYTHON_CACHE_RETAINED_RECIPE_OR_REQUIREMENTS_CHANGED')
            files[name] = {'path': path.relative_to(root).as_posix(), 'metadata': signature, 'sha256': digest_bytes(raw)}
    try:
        syntax = ast.parse(wanted[PYTHON_CACHE_RECIPE]); scripts = [ast.literal_eval(node.value) for node in syntax.body
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'INSTALL' for target in node.targets)]
        need(len(scripts) == 1 and type(scripts[0]) is str, 'PYTHON_CACHE_FIXED_INSTALLER_REQUIRED')
        pins = {}
        for line in wanted[PYTHON_CACHE_REQUIREMENTS].decode('utf8').splitlines():
            value = line.strip()
            if not value or value.startswith('#'): continue
            match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9._-]*)==([0-9][A-Za-z0-9.!+_-]*)', value)
            need(match is not None, 'PYTHON_CACHE_PINNED_REQUIREMENTS_REQUIRED')
            key = re.sub(r'[-_.]+', '-', match[1]).lower()
            need(key not in pins, 'PYTHON_CACHE_DUPLICATE_REQUIREMENT'); pins[key] = match[2]
        need(0 < len(pins) <= 64, 'PYTHON_CACHE_BOUNDED_REQUIREMENTS_REQUIRED')
    except (SyntaxError, UnicodeError, RecursionError, TypeError, ValueError) as error:
        if isinstance(error, RetirementError): raise
        raise RetirementError('PYTHON_CACHE_INVALID_RETAINED_RECIPE') from None
    command = ['-I', '-B', '-c', scripts[0], json.dumps(pins, sort_keys=True)]
    return {'archive': {'path': archive_path.relative_to(root).as_posix(), 'metadata': source_signature,
                        'sha256': owner['sourceSha256']}, 'files': files,
            'installerCommandSha256': digest_bytes(canonical(command))}


def python_cache_container_descriptor(root, row, owner, source):
    """The two original binds and complete inert/stopped resource model."""
    release = owner['release']; approved = PYTHON_CACHE_APPROVED.get(release)
    need(approved is not None and row.get('Id') == approved[2] and row['Id'] != PYTHON_CACHE_PROTECTED_CONTAINER,
         'PYTHON_CACHE_EXACT_OLD_CONTAINER_REQUIRED')
    cfg = row.get('Config') or {}; host = row.get('HostConfig') or {}; labels = cfg.get('Labels') or {}; state = row.get('State') or {}
    folder = Path(root) / 'inbox' / release / 'python-tools'
    need(row.get('Image') == cfg.get('Image') == PYTHON_CACHE_BASE
         and row.get('Name') == '/' + owner['containerName']
         and labels.get('io.doorhandle.ci-tool-preparation') == owner['ownerToken']
         and labels.get('io.doorhandle.release') == release and labels.get('io.doorhandle.source') == owner['sourceSha256']
         and not labels.get('io.doorhandle.ci-tool-preparation-role')
         and cfg.get('User') == '0:0' and cfg.get('Entrypoint') == ['/usr/local/bin/python']
         and cfg.get('WorkingDir') == '/' and cfg.get('Healthcheck', {}).get('Test') == ['NONE']
         and not cfg.get('Volumes') and digest_bytes(canonical(cfg.get('Cmd'))) == source['installerCommandSha256'],
         'PYTHON_CACHE_CONTAINER_SOURCE_OR_COMMAND_DIFFERS')
    need(state.get('Status') == 'exited' and state.get('Running') is False and state.get('Restarting') is False
         and state.get('Paused') is False and state.get('Dead') is False and type(state.get('Pid')) is int and state['Pid'] == 0
         and state.get('FinishedAt') and state['FinishedAt'] != '0001-01-01T00:00:00Z',
         'PYTHON_CACHE_CONTAINER_NOT_COMPLETELY_STOPPED')
    expected_host = {'Privileged': False, 'ReadonlyRootfs': False, 'Memory': 2 * 1024 ** 3,
        'MemorySwap': 2 * 1024 ** 3, 'NanoCpus': 2 * 10 ** 9, 'PidsLimit': 256, 'NetworkMode': 'bridge',
        'PidMode': '', 'IpcMode': 'private', 'UTSMode': '', 'UsernsMode': '',
        'RestartPolicy': {'Name': 'no', 'MaximumRetryCount': 0},
        'Tmpfs': {'/tmp': 'rw,nosuid,nodev,size=268435456'},
        'LogConfig': {'Type': 'json-file', 'Config': {'max-file': '1', 'max-size': '10m'}}}
    need(all(host.get(key) == value for key, value in expected_host.items())
         and host.get('CapDrop') == ['ALL'] and host.get('SecurityOpt') == ['no-new-privileges:true']
         and all(not host.get(key) for key in ('CapAdd', 'Devices', 'DeviceRequests', 'VolumesFrom', 'Binds', 'Links', 'PortBindings')),
         'PYTHON_CACHE_CONTAINER_RESOURCE_OR_PRIVILEGE_DIFFERS')
    mounts = row.get('Mounts')
    need(type(mounts) is list and len(mounts) == 2, 'PYTHON_CACHE_EXACT_TWO_BINDS_REQUIRED')
    expected = {(str(folder / 'python-test-requirements.txt'), '/ci-input/requirements.txt'): False,
                (str(folder / 'reports'), '/ci-report'): True}
    for mount in mounts:
        pair = (mount.get('Source'), mount.get('Destination'))
        need(mount.get('Type') == 'bind' and pair in expected and mount.get('RW') is expected.pop(pair)
             and mount.get('Propagation') == 'rprivate', 'PYTHON_CACHE_FOREIGN_OR_WRITABLE_INPUT_MOUNT')
    need(not expected and type(row.get('SizeRw')) is int and 0 <= row['SizeRw'] <= 2 * 1024 ** 3,
         'PYTHON_CACHE_WRITABLE_LAYER_BOUND_REQUIRED')
    return {'release': release, 'containerId': row['Id'], 'writableBytes': row['SizeRw'],
            'inspectSha256': digest_bytes(canonical(row)), 'ownerSha256': digest_bytes(canonical(owner)), 'source': source}


def python_cache_image_descriptor(row, owner, source, references, base_layers, usage):
    release = owner['release']; approved = PYTHON_CACHE_APPROVED.get(release); cfg = row.get('Config') or {}; labels = cfg.get('Labels') or {}
    need(approved is not None and row.get('Id') == approved[0] and row['Id'] not in PYTHON_CACHE_PROTECTED_IMAGES
         and row.get('RepoTags') == [approved[1]] and row['Id'] not in references,
         'PYTHON_CACHE_EXACT_UNREFERENCED_IMAGE_REQUIRED')
    layers = row.get('RootFS', {}).get('Layers')
    need(row.get('Os') == 'linux' and row.get('Architecture') == 'amd64'
         and cfg.get('User') == '1000:1000' and cfg.get('Entrypoint') == ['/usr/local/bin/python']
         and cfg.get('Cmd') == ['--version'] and cfg.get('WorkingDir') == '/'
         and cfg.get('Healthcheck', {}).get('Test') == ['NONE'] and not cfg.get('Volumes')
         and labels.get('io.doorhandle.ci-tools') == 'python-v1'
         and labels.get('io.doorhandle.source') == owner['sourceSha256'] and labels.get('io.doorhandle.commit') == owner['commit']
         and labels.get('io.doorhandle.ci-tools-recipe-sha256') == owner['sourceFiles'][PYTHON_CACHE_RECIPE]
         and labels.get('io.doorhandle.ci-tools-requirements-sha256') == owner['sourceFiles'][PYTHON_CACHE_REQUIREMENTS]
         and type(layers) is list and len(layers) == len(base_layers) + 1 and layers[:-1] == base_layers
         and type(row.get('Size')) is int and 0 < row['Size'] <= 2 * 1024 ** 3,
         'PYTHON_CACHE_IMAGE_FIXED_RECIPE_OR_BASE_DIFFERS')
    accounting = usage.get(row['Id']) or {}
    need(accounting.get('Containers') == 0 and accounting.get('Size') == row['Size']
         and type(accounting.get('SharedSize')) is int and 0 <= accounting['SharedSize'] <= row['Size'],
         'PYTHON_CACHE_EXACT_IMAGE_DISK_ACCOUNTING_REQUIRED')
    return {'release': release, 'imageId': row['Id'], 'repoTags': row['RepoTags'],
            'uniqueBytes': row['Size'] - accounting['SharedSize'], 'inspectSha256': digest_bytes(canonical(row)),
            'ownerSha256': digest_bytes(canonical(owner)), 'source': source}


def _python_cache_projection(row, *, image=False):
    """Only public Docker metadata enters original inspection files, never Env."""
    cfg = row.get('Config') or {}; labels = cfg.get('Labels') or {}
    for entry in cfg.get('Env') or []:
        key, _, value = entry.partition('=')
        need(not value or not re.search(r'PASSWORD|PASSWD|SECRET|API_KEY|ACCESS_KEY|TOKEN|DATABASE_URL|DB_URL', key, re.I),
             'PYTHON_CACHE_SENSITIVE_ENVIRONMENT_REFUSED')
    keys = ('Id', 'RepoTags', 'Os', 'Architecture', 'Size', 'RootFS') if image else ('Id', 'Name', 'Image', 'State', 'HostConfig', 'Mounts', 'SizeRw')
    value = {key: row.get(key) for key in keys}
    value['Config'] = {key: cfg.get(key) for key in ('Image', 'User', 'Entrypoint', 'Cmd', 'WorkingDir', 'Healthcheck', 'Volumes')}
    value['Config']['Labels'] = {key: labels[key] for key in labels if key.startswith('io.doorhandle.ci-tool')
        or key in ('io.doorhandle.source', 'io.doorhandle.commit', 'io.doorhandle.release')}
    value['labelKeys'] = sorted(labels)
    return value


def _python_cache_inspect(identifier, *, image=False):
    raw = builder_docker(*(['image', 'inspect', identifier] if image else ['inspect', '--size', identifier]))
    rows = json.loads(raw)
    need(type(rows) is list and len(rows) == 1 and type(rows[0]) is dict, 'PYTHON_CACHE_SINGLE_DOCKER_OBJECT_REQUIRED')
    return _python_cache_projection(rows[0], image=image)


def _python_cache_image_ids():
    values = builder_docker('image', 'ls', '-aq', '--no-trunc').decode('ascii').split()
    need(len(values) <= 1024 and all(re.fullmatch(r'sha256:[a-f0-9]{64}', value) for value in values),
         'PYTHON_CACHE_BOUNDED_FULL_IMAGE_IDS_REQUIRED')
    return set(values)


def _python_cache_references():
    ids = builder_container_ids()
    if not ids: return []
    rows = json.loads(builder_docker('inspect', *ids))
    need(type(rows) is list and len(rows) == len(ids) and {row.get('Id') for row in rows} == set(ids),
         'PYTHON_CACHE_COMPLETE_CONTAINER_REFERENCE_SCAN_REQUIRED')
    # No environment, command, label value or business configuration is returned.
    return [{'Id': row['Id'], 'Image': row.get('Image'), 'Name': row.get('Name'),
             'HostConfig': {key: (row.get('HostConfig') or {}).get(key)
                            for key in ('VolumesFrom', 'Links', 'NetworkMode', 'PidMode', 'IpcMode')},
             'Mounts': row.get('Mounts') or []} for row in rows]


def _python_cache_usage():
    # Docker's CLI formats unique sizes to rounded text. This read-only Engine
    # endpoint retains the original integer byte accounting instead.
    import socket
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(20); connection.connect('/var/run/docker.sock')
        connection.sendall(b'GET /system/df HTTP/1.0\r\nHost: docker\r\nConnection: close\r\n\r\n')
        raw = bytearray()
        while True:
            block = connection.recv(1024 ** 2)
            if not block: break
            raw.extend(block); need(len(raw) <= 32 * 1024 ** 2, 'PYTHON_CACHE_DISK_USAGE_BOUND')
    header, body = bytes(raw).split(b'\r\n\r\n', 1)
    need(header.splitlines()[0].split()[1] == b'200', 'PYTHON_CACHE_DISK_USAGE_HTTP_FAILED')
    rows = json.loads(body).get('Images')
    need(type(rows) is list and len(rows) <= 1024, 'PYTHON_CACHE_IMAGE_USAGE_CATALOG_REQUIRED')
    return {row['Id']: {key: row.get(key) for key in ('Size', 'SharedSize', 'Containers')} for row in rows}


def _python_cache_protected():
    images = _python_cache_image_ids()
    need(PYTHON_CACHE_PROTECTED_IMAGES <= images, 'PYTHON_CACHE_GLOBAL_DEPENDENCY_MISSING')
    ids = builder_container_ids()
    need(PYTHON_CACHE_PROTECTED_CONTAINER in ids, 'PYTHON_CACHE_97_ORIGINAL_CONTAINER_MISSING')
    protected = _python_cache_inspect(PYTHON_CACHE_PROTECTED_CONTAINER)
    need(protected['Image'] == PYTHON_CACHE_BASE and protected['Config']['Labels'].get('io.doorhandle.release') == 'ci-97-abedbf81a73d',
         'PYTHON_CACHE_97_PROTECTED_IDENTITY_CHANGED')
    base = _python_cache_inspect(PYTHON_CACHE_BASE, image=True)
    layers = base.get('RootFS', {}).get('Layers')
    need(type(layers) is list and layers and all(re.fullmatch(r'sha256:[a-f0-9]{64}', layer) for layer in layers),
         'PYTHON_CACHE_PROTECTED_BASE_LAYERS_REQUIRED')
    return {'imageIds': sorted(PYTHON_CACHE_PROTECTED_IMAGES), 'container97InspectSha256': digest_bytes(canonical(protected)),
            'baseLayers': layers}


def _python_cache_owner_source(root, release, identity):
    path = Path(root) / 'inbox' / release / 'python-tools' / 'owner.json'
    raw = private_bytes(root, path); owner = python_cache_owner(decode(raw), release, identity)
    source = python_cache_source_proof(root, owner)
    source['owner'] = {'path': path.relative_to(root).as_posix(), 'sha256': digest_bytes(raw), 'metadata': metadata(path.lstat())}
    return owner, source


def _python_cache_quiescent(root, release, descriptor, references, cleanup):
    checkout = owned_path(root, Path(root) / 'verification' / release / 'checkout', directory=True)
    cleanup.process_references(checkout)
    cid = descriptor['containerId']; name = 'doorhandle-ci-python-' + descriptor['containerToken']
    for row in references:
        if row['Id'] == cid: continue
        host = row['HostConfig']
        values = list(host.get('VolumesFrom') or []) + list(host.get('Links') or [])
        values += [host.get(key) or '' for key in ('NetworkMode', 'PidMode', 'IpcMode')]
        need(not any(cid in value or name in value for value in values), 'PYTHON_CACHE_FOREIGN_CONTAINER_REFERENCE')
        for mount in row['Mounts']:
            if mount.get('Type') != 'bind': continue
            path = Path(mount.get('Source') or '/')
            need(not (path == checkout or path.is_relative_to(checkout) or checkout.is_relative_to(path)),
                 'PYTHON_CACHE_FOREIGN_CHECKOUT_BIND')


def _python_cache_available(root):
    info = os.statvfs(root)
    return info.f_bavail * info.f_frsize


def _python_cache_save_inspect(root, directory, value, *, image=False):
    identifier = value['Id'].removeprefix('sha256:')
    path = directory / (('image-' if image else 'container-') + identifier + '.json')
    binding = write_new(path, value)
    return {'path': path.relative_to(root).as_posix(), 'bytes': binding['bytes'], 'sha256': binding['sha256']}


def _python_cache_capture(root, release, identity, protected, usage, *, image=False):
    owner, source = _python_cache_owner_source(root, release, identity)
    identifier = PYTHON_CACHE_APPROVED[release][0 if image else 2]
    row = _python_cache_inspect(identifier, image=image)
    references = _python_cache_references()
    if image:
        descriptor = python_cache_image_descriptor(row, owner, source, {item['Image'] for item in references}, protected['baseLayers'], usage)
    else:
        descriptor = python_cache_container_descriptor(root, row, owner, source)
        descriptor['containerToken'] = owner['ownerToken']
    return descriptor, row, references


def plan_python_build_cache(root, *, expected_current, identity, modules):
    validate_context(expected_current); root = Path(root)
    need(int(TAG.fullmatch(expected_current['release'])[1]) > 97, 'PYTHON_CACHE_NEW_CURRENT_BUILD_REQUIRED')
    containers, images, skipped = [], [], []
    directory = root / 'inbox' / expected_current['release'] / 'native-python-build-cache-inspect'
    owned_path(root, directory.parent, directory=True)
    with controller_lock(root):
        need(not directory.exists() and not directory.is_symlink(), 'PYTHON_CACHE_FRESH_INSPECTION_DIRECTORY_REQUIRED')
        directory.mkdir(mode=0o700); protected = _python_cache_protected(); usage = _python_cache_usage()
        present_containers, present_images = set(builder_container_ids()), _python_cache_image_ids()
        for release, (image_id, _tag, cid) in PYTHON_CACHE_APPROVED.items():
            for image, identifier, present in ((False, cid, present_containers), (True, image_id, present_images)):
                try:
                    need(identifier in present, 'PYTHON_CACHE_ALREADY_ABSENT')
                    with attempt_lock(root, release):
                        descriptor, row, refs = _python_cache_capture(root, release, identity, protected, usage, image=image)
                        if not image: _python_cache_quiescent(root, release, descriptor, refs, modules['cleanup'])
                        descriptor['inspection'] = _python_cache_save_inspect(root, directory, row, image=image)
                        (images if image else containers).append(descriptor)
                except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, EOFError) as error:
                    skipped.append({'release': release, 'object': 'image' if image else 'container',
                                    'reason': str(error) if isinstance(error, RetirementError) else type(error).__name__})
        need(protected == _python_cache_protected(), 'PYTHON_CACHE_PROTECTED_INPUTS_CHANGED')
    return {'schemaVersion': 1, 'kind': PYTHON_CACHE_KIND + '-plan', 'current': expected_current, 'identity': identity,
            'containers': containers, 'images': images, 'skipped': skipped, 'protected': protected,
            'candidateContainerWritableBytes': sum(row['writableBytes'] for row in containers),
            'candidateImageUniqueBytes': sum(row['uniqueBytes'] for row in images), 'deletionPerformed': False,
            'cachedInputsPreserved': True, 'businessDataVolumesDirectoriesSourcesReportsPreserved': True,
            'testsRunByRetirement': False}


def apply_python_build_cache(root, prepared, *, plan_sha256, expected_current, identity, modules):
    validate_context(expected_current); root = Path(root)
    need(digest_bytes(canonical(prepared)) == plan_sha256 and prepared.get('kind') == PYTHON_CACHE_KIND + '-plan'
         and prepared.get('current') == expected_current and prepared.get('identity') == identity
         and prepared.get('deletionPerformed') is False, 'PYTHON_CACHE_EXACT_REVIEWED_PLAN_REQUIRED')
    for key, identifier in (('containers', 'containerId'), ('images', 'imageId')):
        rows = prepared.get(key)
        need(type(rows) is list and len(rows) <= 7 and len({row[identifier] for row in rows}) == len(rows)
             and all(row.get('release') in PYTHON_CACHE_APPROVED and row[identifier] ==
                     PYTHON_CACHE_APPROVED[row['release']][2 if key == 'containers' else 0] for row in rows),
             'PYTHON_CACHE_CLOSED_PLAN_SELECTION_REQUIRED')
    removed_containers, removed_images, failure = [], [], None
    journal_path = root / 'inbox' / expected_current['release'] / 'native-python-build-cache-journal.jsonl'
    before = _python_cache_available(root)
    with controller_lock(root), os.fdopen(os.open(journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as journal:
        def record(value):
            journal.write(canonical(value) + b'\n'); journal.flush(); os.fsync(journal.fileno())
        record({'phase': 'STARTED', 'planSha256': plan_sha256, 'availableBytes': before})
        active = None
        try:
            protected = _python_cache_protected(); need(protected == prepared['protected'], 'PYTHON_CACHE_PROTECTED_INPUTS_CHANGED')
            usage = _python_cache_usage()
            planned_images = {row['imageId'] for row in prepared['images']}
            need(not planned_images & {row['Image'] for row in _python_cache_references()},
                 'PYTHON_CACHE_PLANNED_IMAGE_NEW_REFERENCE')
            for image, candidates in ((False, prepared['containers']), (True, prepared['images'])):
                for candidate in candidates:
                    active = candidate['release']
                    with attempt_lock(root, active):
                        need(protected == _python_cache_protected(), 'PYTHON_CACHE_PROTECTED_INPUTS_CHANGED')
                        current, inspected, refs = _python_cache_capture(root, active, identity, protected, usage, image=image)
                        need(not planned_images & {row['Image'] for row in refs}, 'PYTHON_CACHE_PLANNED_IMAGE_NEW_REFERENCE')
                        need(current == {key: value for key, value in candidate.items() if key != 'inspection'},
                             'PYTHON_CACHE_OBJECT_OR_SOURCE_CHANGED_AFTER_PLAN')
                        reference = candidate['inspection']; expected_name = ('image-' if image else 'container-') + inspected['Id'].removeprefix('sha256:') + '.json'
                        path = root / 'inbox' / expected_current['release'] / 'native-python-build-cache-inspect' / expected_name
                        need(reference['path'] == path.relative_to(root).as_posix(), 'PYTHON_CACHE_EXACT_INSPECTION_PATH_REQUIRED')
                        raw = private_bytes(root, path)
                        need(len(raw) == reference['bytes'] and digest_bytes(raw) == reference['sha256']
                             and raw == canonical(inspected), 'PYTHON_CACHE_ORIGINAL_INSPECTION_DRIFT')
                        if not image: _python_cache_quiescent(root, active, current, refs, modules['cleanup'])
                        # Journal fsync precedes one last complete object/reference read.
                        record({'phase': 'IMAGE_REMOVE_STARTED' if image else 'CONTAINER_REMOVE_STARTED',
                                'release': active, 'inspection': reference})
                        again, _row, refs = _python_cache_capture(root, active, identity, protected, usage, image=image)
                        need(again == current and protected == _python_cache_protected(), 'PYTHON_CACHE_FINAL_REINSPECTION_DRIFT')
                        need(not planned_images & {row['Image'] for row in refs}, 'PYTHON_CACHE_PLANNED_IMAGE_NEW_REFERENCE')
                        if not image: _python_cache_quiescent(root, active, again, refs, modules['cleanup'])
                        identifier = current['imageId' if image else 'containerId']
                        output = builder_docker(*(['image', 'rm', identifier] if image else ['rm', identifier]))
                        need(identifier not in (_python_cache_image_ids() if image else set(builder_container_ids())),
                             'PYTHON_CACHE_REMOVAL_NOT_CONFIRMED')
                        removed = {'release': active, 'imageId' if image else 'containerId': identifier,
                                   'uniqueBytes' if image else 'writableBytes': current['uniqueBytes' if image else 'writableBytes'],
                                   'commandOutputSha256': digest_bytes(output)}
                        (removed_images if image else removed_containers).append(removed)
                        record({'phase': 'IMAGE_REMOVED' if image else 'CONTAINER_REMOVED', **removed})
            need(protected == _python_cache_protected(), 'PYTHON_CACHE_PROTECTED_INPUTS_CHANGED')
        except Exception as error:
            failure = {'release': active, 'reason': str(error) if isinstance(error, RetirementError) else type(error).__name__}
            record({'phase': 'FAILED_OR_UNKNOWN', **failure})
        after = _python_cache_available(root)
        record({'phase': 'FINISHED', 'availableBytes': after, 'removedContainers': len(removed_containers), 'removedImages': len(removed_images)})
    return {'schemaVersion': 1, 'kind': PYTHON_CACHE_KIND + '-receipt', 'current': expected_current, 'identity': identity,
            'status': 'FAILED_OR_UNKNOWN' if failure else 'REMOVED' if removed_containers or removed_images else 'NO_ACTION',
            'planSha256': plan_sha256, 'removedContainers': removed_containers, 'removedImages': removed_images,
            'failure': failure, 'skipped': prepared['skipped'], 'availableBytesBefore': before, 'availableBytesAfter': after,
            'journalSha256': digest_bytes(private_bytes(root, journal_path)), 'cachedInputsPreserved': True,
            'businessDataVolumesDirectoriesSourcesReportsPreserved': True, 'testsRunByRetirement': False,
            'automaticResumeAllowed': False}


def cli(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('capture-request', 'capture-canonical-request', 'plan-builders', 'apply-builders', 'plan', 'apply',
                                           'plan-recent-fixtures', 'apply-recent-fixtures',
                                           'plan-canonical', 'apply-canonical',
                                           'plan-public-layers', 'apply-public-layers', 'plan-generated-image-archives',
                                           'apply-generated-image-archives', 'plan-python-build-cache',
                                           'apply-python-build-cache', 'inspect'), required=True)
    parser.add_argument('--mode', choices=('Verified', 'Maintenance'), required=True)
    for name in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id', 'current-receipt-sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--local-spec-sha256'); parser.add_argument('--request-sha256'); parser.add_argument('--plan-sha256')
    args = parser.parse_args(argv)
    try:
        root, current, identity, quiescence, modules = admitted_current(args); inbox = root / 'inbox' / args.tag
        request_file = inbox / 'native-jar-duplicate-request.json'; plan_file = inbox / 'native-jar-duplicate-plan.json'
        receipt_file = inbox / 'native-jar-duplicate-receipt.json'; capture_file = inbox / 'native-jar-duplicate-capture.json'
        builder_plan_file = inbox / 'native-builder-retirement-plan.json'; builder_receipt_file = inbox / 'native-builder-retirement-receipt.json'
        public_plan_file = inbox / 'native-public-layer-duplicate-plan.json'; public_receipt_file = inbox / 'native-public-layer-duplicate-receipt.json'
        generated_plan_file = inbox / 'native-generated-public-image-archive-plan.json'
        generated_receipt_file = inbox / 'native-generated-public-image-archive-receipt.json'
        python_cache_plan_file = inbox / 'native-python-build-cache-plan.json'
        python_cache_receipt_file = inbox / 'native-python-build-cache-receipt.json'
        canonical_plan_file = inbox / 'native-jar-duplicate-canonical-plan.json'
        canonical_receipt_file = inbox / 'native-jar-duplicate-canonical-receipt.json'
        fixture_plan_file = inbox / 'native-jar-duplicate-fixture-object-plan.json'
        fixture_receipt_file = inbox / 'native-jar-duplicate-fixture-object-receipt.json'
        if args.phase in ('capture-request', 'capture-canonical-request'):
            canonical_only = args.phase == 'capture-canonical-request'
            need(not canonical_only or args.mode == 'Maintenance', 'CANONICAL_RETIREMENT_REQUIRES_MAINTENANCE')
            raw = private_bytes(root, inbox / 'native-jar-duplicate-local-spec.json')
            request, skipped = capture_request(root, raw, local_spec_sha256=args.local_spec_sha256, expected_current=current,
                                              identity=identity, canonical_jar=canonical_only)
            result = {'status': 'CAPTURED', 'current': current, 'identity': identity,
                      'request': write_new(request_file, request), 'skipped': skipped}
            result['capture'] = write_new(capture_file, result)
        elif args.phase == 'inspect':
            files = {}
            for name, path in (('request', request_file), ('plan', plan_file), ('receipt', receipt_file), ('capture', capture_file),
                               ('journal', inbox / 'native-jar-duplicate-journal.jsonl'), ('builderPlan', builder_plan_file),
                               ('builderReceipt', builder_receipt_file), ('builderJournal', inbox / 'native-builder-retirement-journal.jsonl'),
                               ('publicLayerPlan', public_plan_file), ('publicLayerReceipt', public_receipt_file),
                               ('publicLayerJournal', inbox / 'native-public-layer-duplicate-journal.jsonl'),
                               ('generatedArchivePlan', generated_plan_file), ('generatedArchiveReceipt', generated_receipt_file),
                               ('generatedArchiveJournal', inbox / 'native-generated-public-image-archive-journal.jsonl'),
                               ('pythonCachePlan', python_cache_plan_file), ('pythonCacheReceipt', python_cache_receipt_file),
                               ('pythonCacheJournal', inbox / 'native-python-build-cache-journal.jsonl'),
                               ('canonicalPlan', canonical_plan_file), ('canonicalReceipt', canonical_receipt_file),
                               ('recentFixturePlan', fixture_plan_file), ('recentFixtureReceipt', fixture_receipt_file),
                               ('recentFixtureJournal', inbox / 'native-jar-duplicate-fixture-object-journal.jsonl'),
                               ('canonicalJournal', inbox / 'native-jar-duplicate-canonical-journal.jsonl')):
                if path.exists():
                    raw = private_bytes(root, path); files[name] = {'file': path.name, 'bytes': len(raw), 'sha256': digest_bytes(raw)}
            originals = []; directory = inbox / 'native-python-build-cache-inspect'
            if directory.exists():
                owned_path(root, directory, directory=True)
                paths = sorted(directory.iterdir())
                need(len(paths) <= 64, 'BOUNDED_PYTHON_CACHE_ORIGINALS_REQUIRED')
                for path in paths:
                    need(re.fullmatch(r'(?:container|image|owner)-[a-f0-9]{64}\.json', path.name),
                         'FIXED_PYTHON_CACHE_ORIGINAL_NAME_REQUIRED')
                    raw = private_bytes(root, path)
                    originals.append({'file': 'native-python-build-cache-inspect/' + path.name,
                                      'bytes': len(raw), 'sha256': digest_bytes(raw)})
            result = {'status': 'INSPECTED', 'current': current, 'identity': identity, 'files': files,
                      'pythonCacheOriginals': originals}
        elif args.phase in ('plan-recent-fixtures', 'apply-recent-fixtures'):
            need(args.mode == 'Maintenance', 'RECENT_MYSQL_OBJECTS_REQUIRE_MAINTENANCE')
            raw = private_bytes(root, request_file)
            options = {'request_sha256': args.request_sha256, 'expected_current': current, 'identity': identity, 'modules': modules}
            if args.phase == 'plan-recent-fixtures':
                value = plan_recent_fixtures(root, raw, **options)
                result = {'status': 'PLANNED', 'current': current, 'identity': identity,
                    'plan': write_new(fixture_plan_file, value), 'skipped': value['skipped'],
                    'objectCount': len(value['candidates']), 'alreadyAbsent': len(value['absent'])}
            else:
                plan_raw = private_bytes(root, fixture_plan_file)
                need(digest_bytes(plan_raw) == args.plan_sha256, 'ORIGINAL_RECENT_MYSQL_PLAN_RAW_SHA_DRIFT')
                value = apply_recent_fixtures(root, raw, decode(plan_raw), plan_sha256=args.plan_sha256, **options)
                result = {'status': value['status'], 'current': current, 'identity': identity,
                    'requestSha256': value['requestSha256'], 'planSha256': value['planSha256'],
                    'removedContainers': len(value['removed']), 'alreadyAbsent': len(value['alreadyAbsent']),
                    'dataDirectoriesPreserved': value['dataDirectoriesPreserved'], 'jarDeletionPerformed': value['jarDeletionPerformed'],
                    'imagesPreserved': value['imagesPreserved'], 'volumesPreserved': value['volumesPreserved'],
                    'sourceArchivesAndReportsPreserved': value['sourceArchivesAndReportsPreserved'],
                    'receipt': write_new(fixture_receipt_file, value)}
        elif args.phase in ('plan-canonical', 'apply-canonical'):
            need(args.mode == 'Maintenance', 'CANONICAL_RETIREMENT_REQUIRES_MAINTENANCE')
            raw = private_bytes(root, request_file); approved_request(raw, args.request_sha256, current, identity, canonical_jar=True)
            def canonical_quiescence(checkout, tag, token):
                need(checkout == root / 'verification' / tag / 'checkout' and canonical_commit(tag) is not None,
                     'EXACT_CANONICAL_REFERENCE_ROOTS_REQUIRED')
                modules['cleanup'].quiescent({'checkout': checkout, 'token': token}, tag,
                                             modules['cleanup'].docker_snapshot(), include_inbox=True)
            options = {'request_sha256': args.request_sha256, 'expected_current': current, 'identity': identity,
                       'quiescence': canonical_quiescence, 'canonical_jar': True}
            if args.phase == 'plan-canonical':
                value = plan(root, raw, **options)
                result = {'status': 'PLANNED', 'current': current, 'identity': identity,
                          'plan': write_new(canonical_plan_file, value), 'skipped': value['skipped'],
                          'candidateBytes': value['candidateBytes'], 'candidateAllocatedBytes': value['candidateAllocatedBytes']}
            else:
                plan_raw = private_bytes(root, canonical_plan_file)
                need(digest_bytes(plan_raw) == args.plan_sha256, 'ORIGINAL_CANONICAL_PLAN_RAW_SHA_DRIFT')
                value = apply(root, raw, decode(plan_raw), plan_sha256=args.plan_sha256, **options)
                result = {'status': value['status'], 'current': current, 'identity': identity,
                          'receipt': write_new(canonical_receipt_file, value)}
        elif args.phase in ('plan-python-build-cache', 'apply-python-build-cache'):
            options = {'expected_current': current, 'identity': identity, 'modules': modules}
            if args.phase == 'plan-python-build-cache':
                value = plan_python_build_cache(root, **options)
                result = {'status': 'PLANNED', 'current': current, 'identity': identity,
                          'plan': write_new(python_cache_plan_file, value), 'skipped': value['skipped'],
                          'candidateContainerWritableBytes': value['candidateContainerWritableBytes'],
                          'candidateImageUniqueBytes': value['candidateImageUniqueBytes']}
            else:
                plan_raw = private_bytes(root, python_cache_plan_file)
                need(digest_bytes(plan_raw) == args.plan_sha256, 'ORIGINAL_PYTHON_CACHE_PLAN_RAW_SHA_DRIFT')
                value = apply_python_build_cache(root, decode(plan_raw), plan_sha256=args.plan_sha256, **options)
                result = {'status': value['status'], 'current': current, 'identity': identity,
                          'receipt': write_new(python_cache_receipt_file, value)}
        elif args.phase in ('plan-generated-image-archives', 'apply-generated-image-archives'):
            raw = private_bytes(root, request_file); approved_request(raw, args.request_sha256, current, identity)
            options = {'request_sha256': args.request_sha256, 'expected_current': current, 'identity': identity,
                       'quiescence': public_layer_quiescence(root, modules['cleanup'], quiescence)}
            if args.phase == 'plan-generated-image-archives':
                value = plan_generated_image_archives(root, raw, **options)
                result = {'status': 'PLANNED', 'current': current, 'identity': identity, 'plan': write_new(generated_plan_file, value),
                          'skipped': value['skipped'], 'candidateAllocatedBytes': value['candidateAllocatedBytes']}
            else:
                plan_raw = private_bytes(root, generated_plan_file)
                need(digest_bytes(plan_raw) == args.plan_sha256, 'ORIGINAL_GENERATED_CACHE_PLAN_RAW_SHA_DRIFT')
                value = apply_generated_image_archives(root, raw, decode(plan_raw), plan_sha256=args.plan_sha256, **options)
                result = {'status': value['status'], 'current': current, 'identity': identity,
                          'receipt': write_new(generated_receipt_file, value)}
        elif args.phase in ('plan-public-layers', 'apply-public-layers'):
            raw = private_bytes(root, request_file); approved_request(raw, args.request_sha256, current, identity)
            options = {'request_sha256': args.request_sha256, 'expected_current': current, 'identity': identity,
                       'quiescence': public_layer_quiescence(root, modules['cleanup'], quiescence)}
            if args.phase == 'plan-public-layers':
                value = plan_public_layers(root, raw, **options)
                result = {'status': 'PLANNED', 'current': current, 'identity': identity,
                          'plan': write_new(public_plan_file, value), 'skipped': value['skipped'],
                          'candidateBytes': value['candidateBytes'], 'candidateAllocatedBytes': value['candidateAllocatedBytes']}
            else:
                plan_raw = private_bytes(root, public_plan_file)
                need(digest_bytes(plan_raw) == args.plan_sha256, 'ORIGINAL_PUBLIC_LAYER_PLAN_RAW_SHA_DRIFT')
                value = apply_public_layers(root, raw, decode(plan_raw), plan_sha256=args.plan_sha256, **options)
                result = {'status': value['status'], 'current': current, 'identity': identity,
                          'receipt': write_new(public_receipt_file, value)}
        elif args.phase in ('plan-builders', 'apply-builders'):
            raw = private_bytes(root, request_file); approved_request(raw, args.request_sha256, current, identity)
            options = {'request_sha256': args.request_sha256, 'expected_current': current, 'identity': identity, 'modules': modules}
            if args.phase == 'plan-builders':
                value = plan_builders(root, raw, **options)
                result = {'status': 'PLANNED', 'current': current, 'identity': identity,
                          'plan': write_new(builder_plan_file, value), 'skipped': value['skipped']}
            else:
                plan_raw = private_bytes(root, builder_plan_file)
                need(digest_bytes(plan_raw) == args.plan_sha256, 'ORIGINAL_BUILDER_PLAN_RAW_SHA_DRIFT')
                value = apply_builders(root, raw, decode(plan_raw), plan_sha256=args.plan_sha256, **options)
                result = {'status': value['status'], 'current': current, 'identity': identity,
                          'receipt': write_new(builder_receipt_file, value)}
        else:
            raw = private_bytes(root, request_file); approved_request(raw, args.request_sha256, current, identity)
            options = {'request_sha256': args.request_sha256, 'expected_current': current, 'identity': identity, 'quiescence': quiescence}
            if args.phase == 'plan':
                value = plan(root, raw, **options)
                result = {'status': 'PLANNED', 'current': current, 'identity': identity, 'plan': write_new(plan_file, value),
                          'candidateBytes': value['candidateBytes'], 'candidateAllocatedBytes': value['candidateAllocatedBytes'], 'skipped': value['skipped']}
            else:
                plan_raw = private_bytes(root, plan_file)
                need(digest_bytes(plan_raw) == args.plan_sha256, 'ORIGINAL_PLAN_RAW_SHA_DRIFT')
                value = apply(root, raw, decode(plan_raw), plan_sha256=args.plan_sha256, **options)
                result = {'status': value['status'], 'current': current, 'identity': identity, 'receipt': write_new(receipt_file, value)}
        print(json.dumps(result, sort_keys=True))
        return 0 if result['status'] != 'FAILED_OR_UNKNOWN' else 2
    except Exception as error:
        location = error.__traceback__
        while location is not None and location.tb_next is not None: location = location.tb_next
        point = None if location is None else {'file': Path(location.tb_frame.f_code.co_filename).name[:96],
            'function': location.tb_frame.f_code.co_name[:96], 'line': location.tb_lineno}
        print(json.dumps({'status': 'REJECTED', 'phase': args.phase, 'errorType': type(error).__name__, 'location': point,
                          'reason': str(error) if isinstance(error, RetirementError)
                          or getattr(error, 'doorhandle_public_resource_error', False) else 'NATIVE_DUPLICATE_ADMISSION_FAILED'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(cli())
