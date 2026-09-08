"""Bounded, single-client JSON-RPC transport to an explicitly launched Codex server.

This is a new app-server process, not a connection to the user's desktop. No
approval is granted by this client. Interactive requests are reported and denied
as unsupported client methods. Existing host config, authentication and trust load.
"""

import json
import math
import os
import queue
import select
import shutil
import subprocess
import threading
import time

from neurath.providers.contracts import UnsupportedOperation


class RpcRejected(RuntimeError):
    """A native JSON-RPC error response, distinct from a lost response."""

    def __init__(self, method, error):
        self.method, self.error = method, error
        super().__init__(f"Codex {method}: {error}")


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
        self._request_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._response_lock = threading.Lock()
        self._responses = {}
        self._failure = None
        self._closed = False
        self._uncertain = False
        self._diagnostic_tail = ""
        self.supports_collaboration_mode = experimental is True
        self.process = subprocess.Popen(
            [executable, "app-server", "--stdio"], cwd=worktree, env=child_environment(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        os.set_blocking(self.process.stdin.fileno(), False)
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
                if "id" in event and "method" not in event:
                    with self._response_lock:
                        response = self._responses.get(event["id"])
                        if response is None:
                            raise ValueError("provider response has no pending request")
                        response.put_nowait(event)
                    continue
                if "id" in event and "method" in event:
                    self._send({"id": event["id"], "error": {
                        "code": -32601, "message": "Neurath transport does not grant interactive approvals"}})
                size = len(line.encode())
                with self._buffer_lock:
                    if self._queued_bytes + size > 8 * 1024 * 1024:
                        raise ValueError("queued provider data exceeds 8 MiB")
                    self._queued_bytes += size
                self._queue.put_nowait((event, size))
        except (ValueError, OSError, queue.Full) as error:
            self.process.terminate()
            self._fail(error)
        finally:
            self._fail(EOFError("Codex app-server connection ended"))

    def _fail(self, error):
        with self._response_lock:
            if self._failure is not None:
                return
            self._failure = error
            for response in self._responses.values():
                if response.empty():
                    response.put_nowait(error)
        self._queue.put_nowait(error)

    def fail_owned_dependency(self, error):
        """Wake native event/RPC waiters on a local owned-component failure.

        This is a local exception, never a fabricated app-server notification.
        Closing the actual owned process remains the worker responsibility.
        """
        if not isinstance(error, RuntimeError):
            raise TypeError("owned dependency failure must be a RuntimeError")
        self._fail(error)

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

    def _send(self, message, *, deadline=None):
        deadline = deadline if deadline is not None else time.monotonic() + self.timeout
        with self._send_lock:
            data = memoryview((json.dumps(message) + "\n").encode())
            descriptor = self.process.stdin.fileno()
            while data:
                if self._closed:
                    raise EOFError("Codex app-server connection closed")
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([], [descriptor], [], remaining)[1]:
                    self._uncertain = True
                    raise TimeoutError("Codex app-server write timeout; do not retry a mutation blindly")
                try:
                    data = data[os.write(descriptor, data):]
                except BlockingIOError:
                    continue

    def _next(self, deadline, *, uncertain_on_timeout=True):
        try:
            event = self._queue.get(timeout=max(0, deadline - time.monotonic()) if deadline else None)
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
        return event

    def _retain(self, event):
        size = len(json.dumps(event).encode())
        if self._event_bytes + size > 8 * 1024 * 1024:
            self._uncertain = True
            raise ValueError("unconsumed provider data exceeds 8 MiB")
        self._events.append((event, size))
        self._event_bytes += size

    def request(self, method, params):
        with self._request_lock:
            if self._closed or self._uncertain:
                raise RuntimeError("provider connection is closed or its result is uncertain; inspect native state")
            self._sequence += 1
            request_id = self._sequence
            response = queue.Queue(maxsize=1)
            with self._response_lock:
                if self._failure is not None:
                    raise self._failure
                self._responses[request_id] = response
            try:
                deadline = time.monotonic() + self.timeout
                self._send({"id": request_id, "method": method, "params": params}, deadline=deadline)
                try:
                    event = response.get(timeout=max(0, deadline - time.monotonic()))
                except queue.Empty:
                    self._uncertain = True
                    raise TimeoutError("Codex app-server response timeout; do not retry a mutation blindly") from None
                if isinstance(event, BaseException):
                    self._uncertain = True
                    raise event
                if "error" in event:
                    raise RpcRejected(method, event["error"])
                return event["result"]
            finally:
                with self._response_lock:
                    self._responses.pop(request_id, None)

    def event(self, predicate, *, timeout=30):
        """Consume only the matching event; a response is not turn completion."""
        with self._lock:
            if self._closed:
                raise EOFError("Codex app-server connection closed")
            for index, (event, size) in enumerate(self._events):
                if predicate(event):
                    self._events.pop(index)
                    self._event_bytes -= size
                    return event
            deadline = time.monotonic() + timeout if timeout is not None else None
            while True:
                if self._failure is not None and self._queue.empty():
                    raise self._failure
                event = self._next(deadline, uncertain_on_timeout=False)
                if predicate(event):
                    return event
                self._retain(event)

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._fail(EOFError("Codex app-server connection closed"))
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
