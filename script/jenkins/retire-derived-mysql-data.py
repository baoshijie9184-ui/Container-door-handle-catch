"""Retire one explicitly approved, stopped test-replica batch; retain its SQL.

This closed batch is separate from container retirement's data-retention contract.
The privileged worker accepts no arbitrary directory and opens no MySQL contents.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager, ExitStack
import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tarfile
import time
import xml.etree.ElementTree as ET
from types import SimpleNamespace

LOADED_SOURCE = None if __name__ == '_approved_worker' else Path(__file__).read_bytes()
BATCH = 'derived-mysql-221-222-235-238-247-v1'
RECENT_BATCH = 'derived-mysql-250-253-256-259-264-268-v1'
FOLLOWUP_BATCH = 'derived-mysql-281-283-v1'
ROOT = Path('/home/ecs-user/doorhandle-ci')
INSTANCE = 'i-2zeieuov2aum486jm1ek'
MACHINE = '1ebe8f77e3104ab6a49a9386e38abd20'
TARGETS = {
    'ci-221-8c30776fcd95': (3940427, '8c30776fcd95ed6347494ce5904e5ad7de1867ab'),
    'ci-222-936bdb3e91e2': (3958297, '936bdb3e91e23cbc7daf717333f326b61d43170f'),
    'ci-235-7067d66585cd': (2177178, '7067d66585cd181f4ef8d5cf2345eb4e7851ff17'),
    'ci-238-73ce5aeff862': (2177592, '73ce5aeff86201d9b2776159903acd5907c8420a'),
    'ci-247-abb4a9f35efc': (2697383, 'abb4a9f35efc510d2ef8aa3dec8a42c109395b06'),
}
BACKUP_MANIFESTS = {
    'ci-221-8c30776fcd95': 'fead750efa908141dfad088aebdcf1c9b084b29306f24f5bc0bf45332f077677',
    'ci-222-936bdb3e91e2': '2b596eefe4174de416b29d1b48013b0763f9a627553fb9504a0f458cfdb9ed50',
    'ci-235-7067d66585cd': '5708d62019777e0e9a69e603a17c8803dc5a7d0e89ed97abda36b7839a4d3fc8',
    'ci-238-73ce5aeff862': 'fafd2fb2fa55b4ec2c6d80500d372ccdee6be721da7322c9a70f398e8c2840ac',
    'ci-247-abb4a9f35efc': '8ed4185781611e1905547a178aa0d70484274e2288133a89ab0b31b10279c129',
}
SOURCE_SNAPSHOT = '147dd664c907f079970a0317af60d78eba893010725093d96190e0dd37fd8d82'
APPROVED_METADATA = {
    'ci-221-8c30776fcd95': (311, 265048064),
    'ci-222-936bdb3e91e2': (300, 262062080),
    'ci-235-7067d66585cd': (311, 266653696),
    'ci-238-73ce5aeff862': (328, 289935360),
    'ci-247-abb4a9f35efc': (311, 266706944),
}
RECENT_TARGETS = {
    'ci-250-6444cbc36a65': (1525007, '6444cbc36a653a5e068d95c3138d67ab0b9ca01c'),
    'ci-253-e441933dc75b': (2310434, 'e441933dc75bde0f1fb09cf8e6de4c15130eddfb'),
    'ci-256-9f90b9283367': (1918346, '9f90b92833678240188a0ea68a2ec8ca3d137605'),
    'ci-259-516614e07542': (2965403, '516614e0754249d062103ed64f3d5337fdbee29e'),
    'ci-264-2ff9edc00291': (2050112, '2ff9edc00291f558d6a267f617757911d128ad3e'),
    'ci-268-b3f23013513b': (3610894, 'b3f23013513b11af5041c67569a8f029651aa8db'),
}
RECENT_BACKUP_MANIFESTS = {
    'ci-250-6444cbc36a65': '091403eed082fd4b37c897090417124402979f823814777c61bb06e27d7e5078',
    'ci-253-e441933dc75b': '4b8150d34f16df5cccdb024047cf11537fea3f656baf725e2042cf514479471b',
    'ci-256-9f90b9283367': 'b6f2e2ef20156fef963057fbf504a7940c3ca03e30d564f59dcb3de34034a5a4',
    'ci-259-516614e07542': 'b60c394e2ef33ab948dd95fa4d90ff2983ec14ad1a1e0fcb358e9ac0ee1704e5',
    'ci-264-2ff9edc00291': '9bc30ad8b14a3ceabc74b2e681698c9cb3e714b6e3ca498a3fd114ce671d3c68',
    'ci-268-b3f23013513b': '70eeb86a4e386d8bfba4b93141bbf4d2c57d9cf06db04ed2fa8c82f61248820b',
}
RECENT_APPROVED_METADATA = {
    'ci-250-6444cbc36a65': (311, 266702848),
    'ci-253-e441933dc75b': (311, 265072640),
    'ci-256-9f90b9283367': (300, 262090752),
    'ci-259-516614e07542': (300, 262103040),
    'ci-264-2ff9edc00291': (330, 288403456),
    'ci-268-b3f23013513b': (369, 308985856),
}
FOLLOWUP_TARGETS = {
    'ci-281-81244ba1761d': (4474349, '81244ba1761dcd96a1bdfb7e00154c950e778f3e'),
    'ci-283-30f03c1b1535': (1775872, '30f03c1b15354b9585aee1e4594d53f9f57e802c'),
}
FOLLOWUP_BACKUP_MANIFESTS = {
    'ci-281-81244ba1761d': '51f742817aad0d36020af05fad0791147d0ae622167c780c5ba937d02b7f24dc',
    'ci-283-30f03c1b1535': 'e1524fcf84dd2c6981564ee83eccf09ddfaef5d19101e0c7917ae14485a67fbe',
}
FOLLOWUP_APPROVED_METADATA = {
    'ci-281-81244ba1761d': (369, 308858880),
    'ci-283-30f03c1b1535': (374, 311005184),
}
# One historical batch; every original owner, source and terminal control is fixed.
# Fresh privileged inventory is required: UID 1000 cannot census UID 999 data.
HISTORICAL_BATCH = 'derived-mysql-historical-15-v1'
HISTORICAL_AUTHORIZATION_SHA256 = '07d2830e34d5e685e7a1ee08627d93f7383f2843829c66e844d720ffcbeeb60d'
HISTORICAL_ORIGINALS = {'ci-154-38293aa306b3': {'inode': 2560172,
                         'commit': '38293aa306b368964bbc2a7f66bb6a6b5c414016',
                         'sourceSha256': '22cf2788669de28efe464fe5562e6c428f49c1460e5594c47b337db80267a4e7',
                         'ownerSha256': '58893a1445fbf457b7b6f3ccca2cf1fdb4873427cf8aaeaa5f143a98d92ba368',
                         'cleanupSha256': '706fc44e78c372a4f24883269115fb53d71a9bcb08e916aac0ae6ac52ed5769f',
                         'backupManifestSha256': '3896fbb49c77433ce58dc7d4617948ce90ee3e501e6b0040963a65b46ba779d3',
                         'buildXmlSha256': 'cad53340bb8686809237f28f4e907c3afb4da776540df95735f14513b04006e1',
                         'releaseSha256': '3043c6c401de57827d0f26404579f828dde791baaed3890329707808d764cc3a',
                         'action': 'verify-runtime'},
 'ci-160-9d011d9d5ed8': {'inode': 2560952,
                         'commit': '9d011d9d5ed8ef1b6e5526c0964ee5f405ed421b',
                         'sourceSha256': '2b4e24873373723231f7dc570ed1d1e4f1f3e3b8d82a997eb9502bddbe0ce807',
                         'ownerSha256': '1cc55da69847446def136629c1197f42166fc490df89aa25b846b55e4b6820f7',
                         'cleanupSha256': 'fcafbc894d6ebc279a07a891e82960b0a85fa0e3e010d76770e049f55f498136',
                         'backupManifestSha256': '5492c1ff0c4ea2d5feb27797425adbe8270ce79a1edc965977c074abf0e43142',
                         'buildXmlSha256': 'a03140efd1101637eda372b5e08967b9b53f06d33b1aa829f3c5fb826179c4d7',
                         'releaseSha256': 'd5ddbfee5266fad06a6353f2743f004cf53dc2729d236ff9e0d7175159118454',
                         'action': 'verify-runtime'},
 'ci-162-97844cecb2f4': {'inode': 2945377,
                         'commit': '97844cecb2f45a0e469cda24ceaafdc6df1fee1a',
                         'sourceSha256': 'f86cd22c553bd836589d7a907dbb551de7642053664de637dd763191147569d5',
                         'ownerSha256': '5dac049c56f3fb9c058262d572acb578066501b8ca9c82929d1163c48963d51f',
                         'cleanupSha256': '19bf5ab8158e5f48531e68ef4b51eeec1f6828698a81524ab87c3a0ac80739ff',
                         'backupManifestSha256': '5c91199a236d4246e7bc1bceb11a9161adb324f5476533f657eb6fec283064aa',
                         'buildXmlSha256': '1f7ffb93b99d8ec230f5cad65d6011ccd4d6d11b73bdf877f8fe40eb141da58f',
                         'releaseSha256': '813a191b447827018f260db7e5a8301b599dd6b9a20cc5d67024e110ef512164',
                         'action': 'verify-runtime'},
 'ci-166-a3c084e1cf56': {'inode': 2234796,
                         'commit': 'a3c084e1cf568206baca89908542537ad825fef8',
                         'sourceSha256': 'dd088e18cc079a798accc0ca83773e8b986e6c8ed75e97397427de4e52dd9daf',
                         'ownerSha256': '17ef53267f1bc3d3697303915172f539d26aa16c865fe0058343392cedecc273',
                         'cleanupSha256': '00780e09cd66e3998e4ab8d6e3605adfa76a3373d6ce6e202e2ed9844ae38dd5',
                         'backupManifestSha256': '5f5fb91642e9f041abc12d064d6bef1bb1e942e7b89e15b93d6a6166bdf56a09',
                         'buildXmlSha256': '40821d85a99c310ddb5727ca1c3e63e0af0090f0b84f237ba2ec065ac88c6ea7',
                         'releaseSha256': 'f43bdd8e71e0285b957950c15cece8e2bbcf8d49d3921c46080f4dfd450c8c67',
                         'action': 'verify-runtime'},
 'ci-168-a40c779d03a4': {'inode': 2289269,
                         'commit': 'a40c779d03a43b894ead5569b8eb26ee7dc22a2e',
                         'sourceSha256': 'cb14c65c3001bd83641581dacd9b6dff525b5a777b20686279f5b50dcaec778b',
                         'ownerSha256': 'ccc1b1a998dd32c3d239fd088799a341300d1905fea98b6e7c9cf78b87753312',
                         'cleanupSha256': '0715d15b0c4298c8fbbd87fe2af44403b810374bfd87ff69e7fe1960761c4a98',
                         'backupManifestSha256': '8c8a6000ed85cc17f1670e1a564ccc49b36096cb63280321bfda87c3e069b9db',
                         'buildXmlSha256': 'b018267812a47cc8fffa4f001101a6e8b9d589078d23383da8804f59b1f1d139',
                         'releaseSha256': 'd5681ac691b233bbc2dc5247944de5753df2d1c4f26d4a70ae083d454eafd7c8',
                         'action': 'verify-runtime'},
 'ci-173-45465e873d92': {'inode': 2297030,
                         'commit': '45465e873d92822abe446fd7be3f9f00b7816f70',
                         'sourceSha256': '9453764fb6f2657579eac52e338f7aac599f569552185bde732a557b30244bc9',
                         'ownerSha256': '8957612f1505bf074944cc55b32949d774e2b59e658d09ca4e5503da66a9c753',
                         'cleanupSha256': '0674bcdf94c8d6dea2e95868ac1c91077228726a10e0bf816d81302d7776b968',
                         'backupManifestSha256': '568b50cd980a474f4c35e927270f4375c4746e647245c8479bcb212b9ce6848d',
                         'buildXmlSha256': '4705a0c8386b2f9100872be3369ccde84205a8d2e0474a76f1f34744e9ed8c33',
                         'releaseSha256': '15ebe744170ad5b60753c731c69da4dada0b92d8c2a0632593d072ae56c16f78',
                         'action': 'verify-runtime'},
 'ci-187-8e90ba50c691': {'inode': 2562210,
                         'commit': '8e90ba50c691d561bd26b23f037fec1600e5e9de',
                         'sourceSha256': '00665174617881e678fba2243094fb4f9023d05aea8e55897df05b7b816125b3',
                         'ownerSha256': '6f739e2f431d5e7c5781ca28a8362f907da584dc772fa8f4d631882c6e6d5a6b',
                         'cleanupSha256': '39765f47360f24e0ab95636578874f9875f655885ac36270246a48d575d1c955',
                         'backupManifestSha256': '2d863e80834a3f74a1a201cd47936822eff13240e2237ec22ea2bb68df7106f8',
                         'buildXmlSha256': '58fbf39f782028bb24b5a5b6349153f58d6dee02fc5e077a1025015ee41eb790',
                         'releaseSha256': '8918b549bd5b3d002b25c482721c1784da53626f8b53f31c6bdc74024f38524a',
                         'action': 'verify'},
 'ci-188-df1e1a54d48e': {'inode': 2402459,
                         'commit': 'df1e1a54d48e5005185f53459068fbe9efffe333',
                         'sourceSha256': 'f6fdd55e153ed86dacfc0558fde4c43a897e90383f24831acba25c2f8b0b44a1',
                         'ownerSha256': '9e92c97499c3419792568be7b1358b9d51c7ea5ba57eed3027b08738a2195b2e',
                         'cleanupSha256': '4ed3d6df11e3e31447396a4116c266c3cc7a8d6d5d7bf7d1bf1085a3e03da7e6',
                         'backupManifestSha256': 'fc670779606a32eab496f324cff66572769df8f5ba51309d6a38b2912f1ab5ab',
                         'buildXmlSha256': 'c371f2ee5dae73761241d67607c3bac4f3c4ea5736a0cc178723073ebb9ac03e',
                         'releaseSha256': '269eb1688168ad711121350c1d01ac40efabafa3ba9c961491ee21b14b59763b',
                         'action': 'verify'},
 'ci-189-410506ad7c82': {'inode': 2956711,
                         'commit': '410506ad7c82e302e623a2ac27b63dc345fcd131',
                         'sourceSha256': '2dccb79e757df0d9300fe4395c342945c48c19bcf272a7be2c702f4c6b67a50a',
                         'ownerSha256': '0e9f48ae03af88135d051ce946b83e3a9489a2274b37658ce3e0b04c047a6a70',
                         'cleanupSha256': '69d28e6be3d010e694fd9519126045fb3634226218b4f2eec61afec7c6518dec',
                         'backupManifestSha256': 'e9807254955b8a106b59d7c52e74f15e392c5c0a80f55f9220b193b68375b24b',
                         'buildXmlSha256': '400fbac2f9789b5197d6576aeb19ad74b05051efaf847775be2f06db722d5592',
                         'releaseSha256': '172deefc955730d92929dd48076eef0ad1202837c9116741d6e53497c2a70a86',
                         'action': 'verify'},
 'ci-195-2c2e65a0daa9': {'inode': 3554249,
                         'commit': '2c2e65a0daa94d96b327c59d720871ab70bff0a1',
                         'sourceSha256': 'd9a482a4e3c02d5219199b14f2e65671ebcf3aaf44cfc6d17a61421a1dfb5ec9',
                         'ownerSha256': '499b6a5d99f01be8ffd0d2089a1eaf9c2686c03f1fefa1e298dcf6b62bfd3634',
                         'cleanupSha256': 'ae37240028fe0708e5a7e9500597c126a991f563be6d032a1ec795839b8a221d',
                         'backupManifestSha256': 'c48d4b06b51dca456bfc972686cdfac51c0df5a9f61972253cfdf0ed08ef0b89',
                         'buildXmlSha256': 'eef4e3254af7ad0efe26e24c7147cdc0074aff57a8224a6d4416c09689a3757e',
                         'releaseSha256': '739f9ed1cae2fa36670858313195657d4ddf143139f6acb4806dc58a73df993d',
                         'action': 'verify'},
 'ci-198-7af0903ee840': {'inode': 2641237,
                         'commit': '7af0903ee84011dc51f4abac4f4a4d9679db7322',
                         'sourceSha256': '32715e99750c2651370750cc6a8c9a1d380167b73e2fcacbcf5977c7da1e6453',
                         'ownerSha256': 'cb388e8d56a7c9b689ed493720400ef4423b01ccebf8cd7d8d8237d2f4687d57',
                         'cleanupSha256': 'f670dac478d4ff209524376a0e1f0a8dd91ec7700660b52973ce20e022c3f493',
                         'backupManifestSha256': '345b34fbc3d4ddeb1af0cd5bd96f3ec3ddc9fc850fd0add9c6f5a613ea9e123d',
                         'buildXmlSha256': '2040a791ff1cbbea5ef4754e7643ba7dec202757baef6ffd3cec035c5d8d4dde',
                         'releaseSha256': '79ce2a434d7229ffa090fb5dbd66c70f34cda78c3cf9caae5b6e2b75c6fe80a0',
                         'action': 'verify'},
 'ci-201-803baf401b5f': {'inode': 3569055,
                         'commit': '803baf401b5f9566283a59cb6a885a794b9d7d85',
                         'sourceSha256': '5049079bdb37231b8ca2d59f7865269735ce0ce01cae56d0084a81924fa6767a',
                         'ownerSha256': 'be37826e9778ee357c0929a64f1387aee099e7e4854704b2ec01789fe67ed1f1',
                         'cleanupSha256': '65c627c07013130fd00697c1c9bc3aef0265ac20cf1e2a31bae42fab8c063288',
                         'backupManifestSha256': 'bcf2c5f6ed0779915127991f666c3244db8f26b897b2a20f039d6f9da3fb2daa',
                         'buildXmlSha256': '89208ab76c47359bf029bf51c13b75df649ceb807af603d298eac2be5c48d132',
                         'releaseSha256': '2a380442a9f14158bee647955476430502d21c6e2a23a88ff30cce3079866356',
                         'action': 'verify-runtime'},
 'ci-204-24f8eb4b02bf': {'inode': 3577575,
                         'commit': '24f8eb4b02bf290c6dd4e186eb78c5f3c80f3b88',
                         'sourceSha256': '4b1fed5b2e0f0a80cd0006d7a536eff326f547448c5019ec3ceafa457532bd77',
                         'ownerSha256': '25b99240a0b96723d57a3a181961e4915b283dc91a715eb07e88053fd2001a21',
                         'cleanupSha256': 'dadc3b4f6e72fe67c46d466b62dfea7551601851022c1fc917153dc9c5bf9433',
                         'backupManifestSha256': 'fa72828cbfc54ff96554bb29cf3066bafcecf19e7395b908817f190a2e52a29b',
                         'buildXmlSha256': '36e27ddb0d87daa0d94c3d72cc64e8f70fd4a28ecf7cadecd51054cfafaa5b09',
                         'releaseSha256': '5b0bdad3f157a07a7024f31302525f98ff07e477b1fa86aac5afa5fcbd80546d',
                         'action': 'verify-runtime'},
 'ci-223-fc724a42d8f9': {'inode': 3975407,
                         'commit': 'fc724a42d8f9e625d547cf23fe176463d10531b9',
                         'sourceSha256': '6a3b4908121d6370234baf3ad45f73cad95b071c275bf827574541b037c087f4',
                         'ownerSha256': 'c60afcc644854ce99720fef7b9fa2194336db1e1c8e8cf677dd574e47cbd5712',
                         'cleanupSha256': '53397c46aafb8b075de63413dcb843a1ca661128376468634c7305fb1547440f',
                         'backupManifestSha256': 'f29c0c83470f55191b85cc7e3145a346a7e6dc23e7fa429fedd99042eac14158',
                         'buildXmlSha256': '64d61f2f9866711aedd18c5cce2da17a3634d9c0b1c428d0079ba6d48108f993',
                         'releaseSha256': 'dc6074e33dd6897c102cb04d250ee2d85e05994c91dbf2d011edfd9ab0fe8c1c',
                         'action': 'verify-runtime'},
 'ci-224-e2b445effb49': {'inode': 3992505,
                         'commit': 'e2b445effb49edaf2acd624b60da48a3d1e7f4f3',
                         'sourceSha256': '0cb990150e230ac743c5261fba320de650d94398a8899cef280078a3a6892db4',
                         'ownerSha256': '4a18cef0dbd48d62b4f43c7ae5d0beeec55ec4d2e43b054e02c7e063d2426bf7',
                         'cleanupSha256': 'f7e8b9d878059f921680bf580ea442110b2589cd5e82c7afe1b9e6a76c6a976f',
                         'backupManifestSha256': 'e0273b723d7b266117d54c63096e761859c5a9f3e5ce7b23bf63d807a04012fc',
                         'buildXmlSha256': 'db90074bec0b6deddbfb7065d62a5208d3331dad140a8f2e364bf10de88c2217',
                         'releaseSha256': '335a33bece9bd5d9f9696ed63d7e41744972ce603174daa106483b8d7ff4f99d',
                         'action': 'verify-runtime'}}
SHA = re.compile(r'[a-f0-9]{64}')
MIB = 1024 ** 2
TASK_BATCH = 'current-task-failed-verify-mysql-v1'
TASK_ID = '01a1a46b-d37a-7fb2-8638-afe345c73531'
FINISHED_BATCH = 'manifest-pre-runtime-outputs-v1'
FINISHED_TASK_ID = '01a1de46-3b28-7a21-84e7-4f403268fa01'
# Original #385 failed after its two journaled JAR removals, before any DB
# removal. This is one closed continuation, not permission to ignore missing JARs.
FINISHED_DB_CONTINUATIONS = {
    'ci-383-5400127dd813': {
        'attempt': 'ci-385-74a0f42e52f3',
        'commit': '74a0f42e52f3600a93e83c7123ba52f86e90932b',
        'sourceSha256': '8784cd57e638a8a011eccf78c26e83187a5a4ef8e02b6c4afe803a73684283b5',
        'requestSha256': '6099b996d8d23ead8f6c14b9619d7992e8f8865265f7509a98c18f386055f6d6',
        'planSha256': '646ec0ec18a1ff2a87fecbb473bed4187cf45cb1f4da7715cabcf5482aca8739',
        'receiptSha256': 'eceb1338f60d5a7ccfa253b290206a3949fdf0c4541ad6ce93aceeeabbd083ad',
        'journalSha256': 'b0916ad8a2fbbd5651beac2a98dab3a6d40e9e9d3a2fc0d27d0b49c3064839c9',
        'buildXmlSha256': '5e535bb22a49a295c650fc330743645513e72bd09c89ddebc61e7089540e7747',
    },
}


class TaskBatch:
    """Internal, authenticated target set; never a caller-supplied filesystem path."""
    def __init__(self, targets, manifests):
        self.targets, self.manifests = targets, manifests
        self.metadata = {release: None for release in targets}


def need(value, code):
    if not value:
        raise ValueError(code)


def failure_reason_code(error, *, _seen=()):
    """Publish only a literal guard from executing, authenticated helper bytes."""
    if (not isinstance(error, ValueError) or len(error.args) != 1 or type(error.args[0]) is not str
            or id(error) in _seen or len(_seen) >= 4):
        return 'UNCLASSIFIED_ERROR'
    sources = {LOADED_SOURCE} if LOADED_SOURCE else set()
    trace = error.__traceback__
    while trace is not None:
        source = trace.tb_frame.f_globals.get('LOADED_SOURCE')
        if type(source) is bytes and len(source) <= MIB:
            sources.add(source)
        trace = trace.tb_next
    prefixes = set()
    for source in sources:
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            argument = (node.args[1] if node.func.id in ('need', 'require') and len(node.args) >= 2 else
                        node.args[0] if node.func.id in ('ValueError', 'RetirementError', 'BuildResourceError') and node.args else None)
            if isinstance(argument, ast.Constant) and type(argument.value) is str and argument.value == error.args[0]:
                code = re.sub(r'[^A-Z0-9]+', '_', argument.value.upper()).strip('_')
                if re.fullmatch(r'[A-Z][A-Z0-9_]{1,160}', code): return code
            if (node.func.id == 'RetirementError' and isinstance(argument, ast.BinOp)
                    and isinstance(argument.op, ast.Add) and isinstance(argument.left, ast.Constant)
                    and type(argument.left.value) is str
                    and re.fullmatch(r'[A-Z][A-Z0-9_]{1,80}_', argument.left.value)):
                prefixes.add(argument.left.value)
    # A fixed wrapper may retain a safe inner guard, but never an arbitrary
    # suffix copied from exception text. ``raise ... from None`` keeps context.
    context = error.__cause__ or error.__context__
    if prefixes and context is not None:
        inner = failure_reason_code(context, _seen=(*_seen, id(error)))
        for prefix in prefixes:
            # Older cleanup codecs omit direct ``raise ValueError`` literals.
            # Resolve only the authenticated inner guard, never a guessed suffix.
            if (inner != 'UNCLASSIFIED_ERROR'
                    and error.args[0] in (prefix + inner, prefix + 'UNCLASSIFIED_VALIDATION_ERROR')
                    and re.fullmatch(r'[A-Z][A-Z0-9_]{1,160}', prefix + inner)):
                return prefix + inner
    return 'UNCLASSIFIED_ERROR'


def failure_locations(error):
    """Bounded source coordinates only; no exception text, arguments or paths."""
    locations = []; seen = set()
    while error is not None and id(error) not in seen and len(seen) < 4:
        seen.add(id(error)); trace = error.__traceback__
        while trace is not None:
            source = trace.tb_frame.f_globals.get('LOADED_SOURCE')
            if type(source) is bytes and len(source) <= MIB:
                names = {node.name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef)}
                code = trace.tb_frame.f_code; name = Path(code.co_filename).name
                if (name in ('retire-derived-mysql-data.py', 'retire-failed-native-jar-duplicates.py',
                             'cleanup-ecs-builds.py', 'compact-build-resources.py', 'verify-remote.py')
                        and code.co_name in names and 0 < trace.tb_lineno <= len(source.splitlines())):
                    locations.append({'file': name, 'function': code.co_name, 'line': trace.tb_lineno})
            trace = trace.tb_next
        error = error.__cause__ or error.__context__
    return locations[-8:]


def batch_configuration(batch=BATCH):
    # Preserve the original default and select exactly one closed set, never a union.
    if isinstance(batch, TaskBatch):
        return batch.targets, batch.manifests, batch.metadata
    if batch == BATCH:
        return TARGETS, BACKUP_MANIFESTS, APPROVED_METADATA
    if batch == RECENT_BATCH:
        need(set(RECENT_TARGETS) == set(RECENT_BACKUP_MANIFESTS) == set(RECENT_APPROVED_METADATA),
             'COMPLETE_APPROVED_BATCH_REQUIRED')
        return RECENT_TARGETS, RECENT_BACKUP_MANIFESTS, RECENT_APPROVED_METADATA
    if batch == HISTORICAL_BATCH:
        need(len(HISTORICAL_ORIGINALS) == 15, 'COMPLETE_APPROVED_BATCH_REQUIRED')
        return ({release: (row['inode'], row['commit']) for release, row in HISTORICAL_ORIGINALS.items()},
                {release: row['backupManifestSha256'] for release, row in HISTORICAL_ORIGINALS.items()},
                {release: None for release in HISTORICAL_ORIGINALS})
    need(batch == FOLLOWUP_BATCH, 'CLOSED_BATCH_REQUIRED')
    need(len(FOLLOWUP_TARGETS) == 2
         and set(FOLLOWUP_TARGETS) == set(FOLLOWUP_BACKUP_MANIFESTS) == set(FOLLOWUP_APPROVED_METADATA),
         'COMPLETE_APPROVED_BATCH_REQUIRED')
    return FOLLOWUP_TARGETS, FOLLOWUP_BACKUP_MANIFESTS, FOLLOWUP_APPROVED_METADATA


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def signature(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_blocks]


def safe(path):
    path = Path(path)
    need(path.is_absolute() and path.resolve(strict=True) == path, 'CANONICAL_PATH_REQUIRED')
    need(all(not p.is_symlink() for p in (path, *path.parents)), 'LINKED_PATH_REFUSED')
    return path


def read(path, maximum=2 * MIB):
    path = safe(path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
             and not before.st_mode & 0o022 and 0 <= before.st_size <= maximum, 'PRIVATE_REGULAR_INPUT_REQUIRED')
        raw = stream.read(maximum + 1)
        need(len(raw) == before.st_size and signature(os.fstat(stream.fileno())) == signature(before)
             == signature(path.stat()), 'INPUT_CHANGED')
    return raw


def write(path, value):
    raw = encoded(value); need(len(raw) <= 8 * MIB, 'OUTPUT_BOUND_EXCEEDED')
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as output:
        output.write(raw); output.flush(); os.fsync(output.fileno())


def data_path(release, batch=BATCH):
    targets, _, _ = batch_configuration(batch)
    need(release in targets, 'CLOSED_BATCH_TARGET_REQUIRED')
    return ROOT / 'verification' / release / 'checkout/work/compact-fixtures/mysql-data'


def tree(release, batch=BATCH):
    targets, _, metadata = batch_configuration(batch)
    path = safe(data_path(release, batch)); before = path.stat(); expected = targets[release][0]
    need(stat.S_ISDIR(before.st_mode) and before.st_dev == 64771 and before.st_ino == expected
         and before.st_uid == 999 and before.st_gid == 1000 and stat.S_IMODE(before.st_mode) == 0o700,
         'ORIGINAL_DERIVED_DIRECTORY_REQUIRED')
    rows = []; deadline = time.monotonic() + 20
    def visit(fd, prefix='', depth=0):
        need(depth <= 32 and time.monotonic() < deadline, 'INVENTORY_BOUND_EXCEEDED')
        for name in sorted(os.listdir(fd)):
            need(len(rows) < 10000 and time.monotonic() < deadline, 'INVENTORY_BOUND_EXCEEDED')
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            need(info.st_dev == before.st_dev and info.st_uid == 999
                 and (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode) and info.st_nlink == 1),
                 'DERIVED_ENTRY_LINK_OWNER_OR_DEVICE_DIFFERS')
            relative = prefix + name; rows.append({'path': relative, 'metadata': signature(info)})
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    need(signature(os.fstat(child)) == signature(info), 'DIRECTORY_CHANGED')
                    visit(child, relative + '/', depth + 1)
                finally:
                    os.close(child)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        need(signature(os.fstat(fd)) == signature(before), 'ROOT_CHANGED')
        visit(fd)
    finally:
        os.close(fd)
    need(signature(path.stat()) == signature(before), 'ROOT_CHANGED')
    files = sum(stat.S_ISREG(row['metadata'][2]) for row in rows)
    allocated = before.st_blocks * 512 + sum(row['metadata'][9] * 512 for row in rows)
    if metadata[release] is not None:
        need((files, allocated) == metadata[release], 'APPROVED_METADATA_INVENTORY_CHANGED')
    return {'release': release, 'path': str(path), 'rootMetadata': signature(before), 'entries': rows,
            'allocatedBytes': allocated, 'files': files,
            'inventorySha256': digest(encoded(rows))}


def remove_tree(item, batch=BATCH):
    release = item['release']; path = data_path(release, batch)
    need(tree(release, batch) == item, 'DERIVED_TREE_CHANGED_AFTER_PLAN')
    entries = {row['path']: row['metadata'] for row in item['entries']}
    def remove(fd, prefix=''):
        for name in sorted(os.listdir(fd)):
            relative = prefix + name
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            need(relative in entries and signature(info) == entries[relative], 'ENTRY_CHANGED_AFTER_PLAN')
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    need(signature(os.fstat(child)) == entries[relative], 'DIRECTORY_CHANGED_AFTER_PLAN')
                    remove(child, relative + '/')
                finally:
                    os.close(child)
                os.rmdir(name, dir_fd=fd)
            else:
                need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'LINKED_DELETION_REFUSED')
                os.unlink(name, dir_fd=fd)
    parent = os.open(safe(path.parent), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open('mysql-data', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            need(signature(os.fstat(fd)) == item['rootMetadata'], 'ROOT_CHANGED_AFTER_PLAN')
            remove(fd)
        finally:
            os.close(fd)
        # Child removal changes directory times/size; its original inode/owner must remain.
        info = os.stat('mysql-data', dir_fd=parent, follow_symlinks=False)
        need([info.st_dev, info.st_ino, info.st_uid, info.st_gid]
             == [item['rootMetadata'][i] for i in (0, 1, 3, 4)], 'ROOT_REPLACED_DURING_RETIREMENT')
        os.rmdir('mysql-data', dir_fd=parent)
    finally:
        os.close(parent)


def process_references(inventories, proc=Path('/proc')):
    """Administrator metadata check for every user, including root and MySQL.

    Paths and inode identities cover chroot/mount aliases. Never return argv,
    map contents, descriptor names, or unrelated process paths to the controller.
    ``proc`` is an internal synthetic-test injection, not a CLI/root request.
    """
    need(os.getuid() == 0, 'ROOT_REFERENCE_PROBE_REQUIRED')
    roots = [Path(item['path']) for item in inventories]
    inode_keys = set()
    for item in inventories:
        for meta in (item['rootMetadata'], *(row['metadata'] for row in item['entries'])):
            inode_keys.add((meta[0], meta[1]))
    map_keys = {(os.major(dev), os.minor(dev), inode) for dev, inode in inode_keys}
    def refers(value):
        text = os.fsdecode(value).removesuffix(' (deleted)')
        if '=' in text and not text.startswith('/'): text = text.split('=', 1)[1]
        path = Path(text)
        return path.is_absolute() and any(path == root or path.is_relative_to(root) for root in roots)
    def inode_ref(path):
        info = os.stat(path)
        return (info.st_dev, info.st_ino) in inode_keys
    def bounded(path, maximum):
        with path.open('rb') as stream: raw = stream.read(maximum + 1)
        need(len(raw) <= maximum, 'PROCESS_METADATA_BOUND_EXCEEDED')
        return raw
    def process_state(entry):
        raw = bounded(entry / 'stat', 4096)
        fields = raw.rsplit(b')', 1)[1].split()
        need(raw.split(b' ', 1)[0] == entry.name.encode('ascii') and len(fields) >= 20, 'PROCESS_STAT_INVALID')
        return fields[0].decode('ascii'), int(fields[6]), fields[19].decode('ascii')
    entries = list(proc.iterdir()); need(len(entries) <= 65536, 'PROCESS_COUNT_BOUND_EXCEEDED')
    checked = 0; users = set()
    for entry in entries:
        if not entry.name.isdecimal() or int(entry.name) == os.getpid(): continue
        try:
            before = entry.stat(); state, flags, ticks = process_state(entry)
            if state in ('Z', 'X') or flags & 0x00200000: continue  # No userspace references.
            for name in ('cwd', 'root'):
                pointer = entry / name
                need(not refers(os.readlink(pointer)) and not inode_ref(pointer), 'ACTIVE_PROCESS_DIRECTORY_REFERENCE')
            argv = bounded(entry / 'cmdline', MIB)
            need(not any(refers(arg) for arg in argv.split(b'\0') if arg), 'ACTIVE_PROCESS_ARGUMENT_REFERENCE')
            descriptors = list((entry / 'fd').iterdir())
            need(len(descriptors) <= 8192, 'PROCESS_DESCRIPTOR_BOUND_EXCEEDED')
            for descriptor in descriptors:
                try:
                    need(not refers(os.readlink(descriptor)) and not inode_ref(descriptor), 'ACTIVE_PROCESS_FILE_REFERENCE')
                except (FileNotFoundError, ProcessLookupError):
                    try: descriptor.lstat()
                    except (FileNotFoundError, ProcessLookupError): continue
                    raise ValueError('PROCESS_DESCRIPTOR_CHANGED_DURING_PROBE')
            maps = bounded(entry / 'maps', 16 * MIB)
            for line in maps.splitlines():
                fields = line.split(None, 5)
                need(len(fields) >= 5, 'PROCESS_MAP_METADATA_INVALID')
                major, minor = (int(value, 16) for value in fields[3].split(b':'))
                need((major, minor, int(fields[4])) not in map_keys
                     and not (len(fields) == 6 and refers(fields[5])), 'ACTIVE_PROCESS_MAP_REFERENCE')
            after = entry.stat(); _, _, after_ticks = process_state(entry)
            need((before.st_dev, before.st_ino, before.st_uid) == (after.st_dev, after.st_ino, after.st_uid)
                 and ticks == after_ticks, 'PROCESS_IDENTITY_CHANGED_DURING_PROBE')
            checked += 1; users.add(before.st_uid)
        except (FileNotFoundError, ProcessLookupError):
            if not entry.exists(): continue
            state, flags, _ = process_state(entry)
            need(state in ('Z', 'X') or flags & 0x00200000, 'LIVE_PROCESS_METADATA_UNAVAILABLE')
    return {'status': 'QUIESCENT', 'scope': 'ALL_UIDS_CLOSED_DATA_DIRECTORIES',
            'processesChecked': checked, 'uidsChecked': sorted(users)}


def root_worker(request):
    if request.get('phase') in ('task-inventory', 'task-remove'):
        return task_root_worker(request)
    need(os.getuid() == 0 and request.get('batch') in (BATCH, RECENT_BATCH, FOLLOWUP_BATCH, HISTORICAL_BATCH)
         and Path('/etc/machine-id').read_text().strip() == MACHINE, 'APPROVED_ROOT_BATCH_REQUIRED')
    batch = request['batch']; selected, _, _ = batch_configuration(batch)
    phase = request.get('phase'); need(phase in ('inventory', 'remove'), 'ROOT_OPERATION_REFUSED')
    if phase == 'inventory':
        need(set(request) == {'phase', 'batch'}, 'ARBITRARY_ROOT_ARGUMENT_REFUSED')
        targets = [tree(release, batch) for release in selected]
        return {'targets': targets, 'processProbe': process_references(targets)}
    need(set(request) == {'phase', 'batch', 'target'}, 'ARBITRARY_ROOT_ARGUMENT_REFUSED')
    item = request['target']; need(item.get('release') in selected, 'CLOSED_BATCH_TARGET_REQUIRED')
    need(tree(item['release'], batch) == item, 'DERIVED_TREE_CHANGED_AFTER_PLAN')
    probe = process_references([item])
    remove_tree(item, batch)
    return {'release': item['release'], 'status': 'REMOVED', 'allocatedBytesBefore': item['allocatedBytes'],
            'processProbe': probe}


def privileged(request):
    need(os.getuid() == 1000 and type(LOADED_SOURCE) is bytes
         and read(Path(__file__).absolute(), MIB) == LOADED_SOURCE, 'ADMITTED_PRIVILEGED_SOURCE_CHANGED')
    payload = LOADED_SOURCE + b'\nprint(json.dumps(root_worker(json.loads(' + repr(encoded(request).decode()).encode() + b'))))\n'
    # The timeout itself has administrator identity, so it can stop its own
    # privileged child before the unprivileged transport deadline expires.
    command = ['sudo', '-n', 'timeout', '--signal=TERM', '--kill-after=2s', '90s', sys.executable, '-I', '-B', '-c',
               "import sys; s=sys.stdin.buffer.read(2097153); assert len(s)<=2097152; exec(compile(s,'<closed-derived-mysql>','exec'),{'__name__':'_approved_worker','__file__':sys.argv[1]})",
               str(Path(__file__).absolute())]
    process = subprocess.run(command, input=payload, capture_output=True, timeout=100)
    need(process.returncode == 0 and len(process.stdout) <= 4 * MIB, 'PRIVILEGED_OPERATION_NOT_CONFIRMED')
    return json.loads(process.stdout)


@contextmanager
def lock(path):
    path = safe(path)
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        need(stat.S_ISREG(info.st_mode) and info.st_uid == 1000 and info.st_nlink == 1
             and not info.st_mode & 0o022, 'EXISTING_PRIVATE_LOCK_REQUIRED')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


@contextmanager
def attempt_lock(release):
    path = safe(ROOT / 'verification' / release)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        need(info.st_uid == 1000 and not info.st_mode & 0o022 and stat.S_ISDIR(info.st_mode),
             'OLD_ATTEMPT_DIRECTORY_OWNER_DIFFERS')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def keeper_binding(release, batch=BATCH):
    targets, manifests, _ = batch_configuration(batch)
    work = data_path(release, batch).parent
    owner_raw = read(work.parent / 'compact-fixtures-owner.json')
    owner = json.loads(owner_raw); cleanup_raw = read(work / 'cleanup-receipt.json'); cleanup = json.loads(cleanup_raw)
    need(owner.get('release') == release and owner.get('commit') == targets[release][1]
         and owner.get('phase') == 'OWNED_SERVER_STOPPED' and owner.get('dataDirectory') == str(data_path(release, batch))
         and owner.get('sourceTableCount') == 131 and SHA.fullmatch(owner.get('sourceSha256', ''))
         and owner.get('sourceClone') == 'doorhandle_migration_verify_' + owner.get('token', '')
         and re.fullmatch(r'[a-f0-9]{10,64}', owner.get('token', ''))
         and owner.get('containerId') != owner.get('sourceContainerId'),
         'OLD_TEST_OWNERSHIP_NOT_PROVEN')
    need(cleanup.get('status') == 'STOPPED' and cleanup.get('errors') == []
         and cleanup.get('containerId') == owner.get('containerId')
         and cleanup.get('dataDirectoryRetained') == str(data_path(release, batch))
         and cleanup.get('sourceDumpAndEvidenceRetained') is True, 'OLD_TEST_STOP_NOT_PROVEN')
    manifest_raw = read(work / 'source-backup/manifest.json'); manifest = json.loads(manifest_raw)
    need(digest(manifest_raw) == owner.get('sourceBackupSha256') == manifests[release]
         and manifest.get('snapshotSha256') == owner.get('sourceSnapshotSha256')
         == owner.get('sourceCloneSnapshotSha256') == SOURCE_SNAPSHOT and len(manifest.get('tables', {})) == 131
         and manifest.get('data', {}).get('file') == 'data.sql', 'COMPLETE_SOURCE_BACKUP_REQUIRED')
    sql = read(work / 'source-backup/data.sql', 128 * MIB)
    need(len(sql) == manifest['data']['bytes'] and digest(sql) == manifest['data']['sha256'], 'SOURCE_SQL_INTEGRITY_FAILED')
    return {'release': release, 'commit': owner['commit'], 'sourceSha256': owner['sourceSha256'],
            'ownerSha256': digest(owner_raw), 'cleanupSha256': digest(cleanup_raw),
            'backupManifestSha256': digest(manifest_raw), 'sourceSqlSha256': digest(sql),
            'sourceSqlBytes': len(sql), 'sourceSnapshotSha256': owner['sourceSnapshotSha256'],
            'token': owner['token']}


def historical_terminal(raw, release, original):
    need(b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(), 'HISTORICAL_XML_DECLARATION_REFUSED')
    root = ET.fromstring(raw)
    need(root.tag == 'flow-build' and len(root.findall('result')) == 1
         and root.findtext('result') in ('FAILURE', 'ABORTED')
         and root.findtext('completed') == 'true' and root.findtext('execution/done') == 'true',
         'HISTORICAL_FINISHED_BUILD_REQUIRED')
    parameters = {}
    for item in root.findall('./actions/hudson.model.ParametersAction/parameters/*'):
        name = item.findtext('name')
        need(name and name not in parameters, 'HISTORICAL_DUPLICATE_PARAMETER')
        parameters[name] = item.findtext('value')
    need(parameters.get('ACTION') == original['action']
         and parameters.get('DOORHANDLE_CI_SCOPE') == 'mysql'
         and parameters.get('TRUSTED_COMMIT') == original['commit']
         and parameters.get('PRODUCTION_RELEASE_ENABLED') == 'false'
         and release.endswith(original['commit'][:12]), 'HISTORICAL_BUILD_CONTEXT_DIFFERS')


def historical_originals(release, current, keeper):
    """Add custody and fixed producer proof only for the explicitly reviewed 15."""
    need(release in HISTORICAL_ORIGINALS, 'CLOSED_BATCH_TARGET_REQUIRED')
    original = HISTORICAL_ORIGINALS[release]
    need(all(keeper.get(key) == original[key] for key in
             ('commit', 'sourceSha256', 'ownerSha256', 'cleanupSha256', 'backupManifestSha256')),
         'HISTORICAL_KEEPER_IDENTITY_CHANGED')
    controls = ROOT / 'inbox' / current / 'historical-derived-controls'
    need(digest(read(controls / 'authorization.json')) == HISTORICAL_AUTHORIZATION_SHA256,
         'HISTORICAL_USER_AUTHORIZATION_REQUIRED')
    build_raw = read(controls / release / 'build.xml', 4 * MIB)
    release_raw = read(controls / release / 'release.json')
    need(digest(build_raw) == original['buildXmlSha256'] and digest(release_raw) == original['releaseSha256'],
         'HISTORICAL_ORIGINAL_CONTROL_CHANGED')
    historical_terminal(build_raw, release, original)
    context = json.loads(release_raw)
    need(context.get('release') == release and all(context.get(key) == original[key]
         for key in ('commit', 'sourceSha256')), 'HISTORICAL_RELEASE_CONTEXT_DIFFERS')
    source = read(ROOT / 'inbox' / release / 'source.tar.gz', 128 * MIB)
    need(digest(source) == original['sourceSha256'], 'HISTORICAL_SOURCE_INTEGRITY_FAILED')
    names = ('script/jenkins/prepare-compact-fixtures.py', 'script/schema/compact_migration_runtime.py',
             'docs/database/compact-schema-contract.json')
    bodies = {}
    with tarfile.open(fileobj=io.BytesIO(source), mode='r:gz') as archive:
        need(archive.pax_headers.get('comment') == original['commit'], 'HISTORICAL_SOURCE_COMMIT_DIFFERS')
        for member in archive:
            if member.name not in names:
                continue
            need(member.name not in bodies and member.isfile() and 0 < member.size <= MIB,
                 'HISTORICAL_PRODUCER_CLOSURE_DIFFERS')
            bodies[member.name] = archive.extractfile(member).read(MIB + 1)
    need(set(bodies) == set(names), 'HISTORICAL_PRODUCER_CLOSURE_MISSING')
    contract = json.loads(bodies[names[2]])
    need(type(contract.get('sourceTables')) is list and len(contract['sourceTables']) == 131,
         'HISTORICAL_SOURCE_TABLE_CONTRACT_DIFFERS')
    return {'buildXmlSha256': original['buildXmlSha256'], 'releaseSha256': original['releaseSha256'],
            'authorizationSha256': HISTORICAL_AUTHORIZATION_SHA256}


def fixed_helpers(args):
    import tarfile
    # Maintenance deliberately uses a separate source transport from runtime CI.
    source = read(ROOT / 'inbox' / args.tag / 'cleanup-source.tar.gz', 128 * MIB)
    need(digest(source) == args.source_sha256, 'FIXED_SOURCE_CHANGED')
    import io
    names = ('retire-derived-mysql-data.py', 'cleanup-ecs-builds.py', 'verify-remote.py')
    bodies = {}
    with tarfile.open(fileobj=io.BytesIO(source), mode='r:gz') as archive:
        need(archive.pax_headers.get('comment') == args.commit, 'FIXED_SOURCE_COMMIT_DIFFERS')
        for member in archive:
            if member.name not in ('script/jenkins/' + name for name in names):
                continue
            name = member.name.rsplit('/', 1)[-1]
            need(name not in bodies and member.isfile() and 0 < member.size <= MIB, 'FIXED_HELPER_CLOSURE_DIFFERS')
            bodies[name] = archive.extractfile(member).read(MIB + 1)
    need(set(bodies) == set(names), 'FIXED_HELPER_CLOSURE_MISSING')
    modules = {}
    for name in names:
        path = ROOT / 'inbox' / args.tag / name
        need(read(path, MIB) == bodies[name], 'FIXED_HELPER_BYTES_DIFFER')
        if name == names[0]:
            need(Path(__file__).absolute() == path and bodies[name] == LOADED_SOURCE, 'FIXED_EXECUTOR_REQUIRED')
            continue
        spec = importlib.util.spec_from_file_location('derived_' + name.replace('-', '_'), path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); modules[name] = module
    return modules


def run(args):
    if getattr(args, 'failed_builds', None) is not None:
        return task_run(args)
    need(os.getuid() == 1000 and args.batch in (BATCH, RECENT_BATCH, FOLLOWUP_BATCH, HISTORICAL_BATCH) and re.fullmatch(r'ci-[0-9]+-[a-f0-9]{12}', args.tag)
         and re.fullmatch(r'[a-f0-9]{40}', args.commit) and args.tag.endswith(args.commit[:12])
         and int(args.tag.split('-')[1]) > (271 if args.batch == BATCH else 278 if args.batch == RECENT_BATCH else 283 if args.batch == FOLLOWUP_BATCH else 377)
         and SHA.fullmatch(args.source_sha256), 'EXPLICIT_FIXED_MAINTENANCE_REQUIRED')
    batch = args.batch; targets, _, _ = batch_configuration(batch)
    modules = fixed_helpers(args); verifier = modules['verify-remote.py']; cleanup = modules['cleanup-ecs-builds.py']
    identity = verifier.ecs_identity(INSTANCE, MACHINE)
    output = ROOT / 'inbox' / args.tag / 'derived-mysql-retirement'
    plan_file = output / 'plan-private.json'; public_file = output / 'plan.json'; receipt_file = output / 'receipt.json'
    execution_file = output / 'execution.json'
    if args.phase == 'status':
        binding = {'batch': batch, 'release': args.tag, 'commit': args.commit,
                   'sourceSha256': args.source_sha256, 'identity': identity}
        if receipt_file.exists():
            value = json.loads(read(receipt_file))
            need(all(value.get(key) == expected for key, expected in binding.items()), 'TERMINAL_BINDING_DIFFERS')
            return {'status': value['status'], 'terminal': True, **binding}
        if execution_file.exists():
            execution = json.loads(read(execution_file))
            need(all(execution.get(key) == expected for key, expected in binding.items())
                 and execution.get('bootId') == Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                 'EXECUTION_IDENTITY_DIFFERS')
            try:
                raw_stat = Path('/proc') / str(execution['pid']) / 'stat'
                fields = raw_stat.read_text().rsplit(')', 1)[1].split()
                alive = fields[19] == execution['startTicks'] and fields[0] not in ('Z', 'X')
            except FileNotFoundError:
                alive = False
            need(alive, 'EXECUTION_STOPPED_WITHOUT_TERMINAL_RECEIPT')
            return {'status': 'RUNNING', 'terminal': False, **binding}
        return {'status': 'UNKNOWN', 'terminal': False, **binding}
    def admitted():
        containers = cleanup.docker_snapshot(); result = []
        for release in targets:
            need(not (ROOT / 'releases' / release).exists(), 'RETAINED_PUBLISHED_RELEASE_REFUSED')
            value = keeper_binding(release, batch)
            if batch == HISTORICAL_BATCH:
                value.update(historical_originals(release, args.tag, value))
            cleanup.quiescent({'checkout': data_path(release, batch).parents[2], 'token': value['token']},
                              release, containers, include_inbox=True)
            result.append(value)
        return result
    with lock(ROOT / 'state/deploy.lock'), ExitStack() as attempts:
        for release in targets:
            attempts.enter_context(attempt_lock(release))
        if args.phase == 'plan':
            need(not output.exists(), 'FRESH_DERIVED_RETIREMENT_REQUIRED'); output.mkdir(mode=0o700)
            keepers = admitted(); measurement = privileged({'phase': 'inventory', 'batch': batch})
            inventory = measurement['targets']
            need(measurement['processProbe']['status'] == 'QUIESCENT', 'ALL_UID_REFERENCE_PROOF_REQUIRED')
            need([item['release'] for item in inventory] == list(targets), 'COMPLETE_CLOSED_INVENTORY_REQUIRED')
            plan = {'batch': batch, 'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256,
                    'identity': identity, 'keepers': keepers, 'targets': inventory,
                    'processProbe': measurement['processProbe']}
            write(plan_file, plan)
            public = {key: plan[key] for key in ('batch', 'release', 'commit', 'sourceSha256', 'identity')}
            public.update(planSha256=digest(encoded(plan)), targets=[{key: item[key] for key in
                ('release', 'path', 'allocatedBytes', 'files', 'inventorySha256')} for item in inventory],
                sourceSqlAndReportsRetained=True, processProbe=measurement['processProbe'])
            write(public_file, public)
            return {'status': 'PLANNED', 'file': str(public_file), 'privatePlanSha256': digest(encoded(plan))}
        raw = read(plan_file, 8 * MIB); plan = json.loads(raw)
        need(SHA.fullmatch(args.plan_sha256 or '') and digest(raw) == args.plan_sha256
             and all(plan.get(key) == expected for key, expected in {'batch': batch, 'release': args.tag,
                 'commit': args.commit, 'sourceSha256': args.source_sha256, 'identity': identity}.items())
             and plan['keepers'] == admitted(), 'PLAN_OR_KEEPERS_CHANGED')
        need(not receipt_file.exists(), 'RETIREMENT_ALREADY_ATTEMPTED')
        write(execution_file, {'batch': batch, 'release': args.tag, 'commit': args.commit,
              'sourceSha256': args.source_sha256, 'identity': identity, 'pid': os.getpid(),
              'startTicks': Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19],
              'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip()})
        receipt = {'status': 'FAILED_OR_UNKNOWN', 'batch': batch, 'release': args.tag,
                   'commit': args.commit, 'sourceSha256': args.source_sha256, 'identity': identity,
                   'planSha256': args.plan_sha256, 'removed': [], 'sourceSqlAndReportsRetained': True,
                   'availableBytesBefore': os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize}
        try:
            measurement = privileged({'phase': 'inventory', 'batch': batch})
            need(measurement['processProbe']['status'] == 'QUIESCENT'
                 and measurement['targets'] == plan['targets'], 'TARGETS_CHANGED_AFTER_PLAN')
            receipt['processProbe'] = measurement['processProbe']
            for item in plan['targets']:
                admitted()
                receipt['removed'].append(privileged({'phase': 'remove', 'batch': batch, 'target': item}))
            need(plan['keepers'] == admitted(), 'KEEPERS_CHANGED_AFTER_RETIREMENT')
            receipt['status'] = 'COMPLETE'
        except BaseException as error:
            receipt['errorType'] = type(error).__name__
            raise
        finally:
            receipt['availableBytesAfter'] = os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize
            write(receipt_file, receipt)
        return {'status': receipt['status'], 'file': str(receipt_file), 'removedDirectories': len(receipt['removed'])}


def task_numbers(text, current):
    need(type(text) is str and re.fullmatch(r'[1-9][0-9]{0,8}(,[1-9][0-9]{0,8}){0,15}', text or ''),
         'EXPLICIT_BOUNDED_TASK_BUILDS_REQUIRED')
    numbers = text.split(',')
    need(len(numbers) == len(set(numbers)) and all(287 <= int(value) < current for value in numbers),
         'ONLY_EARLIER_TASK_FAILED_BUILDS_ALLOWED')
    return numbers


def task_helpers(binding):
    """Load only the current committed maintenance source, including pure validators."""
    need(set(binding) == {'tag', 'commit', 'sourceSha256', 'requestSha256', 'failedBuilds'}
         | ({'batch'} if binding.get('batch') == FINISHED_BATCH else set()),
         'EXACT_TASK_SOURCE_BINDING_REQUIRED')
    tag, commit = binding['tag'], binding['commit']
    need(re.fullmatch(r'ci-[1-9][0-9]*-[a-f0-9]{12}', tag or '') and
         re.fullmatch(r'[a-f0-9]{40}', commit or '') and tag.endswith('-' + commit[:12]) and
         SHA.fullmatch(binding.get('sourceSha256', '')) and SHA.fullmatch(binding.get('requestSha256', '')),
         'FIXED_TASK_SOURCE_REQUIRED')
    task_numbers(binding['failedBuilds'], int(tag.split('-')[1]))
    raw = read(ROOT / 'inbox' / tag / 'cleanup-source.tar.gz', 128 * MIB)
    need(digest(raw) == binding['sourceSha256'], 'FIXED_TASK_SOURCE_CHANGED')
    wanted = {'retire-derived-mysql-data.py', 'retire-failed-native-jar-duplicates.py',
              'cleanup-ecs-builds.py', 'verify-remote.py', 'compact-build-resources.py'}
    bodies = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        need(archive.pax_headers.get('comment') == commit, 'TASK_SOURCE_COMMIT_DIFFERS')
        for member in archive:
            name = member.name.rsplit('/', 1)[-1]
            prefix = 'script/docker/' if name == 'compact-build-resources.py' else 'script/jenkins/'
            if member.name != prefix + name or name not in wanted:
                continue
            need(name not in bodies and member.isfile() and 0 < member.size <= MIB,
                 'TASK_HELPER_CLOSURE_DIFFERS')
            bodies[name] = archive.extractfile(member).read(MIB + 1)
    need(set(bodies) == wanted, 'TASK_HELPER_CLOSURE_MISSING')
    own = read(ROOT / 'inbox' / tag / 'retire-derived-mysql-data.py', MIB)
    need(own == bodies['retire-derived-mysql-data.py'] and
         (os.getuid() == 0 or own == LOADED_SOURCE), 'FIXED_TASK_EXECUTOR_DIFFERS')
    result = {}
    for name in wanted - {'retire-derived-mysql-data.py'}:
        # Compile the already authenticated bytes; never reopen a module after checking it.
        module = SimpleNamespace(__name__='_task_' + name.replace('-', '_'),
                                 __file__=str(ROOT / 'inbox' / tag / name))
        exec(compile(bodies[name], module.__file__, 'exec'), module.__dict__)
        # Some real helpers snapshot their on-disk file during module import.
        # Root fallbacks must use authenticated archive bytes, not that later read.
        module.LOADED_SOURCE = bodies[name]
        result[name] = module
    return result


def task_request(binding):
    raw = read(ROOT / 'inbox' / binding['tag'] / 'derived-failed-mysql-retirement/request.json')
    need(digest(raw) == binding['requestSha256'], 'AUTHENTICATED_TASK_REQUEST_CHANGED')
    def unique(pairs):
        result = {}
        for key, item in pairs:
            need(key not in result, 'DUPLICATE_TASK_REQUEST_FIELD')
            result[key] = item
        return result
    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda _value: need(False, 'NONFINITE_TASK_REQUEST'))
    identity = {'instanceId': INSTANCE, 'machineId': MACHINE, 'executionLocation': 'ECS'}
    expected = {'release': binding['tag'], 'commit': binding['commit'], 'sourceSha256': binding['sourceSha256']}
    finished = binding.get('batch') == FINISHED_BATCH
    need(set(value) == {'schemaVersion', 'kind', 'current', 'identity', 'authorization', 'builds', 'candidates'}
         and type(value['schemaVersion']) is int and value['schemaVersion'] == 1
         and value['kind'] == ('doorhandle-authorized-pre-runtime-outputs-request' if finished else 'doorhandle-authorized-failed-mysql-data-request')
         and value['current'] == expected and value['identity'] == identity,
         'TASK_REQUEST_CONTEXT_DIFFERS')
    authorization = value['authorization']
    need(set(authorization) == {'taskThreadId', 'sourceSha256', 'endsWithTask', 'allowArbitraryPath'}
         | ({'manifestSha256'} if finished else set())
         and authorization['taskThreadId'] == (FINISHED_TASK_ID if finished else TASK_ID)
         and SHA.fullmatch(authorization.get('sourceSha256', ''))
         and (not finished or SHA.fullmatch(authorization.get('manifestSha256', '')))
         and authorization['endsWithTask'] is True and authorization['allowArbitraryPath'] is False,
         'CURRENT_TASK_AUTHORIZATION_REQUIRED')
    numbers = task_numbers(binding['failedBuilds'], int(binding['tag'].split('-')[1]))
    need(value['builds'] == numbers and type(value['candidates']) is list and
         len(value['candidates']) == len(numbers), 'COMPLETE_EXPLICIT_TASK_TARGETS_REQUIRED')
    for number, row in zip(numbers, value['candidates']):
        need(set(row) == {'release', 'commit', 'sourceSha256', 'controls'} | ({'retirement'} if finished else set()) and
             re.fullmatch(r'[a-f0-9]{40}', row.get('commit', '')) and
             row['release'] == 'ci-' + number + '-' + row['commit'][:12] and
             SHA.fullmatch(row.get('sourceSha256', '')), 'CANONICAL_FAILED_TASK_TAG_REQUIRED')
        need(set(row['controls']) == {'buildXml', 'release', 'localBuild', 'fixtureCleanupPublic',
                                      'preparation', 'transport'}, 'COMPLETE_ORIGINAL_TASK_CONTROLS_REQUIRED')
        for reference in row['controls'].values():
            need(set(reference) == {'bytes', 'sha256'} and type(reference['bytes']) is int and
                 0 < reference['bytes'] <= 2 * MIB and SHA.fullmatch(reference.get('sha256', '')),
                 'EXACT_ORIGINAL_TASK_CONTROL_REQUIRED')
        if finished:
            validate_finished_selection(row)
    if any('completedAttempt' in row.get('retirement', {}) for row in value['candidates']):
        need(len(value['candidates']) == 1, 'CLOSED_CONTINUATION_CANNOT_MIX_TARGETS')
    return value


def validate_finished_selection(row):
    """A reviewed manifest chooses resources; it cannot choose filesystem paths."""
    item = row['retirement']
    need(set(item) == {'policy', 'publicationRecipe', 'jarSha256', 'jarBytes', 'dataIdentity', 'jarIdentities'}
         | ({'completedAttempt'} if 'completedAttempt' in item else set())
         and item['policy'] == FINISHED_BATCH and type(item['publicationRecipe']) is list
         and len(item['publicationRecipe']) == 3
         and all(type(value) is str and SHA.fullmatch(value) for value in item['publicationRecipe'])
         and SHA.fullmatch(item.get('jarSha256', '')) and type(item['jarBytes']) is int
         and 0 < item['jarBytes'] <= 512 * MIB, 'EXACT_FINISHED_RESOURCE_SELECTION_REQUIRED')
    identities = [item['dataIdentity'], *item['jarIdentities']]
    need(type(item['jarIdentities']) is list and len(item['jarIdentities']) == 2
         and all(type(value) is list and len(value) == 2 and all(type(part) is int and part > 0 for part in value)
                 for value in identities) and len({tuple(value) for value in identities}) == 3,
         'EXACT_FINISHED_RESOURCE_INODES_REQUIRED')
    if 'completedAttempt' in item:
        approved = FINISHED_DB_CONTINUATIONS.get(row['release'])
        need(approved is not None and item['completedAttempt'] == approved['attempt'],
             'UNREGISTERED_FINISHED_DB_CONTINUATION')


def finished_completed_binaries(binding, row):
    """Bind the original failed operation and its completed deletions, read-only."""
    if 'completedAttempt' not in row['retirement']: return None
    validate_finished_selection(row)
    approved = FINISHED_DB_CONTINUATIONS[row['release']]
    original = ROOT / 'inbox' / approved['attempt']
    directory = original / 'derived-failed-mysql-retirement'
    files = {
        'sourceSha256': original / 'cleanup-source.tar.gz',
        'requestSha256': directory / 'request.json',
        'planSha256': directory / 'plan-private.json',
        'receiptSha256': directory / 'receipt.json',
        'journalSha256': directory / 'jar-journal.jsonl',
        'buildXmlSha256': ROOT / 'inbox' / binding['tag'] / 'failed-mysql-data-controls' /
                             row['release'] / 'completed-maintenance-build.xml',
    }
    raw = {key: read(path, 8 * MIB) for key, path in files.items()}
    need(all(digest(body) == approved[key] for key, body in raw.items()), 'ORIGINAL_CONTINUATION_EVIDENCE_CHANGED')
    terminal = ET.fromstring(raw['buildXmlSha256'].decode('utf-8').replace('version="1.1"', 'version="1.0"', 1))
    need(terminal.findtext('result') == 'FAILURE' and terminal.findtext('completed') == 'true'
         and terminal.findtext('execution/done') == 'true', 'ORIGINAL_FAILED_MAINTENANCE_REQUIRED')
    request, plan, receipt = (json.loads(raw[key]) for key in ('requestSha256', 'planSha256', 'receiptSha256'))
    expected = {key: value for key, value in row.items() if key != 'retirement'}
    expected['retirement'] = {key: value for key, value in row['retirement'].items() if key != 'completedAttempt'}
    need(request['candidates'] == [expected] and request['builds'] == [row['release'].split('-')[1]]
         and request['current'] == {'release': approved['attempt'], 'commit': approved['commit'],
                                   'sourceSha256': approved['sourceSha256']}, 'CONTINUATION_ORIGINAL_SELECTION_DIFFERS')
    need(receipt['status'] == 'FAILED_OR_UNKNOWN' and receipt['removed'] == []
         and receipt['requestSha256'] == approved['requestSha256'] and receipt['planSha256'] == approved['planSha256']
         and plan['roots'][row['release']][:2] == row['retirement']['dataIdentity'], 'CONTINUATION_ORIGINAL_STATE_DIFFERS')
    journal = [json.loads(line) for line in raw['journalSha256'].splitlines()]
    need(len(journal) == 6 and journal[0] == {'phase': 'STARTED', 'planSha256': approved['planSha256'],
                                           'requestSha256': approved['requestSha256']}
         and journal[-1] == {'phase': 'FINISHED', 'deletedFiles': 2}
         and len(receipt['jarRetirements']) == len(plan['jarTargets']) == 2, 'COMPLETED_BINARY_JOURNAL_REQUIRED')
    for index, target in enumerate(plan['jarTargets']):
        need(journal[2 * index + 1]['phase'] == 'DELETE_STARTED'
             and journal[2 * index + 1]['path'] == target['path']
             and journal[2 * index + 2] == {'phase': 'DELETE_FINISHED', **receipt['jarRetirements'][index]}
             and receipt['jarRetirements'][index]['path'] == target['path'], 'COMPLETED_BINARY_PATHS_DIFFER')
        path = ROOT / target['path']
        need(not path.exists() and not path.is_symlink(), 'COMPLETED_BINARY_PATH_REAPPEARED')
    return {'release': row['release'], 'completedAttempt': approved['attempt'],
            'originalStatus': 'FAILED_OR_UNKNOWN', 'planSha256': approved['planSha256'],
            'receiptSha256': approved['receiptSha256'], 'journalSha256': approved['journalSha256'],
            'alreadyRetiredJarBytes': sum(item['allocatedBytes'] for item in receipt['jarRetirements'])}


def finished_runtime_absence(row, preparation, transport, recipe, identity):
    context = {key: row[key] for key in ('release', 'commit', 'sourceSha256')}
    tag = row['release']; base = ROOT / 'verification' / tag
    forbidden = [ROOT / 'releases' / tag, base / 'runtime-execution.json', base / 'runtime-failure.json',
        base / 'runtime-acceptance.json', base / 'checkout/work/runtime-acceptance',
        base / 'checkout/work/candidate-build-resources', base / 'checkout/work/compact-fixtures/runtime-migration.json']
    need(all(not path.exists() and not path.is_symlink() for path in forbidden),
         'CANDIDATE_OR_RUNTIME_ALREADY_ENTERED')
    reference = preparation.get('candidateBuilderTools', {})
    tool_path = ROOT / 'inbox' / tag / 'candidate-build-tools/tools.json'
    need(all(document.get(key) == expected for document in (preparation, transport) for key, expected in context.items())
         and preparation.get('kind') == 'doorhandle-ecs-tool-preparation' and preparation.get('status') == 'PREPARED'
         and preparation.get('identity') == identity and preparation.get('testsExecuted') is False
         and preparation.get('sourceFiles', {}).get('script/jenkins/prepare-ecs-tools.py') == recipe['toolPreparationHelperSha256']
         and reference.get('file') == str(tool_path) and reference.get('status') == 'PREPARED'
         and SHA.fullmatch(reference.get('sha256', ''))
         and transport.get('kind') == 'doorhandle-public-build-input-transport' and transport.get('status') == 'AVAILABLE'
         and transport.get('buildkitArchive') == preparation.get('buildkitArchive'),
         'PREPARED_TOOLS_ORIGINAL_BINDING_REQUIRED')
    raw = read(tool_path); tools = json.loads(raw)
    need(digest(raw) == reference['sha256']
         and all(tools.get(key) == expected for key, expected in context.items())
         and tools.get('kind') == 'doorhandle-candidate-build-tools' and tools.get('status') == 'PREPARED'
         and tools.get('identity') == identity and tools.get('imageId') == reference.get('imageId'),
         'PREPARED_TOOLS_RECEIPT_CHANGED')
    return {'toolsSha256': digest(raw), 'candidateRuntimeEntered': False}


def task_source_recipe(native, row):
    raw = read(ROOT / 'inbox' / row['release'] / 'source.tar.gz', 128 * MIB)
    need(digest(raw) == row['sourceSha256'], 'RETAINED_TASK_SOURCE_CHANGED')
    names = ('Jenkinsfile.ecs-monolith', 'script/jenkins/pipeline.ps1', 'script/jenkins/prepare-ecs-tools.py')
    bodies = {}
    class Bounded:
        def __init__(self, source): self.source, self.total = source, 0
        def read(self, size=-1):
            remaining = 512 * MIB - self.total
            block = self.source.read(remaining + 1 if size < 0 else min(size, remaining + 1))
            self.total += len(block)
            need(self.total <= 512 * MIB, 'RETAINED_TASK_SOURCE_EXPANSION_BOUND')
            return block
    import gzip
    with gzip.GzipFile(fileobj=io.BytesIO(raw), mode='rb') as expanded, tarfile.open(fileobj=Bounded(expanded), mode='r|') as archive:
        need(archive.pax_headers.get('comment') == row['commit'], 'RETAINED_TASK_COMMIT_DIFFERS')
        for index, member in enumerate(archive, 1):
            need(index <= 50000 and 0 <= member.size <= 32 * MIB, 'RETAINED_TASK_SOURCE_MEMBER_BOUND')
            if member.name in names:
                need(member.name not in bodies and member.isfile() and 0 < member.size <= MIB,
                     'ORIGINAL_TASK_RECIPE_INVALID')
                bodies[member.name] = archive.extractfile(member).read(MIB + 1)
    actual = [digest(bodies[name]) for name in names] if set(bodies) == set(names) else []
    finished = row.get('retirement', {}).get('policy') == FINISHED_BATCH
    need(set(bodies) == set(names) and
         (actual == row['retirement']['publicationRecipe'] if finished else native.database_verification_recipe(
             tuple(actual[:2]), actual[2])),
         'REVIEWED_VERIFY_ONLY_TASK_SOURCE_REQUIRED')
    return {'sourceSha256': digest(raw), 'publicationRecipe': [digest(bodies[name]) for name in names[:2]],
            'toolPreparationHelperSha256': digest(bodies[names[2]])}


def pre_driver_memory_failure(row, receipt, catalog, fixture_container_id):
    """Admit explicit pre-driver memory rejection, plus #387's legacy original."""
    # The manifest binds the full original source through task_source_recipe.
    # New producers emit driverStart only in the local memory-admission catch,
    # before driver.open/Popen. #387 predates that marker and stays a closed case.
    context = {'release': 'ci-387-d0b540e67ab0',
               'commit': 'd0b540e67ab0f17a4539b2f69d557b7b73846933',
               'sourceSha256': '8e2c062f3c8194b334c0fd5be6f449cf606a89b2e8f11d808f8ed54179a70534'}
    source = 'script/jenkins/prepare-compact-fixtures.py'
    runtime = receipt.get('fixtureRuntime', {})
    need(row.get('retirement', {}).get('policy') == FINISHED_BATCH
         and receipt['status'] == 'FAILED' and receipt['verificationExitCode'] is None
         and receipt.get('errorType') == 'ValueError'
         and receipt.get('fixtureManifestProvided') is True
         and runtime.get('required') is True and runtime.get('containerId') == fixture_container_id
         and type(fixture_container_id) is str and SHA.fullmatch(fixture_container_id),
         'REVIEWED_PRE_DRIVER_MEMORY_FAILURE_REQUIRED')
    if 'driverStart' in receipt:
        admission = runtime.get('memoryAdmission', {})
        fields = ('hostMemoryAvailableBytes', 'requiredAvailableMemoryBytes', 'memoryShortfallBytes')
        need(receipt['driverStart'] == {'requested': False, 'blockedBy': 'FIXTURE_MEMORY_ADMISSION'}
             and receipt['driverStart']['requested'] is False
             and admission.get('capacityVerdict') == 'REJECTED'
             and admission.get('creditPolicy') == 'OWNED_ANONYMOUS_ONLY'
             and admission.get('fullAcceptanceResourcesMeasured') is False
             and all(type(admission.get(key)) is int and admission[key] >= 0 for key in fields)
             and admission['memoryShortfallBytes'] == admission['requiredAvailableMemoryBytes']
                 - admission['hostMemoryAvailableBytes'] > 0,
             'EXPLICIT_PRE_DRIVER_MEMORY_REJECTION_REQUIRED')
    else:
        need(all(row.get(key) == value for key, value in context.items())
             and runtime == {'required': True, 'containerId': fixture_container_id}
             and receipt.get('failureLocation') == {'source': source, 'line': 1859}
             and receipt.get('failureLocations') == [{'source': source, 'line': 1859, 'function': 'admit'},
                                                    {'source': source, 'line': 817, 'function': 'require'}],
             'REVIEWED_LEGACY_PRE_DRIVER_FAILURE_REQUIRED')
    checkout = ROOT / 'verification' / row['release'] / 'checkout'
    need(all(not path.exists() and not path.is_symlink() for path in
             (checkout / 'driver.log', checkout / 'work/ci-evidence/receipt.json')),
         'PRE_DRIVER_FAILURE_HAS_DRIVER_OUTPUT')
    need(set(catalog) == {'reports/' + name + '.json' for name in
         ('tool-runtime', 'fixture-runtime', 'middleware-fixture', 'observability-fixture', 'redis-fixture')}
         and all(0 < item['bytes'] <= MIB for item in catalog.values())
         and sum(item['bytes'] for item in catalog.values()) <= MIB,
         'COMPLETE_PRE_DRIVER_LIFECYCLE_REPORTS_REQUIRED')
    for field, name in (('toolRuntime', 'tool-runtime'), ('middlewareFixture', 'middleware-fixture'),
                        ('observabilityFixture', 'observability-fixture'), ('redisFixture', 'redis-fixture')):
        need(receipt.get(field, {}).get('evidenceSha256') == catalog['reports/' + name + '.json']['sha256'],
             'PRE_DRIVER_REPORT_BINDING_DIFFERS')


