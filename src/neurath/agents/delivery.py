"""Event-driven outbox delivery to an already-owned native provider connection.

Internal provider workers register their actual recipient and callable. No tool
accepts an endpoint, actor or callable from an agent. Datagram payloads contain
only message IDs; the authenticated database supplies recipients and senders.
"""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import stat
import tempfile
import threading
import time
import uuid

from neurath.agents.delivery_recovery import (
    delivery_status as delivery_status,
    quarantine as quarantine,
    redrive as redrive,
    schema as recovery_schema,
)
from neurath.agents.store_events import StoreEvents


class DeliveryServiceError(RuntimeError):
    """A local receiver failure, distinct from a native model result."""
    def __init__(self, error_type):
        self.error_type = error_type
        super().__init__("owned delivery service failed: " + error_type)


def _schema(store):
    with store.connection() as db:
        recovery_schema(db)
        db.execute("""CREATE TABLE IF NOT EXISTS delivery_endpoints (
            address TEXT PRIMARY KEY, endpoint TEXT NOT NULL, generation TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS delivery_attempts (
            message TEXT PRIMARY KEY, recipient TEXT NOT NULL, generation TEXT NOT NULL,
            status TEXT NOT NULL, result TEXT NOT NULL, updated REAL NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS delivery_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, message TEXT NOT NULL,
            generation TEXT NOT NULL, status TEXT NOT NULL, result TEXT NOT NULL,
            updated REAL NOT NULL)""")


