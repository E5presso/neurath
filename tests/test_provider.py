"""실제 프로세스 경계에서 provider 계획·중복 실행·종료·복구를 검증한다."""

import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from neurath.application.provider_records import ProviderCapabilities, ProviderObservation
from neurath.domain.aggregates.delegation import Delegation
from neurath.domain.aggregates.request_source import SourceKind
from neurath.domain.delegation_records import (
    DelegationRole,
    DelegationRoute,
    DelegationStatus,
    ProviderPlan,
)
from neurath.domain.errors import InvalidTaskState
from neurath.infrastructure.provider import SubprocessProviderService
from neurath.infrastructure.provider_protocol import discover_models
from neurath.infrastructure.provider_worker import execute, process_identity
from tests.test_collaboration import call, prepare
from tests.test_collaboration import collaboration as collaboration
from tests.test_task_requests import record


@pytest.fixture
def provider_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    binpath = tmp_path / "bin"
    binpath.mkdir()
    monkeypatch.setenv("PATH", str(binpath) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(
        SubprocessProviderService,
        "discover",
        lambda self, p: ProviderCapabilities(p, ("fixture-model",), ("read-only", "plan")),
    )
    plan = ProviderPlan(
        provider="codex",
        model="fixture-model",
        policy="read-only",
        directory=str(tmp_path),
        parent_session_id="parent",
    )
    return binpath, plan


def executable(directory, name, body):
    path = directory / name
    help_text = (
        "--no-daemon --sandbox [possible values: read-only, workspace-write, danger-full-access]"
        if name == "codex"
        else '--permission-mode (choices: "plan", "dontAsk", "acceptEdits")'
    )
    prefix = f"import sys\nif '--help' in sys.argv:\n print({help_text!r});sys.exit(0)\n"
    path.write_text("#!" + sys.executable + "\n" + prefix + body)
    path.chmod(0o755)
    return path


def finished(service, uid):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = service.observe(uid)
        if result.status in ("completed", "failed", "stopped"):
            return result
        time.sleep(0.02)
    raise AssertionError("Fixture process did not finish")


def test_real_subprocess_run_recovers_same_execution_and_original_output(provider_environment):
    binpath, plan = provider_environment
    marker = Path(plan.directory) / "executions"
    executable(
        binpath,
        "codex",
        f"""import json,sys
from pathlib import Path
p=Path({str(marker)!r});p.write_text(p.read_text()+"x" if p.exists() else "x")
print(json.dumps({{"type":"thread.started","thread_id":"actual-fixture-session"}}),flush=True)
print(json.dumps({{"type":"item.completed","item":{{"type":"agent_message","text":sys.stdin.read()}}}}),flush=True)
print(json.dumps({{"type":"turn.completed"}}),flush=True)
""",
    )
    service = SubprocessProviderService()
    uid = str(uuid4())
    initial = service.start(uid, plan, "original assigned scope")
    assert initial.status in ("unknown", "running", "completed")
    result = finished(service, uid)
    assert result.status == "completed" and result.native_session_id == "actual-fixture-session"
    assert result.output == "original assigned scope"
    assert service.start(uid, plan, "original assigned scope") == result
    assert marker.read_text() == "x"
    assert service.cancel(uid).status == "completed"
    with pytest.raises(ValueError):
        service.start(uid, replace(plan, model="different"), "scope")
    process = json.loads((Path(result.reference) / "process.json").read_text())
    assert not process_identity(process["pid"])


def test_actual_cancel_is_not_reported_until_process_exit(provider_environment):
    binpath, plan = provider_environment
    executable(
        binpath,
        "codex",
        'import json,time\nprint(json.dumps({"type":"thread.started","thread_id":"slow-session"}),flush=True)\ntime.sleep(30)\n',
    )
    service = SubprocessProviderService()
    uid = str(uuid4())
    service.start(uid, plan, "scope")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and service.observe(uid).native_session_id is None:
        time.sleep(0.02)
    observed = service.cancel(uid)
    assert observed.status in ("running", "unknown", "stopped")
    assert finished(service, uid).status == "stopped"
    assert service.start(uid, plan, "scope").status == "stopped"


def test_cancel_before_launch_prevents_future_execution(provider_environment):
    _, plan = provider_environment
    service = SubprocessProviderService()
    uid = str(uuid4())
    assert service.cancel(uid).status == "stopped"
    assert service.start(uid, plan, "scope").status == "stopped"
    assert not (service._directory(uid) / "process.json").exists()


@pytest.mark.parametrize(
    "change", [{"model": "unsupported"}, {"policy": "unsupported"}, {"directory": "/missing"}]
)
def test_invalid_plan_creates_no_execution(provider_environment, change):
    _, plan = provider_environment
    service = SubprocessProviderService()
    uid = str(uuid4())
    with pytest.raises(ValueError):
        service.start(uid, replace(plan, **change), "scope")
    assert not service._directory(uid).exists()


def test_empty_prompt_has_no_external_side_effect(provider_environment):
    _, plan = provider_environment
    service = SubprocessProviderService()
    uid = str(uuid4())
    with pytest.raises(ValueError):
        service.start(uid, plan, "")
    assert not service._directory(uid).exists()


@pytest.mark.parametrize(
    "lines,result,status",
    [
        ("invalid partial json\n", {"exit_code": 0}, "failed"),
        (
            json.dumps({"type": "thread.started", "thread_id": "session"}) + "\n",
            {"exit_code": 0},
            "failed",
        ),
        (
            json.dumps({"type": "thread.started", "thread_id": "session"})
            + "\n"
            + json.dumps({"type": "turn.failed", "error": "failure"})
            + "\n",
            {"exit_code": 1},
            "failed",
        ),
        (
            json.dumps(
                {
                    "type": "result",
                    "session_id": "claude-session",
                    "is_error": True,
                    "errors": ["failed"],
                }
            )
            + "\n",
            {"exit_code": 0},
            "failed",
        ),
        (
            json.dumps(
                {
                    "type": "result",
                    "session_id": "claude-session",
                    "result": "answer",
                    "is_error": False,
                }
            )
            + "\n",
            {"exit_code": 0},
            "completed",
        ),
        (
            json.dumps({"type": "error", "error": "auth"}) + "\n",
            {"error": "startup failure"},
            "failed",
        ),
        ("", {"exit_code": -15}, "failed"),
    ],
)
def test_terminal_observations_require_native_identity_and_real_result(
    provider_environment, lines, result, status
):
    service = SubprocessProviderService()
    uid = str(uuid4())
    directory = service._directory(uid)
    directory.mkdir(parents=True)
    (directory / "output.jsonl").write_text(lines)
    (directory / "result.json").write_text(json.dumps(result))
    assert service.observe(uid).status == status


def test_cancel_never_signals_a_reused_process_identity(provider_environment, monkeypatch):
    service = SubprocessProviderService()
    uid = str(uuid4())
    directory = service._directory(uid)
    directory.mkdir(parents=True)
    (directory / "process.json").write_text(
        json.dumps({"pid": os.getpid(), "identity": "wrong identity"})
    )
    monkeypatch.setattr(os, "killpg", lambda *args: pytest.fail("must not signal another process"))
    assert service.cancel(uid).status == "unknown"
    (directory / "process.json").unlink()
    assert service.cancel(uid).status == "unknown"


def test_disappearing_process_during_cancel_remains_unconfirmed(provider_environment, monkeypatch):
    service = SubprocessProviderService()
    uid = str(uuid4())
    directory = service._directory(uid)
    directory.mkdir(parents=True)
    (directory / "process.json").write_text(json.dumps({"pid": 42, "identity": "observed"}))
    monkeypatch.setattr("neurath.infrastructure.provider.process_identity", lambda pid: "observed")

    def disappeared(*args):
        raise ProcessLookupError

    monkeypatch.setattr(os, "killpg", disappeared)
    assert service.cancel(uid).status == "unknown"


def test_worker_handles_cancel_before_spawn_and_missing_cli(provider_environment, monkeypatch):
    binpath, plan = provider_environment
    service = SubprocessProviderService()
    uid = str(uuid4())
    directory = service._directory(uid)
    directory.mkdir(parents=True)
    (directory / "cancel.requested").touch()
    execute(directory)
    assert service.observe(uid).status == "stopped"
    other = service._directory(str(uuid4()))
    other.mkdir()
    (other / "plan.json").write_text(
        json.dumps(
            dict(provider="codex", model=plan.model, policy=plan.policy, directory=plan.directory)
        )
    )
    (other / "prompt.txt").write_text("scope")
    monkeypatch.setenv("PATH", str(binpath))
    execute(other)
    assert "error" in json.loads((other / "result.json").read_text())


def test_claude_worker_uses_explicit_plan_and_real_session(provider_environment):
    binpath, plan = provider_environment
    executable(
        binpath,
        "claude",
        'import sys,json\nassert "plan" in sys.argv\nprint(json.dumps({"type":"result","session_id":sys.argv[sys.argv.index("--session-id")+1],"result":"done","is_error":False}))\n',
    )
    service = SubprocessProviderService()
    uid = str(uuid4())
    service.start(uid, replace(plan, provider="claude", policy="plan"), "scope")
    result = finished(service, uid)
    assert result.status == "completed" and result.native_session_id == uid


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_discovery_uses_control_protocol_without_a_model_prompt(tmp_path, monkeypatch, provider):
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    if provider == "codex":
        script = """import sys,json
request=json.loads(sys.stdin.readline());assert request['method']=='initialize'
print(json.dumps({'id':1,'result':{}}),flush=True)
assert json.loads(sys.stdin.readline())['method']=='initialized'
request=json.loads(sys.stdin.readline());assert request['method']=='model/list'
print(json.dumps({'id':2,'result':{'data':[{'model':'first'}],'nextCursor':'more'}}),flush=True)
request=json.loads(sys.stdin.readline());assert request['params']['cursor']=='more'
print(json.dumps({'id':2,'result':{'data':[{'model':'second'}],'nextCursor':None}}),flush=True)
sys.stdin.read()
"""
    else:
        script = """import sys,json
request=json.loads(sys.stdin.readline());assert request['request']['subtype']=='initialize'
print(json.dumps({'type':'system','subtype':'init'}),flush=True)
print(json.dumps({'type':'control_response','response':{'subtype':'success','response':{'models':[{'value':'alias','resolvedModel':'first'},{'value':'second'}]}}}),flush=True)
sys.stdin.read()
"""
    executable(tmp_path, provider, script)
    assert discover_models(provider) == ("first", "second")
    caps = SubprocessProviderService().discover(provider)
    assert caps.models == ("first", "second") and "inherit" not in caps.policies


@pytest.mark.parametrize(
    "provider,reply",
    [
        ("codex", {"error": {"message": "unsupported protocol"}}),
        ("codex", {"id": 2, "result": {"data": [], "nextCursor": None}}),
        (
            "claude",
            {"type": "control_response", "response": {"subtype": "error", "error": "unavailable"}},
        ),
        (
            "claude",
            {
                "type": "control_response",
                "response": {"subtype": "success", "response": {"models": []}},
            },
        ),
    ],
)
def test_discovery_never_invents_models_after_error(tmp_path, monkeypatch, provider, reply):
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    executable(
        tmp_path,
        provider,
        f"import sys,json\nsys.stdin.readline()\nprint({json.dumps(reply)!r},flush=True)\nsys.stdin.read()\n",
    )
    with pytest.raises(RuntimeError):
        discover_models(provider)


def test_discovery_unsupported_provider_and_early_exit(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        discover_models("invented")
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    executable(tmp_path, "codex", "import sys\nsys.stdin.readline()\n")
    with pytest.raises(RuntimeError, match="exited"):
        discover_models("codex")


async def test_provider_application_commits_before_launch_and_recovers_without_duplicate(
    database, collaboration, monkeypatch
):
    actor, sender, _, _, task = collaboration
    calls = []

    def discover(self, provider):
        return ProviderCapabilities("codex", ("model",), ("read-only",))

    def start(self, uid, plan, prompt):
        import sqlite3

        with sqlite3.connect(database, timeout=0.1) as connection:
            assert connection.execute(
                "SELECT provider_requested FROM core_delegations WHERE id=?", (uid,)
            ).fetchone() == (1,)
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
        assert "original requirement text" in prompt and task.definition.required_result in prompt
        calls.append(uid)
        return ProviderObservation("/run/" + uid, "running", "native-actual")

    monkeypatch.setattr(SubprocessProviderService, "discover", discover)
    monkeypatch.setattr(SubprocessProviderService, "start", start)
    plan = ProviderPlan(
        provider="codex",
        model="model",
        policy="read-only",
        directory=actor.session.working_directory,
        parent_session_id=actor.session.uid,
    )
    from neurath.application.usecases.prepare_delegation import PrepareDelegationCommand

    assignment = PrepareDelegationCommand(
        task.uid, sender.uid, DelegationRole.EXECUTOR, "scope", DelegationRoute.PROVIDER, None, plan
    )
    delegation = await call(database, "delegate_task", "DelegateTask", assignment)
    assert (
        delegation.provider_status == "running" and delegation.native_session_id == "native-actual"
    )
    await call(database, "delegate_task", "DelegateTask", assignment)
    assert calls == [delegation.uid]
    monkeypatch.setattr(
        SubprocessProviderService,
        "observe",
        lambda self, uid: ProviderObservation(
            "/run/" + uid, "completed", "native-actual", "result"
        ),
    )
    await call(database, "recover_provider", "RecoverProvider", delegation.uid, sender.uid)
    completed = await call(
        database, "get_delegation", "GetDelegation", delegation.uid, sender.uid, query=True
    )
    assert completed.provider_status == "completed" and completed.provider_output == "result"
    monkeypatch.setattr(
        SubprocessProviderService,
        "observe",
        lambda self, uid: ProviderObservation("/run/" + uid, "running", "native-actual"),
    )
    await call(database, "recover_provider", "RecoverProvider", delegation.uid, sender.uid)
    assert (
        await call(
            database, "get_delegation", "GetDelegation", delegation.uid, sender.uid, query=True
        )
    ).provider_status == "completed"
    detail = await call(
        database, "get_task", "GetTask", task.project_id, actor.session.uid, task.uid, query=True
    )
    assert detail.delegations[0].uid == delegation.uid and detail.task.status.value == "pending"


async def test_provider_cancel_propagates_and_unsupported_policy_does_not_create_plan(
    database, collaboration, monkeypatch
):
    actor, sender, _, _, task = collaboration
    monkeypatch.setattr(
        SubprocessProviderService,
        "discover",
        lambda self, p: ProviderCapabilities("codex", ("model",), ("read-only",)),
    )
    from neurath.application.usecases.prepare_delegation import PrepareDelegationCommand

    plan = ProviderPlan(
        provider="codex",
        model="model",
        policy="wrong",
        directory=actor.session.working_directory,
        parent_session_id=actor.session.uid,
    )
    request = PrepareDelegationCommand(
        task.uid, sender.uid, DelegationRole.EXECUTOR, "scope", DelegationRoute.PROVIDER, None, plan
    )
    with pytest.raises(ValueError):
        await call(database, "delegate_task", "DelegateTask", request)
    monkeypatch.setattr(
        SubprocessProviderService,
        "start",
        lambda self, uid, p, prompt: ProviderObservation("/run/" + uid, "running", "native-actual"),
    )
    delegation = await call(
        database,
        "delegate_task",
        "DelegateTask",
        replace(request, plan=replace(plan, policy="read-only")),
    )
    stops = []

    def cancel(self, uid):
        stops.append(uid)
        return ProviderObservation("/run/" + uid, "stopped", "native-actual")

    monkeypatch.setattr(SubprocessProviderService, "cancel", cancel)
    correction = await record(
        database, actor, SourceKind.CORRECTION, corrects_id=task.definition.source_id
    )
    await call(
        database,
        "invalidate_task",
        "InvalidateTask",
        task.project_id,
        actor.session.uid,
        task.uid,
        task.revision,
        correction.uid,
        "cancel original request",
    )
    cancelled = await call(
        database, "get_delegation", "GetDelegation", delegation.uid, sender.uid, query=True
    )
    assert cancelled.status is DelegationStatus.STOPPED and stops == [delegation.uid]
    with pytest.raises(InvalidTaskState):
        await call(database, "start_provider", "StartProvider", delegation.uid, sender.uid)


async def test_provider_start_failure_is_preserved_as_uncertain_not_success(
    database, collaboration, monkeypatch
):
    actor, sender, _, _, task = collaboration
    monkeypatch.setattr(
        SubprocessProviderService,
        "discover",
        lambda self, p: ProviderCapabilities("codex", ("model",), ("read-only",)),
    )

    def fail(*args):
        raise OSError("could not launch managed worker")

    monkeypatch.setattr(SubprocessProviderService, "start", fail)
    from neurath.application.usecases.prepare_delegation import PrepareDelegationCommand

    plan = ProviderPlan(
        provider="codex",
        model="model",
        policy="read-only",
        directory=actor.session.working_directory,
        parent_session_id=actor.session.uid,
    )
    delegation = await call(
        database,
        "delegate_task",
        "DelegateTask",
        PrepareDelegationCommand(
            task.uid,
            sender.uid,
            DelegationRole.EXECUTOR,
            "scope",
            DelegationRoute.PROVIDER,
            None,
            plan,
        ),
    )
    assert (
        delegation.provider_status == "unknown" and "could not launch" in delegation.provider_error
    )
    assert delegation.execution_reference is None and delegation.native_session_id is None
    assert delegation.status is DelegationStatus.PREPARED


async def test_provider_hook_binds_only_actual_session_and_current_assignment(
    database, collaboration
):
    from neurath.application.ports.repositories.delegation import IDelegationRepository
    from neurath.application.usecases.receive_hook import ReceiveHookCommand, ReceiveHookUseCase
    from neurath.domain.runtime_records import HookAction, HookEvent
    from tests.conftest import storage_scope
    from tests.support.requests import run

    actor, sender, _, _, task = collaboration
    plan = ProviderPlan(
        provider="codex",
        model="model",
        policy="read-only",
        directory=actor.session.working_directory,
        parent_session_id=actor.session.uid,
    )
    delegation = await prepare(
        database, collaboration, route=DelegationRoute.PROVIDER, recipient_id=None, plan=plan
    )
    async with storage_scope(database) as scope:
        stored = await scope.get(IDelegationRepository).get(delegation.uid)
        stored.provider_requested = True
        await scope.get(IDelegationRepository).save(stored)
    command = ReceiveHookCommand(
        "codex",
        "actual-provider-session",
        actor.session.working_directory,
        HookEvent.SESSION_START,
        start_source="startup",
        delegation_id=delegation.uid,
    )
    assert (
        await run(ReceiveHookUseCase, command, database_path=database)
    ).action is HookAction.ALLOW
    bound = await call(
        database, "get_delegation", "GetDelegation", delegation.uid, sender.uid, query=True
    )
    assert bound.native_session_id == "actual-provider-session" and bound.recipient_id
    await call(
        database,
        "record_provider",
        "RecordProvider",
        delegation.uid,
        ProviderObservation("/actual-run", "running", "actual-provider-session"),
    )
    with pytest.raises(InvalidTaskState):
        await run(
            ReceiveHookUseCase,
            replace(command, host_session_id="another-session"),
            database_path=database,
        )
    with pytest.raises(InvalidTaskState):
        await run(ReceiveHookUseCase, replace(command, provider="claude"), database_path=database)


async def test_provider_cannot_execute_in_a_different_project(database, collaboration, tmp_path):
    actor, _, _, _, _ = collaboration
    elsewhere = tmp_path / "another-project"
    elsewhere.mkdir()
    from tests.support.session_requests import register_session

    await register_session(str(elsewhere), "codex", "elsewhere", database_path=database)
    plan = ProviderPlan(
        provider="codex",
        model="model",
        policy="read-only",
        directory=str(elsewhere),
        parent_session_id=actor.session.uid,
    )
    with pytest.raises(InvalidTaskState, match="another project"):
        await prepare(
            database, collaboration, route=DelegationRoute.PROVIDER, recipient_id=None, plan=plan
        )
    unknown = tmp_path / "unregistered"
    unknown.mkdir()
    with pytest.raises(InvalidTaskState, match="another project"):
        await prepare(
            database,
            collaboration,
            route=DelegationRoute.PROVIDER,
            recipient_id=None,
            plan=replace(plan, directory=str(unknown)),
        )


async def test_run_requires_committed_provider_request(database, collaboration):
    from neurath.application.usecases.run_provider import RunProviderCommand, RunProviderUseCase
    from tests.support.application import spakky_context

    delegation = await prepare(database, collaboration)
    async with spakky_context(database) as scope:
        with pytest.raises(InvalidTaskState):
            await scope.get(RunProviderUseCase).run(RunProviderCommand(delegation.uid, "scope"))


def test_provider_observation_identity_and_late_results_are_fenced():
    from neurath.domain.aggregates.request_source import RequestSource
    from neurath.domain.aggregates.task import Task

    source = RequestSource.create("p", "s", SourceKind.PROMPT, "original")
    task = Task.create("p", "s", source, "title", "result")
    plan = ProviderPlan(
        provider="codex", model="model", policy="read-only", directory="/tmp", parent_session_id="s"
    )
    delegation = Delegation(
        uid=Delegation.next_id(),
        task_id=task.uid,
        definition_number=1,
        source_id=source.uid,
        sender_id="sender",
        recipient_id=None,
        role=DelegationRole.EXECUTOR,
        scope="scope",
        route=DelegationRoute.PROVIDER,
        plan=plan,
    )
    with pytest.raises(InvalidTaskState):
        delegation.observe_provider("/run", "running", None, "", None)
    delegation.request_provider(task, "scope")
    with pytest.raises(InvalidTaskState):
        delegation.observe_provider("", "completed", None, "", None)
    delegation.observe_provider("/run", "running", "native", "", None)
    with pytest.raises(InvalidTaskState):
        delegation.observe_provider("/other", "running", "native", "", None)
    with pytest.raises(InvalidTaskState):
        delegation.observe_provider("/run", "running", "another", "", None)
    delegation.observe_provider("/run", "unknown", None, "", "connection lost")
    assert delegation.native_session_id == "native"
    delegation.bind_provider_peer("codex", "native", "peer")
    with pytest.raises(InvalidTaskState):
        delegation.bind_provider_peer("codex", "native", "other")
    correction = RequestSource.create(
        "p", "s", SourceKind.CORRECTION, "cancel", corrects_id=source.uid
    )
    task.invalidate(correction, "cancelled")
    delegation.reconcile(task)
    delegation.observe_provider("/run", "completed", "native", "late actual result", None)
    assert (
        delegation.status is DelegationStatus.STOPPED
        and delegation.provider_output == "late actual result"
    )
    # 이미 끝난 프로세스의 취소는 기존 종료 관찰을 재사용한다.
    already = replace(
        delegation, stop_reason=None, stop_evidence=None, status=DelegationStatus.COMPLETED
    )
    already.reconcile(task)
    assert already.status is DelegationStatus.STOPPED and already.stop_evidence == "/run"


def test_discovery_timeout_and_stubborn_process_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    executable(
        tmp_path,
        "codex",
        "import sys,time,signal\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\nsys.stdin.readline()\ntime.sleep(30)\n",
    )
    import neurath.infrastructure.provider_protocol as protocol

    clock = iter([0, 0, 31])
    monkeypatch.setattr(protocol.time, "monotonic", lambda: next(clock, 31))
    real_wait = subprocess.Popen.wait

    def short_wait(self, timeout=None):
        return real_wait(self, timeout=0.1 if timeout is not None else None)

    monkeypatch.setattr(subprocess.Popen, "wait", short_wait)
    with pytest.raises(TimeoutError):
        discover_models("codex")


def test_policy_discovery_does_not_claim_unsupported_cli_modes(tmp_path, monkeypatch):
    import neurath.infrastructure.provider as implementation

    monkeypatch.setattr(implementation, "discover_models", lambda p: ("model",))
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="--no-daemon no policies"),
    )
    with pytest.raises(RuntimeError):
        SubprocessProviderService().discover("codex")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a, 0, stdout="--no-daemon --sandbox [possible values: unsupported]"
        ),
    )
    with pytest.raises(RuntimeError):
        SubprocessProviderService().discover("codex")


