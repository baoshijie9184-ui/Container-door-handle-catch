#!/usr/bin/env python3
"""External model key escrow and deployment guard. Never emits plaintext keys or accepts them in argv."""
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid

PROJECT = 'doorhandlecatch-monolith'
TARGET = '/run/secrets/model_config_master_key'
ZONE = dt.timezone(dt.timedelta(hours=8))
FORMAT_LABEL = 'io.doorhandle.model-config-format'


class SecretError(RuntimeError):
    pass


def sha(value):
    return hashlib.sha256(value).hexdigest()


def now():
    return dt.datetime.now(ZONE).isoformat()


def execute(args, data=None, pass_fds=()):
    try:
        result = subprocess.run(args, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=30, check=False, pass_fds=pass_fds)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SecretError('Secret operation unavailable') from error
    if result.returncode or len(result.stdout) > 1048576:
        raise SecretError('Secret operation failed; diagnostics withheld')
    return result.stdout


def openssl(*args, data=None, pass_fds=()):
    return execute(['openssl', *args], data, pass_fds)


def path(value, *, exists=True):
    candidate = Path(value)
    if not candidate.is_absolute() or not re.fullmatch(r'/[A-Za-z0-9_./-]+',str(candidate)) or any(part in ('.', '..') for part in candidate.parts):
        raise SecretError('Expected an absolute non-traversing secret path')
    if any(part.is_symlink() for part in (candidate, *candidate.parents)):
        raise SecretError('Secret paths cannot contain symbolic links')
    return candidate.resolve(strict=exists)