def pre_driver_cleanup(receipt, reports):
    """Original failed receipts stay failed; only owned-resource closure is used."""
    context = {key: receipt[key] for key in ('release', 'commit', 'sourceSha256')}
    need(all(all(document.get(key) == value for key, value in context.items())
             for document in reports.values())
         and all(document.get('identity') == receipt['identity']
                 for name, document in reports.items() if name != 'reports/tool-runtime.json'),
         'PRE_DRIVER_REPORT_CONTEXT_DIFFERS')
    tools, fixture = reports['reports/tool-runtime.json'], reports['reports/fixture-runtime.json']
    # ecs-tool-runtime.evidence emits no identity field. Its source context and
    # manifest digest bind it to the already authenticated outer receipt/claim;
    # unlike the other four reports, it must not invent a second host identity.
    need(tools.get('schema') == 1 and tools.get('kind') == 'doorhandle-ecs-tool-evidence'
         and tools.get('identity', receipt['identity']) == receipt['identity']
         and tools.get('manifestSha256') == receipt['toolRuntime']['manifestSha256']
         and receipt['toolRuntime'].get('cleanupStatus') == 'STOPPED'
         and tools.get('cleanup', {}).get('status') == 'STOPPED'
         and tools['cleanup'].get('remaining') == []
         and tools['cleanup'].get('release') == receipt['release']
         and tools['cleanup'].get('manifestSha256') == tools['manifestSha256'],
         'PRE_DRIVER_TOOLS_CLEANUP_UNRESOLVED')
    need(fixture.get('kind') == 'doorhandle-fixture-runtime' and fixture.get('status') == 'STOPPED'
         and fixture.get('watchStopped') is True and fixture.get('stopScope') == 'OWNED_ATTEMPT_ONLY'
         and fixture.get('containerId') == receipt['fixtureRuntime']['containerId'],
         'PRE_DRIVER_FIXTURE_WATCH_UNRESOLVED')
    for field, name in (('middlewareFixture', 'middleware'), ('observabilityFixture', 'observability'),
                        ('redisFixture', 'redis')):
        document = reports['reports/' + name + '-fixture.json']; summary = receipt.get(field, {})
        need(document.get('kind') == 'doorhandle-' + name + '-fixture'
             and document.get('status') == summary.get('status') == 'STOPPED'
             and document.get('cleanupConfirmed') is True and summary.get('cleanupConfirmed') is True
             and (name == 'observability' or document.get('containerId') == summary.get('containerId')),
             'PRE_DRIVER_OWNED_CLEANUP_UNRESOLVED')
    need(reports['reports/observability-fixture.json'].get('cleanupErrors') == [],
         'PRE_DRIVER_OBSERVABILITY_CLEANUP_UNRESOLVED')


