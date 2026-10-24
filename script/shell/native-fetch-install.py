"""Linux receipts for the fixed Fetch installer. No user command, URL or package is accepted."""
import argparse
from contextlib import contextmanager
import ctypes
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import stat
import subprocess
import sys
import time
import uuid

BUDGET = 512 * 1024 * 1024
TERMINAL = {'SUCCEEDED', 'FAILED', 'CANCELLED', 'SEALED'}


def secure(path):
    for entry in (path, *path.parents):
        if entry.is_symlink() or entry.exists() and entry.resolve() != entry:
            raise ValueError('storage identity')


def node():
    if sys.platform != 'linux' or not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise ValueError('Linux pidfd required')
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip() + ':' + os.readlink('/proc/self/ns/pid')


def process(pid):
    try:
        fields = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
        return {'pid': pid, 'state': fields[0], 'parent': int(fields[1]), 'start': int(fields[19])}
    except (FileNotFoundError, ProcessLookupError):
        return None


def descendants(root):
    rows = {}
    for entry in Path('/proc').iterdir():
        if entry.name.isdigit():
            value = process(int(entry.name))
            if value is not None:
                rows[value['pid']] = value
    found = {root}
    while True:
        expanded = found | {pid for pid, value in rows.items() if value['parent'] in found}
        if found == expanded:
            return [rows[pid] for pid in found if pid != root and pid in rows]
        found = expanded


def signal_owned(value, sig):
    try:
        descriptor = os.pidfd_open(value['pid'])
        try:
            current = process(value['pid'])
            if current is not None and current['start'] == value['start']:
                # An orphan remains below this live subreaper. Never signal a recycled PID.
                chain, seen = current, set()
                while chain and chain['pid'] not in seen:
                    if chain['parent'] == os.getpid():
                        signal.pidfd_send_signal(descriptor, sig)
                        break
                    seen.add(chain['pid']); chain = process(chain['parent'])
        finally:
            os.close(descriptor)
    except ProcessLookupError:
        pass


def bytes_used(folder):
    total, count, pending = 0, 0, [folder]
    while pending:
        path = pending.pop(); secure(path)
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    value = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                count += 1
                if count > 100000 or not (stat.S_ISDIR(value.st_mode) or stat.S_ISREG(value.st_mode) or stat.S_ISLNK(value.st_mode)):
                    raise ValueError('unverified install storage')
                if stat.S_ISDIR(value.st_mode):
                    pending.append(Path(entry.path))
                else:
                    total += value.st_size
                    if total > BUDGET:
                        return total
    return total


