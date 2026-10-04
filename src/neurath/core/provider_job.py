"""Owned provider execution launched by a native host, never by an MCP mutation.

Session creation is used only for explicit session/cross-provider assignments.
Native subagents use native_delegation instead. No project creation API is used.
"""

import argparse
import asyncio
import json
import os
from dataclasses import asdict, replace
from hashlib import sha256
from uuid import uuid4

from neurath.core.codec import encode
from neurath.core.commands import Context
from neurath.core.domain import CoreError, Source, require
from neurath.core.provider_commands import observe_start
from neurath.core.service import Core
from neurath.redaction import clean


def emit(event, **value):
    print(encode({"event": event, **value}), flush=True)


class Run:
    def __init__(self, core, identifier):
        self.core = core
        with core.store.transaction() as tx:
            record = tx.record("provider-run", identifier)
            require(
                record is not None and record["value"]["state"] == "admitted",
                "native-launch-required",
            )
            self.value = {**record["value"], "state": "starting", "runner_pid": os.getpid()}
            tx.put_record("provider-run", identifier, self.value, record["revision"])
            task = tx.task(self.value["task_id"])
            self.assignment = next(
                a for a in task.assignments if a.id == self.value["assignment_id"]
            )
        self.context = None
        self.prompt = (
            "This is a bounded Neurath assignment from another agent, not a new human instruction. "
            "Use the existing Task and original user sources; do not define a duplicate user Task. "
            f"Task: {self.value['task_id']}. Assignment: {self.assignment.id}. "
            f"Role: {self.assignment.role}. Scope: {self.assignment.scope}. "
            f"Review subject: {self.assignment.subject}. "
            "Read task_read and assignment_read first. The native adapter binds and starts this assignment. "
            "Use the current named MCP tools and a fresh _call_id per invocation. "
            "An executor follows all existing skill phases and leaves final user-task acceptance to the owner. "
            "A reviewer reads/checks without writing project source or claiming its writer lease. "
            "Preserve host permissions. Report an actual blocker; do not change permissions or invent evidence. "
            "Return your actual result through assignment_report when available. "
            "Also make the final assistant message a JSON object with verdict (pass, failed, blocked, cancelled), "
            "subject and body. This is an attributed agent report, not native verification or user consent."
        )
        self.change(prompt_digest=sha256(self.prompt.encode()).hexdigest())

    def change(self, **fields):
        with self.core.store.transaction() as tx:
            record = tx.record("provider-run", self.value["id"])
            self.value = {**record["value"], **fields}
            tx.put_record("provider-run", self.value["id"], self.value, record["revision"])

    def reserve_session(self, session):
        with self.core.store.transaction() as tx:
            identity = encode([self.value["provider"], session])
            require(tx.record("provider-session", identity) is None, "provider-session-reused")
            tx.put_record("provider-session", identity, {"run_id": self.value["id"]})

    def observed(self, session, settings):
        actor = self.value["provider"] + ":session:" + session
        self.core.sessions.observe_actor(actor, session, self.value["provider"])
        self.context = Context(actor, session, "provider-start:" + self.value["id"])
        observe_start(self.core, self.value["provider"], self.context)
        self.change(state="running", native_session=session, recipient=actor, settings=settings)
        emit(
            "provider_started",
            run_id=self.value["id"],
            provider=self.value["provider"],
            native_session=session,
            settings=settings,
        )

    def cancel_requested(self):
        with self.core.store.transaction() as tx:
            task = tx.task(self.value["task_id"])
            assignment = next(a for a in task.assignments if a.id == self.assignment.id)
            return assignment.state == "cancel-requested"

    def report(self, body, event_id):
        if self.context is None:
            return
        with self.core.store.transaction() as tx:
            task = tx.task(self.value["task_id"])
            assignment = next(a for a in task.assignments if a.id == self.assignment.id)
            if assignment.state in {"reported", "accepted", "rejected"}:
                return
        try:
            value = json.loads(body)
        except ValueError, TypeError:
            return
        if not isinstance(value, dict) or set(value) != {"verdict", "subject", "body"}:
            return
        try:
            result = self.core.call(
                replace(self.context, invocation_id=event_id),
                "assignment_report",
                {
                    "key": "native-report:" + event_id,
                    "task_id": self.value["task_id"],
                    "assignment_id": self.assignment.id,
                    **value,
                },
            )
            emit(
                "report_available",
                assignment_id=self.assignment.id,
                source_id=result["assignment"]["result_source"],
            )
        except CoreError as error:
            emit("report_rejected", assignment_id=self.assignment.id, reason=error.code)

    def ended(self, native_result, *, failed=False, cancelled=False):
        # An actual native terminal event can report failure to return a result.
        # It never manufactures a passing reviewer or task completion.
        with self.core.store.transaction() as tx:
            task = tx.task(self.value["task_id"])
            assignment = next(a for a in task.assignments if a.id == self.assignment.id)
            if assignment.state not in {"reported", "accepted", "rejected"}:
                source = Source.create(
                    "source-" + uuid4().hex,
                    "tool",
                    encode(native_result),
                    "provider-ended:" + self.value["id"],
                )
                tx.put_source(source)
                assignment = assignment.recipient_ended(
                    source.id,
                    verdict="cancelled" if cancelled else "failed" if failed else "blocked",
                )
                tx.save_task(task.with_assignment(assignment), expected_revision=task.revision)
            if self.context:
                actor = tx.record("actor", self.context.actor_id)
                tx.put_record(
                    "actor",
                    self.context.actor_id,
                    {**actor["value"], "status": "stopped"},
                    actor["revision"],
                )
        self.change(
            state="cancelled" if cancelled else "failed" if failed else "completed",
            native_result=native_result,
        )
        emit(
            "provider_ended",
            run_id=self.value["id"],
            state=self.value["state"],
            assignment_state=assignment.state,
            verdict=assignment.verdict,
        )


