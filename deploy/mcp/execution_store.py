"""Private execution metadata and exit evidence. No URLs, tool text or bearer credentials are stored."""
from contextlib import contextmanager
from pathlib import Path
import os
import re
import sqlite3
import time
import uuid


class CapacityExceeded(RuntimeError):
    pass


class ExecutionStore:
    def __init__(self, path):
        if not path:
            raise ValueError('A persistent MCP execution database is required')
        self.path = Path(path).absolute()
        for entry in (self.path, *self.path.parents):
            if entry.is_symlink():
                raise ValueError('Execution database path redirects are forbidden')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(descriptor)
            except FileExistsError:
                # Another runner may initialize the same persistent volume concurrently.
                if self.path.is_symlink() or not self.path.is_file():
                    raise ValueError('Invalid execution database')
        with self.transaction() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS execution(
                  name TEXT PRIMARY KEY,owner INTEGER NOT NULL,installation TEXT NOT NULL,nonce TEXT NOT NULL,
                  image TEXT NOT NULL,status TEXT NOT NULL,launch_settled INTEGER NOT NULL DEFAULT 0,
                  controller_id TEXT,controller_started TEXT,worker_id TEXT NOT NULL,
                  revision INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,reason TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS execution_owner ON execution(owner,installation,nonce);
                CREATE TABLE IF NOT EXISTS revocation(owner INTEGER NOT NULL,installation TEXT NOT NULL,nonce TEXT NOT NULL,
                  expires_at INTEGER NOT NULL,PRIMARY KEY(owner,installation,nonce));
                CREATE TABLE IF NOT EXISTS execution_event(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,
                  owner INTEGER NOT NULL,action TEXT NOT NULL,status TEXT NOT NULL,created_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS image_retirement(image TEXT PRIMARY KEY,request TEXT NOT NULL,owner INTEGER NOT NULL,
                  state TEXT NOT NULL,archive_sha256 TEXT,image_absent INTEGER NOT NULL DEFAULT 0,updated_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS image_retirement_event(id INTEGER PRIMARY KEY AUTOINCREMENT,image TEXT NOT NULL,
                  request TEXT NOT NULL,state TEXT NOT NULL,created_at INTEGER NOT NULL);
            ''')
            connection.execute('INSERT OR IGNORE INTO metadata VALUES(?,?)', ('pool_id', uuid.uuid4().hex))
            self.pool_id = connection.execute("SELECT value FROM metadata WHERE key='pool_id'").fetchone()[0]
        if not re.fullmatch(r'[a-f0-9]{32}', self.pool_id):
            raise ValueError('Invalid executor pool identity')

    @contextmanager
    def transaction(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA busy_timeout=5000')
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('BEGIN IMMEDIATE')
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def subject(identity):
        owner, installation = identity['owner'], identity['installation']
        nonce = identity.get('execution_nonce', identity['nonce'])
        if type(owner) is not int or owner < 1 or any(str(uuid.UUID(v)) != v for v in (installation, nonce)):
            raise ValueError('Execution identity')
        return owner, installation, nonce

    def revoked(self, identity):
        with self.transaction() as connection:
            row = connection.execute('SELECT expires_at FROM revocation WHERE owner=? AND installation=? AND nonce=?', self.subject(identity)).fetchone()
            return row is not None

    def revoke(self, identity):
        subject = self.subject(identity)
        with self.transaction() as connection:
            connection.execute('INSERT INTO revocation VALUES(?,?,?,?) ON CONFLICT(owner,installation,nonce) DO UPDATE SET expires_at=MAX(expires_at,excluded.expires_at)', (*subject, max(int(time.time()) + 600, identity['exp'])))

    def reserve(self, identity, name, image, worker, controller=None):
        owner, installation, nonce = self.subject(identity)
        if not re.fullmatch('dh-mcp-' + uuid.UUID(nonce).hex + '-[a-f0-9]{32}', name) or not re.fullmatch(r'sha256:[a-f0-9]{64}', image):
            raise ValueError('Execution resource')
        now = int(time.time()); controller = controller or {}
        with self.transaction() as connection:
            revoked = connection.execute('SELECT expires_at FROM revocation WHERE owner=? AND installation=? AND nonce=?', (owner, installation, nonce)).fetchone()
            if revoked is not None:
                raise CapacityExceeded('Execution revoked')
            if connection.execute('SELECT 1 FROM image_retirement WHERE image=?', (image,)).fetchone() is not None:
                raise CapacityExceeded('Image retirement is fenced')
            if connection.execute("SELECT COUNT(*) FROM execution WHERE status<>'REMOVED'").fetchone()[0] >= 2:
                raise CapacityExceeded('Unreleased execution capacity')
            if connection.execute('SELECT COUNT(*) FROM execution').fetchone()[0] >= 100000:
                raise CapacityExceeded('Execution history requires archival')
            connection.execute('INSERT INTO execution(name,owner,installation,nonce,image,status,controller_id,controller_started,worker_id,created_at,expires_at,reason) VALUES(?,?,?,?,?,\'RESERVED\',?,?,?,?,?,\'BEFORE_LAUNCH\')',
                               (name, owner, installation, nonce, image, controller.get('id'), controller.get('started'), worker, now, now+45))
            self.event(connection, name, 'EXECUTION_RESERVED')

    def get(self, name):
        with self.transaction() as connection:
            row = connection.execute('SELECT * FROM execution WHERE name=?', (name,)).fetchone()
            if row is None:
                raise ValueError('Unregistered execution')
            return dict(row)

    def launch_done(self, name):
        with self.transaction() as connection:
            connection.execute('UPDATE execution SET launch_settled=1,revision=revision+1 WHERE name=?', (name,))
            self.event(connection, name, 'LAUNCH_SETTLED')

    def result(self, name, state, reason):
        if state not in ('NEEDS_REVIEW', 'EXITED', 'REMOVED') or not re.fullmatch(r'[A-Z_]{1,64}', reason):
            raise ValueError('Exit evidence')
        with self.transaction() as connection:
            row = connection.execute('SELECT status,launch_settled FROM execution WHERE name=?', (name,)).fetchone()
            if row is None:
                raise ValueError('Unregistered execution')
            if row['status'] == 'REMOVED':
                return
            if state in ('EXITED', 'REMOVED') and not row['launch_settled']:
                state, reason = 'NEEDS_REVIEW', 'LAUNCH_STILL_UNSETTLED'
            connection.execute('UPDATE execution SET status=?,reason=?,revision=revision+1 WHERE name=?', (state, reason, name))
            self.event(connection, name, 'EXIT_OBSERVED')

    def rows(self, identity=None):
        with self.transaction() as connection:
            if identity is None:
                rows = connection.execute("SELECT * FROM execution WHERE status<>'REMOVED' ORDER BY created_at LIMIT 50").fetchall()
            else:
                rows = connection.execute('SELECT * FROM execution WHERE owner=? AND installation=? AND nonce=? ORDER BY created_at DESC LIMIT 50', self.subject(identity)).fetchall()
            return [dict(row) for row in rows]

    def receipt(self, identity):
        owner, installation, nonce = self.subject(identity)
        with self.transaction() as connection:
            revoked = connection.execute('SELECT 1 FROM revocation WHERE owner=? AND installation=? AND nonce=?', (owner, installation, nonce)).fetchone() is not None
            rows = connection.execute("SELECT * FROM execution WHERE owner=? AND installation=? AND nonce=? ORDER BY CASE WHEN status='REMOVED' THEN 1 ELSE 0 END,created_at DESC LIMIT 50", (owner, installation, nonce)).fetchall()
            pending = connection.execute("SELECT COUNT(*) FROM execution WHERE owner=? AND installation=? AND nonce=? AND status NOT IN ('EXITED','REMOVED')", (owner, installation, nonce)).fetchone()[0]
            unremoved = connection.execute("SELECT COUNT(*) FROM execution WHERE owner=? AND installation=? AND nonce=? AND status<>'REMOVED'", (owner, installation, nonce)).fetchone()[0]
        return {'owner': owner, 'installation': installation, 'nonce': nonce, 'poolId': self.pool_id,
                'exitVerified': revoked and pending == 0,
                'cleanupConfirmed': revoked and unremoved == 0,
                'executions': [{'id': row['name'], 'state': row['status'], 'revision': row['revision'], 'reason': row['reason']} for row in rows]}

    @staticmethod
    def event(connection, name, action):
        connection.execute('INSERT INTO execution_event(name,owner,action,status,created_at) SELECT name,owner,?,status,? FROM execution WHERE name=?', (action, int(time.time()), name))
