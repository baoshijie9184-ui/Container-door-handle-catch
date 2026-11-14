"""Retire only the explicitly approved sixteen old synthetic pytest roots.

No target payload is read. Original source/reports are re-admitted by the mature
source cleanup helper. ECS lifecycle stays outside Jenkins and this controller.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import stat
import struct
import subprocess
import sys
import tarfile
import time

ROOT = Path('/home/ecs-user/doorhandle-ci')
BATCH = 'source-pytest16-20261114'
MIB = 1024 ** 2
GIB = 1024 ** 3
MAX_CONTROL = 32 * MIB
MAX_ENTRIES = 100000
MAX_SECONDS = 1800
SHA = re.compile(r'[a-f0-9]{64}')
TAG = re.compile(r'ci-[1-9][0-9]*-[a-f0-9]{12}')
LOADED_SOURCE = Path(__file__).read_bytes() if __file__ != '<stdin>' and os.geteuid() != 0 else None
IDENTITY = {'executionLocation': 'ECS', 'instanceId': 'i-2zeieuov2aum486jm1ek', 'machineId': '1ebe8f77e3104ab6a49a9386e38abd20'}
USER_ANSWER = '允许按条件回收这16份旧Python测试目录，保留业务库、原始SQL、源码、报告和#266，继续通过本地Jenkins在ECS上验证，测试结束后停机不计费。'
EXACT_BUILDS = [100, 102, 103, 104, 105, 107, 109, 110, 114, 120, 122, 150, 178, 180, 215, 217]
APPROVED_ENTRIES = [{'release': 'ci-100-c44e23d06a69', 'path': '/home/ecs-user/doorhandle-ci/verification/ci-100-c44e23d06a69/checkout/work/ci-evidence/tmp/pytest', 'sourceProof': {'commit': 'c44e23d06a69a1b5ecd86b0f894b287783c1bf75', 'sourceSha256': 'c1ec191e4fe5ec8c8331c2d405ba069e7582539fb6df53b04b7443f4f3defd17', 'verificationReceiptSha256': '5fc3717872482cc13772e1ec74ca3a698a9bae27be805a374038a53d3411222c', 'reportCatalogSha256': '1f018dc4b2770833e9a1cd99095e44056363c4c48f1e7c0c636435c63b025a0a', 'claimSha256': 'c6071c3fb1c323faedd78aa761848551f5e513a86edafa3e14de214bf5b71546', 'toolManifestSha256': 'bdfed77e777cf63778b18ef2fe599df058746e890ccf96c1a665f9e1bbb7a538'}}, {'release': 'ci-102-0f12b873c7fb', 'path': '/home/ecs-user/doorhandle-ci/verification/ci-102-0f12b873c7fb/checkout/work/ci-evidence/tmp/pytest', 'sourceProof': {'commit': '0f12b873c7fb56b001cdf9e1cbc9f52849492b50', 'sourceSha256': '0defa2b5a162abac806e44fd6c496bd6b5801cc521d0d718eab937821ac4acbf', 'verificationReceiptSha256': '6e0c6a6dbfa0b4dcbd10f5425654fb84fca5d65d14ccb619b17cef76f458d01c', 'reportCatalogSha256': 'f1eaeccf5051b0695ac945ba687a048e7f2039264c67607ae9d798ce5d4d9209', 'claimSha256': 'ed7f094d412be4ed144a53a77c155ee544159ab6ab0d28bbed5aec593d5eb56c', 'toolManifestSha256': 'f106a932ffeec5e1f4530a8c91cdab747fc11dfb047087532eeae08d1bc2c9f6'}}, {'release': 'ci-103-0f12b873c7fb', 'path': '/home/ecs-user/doorhandle-ci/verification/ci-103-0f12b873c7fb/checkout/work/ci-evidence/tmp/pytest', 'sourceProof': {'commit': '0f12b873c7fb56b001cdf9e1cbc9f52849492b50', 'sourceSha256': '0defa2b5a162abac806e44fd6c496bd6b5801cc521d0d718eab937821ac4acbf', 'verificationReceiptSha256': 'bdbf33b7466db6f08f03ab34b3182d5208f6c8089eb4c05f9c762ec9a8cba2d0', 'reportCatalogSha256': '279472fc1c8d8bcb9cfd7a2318dd1d7ba6c2137e061c8fef942551f8b792aedb', 'claimSha256': 'ef6d9d62c94cc9d2869885c8cadc14c231577cb76cf2312ea3835a0ecc67ad5c', 'toolManifestSha256': '333fbfeabb25e28928f8d1daa07d2e2eb9bc2bab1cde48e9ecc99eccd715233a'}}, {'release': 'ci-104-9e285c25c3f1', 'path': '/home/ecs-user/doorhandle-ci/verification/ci-104-9e285c25c3f1/checkout/work/ci-evidence/tmp/pytest', 'sourceProof': {'commit': '9e285c25c3f10224337391437814dd74544b745a', 'sourceSha256': 'f900315578fff61552bda915dde550b595bc818995e22f49100f8752562576a3', 'verificationReceiptSha256': '1c14bca0f5a319b672be613225e805327739ca7de6fc97425413a1ab0420dc36', 'reportCatalogSha256': '1dc8d188aa3eecce45b6910b3cfbc53898b022b822ba215bff08049867465902', 'claimSha256': 'e9cba3ec32044c748c659d9ad7b31977fa4bc49a93a03fcfa47eaf7ab2e78cb3', 'toolManifestSha256': '0136b4732a7420074fcc71941c4bdb1eb80786b87fa0900bd14404aa6e056960'}}, {'release': 'ci-105-f1f8c8d03018', 'path': '/home/ecs-user/doorhandle-ci/verification/ci-105-f1f8c8d03018/checkout/work/ci-evidence/tmp/pytest', 'sourceProof': {'commit': 'f1f8c8d03018f06af23cba48e2ffbbaf5385f0f5', 'sourceSha256': 'c344e26e8bf8144a47a1162d685c3e018254e3bd208c165acd20adf0124f029d', 'verificationReceiptSha256': 'e3caabbd52e03529dd1c96082b694ff4f9930ba6b53ee491522f796bb3decfe1', 'reportCatalogSha256': 'ca3062e5d2786e3f238e57af08ddae974cae7a9f90d9722e90840c35b9ccc91c', 'claimSha256': '374ed8f493046b6428e32a1fef414a4333c1d182b76925a022e99abd3853c47e', 'toolManifestSha256': 'a6b7d8549cfa9fe61717cb050f229118c5be65f77cdb82d2fb30b1e40a7d3884'}}, {'release': 'ci-107-97ac695d3dc6', 'path': '/home/ecs-user/doorhandle-ci/verification/ci-107-97ac695d3dc6/checkout/work/ci-evidence/tmp/pytest', 'sourceProof': {'commit': '97ac695d3dc63515b898c88181e68224b6bd1046', 'sourceSha256': 'beec20f9a941d46cb29a73b7d57523901d9d2567114ffa2f02d8fb44b6861563', 'verificationReceiptSha256': 'd70a8889fa5236d4fad2266c5f8faccc853c80b7b25390fa75fbd5f97c199f7a', 'reportCatalogSha256': 'a2c027bcea282df144ad59ff71098d2ad39dce15237138da1472fe95fe5fb830', 'claimSha256': '3ca2e9461a7ee24d21f72c7e4f9dc192131c59dad7d1cd58700c4d8dc146239c', 'toolManifestSha256': '372cdf643d9717d0c2b74db2be29f58e01b16d47c6d7bca426546ce9e79c5e44'}}, {'release': 'ci-109-b756a5781f44', 'path': '/home/ecs-user/doorhandle-ci/verification/ci-109-b756a5781f44/checkout/work/ci-evidence/tmp/pytest', 'sourceProof': {'commit': 'b756a5781f44da0372e412132b212e8c07a91eb6', 'sourceSha256': 'd2efcc173b2147af9542125b0c1326f4bc10196935b6763bee837136b4082a0a', 'verificationReceiptSha256': '216410f933ec5b49c69eded5c307e86240ec87878291d8bd6d0ecda02c550e6a', 'reportCatalogSha256': '78c44d664f5e11b1f721d1d39a4d14c4ccecf0f572f6c504a4f663378589740e', 'claimSha256': '4d4e37d721c019bf7fb171f0cff596d9e5e37ccd4f5eba1a66436af461ef682e', 'toolManifestSha256': '2bc70f5c60fdeabec6570e88c1a5bad60f05b91d180cb52b18e729307ed9ca44'}}, {'release': 'ci-110-b756a5781f44', 'path': '/home/ecs-user/doorhandle-ci/verification/ci-110-b756a5781f44/checkout/work/ci-evidence/tmp/pytest', 'sourceProof': {'commit': 'b756a5781f44da0372e412132b212e8c07a91eb6', 'sourceSha256': 'd2efcc173b2147af9542125b0c1326f4bc10196935b6763bee837136b4082a0a', 'verificationReceiptSha256': '02461663b05991c29466e2011eecf75af406205132749525df710f317ae03815', 'reportCatalogSha256': 'fba50a0a18ceffe557e5e9f977a71074ebaf25138635a65c858890a2420e5351', 'claimSha256': 'f0f6c89f6972cc5d04347086299c7cadd65b9772910cd96aa2ed5224a7d83f47', 'toolManifestSha256': 'e0e3e4125b082aca4c26b339294324c6f02fe49c579dc9fb49f4d07b37f38651'}}, {'release': 'ci-114-91c77d977a58', 'path': '/home/ecs-user/doorhandle-ci/verification/ci-114-91c77d977a58/checkout/work/ci-evidence/tmp/pytest', 'sourceProof': {'commit': '91c77d977a58a0080c49786ecf4f29c4cf87eb33', 'sourceSha256': 'd132b165b936ded6b1d5a0a085b78507f40e95582e806166773a1f5289a953c8', 'verificationReceiptSha256': '593dff8ef2968d78396ecd844aa5c70089a81ce5e35b6765e444fcc15b2f403a', 'reportCatalogSha256': '93405a019e0fd331d5d21bc0d6879343f067b39d486908db42372b984808f041', 'claimSha256': '3017ac09c7855d12fc63be777a140fc3f608ac9eb148147bbb1bdb66596fb793', 'toolManifestSha256': 'f04da29a0c24d5750a9b04f161bbe6d6a37c8368575e90a907c60aae81fcc1dc'}}, {'release': 'ci-120-392ae841c2ab', 'path': '/home/ecs-user/doorhandle-ci/verification/ci-120-392ae841c2ab/checkout/work/ci-evidence/tmp/pytest', 'sourceProof': {'commit': '392ae841c2ab50d558eaa4038614b8b4ddb0cf99', 'sourceSha256': '394a79e851758f5662c946d6659f2f6f0acfa1530f93cced162099369599ec7f', 'verificationReceiptSha256': 'a54ffa21faee02596ef670451cd44389373bbaf379ac7667b0c60aa480c0d433', 'reportCatalogSha256': 'cfb50459418d05723a69d536ed38b0151828536ffc83423b2457cc9b2ce6ac02', 'claimSha256': '91a0b584bcf82a2f260bdd700dc47a7535cbcb411cfc30c390ee17be5bd7c909', 'toolManifestSha256': '17aeac9eee479518934705ec96da6603573aa6e45cf7100b1f16dc90edd1430e'}}, {'release': 'ci-122-7a024fc1f02f', 'path': '/home/ecs-user/doorhandle-ci/verification/ci-122-7a024fc1f02f/checkout/work/ci-evidence/tmp/pytest', 'sourceProof': {'commit': '7a024fc1f02fa769ffa4366dd1ec6b9ec30260be', 'sourceSha256': 'e5308a1432910f275ed048fbb6152a6a38187eab6f5b5f6a170e1b9e40c25c30', 'verificationReceiptSha256': '56ba311d01552947f21c63ff2a316d914b0d1f28239f4b39584d2036a0b7144e', 'reportCatalogSha256': '8afc7a54b22255a93fd330c18da4000fe3e8a914ecf3874dfda8e93a6c770075', 'claimSha256': '60e4e0fd2fcdfab2d3fdaec24031639054a7992181d2d43c7937d8ab8a127419', 'toolManifestSha256': 'b3a6e0a0997431ad4d0e1cab03704487d32d3fd29c59d2ca903c34965ddd1241'}}, {'release': 'ci-150-175c639cb2ac', 'path': '/home/ecs-user/doorhandle-ci/verification/ci-150-175c639cb2ac/checkout/work/ci-evidence/tmp/pytest', 'sourceProof': {'commit': '175c639cb2ac6f834f77319ea76ae2fd8c625ae7', 'sourceSha256': 'f3a51e4ddf1ae0f6887f2a6a1586182ffd6769d46bbb180a8a21b0ac8edca769', 'verificationReceiptSha256': 'e985293db6bcfc80e344e0526ac893d7647f412464ed308854a63f1a7e5829d4', 'reportCatalogSha256': 'd75e894c44315127e9a67072dbff74f9b8d3e20a58597a2be79274ca24356f33', 'claimSha256': '8e2e58f18d55237bdc23f494d434957292b6c34f1151e85080826b873e4a68af', 'toolManifestSha256': 'dcad7483d3f875aac10452266d2aa6bb2f7f9b721dd90311c307127191c586bb'}}, {'release': 'ci-178-5e6837e7d7cc', 'path': '/home/ecs-user/doorhandle-ci/verification/ci-178-5e6837e7d7cc/checkout/work/ci-evidence/tmp/pytest', 'sourceProof': {'commit': '5e6837e7d7cc56a494eea9a77fecdf0bb3166758', 'sourceSha256': '5d52213259cedbade9dd354108822d96598626b834b5ddab0a170b84d25fe3f3', 'verificationReceiptSha256': '6195431ff6c13d61f74f3c7d7f2a4e5166d391b4f92ac94fa350a95ed6411ed2', 'reportCatalogSha256': '3210d1718bf1c68e74fb0edd3627233eafa1aae051d99f012a8a00f156b35a36', 'claimSha256': '80e91d3fd4eb93c7137c8b6387a52c892ac511538187912444a7226ca87b50c7', 'toolManifestSha256': '86c0c9de42e1705dbde98f1f33ee64050c1ca3b9049cca5c8ac78bcd939f6345'}}, {'release': 'ci-180-d91691250214', 'path': '/home/ecs-user/doorhandle-ci/verification/ci-180-d91691250214/checkout/work/ci-evidence/tmp/pytest', 'sourceProof': {'commit': 'd916912502142ba276352232aeb1be16c082f2a7', 'sourceSha256': '20fc7de8e039b7f5fd3c5c040d7cc10f51f25111b520b84268b0880a58f8d0c6', 'verificationReceiptSha256': '915ef9ed9a0a858847bc30cf64607b5ea6a25e92b379236e71784bbfd6c60aa1', 'reportCatalogSha256': 'ddbcd0e85578deb82adf9eaa9ad7c71265db674d38335bfb498411da5d4e2d57', 'claimSha256': '070a0f52fa814f589739e8cebd0e3d4ff917dd8d2add9571a065c4b58ebee0ba', 'toolManifestSha256': 'abb2eb85356fb75e5dafd3c7dd27587dd569a487e975f2692616ef4e7b8829a2'}}, {'release': 'ci-215-f15ec25989dc', 'path': '/home/ecs-user/doorhandle-ci/verification/ci-215-f15ec25989dc/checkout/work/ci-evidence/tmp/pytest', 'sourceProof': {'commit': 'f15ec25989dc89509d2f7881a72c5ae1cdfa8e52', 'sourceSha256': '07a0aa1cbfec2d8d2ca5cdd5d526b5dacc4ff4faa43437186c75152a5bf8a8ea', 'verificationReceiptSha256': '5a47aa3f13c4494c089a16e3e6eaf1fe0e75a63dcc293fc4d370d46a10302ca6', 'reportCatalogSha256': 'e6095a8615a4f83c32eee9188a73a574085a8be8df2f2aa31d39a40ff9eb1d61', 'claimSha256': '2851c1d3e758a4cb00f87575f09aeed8aa199973957e58693db415a688ffceaa', 'toolManifestSha256': '70aa0345923648e6c5c0fcf5ad9041d4f29c7a67b1cd0988a8910cf1230257a7'}}, {'release': 'ci-217-30189a58d2ff', 'path': '/home/ecs-user/doorhandle-ci/verification/ci-217-30189a58d2ff/checkout/work/ci-evidence/tmp/pytest', 'sourceProof': {'commit': '30189a58d2ff4948159b3fa34c0938a291f74f42', 'sourceSha256': '8db8e6f5da29bc1d193a7d41a8463fefc7c867a1739751f093816efe221172c2', 'verificationReceiptSha256': '3c333272d9fa1bbce774f4b1843cbf825995ba9629c2458c6f6a8a1a12ac0109', 'reportCatalogSha256': '83f8ea76ff59e5ff4f66957ef1861e2f920a048b9d0e764166f770c34b51ad20', 'claimSha256': '95b9a1d42607c4d662e5a65d690677d6f0232f69f41bd3cd75a23108a0a5641e', 'toolManifestSha256': '2e8e1e59a87c16a0c9e3c85ad64ce35344789d7175541addd026d5d44d1a726b'}}]
REQUIRED_CONDITIONS = ['EXACT_SOURCE_AND_TERMINAL_OWNER_BINDING', 'SOURCE_AND_ORIGINAL_REPORTS_PRESERVED', 'CURRENT_OBJECT_IDENTITY_AND_OWNERSHIP_CONFIRMED', 'NO_ACTIVE_PROCESS_CONTAINER_OR_RELEASE_REFERENCE', 'PIPELINE_FIXED_COMMITTED_SOURCE_ONLY', 'FRESH_DISK_READBACK_AND_ORIGINAL_PLAN_RECEIPTS']
ALWAYS_PRESERVE = ['FORMAL_BUSINESS_DATABASE', 'ORIGINAL_SQL', 'SOURCE_CODE_AND_ARCHIVES', 'ORIGINAL_REPORTS', 'BUILD_266_RECOVERY_POINT', 'EXCLUDED_225_AND_229']
EXACT_RELEASES = tuple(row["release"] for row in APPROVED_ENTRIES)


def need(value, code):
    if not value: raise ValueError(code)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(MIB), b''): h.update(block)
    return h.hexdigest()


def metadata(info):
    return [info.st_mode, info.st_uid, info.st_gid, info.st_size, info.st_mtime_ns,
            info.st_ino, info.st_dev, info.st_ctime_ns, info.st_nlink]


def validate_authorization(value):
    need(type(value) is dict and type(value.get('schemaVersion')) is int and value['schemaVersion'] == 1
         and value.get('kind') == 'doorhandle-exact-source-pytest-temporary-retirement-authorization'
         and value.get('source') == 'USER_EXPLICIT_MESSAGE' and value.get('answer') == USER_ANSWER
         and value.get('branch') == 'java-cloud' and value.get('job') == 'doorhandle-java'
         and value.get('root') == str(ROOT) and value.get('identity') == IDENTITY
         and type(value.get('actorUid')) is int and value['actorUid'] == 1000
         and value.get('exactBuilds') == EXACT_BUILDS
         and value.get('excludedBuilds') == [225, 229, 266]
         and isinstance(value.get('grantedAtUtc'), str) and value['grantedAtUtc'], 'EXACT_USER_AUTHORIZATION_REQUIRED')
    for key in ('allowArbitraryPath', 'allowFutureBuilds', 'allowDiskExpansion', 'allowRootTargetMutations'):
        need(value.get(key) is False, 'AUTHORIZATION_CANNOT_EXPAND_SCOPE')
    for key in ('allowOwnerWriteForOwnedTargetDirectories', 'authorizationEndsWhenExactTargetsConsumed'):
        need(value.get(key) is True, 'EXACT_OWNER_WRITE_AND_CONSUMPTION_AUTHORIZATION_REQUIRED')
    need(value.get('requiredConditions') == REQUIRED_CONDITIONS
         and value.get('alwaysPreserve') == ALWAYS_PRESERVE, 'PRESERVATION_CONDITIONS_CHANGED')
    rows = value.get('entries')
    need(type(rows) is list and len(rows) == 16, 'EXACT_SIXTEEN_TARGETS_REQUIRED')
    selected = [{key: row.get(key) for key in ('release', 'path', 'sourceProof')} for row in rows]
    need(selected == APPROVED_ENTRIES, 'EXACT_SOURCE_TARGETS_CHANGED')
    return selected


def relative_target(release):
    need(release in EXACT_RELEASES, 'UNAPPROVED_OLD_RELEASE')
    return 'verification/' + release + '/checkout/work/ci-evidence/tmp/pytest'


def inventory(path):
    """Metadata only: no-follow, same device, owner bound, no target file reads."""
    path = Path(path); rows = []; seen = set(); allocated = files = 0
    need(path.is_absolute() and '..' not in path.parts, 'ABSOLUTE_INVENTORY_PATH_REQUIRED')
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = child
    except BaseException:
        os.close(fd); raise
    try:
        initial = os.fstat(fd); device = initial.st_dev; uid = os.getuid()
        need(initial.st_uid == uid and stat.S_ISDIR(initial.st_mode), 'TARGET_OWNER_OR_TYPE_CHANGED')
        def account(info):
            nonlocal allocated
            need(info.st_uid == uid and info.st_dev == device, 'TARGET_OWNER_OR_DEVICE_CHANGED')
            key = (info.st_dev, info.st_ino)
            if key not in seen: seen.add(key); allocated += info.st_blocks * 512
            need(allocated <= 4 * GIB, 'TARGET_ALLOCATION_BOUND_EXCEEDED')
        account(initial)
        def visit(directory, prefix='', depth=0):
            nonlocal files
            need(depth <= 128, 'TARGET_DEPTH_BOUND_EXCEEDED')
            for name in sorted(os.listdir(directory)):
                need(name not in ('.', '..') and '/' not in name, 'TARGET_NAME_INVALID')
                info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                account(info)
                need(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                     or stat.S_ISFIFO(info.st_mode) or stat.S_ISSOCK(info.st_mode), 'TARGET_SPECIAL_DEVICE_REFUSED')
                relative = prefix + name
                need(len(relative.encode()) <= 4096, 'TARGET_PATH_BOUND_EXCEEDED')
                rows.append({'path': relative, 'metadata': metadata(info)})
                need(len(rows) <= MAX_ENTRIES, 'TARGET_ENTRY_BOUND_EXCEEDED')
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                    try:
                        need(metadata(os.fstat(child)) == metadata(info), 'DIRECTORY_CHANGED_DURING_INVENTORY')
                        visit(child, relative + '/', depth + 1)
                        need(metadata(os.fstat(child)) == metadata(info), 'DIRECTORY_CHANGED_DURING_INVENTORY')
                    finally: os.close(child)
                elif stat.S_ISREG(info.st_mode): files += 1
        visit(fd)
        need(metadata(os.fstat(fd)) == metadata(initial)
             and metadata(path.lstat()) == metadata(initial), 'TARGET_CHANGED_DURING_INVENTORY')
    finally: os.close(fd)
    return {'rootMetadata': metadata(initial), 'entries': rows, 'entryCount': len(rows),
            'files': files, 'allocatedBytes': allocated,
            'inventorySha256': hashlib.sha256(encoded(rows)).hexdigest()}


def same_metadata(actual, expected, unlinks=None):
    actual = metadata(actual) if not isinstance(actual, list) else actual
    observed = (unlinks or {}).get((expected[6], expected[5]))
    if observed:
        return (type(observed) is dict and set(observed) == {'count', 'metadata'}
                and type(observed['count']) is int and observed['count'] > 0
                and actual == observed['metadata'] and actual[:7] == expected[:7]
                and actual[8] == expected[8] - observed['count'] and actual[8] >= 1)
    return actual == expected


def remove_owned_tree(root, target, planned, journal, unlinks=None):
    """Unlink only the approved synthetic names; chmod directories, never files."""
    root = Path(root); unlinks = {} if unlinks is None else unlinks
    need(target in {relative_target(tag) for tag in EXACT_RELEASES}, 'DELETION_TARGET_OUTSIDE_EXACT_SCOPE')
    need(planned['inventorySha256'] == hashlib.sha256(encoded(planned['entries'])).hexdigest(),
         'INVENTORY_NOT_BOUND')
    entries = {row['path']: row['metadata'] for row in planned['entries']}
    need(len(entries) == len(planned['entries']), 'DUPLICATE_INVENTORY_PATH')
    children = {}
    for relative in entries:
        parent, _, name = relative.rpartition('/')
        children.setdefault(parent, set()).add(name)
    stack = [os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]
    device = os.fstat(stack[0]).st_dev; uid = os.getuid()
    try:
        parts = target.split('/')
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=stack[-1])
            stack.append(child); info = os.fstat(child)
            need(info.st_uid == uid and info.st_dev == device and not info.st_mode & 0o022,
                 'DELETION_ANCESTOR_CHANGED')
        def erase(parent, name, relative, expected):
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            need(info.st_uid == uid and info.st_dev == device and same_metadata(info, expected, unlinks),
                 'TARGET_CHANGED_AFTER_PLAN')
            if not stat.S_ISDIR(info.st_mode):
                need(stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                     or stat.S_ISFIFO(info.st_mode) or stat.S_ISSOCK(info.st_mode), 'TARGET_SPECIAL_DEVICE_REFUSED')
                need(same_metadata(os.stat(name, dir_fd=parent, follow_symlinks=False), expected, unlinks),
                     'TARGET_CHANGED_BEFORE_UNLINK')
                held = os.open(name, os.O_PATH | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    need(same_metadata(os.fstat(held), expected, unlinks), 'INODE_CHANGED_AT_UNLINK')
                    need(metadata(os.stat(name, dir_fd=parent, follow_symlinks=False)) == metadata(os.fstat(held)),
                         'ENTRY_NAME_CHANGED_AT_UNLINK')
                    os.unlink(name, dir_fd=parent)
                    after = metadata(os.fstat(held)); before = metadata(info)
                    need(after[:7] == before[:7] and after[8] == before[8] - 1, 'INODE_CHANGED_DURING_UNLINK')
                    key = (info.st_dev, info.st_ino)
                    count = unlinks.get(key, {}).get('count', 0)
                    unlinks[key] = {'count': count + 1, 'metadata': after}
                finally: os.close(held)
                journal({'phase': 'UNLINK', 'path': relative})
                return
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            old_mode = stat.S_IMODE(info.st_mode); changed = removed = False
            try:
                need(same_metadata(os.fstat(fd), expected, unlinks), 'DIRECTORY_CHANGED_AFTER_PLAN')
                if not old_mode & stat.S_IWUSR:
                    os.fchmod(fd, old_mode | stat.S_IWUSR); changed = True
                    journal({'phase': 'OWNER_WRITE_ADDED', 'path': relative, 'originalMode': old_mode})
                prefix = '' if relative == '.' else relative + '/'
                names = sorted(os.listdir(fd))
                expected_names = children.get('' if relative == '.' else relative, set())
                need(set(names) == expected_names, 'TARGET_ENTRIES_CHANGED_AFTER_PLAN')
                for child in names:
                    key = prefix + child
                    need(key in entries, 'NEW_TARGET_ENTRY_AFTER_PLAN')
                    erase(fd, child, key, entries[key])
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                held = os.fstat(fd)
                need((current.st_dev, current.st_ino, current.st_uid) == (held.st_dev, held.st_ino, uid),
                     'DIRECTORY_NAME_REPLACED_DURING_DELETE')
                need(held.st_gid == expected[2] and held.st_mode == (expected[0] | (stat.S_IWUSR if changed else 0)),
                     'DIRECTORY_PERMISSION_CHANGED_DURING_DELETE')
                os.rmdir(name, dir_fd=parent); removed = True
                journal({'phase': 'RMDIR', 'path': relative})
            finally:
                if changed and not removed:
                    os.fchmod(fd, old_mode)
                    journal({'phase': 'OWNER_MODE_RESTORED', 'path': relative, 'mode': old_mode})
                os.close(fd)
        erase(stack[-1], parts[-1], '.', planned['rootMetadata'])
    finally:
        for fd in reversed(stack): os.close(fd)


def read_bounded(path, maximum=MAX_CONTROL):
    path = Path(path); before = path.lstat()
    need(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
         and not before.st_mode & 0o022 and 0 <= before.st_size <= maximum, 'PRIVATE_CONTROL_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        need(metadata(os.fstat(fd)) == metadata(before), 'CONTROL_CHANGED_AT_OPEN')
        raw = b''
        while len(raw) <= maximum:
            block = os.read(fd, min(MIB, maximum + 1 - len(raw)))
            if not block: break
            raw += block
        need(len(raw) == before.st_size and metadata(os.fstat(fd)) == metadata(before)
             == metadata(path.lstat()), 'CONTROL_CHANGED_DURING_READ')
        return raw
    finally: os.close(fd)


def read_json(path, maximum=MAX_CONTROL):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'DUPLICATE_CONTROL_FIELD'); result[key] = value
        return result
    return json.loads(read_bounded(path, maximum), object_pairs_hook=unique)


def write_json(path, value):
    raw = encoded(value) + b'\n'; need(len(raw) <= MAX_CONTROL, 'CONTROL_SIZE_BOUND_EXCEEDED')
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream: stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def fixed_modules(args):
    need(os.getuid() == os.geteuid() == 1000 and ROOT.resolve() == ROOT, 'ECS_UID_1000_REQUIRED')
    need(TAG.fullmatch(args.tag) and re.fullmatch(r'[a-f0-9]{40}', args.commit)
         and args.tag.endswith('-' + args.commit[:12]) and SHA.fullmatch(args.source_sha256), 'FIXED_CONTEXT_REQUIRED')
    inbox = ROOT / 'inbox' / args.tag
    wanted = {'script/jenkins/retire-source-pytest.py': inbox / 'retire-source-pytest.py',
              'script/jenkins/cleanup-ecs-builds.py': inbox / 'cleanup-ecs-builds.py',
              'script/jenkins/verify-remote.py': inbox / 'verify-remote.py'}
    archive = inbox / 'cleanup-source.tar.gz'
    raw = read_bounded(archive, 128 * MIB)
    need(hashlib.sha256(raw).hexdigest() == args.source_sha256, 'FIXED_ARCHIVE_CHANGED')
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as package:
        need(package.pax_headers.get('comment') == args.commit, 'FIXED_SOURCE_COMMIT_CHANGED')
        total = 0
        for number, member in enumerate(package):
            total += member.size
            need(number < 50000 and 0 <= member.size <= 32 * MIB and total <= 512 * MIB,
                 'FIXED_SOURCE_BOUND_EXCEEDED')
            if member.name not in wanted: continue
            need(member.isfile() and 0 < member.size <= MIB and member.name not in seen,
                 'FIXED_HELPER_ENTRY_INVALID')
            need(package.extractfile(member).read() == read_bounded(wanted[member.name], MIB),
                 'FIXED_HELPER_CHANGED')
            seen.add(member.name)
    need(seen == set(wanted), 'FIXED_HELPER_CLOSURE_MISSING')
    cleanup = load('approved_source_cleanup', wanted['script/jenkins/cleanup-ecs-builds.py'])
    verifier = load('approved_source_verifier', wanted['script/jenkins/verify-remote.py'])
    need(verifier.ecs_identity(IDENTITY['instanceId'], IDENTITY['machineId']) == IDENTITY, 'ORIGINAL_ECS_REQUIRED')
    for path in (ROOT, ROOT / 'inbox', ROOT / 'verification', inbox): cleanup.owned(path, directory=True)
    auth = inbox / 'source-pytest16-authorization.json'
    need(digest(auth) == args.authorization_sha256, 'AUTHORIZATION_SHA_CHANGED')
    validate_authorization(read_json(auth))
    return inbox, cleanup, verifier


def source_binding(entry, cleanup, verifier):
    tag = entry['release']; proof = entry['sourceProof']
    need(not os.path.lexists(ROOT / 'releases' / tag), 'RETAINED_RELEASE_OR_ROLLBACK_ARTIFACTS')
    file = ROOT / 'verification' / tag / 'verification-receipt.json'
    record = cleanup.read_json(file, verifier.MAX_RECEIPT_BYTES)
    need(cleanup.digest(file) == proof['verificationReceiptSha256'], 'ORIGINAL_RECEIPT_CHANGED')
    custody = {'release': tag, 'commit': proof['commit'], 'sourceSha256': proof['sourceSha256'],
        'identity': IDENTITY, 'verificationReceiptSha256': proof['verificationReceiptSha256'],
        'reportCatalogSha256': proof['reportCatalogSha256'], 'reportFiles': len(record['reportFiles']),
        'reportBytes': sum(row['bytes'] for row in record['reportFiles']), 'originalEvidenceArchive': None}
    binding = cleanup.evidence_binding(ROOT, custody, IDENTITY, verifier)
    need(binding['claimSha256'] == proof['claimSha256'] and binding['toolManifestSha256'] == proof['toolManifestSha256'],
         'ORIGINAL_SOURCE_OWNER_CHANGED')
    inner = binding['inner']
    need(inner.get('javaOnly') is False and inner.get('wholeMigrationRequested') is False
         and inner.get('workerMysqlRequested') is False and inner.get('fixtureProperties') == []
         and inner.get('fixtureManifest') is None and inner.get('workerMysqlConfigSha256') is None,
         'SYNTHETIC_SOURCE_ONLY_REQUIRED')
    command = [row for row in inner['commands'] if row.get('label') == 'python']
    need(len(command) == 1 and command[0].get('finishedAt') and command[0].get('exitCode') in (0, 1),
         'ORIGINAL_PYTEST_COMMAND_NOT_TERMINAL')
    expected_args = ['-B', '-m', 'pytest', 'tests_python', '-q', '--basetemp=' + str(binding['checkout'] / 'work/ci-evidence/tmp/pytest'),
                     '--junitxml=' + str(binding['checkout'] / 'work/ci-evidence/python.xml')]
    tools = cleanup.read_json(binding['checkout'] / 'work/ci-evidence/tool-runtime.json', MIB)
    manifest = cleanup.read_json(ROOT / 'inbox' / tag / 'tool-runtime/manifest.json', MIB)
    recipes = {}
    names = {'script/jenkins/verify-ecs.py', 'script/jenkins/ecs-tool-runtime.py'}
    with verifier.bounded_tar(ROOT / 'inbox' / tag / 'source.tar.gz', verifier.MAX_SOURCE_BYTES) as package:
        for member in package:
            if member.name not in names: continue
            need(member.isfile() and 0 < member.size <= MIB and member.name not in recipes, 'PYTEST_RECIPE_INVALID')
            recipes[member.name] = package.extractfile(member).read()
    need(set(recipes) == names
         and cleanup.digest(binding['checkout'] / 'script/jenkins/verify-ecs.py')
             == hashlib.sha256(recipes['script/jenkins/verify-ecs.py']).hexdigest()
         and manifest['files'].get('executor.py') == hashlib.sha256(recipes['script/jenkins/ecs-tool-runtime.py']).hexdigest()
         and cleanup.digest(Path(manifest['directory']) / 'executor.py') == manifest['files']['executor.py'],
         'PYTEST_SOURCE_OR_EXECUTOR_CHANGED')
    rows = [row for row in tools.get('commands', []) if row.get('tool') == 'python'
            and row.get('argumentsSha256') == hashlib.sha256(json.dumps(expected_args, ensure_ascii=True).encode()).hexdigest()]
    need(len(rows) == 1 and rows[0].get('status') == 'EXITED' and type(rows[0].get('exitCode')) is int
         and rows[0]['exitCode'] == command[0]['exitCode']
         and SHA.fullmatch(rows[0].get('containerId', ''))
         and rows[0].get('cleanup', {}).get('containerId') == rows[0]['containerId']
         and rows[0]['cleanup'].get('image') == manifest['images']['python']
         and rows[0].get('cleanup', {}).get('removed') is True and rows[0]['cleanup'].get('pid') == 0
         and rows[0]['cleanup'].get('exitCode') == command[0]['exitCode'], 'EXACT_PYTEST_BASETEMP_NOT_PROVEN')
    need({'reports/python.xml', 'reports/python.log'} <= set(binding['catalog']), 'ORIGINAL_PYTEST_REPORTS_REQUIRED')
    # The mature binding already authenticates the complete original XML bytes;
    # nonzero pytest exit is retained as FAILED rather than reclassified as PASS.
    import xml.etree.ElementTree as ET
    raw = read_bounded(binding['checkout'] / 'work/ci-evidence/python.xml', verifier.MAX_FILE_BYTES)
    need(b'<!DOCTYPE' not in raw and b'<!ENTITY' not in raw, 'XML_ENTITY_REFUSED')
    cases = list(ET.fromstring(raw).iter('testcase'))
    failed = sum(case.find('failure') is not None or case.find('error') is not None for case in cases)
    need(cases and (command[0]['exitCode'] == 0 and failed == 0 or command[0]['exitCode'] == 1 and failed > 0),
         'ORIGINAL_PYTEST_EXIT_AND_XML_DIFFER')
    return binding


def unix_socket_vfs():
    """Read the kernel's bound VFS identities, never resolve historical names.

    UNIX_DIAG_VFS refers to the filesystem dentry rather than the unrelated
    socketfs inode shown by /proc/PID/fd. It survives rename, relative bind and
    a closed /proc/self/fd bind directory. An incomplete dump is not evidence
    that a socket has closed. Linux UAPI: include/uapi/linux/unix_diag.h.
    """
    sequence = secrets.randbits(32) or 1
    request = struct.pack('=BBHIIIII', socket.AF_UNIX, 0, 0, 0xffffffff,
                          0, 3, 0xffffffff, 0xffffffff)
    header = struct.pack('=IHHII', 16 + len(request), 20, 0x301, sequence, 0)
    identities = set(); total = 0
    with socket.socket(socket.AF_NETLINK, socket.SOCK_RAW | socket.SOCK_CLOEXEC, 4) as channel:
        channel.settimeout(3); channel.bind((0, 0))
        need(channel.sendto(header + request, (0, 0)) == len(header + request), 'UNIX_SOCKET_DIAGNOSTIC_INCOMPLETE')
        port = channel.getsockname()[0]
        for _ in range(1024):
            raw, _ancillary, flags, sender = channel.recvmsg(256 * 1024)
            total += len(raw)
            need(raw and total <= 16 * MIB and sender[0] == 0
                 and not flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC), 'UNIX_SOCKET_DIAGNOSTIC_INCOMPLETE')
            offset = 0
            while offset < len(raw):
                need(len(raw) - offset >= 16, 'UNIX_SOCKET_DIAGNOSTIC_INVALID')
                length, kind, message_flags, seq, pid = struct.unpack_from('=IHHII', raw, offset)
                need(16 <= length <= len(raw) - offset and seq == sequence and pid in (0, port)
                     and not message_flags & 0x10, 'UNIX_SOCKET_DIAGNOSTIC_INCOMPLETE')
                body = raw[offset + 16:offset + length]
                offset += (length + 3) & ~3
                if kind == 3:  # NLMSG_DONE; errors and interrupted dumps fail closed.
                    need(len(body) in (0, 4) and (not body or struct.unpack('=i', body)[0] == 0)
                         and offset == len(raw), 'UNIX_SOCKET_DIAGNOSTIC_INCOMPLETE')
                    return identities
                need(kind == 20 and len(body) >= 16 and body[0] == socket.AF_UNIX,
                     'UNIX_SOCKET_DIAGNOSTIC_INVALID')
                position = 16; attributes = {}
                while position < len(body):
                    need(len(body) - position >= 4, 'UNIX_SOCKET_DIAGNOSTIC_INVALID')
                    size, attribute = struct.unpack_from('=HH', body, position)
                    need(4 <= size <= len(body) - position and attribute not in attributes,
                         'UNIX_SOCKET_DIAGNOSTIC_INVALID')
                    attributes[attribute] = body[position + 4:position + size]
                    position += (size + 3) & ~3
                need(position == len(body), 'UNIX_SOCKET_DIAGNOSTIC_INVALID')
                if 1 in attributes:  # UNIX_DIAG_VFS: kernel s_dev (20 minor bits), not userspace dev_t.
                    need(len(attributes[1]) == 8, 'UNIX_SOCKET_DIAGNOSTIC_INVALID')
                    inode, device = struct.unpack('=II', attributes[1])
                    identities.add((os.makedev(device >> 20, device & 0xfffff), inode))
    raise ValueError('UNIX_SOCKET_DIAGNOSTIC_INCOMPLETE')


def enter_net_namespace(descriptor):
    """Only the read-only metadata worker changes its own network namespace."""
    if hasattr(os, 'setns'):
        os.setns(descriptor, 0x40000000)
    else:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.setns(descriptor, 0x40000000) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))


def socket_references(socket_keys, proc=Path('/proc')):
    if not socket_keys: return 0
    need(all(inode <= 0xffffffff for _device, inode in socket_keys), 'UNIX_SOCKET_VFS_IDENTITY_UNREPRESENTABLE')
    checked = set()
    def life(entry):
        with (entry / 'stat').open('rb') as stream: raw = stream.read(4097)
        need(len(raw) <= 4096 and raw.split(b' ', 1)[0] == entry.name.encode(), 'PROCESS_STAT_INVALID')
        fields = raw.rsplit(b')', 1)[1].split()
        need(len(fields) >= 20, 'PROCESS_STAT_INVALID')
        return fields[0], int(fields[6]), fields[19]
    with (proc / 'self/ns/net').open('rb') as original:
        origin = os.fstat(original.fileno())
        origin_key = (origin.st_dev, origin.st_ino)
        def inspect(descriptor):
            info = os.fstat(descriptor); key = (info.st_dev, info.st_ino)
            if key in checked: return
            need(len(checked) < 1024, 'UNIX_SOCKET_NAMESPACE_BOUND_EXCEEDED')
            try:
                if key != origin_key: enter_net_namespace(descriptor)
                need(not socket_keys & unix_socket_vfs(), 'ACTIVE_UNIX_SOCKET_VFS_REFERENCE')
                checked.add(key)
            finally:
                if key != origin_key: enter_net_namespace(original.fileno())
        inspect(original.fileno())
        with os.scandir(proc) as items:
            for number, item in enumerate(items):
                need(number < 65536, 'PROCESS_COUNT_BOUND_EXCEEDED')
                if not item.name.isdecimal(): continue
                entry = Path(item.path)
                try:
                    before = entry.stat(); status, flags, ticks = life(entry)
                    if status in (b'Z', b'X') or flags & 0x00200000: continue
                    with (entry / 'ns/net').open('rb') as namespace:
                        inspect(namespace.fileno())
                        after = entry.stat(); _, _, after_ticks = life(entry)
                        current = (entry / 'ns/net').stat()
                        held = os.fstat(namespace.fileno())
                        need((before.st_dev, before.st_ino, before.st_uid) == (after.st_dev, after.st_ino, after.st_uid)
                             and ticks == after_ticks
                             and (current.st_dev, current.st_ino) == (held.st_dev, held.st_ino),
                             'UNIX_SOCKET_NAMESPACE_CHANGED')
                except (FileNotFoundError, ProcessLookupError):
                    need(not entry.exists(), 'UNIX_SOCKET_NAMESPACE_COVERAGE_UNKNOWN')
    return len(checked)


def probe_processes(request, proc=Path('/proc')):
    """Read-only administrator probe, restricted to one of the closed pytest roots."""
    need(os.getuid() == os.geteuid() == 0 and set(request) == {'release', 'keys', 'socketKeys', 'nonce'},
         'ROOT_PERMITS_ONLY_CLOSED_PROCESS_METADATA')
    release = request['release']; relative_target(release)
    need(Path('/etc/machine-id').read_text().strip() == IDENTITY['machineId'], 'ORIGINAL_MACHINE_REQUIRED')
    keys = request['keys']
    need(type(keys) is list and 0 < len(keys) <= MAX_ENTRIES + 1
         and all(type(row) is list and len(row) == 2 and all(type(n) is int and n >= 0 for n in row) for row in keys)
         and re.fullmatch(r'[a-f0-9]{32}', request['nonce']), 'CLOSED_INODE_REQUEST_INVALID')
    inode_keys = {tuple(row) for row in keys}
    socket_keys = request['socketKeys']
    need(type(socket_keys) is list and len(socket_keys) <= len(keys)
         and all(type(row) is list and len(row) == 2 and all(type(n) is int and n >= 0 for n in row)
                 and tuple(row) in inode_keys for row in socket_keys), 'CLOSED_SOCKET_REQUEST_INVALID')
    checkout = ROOT / 'verification' / release / 'checkout'
    inbox = ROOT / 'inbox' / release
    map_keys = {(os.major(dev), os.minor(dev), inode) for dev, inode in inode_keys}
    def refers(raw): return any(os.fsencode(str(path)) in raw for path in (checkout, inbox))
    def bounded(path, maximum):
        with path.open('rb') as stream: raw = stream.read(maximum + 1)
        need(len(raw) <= maximum, 'PROCESS_METADATA_BOUND_EXCEEDED'); return raw
    def state(entry):
        raw = bounded(entry / 'stat', 4096); fields = raw.rsplit(b')', 1)[1].split()
        need(raw.split(b' ', 1)[0] == entry.name.encode() and len(fields) >= 20, 'PROCESS_STAT_INVALID')
        return fields[0], int(fields[6]), fields[19]
    def pointer(path):
        need(not refers(os.fsencode(os.readlink(path))), 'ACTIVE_PROCESS_PATH_REFERENCE')
        info = os.stat(path)
        need((info.st_dev, info.st_ino) not in inode_keys, 'ACTIVE_PROCESS_INODE_REFERENCE')
    checked = 0; users = set(); scanned = 0
    with os.scandir(proc) as items:
        for item in items:
            scanned += 1; need(scanned <= 65536, 'PROCESS_COUNT_BOUND_EXCEEDED')
            if not item.name.isdecimal() or int(item.name) == os.getpid(): continue
            entry = Path(item.path)
            try:
                before = entry.stat(); status, flags, ticks = state(entry)
                if status in (b'Z', b'X') or flags & 0x00200000: continue
                pointer(entry / 'cwd'); pointer(entry / 'root')
                need(not refers(bounded(entry / 'cmdline', MIB)), 'ACTIVE_PROCESS_ARGUMENT_REFERENCE')
                with os.scandir(entry / 'fd') as descriptors:
                    for number, descriptor in enumerate(descriptors):
                        need(number < 8192, 'PROCESS_DESCRIPTOR_BOUND_EXCEEDED')
                        try: pointer(Path(descriptor.path))
                        except (FileNotFoundError, ProcessLookupError):
                            try: os.lstat(descriptor.path)
                            except (FileNotFoundError, ProcessLookupError): continue
                            raise ValueError('PROCESS_DESCRIPTOR_CHANGED')
                for line in bounded(entry / 'maps', 16 * MIB).splitlines():
                    fields = line.split(None, 5); need(len(fields) >= 5, 'PROCESS_MAP_INVALID')
                    major, minor = [int(v, 16) for v in fields[3].split(b':')]
                    need((major, minor, int(fields[4])) not in map_keys
                         and not (len(fields) == 6 and refers(fields[5])), 'ACTIVE_PROCESS_MAP_REFERENCE')
                after = entry.stat(); _, _, after_ticks = state(entry)
                need((before.st_dev, before.st_ino, before.st_uid) == (after.st_dev, after.st_ino, after.st_uid)
                     and ticks == after_ticks, 'PROCESS_IDENTITY_CHANGED')
                checked += 1; users.add(before.st_uid)
            except (FileNotFoundError, ProcessLookupError):
                if not entry.exists(): continue
                status, flags, _ = state(entry)
                need(status in (b'Z', b'X') or flags & 0x00200000, 'LIVE_PROCESS_METADATA_UNAVAILABLE')
    namespaces = socket_references({tuple(row) for row in socket_keys}, proc)
    return {'status': 'QUIESCENT', 'scope': 'ALL_UIDS_EXACT_SOURCE_PYTEST_ROOT', 'release': release,
            'nonce': request['nonce'], 'keysSha256': hashlib.sha256(encoded(keys)).hexdigest(),
            'socketKeysSha256': hashlib.sha256(encoded(socket_keys)).hexdigest(),
            'socketNamespacesChecked': namespaces,
            'processesChecked': checked, 'uidsChecked': sorted(users)}


def reference_probe(release, tree, cleanup):
    target = ROOT / 'verification' / release / 'checkout'
    for _cid, _running, _restarting, _pid, container_release, _token, mounts in cleanup.docker_snapshot():
        need(container_release != release, 'OLD_RELEASE_CONTAINER_STILL_PRESENT')
        for mount in mounts:
            if mount.get('Type') != 'bind' or not mount.get('Source'): continue
            source = Path(mount['Source'])
            need(not (source == target or source.is_relative_to(target) or target.is_relative_to(source)),
                 'CONTAINER_REFERENCES_APPROVED_TEST_ROOT')
    keys = sorted({(row[6], row[5]) for row in [tree['rootMetadata'], *[item['metadata'] for item in tree['entries']]]})
    need(not set(keys) & cleanup.locked_inodes(), 'TARGET_HAS_HELD_FILE_LOCK')
    need(type(LOADED_SOURCE) is bytes and read_bounded(Path(__file__), MIB) == LOADED_SOURCE,
         'LOADED_PROCESS_PROBE_SOURCE_CHANGED')
    socket_keys = sorted({(row['metadata'][6], row['metadata'][5]) for row in tree['entries']
                          if stat.S_ISSOCK(row['metadata'][0])})
    request = {'release': release, 'keys': [list(key) for key in keys],
               'socketKeys': [list(key) for key in socket_keys], 'nonce': secrets.token_hex(16)}
    payload = LOADED_SOURCE + b'\nprint(json.dumps(probe_processes(json.loads(' + repr(encoded(request).decode()).encode() + b'))))\n'
    need(len(payload) <= 8 * MIB, 'PROCESS_PROBE_PAYLOAD_BOUND_EXCEEDED')
    command = ['/usr/bin/sudo', '-n', '/usr/bin/timeout', '--signal=TERM', '--kill-after=2s', '60s',
               sys.executable, '-I', '-B', '-c',
               "import sys; s=sys.stdin.buffer.read(8388609); assert len(s)<=8388608; exec(compile(s,'<approved-pytest-metadata>','exec'),{'__name__':'_approved_metadata','__file__':sys.argv[1]})",
               str(Path(__file__).absolute())]
    process = subprocess.run(command, input=payload, capture_output=True, timeout=70,
                             env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'})
    need(process.returncode == 0 and len(process.stdout) <= 4096 and len(process.stderr) <= 4096,
         'ALL_UID_PROCESS_METADATA_NOT_CONFIRMED')
    result = json.loads(process.stdout)
    need(result.get('status') == 'QUIESCENT' and result.get('scope') == 'ALL_UIDS_EXACT_SOURCE_PYTEST_ROOT'
         and result.get('release') == release and result.get('nonce') == request['nonce']
         and result.get('keysSha256') == hashlib.sha256(encoded(request['keys'])).hexdigest()
         and result.get('socketKeysSha256') == hashlib.sha256(encoded(request['socketKeys'])).hexdigest()
         and type(result.get('socketNamespacesChecked')) is int
         and result['socketNamespacesChecked'] >= (1 if socket_keys else 0),
         'ALL_UID_PROCESS_RESPONSE_NOT_BOUND')
    return result


def context(args):
    return {'batch': BATCH, 'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256,
            'authorizationSha256': args.authorization_sha256, 'identity': IDENTITY,
            'sourceSqlAndReportsRetained': True, 'businessDatabaseUntouched': True,
            'excludedBuilds': [225, 229, 266], 'testsExecuted': False}


def admit_growth(growth):
    usage = os.statvfs(ROOT); available = usage.f_bavail * usage.f_frsize
    need(available >= 2 * GIB + growth + MIB, 'MAINTENANCE_CONTROL_RESERVE_REQUIRED')
    return available


def marker_path(release):
    return ROOT / 'verification' / release / 'source-pytest16-retired.json'


def retained_marker(entry):
    path = marker_path(entry['release']); target = ROOT / relative_target(entry['release'])
    if not path.exists():
        need(target.exists(), 'UNRECORDED_TARGET_ABSENCE'); return None
    value = read_json(path, MIB)
    need(value.get('batch') == BATCH and value.get('oldRelease') == entry['release']
         and value.get('sourceProof') == entry['sourceProof'] and value.get('status') == 'REMOVED'
         and not os.path.lexists(target), 'RETIRED_TARGET_REPOPULATED_OR_MARKER_CHANGED')
    need(TAG.fullmatch(value.get('release', ''))
         and value.get('receipt') == str(ROOT / 'inbox' / value['release'] / 'source-pytest-retirement/receipt.json'),
         'RETIREMENT_RECEIPT_PATH_CHANGED')
    receipt = read_json(Path(value['receipt']), MIB)
    need(receipt.get('batch') == BATCH and receipt.get('release') == value['release']
         and receipt.get('identity') == IDENTITY and receipt.get('sourceSqlAndReportsRetained') is True
         and receipt.get('status') in ('COMPLETE', 'PARTIAL_FAILURE')
         and any(row.get('release') == entry['release'] and row.get('status') == 'REMOVED'
                 for row in receipt.get('settled', [])), 'ORIGINAL_RETIREMENT_RECEIPT_REQUIRED')
    return {'release': entry['release'], 'status': 'ALREADY_RETIRED', 'markerSha256': digest(path),
            'originalRelease': value['release']}


def make_plan(args, folder, cleanup, verifier):
    targets = []; current = context(args); remaining = 0
    with cleanup.cleanup_lock(ROOT):
        for entry in APPROVED_ENTRIES:
            with cleanup.attempt_lock(ROOT, entry['release']):
                source_binding(entry, cleanup, verifier)
                existing = retained_marker(entry)
                if existing is not None:
                    targets.append(existing); continue
                target = ROOT / relative_target(entry['release'])
                cleanup.owned_chain(target.parent, ROOT, directory=True)
                tree = inventory(target)
                probe = reference_probe(entry['release'], tree, cleanup)
                value = {'schema': 1, **current, 'oldRelease': entry['release'], 'sourceProof': entry['sourceProof'],
                         'target': relative_target(entry['release']), 'inventory': tree, 'processProbe': probe}
                raw = encoded(value) + b'\n'; need(len(raw) <= MAX_CONTROL, 'ROOT_PLAN_BOUND_EXCEEDED')
                admit_growth(len(raw)); file = folder / ('root-' + entry['release'].split('-')[1] + '.json')
                write_json(file, value)
                targets.append({'release': entry['release'], 'status': 'PLANNED', 'file': file.name,
                    'sha256': digest(file), 'entries': tree['entryCount'], 'allocatedBytes': tree['allocatedBytes']})
                remaining += 1
        need(remaining > 0, 'ALL_EXACT_TARGETS_ALREADY_CONSUMED')
        result = {'schema': 1, 'kind': 'doorhandle-source-pytest-retirement-plan', **current,
                  'status': 'PLANNED', 'targets': targets, 'remainingTargets': remaining,
                  'candidateAllocatedUpperBoundBytes': sum(row.get('allocatedBytes', 0) for row in targets)}
        # Journal events contain only the plan's paths, fixed phases and bounded
        # mode metadata. Reserve their complete upper bound before any deletion.
        journal_bytes = 0
        for row in targets:
            if row['status'] != 'PLANNED': continue
            tree = read_json(folder / row['file'])['inventory']
            journal_bytes += sum(2 * len(encoded({'phase': 'OWNER_MODE_RESTORED', 'path': item['path'], 'mode': 511})) + 128
                                 for item in tree['entries']) + 65536
        result['journalUpperBoundBytes'] = journal_bytes
        admit_growth(journal_bytes + len(encoded(result)))
        write_json(folder / 'plan.json', result)
    return result


def process_start(pid):
    return Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()[19]


def apply(args, folder, plan, cleanup, verifier):
    current = context(args)
    need(all(plan.get(k) == v for k, v in current.items()) and len(plan.get('targets', [])) == 16,
         'PLAN_BELONGS_TO_ANOTHER_ATTEMPT')
    need(digest(folder / 'plan.json') == args.plan_sha256, 'PLAN_SHA_CHANGED')
    claim = {'pid': os.getpid(), 'startTicks': process_start(os.getpid()), **current}
    write_json(folder / 'claim.json', claim)
    usage = os.statvfs(ROOT); before = usage.f_bavail * usage.f_frsize
    settled = []; error_type = code = None; unlinks = {}; began = time.monotonic()
    try:
        before = admit_growth(plan['journalUpperBoundBytes'] + MIB)
        with cleanup.cleanup_lock(ROOT):
            for entry, row in zip(APPROVED_ENTRIES, plan['targets']):
                need(time.monotonic() - began <= MAX_SECONDS and row['release'] == entry['release'], 'APPLY_SCOPE_OR_TIME_CHANGED')
                with cleanup.attempt_lock(ROOT, entry['release']):
                    source_binding(entry, cleanup, verifier)
                    if row['status'] == 'ALREADY_RETIRED':
                        need(retained_marker(entry) == row, 'RETIRED_MARKER_CHANGED'); settled.append(row); continue
                    need(row['file'] == 'root-' + entry['release'].split('-')[1] + '.json', 'ROOT_PLAN_PATH_CHANGED')
                    file = folder / row['file']
                    need(digest(file) == row['sha256'], 'ORIGINAL_ROOT_PLAN_CHANGED')
                    root_plan = read_json(file)
                    need(all(root_plan.get(k) == v for k, v in current.items())
                         and root_plan.get('oldRelease') == entry['release']
                         and root_plan.get('target') == relative_target(entry['release'])
                         and root_plan.get('sourceProof') == entry['sourceProof'], 'ROOT_PLAN_SCOPE_CHANGED')
                    original = root_plan['inventory']; actual = inventory(ROOT / root_plan['target'])
                    need(actual['rootMetadata'] == original['rootMetadata'] and len(actual['entries']) == len(original['entries'])
                         and all(a['path'] == b['path'] and same_metadata(a['metadata'], b['metadata'], unlinks)
                                 for a, b in zip(actual['entries'], original['entries'])), 'TARGET_CHANGED_SINCE_PLAN')
                    probe = reference_probe(entry['release'], actual, cleanup)
                    journal_file = folder / ('root-' + entry['release'].split('-')[1] + '.journal.jsonl')
                    fd = os.open(journal_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(fd, 'wb', buffering=65536) as stream:
                        count = 0
                        def journal(event):
                            nonlocal count
                            stream.write(encoded(event) + b'\n'); count += 1
                            if count % 256 == 0:
                                stream.flush(); os.fsync(stream.fileno()); admit_growth(0)
                                need(time.monotonic() - began <= MAX_SECONDS, 'APPLY_TIME_BOUND_EXCEEDED')
                        try:
                            remove_owned_tree(ROOT, root_plan['target'], original, journal, unlinks)
                        finally:
                            stream.flush(); os.fsync(stream.fileno())
                    result = {'release': entry['release'], 'status': 'REMOVED', 'entries': original['entryCount'],
                              'allocatedBytesBefore': original['allocatedBytes'], 'rootPlanSha256': row['sha256'],
                              'journal': journal_file.name, 'journalSha256': digest(journal_file), 'processProbe': probe}
                    settled.append(result)
                    marker = {'batch': BATCH, 'oldRelease': entry['release'], 'sourceProof': entry['sourceProof'],
                              'status': 'REMOVED', 'release': args.tag, 'receipt': str(folder / 'receipt.json')}
                    write_json(marker_path(entry['release']), marker)
    except BaseException as error:
        error_type = type(error).__name__
        code = error.args[0] if isinstance(error, ValueError) and error.args and re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}', str(error.args[0])) else 'RETIREMENT_FAILED'
    usage = os.statvfs(ROOT)
    result = {'schema': 1, 'kind': 'doorhandle-source-pytest-retirement-receipt', **current,
        'status': 'COMPLETE' if error_type is None and len(settled) == 16 else 'PARTIAL_FAILURE',
        'settled': settled, 'errorType': error_type, 'guardCode': code,
        'planSha256': args.plan_sha256, 'availableBytesBefore': before,
        'availableBytesAfter': usage.f_bavail * usage.f_frsize,
        'finishedAtUtc': datetime.now(timezone.utc).isoformat()}
    write_json(folder / 'receipt.json', result)
    return result


def status(args, folder):
    current = context(args); receipt = folder / 'receipt.json'
    if receipt.exists():
        value = read_json(receipt, MIB)
        need(all(value.get(k) == v for k, v in current.items()), 'TERMINAL_RECEIPT_CONTEXT_CHANGED')
        return {**current, 'status': value['status'], 'terminal': True}
    claim_file = folder / 'claim.json'
    if not claim_file.exists():
        failure_file = folder / 'planning-failure.json'
        if failure_file.exists():
            failure = read_json(failure_file, MIB)
            need(all(failure.get(k) == v for k, v in current.items()) and failure.get('status') == 'PLAN_FAILED',
                 'ORIGINAL_PLAN_FAILURE_CHANGED')
            return {**current, 'status': 'PLAN_FAILED', 'terminal': False, 'planTerminal': True}
        complete_file = folder / 'plan-complete.json'
        if complete_file.exists():
            complete = read_json(complete_file, MIB)
            planner = read_json(folder / 'planning-claim.json', MIB)
            need(all(complete.get(k) == v and planner.get(k) == v for k, v in current.items())
                 and complete.get('planSha256') == digest(folder / 'plan.json'), 'ORIGINAL_PLAN_COMPLETION_CHANGED')
            try: running = process_start(planner['pid']) == planner['startTicks']
            except (FileNotFoundError, ProcessLookupError): running = False
            return {**current, 'status': 'PLANNING' if running else 'PLANNED', 'terminal': False,
                    'planTerminal': not running, 'planSha256': complete['planSha256']}
        planner_file = folder / 'planning-claim.json'
        if planner_file.exists():
            planner = read_json(planner_file, MIB)
            need(all(planner.get(k) == v for k, v in current.items()), 'ORIGINAL_PLANNER_CLAIM_CHANGED')
            try: running = process_start(planner['pid']) == planner['startTicks']
            except (FileNotFoundError, ProcessLookupError): running = False
            return {**current, 'status': 'PLANNING' if running else 'UNKNOWN_PLANNING_RESULT',
                    'terminal': False, 'planTerminal': False, 'running': running}
        return {**current, 'status': 'NOT_ISSUED', 'terminal': False, 'planTerminal': False}
    claim = read_json(claim_file, MIB)
    need(all(claim.get(k) == v for k, v in current.items()), 'ORIGINAL_CLAIM_CHANGED')
    try: running = process_start(claim['pid']) == claim['startTicks']
    except (FileNotFoundError, ProcessLookupError): running = False
    return {**current, 'status': 'RUNNING' if running else 'UNKNOWN_WITHOUT_RECEIPT', 'terminal': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('plan', 'apply', 'status'))
    for name in ('tag', 'commit', 'source-sha256', 'authorization-sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--plan-sha256')
    args = parser.parse_args()
    need(os.geteuid() != 0, 'ROOT_TARGET_MUTATIONS_REFUSED')
    inbox, cleanup, verifier = fixed_modules(args)
    folder = inbox / 'source-pytest-retirement'
    if args.phase == 'plan':
        need(not folder.exists() and not folder.is_symlink(), 'FRESH_RETIREMENT_DIRECTORY_REQUIRED')
        admit_growth(MIB); folder.mkdir(mode=0o700)
        write_json(folder / 'planning-claim.json', {**context(args), 'pid': os.getpid(),
                                                  'startTicks': process_start(os.getpid())})
        try:
            result = make_plan(args, folder, cleanup, verifier)
            write_json(folder / 'plan-complete.json', {**context(args), 'planSha256': digest(folder / 'plan.json')})
        except BaseException as error:
            write_json(folder / 'planning-failure.json', {**context(args), 'status': 'PLAN_FAILED',
                                                        'errorType': type(error).__name__})
            raise
        result = {**context(args), 'status': result['status'], 'planSha256': digest(folder / 'plan.json')}
    else:
        cleanup.owned_chain(folder, ROOT, directory=True)
        if args.phase == 'status': result = status(args, folder)
        else:
            need(SHA.fullmatch(args.plan_sha256 or '') and not (folder / 'claim.json').exists()
                 and not (folder / 'receipt.json').exists(), 'ORIGINAL_APPLY_CANNOT_BE_REPLAYED')
            result = apply(args, folder, read_json(folder / 'plan.json'), cleanup, verifier)
    try: print(json.dumps(result), flush=True)
    except BrokenPipeError: pass
    return 0 if args.phase == 'status' or result['status'] in ('PLANNED', 'COMPLETE') else 2


if __name__ == '__main__':
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    def interrupted(*_): raise KeyboardInterrupt()
    for event in (signal.SIGTERM, signal.SIGINT): signal.signal(event, interrupted)
    try: raise SystemExit(main())
    except (ValueError, OSError, KeyError, TypeError) as error:
        code = error.args[0] if isinstance(error, ValueError) and error.args and re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}', str(error.args[0])) else 'RETIREMENT_REFUSED'
        print(json.dumps({'status': 'REFUSED', 'errorType': type(error).__name__, 'guardCode': code}), file=sys.stderr)
        raise SystemExit(2)
