"""Reject false stock-batch proof without launching models or subprocess fixtures."""
import copy
from pathlib import Path
import importlib.util

import pytest

pytestmark = pytest.mark.fast

spec = importlib.util.spec_from_file_location(
    "stock_provider_probe", Path(__file__).parents[1] / "tools/native_wave_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
assignments, digest, verify_wave_events = probe.assignments, probe.digest, probe.verify_wave_events
EXPECTED_LINES = {name: f"# Fixture {name}" for name in ("a", "b", "c")}


def trace(include_task_list=True):
    expected = assignments([Path("/fixture/a"), Path("/fixture/b"), Path("/fixture/c")])
    claim = {"session_id": "root", "actor_id": "codex:session:root", "lease_epoch": 1,
             "fencing_token": "fixture"}
    task = {"id": "task", "status": "in_progress", "revision": 2, "definition_digest": "d" * 64}
    scope = {"session_id": "root", "actor_id": claim["actor_id"], "task_id": "task",
             "task_revision": 2, "definition_digest": "d" * 64}
    dependencies = {"a": [], "b": [], "c": ["a", "b"]}
    entries = [{"entry_id": name, "depends_on": dependencies[name], "run_id": "run-" + name
                if name != "c" else None, "status": "accepted" if name != "c" else "queued",
                "result": None, "generation": None, "result_digest": None, "consumption": None,
                "attempt": 0, "attempts": [], "original_request": {k: expected[name][k]
                    for k in ("assignment", "worktree", "provider")}} for name in expected]
    wave = {"wave_id": "wave", "owner": "codex:root", "task_scope": scope, "max_parallel": 2,
            "cancel_requested": False, "provenance": "provider-peer", "entries": entries,
            "all_succeeded": False, "states": {"a": "accepted", "b": "accepted", "c": "queued"}}
    events = []
    def emit(tool, data, **arguments):
        event = {"method": "item/completed", "params": {"threadId": "root", "turnId": "turn",
            "item": {"type": "mcpToolCall", "tool": tool, "arguments": arguments,
                     "result": {"structuredContent": {"ok": True, "result": data}}}}}
        events.append(copy.deepcopy(event))
    emit("worktree_claim", claim)
    compact_task = {key: task[key] for key in ("id", "status", "revision")}
    emit("task_start", {"all_terminal": False, "tasks": [compact_task]}, task_id="task")
    if include_task_list:
        emit("task_list", {"all_succeeded": False, "tasks": [task]})
    requests = []
    for name, request in expected.items():
        emit("provider_models", {"inventory_id": "inventory-" + name}, worktree=request["worktree"])
        emit("provider_plan", {"plan_id": "plan-" + name, "revision": 1},
             worktree=request["worktree"], assignment=request["assignment"])
        requests.append({"entry_id": name, "depends_on": dependencies[name],
                         "request": {**request, "plan_id": "plan-" + name, "plan_revision": 1}})
    emit("provider_wave_run", wave, wave_id="wave", task_id="task", expected_task_revision=2,
         max_parallel=2, entries=requests)
    for entry in entries:
        name = entry["entry_id"]
        entry["status"] = "completed"
        result = {"status": "completed", "worker_generation": 1, "run_id": entry["run_id"],
                  "implementation_dispatched": True, "execution": "native-turn-completed",
                  "created": {"provider": "codex", "worktree": expected[name]["worktree"],
                              "native_session": "native-" + name},
                  "submission": {"delivery": "submitted", "native_turn": "turn-" + name},
                  "completion": {"id": "turn-" + name, "status": "completed", "error": None},
                  "completion_link": {"native_session": "native-" + name,
                                      "submitted_turn": "turn-" + name,
                                      "completed_turn": "turn-" + name, "disposition": "terminal"},
                  "text": f"NEURATH_PROVIDER_ENTRY_{name.upper()}_OK\n{EXPECTED_LINES[name]}"}
        entry.update(result=result, generation=1, result_digest=digest(result))
        emit("provider_wave_read", wave, wave_id="wave")
        proof = {"run_id": entry["run_id"], "generation": 1,
                 "result_digest": entry["result_digest"], "verdict": "accepted"}
        entry["consumption"] = proof
        wave["states"][name] = "succeeded"
        if name == "b":
            entries[2].update(run_id="run-c", status="accepted")
        emit("provider_wave_consume", wave, wave_id="wave", entry_id=name, **proof)
    wave["all_succeeded"] = True
    emit("provider_wave_read", wave, wave_id="wave")
    emit("task_resolve", {"all_terminal": True, "tasks": [{**compact_task, "revision": 3, "status": "succeeded"}]}, task_id="task")
    emit("worktree_release", {"released": True, "claim": claim}, expected_lease_epoch=1, fencing_token="fixture")
    return events, expected


def item(event):
    return event["params"]["item"]


def data(event):
    return item(event)["result"]["structuredContent"]["result"]


@pytest.mark.parametrize("owned_followup", [False, True])
def test_stock_provider_batch_requires_consumed_dag_and_original_native_completions(owned_followup):
    events, expected = trace()
    if owned_followup:
        for event in events:
            for entry in data(event).get("entries", []):
                if entry["entry_id"] != "a" or not entry["result"]:
                    continue
                result = entry["result"]
                result["completion"]["id"] = "owned-followup-turn"
                result["completion_link"]["completed_turn"] = "owned-followup-turn"
                entry["result_digest"] = digest(result)
                if entry["consumption"]:
                    entry["consumption"]["result_digest"] = entry["result_digest"]
                if item(event)["tool"] == "provider_wave_consume" and item(event)["arguments"]["entry_id"] == "a":
                    item(event)["arguments"]["result_digest"] = entry["result_digest"]
    report = verify_wave_events(events, "root", "turn", expected, EXPECTED_LINES)
    assert report["status"] == "passed"
    assert report["run_ids"] == {name: "run-" + name for name in expected}


@pytest.mark.parametrize("change", [
    "initial-slot", "duplicate-run", "missing-read", "missing-consume", "early-dependent",
    "wrong-generation", "wrong-digest", "missing-completion", "wrong-native-turn", "missing-dispatch",
    "wrong-assignment", "wrong-worktree", "wrong-native-session", "wrong-result-run", "inbox-recovery",
    "wrong-owner", "wrong-task", "wrong-definition", "wrong-wave", "foreign-root", "foreign-turn",
    "claim-token", "missing-release", "missing-model-plan", "unresolved-task", "false-success",
    "missing-link", "link-native-session", "link-submitted-turn", "link-waiting",
    "missing-fact", "wrong-fact",
])
def test_incomplete_or_substituted_provider_evidence_is_rejected(change):
    events, expected = trace()
    run = next(e for e in events if item(e)["tool"] == "provider_wave_run")
    reads = [e for e in events if item(e)["tool"] == "provider_wave_read"]
    consume = next(e for e in events if item(e)["tool"] == "provider_wave_consume")
    entry = data(reads[0])["entries"][0]
    if change == "initial-slot":
        data(run)["entries"][1]["run_id"] = None
    elif change == "duplicate-run":
        data(run)["entries"][1]["run_id"] = data(run)["entries"][0]["run_id"]
    elif change == "missing-read":
        events.remove(reads[0])
    elif change == "missing-consume":
        events.remove(consume)
    elif change == "early-dependent":
        data(reads[0])["entries"][2]["run_id"] = "run-c"
    elif change == "wrong-generation":
        entry["generation"] = 2
    elif change == "wrong-digest":
        entry["result_digest"] = "sha256:other"
    elif change in {"missing-completion", "wrong-native-turn", "missing-dispatch", "wrong-worktree",
                    "wrong-native-session", "wrong-result-run", "inbox-recovery", "missing-link",
                    "link-native-session", "link-submitted-turn", "link-waiting"}:
        result = entry["result"]
        if change == "missing-link":
            result.pop("completion_link")
        elif change == "link-native-session":
            result["completion_link"]["native_session"] = "other-native-session"
        elif change == "link-submitted-turn":
            result["completion_link"]["submitted_turn"] = "other-submission"
        elif change == "link-waiting":
            result["completion_link"]["disposition"] = "waiting"
        elif change == "missing-completion":
            result.pop("completion")
        elif change == "wrong-native-turn":
            result["completion"]["id"] = "different-turn"
        elif change == "missing-dispatch":
            result["implementation_dispatched"] = False
        elif change == "wrong-worktree":
            result["created"]["worktree"] = "/other"
        elif change == "wrong-native-session":
            result["created"]["native_session"] = "root"
        elif change == "wrong-result-run":
            result["run_id"] = "other"
        else:
            entry["generation"] = result["worker_generation"] = 2
        entry["result_digest"] = digest(result)
    elif change in {"missing-fact", "wrong-fact"}:
        entry["result"]["text"] = "NEURATH_PROVIDER_ENTRY_A_OK"
        if change == "wrong-fact":
            entry["result"]["text"] += "\n# Incorrect source line"
        entry["result_digest"] = digest(entry["result"])
    elif change == "wrong-assignment":
        entry["original_request"]["assignment"] = "Different assignment"
    elif change == "wrong-owner":
        data(reads[0])["owner"] = "codex:other"
    elif change == "wrong-task":
        data(run)["task_scope"]["task_id"] = "other"
    elif change == "wrong-definition":
        data(run)["task_scope"]["definition_digest"] = "e" * 64
    elif change == "wrong-wave":
        data(reads[0])["wave_id"] = "other"
    elif change == "foreign-root":
        reads[0]["params"]["threadId"] = "other"
    elif change == "foreign-turn":
        reads[0]["params"]["turnId"] = "other"
    elif change == "claim-token":
        item(events[-1])["arguments"]["fencing_token"] = "other"
    elif change == "missing-release":
        events.pop()
    elif change == "missing-model-plan":
        events.remove(next(e for e in events if item(e)["tool"] == "provider_plan"))
    elif change == "unresolved-task":
        data(events[-2])["tasks"][0]["status"] = "failed"
    else:
        data(reads[-1])["states"]["c"] = "failed"
    with pytest.raises((AssertionError, KeyError)):
        verify_wave_events(events, "root", "turn", expected, EXPECTED_LINES)


def test_expected_source_line_ignores_html_and_preserves_source(tmp_path):
    (tmp_path / "README.md").write_text("<h1>HTML heading</h1>\nplain text\n# Exact source  \n## Later\n")
    assert probe.expected_source_lines({"a": {"worktree": str(tmp_path)}}) == {"a": "# Exact source  "}


@pytest.mark.parametrize("rendered", ["# Fixture a", "`# Fixture a`",
                                       "NEURATH_PROVIDER_ENTRY_A_OK — `# Fixture a`"])
def test_requested_source_fact_accepts_plain_or_inline_code_line(rendered):
    events, expected = trace()
    entry = data(next(e for e in events if item(e)["tool"] == "provider_wave_read"))["entries"][0]
    entry["result"]["text"] = "NEURATH_PROVIDER_ENTRY_A_OK\n" + rendered
    entry["result_digest"] = digest(entry["result"])
    probe._completion(entry, expected["a"], {"root": "root"}, EXPECTED_LINES["a"])


def test_compact_task_mutations_preserve_exact_task_and_wave_scope():
    events, expected = trace(include_task_list=False)
    result = verify_wave_events(events, "root", "turn", expected, EXPECTED_LINES)
    assert result["definition_observation"] == "wave-admission"
    assert result["definition_digest"] == "d" * 64


def test_full_task_list_independently_binds_definition():
    events, expected = trace()
    result = verify_wave_events(events, "root", "turn", expected, EXPECTED_LINES)
    assert result["definition_observation"] == "task-ledger"


def test_all_terminal_does_not_substitute_for_task_success():
    events, expected = trace(include_task_list=False)
    data(events[-2])["tasks"][0]["status"] = "failed"
    with pytest.raises(AssertionError):
        verify_wave_events(events, "root", "turn", expected, EXPECTED_LINES)


@pytest.mark.parametrize("rendered", ["# Fixture a extra", "`# Fixture a extra`", "prefix # Fixture a suffix"])
def test_source_fact_rejects_only_substring_match(rendered):
    events, expected = trace()
    entry = data(next(e for e in events if item(e)["tool"] == "provider_wave_read"))["entries"][0]
    entry["result"]["text"] = "NEURATH_PROVIDER_ENTRY_A_OK\n" + rendered
    entry["result_digest"] = digest(entry["result"])
    with pytest.raises(AssertionError):
        probe._completion(entry, expected["a"], {"root": "root"}, EXPECTED_LINES["a"])