def task_reports(row, verifier, *, metadata_only=False, fixture_container_id=None):
    receipt_path = ROOT / 'verification' / row['release'] / 'verification-receipt.json'
    if not receipt_path.exists() and not receipt_path.is_symlink():
        # A preparation failure can have a complete source backup without ever
        # starting verification. Unknown/partially uploaded attempts are retained.
        need(not (receipt_path.parent / '.verification-claimed').exists() and
             not (ROOT / 'inbox' / row['release'] / 'verify-remote.py').exists() and
             not (ROOT / 'inbox' / row['release'] / 'verification-evidence.tar.gz').exists(),
             'UNKNOWN_OR_PARTIAL_VERIFICATION_REPORT_STATE')
        return {'status': 'NOT_STARTED', 'originalJenkinsControlsRetained': True}
    raw = read(receipt_path)
    need(len(raw) <= verifier.MAX_RECEIPT_BYTES, 'ORIGINAL_REPORT_RECEIPT_BOUND')
    receipt = json.loads(raw)
    args = SimpleNamespace(tag=row['release'], commit=row['commit'], source_sha256=row['sourceSha256'],
                           attempt=receipt.get('attempt'), scope='mysql', instance_id=INSTANCE, machine_id=MACHINE)
    pre_driver = receipt.get('verificationExitCode') is None
    need(re.fullmatch(r'[a-f0-9]{32}', args.attempt or '') and receipt.get('status') in ('PASS', 'FAILED')
         and (pre_driver or (type(receipt.get('verificationExitCode')) is int
              and ((receipt['status'] == 'PASS' and receipt['verificationExitCode'] == 0)
                   or (receipt['status'] == 'FAILED' and receipt['verificationExitCode'] != 0))))
         and not receipt.get('evidenceOmissions'),
         'ORIGINAL_FAILED_VERIFICATION_REPORTS_REQUIRED')
    claim = json.loads(read(receipt_path.parent / '.verification-claimed/claim.json'))
    need(claim == {'schema': 1, 'kind': 'doorhandle-ci-claim', 'release': row['release'],
        'attempt': args.attempt, 'commit': row['commit'], 'sourceSha256': row['sourceSha256'],
        'identity': {'instanceId': INSTANCE, 'machineId': MACHINE, 'executionLocation': 'ECS'}, 'scope': 'mysql'},
        'ORIGINAL_VERIFICATION_CLAIM_DIFFERS')
    catalog = verifier.validate_envelope(receipt, args)
    need(bool(catalog), 'ORIGINAL_VERIFICATION_REPORTS_REQUIRED')
    if pre_driver: pre_driver_memory_failure(row, receipt, catalog, fixture_container_id)
    archive_path = safe(ROOT / 'inbox' / row['release'] / 'verification-evidence.tar.gz')
    before = archive_path.stat()
    need(stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
         and not before.st_mode & 0o022 and 0 < before.st_size <= verifier.MAX_EVIDENCE_ARCHIVE,
         'ORIGINAL_REPORT_ARCHIVE_REQUIRED')
    if not metadata_only or pre_driver:
        seen = set(); lifecycle = {}
        with verifier.bounded_tar(archive_path, verifier.MAX_EVIDENCE_BYTES + 16 * MIB) as archive:
            for index, member in enumerate(archive, 1):
                name = verifier.member_path(member.name).as_posix()
                need(index <= verifier.MAX_EVIDENCE_FILES and member.isfile() and name not in seen,
                     'ORIGINAL_REPORT_ARCHIVE_INVALID')
                seen.add(name)
                if index == 1:
                    need(name == 'verification-receipt.json' and member.size == len(raw) and
                         archive.extractfile(member).read(len(raw) + 1) == raw, 'ORIGINAL_REPORT_RECEIPT_CHANGED')
                    continue
                need(name in catalog and member.size == catalog[name]['bytes'], 'ORIGINAL_REPORT_CATALOG_DIFFERS')
                if pre_driver:
                    body = archive.extractfile(member).read(MIB + 1)
                    need(len(body) == member.size and digest(body) == catalog[name]['sha256'], 'ORIGINAL_REPORT_BYTES_CHANGED')
                    lifecycle[name] = json.loads(body)
                    continue
                check = hashlib.sha256()
                with archive.extractfile(member) as stream:
                    for block in iter(lambda: stream.read(MIB), b''):
                        check.update(block)
                need(check.hexdigest() == catalog[name]['sha256'], 'ORIGINAL_REPORT_BYTES_CHANGED')
        need(seen == {'verification-receipt.json', *catalog}, 'ORIGINAL_REPORT_ARCHIVE_INCOMPLETE')
        if pre_driver: pre_driver_cleanup(receipt, lifecycle)
    need(signature(before) == signature(archive_path.stat()), 'ORIGINAL_REPORT_ARCHIVE_CHANGED')
    return {'verificationStatus': receipt['status'], 'receiptSha256': digest(raw),
            'archiveMetadata': signature(before), 'reportFiles': len(catalog),
            **({'verificationExitCode': None, 'driverStarted': False, 'failureStage': 'FIXTURE_MEMORY_ADMISSION'}
               if pre_driver else {})}


