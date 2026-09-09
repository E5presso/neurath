"""Native TODO receipts require exact coverage and cannot resolve work."""
import copy
import json

import pytest

pytest_plugins = ["tests.test_task_ledger_service", "tests.test_agent_hooks"]


def event(store, kernel, sk, payload, succeeded=None):
    from scripts.agent_harness.task_todo import record
    with store.database.transaction() as tx:
        process = store.session_store.read_transaction(tx, sk.SessionId("one"))
        return record(tx, process, sk.ActorId("owner"), "codex", payload, succeeded=succeeded)


def payload(result):
    return {"tool_name": result["native_todo"]["tool"], "tool_input": result["native_todo"]["arguments"],
            "tool_use_id": "todo-one"}


def test_native_todo_exact_pair_preserves_task_truth_and_rejects_substitution(service):
    from tests.test_task_ledger_service import item
    from scripts.agent_harness.task_ledger import TaskLedgerError
    store, kernel, sk = service
    defined = store.define([item()], expected_revision=0, key="define")
    request = payload(defined)
    assert event(store, kernel, sk, request)
    wrong = copy.deepcopy(request)
    wrong["tool_input"]["plan"][0]["status"] = "completed"
    with pytest.raises(TaskLedgerError):
        event(store, kernel, sk, wrong, True)
    assert event(store, kernel, sk, request, True)
    assert event(store, kernel, sk, request, True)
    current = store.list()
    assert current["revision"] == defined["revision"]
    assert current["tasks"] == defined["tasks"]
    assert current["native_todo"]["availability"] == "observed-supported"


def test_native_todo_old_success_cannot_cover_new_task_revision(service):
    from tests.test_task_ledger_service import item
    from scripts.agent_harness.task_todo import require_current
    from scripts.agent_harness.task_service import read_ledger
    from scripts.agent_harness.task_ledger import TaskLedgerError
    store, kernel, sk = service
    request = payload(store.define([item()], expected_revision=0, key="define"))
    event(store, kernel, sk, request)
    store.define([item("later")], expected_revision=1, key="append")
    event(store, kernel, sk, request, True)
    with store.database.transaction() as tx:
        process = store.session_store.read_transaction(tx, sk.SessionId("one"))
        _, ledger = read_ledger(tx, process)
        with pytest.raises(TaskLedgerError, match="stale"):
            require_current(tx, process, ledger)
        assert json.loads(tx.get("task-todo-attempt:one", "todo-one").payload)["status"] == "stale"


def test_native_todo_unobserved_support_is_not_invented(service):
    from scripts.agent_harness.task_todo import require_current
    from scripts.agent_harness.task_service import read_ledger
    store, kernel, sk = service
    assert store.list()["native_todo"]["availability"] == "unobserved"
    assert not event(store, kernel, sk, {"tool_name": "update_plan", "tool_input": {"plan": []}})
    with store.database.transaction() as tx:
        process = store.session_store.read_transaction(tx, sk.SessionId("one"))
        _, ledger = read_ledger(tx, process)
        require_current(tx, process, ledger)


def test_terminal_task_stop_requires_current_observed_todo_submission(service):
    from tests.test_task_ledger_service import item, _terminal_fixture
    from scripts.agent_harness.task_service import require_settled_tasks
    from scripts.agent_harness.task_ledger import TaskLedgerError
    store, kernel, sk = service
    store.define([item()], expected_revision=0, key="define")
    _terminal_fixture(store, kernel, sk)
    request = payload(store.list())
    event(store, kernel, sk, request)
    with store.database.transaction() as tx:
        process = store.session_store.read_transaction(tx, sk.SessionId("one"))
        with pytest.raises(TaskLedgerError, match="TODO"):
            require_settled_tasks(tx, process)
    event(store, kernel, sk, request, True)
    with store.database.transaction() as tx:
        process = store.session_store.read_transaction(tx, sk.SessionId("one"))
        require_settled_tasks(tx, process)


def test_native_todo_both_host_hook_routes_record_matching_submission(sessions):
    from tests.test_workflow_tasks import call
    from tests.test_task_ledger_service import item
    from neurath.runtime.database import RuntimeDatabase
    root, invoke = sessions
    for host, session in (("codex", "api"), ("claude-code", "ui")):
        defined = call(sessions, "task_define", {"tasks": [item()], "expected_revision": 0,
            "key": "define-todo"}, host=host, session=session)
        todo = defined["native_todo"]
        request = dict(tool_name=todo["tool"], tool_input=todo["arguments"], tool_use_id="native-todo")
        code, _, diagnostic = invoke(host, session, "PreToolUse", **request)
        assert code == 0, diagnostic
        code, _, diagnostic = invoke(host, session, "PostToolUse", **request,
                                    tool_response={"success": True})
        assert code == 0, diagnostic
        current = call(sessions, "task_list", {}, host=host, session=session)
        assert current["native_todo"]["availability"] == "observed-supported"
        assert current["tasks"] == defined["tasks"]
        with RuntimeDatabase(root).transaction() as tx:
            receipt = json.loads(tx.get(f"task-todo-attempt:{session}", "native-todo").payload)
        assert receipt["status"] == "current"


@pytest.mark.parametrize("failure", [{"success": False}, {"isError": True}])
def test_native_todo_explicit_failure_never_records_current_publication(sessions, failure):
    from tests.test_workflow_tasks import call
    from tests.test_task_ledger_service import item
    from neurath.runtime.database import RuntimeDatabase
    root, invoke = sessions
    for host, session in (("codex", "api"), ("claude-code", "ui")):
        defined = call(sessions, "task_define", {"tasks": [item()], "expected_revision": 0,
            "key": "define-failed-todo"}, host=host, session=session)
        todo = defined["native_todo"]
        request = dict(tool_name=todo["tool"], tool_input=todo["arguments"], tool_use_id="failed-native-todo")
        assert invoke(host, session, "PreToolUse", **request)[0] == 0
        code, _, diagnostic = invoke(host, session, "PostToolUse", **request, tool_response=failure)
        assert code == 0, diagnostic
        with RuntimeDatabase(root).transaction() as tx:
            receipt = json.loads(tx.get(f"task-todo-attempt:{session}", "failed-native-todo").payload)
        assert receipt["status"] == "failed" and receipt["outcome"] == "failed"
        current = call(sessions, "task_list", {}, host=host, session=session)
        assert current["tasks"] == defined["tasks"]