def test_start_race_recovers_winner_without_spawning_twice(provider_environment, monkeypatch):
    _, plan = provider_environment
    service = SubprocessProviderService()
    uid = str(uuid4())
    directory = service._directory(uid)
    original = Path.mkdir

    def race(self, *a, **k):
        if self == directory:
            original(self, *a, **k)
            raise FileExistsError
        return original(self, *a, **k)

    monkeypatch.setattr(Path, "mkdir", race)
    assert service.start(uid, plan, "scope").status == "unknown"
    assert not (directory / "worker.pid").exists()


def test_worker_entrypoint_and_cancel_between_spawn_and_receipt(provider_environment, monkeypatch):
    import runpy

    from neurath.infrastructure import provider_worker

    binpath, plan = provider_environment
    service = SubprocessProviderService()
    directory = service._directory(str(uuid4()))
    directory.mkdir(parents=True)
    (directory / "plan.json").write_text(
        json.dumps(
            dict(provider="claude", model=plan.model, policy="plan", directory=plan.directory)
        )
    )
    (directory / "prompt.txt").write_text("scope")
    executable(binpath, "claude", "import time\ntime.sleep(20)\n")
    original = provider_worker.process_identity

    def after_spawn(pid):
        observed = original(pid)
        (directory / "cancel.requested").touch()
        return observed

    monkeypatch.setattr(provider_worker, "process_identity", after_spawn)
    execute(directory)
    assert service.observe(directory.name).status == "stopped"
    # 모듈 진입점에서도 취소된 실행의 새 프로세스를 만들지 않는다.
    monkeypatch.setattr(sys, "argv", ["worker", str(directory)])
    with pytest.warns(RuntimeWarning, match="found in sys.modules"):
        runpy.run_module("neurath.infrastructure.provider_worker", run_name="__main__")
    assert service.observe(directory.name).status == "stopped"


