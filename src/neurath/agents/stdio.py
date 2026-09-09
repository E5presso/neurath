"""Bounded isolated tool calls keep the MCP input/control stream responsive."""
import json
import multiprocessing
import os
import sys
import threading
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path

from neurath.memory.store import canonical

MAX_HEAVY_CALLS = 4
MAX_CONTROL_CALLS = 8
MAX_REPLY_BYTES = 16 * 1024 * 1024


def error_reply(identity, code, message):
    return {"jsonrpc": "2.0", "id": identity, "error": {"code": code, "message": message}}


def _worker(root, request, sender):
    # Both Python and native-library diagnostics must stay off protocol stdout.
    os.dup2(2, 1)
    from neurath.runtime.engine import activate
    from neurath.agents.mcp import response
    activate(Path(root))
    try:
        with redirect_stdout(sys.stderr):
            result = response(Path(root), request)
        payload = canonical(result).encode()
        if len(payload) > MAX_REPLY_BYTES:
            raise ValueError("tool response exceeds transport budget")
    except BaseException as error:
        payload = canonical(error_reply(request["id"], -32603,
            f"Worker ended without a delivered result ({type(error).__name__}); inspect operation state")).encode()
    try:
        sender.send_bytes(payload)
    except (BrokenPipeError, OSError):
        pass
    finally:
        sender.close()


@dataclass
class _Call:
    identity: object
    process: object
    receiver: object
    heavy: bool
    cancelled: bool = False
    thread: object = None


class StdioCalls:
    """Only monitor threads share memory; task execution runs in fresh processes."""

    def __init__(self, root, output):
        self.root, self.output = Path(root), output
        self.context = multiprocessing.get_context("spawn")
        self.lock, self.output_lock = threading.Lock(), threading.Lock()
        self.calls = {}
        self.closing = False

    def write(self, reply):
        if reply is None:
            return
        with self.output_lock:
            try:
                self.output.write(canonical(reply) + "\n")
                self.output.flush()
            except (BrokenPipeError, OSError):
                pass  # Delivery loss cannot turn an executed operation into a retry.

    @staticmethod
    def _heavy(name):
        from neurath.runtime.task_schema import TASKS
        if name in {"verification_run", "verification_builtin", "verification_nodes", "provider_run"}:
            return True
        if name in {"provider_cancel", "provider_status"}:
            return False
        task = TASKS.get(name)
        return bool(task and not task[4] and task[0] in {
            "execution", "installation", "model-plan", "workflow-task", "maintenance"})

    def submit(self, request):
        key = canonical(request["id"])
        heavy = self._heavy(request["params"]["name"])
        limit = MAX_HEAVY_CALLS if heavy else MAX_CONTROL_CALLS
        with self.lock:
            if self.closing or key in self.calls or sum(c.heavy == heavy for c in self.calls.values()) >= limit:
                return False
            receiver, sender = self.context.Pipe(duplex=False)
            process = self.context.Process(target=_worker, args=(str(self.root), request, sender))
            try:
                process.start()
            except BaseException:
                receiver.close()
                sender.close()
                raise
            sender.close()
            call = _Call(request["id"], process, receiver, heavy)
            self.calls[key] = call
            call.thread = threading.Thread(target=self._watch, args=(key, call), daemon=True)
            try:
                call.thread.start()
            except BaseException:
                del self.calls[key]
                process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2)
                receiver.close()
                raise
        return True

    def _watch(self, key, call):
        try:
            reply = json.loads(call.receiver.recv_bytes(MAX_REPLY_BYTES))
        except (EOFError, OSError, ValueError):
            reply = error_reply(call.identity, -32603, "Worker result unavailable; inspect operation state")
        finally:
            call.receiver.close()
        call.process.join(timeout=2)
        if call.process.is_alive():
            call.process.terminate()
            call.process.join(timeout=2)
        if call.process.is_alive():
            call.process.kill()
            call.process.join(timeout=2)
        with self.lock:
            if self.calls.get(key) is not call:
                return
            del self.calls[key]
            cancelled, closing = call.cancelled, self.closing
        if not closing:
            self.write(error_reply(call.identity, -32800,
                "Request cancelled; inspect the operation outcome before retrying") if cancelled else reply)

    def cancel(self, identity):
        with self.lock:
            call = self.calls.get(canonical(identity))
            if call is None:
                return
            call.cancelled = True
            if call.process.is_alive():
                # The bounded verifier's SIGTERM handler also closes its owned tree.
                call.process.terminate()

    def close(self):
        with self.lock:
            self.closing = True
            calls = list(self.calls.values())
            for call in calls:
                call.cancelled = True
                if call.process.is_alive():
                    call.process.terminate()
        for call in calls:
            call.thread.join(timeout=3)
            if call.thread.is_alive() and call.process.is_alive():
                call.process.kill()
                call.thread.join(timeout=3)