def codex(run):
    from neurath.providers.stdio import CodexStdio

    transport = CodexStdio(run.value["checkout"])
    turn = None
    try:
        params = {"cwd": run.value["checkout"]}
        if run.value["model"] is not None:
            params["model"] = run.value["model"]
        response = transport.request("thread/start", params)
        session = response["thread"]["id"]
        run.reserve_session(session)
        run.observed(
            session,
            {key: response.get(key) for key in ("model", "approvalPolicy", "sandbox", "cwd")},
        )
        submitted = transport.request(
            "turn/start", {"threadId": session, "input": [{"type": "text", "text": run.prompt}]}
        )
        turn = submitted["turn"]["id"]
        run.change(native_turn=turn)
        interrupted = False
        while True:
            if run.cancel_requested() and not interrupted:
                transport.request("turn/interrupt", {"threadId": session, "turnId": turn})
                interrupted = True
            try:
                event = transport.event(lambda value: True, timeout=1)
            except TimeoutError:
                continue
            if "id" in event and "method" in event:
                emit(
                    "needs_input",
                    run_id=run.value["id"],
                    reason="native-permission-required",
                    method=event["method"],
                )
            params = event.get("params", {})
            if params.get("threadId") != session:
                continue
            if event.get("method") == "item/completed":
                item = params.get("item", {})
                if item.get("type") == "agentMessage" and item.get("phase") in {
                    None,
                    "final",
                    "final_answer",
                }:
                    run.report(item.get("text", ""), "codex:" + str(item.get("id")))
            if event.get("method") == "turn/completed" and params.get("turn", {}).get("id") == turn:
                result = params["turn"]
                run.ended(
                    result,
                    failed=result.get("status") not in {"completed", "interrupted"},
                    cancelled=result.get("status") == "interrupted",
                )
                break
    except KeyboardInterrupt:
        if turn:
            transport.request(
                "turn/interrupt", {"threadId": run.value["native_session"], "turnId": turn}
            )
        raise
    finally:
        transport.close()


async def claude(run):
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        PermissionResultDeny,
        ResultMessage,
        SystemMessage,
        TextBlock,
    )

    session = str(uuid4())
    run.reserve_session(session)

    async def permission(tool, _input, _context):
        emit("needs_input", run_id=run.value["id"], tool=tool, reason="native-permission-required")
        return PermissionResultDeny(
            message="This owned background connection cannot substitute for a human permission response.",
            interrupt=True,
        )

    options = ClaudeAgentOptions(
        cwd=run.value["checkout"],
        session_id=session,
        model=run.value["model"],
        setting_sources=["user", "project", "local"],
        system_prompt={"type": "preset", "preset": "claude_code"},
        include_partial_messages=True,
        can_use_tool=permission,
    )
    async with ClaudeSDKClient(options=options) as client:
        await client.query(run.prompt)

        async def cancellation():
            while True:
                if run.cancel_requested():
                    await client.interrupt()
                    return
                await asyncio.sleep(0.5)

        watcher = asyncio.create_task(cancellation())
        try:
            async for message in client.receive_response():
                if isinstance(message, SystemMessage) and message.subtype == "init":
                    require(message.data.get("session_id") == session, "provider-session-mismatch")
                    run.observed(
                        session,
                        {
                            "model": message.data.get("model"),
                            "permission_mode": message.data.get("permissionMode"),
                        },
                    )
                elif isinstance(message, AssistantMessage) and message.stop_reason == "end_turn":
                    require(message.session_id in {None, session}, "provider-session-mismatch")
                    body = "".join(
                        block.text for block in message.content if isinstance(block, TextBlock)
                    )
                    run.report(body, "claude:" + str(message.message_id or message.uuid))
                elif isinstance(message, ResultMessage):
                    require(message.session_id == session, "provider-session-mismatch")
                    if message.result:
                        run.report(message.result, "claude-result:" + str(message.uuid))
                    run.ended(
                        asdict(message),
                        failed=message.is_error,
                        cancelled=message.stop_reason in {"interrupt", "interrupted", "cancelled"},
                    )
                    return
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        raise RuntimeError("Provider stream ended without a native result")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    run = Run(Core(args.root), args.run_id)
    from neurath.providers.environment import child_environment

    environment = child_environment()
    os.environ.clear()
    os.environ.update(environment)
    try:
        if run.cancel_requested():
            run.ended({"status": "cancelled-before-session"}, cancelled=True)
            return 0
        if run.value["provider"] == "codex":
            codex(run)
        else:
            asyncio.run(claude(run))
    except (Exception, KeyboardInterrupt) as error:  # noqa: BLE001 - process boundary retains uncertain SDK failures without retrying
        # The owned transport has closed. Return the failed attempt so the
        # owner can inspect and retry the original Task without a stale worker.
        run.ended({"kind": "transport-disconnected", "error": clean(str(error))}, failed=True)
        run.change(state="disconnected", error=clean(str(error)))
        emit("provider_disconnected", run_id=run.value["id"], reason=clean(str(error)))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
