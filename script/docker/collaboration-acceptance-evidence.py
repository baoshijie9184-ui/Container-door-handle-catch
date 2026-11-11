"""Pure validation of five original public collaboration receipts; no runtime IO."""
import hashlib
import importlib.util
from pathlib import Path


PREFIX = 'checkout/work/runtime-acceptance/'
CONTEXT = ('schemaVersion', 'kind', 'release', 'commit', 'sourceSha256', 'identity',
           'acceptanceProfileSha256', 'candidateBuildSha256')
STAGES = ('preflight', 'admission', 'authorization')
HTTP = ('claim', 'personnel')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


browser = load('collaboration_receipt_bytes', Path(__file__).with_name('collaboration-browser-evidence.py'))
stable = load('collaboration_stable_policy', Path(__file__).with_name('compact-runtime-stable-identity.py'))
http = load('collaboration_http_policy', Path(__file__).with_name('compact-collaboration-http.py'))


def require(value, message):
    if not value: raise ValueError(message)


def digest(value):
    return hashlib.sha256(value.encode('utf8')).hexdigest()


def public_values(value, depth=0):
    require(depth <= 12, 'Public receipt nesting exceeded its bound')
    if type(value) is dict:
        forbidden = {'password', 'username', 'cookie', 'cookies', 'token', 'apikey', 'secret', 'content', 'body', 'messages', 'expectedname'}
        require(all(isinstance(key, str) and key.lower().replace('_', '') not in forbidden for key in value),
                'Private identity, transport or message fields cannot be archived')
        for child in value.values(): public_values(child, depth + 1)
    elif type(value) is list:
        require(len(value) <= 128, 'Public receipt collection exceeded its bound')
        for child in value: public_values(child, depth + 1)
    elif isinstance(value, str): require(len(value) <= 512, 'Unbounded public receipt text')
    else: require(value is None or type(value) in (bool, int, float), 'Unexpected public receipt value')


def catalog(cleanup):
    identities, requests = cleanup.get('stableIdentityEvidence', {}), cleanup.get('collaborationHttpEvidence', {})
    require(type(identities) is dict and set(identities) <= set(STAGES)
            and type(requests) is dict and set(requests) <= set(HTTP), 'Unexpected collaboration receipt catalog')
    result = {}
    for stage, reference in identities.items():
        name = 'stable-identity-' + stage + '.json'
        require(type(reference) is dict and set(reference) == {'file', 'sha256', 'status'}
                and reference.get('status') in ('PREFLIGHT_ONLY', 'PASS', 'BLOCKED'), 'Invalid identity receipt reference')
        result[name] = reference
    for stage, reference in requests.items():
        name = 'collaboration-http-' + stage + '.json'
        require(type(reference) is dict and set(reference) == {'file', 'sha256'}, 'Invalid HTTP receipt reference')
        result[name] = reference
    for name, reference in result.items():
        require(reference.get('file') == PREFIX + name and isinstance(reference.get('sha256'), str)
                and browser.SHA.fullmatch(reference['sha256']), 'Collaboration receipt escaped its fixed public path')
    return result


def validate_files(directory, cleanup, proof=None, browser_report=None, *, owned_runtime_directory=False):
    directory = Path(directory)
    context = {key: cleanup[key] for key in CONTEXT}
    references, values = catalog(cleanup), {}
    if not owned_runtime_directory:
        observed = {path.name for path in directory.iterdir()}
        require(observed == set(references), 'Uncataloged or missing collaboration receipt bytes')
    for name, reference in references.items():
        raw, checksum = browser.raw_file(directory / name, 256 * 1024)
        require(checksum == reference['sha256'], 'Original collaboration receipt bytes changed')
        value = browser.decode(raw); public_values(value); values[name] = value
        if name.startswith('stable-identity-'):
            stage = name[len('stable-identity-'):-len('.json')]
            require(value.get('kind') == 'doorhandle-runtime-stable-identity' and value.get('runtimeKind') == context['kind']
                    and value.get('stage') == stage and value.get('status') == reference['status']
                    and all(value.get(key) == data for key, data in context.items() if key != 'kind')
                    and value.get('projectSha256') == digest(cleanup['project'])
                    and value.get('mappingAppliedByRunner') is False and value.get('directSqlModeChanges') is False
                    and value.get('legacyModeAccepted') is False and value.get('historicalNamesInPublicEvidence') is False
                    and browser.SHA.fullmatch(value.get('targetSchemaSha256', ''))
                    and browser.SHA.fullmatch(value.get('migrationReceiptSha256', ''))
                    and browser.SHA.fullmatch(value.get('initialTargetSnapshotSha256', '')),
                    'Identity receipt belongs to another source, scope or stage')
            if value['status'] == 'BLOCKED':
                require(isinstance(value.get('reason'), str) and 1 <= len(value['reason']) <= 128
                        and all(char in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789' for char in value['reason']),
                        'Uncontrolled identity failure text cannot be archived')
        else:
            require(all(value.get(key) == data for key, data in context.items())
                    and value.get('project') == cleanup['project'] and value.get('status') == 'PASS'
                    and type(value.get('observations')) is dict, 'HTTP receipt belongs to another source or runtime')
    if proof is None:
        return {'status': 'PRESERVED', 'files': len(values)}
    require(set(cleanup.get('stableIdentityEvidence', {})) == set(STAGES)
            and set(cleanup.get('collaborationHttpEvidence', {})) == set(HTTP)
            and all(proof.get(key) == data for key, data in context.items())
            and proof.get('project') == cleanup['project'] and proof.get('status') == 'PASS'
            and cleanup.get('status') == 'STOPPED', 'Successful runtime requires all five original collaboration receipts')
    identity = proof.get('stableIdentity', {})
    require(type(identity) is dict and set(identity) == {'status', 'admission', 'authorization', 'legacyModeAccepted'}
            and identity.get('status') == 'PASS' and identity.get('legacyModeAccepted') is False
            and identity.get('admission') == cleanup['stableIdentityEvidence']['admission']
            and identity.get('authorization') == cleanup['stableIdentityEvidence']['authorization']
            and proof.get('collaborationHttpAcceptance') == cleanup['collaborationHttpEvidence'],
            'Runtime collaboration proof differs from original cleanup references')
    require(type(browser_report) is dict and browser_report.get('status') == 'PASS'
            and browser_report.get('commit') == context['commit'] and browser_report.get('sourceSha256') == context['sourceSha256'],
            'Actual browser account evidence is required for collaboration identities')
    accounts = browser_report.get('accounts', {})
    require(set(accounts) == browser.ACCOUNTS and len({row['userId'] for row in accounts.values()}) == 4,
            'Four actual independent browser identities are required')
    preflight, admitted, authorization = (values['stable-identity-' + stage + '.json'] for stage in STAGES)
    for value in (preflight, admitted, authorization):
        require(value.get('migrationReceiptSha256') == proof.get('migrationReceiptSha256')
                and value.get('initialTargetSnapshotSha256') == proof.get('initialTargetSnapshotSha256')
                and value['targetSchemaSha256'] == admitted['targetSchemaSha256'], 'Identity admission used another migrated target')
    stable.validate_final_values(preflight, admitted, authorization, accounts, proof['actualServerUuid'])
    actual = http.validate_observations(values['collaboration-http-claim.json'], values['collaboration-http-personnel.json'], accounts)
    require(authorization['taskBinding'].get('taskIdSha256') == digest(actual['taskId']),
            'Stable authorization and actual candidate claim used different worker tasks')
    return {'status': 'VERIFIED', 'files': 5, 'stableIdentityVerified': True, 'actualHttpCollaborationVerified': True}
