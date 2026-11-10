"""Closed byte custody for the separately approved, ordinary-user three-schema export.

No database client is invoked here. The caller must supply the actual completed
batch receipt SHA, and later fixed Jenkins input hashes; no sample source pins
can authorize a real export, recovery, business merge or local retirement.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import ntpath
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
PROJECT = Path('D:/AI/lunwen1/DoorHandleCatch')
SCHEMAS = ('doorhandledb', 'doorhandle_agent_verify_ef8d5844c1', 'doorhandle_model_verify_22e4bc5566')
PROFILE = 'project-mysql-three-schema-v2'
KIND = 'doorhandle-project-mysql-custody'
MIB = 1024 ** 2
MAX_BYTES = 4 * 1024 ** 3
SHA = re.compile(r'[a-f0-9]{64}')
EXPORT_MEMBERS = frozenset({'authorization-private.json', 'credential-handle-private.json',
    'before-identity-private.json', 'after-identity-private.json', 'before-catalog-private.jsonl',
    'after-catalog-private.jsonl', 'before-row-counts-private.jsonl', 'after-row-counts-private.jsonl',
    'before-grants-private.txt', 'after-grants-private.txt', 'before-privileges-private.json',
    'after-privileges-private.json', 'schema-before.sql', 'schema-after.sql', 'database.sql',
    'database.sql.gz', 'public-manifest.json'})
BATCH_MEMBERS = frozenset({'authorization-private.json', 'batch-result-private.json',
                         *(schema + '-result.json' for schema in SCHEMAS)})
PRODUCERS = {'worker': 'export-legacy-local-mysql.ps1', 'batch': 'export-remaining-local-mysql.ps1',
             'sourceHelper': 'nonadmin-local-mysql-source.ps1', 'policy': 'nonadmin-local-mysql-policy.py'}
MEMBERS = frozenset({'batch/' + name for name in BATCH_MEMBERS}
    | {'schemas/' + schema + '/' + name for schema in SCHEMAS for name in EXPORT_MEMBERS}
    | {'producer/' + name for name in PRODUCERS.values()})
SNAPSHOT = 'project-mysql-snapshot'
RESTORE = 'project-mysql-originals'


def need(value, message):
    if not value: raise ValueError(message)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def legacy(): return module('three_schema_existing_custody', ROOT / 'script/jenkins/preserve-local-mysql.py')
def common(): return legacy().common()
def digest(path): return legacy().digest(path)
def read(path): return common().read_json(path, maximum=MIB)
def write(path, value): return legacy().write(path, value)
def sha(value): return legacy().sha(value)


def member_paths(directory):
    utility = common(); directory = utility.safe(directory)
    need({path.relative_to(directory).as_posix() for path in directory.rglob('*') if path.is_file()} == MEMBERS,
         'The closed packet original membership differs')
    result = {}
    for name in MEMBERS:
        path = utility.safe(directory / name); info = path.stat()
        need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= MAX_BYTES,
             'Only bounded unlinked regular originals are admitted')
        result[name] = path
    return result


def decode_lines(path):
    need(path.stat().st_size <= MIB, 'Bounded original observation required')
    return [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line]


def validate_exports(batch, authorization, exports, batch_sha, producer):
    """Validate the actual v2 producer fields, without pretending to hash live rows."""
    need(SHA.fullmatch(batch_sha) and batch.get('schemaVersion') == 2
        and batch.get('kind') == 'doorhandle-nonadmin-remaining-local-mysql-export'
        and batch.get('status') == 'LOCAL_EXPORTS_COMPLETE_ECS_RESTORE_PENDING'
        and batch.get('sourceMode') == 'PINNED_HISTORY_FRESH_SERVICE_TCP' and batch.get('restorePending') is True,
        'A complete actual ordinary-user batch is required')
    need(all(type(batch.get(key)) is list and len(batch[key]) == len(set(batch[key])) == 3
             and set(batch[key]) == set(SCHEMAS) for key in ('sourceSchemas', 'completedSchemas'))
        and set(exports) == set(SCHEMAS) and batch.get('failedSchema') is None and batch.get('errorType') is None,
        'All three exact schemas must complete once')
    need(all(batch.get(key) is False for key in ('sourceMutationsRequested', 'servicesChanged', 'testsExecuted',
        'cloudUploaded', 'backupRestoreVerified', 'retirementAllowed', 'automaticRetryAllowed')),
        'Export preservation boundaries differ')
    dependency = batch.get('dependencySha256', {})
    need(set(dependency) == {'sourceHelper', 'policy', 'interpreter'}
        and all(type(value) is str and SHA.fullmatch(value) for value in dependency.values()),
        'The actual export dependency bindings are incomplete')
    need(set(producer) == set(PRODUCERS)
        and all(type(body) is bytes and 0 < len(body) <= MIB
                and body.replace(b'\r\n', b'\n') == (ROOT / 'script/jenkins' / PRODUCERS[name]).read_bytes().replace(b'\r\n', b'\n')
                for name, body in producer.items()), 'Producer code differs beyond Git CRLF/LF checkout encoding')
    producer_sha = {name: hashlib.sha256(body).hexdigest() for name, body in producer.items()}
    need(batch.get('workerScriptSha256') == producer_sha['worker']
        and all(dependency[name] == producer_sha[name] for name in ('sourceHelper', 'policy')),
        'The approved batch must use this fixed export implementation')
    need(authorization.get('kind') == 'doorhandle-nonadmin-remaining-local-mysql-export-authorization'
        and authorization.get('sourceSchemas') == batch['sourceSchemas']
        and authorization.get('newOneTimeReadOnlyExceptionAcknowledged') is True
        and authorization.get('includeLegacyBusinessSource') is True
        and authorization.get('userAuthorizationReference') == batch.get('userAuthorizationReference')
        and type(batch.get('userAuthorizationReference')) is str
        and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,180}', batch['userAuthorizationReference'])
        and authorization.get('workerScriptSha256') == batch['workerScriptSha256']
        and authorization.get('batchScriptSha256') == producer_sha['batch']
        and authorization.get('dependencySha256') == dependency,
        'The original batch authorization does not close')
    entries = batch.get('exports')
    need(type(entries) is list and len(entries) == 3 and {item.get('sourceSchema') for item in entries} == set(SCHEMAS),
         'The successful batch export catalogue differs')
    for schema, public in exports.items():
        entry = next(item for item in entries if item['sourceSchema'] == schema)
        need(public.get('schemaVersion') == 2 and public.get('kind') == 'doorhandle-nonadmin-local-mysql-export'
            and public.get('status') == entry.get('status') == 'LOCAL_EXPORT_COMPLETE_RESTORE_PENDING'
            and public.get('sourceSchema') == schema and public.get('sourceEndpoint') == '127.0.0.1:3306'
            and public.get('sourceMode') == 'PINNED_HISTORY_FRESH_SERVICE_TCP'
            and public.get('scriptSha256') == batch['workerScriptSha256']
            and public.get('sourceHelperSha256') == dependency['sourceHelper']
            and public.get('policySha256') == dependency['policy']
            and public.get('policyInterpreterSha256') == dependency['interpreter']
            and public.get('rowEvidence') == 'BEFORE_AFTER_OBSERVATIONS_NOT_THE_DUMP_TRANSACTION'
            and public.get('ddlEvidence') == 'MATCHING_RESTRICTED_BEFORE_AFTER_DDL'
            and public.get('dumpConsistency') == 'MYSQLDUMP_SINGLE_TRANSACTION_INNODB',
            'The schema export source or consistency claim differs')
        need(all(public.get(key) is True for key in ('restorePending', 'historicalConfigurationPinVerified',
            'freshServiceEndpointVerified', 'freshDirectPrivilegesVerified', 'actualClientIdentityVerified',
            'privateInputFilesRemoved', 'gzipByteReadbackVerified'))
            and all(public.get(key) is False for key in ('sourceConfigurationVerified', 'credentialsArchived',
            'sourceDeleted', 'servicesChanged', 'testsExecuted', 'cloudUploaded', 'backupRestoreVerified', 'retirementAllowed')),
            'The schema preservation evidence is incomplete')
        need(type(public.get('tableCount')) is int and 0 < public['tableCount'] <= 128
            and public['tableCount'] == entry.get('tableCount')
            and all(type(public.get(key)) is int and public[key] >= 0 and public[key] == entry.get(key)
                    for key in ('observedRowsBefore', 'observedRowsAfter'))
            and public['observedRowsBefore'] == public['observedRowsAfter'], 'Observed source counts differ')
        need(set(public.get('files', {})) == EXPORT_MEMBERS - {'public-manifest.json'},
             'Credential or incomplete side files cannot enter the packet')
        for name, checksum, limit in (('database.sql', 'rawSqlSha256', 512 * MIB), ('database.sql.gz', 'gzipSha256', 512 * MIB)):
            size = 'rawSqlBytes' if name == 'database.sql' else 'gzipBytes'
            need(type(public.get(size)) is int and 0 < public[size] <= limit
                and type(public.get(checksum)) is str and SHA.fullmatch(public[checksum])
                and public[checksum] == entry.get(checksum)
                and public['files'][name] == {'bytes': public[size], 'sha256': public[checksum]},
                'Original SQL byte bindings differ')


def verify_originals(paths, batch_sha):
    need(digest(paths['batch/batch-result-private.json']) == batch_sha, 'The caller-pinned batch receipt changed')
    batch = read(paths['batch/batch-result-private.json'])
    exports = {schema: read(paths['schemas/' + schema + '/public-manifest.json']) for schema in SCHEMAS}
    producer = {name: paths['producer/' + file].read_bytes() for name, file in PRODUCERS.items()}
    validate_exports(batch, read(paths['batch/authorization-private.json']), exports, batch_sha, producer)
    source_identity = None; result = {}
    for schema, public in exports.items():
        prefix = 'schemas/' + schema + '/'
        item = next(entry for entry in batch['exports'] if entry['sourceSchema'] == schema)
        need(read(paths['batch/' + schema + '-result.json']) == item
            and digest(paths[prefix + 'public-manifest.json']) == item['manifestSha256'], 'Per-schema batch receipt changed')
        for name, binding in public['files'].items():
            need(set(binding) == {'bytes', 'sha256'} and type(binding['bytes']) is int
                and paths[prefix + name].stat().st_size == binding['bytes']
                and digest(paths[prefix + name]) == binding['sha256'], 'An original export member changed')
        for suffix in ('catalog-private.jsonl', 'row-counts-private.jsonl', 'privileges-private.json'):
            need(paths[prefix + 'before-' + suffix].read_bytes() == paths[prefix + 'after-' + suffix].read_bytes(),
                 'Before/after schema observations differ')
        need(paths[prefix + 'schema-before.sql'].read_bytes() == paths[prefix + 'schema-after.sql'].read_bytes(),
             'Before/after source DDL differs')
        identities = [read(paths[prefix + phase + '-identity-private.json']) for phase in ('before', 'after')]
        need(identities[0] == identities[1] and identities[0].get('schema') == schema,
             'The actual export endpoint identity changed')
        authorization = read(paths[prefix + 'authorization-private.json'])
        credential = read(paths[prefix + 'credential-handle-private.json'])
        expected = authorization.get('sourceProcess', {}).get('configuration', {})
        need(authorization.get('kind') == 'doorhandle-nonadmin-local-mysql-export-authorization'
            and authorization.get('sourceSchema') == schema
            and authorization.get('userAuthorizationReference') == batch['userAuthorizationReference']
            and authorization.get('oneTimeReadOnlyExceptionAcknowledged') is True
            and authorization.get('additionalFixtureReadOnlyExceptionAcknowledged') is True
            and authorization.get('sourceMode') == 'PINNED_HISTORY_FRESH_SERVICE_TCP'
            and expected.get('expectedServerUuid') == identities[0].get('serverUuid')
            and type(expected.get('expectedDataDirectory')) is str and type(identities[0].get('dataDirectory')) is str
            and ntpath.normcase(ntpath.normpath(expected['expectedDataDirectory']))
                == ntpath.normcase(ntpath.normpath(identities[0]['dataDirectory']))
            and identities[0].get('port') == 3306 and str(identities[0].get('version', '')).startswith('8.3.'),
            'The original source authorization and actual endpoint differ')
        need(credential.get('kind') == 'doorhandle-fixed-credential-read-observation'
            and all(credential.get(key) is False for key in ('sourceContentModified', 'sourceAclModified', 'credentialValuesIncluded'))
            and credential.get('sourceSha256') == authorization.get('credentialSourceSha256')
                == public.get('credentialSourceSha256') == '97c366105bd23057d4733636b05766eb36e03da1a07af6e8b37dd0c4c90e6b2b',
            'The credential read observation does not preserve the approved source boundary')
        privileges = read(paths[prefix + 'before-privileges-private.json'])
        need(privileges.get('scope') == schema
            and all(privileges.get(key) is True for key in ('select', 'trigger', 'event', 'routines', 'directGrantsVerified')),
            'The original direct read privileges were not verified')
        identity = {key: value for key, value in identities[0].items() if key != 'schema'}
        need(source_identity is None or source_identity == identity, 'The three exports came from different actual servers')
        source_identity = identity
        catalog = decode_lines(paths[prefix + 'before-catalog-private.jsonl'])
        counts = decode_lines(paths[prefix + 'before-row-counts-private.jsonl'])
        names = [row['table'] for row in catalog]
        need(len(names) == len(set(names)) == public['tableCount']
            and all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', name) for name in names)
            and all(row.get('kind') == 'BASE TABLE' and row.get('engine') == 'InnoDB' for row in catalog)
            and [row['table'] for row in counts] == names
            and all(type(row['rows']) is int and row['rows'] >= 0 for row in counts)
            and sum(row['rows'] for row in counts) == public['observedRowsBefore'], 'Original full table observations differ')
        checksum, expanded = hashlib.sha256(), 0
        with gzip.open(paths[prefix + 'database.sql.gz'], 'rb') as stream:
            for block in iter(lambda: stream.read(MIB), b''):
                expanded += len(block); need(expanded <= public['rawSqlBytes'], 'Gzip expansion exceeds original SQL')
                checksum.update(block)
        need(expanded == public['rawSqlBytes'] and checksum.hexdigest() == public['rawSqlSha256'],
             'Compressed SQL does not reproduce exact raw source bytes')
        result[schema] = {'tables': names, 'counts': {row['table']: row['rows'] for row in counts},
            'rawSqlSha256': public['rawSqlSha256'], 'rawSqlBytes': public['rawSqlBytes'],
            'manifestSha256': item['manifestSha256'], 'purpose': 'BUSINESS_SOURCE' if schema == 'doorhandledb' else 'FIXTURE_ARCHIVE_ONLY'}
    return result


def pack(batch_directory, batch_sha, output):
    """Byte copy only, after a separately authorized export actually completed."""
    utility = common(); directory = utility.safe(batch_directory); output = utility.safe(output, exists=False)
    need(directory.parent == PROJECT / 'work/jenkins' and directory.name.startswith('remaining-local-mysql-export-')
        and output.parent == PROJECT / 'work/data-migration-20261107' and output.name.startswith('project-mysql-custody-')
        and not output.exists() and {p.name for p in directory.iterdir()} == BATCH_MEMBERS,
        'Use the exact completed batch and a fresh project-private packet')
    paths = {'batch/' + name: utility.safe(directory / name) for name in BATCH_MEMBERS}
    paths.update({'producer/' + file: utility.safe(ROOT / 'script/jenkins' / file) for file in PRODUCERS.values()})
    batch = read(paths['batch/batch-result-private.json'])
    need(digest(paths['batch/batch-result-private.json']) == batch_sha, 'The externally pinned actual batch receipt differs')
    for entry in batch.get('exports', []):
        schema = entry.get('sourceSchema'); need(schema in SCHEMAS, 'Unknown schema export')
        source = utility.safe(entry['exportDirectory'])
        need(source.parent == PROJECT / 'work/data-migration-20261107' and source.name.startswith('local-mysql-export-')
            and {path.name for path in source.iterdir()} == EXPORT_MEMBERS, 'The export directory contains unknown or missing files')
        paths.update({'schemas/' + schema + '/' + name: utility.safe(source / name) for name in EXPORT_MEMBERS})
    need(set(paths) == MEMBERS, 'The complete three-schema byte input is required')
    specifications = verify_originals(paths, batch_sha)
    rows, states = [], {}
    for name, path in sorted(paths.items()):
        info = path.stat(); need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'Unlinked regular originals required')
        rows.append({'member': name, 'bytes': info.st_size, 'sha256': digest(path), 'permissions': utility.permissions(path)})
        states[name] = utility.fingerprint(info)
        need(utility.fingerprint(path.stat()) == states[name], 'Original changed during admission')
    total = sum(row['bytes'] for row in rows)
    need(0 < total <= MAX_BYTES and shutil.disk_usage(output.parent).free >= utility.DISK_FLOOR + total,
         'Packet or workstation reserve exceeds its bound')
    utility.private_directory(output); archive = output / 'originals.tar.gz'
    with tarfile.open(archive, 'x:gz', format=tarfile.USTAR_FORMAT) as tar:
        for row in rows:
            path = paths[row['member']]; need(utility.fingerprint(path.stat()) == states[row['member']], 'Original identity changed')
            item = tarfile.TarInfo(row['member']); item.size = row['bytes']; item.mode = 0o600
            item.mtime = row['permissions']['mtimeNs'] // 1000000000
            with path.open('rb') as stream: tar.addfile(item, stream)
            need(digest(path) == row['sha256'] and utility.fingerprint(path.stat()) == states[row['member']], 'Original changed during copy')
    if os.name != 'nt': os.chmod(archive, 0o600)
    manifest = {'schemaVersion': 2, 'kind': KIND, 'profile': PROFILE, 'status': 'PACKED_RESTORE_PENDING',
        'batchReceiptSha256': batch_sha, 'files': rows, 'originalBytes': total, 'schemas': specifications,
        'catalogSha256': sha([[row['member'], row['bytes'], row['sha256']] for row in rows]),
        'archiveBytes': archive.stat().st_size, 'archiveSha256': digest(archive),
        'liveSourceRowHashesVerified': False, 'productionMerged': False, 'retirementAllowed': False}
    write(output / 'custody.json', manifest)
    return {'status': manifest['status'], 'manifestSha256': digest(output / 'custody.json'),
        'manifestBytes': (output / 'custody.json').stat().st_size, 'archiveSha256': manifest['archiveSha256'],
        'archiveBytes': manifest['archiveBytes'], 'batchReceiptSha256': batch_sha,
        'databasesOpened': 0, 'productionMerged': False, 'retirementAllowed': False}


def admit(args):
    work, context = legacy().admit(args)
    need(type(args.batch_receipt_sha256) is str and SHA.fullmatch(args.batch_receipt_sha256), 'Actual external batch SHA required')
    archive = Path(args.root) / 'inbox' / args.tag / 'source.tar.gz'
    with tarfile.open(archive, 'r:gz') as source:
        for name in ('project-mysql-custody.py', 'restore-project-mysql.py', 'export-legacy-local-mysql.ps1',
                     'export-remaining-local-mysql.ps1', 'nonadmin-local-mysql-source.ps1', 'nonadmin-local-mysql-policy.py'):
            member = source.getmember('script/jenkins/' + name)
            need(member.isfile() and 0 < member.size <= MIB
                and hashlib.sha256(source.extractfile(member).read(MIB + 1)).hexdigest() == digest(ROOT / 'script/jenkins' / name),
                'Three-schema code differs from the fixed source')
    return work, {**context, 'kind': KIND, 'profile': PROFILE, 'batchReceiptSha256': args.batch_receipt_sha256}


def verified_inputs(args, work):
    utility = common(); snapshot = utility.owner_path(work / SNAPSHOT, directory=True)
    need({p.name for p in snapshot.iterdir()} == {'custody.json', 'originals.tar.gz'}, 'Closed ECS transfer inputs required')
    for name, prefix, limit in (('custody.json', 'manifest', MIB), ('originals.tar.gz', 'archive', MAX_BYTES)):
        path = utility.owner_path(snapshot / name); size = getattr(args, prefix + '_bytes'); checksum = getattr(args, prefix + '_sha256')
        need(type(size) is int and 0 < size <= limit and type(checksum) is str and SHA.fullmatch(checksum)
            and path.stat().st_size == size and digest(path) == checksum, 'Explicit Jenkins byte input differs')
    value = read(snapshot / 'custody.json'); rows = value.get('files', [])
    need(value.get('schemaVersion') == 2 and value.get('kind') == KIND and value.get('profile') == PROFILE
        and value.get('status') == 'PACKED_RESTORE_PENDING' and value.get('batchReceiptSha256') == args.batch_receipt_sha256
        and len(rows) == len(MEMBERS) and {row.get('member') for row in rows} == MEMBERS
        and all(set(row) == {'member', 'bytes', 'sha256', 'permissions'} and type(row['bytes']) is int
                and 0 < row['bytes'] <= MAX_BYTES and SHA.fullmatch(row['sha256']) for row in rows)
        and value.get('originalBytes') == sum(row['bytes'] for row in rows) <= MAX_BYTES
        and value.get('catalogSha256') == sha([[row['member'], row['bytes'], row['sha256']] for row in rows])
        and value.get('archiveBytes') == args.archive_bytes and value.get('archiveSha256') == args.archive_sha256
        and all(value.get(key) is False for key in ('liveSourceRowHashesVerified', 'productionMerged', 'retirementAllowed')),
        'Closed actual three-schema custody manifest differs')
    return value


def restore_bytes(args):
    work, context = admit(args); utility = common(); manifest = verified_inputs(args, work)
    output = utility.safe(work / RESTORE, exists=False); need(not output.exists(), 'Use a fresh ECS original recovery')
    utility.resource_guard(work, manifest['originalBytes']); utility.private_directory(output)
    rows = {row['member']: row for row in manifest['files']}; seen = set()
    class ClosedHeader(tarfile.TarInfo):
        def _proc_member(self, archive):
            need(self.type in (tarfile.REGTYPE, tarfile.AREGTYPE) and self.name in rows
                and self.size == rows[self.name]['bytes'], 'Nonregular, expanded or unknown archive header refused')
            return super()._proc_member(archive)
    with tarfile.open(work / SNAPSHOT / 'originals.tar.gz', 'r:gz', tarinfo=ClosedHeader) as archive:
        for item in archive:
            need(item.name not in seen and not item.issparse(), 'Duplicate or sparse original refused')
            target = output / item.name; target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            with archive.extractfile(item) as incoming, os.fdopen(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stream:
                copied = 0
                for block in iter(lambda: incoming.read(MIB), b''):
                    copied += len(block); need(copied <= item.size, 'Original expanded beyond its fixed bound'); stream.write(block)
                stream.flush(); os.fsync(stream.fileno())
            need(copied == item.size and digest(target) == rows[item.name]['sha256'], 'Original byte recovery differs')
            seen.add(item.name)
    need(seen == MEMBERS and verify_originals(member_paths(output), args.batch_receipt_sha256) == manifest['schemas'],
         'The complete recovered original packet differs')
    result = {**context, 'status': 'BYTES_RESTORED_VERIFIED', 'manifestSha256': args.manifest_sha256,
        'archiveSha256': args.archive_sha256, 'catalogSha256': manifest['catalogSha256'],
        'databasesOpened': 0, 'sqlDoubleRestoreVerified': False, 'productionMerged': False, 'retirementAllowed': False}
    write(output / 'restore-receipt.json', result)
    return {**result, 'restoreReceiptSha256': digest(output / 'restore-receipt.json')}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('action', choices=('pack', 'prepare', 'restore'))
    for name in ('batch-directory', 'output', 'root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id',
                 'batch-receipt-sha256', 'manifest-sha256', 'archive-sha256'): parser.add_argument('--' + name)
    for name in ('manifest-bytes', 'archive-bytes'): parser.add_argument('--' + name, type=int)
    args = parser.parse_args()
    if args.action == 'pack': result = pack(args.batch_directory, args.batch_receipt_sha256, args.output)
    elif args.action == 'prepare':
        work, _context = admit(args); path = common().safe(work / SNAPSHOT, exists=False)
        need(not path.exists() and not (work / RESTORE).exists(), 'Fresh ECS packet transfer required')
        common().private_directory(path); result = {'status': 'TRANSFER_DIRECTORY_PREPARED', 'directory': str(path)}
    else: result = restore_bytes(args)
    print(json.dumps(result))


if __name__ == '__main__': main()
