"""Owned memory lifecycle controls and expiry receipts, sharing the fenced bridge journal."""
import hmac
import logging
import time
from contextlib import closing
from datetime import datetime

try:
    from .write_receipts import CST, ErrorSignal, ReceiptError, now
except ImportError:
    from write_receipts import CST, ErrorSignal, ReceiptError, now


def memory_digest(item):
    import hashlib
    import json
    version = {key: item.get(key) for key in ("id", "memory", "user_id", "agent_id", "run_id", "updated_at")}
    return hashlib.sha256(json.dumps(version, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


class LifecycleStore:
    def __init__(self, receipts):
        self.receipts = receipts
        with closing(receipts.connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS memory_lifecycle (
                user_id TEXT NOT NULL, app_id TEXT NOT NULL, memory_id TEXT NOT NULL,
                revision INTEGER NOT NULL, state TEXT NOT NULL, expires_at TEXT,
                auto_delete INTEGER NOT NULL, expected_digest TEXT NOT NULL,
                cleanup_state TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(user_id,app_id,memory_id))""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_memory_expiry ON memory_lifecycle(cleanup_state,auto_delete,expires_at)")
            db.execute("UPDATE bridge_protocol_floor SET required_version=MAX(required_version,2) WHERE EXISTS(SELECT 1 FROM memory_lifecycle)")
            db.execute("""CREATE TABLE IF NOT EXISTS memory_cleanup_event (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, app_id TEXT NOT NULL,
                memory_id TEXT NOT NULL, revision INTEGER NOT NULL, outcome TEXT NOT NULL, created_at TEXT NOT NULL)""")
            # Initialization occurs only after the writer's operating-system fence has been acquired.
            rows = db.execute("SELECT * FROM memory_lifecycle WHERE cleanup_state='RUNNING'").fetchall()
            for row in rows:
                self._event(db, row, "NEEDS_REVIEW")
            db.execute("UPDATE memory_lifecycle SET cleanup_state='NEEDS_REVIEW',updated_at=? WHERE cleanup_state='RUNNING'", (now(),))

    def get(self, user, app, memory_id):
        with closing(self.receipts.connect()) as db:
            row = db.execute("SELECT * FROM memory_lifecycle WHERE user_id=? AND app_id=? AND memory_id=?", (user, app, memory_id)).fetchone()
            return dict(row) if row else None

    def public(self, user, app, memory_id):
        row = self.get(user, app, memory_id)
        return {"memoryId": memory_id, "revision": row["revision"] if row else 0,
                "state": row["state"] if row else "ACTIVE", "expiresAt": row["expires_at"] if row else None,
                "autoDelete": bool(row["auto_delete"]) if row else False,
                "cleanupState": row["cleanup_state"] if row else "NONE", "updatedAt": row["updated_at"] if row else None}

    def allowed(self, user, app, memory_id):
        row = self.get(user, app, memory_id)
        return not row or (row["state"] == "ACTIVE" and (not row["expires_at"] or row["expires_at"] > now())
                           and row["cleanup_state"] not in {"RUNNING", "SUCCEEDED", "NEEDS_REVIEW"})

    def change(self, user, app, memory_id, revision, digest, state, expires_at, auto_delete):
        with closing(self.receipts.connect()) as db, db:
            db.execute("INSERT OR IGNORE INTO memory_lifecycle VALUES(?,?,?,0,'ACTIVE',NULL,0,?,'NONE',?)", (user, app, memory_id, digest, now()))
            changed = db.execute("""UPDATE memory_lifecycle SET revision=revision+1,state=?,expires_at=?,auto_delete=?,
                expected_digest=?,cleanup_state=?,updated_at=? WHERE user_id=? AND app_id=? AND memory_id=? AND revision=?""",
                (state, expires_at, int(auto_delete), digest, "READY" if auto_delete else "NONE", now(), user, app, memory_id, revision))
            if changed.rowcount != 1:
                raise ReceiptError(409, "Memory lifecycle changed; refresh before changing")
            row = db.execute("SELECT * FROM memory_lifecycle WHERE user_id=? AND app_id=? AND memory_id=?", (user, app, memory_id)).fetchone()
            self._event(db, row, "POLICY_CHANGED")
            db.execute("UPDATE bridge_protocol_floor SET required_version=MAX(required_version,2)")
        return self.public(user, app, memory_id)

    @staticmethod
    def _event(db, row, outcome):
        db.execute("INSERT INTO memory_cleanup_event(user_id,app_id,memory_id,revision,outcome,created_at) VALUES(?,?,?,?,?,?)",
                   (row["user_id"], row["app_id"], row["memory_id"], row["revision"], outcome, now()))

    def history(self, user, app):
        with closing(self.receipts.connect()) as db:
            ids = db.execute("SELECT memory_id FROM memory_lifecycle WHERE user_id=? AND app_id=? ORDER BY updated_at DESC,memory_id LIMIT 50", (user, app)).fetchall()
        return [self.public(user, app, row[0]) for row in ids]

    def due(self):
        with closing(self.receipts.connect()) as db:
            return [dict(row) for row in db.execute("SELECT * FROM memory_lifecycle WHERE cleanup_state='READY' AND auto_delete=1 AND expires_at<=? ORDER BY expires_at LIMIT 5", (now(),))]

    def transition(self, row, source, target):
        with closing(self.receipts.connect()) as db, db:
            result = db.execute("UPDATE memory_lifecycle SET cleanup_state=?,updated_at=? WHERE user_id=? AND app_id=? AND memory_id=? AND revision=? AND cleanup_state=?",
                                (target, now(), row["user_id"], row["app_id"], row["memory_id"], row["revision"], source))
            if result.rowcount != 1:
                raise ReceiptError(409, "Memory cleanup receipt changed")
            self._event(db, row, target)

    def sweep(self, memory):
        """Caller holds the sole mutation slot. Never replay interrupted or unknown deletions."""
        started = time.monotonic()
        for row in self.due():
            if time.monotonic() - started > 2:
                break  # A soft batch bound; does not pretend to cancel a native SDK operation.
            self.transition(row, "READY", "RUNNING")  # Pre-write audit failure stops the cycle.
            signal = ErrorSignal()
            logger = logging.getLogger("mem0.memory.main")
            logger.addHandler(signal)
            try:
                current = memory.get(row["memory_id"])
                if current:
                    if current.get("user_id") != row["user_id"] or current.get("agent_id") != row["app_id"] or not hmac.compare_digest(memory_digest(current), row["expected_digest"]):
                        raise ValueError("Memory no longer matches the confirmed cleanup version")
                    memory.delete(row["memory_id"])
                if memory.get(row["memory_id"]) is not None or signal.failed.is_set():
                    raise ValueError("Memory removal is not fully confirmed")
                self.transition(row, "RUNNING", "SUCCEEDED")
            except Exception:
                self.transition(row, "RUNNING", "NEEDS_REVIEW")
            finally:
                logger.removeHandler(signal)

    def verify(self, memory, user, app, memory_id):
        row = self.get(user, app, memory_id)
        if not row:
            raise ReceiptError(404, "Memory lifecycle is unavailable")
        if row["cleanup_state"] == "NEEDS_REVIEW":
            current = memory.get(memory_id)
            if current is None:
                self.transition(row, "NEEDS_REVIEW", "SUCCEEDED")
        return self.public(user, app, memory_id)


class GovernedVectorStore:
    """Filter native SDK retrieval and extraction context without changing stored vectors."""
    def __init__(self, delegate, lifecycle):
        self.delegate, self.lifecycle = delegate, lifecycle

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def search(self, *args, **kwargs):
        rows = self.delegate.search(*args, **kwargs)
        return [row for row in rows if row.payload and self.lifecycle.allowed(row.payload.get("user_id"), row.payload.get("agent_id"), row.id)]
