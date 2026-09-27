"""Owned stock app-server transport shared by native verification scenarios.

This client never approves interactive requests or changes host trust/settings.
Its lifecycle owns only its explicitly created subprocess and evidence streams.
"""

from contextlib import ExitStack
import json
import os
import queue
import subprocess
import threading
import time


class Host:
    def __init__(self, project, output, executable="codex"):
        self.events = []
        self.queue = queue.Queue()
        self.sequence = 0
        self._resources = ExitStack()
        self._closed = False
        self.process = None
        try:
            self.log = self._resources.enter_context((output / "events.jsonl").open("a"))
            self.stderr = self._resources.enter_context((output / "stderr.log").open("a"))
            env = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith(("NEURATH_", "CLAUDE", "CODEX_")) or key == "CODEX_HOME"
            }
            self.process = subprocess.Popen(
                [executable, "app-server", "--stdio"],
                cwd=project,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.stderr,
                text=True,
                bufsize=1,
            )
            threading.Thread(target=self._read, daemon=True).start()
            self.request(
                "initialize",
                {
                    "clientInfo": {"name": "neurath_steering_probe", "version": "1"},
                    "capabilities": {"experimentalApi": True},
                },
            )
            self.send({"method": "initialized", "params": {}})
        except BaseException:
            # Constructor failure includes interruption; never orphan our own host.
            self.close()
            raise

    def _read(self):
        for line in self.process.stdout:
            try:
                self.queue.put(json.loads(line))
            except ValueError:
                continue
        self.queue.put(None)

    def send(self, value):
        self.process.stdin.write(json.dumps(value) + "\n")
        self.process.stdin.flush()

    def wait(self, predicate, timeout=240):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = self.queue.get(timeout=max(0.01, deadline - time.monotonic()))
            if event is None:
                raise RuntimeError("native host exited")
            self.events.append(event)
            self.log.write(json.dumps(event) + "\n")
            self.log.flush()
            if "id" in event and "method" in event:
                self.send(
                    {
                        "id": event["id"],
                        "error": {
                            "code": -32601,
                            "message": "Interactive requests are unsupported by this verification client",
                        },
                    }
                )
            if predicate(event):
                if "error" in event:
                    raise RuntimeError(event["error"])
                return event
        raise TimeoutError("native host event timeout")

    def request(self, method, params):
        self.sequence += 1
        identity = self.sequence
        self.send({"id": identity, "method": method, "params": params})
        return self.wait(lambda event: event.get("id") == identity)["result"]

    def close(self):
        """Close only the process created by this client, even after partial startup."""
        if self._closed:
            return
        self._closed = True
        try:
            if self.process is not None:
                try:
                    self.process.stdin.close()
                except BrokenPipeError:
                    pass
                try:
                    self.process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=15)
        finally:
            if self.process is not None and self.process.returncode is not None:
                self.process.stdout.close()
            self._resources.close()