def test_worker_observes_process_that_exits_during_cancel(provider_environment, monkeypatch):
    from neurath.infrastructure import provider_worker

    binpath, plan = provider_environment
    service = SubprocessProviderService()
    directory = service._directory(str(uuid4()))
    directory.mkdir(parents=True)
    (directory / "plan.json").write_text(
        json.dumps(
            dict(provider="codex", model=plan.model, policy=plan.policy, directory=plan.directory)
        )
    )
    (directory / "prompt.txt").write_text("scope")
    executable(binpath, "codex", 'print("{}")\n')

    def after_spawn(pid):
        (directory / "cancel.requested").touch()
        return "observed"

    monkeypatch.setattr(provider_worker, "process_identity", after_spawn)

    def gone(*args):
        raise ProcessLookupError

    monkeypatch.setattr(os, "killpg", gone)
    execute(directory)
    assert (directory / "result.json").exists()


def test_normal_worker_completion_preserves_tool_events_without_treating_them_as_answer(
    provider_environment,
):
    binpath, plan = provider_environment
    service = SubprocessProviderService()
    directory = service._directory(str(uuid4()))
    directory.mkdir(parents=True)
    (directory / "plan.json").write_text(
        json.dumps(
            dict(provider="codex", model=plan.model, policy=plan.policy, directory=plan.directory)
        )
    )
    (directory / "prompt.txt").write_text("scope")
    executable(
        binpath,
        "codex",
        """import json
for event in [
 {'type':'thread.started','thread_id':'actual'},
 {'type':'item.completed','item':{'type':'command_execution','text':'tool output'}},
 {'type':'item.completed','item':{'type':'agent_message','text':'actual answer'}},
 {'type':'turn.completed'},
]: print(json.dumps(event),flush=True)
""",
    )
    execute(directory)
    result = service.observe(directory.name)
    assert result.status == "completed" and result.output == "actual answer"