def task_admitted(binding, value, helpers, *, metadata_only=False):
    native, verifier = helpers['retire-failed-native-jar-duplicates.py'], helpers['verify-remote.py']
    finished = binding.get('batch') == FINISHED_BATCH
    local_names = {**native.UPLOADED_NAMES, 'preparation': 'ecs-tool-preparation.json',
                   'transport': 'candidate-build-tools-transport.json' if finished else 'ecs-tool-preparation-transport.json'}
    keepers = []
    for row in value['candidates']:
        tag = row['release']; work = ROOT / 'verification' / tag / 'checkout/work/compact-fixtures'
        context = {key: row[key] for key in ('release', 'commit', 'sourceSha256')}
        raw_docs, local = {}, {}
        for role, name in local_names.items():
            raw = read(ROOT / 'inbox' / binding['tag'] / 'failed-mysql-data-controls' / tag / name)
            need(len(raw) == row['controls'][role]['bytes'] and digest(raw) == row['controls'][role]['sha256'],
                 'AUTHENTICATED_JENKINS_TASK_CONTROL_CHANGED')
            if role in native.UPLOADED_NAMES:
                raw_docs[role] = raw
            else:
                local[role] = json.loads(raw)
        for role, path in (('artifactPlan', ROOT / 'inbox' / tag / 'build-artifacts.json'),
                           ('fixtureOwner', work.parent / 'compact-fixtures-owner.json'),
                           ('fixtureCleanup', work / 'cleanup-receipt.json')):
            raw_docs[role] = read(path)
        evidence = native.validate_control_documents(raw_docs, context, value['identity'],
                                                     canonical_jar=True, database_verification=not finished)
        owner, cleanup = json.loads(raw_docs['fixtureOwner']), json.loads(raw_docs['fixtureCleanup'])
        need(owner.get('dataDirectory') == str(work / 'mysql-data') and owner.get('sourceTableCount') == 131
             and owner.get('sourceClone') == 'doorhandle_migration_verify_' + evidence['ownerToken']
             and owner.get('containerId') != owner.get('sourceContainerId')
             and cleanup.get('dataDirectoryRetained') == str(work / 'mysql-data'), 'EXACT_DERIVED_TASK_OWNER_REQUIRED')
        recipe = task_source_recipe(native, row)
        preparation, transport = local['preparation'], local['transport']
        if finished:
            absence = finished_runtime_absence(row, preparation, transport, recipe, value['identity'])
            need((evidence['jarSha256'], evidence['jarBytes']) ==
                 (row['retirement']['jarSha256'], row['retirement']['jarBytes']),
                 'MANIFEST_BINARY_DIFFERS_FROM_ORIGINAL_BUILD')
        else:
            need(all(document.get(key) == expected for document in (preparation, transport)
                 for key, expected in context.items()) and preparation.get('status') == 'PREPARED'
             and preparation.get('kind') == 'doorhandle-ecs-tool-preparation'
             and preparation.get('identity') == value['identity'] and 'candidateBuilderTools' not in preparation
             and preparation.get('sourceFiles', {}).get('script/jenkins/prepare-ecs-tools.py') == recipe['toolPreparationHelperSha256']
             and transport.get('prepareCandidateBuilder') is False and transport.get('status') == 'PREPARED'
             and transport.get('kind') == 'doorhandle-ecs-tool-preparation-transport'
             and type(transport.get('schema')) is int and transport['schema'] == 1
             and transport.get('instanceId') == INSTANCE and transport.get('machineId') == MACHINE
             and type(transport.get('finalExitCode')) is int and transport['finalExitCode'] == 0 and 'buildkitArchive' not in transport,
                 'VERIFY_ONLY_TASK_WITHOUT_CANDIDATE_BUILDER_REQUIRED')
        need((finished or not (ROOT / 'inbox' / tag / 'candidate-build-tools').exists())
             and not (work / 'derived-mysql-retired-task.json').exists()
             and not (ROOT / 'releases' / tag).exists(), 'PUBLISHED_CANDIDATE_OR_RETIRED_TASK_REFUSED')
        publication = None if metadata_only else native.canonical_publication_refs(ROOT, tag)
        manifest_raw = read(work / 'source-backup/manifest.json'); manifest = json.loads(manifest_raw)
        need(digest(manifest_raw) == owner.get('sourceBackupSha256') and
             manifest.get('snapshotSha256') == owner.get('sourceSnapshotSha256') == owner.get('sourceCloneSnapshotSha256')
             and SHA.fullmatch(owner.get('sourceSnapshotSha256', '')) and len(manifest.get('tables', {})) == 131
             and manifest.get('data', {}).get('file') == 'data.sql', 'COMPLETE_TASK_SOURCE_BACKUP_REQUIRED')
        sql_sha, sql_bytes = manifest['data'].get('sha256'), manifest['data'].get('bytes')
        need(SHA.fullmatch(sql_sha or '') and type(sql_bytes) is int and 0 < sql_bytes <= 128 * MIB,
             'COMPLETE_TASK_SQL_METADATA_REQUIRED')
        if not metadata_only:
            sql = read(work / 'source-backup/data.sql', 128 * MIB)
            need(len(sql) == sql_bytes and digest(sql) == sql_sha, 'TASK_SOURCE_SQL_INTEGRITY_FAILED')
        keepers.append({**context, 'jenkinsResult': evidence['jenkinsResult'], 'token': evidence['ownerToken'],
            'ownerSha256': digest(raw_docs['fixtureOwner']),
            'cleanupSha256': digest(raw_docs['fixtureCleanup']), 'backupManifestSha256': digest(manifest_raw),
            'sourceSqlSha256': sql_sha, 'sourceSqlBytes': sql_bytes, 'sourceSnapshotSha256': owner['sourceSnapshotSha256'],
            'sourceRecipe': recipe, 'publicationReferences': publication,
            'reports': task_reports(row, verifier, metadata_only=metadata_only, fixture_container_id=owner['containerId']),
            **({'preRuntimeAbsence': absence} if finished else {}),
            **({'completedBinaryRetirement': finished_completed_binaries(binding, row)}
               if finished and 'completedAttempt' in row['retirement'] else {})})
    return keepers


