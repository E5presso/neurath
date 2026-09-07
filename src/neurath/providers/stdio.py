"""Bounded, single-client JSON-RPC transport to an explicitly launched Codex server.

This is a new app-server process, not a connection to the user's desktop. No
approval is granted by this client. Interactive requests are reported and denied
as unsupported client methods. Existing host config, authentication and trust load.
"""

import json
import math
import queue
import shutil
import subprocess
import threading
import time

from neurath.providers.contracts import UnsupportedOperation


class CodexStdio:
    approval_policies = ("never",)

    def __init__(self, worktree, *, timeout=30, experimental=False):
        from neurath.agents.runner import child_environment

        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
            raise ValueError("timeout must be between 0 and 3600 seconds")
        executable = shutil.which("codex")
        if executable is None:
            raise UnsupportedOperation("Codex CLI is not installed")
        self.timeout = timeout
        self._sequence = 0
        self._queue = queue.Queue()
        self._queued_bytes = 0
        self._buffer_lock = threading.Lock()
        self._events = []
        self._event_bytes = 0
        self._lock = threading.Lock()
        self._closed = False
        self._uncertain = False
        self._diagnostic_tail = ""
        self.supports_collaboration_mode = experimental is True
        self.process = subprocess.Popen(
            [executable, "app-server", "--stdio"], cwd=worktree, env=child_environment(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._errors = threading.Thread(target=self._read_errors, daemon=True)
        self._reader.start()
        self._errors.start()
        try:
            params = {"clientInfo": {"name": "neurath_provider", "version": "1"}}
            if experimental:
                params["capabilities"] = {"experimentalApi": True}
            self.server = self.request("initialize", params)
            self._send({"method": "initialized", "params": {}})
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            while not self._closed:
                line = self.process.stdout.readline(1024 * 1024 + 1)
                if not line:
                    break
                if len(line) > 1024 * 1024:
                    raise ValueError("provider event exceeds limit")
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError("provider event must be an object")
                size = len(line.encode())
                with self._buffer_lock:
                    if self._queued_bytes + size > 8 * 1024 * 1024:
                        raise ValueError("queued provider data exceeds 8 MiB")
                    self._queued_bytes += size
                self._queue.put_nowait((event, size))
        except (ValueError, OSError, queue.Full) as error:
            self.process.terminate()
            try:
                self._queue.put_nowait(error)
            except queue.Full:
                pass
        finally:
            try:
                self._queue.put_nowait(EOFError("Codex app-server connection ended"))
            except queue.Full:
                pass

    def _read_errors(self):
        try:
            while chunk := self.process.stderr.read(4096):
                self._diagnostic_tail = (self._diagnostic_tail + chunk)[-16384:]
        except (ValueError, OSError):
            pass

    @property
    def diagnostic(self):
        from neurath.memory.store import clean
        return clean(self._diagnostic_tail)

    def _send(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def _next(self, deadline, *, uncertain_on_timeout=True):
        try:
            event = self._queue.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            if uncertain_on_timeout:
                self._uncertain = True
            raise TimeoutError("Codex app-server response timeout; do not retry a mutation blindly") from None
        if isinstance(event, BaseException):
            self._uncertain = True
            raise event
        event, size = event
        with self._buffer_lock:
            self._queued_bytes -= size
        if "id" in event and "method" in event:
            self._send({"id": event["id"], "error": {
                "code": -32601, "message": "Neurath transport does not grant interactive approvals"}})
        return event

    def _retain(self, event):
        size = len(json.dumps(event).encode())
        if self._event_bytes + size > 8 * 1024 * 1024:
            self._uncertain = True
            raise ValueError("unconsumed provider data exceeds 8 MiB")
        self._events.append((event, size))
        self._event_bytes += size

    def request(self, method, params):
        with self._lock:
            if self._closed or self._uncertain:
                raise RuntimeError("provider connection is closed or its result is uncertain; inspect native state")
            self._sequence += 1
            request_id = self._sequence
            self._send({"id": request_id, "method": method, "params": params})
            deadline = time.monotonic() + self.timeout
            while True:
                event = self._next(deadline)
                if event.get("id") == request_id and "method" not in event:
                    if "error" in event:
                        raise RuntimeError(f"Codex {method}: {event['error']}")
                    return event["result"]
                self._retain(event)

    def event(self, predicate, *, timeout=30):
        """Consume only the matching event; a response is not turn completion."""
        with self._lock:
            for index, (event, size) in enumerate(self._events):
                if predicate(event):
                    self._events.pop(index)
                    self._event_bytes -= size
                    return event
            deadline = time.monotonic() + timeout
            while True:
                event = self._next(deadline, uncertain_on_timeout=False)
                if predicate(event):
                    return event
                self._retain(event)

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self.process.stdin:
            try:
                self.process.stdin.close()
            except BrokenPipeError:
                pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self._reader.join(timeout=1)
        self._errors.join(timeout=1)
        self.process.stdout.close()
        self.process.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