async def test_corrected_assignment_retains_original_request_in_peer_and_provider_input(
    database, collaboration, monkeypatch
):
    actor, sender, _, recipient, task = collaboration
    correction = (
        await call(
            database,
            "record_source",
            "RecordSource",
            task.project_id,
            actor.session.uid,
            SourceKind.CORRECTION,
            "Change only the output format",
            corrects_id=task.definition.source_id,
        )
    ).source
    task = (
        await call(
            database,
            "correct_task",
            "CorrectTask",
            task.project_id,
            actor.session.uid,
            task.uid,
            task.revision,
            correction.uid,
            required_result="Same artifact in the corrected format",
        )
    ).task
    from neurath.application.usecases.prepare_delegation import PrepareDelegationCommand

    peer = await call(
        database,
        "delegate_task",
        "DelegateTask",
        PrepareDelegationCommand(
            task.uid,
            sender.uid,
            DelegationRole.EXECUTOR,
            "Produce corrected output",
            DelegationRoute.PEER,
            recipient.uid,
        ),
    )
    message = await call(database, "read_message", "ReadMessage", peer.message_id, recipient.uid)
    assert (
        "original requirement text" in message.body
        and "Change only the output format" in message.body
    )
    prompts = []
    monkeypatch.setattr(
        SubprocessProviderService,
        "discover",
        lambda self, p: ProviderCapabilities("codex", ("model",), ("read-only",)),
    )

    def start(self, uid, plan, prompt):
        prompts.append(prompt)
        return ProviderObservation(
            "/run/" + uid, "unknown", error="fixture accepted, start unconfirmed"
        )

    monkeypatch.setattr(SubprocessProviderService, "start", start)
    plan = ProviderPlan(
        provider="codex",
        model="model",
        policy="read-only",
        directory=actor.session.working_directory,
        parent_session_id=actor.session.uid,
    )
    provider = await call(
        database,
        "delegate_task",
        "DelegateTask",
        PrepareDelegationCommand(
            task.uid,
            sender.uid,
            DelegationRole.REVIEWER,
            "Review corrected output",
            DelegationRoute.PROVIDER,
            None,
            plan,
        ),
    )
    assert provider.provider_status == "unknown"
    assert (
        "original requirement text" in prompts[0] and "Change only the output format" in prompts[0]
    )