def task_configuration(value, keepers, roots):
    tags = [row['release'] for row in value['candidates']]
    need(set(roots) == set(tags) and [row['release'] for row in keepers] == tags,
         'EXACT_TASK_ROOT_IDENTITIES_REQUIRED')
    targets = {}
    for row in value['candidates']:
        meta = roots[row['release']]
        need(type(meta) is list and len(meta) == 5 and all(type(part) is int for part in meta)
             and meta[0] == 64771 and stat.S_ISDIR(meta[2]) and meta[3:] == [999, 1000]
             and stat.S_IMODE(meta[2]) == 0o700, 'TASK_METADATA_DIRECTORY_IDENTITY_REQUIRED')
        if 'retirement' in row:
            need(meta[:2] == row['retirement']['dataIdentity'], 'MANIFEST_DATA_DIRECTORY_REPLACED')
        targets[row['release']] = (meta[1], row['commit'])
    return TaskBatch(targets, {row['release']: row['backupManifestSha256'] for row in keepers})


def task_fixture_candidates(value, keepers, helpers):
    """Reuse the stopped-object proof, independently of regenerable JAR presence."""
    native, builder = helpers['retire-failed-native-jar-duplicates.py'], helpers['compact-build-resources.py']
    need(len(value['candidates']) == len(keepers), 'COMPLETE_TASK_FIXTURE_PROOFS_REQUIRED')
    candidates = []
    for row, keeper in zip(value['candidates'], keepers):
        context = {key: row[key] for key in ('release', 'commit', 'sourceSha256')}
        need(context == {key: keeper[key] for key in context}, 'TASK_FIXTURE_KEEPER_CONTEXT_DIFFERS')
        work = ROOT / 'verification' / row['release'] / 'checkout/work/compact-fixtures'
        documents, references = {}, {}
        for role, path, checksum in (('fixtureOwner', work.parent / 'compact-fixtures-owner.json', keeper['ownerSha256']),
                                     ('fixtureCleanup', work / 'cleanup-receipt.json', keeper['cleanupSha256'])):
            with native.held_file(ROOT, path, native.MAX_CONTROL) as (stream, metadata):
                raw = stream.read(native.MAX_CONTROL + 1)
                need(digest(raw) == checksum, 'TASK_FIXTURE_ORIGINAL_CHANGED')
                documents[role] = native.decode(raw)
                references[role] = {'path': path.relative_to(ROOT).as_posix(), 'bytes': len(raw),
                                    'sha256': checksum, 'metadata': metadata}
        options = ({'pre_runtime_recipe': row['retirement']['publicationRecipe'], 'builder_helpers': True} if 'retirement' in row
                   else {'database_verification': True})
        source = native.source_proof(ROOT, row['release'], row['commit'], row['sourceSha256'],
                                     canonical_jar=True, failed_native=True, **options)
        historical = {'context': context, 'controls': references, 'sourceArchive': source,
            'evidence': {'identity': value['identity'], 'ownerToken': keeper['token']},
            'fixtureOwner': native.fixture_owner_projection(documents['fixtureOwner']),
            'fixtureCleanup': {key: documents['fixtureCleanup'].get(key) for key in
                ('schemaVersion', 'kind', 'release', 'commit', 'sourceSha256', 'identity', 'status', 'errors',
                 'containerId', 'sourceContainerUntouched', 'dataDirectoryRetained', 'sourceDumpAndEvidenceRetained')}}
        fixture = native.capture_fixture(ROOT, value, historical, builder, source_proof=source, failed_native=True)
        candidate = {'historical': historical, 'fixture': fixture}
        if 'retirement' in row:
            historical['finishedOutputsPolicy'] = FINISHED_BATCH
            historical['preparedToolsSha256'] = keeper['preRuntimeAbsence']['toolsSha256']
            candidate['preservedBuilder'] = finished_preserved_builder(historical, helpers)
        candidates.append(candidate)
    return candidates


