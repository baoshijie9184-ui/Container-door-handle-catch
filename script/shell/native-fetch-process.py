"""Linux-only lifecycle controller for the reviewed Fetch package. No arbitrary commands or tool bodies."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import runpy
import signal
import sqlite3
import sys
import time
import uuid


def canonical_uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('identity')
    return value


def secure(path):
    for entry in (path, *path.parents):
        if entry.is_symlink() or entry.exists() and entry.resolve() != entry:
            raise ValueError('storage identity')


def node_identity():
    if sys.platform != 'linux' or not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise ValueError('native process receipts require Linux pidfd support')
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip() + ':' + os.readlink('/proc/self/ns/pid')


class Records:
    def __init__(self, directory):
        self.directory = Path(directory).absolute()
        secure(self.directory)
        parts = self.directory.parts
        if len(parts) < 6 or parts[-6] != 'users' or parts[-4:-1] != ('mcp', 'fetch', 'installs') or not parts[-5].isdigit() or int(parts[-5]) < 1:
            raise ValueError('installation identity')
        self.owner, self.installation = int(parts[-5]), canonical_uuid(parts[-1])
        folder = self.directory.parent.parent / 'runtime'
        secure(folder); folder.mkdir(mode=0o700, parents=True, exist_ok=True); secure(folder)
        self.path = folder / 'processes.sqlite3'; secure(self.path)
        try:
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600); os.close(descriptor)
        except FileExistsError:
            secure(self.path)
        with self.transaction() as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            connection.execute('CREATE TABLE IF NOT EXISTS execution(nonce TEXT PRIMARY KEY,installation TEXT NOT NULL,owner INTEGER NOT NULL,node TEXT NOT NULL,pid INTEGER,start_ticks INTEGER,revoked INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL,created_at INTEGER NOT NULL)')
            connection.execute('CREATE TABLE IF NOT EXISTS event(id INTEGER PRIMARY KEY AUTOINCREMENT,nonce TEXT NOT NULL,action TEXT NOT NULL,state TEXT NOT NULL,created_at INTEGER NOT NULL)')
            connection.execute('INSERT OR IGNORE INTO metadata VALUES(?,?)', ('pool', uuid.uuid4().hex))
            self.pool = connection.execute("SELECT value FROM metadata WHERE key='pool'").fetchone()[0]
        if not re.fullmatch('[a-f0-9]{32}', self.pool):
            raise ValueError('pool identity')

    @contextmanager
    def transaction(self):
        connection = sqlite3.connect(self.path, timeout=5); connection.row_factory = sqlite3.Row
        try:
            connection.execute('BEGIN IMMEDIATE'); yield connection; connection.commit()
        except BaseException:
            connection.rollback(); raise
        finally:
            connection.close()

    def get(self, connection, nonce):
        row = connection.execute('SELECT * FROM execution WHERE nonce=? AND owner=? AND installation=?', (nonce, self.owner, self.installation)).fetchone()
        if row is None:
            raise ValueError('execution unavailable')
        return dict(row)

    @staticmethod
    def event(connection, nonce, action, state):
        connection.execute('INSERT INTO event(nonce,action,state,created_at) VALUES(?,?,?,?)', (nonce, action, state, int(time.time())))

    def reserve(self, nonce):
        with self.transaction() as connection:
            if connection.execute("SELECT COUNT(*) FROM execution WHERE state<>'REMOVED'").fetchone()[0] >= 2:
                raise ValueError('unreleased execution capacity')
            if connection.execute('SELECT COUNT(*) FROM execution').fetchone()[0] >= 100000:
                raise ValueError('history archival required')
            connection.execute("INSERT INTO execution(nonce,installation,owner,node,state,created_at) VALUES(?,?,?,?,'RESERVED',?)", (nonce, self.installation, self.owner, node_identity(), int(time.time())))
            self.event(connection, nonce, 'RESERVE', 'RESERVED')

    def run(self, nonce):
        # A dedicated session prevents joining the Java application's process group.
        os.setsid(); identity = process(os.getpid())
        with self.transaction() as connection:
            row = self.get(connection, nonce)
            if row['pid'] is not None or row['node'] != node_identity() or row['state'] == 'REMOVED':
                raise ValueError('execution cannot be replayed')
            connection.execute("UPDATE execution SET pid=?,start_ticks=?,state='STARTED' WHERE nonce=?", (os.getpid(), identity['start'], nonce))
            self.event(connection, nonce, 'LAUNCH', 'STARTED')
            revoked = bool(row['revoked'])
        if revoked:
            return
        # Fixed module only. SDK stdio and JSON-RPC messages remain untouched.
        sys.argv = ['mcp-server-fetch']; sys.dont_write_bytecode = True
        with open(os.devnull, 'wb') as sink:
            os.dup2(sink.fileno(), 2)
        runpy.run_module('mcp_server_fetch', run_name='__main__')

    def abandon(self, nonce):
        # Only the Java pre-launch failure branch uses this command. No SDK connection exists yet.
        with self.transaction() as connection:
            connection.execute("INSERT OR IGNORE INTO execution(nonce,installation,owner,node,state,created_at) VALUES(?,?,?,?,'RESERVED',?)", (nonce, self.installation, self.owner, node_identity(), int(time.time())))
            row = self.get(connection, nonce)
            if row['pid'] is not None:
                raise ValueError('execution already launched')
            connection.execute("UPDATE execution SET revoked=1,state='REMOVED' WHERE nonce=?", (nonce,)); self.event(connection, nonce, 'ABANDON_BEFORE_SDK', 'REMOVED')

    def stop(self, nonce):
        with self.transaction() as connection:
            row = self.get(connection, nonce)
            connection.execute('UPDATE execution SET revoked=1 WHERE nonce=?', (nonce,))
            self.event(connection, nonce, 'STOP_REQUEST', row['state'])
        exited, cleaned = False, False
        if row['node'] == node_identity() and row['pid'] is not None:
            root = process(row['pid']); members = group(row['pid'])
            if root is not None and root['start'] == row['start_ticks'] and root['state'] != 'Z':
                descriptor = os.pidfd_open(row['pid'])
                try:
                    # Recheck after obtaining the stable process handle. Never signal a recycled PID.
                    checked = process(row['pid'])
                    if checked is None or checked['start'] != row['start_ticks']:
                        raise ValueError('process generation changed')
                    signal.pidfd_send_signal(descriptor, signal.SIGSTOP)
                    deadline = time.monotonic() + 1
                    while time.monotonic() < deadline:
                        checked = process(row['pid'])
                        if checked is None:
                            break
                        if checked['start'] != row['start_ticks']:
                            raise ValueError('process generation changed')
                        if checked['state'] in ('T', 't'):
                            # The frozen session leader pins the group identity while terminating it.
                            os.killpg(row['pid'], signal.SIGSTOP)
                            os.killpg(row['pid'], signal.SIGKILL)
                            break
                        time.sleep(.02)
                finally:
                    # A failed group observation must not leave the session leader frozen
                    # while the SDK waits for its exit. The pidfd addresses only this generation.
                    try:
                        signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    os.close(descriptor)
            deadline = time.monotonic() + 2
            while True:
                members = group(row['pid'])
                if not members or time.monotonic() >= deadline:
                    break
                time.sleep(.03)
            exited = not any(value['state'] != 'Z' for value in members)
            cleaned = not members
        state = 'REMOVED' if cleaned else 'EXITED' if exited else 'NEEDS_REVIEW'
        with self.transaction() as connection:
            # Observed exit is monotonic; a temporary process-query error is never affirmative evidence.
            latest = self.get(connection, nonce)
            if latest['state'] == 'REMOVED':
                exited, cleaned, state = True, True, 'REMOVED'
            elif latest['state'] == 'EXITED' and not cleaned:
                exited, state = True, 'EXITED'
            connection.execute('UPDATE execution SET state=? WHERE nonce=?', (state, nonce)); self.event(connection, nonce, 'EXIT_OBSERVED', state)
        return {'poolId': self.pool, 'owner': self.owner, 'installation': self.installation, 'executionNonce': nonce, 'state': state, 'exitVerified': exited, 'cleanupConfirmed': cleaned, 'transport': 'STDIO'}


def process(pid):
    try:
        value = Path('/proc') / str(pid) / 'stat'
        fields = value.read_text().rsplit(')', 1)[1].split()
        return {'pid': pid, 'state': fields[0], 'group': int(fields[2]), 'session': int(fields[3]), 'start': int(fields[19])}
    except FileNotFoundError:
        return None


def group(leader):
    result = []
    for entry in Path('/proc').iterdir():
        if entry.name.isdigit():
            value = process(int(entry.name))
            if value is not None and value['group'] == leader and value['session'] == leader:
                result.append(value)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['pool', 'reserve', 'run', 'stop', 'abandon'])
    parser.add_argument('--directory', required=True); parser.add_argument('--execution'); parser.add_argument('--pool')
    args = parser.parse_args(); node_identity(); records = Records(args.directory)
    if args.action == 'pool':
        print(json.dumps({'poolId': records.pool})); return
    nonce = canonical_uuid(args.execution)
    if args.pool != records.pool:
        raise ValueError('pool changed')
    if args.action == 'reserve':
        records.reserve(nonce); print(json.dumps({'reserved': True, 'poolId': records.pool, 'executionNonce': nonce}))
    elif args.action == 'run':
        records.run(nonce)
    elif args.action == 'abandon':
        records.abandon(nonce); print(json.dumps({'abandoned': True}))
    else:
        print(json.dumps(records.stop(nonce)))


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        # No protocol frame, tool body, environment, server path or traceback is printed.
        raise SystemExit(2)