class Records:
    def __init__(self, directory):
        self.directory = Path(directory).absolute(); secure(self.directory)
        parts = self.directory.parts
        if len(parts) < 6 or parts[-6] != 'users' or parts[-4:-1] != ('mcp', 'fetch', 'installs'):
            raise ValueError('installation identity')
        self.owner, self.installation = int(parts[-5]), parts[-1]
        if self.owner < 1 or str(self.owner) != parts[-5] or str(uuid.UUID(self.installation)) != self.installation:
            raise ValueError('installation identity')
        runtime = self.directory.parent.parent / 'runtime'; secure(runtime)
        runtime.mkdir(mode=0o700, parents=True, exist_ok=True); secure(runtime)
        metadata = runtime.stat()
        if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
            raise ValueError('private runtime required')
        self.path = runtime / 'installers.sqlite3'; secure(self.path)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(descriptor)
        except FileExistsError:
            pass
        metadata = self.path.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
            raise ValueError('private journal required')
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS installer(installation TEXT PRIMARY KEY,owner INTEGER NOT NULL,node TEXT NOT NULL,pid INTEGER,start_ticks INTEGER,revoked INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL,exit_code INTEGER,stopped INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS event(id INTEGER PRIMARY KEY AUTOINCREMENT,installation TEXT NOT NULL,action TEXT NOT NULL,state TEXT NOT NULL,created_at INTEGER NOT NULL)')
            db.execute('INSERT OR IGNORE INTO metadata VALUES(?,?)', ('pool', uuid.uuid4().hex))
            self.pool = db.execute("SELECT value FROM metadata WHERE key='pool'").fetchone()[0]
        if not re.fullmatch('[a-f0-9]{32}', self.pool):
            raise ValueError('pool identity')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=5); db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL'); db.execute('BEGIN IMMEDIATE'); yield db; db.commit()
        except BaseException:
            db.rollback(); raise
        finally:
            db.close()

    def row(self, db):
        value = db.execute('SELECT * FROM installer WHERE installation=? AND owner=?', (self.installation, self.owner)).fetchone()
        if value is None:
            raise ValueError('installer reservation missing')
        return value

    def event(self, db, action, state):
        db.execute('INSERT INTO event(installation,action,state,created_at) VALUES(?,?,?,?)', (self.installation, action, state, int(time.time())))

    def reserve(self):
        with self.transaction() as db:
            existing = db.execute('SELECT 1 FROM installer WHERE installation=?', (self.installation,)).fetchone()
            if existing is None and (self.path.stat().st_size > 8 * 1024 * 1024 or db.execute('SELECT COUNT(*) FROM installer').fetchone()[0] >= 10000):
                raise ValueError('installer journal capacity')
            db.execute("INSERT OR IGNORE INTO installer(installation,owner,node,state,created_at) VALUES(?,?,?,'RESERVED',?)", (self.installation, self.owner, node(), int(time.time())))
            self.row(db)
        return self.status()

    def status(self):
        with self.transaction() as db:
            row = self.row(db)
            verified = bool(row['stopped']) and row['state'] in TERMINAL
            return {'poolId': self.pool, 'owner': self.owner, 'installation': self.installation, 'state': row['state'], 'writerStopped': verified, 'exitCode': row['exit_code']}

    def stop(self):
        with self.transaction() as db:
            row = self.row(db)
            if not row['stopped'] and not row['revoked']:
                state = 'SEALED' if row['pid'] is None else 'STOPPING'
                db.execute('UPDATE installer SET revoked=1,state=?,stopped=? WHERE installation=?', (state, int(row['pid'] is None), self.installation))
                self.event(db, 'STOP_REQUEST', state)
        return self.status()

    def run(self):
        os.setsid()
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, ctypes.c_ulong(1), 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            raise ValueError('subreaper unavailable')
        identity = process(os.getpid())
        with self.transaction() as db:
            row = self.row(db)
            if row['pid'] is not None or row['revoked'] or row['state'] != 'RESERVED' or row['node'] != node():
                raise ValueError('installer cannot replay')
            db.execute("UPDATE installer SET pid=?,start_ticks=?,state='RUNNING' WHERE installation=?", (os.getpid(), identity['start'], self.installation)); self.event(db, 'START', 'RUNNING')
        cancelled = [False]
        def requested(_signal, _frame):
            cancelled[0] = True
        signal.signal(signal.SIGTERM, requested); signal.signal(signal.SIGINT, requested)
        child, code, started, checked = None, 125, time.monotonic(), 0.0
        try:
            installer = Path(__file__).absolute().with_name('install-local-fetch-mcp.py'); secure(installer)
            if not installer.is_file() or installer.stat().st_size > 65536 or not self.directory.is_dir():
                raise ValueError('fixed installer unavailable')
            with self.transaction() as db:
                if self.row(db)['revoked']:
                    cancelled[0] = True
            if not cancelled[0]:
                child = subprocess.Popen([sys.executable, '-I', '-B', str(installer), '--directory', str(self.directory)], cwd=self.directory,
                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
                code = None
        except Exception:
            cancelled[0] = True
        while True:
            try:
                with self.transaction() as db:
                    cancelled[0] = cancelled[0] or bool(self.row(db)['revoked'])
                if time.monotonic() - started >= 600:
                    cancelled[0] = True
                if not cancelled[0] and time.monotonic() - checked >= 1:
                    checked = time.monotonic()
                    if bytes_used(self.directory) > BUDGET:
                        cancelled[0] = True
                children = descendants(os.getpid())
                if code is not None and any(value['state'] != 'Z' for value in children):
                    cancelled[0] = True
                if cancelled[0] or code is not None:
                    for value in children:
                        if value['state'] != 'Z':
                            signal_owned(value, signal.SIGSTOP); signal_owned(value, signal.SIGKILL)
                no_children = False
                while True:
                    try:
                        pid, status = os.waitpid(-1, os.WNOHANG)
                    except ChildProcessError:
                        no_children = True; break
                    if pid == 0:
                        break
                    if child is not None and pid == child.pid:
                        code = os.waitstatus_to_exitcode(status); child.returncode = code
                if no_children and not descendants(os.getpid()):
                    state = 'CANCELLED' if cancelled[0] else 'SUCCEEDED' if code == 0 else 'FAILED'
                    with self.transaction() as db:
                        if self.row(db)['revoked']:
                            state = 'CANCELLED'
                        if not self.row(db)['stopped']:
                            db.execute('UPDATE installer SET state=?,exit_code=?,stopped=1 WHERE installation=?', (state, code, self.installation)); self.event(db, 'TREE_STOPPED', state)
                    return self.status()
            except Exception:
                # Keep this supervisor alive so orphaned children retain an identifiable parent.
                # A failed observation is never persisted as affirmative exit evidence.
                cancelled[0] = True
            time.sleep(.2 if time.monotonic() - started < 610 else 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('reserve', 'run', 'status', 'stop'))
    parser.add_argument('--directory', required=True); parser.add_argument('--pool')
    args = parser.parse_args(); node(); records = Records(args.directory)
    if args.action not in ('reserve', 'status') and args.pool != records.pool or args.pool is not None and args.pool != records.pool:
        raise ValueError('pool changed')
    result = getattr(records, args.action)()
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        # No pip output, package index, environment, local path or traceback is returned.
        raise SystemExit(2)
