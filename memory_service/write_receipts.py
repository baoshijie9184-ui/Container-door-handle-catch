"""Private, durable receipts for one Mem0 writer. No conversation text is stored here."""
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

CST = timezone(timedelta(hours=8))


def now():
    return datetime.now(CST).isoformat(timespec="microseconds")


class ReceiptError(Exception):
    def __init__(self, status, detail, *, not_started=False):
        super().__init__(detail)
        self.status, self.detail = status, detail
        self.not_started = not_started


class ProcessFence:
    """An OS-owned lock, released by the OS on process death, never inferred from a PID file."""
    def __init__(self, directory):
        path = Path(directory).absolute()
        for parent in (path, *path.parents):
            if parent.is_symlink():
                raise ValueError("Memory receipt directory cannot contain links")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path, 0o700)
        self.path = path
        lock = path / "writer.lock"
        if lock.is_symlink():
            raise ValueError("Memory writer lock cannot be a link")
        self.file = open(lock, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0, 2)
                if self.file.tell() == 0:
                    self.file.write(b"0"); self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.chmod(lock, 0o600)
        except BaseException:
            self.file.close()
            raise

    def close(self):
        if not self.file.closed:
            self.file.close()


class ReceiptStore:
    def __init__(self, directory):
        self.path = Path(directory) / "write-receipts.sqlite3"
        if self.path.is_symlink():
            raise ValueError("Memory receipts cannot be a link")
        with closing(self.connect()) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS memory_write_receipt (
                user_id TEXT NOT NULL, app_id TEXT NOT NULL, request_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL, status TEXT NOT NULL,
                result_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, deadline_at TEXT NOT NULL,
                PRIMARY KEY(user_id,app_id,request_id))""")
        os.chmod(self.path, 0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=1)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        return db

    def interrupted(self):
        with closing(self.connect()) as db, db:
            db.execute("UPDATE memory_write_receipt SET status='NEEDS_REVIEW',updated_at=? WHERE status='RUNNING'", (now(),))

    def get(self, user, app, request_id):
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM memory_write_receipt WHERE user_id=? AND app_id=? AND request_id=?", (user, app, request_id)).fetchone()
            return dict(row) if row else None

    def reserve(self, user, app, request_id, fingerprint, deadline_seconds):
        timestamp = now()
        deadline = (datetime.now(CST) + timedelta(seconds=deadline_seconds)).isoformat(timespec="microseconds")
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO memory_write_receipt(user_id,app_id,request_id,fingerprint,status,created_at,updated_at,deadline_at) VALUES(?,?,?,?,'RUNNING',?,?,?)",
                       (user, app, request_id, fingerprint, timestamp, timestamp, deadline))

    def finish(self, user, app, request_id, status, results=()):
        if status not in {"SUCCEEDED", "NEEDS_REVIEW", "NOT_STARTED"}:
            raise ValueError("Invalid memory receipt status")
        encoded = json.dumps(list(results), ensure_ascii=False, separators=(",", ":"))
        with closing(self.connect()) as db, db:
            if db.execute("UPDATE memory_write_receipt SET status=?,result_json=?,updated_at=? WHERE user_id=? AND app_id=? AND request_id=? AND status IN ('RUNNING','NEEDS_REVIEW')",
                          (status, encoded, now(), user, app, request_id)).rowcount != 1:
                raise RuntimeError("Memory receipt version changed")

    def mark_overdue(self, user, app, request_id):
        # Completion may race a reader's earlier RUNNING snapshot. Never overwrite SUCCEEDED.
        with closing(self.connect()) as db, db:
            db.execute("UPDATE memory_write_receipt SET status='NEEDS_REVIEW',updated_at=? WHERE user_id=? AND app_id=? AND request_id=? AND status='RUNNING' AND deadline_at<?",
                       (now(), user, app, request_id, now()))


class ErrorSignal(logging.Handler):
    """Observe swallowed SDK errors without retaining their message, exception or private text."""
    def __init__(self):
        super().__init__(logging.WARNING)
        self.failed = threading.Event()

    def emit(self, record):
        self.failed.set()


def safe_results(result, memory, user, app):
    if not isinstance(result, dict) or not isinstance(result.get("results"), list) or len(result["results"]) > 100:
        raise ValueError("Invalid Mem0 result")
    rows = []
    for item in result["results"]:
        if not isinstance(item, dict) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(item.get("id", ""))):
            raise ValueError("Invalid Mem0 result identity")
        event = item.get("event")
        if event not in {"ADD", "UPDATE", "DELETE", "NONE"}:
            raise ValueError("Unknown Mem0 event")
        current = memory.get(item["id"])
        if event == "DELETE":
            if current:
                raise ValueError("Mem0 deletion is not confirmed")
        elif not current or current.get("user_id") != user or current.get("agent_id") != app:
            raise ValueError("Mem0 stored result is not confirmed")
        elif item.get("memory") is not None and current.get("memory") != item["memory"]:
            raise ValueError("Mem0 stored text differs")
        rows.append({"id": item["id"], "event": event})
    return rows


class MemoryWriter:
    def __init__(self, directory, memory, write_lock, *, response_wait=3.0, operation_seconds=120):
        self.fence = ProcessFence(directory)
        try:
            self.store = ReceiptStore(self.fence.path)
            self.store.interrupted()
            try:
                from .lifecycle import LifecycleStore
            except ImportError:
                from lifecycle import LifecycleStore
            self.lifecycle = LifecycleStore(self.store)
        except BaseException:
            self.fence.close(); raise
        self.memory, self.write_lock = memory, write_lock
        self.response_wait, self.operation_seconds = response_wait, operation_seconds
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory-extraction")
        self.mutex = threading.RLock()
        self.audit_unavailable = threading.Event()
        self.closed, self.future = False, None

    def receipt(self, user, app, request_id):
        row = self.store.get(user, app, request_id)
        if row is None:
            raise ReceiptError(404, "Memory operation is unavailable")
        if row["status"] == "RUNNING" and self.audit_unavailable.is_set():
            raise ReceiptError(503, "Memory outcome receipt is unavailable; needs verification")
        if row["status"] == "RUNNING" and row["deadline_at"] < now():
            self.store.mark_overdue(user, app, request_id)
            row = self.store.get(user, app, request_id)
        return {"requestId": row["request_id"], "status": row["status"], "createdAt": row["created_at"],
                "updatedAt": row["updated_at"], "deadlineAt": row["deadline_at"], "results": json.loads(row["result_json"])}

    def submit(self, user, app, session, content, metadata, request_id=None):
        metadata = dict(metadata or {})
        canonical = json.dumps({"user": user, "app": app, "session": session, "content": content,
                                "metadata": {k: v for k, v in metadata.items() if k != "timestamp"}},
                               ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        request_id = request_id or fingerprint  # compatibility for a previous Java client; new clients send turn IDs
        with self.mutex:
            old = self.store.get(user, app, request_id)
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ReceiptError(409, "Memory request identity already used")
                return self.receipt(user, app, request_id)
            if self.closed or self.audit_unavailable.is_set() or not self.write_lock.acquire(blocking=False):
                raise ReceiptError(503, "Memory write busy; operation not started", not_started=True)
            try:
                self.store.reserve(user, app, request_id, fingerprint, self.operation_seconds)
            except BaseException:
                self.write_lock.release(); raise
            try:
                self.future = self.executor.submit(self._execute, user, app, session, content, metadata, request_id)
            except BaseException:
                try: self.store.finish(user, app, request_id, "NOT_STARTED")
                finally: self.write_lock.release()
                raise
            future = self.future
        try:
            future.result(timeout=self.response_wait)
        except FutureTimeout:
            pass  # The worker still owns the writer slot; a reply timeout does not cancel a write.
        return self.receipt(user, app, request_id)

    def _execute(self, user, app, session, content, metadata, request_id):
        signal = ErrorSignal()
        logger = logging.getLogger("mem0.memory.main")
        logger.addHandler(signal)
        try:
            memory = self.memory()
            result = memory.add(content, user_id=user, agent_id=app, run_id=session, metadata=metadata)
            verified = safe_results(result, memory, user, app)
            if signal.failed.is_set():
                raise ValueError("Mem0 reported an internal error")
            self.store.finish(user, app, request_id, "SUCCEEDED", verified)
        except Exception:
            # A partial vector/history write or failed outcome audit cannot safely be replayed.
            try: self.store.finish(user, app, request_id, "NEEDS_REVIEW")
            except Exception:
                self.audit_unavailable.set()
                logging.getLogger(__name__).warning("Memory outcome receipt is unavailable")
        finally:
            logger.removeHandler(signal)
            self.write_lock.release()
            with self.mutex:
                if self.closed:
                    self.fence.close()

    def close(self, wait=True):
        with self.mutex:
            self.closed = True
        self.executor.shutdown(wait=wait)
        with self.mutex:
            if self.future is None or self.future.done():
                self.fence.close()

    def schedule_cleanup(self):
        with self.mutex:
            if self.closed or self.audit_unavailable.is_set() or not self.write_lock.acquire(blocking=False):
                return False
            try:
                self.future = self.executor.submit(self._cleanup)
            except BaseException:
                self.write_lock.release()
                raise
            return True

    def _cleanup(self):
        try:
            self.lifecycle.sweep(self.memory())
        except Exception:
            # Unknown completion-audit failures must also fence new extraction writes.
            self.audit_unavailable.set()
            logging.getLogger(__name__).warning("Memory cleanup receipt is unavailable")
        finally:
            self.write_lock.release()
            with self.mutex:
                if self.closed:
                    self.fence.close()
