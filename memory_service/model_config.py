"""Encrypted, durable LLM configuration; never touches embeddings or vector indexes."""
import base64
import hashlib
import json
import re
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    from .write_receipts import ReceiptError, now
except ImportError:
    from write_receipts import ReceiptError, now


class GuardedLlm:
    def __init__(self, delegate, store, fingerprint, revision=0):
        self.delegate, self.store, self.fingerprint, self.revision = delegate, store, fingerprint, revision

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def generate_response(self, *args, **kwargs):
        self.store.assert_runtime(self.revision, self.fingerprint)
        return self.delegate.generate_response(*args, **kwargs)


class LlmConfigurationStore:
    def __init__(self, directory, key_file, allowed_urls, memory, write_lock, factory):
        directory, key_file = Path(directory), Path(key_file)
        if key_file.is_symlink() or not key_file.is_file() or key_file.stat().st_size > 128:
            raise ValueError("Model configuration Secret file is unavailable")
        self.key = base64.b64decode(key_file.read_text().strip(), validate=True)
        if len(self.key) != 32:
            raise ValueError("Model configuration Secret must contain 256 bits")
        if any(parent.is_symlink() for parent in (directory, *directory.parents)):
            raise ValueError("Model configuration directory cannot contain links")
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "llm_configuration.db"
        if self.path.is_symlink():
            raise ValueError("Model configuration database cannot be a link")
        self.urls, self.memory, self.write_lock, self.factory = dict(allowed_urls), memory, write_lock, factory
        self.mutex = threading.RLock()
        with closing(self.connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS llm_configuration (
                    revision INTEGER PRIMARY KEY, envelope TEXT NOT NULL, digest TEXT NOT NULL,
                    created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS llm_control (
                    id INTEGER PRIMARY KEY CHECK(id=1), active_revision INTEGER NOT NULL);
                INSERT OR IGNORE INTO llm_control VALUES(1,0);
                CREATE TABLE IF NOT EXISTS llm_revoked_key (
                    fingerprint TEXT PRIMARY KEY, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS llm_config_event (
                    revision INTEGER NOT NULL, action TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(revision,action));
            """)
        self.path.chmod(0o600)
        # A mismatched external key must fail startup before an active configuration or a later rollback is used.
        with closing(self.connect()) as db:
            cursor = db.execute("SELECT revision,envelope FROM llm_configuration ORDER BY revision")
            while True:
                rows = cursor.fetchmany(100)
                if not rows:
                    break
                for row in rows:
                    self.decode(row["revision"], row["envelope"])

    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        return db

    @staticmethod
    def fingerprint(key):
        return hashlib.sha256(key.encode()).hexdigest()

    def decode(self, revision, envelope):
        try:
            version, nonce, ciphertext = envelope.split(".")
            nonce = base64.b64decode(nonce, validate=True)
            if version != "v1" or len(nonce) != 12 or revision < 1:
                raise ValueError()
            aad = f"doorhandle:mem0-llm:{revision}".encode()
            raw = AESGCM(self.key).decrypt(nonce, base64.b64decode(ciphertext, validate=True), aad)
            data = json.loads(raw)
            if set(data) != {"provider", "model", "api_key", "base_url"}:
                raise ValueError()
            if data["provider"] not in self.urls or data["base_url"] != self.urls[data["provider"]]:
                raise ValueError()
            if not isinstance(data["model"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/\-]{0,127}", data["model"]):
                raise ValueError()
            if not isinstance(data["api_key"], str) or not 1 <= len(data["api_key"]) <= 4096 or any(ord(c) < 32 or ord(c) == 127 for c in data["api_key"]):
                raise ValueError()
            return data
        except Exception:
            raise ReceiptError(400, "Encrypted model configuration is invalid") from None

    def assert_credential(self, fingerprint):
        try:
            with closing(self.connect()) as db:
                if db.execute("SELECT 1 FROM llm_revoked_key WHERE fingerprint=?", (fingerprint,)).fetchone():
                    raise ReceiptError(503, "Memory extraction credential was revoked; operation not started", not_started=True)
        except sqlite3.Error:
            raise ReceiptError(503, "Memory model configuration needs verification; operation not started", not_started=True) from None

    def assert_runtime(self, revision, fingerprint):
        self.assert_credential(fingerprint)
        if self.applied_revision() != revision:
            raise ReceiptError(503, "Memory model runtime needs verification; operation not started", not_started=True)

    def prepare(self, revision, envelope):
        data = self.decode(revision, envelope)
        self.assert_credential(self.fingerprint(data["api_key"]))
        digest = hashlib.sha256(envelope.encode()).hexdigest()
        with self.mutex, closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT digest FROM llm_configuration WHERE revision=?", (revision,)).fetchone()
            if row:
                if row["digest"] != digest:
                    raise ReceiptError(409, "Model configuration revision is immutable")
                return
            db.execute("INSERT INTO llm_configuration VALUES(?,?,?,?)", (revision, envelope, digest, now()))
            db.execute("INSERT INTO llm_config_event VALUES(?,'PREPARED',?)", (revision, now()))

    def applied_revision(self):
        with closing(self.connect()) as db:
            return db.execute("SELECT active_revision FROM llm_control WHERE id=1").fetchone()[0]

    def _candidate(self, db, revision, check_credential=True):
        row = db.execute("SELECT envelope FROM llm_configuration WHERE revision=?", (revision,)).fetchone()
        if row is None:
            raise ReceiptError(409, "Model configuration is not prepared")
        data = self.decode(revision, row["envelope"])
        fingerprint = self.fingerprint(data["api_key"])
        if check_credential:
            self.assert_credential(fingerprint)
        # LlmFactory constructs a client only; no extraction or provider probe here.
        return GuardedLlm(self.factory(data), self, fingerprint, revision)

    def apply(self, revision):
        if not self.write_lock.acquire(blocking=False):
            raise ReceiptError(503, "Memory extraction is using the previous model; apply later", not_started=True)
        try:
            with self.mutex, closing(self.connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                active = db.execute("SELECT active_revision FROM llm_control WHERE id=1").fetchone()[0]
                if revision < active:
                    raise ReceiptError(409, "Cannot apply an older model revision")
                if revision == active:
                    return
                candidate = self._candidate(db, revision)
                db.execute("UPDATE llm_control SET active_revision=? WHERE id=1", (revision,))
                db.execute("INSERT INTO llm_config_event VALUES(?,'APPLIED',?)", (revision, now()))
                # Commit before swapping. On a crash in between, startup restores this revision.
                db.commit()
                self.memory().llm = candidate
        finally:
            self.write_lock.release()

    def restore(self):
        """Startup under the existing process fence, before accepting requests."""
        with self.mutex, closing(self.connect()) as db:
            revision = self.applied_revision()
            if revision:
                self.memory().llm = self._candidate(db, revision, check_credential=False)

    def guard_environment(self, api_key):
        self.memory().llm = GuardedLlm(self.memory().llm, self, self.fingerprint(api_key))

    def revoke(self, fingerprint):
        if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            raise ReceiptError(400, "Credential fingerprint is invalid")
        # Existing extraction may finish with its original client. Every subsequent LLM call checks this table.
        with self.mutex, closing(self.connect()) as db, db:
            db.execute("INSERT OR IGNORE INTO llm_revoked_key VALUES(?,?)", (fingerprint, now()))