def _message_id(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("invalid message ID")
    return value


def _private_socket(path):
    """Refuse redirected, foreign-owned or publicly writable endpoints."""
    path = Path(path)
    parent = path.parent
    try:
        directory, entry = parent.lstat(), path.lstat()
    except OSError:
        return False
    return (parent.parent == Path("/tmp") and parent.name.startswith("neurath-delivery-")
            and stat.S_ISDIR(directory.st_mode) and directory.st_uid == os.getuid()
            and stat.S_IMODE(directory.st_mode) == 0o700
            and stat.S_ISSOCK(entry.st_mode) and entry.st_uid == os.getuid()
            and stat.S_IMODE(entry.st_mode) == 0o600)


def dispatch(store, message_id):
    """Called after the message transaction commits. Notification is not receipt."""
    _message_id(message_id)
    _schema(store)
    with store.connection() as db:
        message = store._message(db, message_id)
        if message["status"] not in {"queued", "submitted"}:
            return {"delivery": message["status"], "message_id": message_id}
        attempt = db.execute("SELECT status FROM delivery_attempts WHERE message=?", (message_id,)).fetchone()
        if attempt and attempt["status"] == "needs-input":
            return {"delivery": attempt["status"], "message_id": message_id}
        endpoint = db.execute("SELECT endpoint FROM delivery_endpoints WHERE address=?",
                              (message["recipient"],)).fetchone()
    if not endpoint or not _private_socket(endpoint["endpoint"]):
        return {"delivery": "queued", "message_id": message_id}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender:
            sender.setblocking(False)
            sender.sendto(message_id.encode("ascii"), endpoint["endpoint"])
    except OSError:
        return {"delivery": "queued", "message_id": message_id}
    return {"delivery": "notified", "message_id": message_id}


def receipt(store, message_id):
    """Read-only diagnostic; callers must not use this as a polling monitor."""
    _message_id(message_id)
    _schema(store)
    with store.connection() as db:
        row = db.execute("SELECT * FROM delivery_attempts WHERE message=?", (message_id,)).fetchone()
        return None if row is None else {**dict(row), "result": json.loads(row["result"])}


class DeliveryService:
    """One socket receiver per live native owner, with no task-lifetime deadline.

    Registration, durable store changes and resume each read pending messages once. resume() must only
    follow an actual native event clearing approval/input state. Unavailable transports use message retry backoff.
    Unacknowledged messages retry with the original ID. Retry deadlines concern
    individual messages; no periodic inbox scan or task-lifetime timer is used.
    An OS-held address lease prevents a second worker replacing a live owner;
    a crashed process releases the lease without guessing process IDs.
    """

    def __init__(self, store, address, deliver, *, retry_delay=30.0, on_failure=None):
        if not callable(deliver):
            raise ValueError("delivery requires an owned provider callable")
        if on_failure is not None and not callable(on_failure):
            raise ValueError("failure notification requires an owned callback")
        self._on_failure = on_failure
        self.store, self.address, self.deliver = store, address, deliver
        self.generation = uuid.uuid4().hex
        self.endpoint = None
        self._directory = self._socket = self._lease = self._thread = self._events = self._store_reader = None
        self._stop, self._resume = threading.Event(), threading.Event()
        self.changed = threading.Condition()
        self.failure = None
        self.terminal_error = None
        if not isinstance(retry_delay, (int, float)) or not 0 < retry_delay <= 300:
            raise ValueError("invalid message retry delay")
        self.retry_delay = retry_delay
        self._retry_at, self._counts, self._held = {}, {}, set()

    def __enter__(self):
        if self._thread is not None or self._stop.is_set():
            raise ValueError("delivery service cannot be restarted")
        _schema(self.store)
        with self.store.connection() as db:
            self.store._agent(db, self.address)
        name = "delivery-" + hashlib.sha256(self.address.encode()).hexdigest() + ".lock"
        self._lease = os.open(self.store.directory / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._directory = tempfile.mkdtemp(prefix="neurath-delivery-", dir="/tmp")
            os.chmod(self._directory, 0o700)
            self.endpoint = str(Path(self._directory) / "socket")
            self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            self._socket.bind(self.endpoint)
            os.chmod(self.endpoint, 0o600)
            with self.store.connection() as db:
                db.execute("INSERT INTO delivery_endpoints VALUES(?,?,?) ON CONFLICT(address) "
                           "DO UPDATE SET endpoint=excluded.endpoint,generation=excluded.generation",
                           (self.address, self.endpoint, self.generation))
            self._socket.setblocking(False)
            # A transaction-free reader prevents our own last-connection WAL
            # checkpoint/removal from generating an endless file-event loop.
            self._store_reader = sqlite3.connect(self.store.path.as_uri() + "?mode=ro",
                                                 uri=True, check_same_thread=False)
            self._store_reader.execute("SELECT 1 FROM messages LIMIT 0").close()
            self._events = StoreEvents(self.store.path, self._socket)
            self._thread = threading.Thread(target=self._run, daemon=True, name="neurath-delivery")
            self._thread.start()
            return self
        except BaseException:
            self.close()
            raise

    def _current(self, db):
        row = db.execute("SELECT * FROM delivery_endpoints WHERE address=?", (self.address,)).fetchone()
        return row and (row["generation"], row["endpoint"]) == (self.generation, self.endpoint)

    def _pending(self, *, resume=False):
        with self.store.connection() as db:
            if not self._current(db):
                return []
            if resume:
                self._held.clear()
            return [row[0] for row in db.execute(
                "SELECT m.id FROM messages m WHERE m.recipient=? "
                "AND m.status IN ('queued','submitted') ORDER BY m.sequence",
                (self.address,))]

    def _deliver(self, message_id):
        _message_id(message_id)
        if message_id in self._held or self._retry_at.get(message_id, 0) > time.monotonic():
            return
        self._retry_at.pop(message_id, None)
        with self.store.connection() as db:
            if not self._current(db):
                return
            message = self.store._message(db, message_id)
            if message["recipient"] != self.address or message["status"] not in {"queued", "submitted"}:
                self._counts.pop(message_id, None)
                return
            if db.execute("SELECT 1 FROM delivery_holds WHERE message=? AND active=1", (message_id,)).fetchone():
                return
            conversation = db.execute("SELECT * FROM conversations WHERE id=?", (message["conversation"],)).fetchone()
            if not conversation or not self.store._deliverable(db, conversation, message_id):
                return
            db.execute("INSERT INTO delivery_attempts VALUES(?,?,?,?,?,?) ON CONFLICT(message) "
                       "DO UPDATE SET generation=excluded.generation,status=excluded.status,"
                       "result=excluded.result,updated=excluded.updated",
                       (message_id, self.address, self.generation, "sending", "{}", time.time()))
            attempt_id = db.execute("INSERT INTO delivery_history(message,generation,status,result,updated) "
                                    "VALUES(?,?,?,?,?)", (message_id, self.generation, "sending", "{}", time.time())).lastrowid
            sender = message["sender"]
        try:
            result = self.deliver(message_id)
            if not isinstance(result, dict):
                raise ValueError("provider returned no delivery receipt")
            status = result.get("delivery")
            if status not in {"submitted", "uncertain", "failed", "needs-input", "unavailable", "repair-required"}:
                raise ValueError("provider returned an unsupported delivery status")
            if status == "repair-required":
                quarantine(self.store, message_id, reason=result.get("reason"), expected_generation=self.generation)
            # Only transport/result identifiers belong in this local receipt.
            result = {key: result[key] for key in ("delivery", "transport", "native_session", "native_turn")
                      if key in result and isinstance(result[key], str)}
            if status == "submitted":
                transport = result.get("transport")
                if not transport:
                    raise ValueError("submitted delivery requires its actual transport")
                # Record submission only while this connection still owns the
                # endpoint. A late response cannot change a successor's state.
                with self.store.connection() as db:
                    if self._current(db):
                        db.execute("UPDATE messages SET status='submitted',transport=? "
                                   "WHERE id=? AND sender=? AND status='queued'",
                                   (transport, message_id, sender))
        except Exception as error:
            status, result = "uncertain", {"error_type": type(error).__name__}
        with self.store.connection() as db:
            db.execute("UPDATE delivery_history SET status=?,result=?,updated=? WHERE id=?",
                       (status, json.dumps(result), time.time(), attempt_id))
            if self._current(db):
                db.execute("UPDATE delivery_attempts SET status=?,result=?,updated=? "
                           "WHERE message=? AND generation=?",
                           (status, json.dumps(result), time.time(), message_id, self.generation))
            pending = self.store._message(db, message_id)["status"] in {"queued", "submitted"}
        if pending and not self._stop.is_set():
            if status == "repair-required":
                return
            if status == "needs-input":
                self._held.add(message_id)
            else:
                self._schedule(message_id)

    def _schedule(self, message_id):
        count = min(self._counts.get(message_id, 0) + 1, 8)
        self._counts[message_id] = count
        self._retry_at[message_id] = time.monotonic() + min(300, self.retry_delay * 2 ** (count - 1))

    def _process(self, message_id):
        try:
            self._deliver(message_id)
        except Exception as error:
            self.failure = type(error).__name__
            self._schedule(message_id)
        finally:
            with self.changed:
                self.changed.notify_all()

    def _run(self):
        terminal_error = None
        try:
            for message_id in self._pending():
                if self._stop.is_set():
                    return
                self._process(message_id)
            while not self._stop.is_set():
                deadline = min(self._retry_at.values(), default=None)
                timeout = None if deadline is None else max(0.001, deadline - time.monotonic())
                payload, store_changed = self._events.wait(timeout)
                if store_changed:
                    for message_id in self._pending():
                        if self._stop.is_set():
                            break
                        self._process(message_id)
                if self._stop.is_set():
                    break
                if self._resume.is_set():
                    self._resume.clear()
                    for message_id in self._pending(resume=True):
                        if self._stop.is_set():
                            break
                        self._process(message_id)
                if len(payload) == 64:
                    try:
                        message_id = payload.decode("ascii")
                        _message_id(message_id)
                    except (UnicodeError, ValueError):
                        continue
                    self._process(message_id)
                for message_id, deadline in list(self._retry_at.items()):
                    if deadline <= time.monotonic() and not self._stop.is_set():
                        self._process(message_id)
        except Exception as error:
            self.failure = type(error).__name__
            terminal_error = DeliveryServiceError(self.failure)
            self.terminal_error = terminal_error
        finally:
            try:
                self._cleanup()
            except Exception as error:
                self.failure = self.failure or type(error).__name__
                terminal_error = terminal_error or DeliveryServiceError(self.failure)
                self.terminal_error = terminal_error
            with self.changed:
                self.changed.notify_all()
            if terminal_error is not None and not self._stop.is_set() and self._on_failure is not None:
                try:
                    self._on_failure(terminal_error)
                except Exception as error:
                    self.failure_notification_error = type(error).__name__

    def _wake(self):
        if self.endpoint:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender:
                    sender.setblocking(False)
                    sender.sendto(b"", self.endpoint)
            except OSError:
                pass  # A full socket already has a wakeup pending.

    def resume(self):
        """Retry held messages only after an actual relevant native event."""
        if self._stop.is_set() or self._thread is None:
            raise ValueError("delivery service is not running")
        self._resume.set()
        self._wake()

    def _cleanup(self):
        try:
            with self.store.connection() as db:
                db.execute("DELETE FROM delivery_endpoints WHERE address=? AND generation=?",
                           (self.address, self.generation))
        finally:
            if self._events:
                self._events.close()
                self._events = None
            if self._store_reader:
                self._store_reader.close()
                self._store_reader = None
            if self._socket:
                self._socket.close()
                self._socket = None
            if self._directory:
                Path(self.endpoint).unlink(missing_ok=True)
                Path(self._directory).rmdir()
                self._directory = None
            if self._lease is not None:
                os.close(self._lease)
                self._lease = None

    def close(self):
        self._stop.set()
        with self.store.connection() as db:
            db.execute("DELETE FROM delivery_endpoints WHERE address=? AND generation=?",
                       (self.address, self.generation))
        self._wake()
        if self._thread is not None:
            self._thread.join(timeout=1)
            # An in-flight provider RPC retains the lease and cleans up on
            # return. Caller shutdown never waits for its task lifetime.
        else:
            self._cleanup()

    def __exit__(self, *args):
        self.close()
