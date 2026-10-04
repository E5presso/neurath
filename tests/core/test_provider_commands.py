"""Independent sessions require explicit selection and a native launch observation."""

import subprocess

import pytest

from neurath.core.domain import CoreError, Phase, Skill
from neurath.core.hook_adapter import HookAdapter
from neurath.core.provider_job import Run
from neurath.core.service import Context, Core
from neurath.providers.environment import child_environment


@pytest.fixture
def prepared(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    core = Core(
        tmp_path,
        skills={"run": Skill("run", "1", (Phase("execute", effects=frozenset({"delegate"})),))},
    )
    context = Context("codex:session:s", "s", "native")
    core.observe_actor(context.actor_id, context.session_id, "codex")
    source = core.observe_input(context, "Delegate the needed work", "input")
    task = core.call(
        context,
        "task_define",
        {
            "key": "define",
            "goal": "Result delivered",
            "source_ids": [source.id],
            "acceptance": [{"id": "done"}],
        },
    )["task"]
    for name, extra in [("task_start", {}), ("skill_start", {"skill": "run"})]:
        task = core.call(
            context,
            name,
            {"key": name, "task_id": task["id"], "expected_revision": task["revision"], **extra},
        )["task"]
    assignment = core.call(
        context,
        "assignment_prepare",
        {
            "key": "assignment",
            "task_id": task["id"],
            "expected_revision": task["revision"],
            "execution": "cross-provider",
            "provider": "claude-code",
            "scope": "Bounded independent inspection",
            "role": "worker",
            "subject": "source",
            "reason": "The other provider is needed for this bounded perspective",
        },
    )["assignment"]
    result = core.call(
        context,
        "provider_prepare",
        {
            "key": "provider",
            "task_id": task["id"],
            "assignment_id": assignment["id"],
            "checkout": str(tmp_path),
        },
    )
    return core, context, task["id"], assignment["id"], result


def test_prepare_never_starts_a_process_and_requires_native_admission(prepared):
    core, context, task_id, assignment_id, result = prepared
    assert result["run"]["state"] == "prepared"
    assert result["native_action"]["tool"] == "exec_command"
    with pytest.raises(CoreError, match="native-launch-required"):
        Run(core, result["run"]["id"])
    hook = HookAdapter(core, "codex")
    assert (
        hook.handle(
            "PreToolUse",
            {
                "session_id": "s",
                "tool_use_id": "launch",
                "tool_name": "Bash",
                "tool_input": {
                    "command": result["run"]["command"],
                    "workdir": result["run"]["checkout"],
                },
            },
            "pre",
        )
        == {}
    )
    run = Run(core, result["run"]["id"])
    assert run.value["state"] == "starting"
    with pytest.raises(CoreError, match="dispatch-already-started"):
        core.call(
            context,
            "provider_prepare",
            {
                "key": "duplicate",
                "task_id": task_id,
                "assignment_id": assignment_id,
                "checkout": result["run"]["checkout"],
            },
        )


def test_observed_provider_session_uses_existing_task_and_marks_peer_input(prepared):
    core, context, task_id, _assignment_id, result = prepared
    hook = HookAdapter(core, "codex")
    hook.handle(
        "PreToolUse",
        {
            "session_id": "s",
            "tool_use_id": "launch",
            "tool_name": "Bash",
            "tool_input": {"command": result["run"]["command"]},
        },
        "pre",
    )
    run = Run(core, result["run"]["id"])
    run.reserve_session("observed-claude")
    target = HookAdapter(core, "claude-code")
    target.handle("SessionStart", {"session_id": "observed-claude"}, "actual-start")
    run.observed("observed-claude", {"permission_mode": "default"})
    target.handle(
        "UserPromptSubmit", {"session_id": "observed-claude", "prompt": run.prompt}, "peer-input"
    )
    child = Context("claude-code:session:observed-claude", "observed-claude", "read")
    current = core.call(child, "task_list", {})
    assert len(current["tasks"]) == 1
    assert current["tasks"][0]["assignments"][0]["state"] == "active"
    with pytest.raises(CoreError, match="non-user-instruction"):
        core.call(
            child,
            "task_define",
            {
                "key": "duplicate-user-goal",
                "goal": "New work",
                "source_ids": [current["current_input"]["source_id"]],
                "acceptance": [{"id": "done"}],
            },
        )
    assert (
        core.call(context, "task_read", {"task_id": task_id})["task"]["owner_actor"]
        == context.actor_id
    )


def test_child_environment_keeps_user_security_settings_while_removing_identity():
    environment = child_environment(
        {
            "CODEX_THREAD_ID": "parent",
            "NEURATH_TOOL_BINDING": "parent",
            "CLAUDECODE": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "CODEX_SANDBOX_NETWORK_DISABLED": "1",
            "CODEX_HOME": "/configured",
            "HOME": "/home/user",
        }
    )
    assert "CODEX_THREAD_ID" not in environment and "NEURATH_TOOL_BINDING" not in environment
    assert environment["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert environment["CODEX_SANDBOX_NETWORK_DISABLED"] == "1"
    assert environment["HOME"] == "/home/user"


def test_codex_final_answer_event_retains_actual_report_before_terminal_fallback(monkeypatch):
    import neurath.providers.stdio
    from neurath.core.provider_job import codex

    body = '{"verdict":"blocked","subject":"fixture","body":"Native binding unavailable"}'

    class Transport:
        def __init__(self, checkout):
            self.events = iter(
                [
                    {
                        "method": "item/completed",
                        "params": {
                            "threadId": "actual",
                            "item": {
                                "id": "message",
                                "type": "agentMessage",
                                "phase": "final_answer",
                                "text": body,
                            },
                        },
                    },
                    {
                        "method": "turn/completed",
                        "params": {
                            "threadId": "actual",
                            "turn": {
                                "id": "turn",
                                "status": "completed",
                            },
                        },
                    },
                ]
            )

        def request(self, method, params):
            return (
                {"thread": {"id": "actual"}}
                if method == "thread/start"
                else {"turn": {"id": "turn"}}
            )

        def event(self, predicate, timeout):
            return next(self.events)

        def close(self):
            pass

    class Probe:
        prompt = "controlled test"

        def __init__(self):
            self.value = {"checkout": "fixture", "model": None}
            self.reports = []

        def reserve_session(self, session):
            assert session == "actual"

        def observed(self, session, settings):
            self.value["native_session"] = session

        def change(self, **values):
            self.value.update(values)

        def cancel_requested(self):
            return False

        def report(self, text, event_id):
            self.reports.append((text, event_id))

        def ended(self, result, **status):
            assert self.reports == [(body, "codex:message")]

    monkeypatch.setattr(neurath.providers.stdio, "CodexStdio", Transport)
    codex(Probe())


def test_prepared_provider_can_be_cancelled_without_starting_or_completing_user_task(prepared):
    core, context, task_id, assignment_id, result = prepared
    cancelled = core.call(
        context,
        "assignment_cancel",
        {
            "key": "cancel-prepared",
            "task_id": task_id,
            "assignment_id": assignment_id,
            "reason": "This execution is no longer needed",
        },
    )
    assert cancelled["assignment"]["state"] == "rejected"
    assert (
        core.call(context, "provider_read", {"run_id": result["run"]["id"]})["run"]["state"]
        == "cancelled"
    )
    assert core.call(context, "task_read", {"task_id": task_id})["task"]["state"] == "running"


def test_running_provider_observes_cancellation_as_request_until_native_return(prepared):
    core, context, task_id, assignment_id, result = prepared
    hook = HookAdapter(core, "codex")
    hook.handle(
        "PreToolUse",
        {
            "session_id": "s",
            "tool_use_id": "launch",
            "tool_name": "Bash",
            "tool_input": {"command": result["run"]["command"]},
        },
        "pre",
    )
    run = Run(core, result["run"]["id"])
    run.reserve_session("native-child")
    run.observed("native-child", {})
    core.call(
        context,
        "assignment_cancel",
        {
            "key": "cancel-running",
            "task_id": task_id,
            "assignment_id": assignment_id,
            "reason": "Stop this attempt",
        },
    )
    assert run.cancel_requested()
    assert (
        core.call(context, "assignment_read", {"task_id": task_id, "assignment_id": assignment_id})[
            "assignment"
        ]["state"]
        == "cancel-requested"
    )
    run.ended({"status": "interrupted"}, cancelled=True)
    assert core.call(context, "task_read", {"task_id": task_id})["task"]["state"] == "running"
    assert (
        core.call(context, "assignment_read", {"task_id": task_id, "assignment_id": assignment_id})[
            "assignment"
        ]["verdict"]
        == "cancelled"
    )