def test_assignment_cannot_use_a_different_task_or_fabricated_provider_identity():
    from neurath.domain.aggregates.request_source import RequestSource
    from neurath.domain.aggregates.task import Task

    source = RequestSource.create("p", "s", SourceKind.PROMPT, "original")
    task = Task.create("p", "s", source, "title", "result")
    delegation = Delegation(
        uid="d",
        task_id="another-task",
        definition_number=1,
        source_id=source.uid,
        sender_id="a",
        recipient_id="b",
        role=DelegationRole.EXECUTOR,
        scope="scope",
        route=DelegationRoute.PEER,
    )
    with pytest.raises(InvalidTaskState):
        delegation.require_current(task)
    with pytest.raises(InvalidTaskState):
        delegation.bind_provider_peer("codex", "native", "b")
    planned = replace(
        delegation,
        route=DelegationRoute.PROVIDER,
        plan=ProviderPlan(
            provider="codex", model="m", policy="read-only", directory="/tmp", parent_session_id="s"
        ),
        provider_requested=True,
    )
    planned.observe_provider("/run", "completed", "native", "done", None)
    planned.observe_provider("", "unknown", None, "", "late start failure")
    assert planned.provider_status == "completed" and planned.provider_output == "done"


async def test_handoff_reuses_original_assignment_without_old_owner_or_duplicate_execution(
    database, collaboration, monkeypatch
):
    from neurath.application.ports.repositories.session import ISessionRepository
    from neurath.application.ports.repositories.task import ITaskRepository
    from neurath.application.usecases.prepare_delegation import PrepareDelegationCommand
    from neurath.domain.errors import InvalidExecutionState
    from tests.conftest import storage_scope

    actor, sender, receiver, recipient, task = collaboration
    plan = ProviderPlan(
        provider="codex",
        model="model",
        policy="read-only",
        directory=actor.session.working_directory,
        parent_session_id=actor.session.uid,
    )
    original = await prepare(
        database, collaboration, route=DelegationRoute.PROVIDER, recipient_id=None, plan=plan
    )
    async with storage_scope(database) as scope:
        session = await scope.get(ISessionRepository).get(actor.session.uid)
        session.hand_off(receiver.session, session.revision)
        await scope.get(ISessionRepository).save(session)
        stored = await scope.get(ITaskRepository).get(task.uid)
        stored.transfer(actor.session.uid, receiver.session.uid)
        await scope.get(ITaskRepository).save(stored)
    with pytest.raises(InvalidExecutionState):
        await call(database, "start_provider", "StartProvider", original.uid, sender.uid)
    with pytest.raises(InvalidExecutionState):
        await call(database, "dispatch_delegation", "DispatchDelegation", original.uid, sender.uid)
    with pytest.raises(InvalidTaskState, match="already has a root assignment"):
        await call(
            database,
            "prepare_delegation",
            "PrepareDelegation",
            **vars(
                PrepareDelegationCommand(
                    task.uid,
                    recipient.uid,
                    DelegationRole.EXECUTOR,
                    "scope",
                    DelegationRoute.PROVIDER,
                    None,
                    replace(plan, parent_session_id=receiver.session.uid),
                )
            ),
        )
    launched = []

    def start(self, uid, plan, prompt):
        launched.append(uid)
        return ProviderObservation("/run/" + uid, "running", "native-after-handoff")

    monkeypatch.setattr(SubprocessProviderService, "start", start)
    await call(database, "start_provider", "StartProvider", original.uid, recipient.uid)
    await call(database, "start_provider", "StartProvider", original.uid, recipient.uid)
    assert launched == [original.uid]
    observed = await call(
        database, "get_delegation", "GetDelegation", original.uid, sender.uid, query=True
    )
    assert observed.sender_id == sender.uid and observed.plan.parent_session_id == actor.session.uid


def test_codex_without_isolated_execution_support_is_not_advertised(monkeypatch):
    import neurath.infrastructure.provider as implementation

    monkeypatch.setattr(implementation, "discover_models", lambda p: ("model",))
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a, 0, stdout="--sandbox [possible values: read-only]"
        ),
    )
    with pytest.raises(RuntimeError, match="isolated process"):
        SubprocessProviderService().discover("codex")
