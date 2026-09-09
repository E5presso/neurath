"""Mandatory project checks survive material bookkeeping and host Stop retries."""

import hashlib
import json
import subprocess

import pytest


@pytest.fixture
def obligation_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".neurath/local/\n.validation/\n")
    (tmp_path / ".neurath").mkdir()
    (tmp_path / ".neurath/project.json").write_text(json.dumps({"verification": {
        "check": {"argv": ["true"], "cwd": ".", "success_codes": [0]}}}))
    return tmp_path


def ledger(root):
    from neurath.runtime.verification_obligations import VerificationObligations
    return VerificationObligations(root)


def register(root, batch="edit", path="source.py"):
    from neurath.runtime.engine import activate
    activate()
    from scripts.agent_harness.material_action import material_observable_digest
    target = root / path
    ledger(root).register("codex", "session", "actor", batch, [{
        "observable_id": str(target), "baseline_digest": material_observable_digest(target),
        "expected_delta": "changed" if target.exists() else "created"}])
    return target


def receipt(root, **updates):
    from neurath.runtime.verification import fingerprint
    config = json.loads((root / ".neurath/project.json").read_text())["verification"]["check"]
    return {"status": "passed", "before_fingerprint": fingerprint(root),
        "after_fingerprint": fingerprint(root), "worktree_changed": False,
        "config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "timed_out": False, "exit_code": 0, **updates}


def pending(root):
    return ledger(root).pending("codex", "session", "actor")


def test_source_change_registers_verification_obligation(obligation_repo):
    root = obligation_repo
    register(root).write_text("changed")
    assert pending(root)[0]["reason"] == "verification-required"


def test_later_batch_preserves_unsettled_verification(obligation_repo):
    root = obligation_repo
    register(root).write_text("changed")
    register(root, "bookkeeping", ".validation/report.txt")
    assert len(pending(root)) == 1


def test_exact_verification_receipt_settles_obligation(obligation_repo):
    root = obligation_repo
    register(root).write_text("changed")
    ledger(root).verified("codex", "session", "actor", "check", receipt(root))
    assert pending(root) == []
    (root / "source.py").write_text("later change")
    assert pending(root)


def test_staging_after_verification_does_not_reopen_debt(obligation_repo):
    root = obligation_repo
    register(root).write_text("changed")
    ledger(root).verified("codex", "session", "actor", "check", receipt(root))
    subprocess.run(["git", "-C", str(root), "add", "source.py"], check=True)
    assert pending(root) == []


def test_change_after_runner_before_recording_is_not_certified(obligation_repo):
    root = obligation_repo
    target = register(root)
    target.write_text("checked")
    proof = receipt(root)
    target.write_text("not checked")
    ledger(root).verified("codex", "session", "actor", "check", proof)
    assert pending(root)


def test_stale_or_wrong_verification_cannot_settle(obligation_repo):
    root = obligation_repo
    register(root).write_text("changed")
    for check, updates in [("other", {}), ("check", {"status": "failed"}),
            ("check", {"timed_out": True}), ("check", {"worktree_changed": True}),
            ("check", {"config_sha256": "0" * 64}), ("check", {"before_fingerprint": "0" * 64})]:
        ledger(root).verified("codex", "session", "actor", check, receipt(root, **updates))
        assert pending(root), (check, updates)


def test_checkpoint_cannot_settle_verification(obligation_repo):
    from neurath.memory.store import ProjectMemory
    root = obligation_repo
    register(root).write_text("changed")
    ProjectMemory(root).checkpoint("codex", "session", "checkpoint", summary="done", status="completed")
    assert pending(root)


def test_readonly_and_denied_no_effect_need_no_verification(obligation_repo):
    root = obligation_repo
    assert pending(root) == []
    register(root)
    assert pending(root) == []


def test_missing_binding_and_changed_config_remain_pending(obligation_repo):
    root = obligation_repo
    register(root).write_text("changed")
    ledger(root).verified("codex", "session", "actor", "check", receipt(root))
    (root / ".neurath/project.json").write_text('{"verification": {}}')
    assert pending(root)[0]["reason"] == "verification-unbound"


def test_ignored_artifacts_and_foreign_actor_do_not_settle_source(obligation_repo):
    root = obligation_repo
    (root / ".validation").mkdir()
    register(root, "report", ".validation/report.txt").write_text("report")
    assert pending(root) == []
    register(root).write_text("changed")
    ledger(root).verified("codex", "session", "other-actor", "check", receipt(root))
    assert pending(root)


def test_replayed_registration_preserves_original_baseline(obligation_repo):
    root = obligation_repo
    path = register(root)
    path.write_text("changed")
    register(root)
    assert pending(root)


pytest_plugins = ["tests.test_agent_hooks", "tests.test_stop_contract"]


def test_named_material_prepare_registers_before_edit(sessions):
    from tests.test_workflow_tasks import call
    root = sessions[0]
    call(sessions, "worktree_claim", {})
    result = call(sessions, "material_prepare", {"batch_id": "implementation", "kind": "local-mutation",
        "targets": ["implementation.py"], "expectations": [{"observable_id": "implementation.py",
        "expected_delta": "created"}], "key": "implementation"})
    (root / "implementation.py").write_text("changed")
    assert ledger(root).pending("codex", "api", result["actor_id"])


def test_rejected_prepare_does_not_register_phantom_debt(sessions):
    from tests.test_workflow_tasks import call
    root = sessions[0]
    call(sessions, "worktree_claim", {})
    def prepare(batch, path):
        return call(sessions, "material_prepare", {"batch_id": batch, "kind": "local-mutation",
            "targets": [path], "expectations": [{"observable_id": path, "expected_delta": "created"}],
            "key": batch}, invocation=batch)
    first = prepare("first", "first.py")
    with pytest.raises(ValueError):
        prepare("rejected", "rejected.py")
    (root / "rejected.py").write_text("unrelated later file")
    assert ledger(root).pending("codex", "api", first["actor_id"]) == []


def test_reused_batch_name_preserves_new_sequence_targets(sessions):
    from tests.test_workflow_tasks import call
    root = sessions[0]
    call(sessions, "worktree_claim", {})
    for index, batch in enumerate(("edit", "middle", "edit")):
        prepared = call(sessions, "material_prepare", {"batch_id": batch, "kind": "local-mutation",
            "targets": [f"target{index}.py"], "expectations": [{"observable_id": f"target{index}.py",
            "expected_delta": "created"}], "key": f"prepare-{index}"}, invocation=f"prepare-{index}")
        call(sessions, "material_resolve", {"batch_id": batch, "expected_revision": prepared["revision"],
            "resolution": "aborted", "key": f"abort-{index}"}, invocation=f"abort-{index}")
    (root / "target2.py").write_text("changed after latest preparation")
    debts = ledger(root).pending("codex", "api", prepared["actor_id"])
    assert len(debts) == 1 and debts[0]["batch"] == "3:edit"


def _stop_prioritizes_verification_and_preserves_debt(stop_runtime, monkeypatch, host):
    from neurath.hosts.identity import _state
    from neurath.memory import hooks as memory
    root, send = stop_runtime
    assert send(host, "SessionStart", source="startup")[0] == 0
    assert send(host, "UserPromptSubmit", prompt="Implement and verify")[0] == 0
    state = _state(root, "root")
    ledger(root).register(host, "root", state.session.root_actor_id, "source", [{
        "observable_id": str(root / "source.py"), "baseline_digest": None, "expected_delta": "created"}])
    (root / "source.py").write_text("partial")
    monkeypatch.setattr(memory, "checkpoint_request", lambda *_: "Save the missing handoff")
    code, output, diagnostic = send(host, "Stop", stop_hook_active=False)
    assert code == 0 and output.get("decision") == "block", diagnostic
    assert output["reason"].index("verification") < output["reason"].index("handoff")
    code, output, diagnostic = send(host, "Stop", stop_hook_active=True)
    assert code == 0 and output.get("decision") == "block", diagnostic
    assert ledger(root).pending(host, "root", state.session.root_actor_id)
    assert _state(root, "root").foreground_turns[state.session.root_actor_id].status.value == "active"


def test_codex_stop_prioritizes_verification_and_preserves_debt(stop_runtime, monkeypatch):
    _stop_prioritizes_verification_and_preserves_debt(stop_runtime, monkeypatch, "codex")


def test_claude_stop_prioritizes_verification_and_preserves_debt(stop_runtime, monkeypatch):
    _stop_prioritizes_verification_and_preserves_debt(stop_runtime, monkeypatch, "claude-code")