def bounded(file, limit, *, private=False, group_key=False):
    file = path(file)
    with os.fdopen(os.open(file, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit or before.st_nlink != 1:
            raise SecretError('Invalid secret file type, links or length')
        mode = stat.S_IMODE(before.st_mode)
        if private and mode & 0o077 or group_key and (mode not in (0o640,0o440) or before.st_gid != 10001):
            raise SecretError('Secret file permissions must be private; application key requires group 10001, mode 0640/0440')
        value = stream.read(limit+1)
        after = os.fstat(stream.fileno())
        identity = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns)
        if len(value) > limit or identity(before) != identity(after) or identity(before) != identity(file.stat()):
            raise SecretError('Secret changed during access')
        return value


def write_new(file, value, mode=0o600):
    file = path(file, exists=False)
    descriptor = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(descriptor, 'wb') as stream:
        os.fchmod(stream.fileno(), mode);stream.write(value);stream.flush();os.fsync(stream.fileno())
    directory = os.open(file.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def key_bytes(file):
    try:
        key = base64.b64decode(bounded(file, 128, group_key=True).strip(), validate=True)
    except (ValueError, TypeError) as error:
        raise SecretError('Invalid model key encoding') from error
    if len(key) != 32:
        raise SecretError('Model key must contain exactly 256 bits')
    return key


def private_directory(value):
    directory = path(value)
    if not directory.is_dir() or stat.S_IMODE(directory.stat().st_mode) & 0o077:
        raise SecretError('External backup directory must already exist with mode 0700')
    return directory


def public_certificate(file, fingerprint, *, allow_expired=False):
    content = bounded(file, 16384)
    if path(file).stat().st_mode & 0o022:raise SecretError('Recipient certificate cannot be writable by group or others')
    if b'PRIVATE KEY' in content or content.count(b'BEGIN CERTIFICATE') != 1:
        raise SecretError('Escrow recipient must contain one public certificate, never a private key')
    der = openssl('x509', '-outform', 'DER', data=content)
    if not re.fullmatch(r'[a-f0-9]{64}', fingerprint or '') or sha(der) != fingerprint:
        raise SecretError('Escrow recipient certificate fingerprint differs')
    # Certificate revocation is an operator decision. Expired recipients cannot create new backups.
    if not allow_expired:openssl('x509', '-checkend', '0', '-noout', data=content)
    public = openssl('x509', '-pubkey', '-noout', data=content)
    details = openssl('pkey', '-pubin', '-text', '-noout', data=public).decode('ascii')
    bits = re.search(r'Public-Key:\s*\((\d+) bit\)', details)
    if not bits or int(bits.group(1)) < 3072 or b'BEGIN PUBLIC KEY' not in public or 'Modulus:' not in details:
        raise SecretError('Escrow requires an RSA recipient with at least 3072 bits')
    return content


def load_settings(root, runtime):
    root, runtime = path(root), path(runtime)
    policy = runtime/'deploy/model-config-policy.json'
    pin = root/'state/model-key-pin.json'
    if not policy.exists():
        if policy.is_symlink() or pin.exists():
            raise SecretError('Model policy missing after key registration')
        return None
    setting = json.loads(bounded(policy, 8192, private=True))
    if setting.get('schema') != 1 or type(setting.get('enabled')) is not bool:
        raise SecretError('Invalid model Secret policy')
    if not setting['enabled']:
        if pin.exists() or set(setting) != {'schema', 'enabled'}:
            raise SecretError('Registered model governance cannot be silently disabled')
        return None
    required = {'schema', 'enabled', 'masterKeyFile', 'backupDirectory', 'recipientCertificate', 'recipientSha256'}
    if set(setting) != required:
        raise SecretError('Unexpected model Secret policy fields')
    source = path(setting['masterKeyFile']);vault = private_directory(setting['backupDirectory']);cert = path(setting['recipientCertificate'])
    if any(parent.stat().st_mode & 0o022 for candidate in (source,cert) for parent in candidate.parents if parent != Path('/')):
        raise SecretError('Secret and recipient ancestors cannot be writable by group or others')
    checkout = Path(__file__).resolve().parents[2]
    for candidate in (source, vault, cert):
        if any(candidate == denied or candidate.is_relative_to(denied) for denied in (root, runtime, checkout)):
            raise SecretError('Secret material and escrow must remain outside source, releases, runtime and database backups')
    if source.is_relative_to(vault) or cert.is_relative_to(vault):
        raise SecretError('Live Secret and recipient must be separate from the escrow directory')
    raw = key_bytes(source);public_certificate(cert, setting['recipientSha256'])
    identity = sha(raw)
    if pin.exists():
        previous = json.loads(bounded(pin, 8192, private=True))
        if previous.get('schema') != 1 or previous.get('keySha256') != identity:
            raise SecretError('Master key replacement requires a separate re-encryption migration')
    return {**setting, 'masterKeyFile':str(source), 'backupDirectory':str(vault),
            'recipientCertificate':str(cert), 'keySha256':identity}


def escrow_folder(setting):
    return Path(setting['backupDirectory'])/(setting['keySha256']+'-'+setting['recipientSha256'])


def inspect_bundle(folder, setting=None):
    folder = private_directory(folder)
    manifest = json.loads(bounded(folder/'manifest.json', 8192, private=True))
    ciphertext = bounded(folder/'master-key.cms', 65536, private=True)
    if manifest.get('schema') != 1 or manifest.get('project') != PROJECT or manifest.get('algorithm') != 'CMS-AES-256-GCM-RSA-OAEP-SHA256' or manifest.get('ciphertextSha256') != sha(ciphertext):
        raise SecretError('Escrow manifest or ciphertext digest differs')
    if any(not re.fullmatch(r'[a-f0-9]{64}', manifest.get(field, '')) for field in ('keySha256','recipientSha256')):
        raise SecretError('Escrow identity is invalid')
    if setting and any(manifest[field] != setting[field] for field in ('keySha256','recipientSha256')):
        raise SecretError('Escrow does not match the selected key and recipient')
    return manifest, ciphertext


def backup_key(root, runtime):
    setting = load_settings(root, runtime)
    if setting is None:
        return {'enabled':False}
    target = escrow_folder(setting)
    if not target.exists():
        scratch = Path(setting['backupDirectory'])/('.pending-'+uuid.uuid4().hex)
        scratch.mkdir(mode=0o700)
        # The plaintext exists only in this process and the OpenSSL stdin pipe, never a temp file.
        raw=key_bytes(setting['masterKeyFile'])
        if sha(raw)!=setting['keySha256']:raise SecretError('Model key changed before backup')
        payload = json_bytes({'schema':1, 'project':PROJECT, 'keySha256':setting['keySha256'],
                              'masterKeyBase64':base64.b64encode(raw).decode()})
        ciphertext = openssl('cms', '-encrypt', '-binary', '-outform', 'DER', '-aes-256-gcm',
                             '-recip', setting['recipientCertificate'], '-keyopt', 'rsa_padding_mode:oaep',
                             '-keyopt', 'rsa_oaep_md:sha256', '-keyopt', 'rsa_mgf1_md:sha256', data=payload)
        write_new(scratch/'master-key.cms', ciphertext)
        manifest = {'schema':1, 'project':PROJECT, 'createdAt':now(), 'algorithm':'CMS-AES-256-GCM-RSA-OAEP-SHA256',
                    'keySha256':setting['keySha256'], 'recipientSha256':setting['recipientSha256'],
                    'ciphertextSha256':sha(ciphertext)}
        write_new(scratch/'manifest.json', json_bytes(manifest))
        # A failed attempt leaves an explicitly pending encrypted directory, never an advertised complete backup.
        os.rename(scratch, target)
        descriptor=os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
    manifest, _ = inspect_bundle(target, setting)
    return {'enabled':True, 'keySha256':manifest['keySha256'], 'recipientSha256':manifest['recipientSha256'],
            'ciphertextSha256':manifest['ciphertextSha256'], 'backupId':target.name,
            'decryptionVerified':verify_proof(target, setting)}


def verify_proof(folder, setting):
    proof = folder/'restore-proof.cms'
    if not proof.exists():
        return False
    manifest, _ = inspect_bundle(folder, setting)
    # Trust is the manually pinned exact recipient certificate, not a permissive public CA lookup.
    body = openssl('cms', '-verify', '-binary', '-inform', 'DER', '-nointern', '-noverify',
                   '-certfile', setting['recipientCertificate'], data=bounded(proof, 65536, private=True))
    value = json.loads(body)
    return value.get('schema') == 1 and value.get('project') == PROJECT and value.get('restored') is True and all(value.get(field) == manifest[field] for field in ('keySha256','recipientSha256','ciphertextSha256'))


def verify_reference(root, runtime, reference):
    setting = load_settings(root, runtime)
    if not reference.get('enabled'):
        if setting:
            raise SecretError('Snapshot did not bind the model key escrow')
        return
    if setting is None:
        raise SecretError('Snapshot requires an external model key policy')
    manifest, _ = inspect_bundle(escrow_folder(setting), setting)
    if any(reference.get(field) != manifest[field] for field in ('keySha256','recipientSha256','ciphertextSha256')) or not verify_proof(escrow_folder(setting), setting):
        raise SecretError('Snapshot model key recovery evidence differs or is missing')


def status(root, runtime):
    setting=load_settings(root,runtime)
    if setting is None:return {'enabled':False,'healthy':True}
    folder=escrow_folder(setting)
    if not folder.exists():return {'enabled':True,'healthy':False,'backupPresent':False,'decryptionVerified':False}
    manifest,_=inspect_bundle(folder,setting);proof=verify_proof(folder,setting)
    return {'enabled':True,'healthy':proof,'backupPresent':True,'decryptionVerified':proof,'keySha256':manifest['keySha256']}


def deployment_guard(root, runtime, config, *, pin=False):
    setting = load_settings(root, runtime)
    services = config.get('services', {})
    if not setting:
        if any(str(services.get(name,{}).get('environment',{}).get(flag,'false')).lower() == 'true'
               for name,flag in (('backend','AGENT_MODEL_CONFIG_ENABLED'),('mem0','MODEL_CONFIG_ENABLED'))):
            raise SecretError('Model management requires an external key policy')
        for name in ('backend','mem0'):
            ids=execute(['docker','ps','-aq','--filter','label=com.docker.compose.project='+PROJECT,'--filter','label=com.docker.compose.service='+name]).decode().split()
            if ids:
                rows=json.loads(execute(['docker','inspect',*ids]))
                for row in rows:
                    configured=any(value in ('AGENT_MODEL_CONFIG_ENABLED=true','MODEL_CONFIG_ENABLED=true') for value in row.get('Config',{}).get('Env',[]))
                    if configured or any(mount.get('Destination')==TARGET for mount in row.get('Mounts',[])):
                        raise SecretError('Existing governed containers cannot lose their key policy during deploy or rollback')
        return {'enabled':False}
    receipt = backup_key(root, runtime)
    if not receipt['decryptionVerified']:
        raise SecretError('An offline signed restore proof is required before model management activation')
    secret = config.get('secrets',{}).get('model_config_master_key',{})
    if secret.get('file') != setting['masterKeyFile']:
        raise SecretError('Compose Secret source differs from the protected policy')
    for service,flag in (('backend','AGENT_MODEL_CONFIG_ENABLED'),('mem0','MODEL_CONFIG_ENABLED')):
        spec=services.get(service,{})
        if str(spec.get('environment',{}).get(flag,'false')).lower() != 'true' or spec.get('environment',{}).get('MODEL_CONFIG_MASTER_KEY_FILE') != TARGET:
            raise SecretError('Backend and memory must use the same file-based model configuration')
        mounts=spec.get('secrets',[])
        if not any(isinstance(mount,dict) and mount.get('source')=='model_config_master_key' and mount.get('target','model_config_master_key') in ('model_config_master_key',TARGET) for mount in mounts):
            raise SecretError('Application model key Secret mount is missing')
        image=spec.get('image')
        if not isinstance(image,str) or not image or image.startswith('-'):
            raise SecretError('Model configuration image identity unavailable')
        rows=json.loads(execute(['docker','image','inspect',image]))
        if len(rows)!=1 or rows[0].get('Config',{}).get('Labels',{}).get(FORMAT_LABEL) != '1':
            raise SecretError('Selected application image cannot safely read governed credentials; choose a compatible rollback image')
        current=execute(['docker','ps','-aq','--filter','label=com.docker.compose.project='+PROJECT,'--filter','label=com.docker.compose.service='+service]).decode().split()
        if len(current)!=1:raise SecretError('Expected one existing application container for compatibility rollback')
        actual=json.loads(execute(['docker','inspect',current[0]]))[0]
        current_image=json.loads(execute(['docker','image','inspect',actual['Image']]))[0]
        if current_image.get('Config',{}).get('Labels',{}).get(FORMAT_LABEL) != '1':
            raise SecretError('Establish a governance-capable rollback baseline with the feature disabled before first activation')
        for mount in actual.get('Mounts',[]):
            if mount.get('Destination')==TARGET and (mount.get('RW') or sha(key_bytes(mount['Source']))!=setting['keySha256']):
                raise SecretError('Existing application key mount differs from the protected policy')
    key_pin=Path(root)/'state/model-key-pin.json'
    if pin and not key_pin.exists():
        write_new(key_pin,json_bytes({'schema':1,'keySha256':setting['keySha256'],'registeredAt':now()}))
    return receipt


def restore_bundle(bundle, recipient, private_key, destination, *, passphrase_fd):
    folder=private_directory(bundle);manifest,ciphertext=inspect_bundle(folder)
    recipient=path(recipient);public_certificate(recipient,manifest['recipientSha256'],allow_expired=True)
    private_key=path(private_key);bounded(private_key,32768,private=True)
    destination=path(destination,exists=False)
    if destination.exists() or destination.is_relative_to(folder):
        raise SecretError('Restore requires a new file outside the encrypted bundle')
    if passphrase_fd is None:
        if not sys.stdin.isatty():raise SecretError('Offline recovery needs a terminal prompt or an inherited passphrase descriptor')
        import getpass
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('error',getpass.GetPassWarning)
            password=(getpass.getpass('Offline recovery key passphrase: ')+'\n').encode()
    elif passphrase_fd < 3:
        raise SecretError('Provide the offline private key passphrase through an inherited file descriptor')
    else:
        password=os.read(passphrase_fd,4097)
    # The descriptor is duplicated for signing because OpenSSL consumes it during decryption.
    # A private passphrase file is never passed to Jenkins or the deployment server.
    if len(password)>4096 or b'\x00' in password:
        raise SecretError('Invalid private passphrase descriptor')
    def private_operation(*args,data):
        reader,writer=os.pipe()
        try:
            os.write(writer,password);os.close(writer);writer=-1
            return openssl(*args,'-passin','fd:'+str(reader),data=data,pass_fds=(reader,))
        finally:
            os.close(reader)
            if writer!=-1:os.close(writer)
    plaintext=private_operation('cms','-decrypt','-binary','-inform','DER','-recip',str(recipient),'-inkey',str(private_key),data=ciphertext)
    value=json.loads(plaintext);raw=base64.b64decode(value.get('masterKeyBase64',''),validate=True)
    if value.get('schema')!=1 or value.get('project')!=PROJECT or len(raw)!=32 or sha(raw)!=manifest['keySha256'] or value.get('keySha256')!=sha(raw):
        raise SecretError('Restored model key does not match the bundle identity')
    write_new(destination,base64.b64encode(raw)+b'\n')
    proof=json_bytes({'schema':1,'project':PROJECT,'restored':True,'restoredAt':now(),**{field:manifest[field] for field in ('keySha256','recipientSha256','ciphertextSha256')}})
    signed=private_operation('cms','-sign','-binary','-nodetach','-nocerts','-outform','DER','-md','sha256','-signer',str(recipient),'-inkey',str(private_key),data=proof)
    write_new(folder/'restore-proof.cms',signed)
    return {'restored':True,'keySha256':manifest['keySha256'],'proofCreated':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['source','backup','guard','restore','status'])
    parser.add_argument('--root');parser.add_argument('--runtime');parser.add_argument('--pin',action='store_true')
    parser.add_argument('--bundle');parser.add_argument('--recipient');parser.add_argument('--private-key');parser.add_argument('--destination');parser.add_argument('--passphrase-fd',type=int)
    args=parser.parse_args()
    try:
        if os.name!='posix':raise SecretError('Run key operations in an existing trusted Linux environment')
        if args.action=='restore':
            if not all((args.bundle,args.recipient,args.private_key,args.destination)):raise SecretError('Missing offline recovery paths')
            result=restore_bundle(args.bundle,args.recipient,args.private_key,args.destination,passphrase_fd=args.passphrase_fd)
        else:
            if not args.root or not args.runtime:raise SecretError('Missing deployment paths')
            root,runtime=path(args.root),path(args.runtime)
            with os.fdopen(os.open(root/'state/model-key.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600),'a') as lock:
                import fcntl
                os.fchmod(lock.fileno(),0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                if args.action=='source':
                    setting=load_settings(root,runtime);print(setting['masterKeyFile'] if setting else 'disabled');return
                result=status(root,runtime) if args.action=='status' else backup_key(root,runtime) if args.action=='backup' else deployment_guard(root,runtime,json.load(sys.stdin),pin=args.pin)
        print(json.dumps(result))
    except Exception:
        print('Model Secret operation did not complete; review the private policy, escrow and recovery proof. No key was printed.',file=sys.stderr)
        raise SystemExit(6)


if __name__=='__main__':main()