def finished_preserved_builder(historical, helpers):
    """Authenticate an independent stopped builder; never authorize its removal."""
    need(historical.get('finishedOutputsPolicy') == FINISHED_BATCH, 'EXACT_FINISHED_BUILDER_POLICY_REQUIRED')
    native, builder = (helpers[name] for name in
        ('retire-failed-native-jar-duplicates.py', 'compact-build-resources.py'))
    context = historical['context']; directory = ROOT / 'inbox' / context['release'] / 'candidate-build-tools'
    raw = {}
    for role, name in (('tools', 'tools.json'), ('summary', 'resource-summary.json'),
                       ('measurement', 'official-layer-measurements.json')):
        with native.held_file(ROOT, directory / name, native.MAX_CONTROL) as (stream, _metadata):
            raw[role] = stream.read(native.MAX_CONTROL + 1)
    need(digest(raw['tools']) == historical['preparedToolsSha256'], 'FINISHED_PREPARED_BUILDER_TOOLS_CHANGED')
    tools, summary = native.decode(raw['tools']), native.decode(raw['summary'])
    need(tools.get('resourceEvidence') == {'file': str(directory / 'resource-summary.json'), 'sha256': digest(raw['summary'])}
         and tools.get('imageMeasurementSha256') == digest(raw['measurement']), 'FINISHED_BUILDER_CONTROL_BINDING_CHANGED')
    source = {**historical['sourceArchive'], 'preparedToolsSha256': historical['preparedToolsSha256']}
    builder.failed_native_builder_source(context, {key: digest(body) for key, body in raw.items()}, source)
    cid = summary.get('cleanup', {}).get('builderContainerId')
    need(type(cid) is str and SHA.fullmatch(cid), 'FINISHED_ORIGINAL_BUILDER_ID_REQUIRED')
    # An absent original grants no exclusion. Any replacement/unknown object
    # remains visible to the normal complete-container reference checks.
    if cid not in native.builder_container_ids(): return None
    return builder.historical_builder_descriptor(ROOT, context, historical['evidence']['identity'],
        raw['tools'], raw['summary'], raw['measurement'], source['builderHelperSha256'],
        builder.historical_builder_inspect(native.builder_docker('inspect', cid)),
        failed_native=True, source_proof=source)


