"""Verify an installed provider DAG through an explicitly selected stock Codex.

The caller supplies the distribution's verified executable SHA and three distinct,
installed, clean worker worktrees. This probe records executable identity; it does
not establish vendor provenance from a self-computed hash. Evidence stays local.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess



def digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def executable_receipt(executable, expected_sha256):
    executable = Path(executable).resolve(strict=True)
    assert executable.is_file() and executable.name == "codex"
    actual = hashlib.sha256(executable.read_bytes()).hexdigest()
    assert actual == expected_sha256, "Executable does not match caller-verified distribution SHA"
    version = subprocess.run([str(executable), "--version"], check=True,
                             capture_output=True, text=True).stdout.strip()
    assert version
    return {"path": str(executable), "sha256": actual, "version": version,
            "provenance": "caller-verified distribution; not independently vendor-attested"}


def assignments(worktrees):
    return {name: {"provider": "codex", "worktree": str(path), "mode": "inherit",
        "assignment": (
            f"Authorized provider batch regression entry {name}. Inspect the existing README "
            "and report its first heading. Do not edit repository files or start children. "
            "Record and resolve only this assignment's task with the observed fact, display "
            "native TODO, and release your exact owned worktree claim. "
            f"Finish with NEURATH_PROVIDER_ENTRY_{name.upper()}_OK and the heading.")}
        for name, path in zip(("a", "b", "c"), worktrees, strict=True)}


def controller_prompt(expected):
    return (
        "Run an authorized Neurath stock provider batch regression. The caller has released "
        "its root claim. Check session_status and task_list, acquire the unclaimed root through "
        "worktree_claim; never force takeover. Define/start one task whose goal is to verify "
        "runtime-owned parallel provider dispatch and consumed-result DAG ordering. Use "
        "current named MCP schemas and returned identifiers/revisions. Display returned native "
        "TODO. Do not edit repository files, change trust/settings, create phase workflows, "
        "spawn native children, or call provider_run directly. The already prepared worker "
        "worktrees are distinct installed clean checkouts. Use provider_models then "
        "provider_plan for each exact target/assignment; reuse the observed model catalog "
        "where supported. Choose the smallest available capable model and record the actual "
        "plan; permission mode must remain inherit. Call provider_wave_run ONCE with "
        "max_parallel=2 and entries a,b independent; c depends_on=[a,b]. capacity_basis is "
        "two authorized isolated worker slots. Add real plan_id/plan_revision and matching "
        "model/reasoning fields to these exact request scopes: " + json.dumps(expected) + ". "
        "Retain wave_id, task_id/revision and the actual run IDs. The initial response must "
        "reserve both a and b and leave c without a run. Wait for native result messages, "
        "not a polling loop. After each completion event read provider_wave_read, inspect "
        "the actual result and verify implementation_dispatched, original generation 1, "
        "a terminal completion_link joining native session, submitted turn and completed "
        "turn (an owned inbox followup can differ), and the entry's marker/README fact. Consume "
        "each exact run/generation/result_digest with verdict accepted only after success. "
        "Read the wave after both are consumed: c must now have a distinct run. Wait for "
        "c's native completion, inspect and consume it the same way, then read the wave "
        "to prove all_succeeded. Resolve the root task from these observations; display "
        "native TODO; release the exact observed lease/token and finish "
        "NEURATH_STOCK_PROVIDER_WAVE_OK. Do not recover or retry inside this regression. "
        "On a concrete failure retain unfinished task evidence, cancel only this owned "
        "wave through its named tool if it exists, report the exact prerequisite, and "
        "release only your own claim when the lifecycle permits. Never invent receipts."
    )


def _completion(entry, expected, native_sessions):
    result = entry["result"]
    assert entry["status"] == result["status"] == "completed"
    assert entry["generation"] == result["worker_generation"] == 1
    assert result["run_id"] == entry["run_id"]
    assert entry["result_digest"] == digest(result)
    assert result["implementation_dispatched"] is True
    assert result["execution"] == "native-turn-completed"
    assert result["created"]["provider"] == "codex"
    assert result["created"]["worktree"] == expected["worktree"]
    native = result["created"]["native_session"]
    assert native and native != native_sessions["root"]
    previous = native_sessions.setdefault(entry["entry_id"], native)
    assert previous == native and len(set(native_sessions.values())) == len(native_sessions)
    assert result["submission"]["delivery"] == "submitted"
    assert result["submission"]["native_turn"]
    assert result["completion_link"] == {
        "native_session": native,
        "submitted_turn": result["submission"]["native_turn"],
        "completed_turn": result["completion"]["id"],
        "disposition": "terminal",
    }
    assert result["completion"]["id"] and result["completion"]["status"] == "completed"
    assert result["completion"].get("error") is None
    assert f"NEURATH_PROVIDER_ENTRY_{entry['entry_id'].upper()}_OK" in result["text"]


def verify_wave_events(events, thread, turn, expected):
    """Verify actual named-tool results, never assistant prose or synthetic hook denials."""
    claim = task = scope = wave_id = initial = resolved = released = success = None
    runs, consumed, completions, plans = {}, {}, {}, set()
    inventories = set()
    native_sessions = {"root": thread}
    dependencies = {"a": [], "b": [], "c": ["a", "b"]}
    assert set(expected) == set(dependencies)
    assert len({value["worktree"] for value in expected.values()}) == 3
    for index, event in enumerate(events):
        params = event.get("params", {})
        if params.get("threadId") != thread or params.get("turnId") != turn:
            continue
        item = params.get("item", {})
        if event.get("method") != "item/completed" or item.get("type") != "mcpToolCall":
            continue
        envelope = (item.get("result") or {}).get("structuredContent", {})
        if envelope.get("ok") is not True:
            continue
        data, args, tool = envelope.get("result", {}), item.get("arguments", {}), item.get("tool")
        if tool == "worktree_claim":
            assert claim is None and data["session_id"] == thread
            assert data["actor_id"] and data["fencing_token"] and data["lease_epoch"] > 0
            claim = data
        elif tool == "task_start":
            assert task is None
            active = [value for value in data["tasks"] if value["status"] == "in_progress"]
            assert len(active) == 1 and active[0]["id"] == args["task_id"]
            task = active[0]
        elif tool == "provider_models":
            inventories.add(args["worktree"])
        elif tool == "provider_plan":
            assert args["worktree"] in inventories
            plans.add((data["plan_id"], data["revision"], args["worktree"], args["assignment"]))
        if tool not in {"provider_wave_run", "provider_wave_read", "provider_wave_consume"}:
            if tool == "task_resolve" and task and args.get("task_id") == task["id"]:
                assert success is not None and data["all_succeeded"] is True
                matched = [value for value in data["tasks"] if value["id"] == task["id"]]
                assert len(matched) == 1 and matched[0]["status"] == "succeeded"
                resolved = index
            if tool == "worktree_release":
                assert resolved is not None and data["released"] is True and data["claim"] == claim
                assert args["expected_lease_epoch"] == claim["lease_epoch"]
                assert args["fencing_token"] == claim["fencing_token"]
                released = index
            continue
        if tool == "provider_wave_run":
            assert initial is None and claim and task
            assert args["task_id"] == task["id"] and args["expected_task_revision"] == task["revision"]
            assert args["max_parallel"] == 2
            assert len(args["entries"]) == 3
            for entry in args["entries"]:
                name, request = entry["entry_id"], entry["request"]
                assert name in expected and entry["depends_on"] == dependencies[name]
                assert all(request.get(key) == value for key, value in expected[name].items())
                assert (request["plan_id"], request["plan_revision"], request["worktree"],
                        request["assignment"]) in plans
            assert {entry["entry_id"] for entry in args["entries"]} == set(expected)
            wave_id, scope, initial = args["wave_id"], data["task_scope"], index
            assert scope["session_id"] == thread and scope["actor_id"] == claim["actor_id"]
            assert scope["task_id"] == task["id"] and scope["task_revision"] == task["revision"]
            assert scope["definition_digest"] == task["definition_digest"]
        assert initial is not None and args["wave_id"] == data["wave_id"] == wave_id
        assert data["owner"] == "codex:" + thread and data["task_scope"] == scope
        assert data["max_parallel"] == 2 and data["cancel_requested"] is False
        assert data["provenance"] == "provider-peer"
        assert len(data["entries"]) == 3
        entries = {entry["entry_id"]: entry for entry in data["entries"]}
        assert set(entries) == set(expected)
        # A consume response may contain the dependent reservation it just unlocked.
        if tool == "provider_wave_consume":
            name = args["entry_id"]
            assert name in completions and name not in consumed
            entry = entries[name]
            proof = {key: args[key] for key in ("run_id", "generation", "result_digest", "verdict")}
            assert proof["verdict"] == "accepted" and entry["consumption"] == proof
            assert tuple(proof[key] for key in ("run_id", "generation", "result_digest")) == completions[name]
            consumed[name] = proof
        for name, entry in entries.items():
            assert entry["depends_on"] == dependencies[name]
            assert entry["original_request"] == {key: expected[name][key]
                                                 for key in ("assignment", "provider", "worktree")}
            assert entry.get("attempt", 0) == 0 and not entry.get("attempts")
            if index == initial:
                assert bool(entry["run_id"]) is (name in {"a", "b"})
            if entry["run_id"]:
                assert all(dependency in consumed for dependency in dependencies[name])
                assert runs.setdefault(name, entry["run_id"]) == entry["run_id"]
                assert len(set(runs.values())) == len(runs)
            if entry["status"] == "completed":
                _completion(entry, expected[name], native_sessions)
                completions[name] = (entry["run_id"], entry["generation"], entry["result_digest"])
            if entry["consumption"]:
                assert entry["consumption"] == consumed.get(name)
        if tool == "provider_wave_read" and data.get("all_succeeded") is True:
            assert set(consumed) == set(expected)
            assert data["states"] == {name: "succeeded" for name in expected}
            success = index
    assert initial is not None and success is not None and resolved is not None and released is not None
    assert initial < success < resolved < released and set(runs) == set(expected)
    return {"status": "passed", "thread": thread, "turn": turn, "wave_id": wave_id,
            "task_id": task["id"], "run_ids": runs, "native_sessions": native_sessions,
            "evidence": ["events.jsonl", "hooks.json", "completion.json", "executable.json"]}


def probe(project, output, executable, model, worktrees, expected_sha256):
    from native_steering_probe import Host

    assert len(worktrees) == len(set(worktrees)) == 3 and project not in worktrees
    output.mkdir(parents=True, exist_ok=False)
    receipt = executable_receipt(executable, expected_sha256)
    (output / "executable.json").write_text(json.dumps(receipt, indent=2))
    expected = assignments(worktrees)
    (output / "assignments.json").write_text(json.dumps(expected, indent=2))
    # Provider workers resolve `codex` from PATH. Pin that lookup to the same
    # verified stock distribution without editing global or project settings.
    old_path = os.environ.get("PATH")
    os.environ["PATH"] = str(Path(receipt["path"]).parent) + os.pathsep + (old_path or "")
    try:
        host = Host(project, output, receipt["path"])
    finally:
        if old_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = old_path
    report = {"status": "running", "executable": receipt}
    try:
        hooks = host.request("hooks/list", {"cwds": [str(project), *map(str, worktrees)]})
        (output / "hooks.json").write_text(json.dumps(hooks, indent=2))
        assert len(hooks["data"]) == 4
        for target in hooks["data"]:
            assert target["hooks"] and all(h["trustStatus"] == "trusted" and h["enabled"]
                                           for h in target["hooks"])
        thread = host.request("thread/start", {"cwd": str(project), "model": model,
            "approvalPolicy": "never", "sandbox": "danger-full-access",
            "config": {"features.code_mode": True, "features.code_mode_host": True}})["thread"]["id"]
        turn = host.request("turn/start", {"threadId": thread,
            "input": [{"type": "text", "text": controller_prompt(expected)}]})["turn"]["id"]
        report.update(thread=thread, turn=turn)
        print(json.dumps(report), flush=True)
        end = host.wait(lambda e: e.get("method") == "turn/completed"
            and e.get("params", {}).get("threadId") == thread
            and e.get("params", {}).get("turn", {}).get("id") == turn, timeout=1200)
        (output / "completion.json").write_text(json.dumps(end, indent=2))
        assert end["params"]["turn"]["status"] == "completed", end
        assert executable_receipt(executable, expected_sha256) == receipt
        report.update(verify_wave_events(host.events, thread, turn, expected))
    except Exception as error:
        report.update(status="failed", error=repr(error))
        raise
    finally:
        (output / "report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)
        host.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--codex-bin", type=Path, required=True)
    parser.add_argument("--expected-codex-sha256", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--worker-worktree", type=Path, action="append", required=True)
    args = parser.parse_args()
    probe(args.project.resolve(), args.output.resolve(), args.codex_bin.resolve(), args.model,
          [path.resolve() for path in args.worker_worktree], args.expected_codex_sha256)
