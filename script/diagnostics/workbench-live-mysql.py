"""Isolated workbench live-evaluation MySQL database; never uses the application schema.

Uses existing SSH and Docker. A short-lived account has grants only on its own random
database. Private credentials and tunnel identity remain under ignored project work/.
"""
import argparse
import ipaddress
import json
import re
import socket
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SSH = ['ssh', '-F', str(ROOT / 'work/cloud/ssh-config'), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8']
HOST = 'doorhandle-bj'
CONTAINER = 'doorhandlecatch-monolith-mysql-1'
MYSQL = f'''sudo -n docker exec -i {CONTAINER} sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --batch --skip-column-names' '''
PORT = 13310


def remote(command, stdin=None):
    result = subprocess.run(SSH + [HOST, command], input=stdin, capture_output=True,
                            text=True, encoding='utf8', timeout=30)
    if result.returncode:
        raise RuntimeError('SSH/MySQL verification command failed; credentials are not displayed')
    return result.stdout.strip()


def private_directory(value):
    path = Path(value).resolve()
    if not path.is_relative_to((ROOT / 'work').resolve()) or path == (ROOT / 'work').resolve():
        raise ValueError('A dedicated project work/ directory is required')
    return path


def identity(config):
    database = config['database']
    if not re.fullmatch(r'doorhandle_wb_live_[a-f0-9]{10}', database):
        raise ValueError('Invalid isolated database identity')
    if config['username'] != 'wb_live_' + database.rsplit('_', 1)[-1]:
        raise ValueError('Invalid isolated user identity')
    return database, config['username']


def prepare(directory):
    directory.mkdir(parents=True, exist_ok=True)
    config_path = directory / 'connection.json'
    if config_path.exists():
        raise RuntimeError('Inspect or clean the existing experiment before preparing another')
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', PORT)) == 0:
            raise RuntimeError('Verification port already belongs to another process')
    address = remote(f"sudo -n docker inspect --format '{{{{range .NetworkSettings.Networks}}}}{{{{.IPAddress}}}}{{{{end}}}}' {CONTAINER}")
    ipaddress.IPv4Address(address)
    suffix = uuid.uuid4().hex[:10]
    config = {'database': 'doorhandle_wb_live_' + suffix, 'username': 'wb_live_' + suffix,
              'password': uuid.uuid4().hex + uuid.uuid4().hex, 'containerAddress': address, 'port': PORT}
    database, user = identity(config)
    config['url'] = f'jdbc:mysql://127.0.0.1:{PORT}/{database}?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai&connectTimeout=8000&socketTimeout=15000'
    # Persist cleanup identity before any remote mutation, including partial preparation.
    config_path.write_text(json.dumps(config), encoding='utf8')
    remote(MYSQL, f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4;\nCREATE USER '{user}'@'%' IDENTIFIED BY '{config['password']}';\nGRANT ALL ON `{database}`.* TO '{user}'@'%';\n")
    with (directory / 'tunnel.log').open('wb') as log:
        process = subprocess.Popen(SSH + ['-N', '-L', f'127.0.0.1:{PORT}:{address}:3306',
                                         '-o', 'ExitOnForwardFailure=yes', HOST],
                                   stdout=subprocess.DEVNULL, stderr=log,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    config['tunnelPid'] = process.pid
    config_path.write_text(json.dumps(config), encoding='utf8')
    for _ in range(40):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', PORT)) == 0:
                print(json.dumps({'database': database, 'port': PORT, 'ready': True}))
                return
        if process.poll() is not None:
            break
        time.sleep(.2)
    raise RuntimeError('Tunnel not ready; cleanup identity was retained')


def cleanup(directory):
    config_path = directory / 'connection.json'
    config = json.loads(config_path.read_text(encoding='utf8'))
    database, user = identity(config)
    address = str(ipaddress.IPv4Address(config['containerAddress']))
    if config['port'] != PORT:
        raise ValueError('Invalid verification tunnel port')
    remote(MYSQL, f"DROP DATABASE IF EXISTS `{database}`;\nDROP USER IF EXISTS '{user}'@'%';\n")
    if 'tunnelPid' in config:
        pid = int(config['tunnelPid'])
        script = f'''$taskProcess=Get-CimInstance Win32_Process -Filter "ProcessId={pid}"; if($taskProcess -and $taskProcess.Name -eq 'ssh.exe' -and $taskProcess.CommandLine -like '*127.0.0.1:{PORT}:{address}:3306*' -and $taskProcess.CommandLine -like '*doorhandle-bj*'){{Stop-Process -Id {pid}}}'''
        subprocess.run(['pwsh', '-NoProfile', '-Command', script], check=True, capture_output=True)
    receipt = {'database': database, 'cleaned': True}
    (directory / 'cleanup.json').write_text(json.dumps(receipt), encoding='utf8')
    config_path.unlink()
    print(json.dumps(receipt))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'cleanup'])
    parser.add_argument('--directory', required=True)
    args = parser.parse_args()
    (prepare if args.action == 'prepare' else cleanup)(private_directory(args.directory))