def task_candidate_references(candidate, helpers):
    native, cleanup, builder = (helpers[name] for name in
        ('retire-failed-native-jar-duplicates.py', 'cleanup-ecs-builds.py', 'compact-build-resources.py'))
    historical, fixture = candidate['historical'], candidate['fixture']
    if historical.get('finishedOutputsPolicy') == FINISHED_BATCH:
        preserved = finished_preserved_builder(historical, helpers)
        need('preservedBuilder' in candidate and preserved == candidate['preservedBuilder'],
             'FINISHED_PRESERVED_BUILDER_CHANGED')
        if preserved is not None:
            return native.builder_references(ROOT, historical, preserved, cleanup, builder, fixture,
                                             include_inbox=True, failed_native=True)
    if fixture is not None:
        return native.recent_fixture_references(ROOT, candidate, cleanup, builder)
    tag = historical['context']['release']
    return cleanup.quiescent({'checkout': ROOT / 'verification' / tag / 'checkout',
                              'token': historical['evidence']['ownerToken']}, tag,
                             cleanup.docker_snapshot(), include_inbox=True)


def task_fixture_quiescence(keepers, candidates, helpers):
    need(len(keepers) == len(candidates), 'COMPLETE_TASK_FIXTURE_PROOFS_REQUIRED')
    for keeper, candidate in zip(keepers, candidates):
        need(candidate['historical']['context']['release'] == keeper['release'], 'TASK_FIXTURE_KEEPER_CONTEXT_DIFFERS')
        task_candidate_references(candidate, helpers)


