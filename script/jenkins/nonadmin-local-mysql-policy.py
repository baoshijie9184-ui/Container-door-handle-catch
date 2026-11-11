"""Closed metadata checks for the one fixed nonadministrator migration export.

This module never connects to MySQL, reads credentials, changes permissions or
executes another program. Its CLI admits only nonsecret OS/grant records on
stdin. Historical source identity comes from one byte-pinned metadata bundle;
the retired original export files are never reopened.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import stat
import sys


MAXIMUM = 64 * 1024
SCHEMA_ORDER = ('doorhandledb', 'doorhandle_agent_verify_ef8d5844c1', 'doorhandle_model_verify_22e4bc5566')
SCHEMAS = frozenset(SCHEMA_ORDER)
EXECUTABLE = r'C:\Program Files\MySQL\MySQL Server 8.3\bin\mysqld.exe'
DEFAULTS = r'--defaults-file=C:\ProgramData\MySQL\MySQL Server 8.3\my.ini'
DATA_DIRECTORY = r'C:\ProgramData\MySQL\MySQL Server 8.3\Data'
HISTORY_BUNDLE = Path('D:/AI/lunwen1/DoorHandleCatch/work/jenkins/nonadmin-local-export-assessment-20261109T230447Z/'
                      'source-pins-20261109T232421Z-f085d724/history-pins-private.json')
HISTORY_BUNDLE_SHA256 = '1b7e580828c50d815d5d470461681a313867d07e9ef69c26e4b9b07371c3d530'
HISTORY_CANONICAL_SHA256 = '3d1c7615f3fb372cf9780ae2507054775821b152e6249e1b35a68ee7155c0ecb'
OWNERSHIP_SHA256 = 'e8d8bfab9bb8cdcdda0c9d437fadcf4802b205c5eaa1cb9dfcbd61f3169a8a1c'
ORIGINAL_EVIDENCE_PINS = {
    'authorization-private.json': '02b3fce06181139d9b0db22ec175560aeed4ef9f29f92f864a084403fd9e4d22',
    'before-identity-private.json': 'ea0e00034f61042d6cad94724d2541a08307f93aa2bad332305b97c3c732e611',
    'after-identity-private.json': 'ea0e00034f61042d6cad94724d2541a08307f93aa2bad332305b97c3c732e611',
    'public-manifest.json': '0b58012469e0babb2031b54d34ed906910b75f9385d8950776776153dde3495d',
}
CONFIGURATION_FIELDS = frozenset(('expectedServerUuid', 'expectedDataDirectory',
                                'sourceIniSha256', 'sourceUuidMetadataSha256'))
PROCESS_FIELDS = frozenset(('processId', 'parentProcessId', 'name', 'createdAtUtc',
                           'executablePath', 'commandLine'))
ENDPOINT_FIELDS = frozenset(('localAddress', 'localPort', 'remoteAddress', 'remotePort',
                            'owningProcess', 'state'))


class PolicyError(ValueError):
    """Only fixed, value-free refusal codes may cross the process boundary."""


def need(condition, code):
    if not condition:
        raise PolicyError(code)


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(',', ':')).encode('utf8')


def checksum(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def decode(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            need(key not in value, 'NONADMIN_DUPLICATE_JSON_KEY')
            value[key] = item
        return value
    need(type(raw) is bytes and len(raw) <= MAXIMUM, 'NONADMIN_BOUNDED_JSON_REQUIRED')
    return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique,
                      parse_constant=lambda _: need(False, 'NONADMIN_NONFINITE_JSON_REFUSED'))


def command(value):
    need(type(value) is str and 0 < len(value) <= 8192
         and not re.search(r'[\x00-\x08\x0a-\x1f]', value) and '\\"' not in value,
         'NONADMIN_FIXED_SERVER_COMMAND_REQUIRED')
    arguments, previous = [], 0
    for match in re.finditer(r'"[^"]*"|[^\s"]+="[^"]*"|[^\s"]+', value):
        gap = value[previous:match.start()]
        need(not gap.strip() and (not arguments or bool(gap)), 'NONADMIN_SERVER_QUOTING_REFUSED')
        arguments.append(match.group().replace('"', '')); previous = match.end()
    need(not value[previous:].strip() and len(arguments) in (2, 3)
         and arguments[0].casefold() == EXECUTABLE.casefold()
         and arguments[1].casefold() == DEFAULTS.casefold()
         and (len(arguments) == 2 or arguments[2] == 'MySQL83'), 'NONADMIN_SERVER_OVERRIDE_REFUSED')


def configuration(value):
    need(type(value) is dict and set(value) == CONFIGURATION_FIELDS,
         'NONADMIN_HISTORICAL_CONFIGURATION_REQUIRED')
    need(type(value['expectedServerUuid']) is str
         and re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', value['expectedServerUuid'])
         and type(value['expectedDataDirectory']) is str
         and ntpath.normcase(value['expectedDataDirectory'].rstrip('\\/')) == ntpath.normcase(DATA_DIRECTORY)
         and all(type(value[k]) is str and re.fullmatch(r'[a-f0-9]{64}', value[k])
                 for k in ('sourceIniSha256', 'sourceUuidMetadataSha256')),
         'NONADMIN_HISTORICAL_SOURCE_PIN_INVALID')
    return {**value, 'expectedDataDirectory': DATA_DIRECTORY}


def process(value):
    need(type(value) is dict and set(value) == PROCESS_FIELDS, 'NONADMIN_COMPLETE_PROCESS_REQUIRED')
    need(type(value['processId']) is int and 0 < value['processId'] <= 0xffffffff
         and type(value['parentProcessId']) is int and 0 <= value['parentProcessId'] <= 0xffffffff
         and type(value['name']) is str and value['name'].casefold() == 'mysqld.exe',
         'NONADMIN_FIXED_PROCESS_IDENTITY_REQUIRED')
    stamp = value['createdAtUtc']
    match = re.fullmatch(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,7}))?(?:Z|\+00:00)', stamp) if type(stamp) is str else None
    need(match is not None, 'NONADMIN_PROCESS_CREATION_REQUIRED')
    try:
        # Python 3.9 rejects .NET's seven-digit round-trip fraction. Parse the
        # whole UTC second portably and retain all 100ns ticks for ordering;
        # rounding to microseconds could admit a child older than its parent.
        parsed = dt.datetime.fromisoformat(match[1] + '+00:00')
        ticks = int((match[2] or '').ljust(7, '0'))
    except ValueError:
        raise PolicyError('NONADMIN_PROCESS_CREATION_REQUIRED') from None
    for key in ('executablePath', 'commandLine'):
        need(value[key] is None or type(value[key]) is str and len(value[key]) <= 8192,
             'NONADMIN_VISIBLE_PROCESS_METADATA_INVALID')
    if value['executablePath']:
        need(value['executablePath'].casefold() == EXECUTABLE.casefold(), 'NONADMIN_PROCESS_EXECUTABLE_CHANGED')
    if value['commandLine']:
        command(value['commandLine'])
    return parsed, ticks


def validate_source(record, historical):
    """Admit a complete fresh service/listener observation, never credentials."""
    historical = configuration(historical)
    need(type(record) is dict and set(record) == {'service', 'serviceProcess', 'worker', 'endpoints', 'hostName'},
         'NONADMIN_COMPLETE_SOURCE_RECORD_REQUIRED')
    service, parent, worker = record['service'], record['serviceProcess'], record['worker']
    need(type(service) is dict and set(service) == {'name', 'state', 'processId', 'pathName'}
         and service['name'] == 'MySQL83' and service['state'] == 'Running'
         and type(service['processId']) is int and 0 < service['processId'] <= 0xffffffff,
         'NONADMIN_RUNNING_FIXED_SERVICE_REQUIRED')
    command(service['pathName'])
    parent_stamp, worker_stamp = process(parent), process(worker)
    need(parent['processId'] == service['processId'], 'NONADMIN_SERVICE_PROCESS_BINDING_DIFFERS')
    need((worker['processId'] == parent['processId'] and worker == parent)
         or worker['processId'] != parent['processId'] and worker['parentProcessId'] == parent['processId']
         and worker_stamp >= parent_stamp, 'NONADMIN_LISTENER_PARENT_BINDING_DIFFERS')
    host = record['hostName']
    need(type(host) is str and re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', host),
         'NONADMIN_HOST_NAME_REQUIRED')
    endpoints = record['endpoints']
    need(type(endpoints) is list and 0 < len(endpoints) <= 16, 'NONADMIN_FIXED_ENDPOINT_REQUIRED')
    seen = set()
    for item in endpoints:
        need(type(item) is dict and set(item) == ENDPOINT_FIELDS, 'NONADMIN_COMPLETE_ENDPOINT_REQUIRED')
        need(all(type(item[k]) is int for k in ('localPort', 'remotePort', 'owningProcess', 'state'))
             and item['localPort'] == 3306 and item['remotePort'] == 0
             and item['owningProcess'] == worker['processId'] and item['state'] in (0, 2)
             and item['localAddress'] in ('127.0.0.1', '0.0.0.0', '::')
             and item['remoteAddress'] in ('0.0.0.0', '::'), 'NONADMIN_ENDPOINT_OWNER_OR_BINDING_DIFFERS')
        identity = encoded(item); need(identity not in seen, 'NONADMIN_DUPLICATE_ENDPOINT_REFUSED'); seen.add(identity)
    states = sorted({item['state'] for item in endpoints})
    return {'serviceProcessId': parent['processId'], 'serviceCreatedAtUtc': parent['createdAtUtc'],
        'worker': {key: worker[key] for key in ('processId', 'parentProcessId', 'createdAtUtc')},
        'sourceSeenState': states, 'tcpEvidenceKind': 'UNKNOWN_OWNER_BOUND_ENDPOINT' if 0 in states else 'REPORTED_LISTEN_OWNER_BOUND_ENDPOINT',
        'configuration': historical, 'hostName': host, 'policyVersion': 'nonadmin-fixed-three-schema-v1',
        'historyPinsSha256': {'history-pins-private.json': HISTORY_BUNDLE_SHA256},
        'historyOriginalEvidenceSha256': dict(ORIGINAL_EVIDENCE_PINS), 'historyOwnershipSha256': OWNERSHIP_SHA256,
        'sourcePathNameSha256': hashlib.sha256(service['pathName'].encode()).hexdigest(),
        'processObservationSha256': checksum({'serviceProcess': parent, 'worker': worker}),
        'endpointBindingsSha256': hashlib.sha256(b'\n'.join(sorted(seen))).hexdigest()}


def validate_privileges(record):
    """Direct grants only; --routines requires global SELECT (MySQL manual)."""
    need(type(record) is dict and set(record) == {'schema', 'grants'}
         and type(record['schema']) is str and record['schema'] in SCHEMAS,
         'NONADMIN_FIXED_PRIVILEGE_SCOPE_REQUIRED')
    schema, grants = record['schema'], record['grants']
    need(type(grants) is list and 0 < len(grants) <= 32, 'NONADMIN_DIRECT_GRANTS_REQUIRED')
    global_privileges, effective = set(), set()
    for grant in grants:
        need(type(grant) is dict and set(grant) == {'scope', 'privileges'}
             and grant['scope'] in ('*.*', schema + '.*'), 'NONADMIN_UNREVIEWED_GRANT_SCOPE_REFUSED')
        values = grant['privileges']
        need(type(values) is list and 0 < len(values) <= 256
             and all(type(x) is str and re.fullmatch(r'[A-Z][A-Z_]*(?: [A-Z][A-Z_]*){0,4}', x) for x in values)
             and len(set(values)) == len(values), 'NONADMIN_DIRECT_PRIVILEGE_NAMES_REQUIRED')
        effective.update(values)
        if grant['scope'] == '*.*': global_privileges.update(values)
    # https://dev.mysql.com/doc/refman/8.0/en/mysqldump.html#option_mysqldump_routines
    need('SELECT' in global_privileges or 'ALL PRIVILEGES' in global_privileges,
         'NONADMIN_ROUTINE_GLOBAL_SELECT_REQUIRED')
    need('ALL PRIVILEGES' in effective or {'SELECT', 'TRIGGER', 'EVENT'} <= effective,
         'NONADMIN_REQUIRED_SCHEMA_READ_PRIVILEGES_MISSING')
    return {'scope': schema, 'select': True, 'trigger': True, 'event': True,
            'routines': True, 'directGrantsVerified': True}


def fingerprint(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode, info.st_nlink


def read_fixed_json(path, expected_sha):
    path = Path(path)
    need(path.is_absolute() and '..' not in path.parts, 'NONADMIN_FIXED_HISTORY_PATH_REQUIRED')
    for ancestor in (path, *path.parents):
        info = ancestor.lstat()
        need(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400
             and not getattr(ancestor, 'is_junction', lambda: False)(), 'NONADMIN_HISTORY_LINK_REFUSED')
    before = path.lstat()
    need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_ino != 0
         and 0 < before.st_size <= MAXIMUM, 'NONADMIN_BOUNDED_SINGLE_HISTORY_FILE_REQUIRED')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        need(fingerprint(os.fstat(stream.fileno())) == fingerprint(before), 'NONADMIN_HISTORY_IDENTITY_CHANGED')
        raw = stream.read(MAXIMUM + 1)
        need(fingerprint(os.fstat(stream.fileno())) == fingerprint(before), 'NONADMIN_HISTORY_CHANGED_DURING_READ')
    need(fingerprint(path.lstat()) == fingerprint(before) and len(raw) == before.st_size
         and hashlib.sha256(raw).hexdigest() == expected_sha, 'NONADMIN_HISTORY_PIN_MISMATCH')
    return decode(raw)


def validate_history(bundle):
    """The approved bundle fixes identity, ownership and all four old digests."""
    need(type(bundle) is dict and set(bundle) == {'kind', 'schemaVersion', 'configuration', 'schemas',
        'originalEvidenceSha256', 'ownership'} and bundle['kind'] == 'doorhandle-local-mysql-history-pin-bundle'
        and type(bundle['schemaVersion']) is int and bundle['schemaVersion'] == 1
        and type(bundle['schemas']) is list and bundle['schemas'] == list(SCHEMA_ORDER)
        and type(bundle['originalEvidenceSha256']) is dict
        and bundle['originalEvidenceSha256'] == ORIGINAL_EVIDENCE_PINS, 'NONADMIN_FIXED_HISTORY_BUNDLE_REQUIRED')
    ownership = bundle['ownership']
    need(type(ownership) is dict and set(ownership) == SCHEMAS, 'NONADMIN_CLOSED_SCHEMA_OWNERSHIP_REQUIRED')
    for schema, claim in ownership.items():
        need(type(claim) is dict and set(claim) == {'matchesPreviouslyInventoriedSchema', 'evidence'}
             and claim['matchesPreviouslyInventoriedSchema'] is True and type(claim['evidence']) is list
             and len(claim['evidence']) == (2 if schema == 'doorhandledb' else 3), 'NONADMIN_OWNERSHIP_EVIDENCE_REQUIRED')
        paths = set()
        for row in claim['evidence']:
            need(type(row) is dict and set(row) == {'path', 'sha256'} and type(row['path']) is str
                 and 0 < len(row['path']) <= 1024 and '\\' not in row['path'] and ':' not in row['path']
                 and all(part not in ('', '.', '..') for part in row['path'].split('/'))
                 and row['path'] not in paths and type(row['sha256']) is str
                 and re.fullmatch(r'[a-f0-9]{64}', row['sha256']), 'NONADMIN_FIXED_OWNERSHIP_MEMBER_REQUIRED')
            paths.add(row['path'])
    need(checksum(ownership) == OWNERSHIP_SHA256 and checksum(bundle) == HISTORY_CANONICAL_SHA256,
         'NONADMIN_HISTORY_CONTENT_PIN_MISMATCH')
    return configuration(bundle['configuration'])


def load_historical():
    # No arbitrary path argument and no dependency on retired original files.
    return validate_history(read_fixed_json(HISTORY_BUNDLE, HISTORY_BUNDLE_SHA256))


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    try:
        need(arguments in (['source'], ['privileges']), 'NONADMIN_FIXED_POLICY_ACTION_REQUIRED')
        raw = getattr(sys.stdin, 'buffer', sys.stdin).read(MAXIMUM + 1)
        if type(raw) is str: raw = raw.encode('utf8')
        record = decode(raw)
        value = validate_source(record, load_historical()) if arguments == ['source'] else validate_privileges(record)
        print(encoded(value).decode()); return 0
    except Exception as error:
        code = str(error) if isinstance(error, PolicyError) and re.fullmatch(r'[A-Z][A-Z0-9_]{1,100}', str(error)) else 'NONADMIN_POLICY_INPUT_INVALID'
        print(json.dumps({'status': 'REFUSED', 'errorCode': code}, sort_keys=True)); return 1


if __name__ == '__main__':
    raise SystemExit(main())