def task_remove_fixture(candidate, helpers):
    """Remove only the exact admitted stopped object; never its data or images."""
    fixture = candidate['fixture']
    if fixture is None:
        return {'release': candidate['historical']['context']['release'], 'status': 'ALREADY_ABSENT'}
    native, builder = (helpers[name] for name in
        ('retire-failed-native-jar-duplicates.py', 'compact-build-resources.py'))
    return builder.historical_mysql_fixture_remove(fixture,
        lambda cid: native.builder_docker('inspect', cid), lambda cid: native.builder_docker('rm', cid),
        native.builder_container_ids,
        lambda _cid: task_candidate_references(candidate, helpers),
        lambda: native.fixture_data_metadata(ROOT, fixture['dataDirectory']))


def finished_jar_targets(value, helpers):
    native = helpers['retire-failed-native-jar-duplicates.py']
    targets = []
    for row in value['candidates']:
        item = row['retirement']; tag = row['release']
        if 'completedAttempt' in item:
            validate_finished_selection(row)
            continue  # Original bound journal is revalidated by task_admitted.
        copy = native.describe_duplicate(ROOT, tag, item['jarSha256'], item['jarBytes'])
        canonical = native.describe_canonical_jar(ROOT, tag, item['jarSha256'], item['jarBytes'], failed_native=True)
        need([canonical['metadata'][:2], copy['metadata'][:2]] == item['jarIdentities'],
             'MANIFEST_JAR_INODE_REPLACED')
        # The duplicate's keeper must still exist when the copy is removed.
        targets.extend([copy, canonical])
    return targets


def finished_remove_jars(output, targets, helpers, quiescence, receipt):
    native = helpers['retire-failed-native-jar-duplicates.py']
    with os.fdopen(os.open(output / 'jar-journal.jsonl', os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as journal:
        def record(event):
            journal.write(encoded(event) + b'\n'); journal.flush(); os.fsync(journal.fileno())
        record({'phase': 'STARTED', 'planSha256': receipt['planSha256'], 'requestSha256': receipt['requestSha256']})
        for target in targets:
            quiescence()
            quarantine = native.reserve_quarantine(ROOT, target['release'])
            record({'phase': 'DELETE_STARTED', 'path': target['path'], 'quarantine': quarantine})
            if target['kind'] == native.JAR_COPY_KIND:
                removed = native.remove_duplicate(ROOT, target, quarantine, quiescence=quiescence)
            else:
                need(target['kind'] == native.CANONICAL_JAR_KIND, 'UNKNOWN_FINISHED_BINARY_KIND')
                removed = native.remove_canonical_jar(ROOT, target, quarantine, quiescence=quiescence, failed_native=True)
            receipt['jarRetirements'].append(removed)
            record({'phase': 'DELETE_FINISHED', **removed})
        record({'phase': 'FINISHED', 'deletedFiles': len(receipt['jarRetirements'])})


def task_root_worker(request):
    need(os.getuid() == 0 and Path('/etc/machine-id').read_text().strip() == MACHINE,
         'APPROVED_TASK_ROOT_IDENTITY_REQUIRED')
    phase = request.get('phase')
    expected = {'phase', 'binding', 'roots'} | ({'target'} if phase == 'task-remove' else set())
    need(set(request) == expected and phase in ('task-inventory', 'task-remove'), 'ARBITRARY_TASK_ROOT_ARGUMENT_REFUSED')
    helpers = task_helpers(request['binding']); value = task_request(request['binding'])
    keepers = task_admitted(request['binding'], value, helpers, metadata_only=True)
    configuration = task_configuration(value, keepers, request['roots'])
    if phase == 'task-inventory':
        targets = [tree(tag, configuration) for tag in configuration.targets]
        return {'targets': targets, 'processProbe': process_references(targets)}
    item = request['target']
    need(item.get('release') in configuration.targets and tree(item['release'], configuration) == item,
         'TASK_TREE_CHANGED_AFTER_PLAN')
    probe = process_references([item]); remove_tree(item, configuration)
    return {'release': item['release'], 'status': 'REMOVED', 'allocatedBytesBefore': item['allocatedBytes'],
            'processProbe': probe}


def task_run(args):
    need(os.getuid() == 1000 and args.batch in (TASK_BATCH, FINISHED_BATCH), 'EXPLICIT_TASK_MAINTENANCE_REQUIRED')
    finished = args.batch == FINISHED_BATCH
    binding = {'tag': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256,
               'requestSha256': args.request_sha256, 'failedBuilds': args.failed_builds}
    if finished: binding['batch'] = FINISHED_BATCH
    helpers = task_helpers(binding); value = task_request(binding)
    identity = helpers['verify-remote.py'].ecs_identity(INSTANCE, MACHINE)
    output = ROOT / 'inbox' / args.tag / 'derived-failed-mysql-retirement'
    plan_file, receipt_file, execution_file = (output / name for name in ('plan-private.json', 'receipt.json', 'execution.json'))
    public_binding = {'batch': args.batch, 'release': args.tag, 'commit': args.commit,
        'sourceSha256': args.source_sha256, 'identity': identity, 'requestSha256': args.request_sha256,
        'taskThreadId': FINISHED_TASK_ID if finished else TASK_ID}
    if args.phase == 'status':
        if receipt_file.exists():
            receipt = json.loads(read(receipt_file))
            need(all(receipt.get(key) == expected for key, expected in public_binding.items()), 'TASK_TERMINAL_BINDING_DIFFERS')
            return {**public_binding, 'terminal': True, 'status': receipt['status']}
        if execution_file.exists():
            execution = json.loads(read(execution_file))
            need(execution.get('binding') == public_binding and execution.get('bootId') == Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                 'TASK_EXECUTION_BINDING_DIFFERS')
            try:
                fields = (Path('/proc') / str(execution['pid']) / 'stat').read_text().rsplit(')', 1)[1].split()
                alive = fields[19] == execution['startTicks'] and fields[0] not in ('Z', 'X')
            except FileNotFoundError:
                alive = False
            need(alive, 'TASK_EXECUTION_STOPPED_WITHOUT_TERMINAL')
            return {**public_binding, 'terminal': False, 'status': 'RUNNING'}
        return {**public_binding, 'terminal': False, 'status': 'UNKNOWN'}
    cleanup = helpers['cleanup-ecs-builds.py']
    def admitted(*, fixture_objects=False):
        keepers = task_admitted(binding, value, helpers)
        if fixture_objects or finished:
            candidates = task_fixture_candidates(value, keepers, helpers)
            task_fixture_quiescence(keepers, candidates, helpers)
            if fixture_objects: return keepers, candidates
            need(all(item['fixture'] is None for item in candidates), 'FINISHED_FIXTURE_REAPPEARED_AFTER_REMOVAL')
            need([(item['historical']['context'], item.get('preservedBuilder')) for item in candidates] ==
                 [(item['historical']['context'], item.get('preservedBuilder')) for item in plan['fixtures']],
                 'FINISHED_PRESERVED_BUILDER_CHANGED_AFTER_PLAN')
            return keepers
        containers = cleanup.docker_snapshot()
        for keeper in keepers:
            cleanup.quiescent({'checkout': ROOT / 'verification' / keeper['release'] / 'checkout', 'token': keeper['token']},
                              keeper['release'], containers, include_inbox=True)
        return keepers
    with lock(ROOT / 'state/deploy.lock'), ExitStack() as attempts:
        for row in value['candidates']:
            attempts.enter_context(attempt_lock(row['release']))
        if args.phase == 'plan':
            need(not plan_file.exists() and not receipt_file.exists() and not execution_file.exists(), 'FRESH_TASK_PLAN_REQUIRED')
            keepers, fixtures = admitted(fixture_objects=True)
            roots = {row['release']: signature(safe(ROOT / 'verification' / row['release'] /
                     'checkout/work/compact-fixtures/mysql-data').stat())[:5] for row in value['candidates']}
            measured = privileged({'phase': 'task-inventory', 'binding': binding, 'roots': roots})
            need(measured['processProbe']['status'] == 'QUIESCENT', 'ALL_UID_TASK_QUIESCENCE_REQUIRED')
            plan = {**public_binding, 'keepers': keepers, 'fixtures': fixtures, 'roots': roots, 'targets': measured['targets'],
                    'processProbe': measured['processProbe']}
            if finished:
                plan['jarTargets'] = finished_jar_targets(value, helpers)
                plan['completedBinaryRetirements'] = [item['completedBinaryRetirement'] for item in keepers
                                                       if 'completedBinaryRetirement' in item]
            write(plan_file, plan)
            public = {**public_binding, 'planSha256': digest(encoded(plan)), 'sourceSqlAndReportsRetained': True,
                'targets': [{key: target[key] for key in ('release', 'path', 'allocatedBytes', 'files', 'inventorySha256')}
                            for target in measured['targets']], 'processProbe': measured['processProbe'],
                'fixtureObjects': [{'release': item['historical']['context']['release'],
                    'containerId': item['fixture']['containerId'] if item['fixture'] else None,
                    'status': 'STOPPED_OBJECT_ADMITTED' if item['fixture'] else 'ALREADY_ABSENT'} for item in fixtures]}
            if finished:
                public['jarTargets'] = plan['jarTargets']
                public['completedBinaryRetirements'] = plan['completedBinaryRetirements']
            write(output / 'plan.json', public)
            return {'status': 'PLANNED', **public_binding, 'planSha256': public['planSha256']}
        raw = read(plan_file, 8 * MIB); plan = json.loads(raw)
        need(SHA.fullmatch(args.plan_sha256 or '') and digest(raw) == args.plan_sha256 and
             all(plan.get(key) == expected for key, expected in public_binding.items())
             and (plan['keepers'], plan['fixtures']) == admitted(fixture_objects=True)
             and not receipt_file.exists() and not execution_file.exists(), 'TASK_PLAN_OR_KEEPERS_CHANGED')
        if finished:
            need(plan.get('jarTargets') == finished_jar_targets(value, helpers), 'FINISHED_JARS_CHANGED_AFTER_PLAN')
        write(execution_file, {'binding': public_binding, 'pid': os.getpid(),
            'startTicks': Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19],
            'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip()})
        receipt = {**public_binding, 'status': 'FAILED_OR_UNKNOWN', 'planSha256': args.plan_sha256,
                   'removed': [], 'fixtureRetirements': [], 'sourceSqlAndReportsRetained': True,
                   'availableBytesBefore': os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize}
        if finished:
            receipt['jarRetirements'] = []
            receipt['completedBinaryRetirements'] = plan['completedBinaryRetirements']
        try:
            measurement = privileged({'phase': 'task-inventory', 'binding': binding, 'roots': plan['roots']})
            need(measurement['targets'] == plan['targets'] and measurement['processProbe']['status'] == 'QUIESCENT',
                 'TASK_TARGETS_CHANGED_AFTER_PLAN')
            for candidate in plan['fixtures']:
                need(plan['keepers'] == task_admitted(binding, value, helpers), 'TASK_KEEPERS_CHANGED_BEFORE_OBJECT_REMOVE')
                observed = task_fixture_candidates(value, plan['keepers'], helpers)
                current = next(item for item in observed if item['historical']['context'] == candidate['historical']['context'])
                need(current == candidate, 'TASK_FIXTURE_CHANGED_AFTER_PLAN')
                receipt['fixtureRetirements'].append(task_remove_fixture(candidate, helpers))
            # Fixtures are gone at the data boundary. Finished-output policy
            # retains only its fully authenticated independent stopped builder.
            need(plan['keepers'] == admitted(), 'TASK_KEEPERS_CHANGED_AFTER_OBJECT_REMOVE')
            if finished:
                def jar_quiescence():
                    need(plan['keepers'] == admitted(), 'TASK_KEEPERS_CHANGED_BEFORE_BINARY_REMOVE')
                finished_remove_jars(output, plan['jarTargets'], helpers, jar_quiescence, receipt)
            for target in plan['targets']:
                need(plan['keepers'] == admitted(), 'TASK_KEEPERS_CHANGED_BEFORE_REMOVE')
                receipt['removed'].append(privileged({'phase': 'task-remove', 'binding': binding,
                    'roots': plan['roots'], 'target': target}))
            need(plan['keepers'] == admitted(), 'TASK_SQL_SOURCE_OR_REPORTS_CHANGED_AFTER_REMOVE')
            for target in plan['targets']:
                write(ROOT / 'verification' / target['release'] / 'checkout/work/compact-fixtures/derived-mysql-retired-task.json',
                      {**public_binding, 'targetRelease': target['release'], 'status': 'REMOVED', 'planSha256': args.plan_sha256})
            receipt['status'] = 'COMPLETE'
        except BaseException as error:
            receipt['errorType'] = type(error).__name__
            receipt['reasonCode'] = failure_reason_code(error)
            receipt['failureLocations'] = failure_locations(error)
            raise
        finally:
            receipt['availableBytesAfter'] = os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize
            write(receipt_file, receipt)
        return {'status': receipt['status'], **public_binding, 'removedDirectories': len(receipt['removed'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('plan', 'apply', 'status'))
    for name in ('batch', 'tag', 'commit', 'source-sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--plan-sha256')
    parser.add_argument('--failed-builds')
    parser.add_argument('--request-sha256')
    args = parser.parse_args()
    # Transport loss observes this same operation; it must never replay deletion.
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    try:
        print(json.dumps(run(args))); return 0
    except BaseException as error:
        print(json.dumps({'status': 'FAILED_OR_UNKNOWN', 'errorType': type(error).__name__,
                          'reasonCode': failure_reason_code(error), 'phase': args.phase,
                          'failureLocations': failure_locations(error)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
