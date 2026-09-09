"""The typed session kernel stores canonical snapshots in project SQLite."""
from concurrent.futures import ThreadPoolExecutor

import pytest


@pytest.fixture
def session_types():
    from neurath.runtime.engine import activate
    activate()
    from scripts.agent_harness import session_kernel as sk
    return sk


def start(sk, root, session="one"):
    kernel = sk.SessionKernel(sk.SessionLocator(root))
    state = kernel.apply(sk.SessionStarted(
        session_id=sk.SessionId(session), resume_id=sk.ResumeId("resume-" + session),
        runtime=sk.SessionRuntime.CODEX, root_actor_id=sk.ActorId("root-" + session),
        idempotency_key="start-" + session))
    return kernel, state


def test_sessions_share_database_without_process_json(tmp_path, session_types):
    sk = session_types
    kernel, first = start(sk, tmp_path)
    _, second = start(sk, tmp_path, "two")
    assert (tmp_path / ".neurath/local/runtime.sqlite3").is_file()
    assert not sk.SessionLocator(tmp_path).locate(first.session.id).process_state.exists()
    assert kernel.inspect(first.session.id).to_payload() == first.to_payload()
    assert kernel.inspect(second.session.id).to_payload() == second.to_payload()
    with pytest.raises(sk.SessionNotFound):
        kernel.inspect(sk.SessionId("absent"))


def test_sqlite_session_concurrent_reducers_preserve_all_actors(tmp_path, session_types):
    sk = session_types
    kernel, first = start(sk, tmp_path)

    def add(number):
        return kernel.apply(sk.ActorStarted(session_id=first.session.id,
            actor_id=sk.ActorId("child-" + str(number)), parent_actor_id=first.session.root_actor_id,
            kind=sk.ActorKind.SUBAGENT, idempotency_key="child-" + str(number)))

    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(add, range(8)))
    current = kernel.inspect(first.session.id)
    assert len(current.actors) == 9
    assert current.revision == 8


def test_sqlite_session_failed_commit_preserves_previous_snapshot(tmp_path, session_types):
    sk = session_types
    kernel, first = start(sk, tmp_path)

    def interrupted(stage):
        raise RuntimeError("commit interrupted")

    store = sk.SessionStateStore(sk.SessionLocator(tmp_path).locate(first.session.id).process_state,
                                commit_observer=interrupted)
    with pytest.raises(RuntimeError, match="commit interrupted"):
        store.transact(sk.ActorStarted(session_id=first.session.id, actor_id=sk.ActorId("child"),
            parent_actor_id=first.session.root_actor_id, kind=sk.ActorKind.SUBAGENT,
            idempotency_key="child"))
    assert kernel.inspect(first.session.id).to_payload() == first.to_payload()


def test_sqlite_session_retention_collects_once_and_preserves_other_sessions(tmp_path, session_types):
    sk = session_types
    from scripts.agent_harness.session_retention import (
        ActiveSessionRetentionError, SessionRetentionManager,
    )
    from scripts.agent_harness.state_handle import RuntimeIdentityBinding, StateHandle

    kernel, first = start(sk, tmp_path)
    _, other = start(sk, tmp_path, "two")
    locator = sk.SessionLocator(tmp_path)
    manager = SessionRetentionManager(locator, retention_seconds=0, clock=lambda: float("inf"))
    with pytest.raises(ActiveSessionRetentionError):
        manager.collect_expired(first.session.id)
    handle = StateHandle.attach(locator, RuntimeIdentityBinding(runtime=sk.SessionRuntime.CODEX,
        session_id=first.session.id, actor_id=first.session.root_actor_id,
        root_actor_id=first.session.root_actor_id))
    manager.end(handle, idempotency_key="end")
    assert manager.collect_expired(first.session.id)
    assert not manager.collect_expired(first.session.id)
    with pytest.raises(sk.SessionNotFound):
        kernel.inspect(first.session.id)
    assert kernel.inspect(other.session.id).to_payload() == other.to_payload()


def test_sqlite_session_import_retains_revision_and_rejects_changed_legacy_writer(tmp_path, session_types):
    import json
    sk = session_types
    from scripts.agent_harness.runtime_database import LegacyStateChanged

    old = tmp_path / "old"
    old.mkdir()
    _, first = start(sk, old)
    target = tmp_path / "target"
    target.mkdir()
    locator = sk.SessionLocator(target)
    path = locator.locate(first.session.id).process_state
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(first.to_payload()))
    kernel = sk.SessionKernel(locator)
    assert kernel.inspect(first.session.id).to_payload() == first.to_payload()
    payload = first.to_payload()
    payload["revision"] += 1
    path.write_text(json.dumps(payload))
    with pytest.raises(sk.InvalidSessionState) as caught:
        kernel.inspect(first.session.id)
    assert isinstance(caught.value.__cause__, LegacyStateChanged)


def test_sqlite_transaction_reads_exact_session_authority(tmp_path, session_types):
    sk = session_types
    from scripts.agent_harness.runtime_database import RuntimeDatabase
    _, first = start(sk, tmp_path)
    store = sk.SessionStateStore(sk.SessionLocator(tmp_path).locate(first.session.id).process_state)
    with RuntimeDatabase(tmp_path).transaction() as tx:
        assert store.read_transaction(tx, first.session.id).to_payload() == first.to_payload()
        tx.put("task-ledger", str(first.session.id), b"pending", expected_revision=None)
        with pytest.raises(sk.InvalidSessionState, match="identity"):
            store.read_transaction(tx, sk.SessionId("other"))
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    with RuntimeDatabase(foreign).transaction() as tx:
        with pytest.raises(sk.InvalidSessionState, match="another project"):
            store.read_transaction(tx, first.session.id)


def test_sqlite_artifacts_preserve_digest_and_session_isolation(tmp_path, session_types):
    sk = session_types
    from scripts.agent_harness.artifact_store import ArtifactNotFound, SessionArtifactStore
    from scripts.agent_harness.state_handle import RuntimeIdentityBinding, StateHandle

    def artifacts(session):
        _, state = start(sk, tmp_path, session)
        handle = StateHandle.attach(sk.SessionLocator(tmp_path), RuntimeIdentityBinding(
            runtime=sk.SessionRuntime.CODEX, session_id=state.session.id,
            actor_id=state.session.root_actor_id, root_actor_id=state.session.root_actor_id))
        return SessionArtifactStore(handle)

    one, two = artifacts("one"), artifacts("two")
    receipt = one.put_json({"evidence": ["exact"]})
    assert one.put_json({"evidence": ["exact"]}).reference == receipt.reference
    assert one.read_json(receipt.reference) == {"evidence": ["exact"]}
    assert not list(tmp_path.glob("**/artifacts/**/*.json"))
    with pytest.raises(ArtifactNotFound):
        two.read_json(receipt.reference)


def test_sqlite_enclave_preserves_digest_cas_and_root_authority(tmp_path, session_types):
    sk = session_types
    from scripts.agent_harness.enclave_store import (
        EnclaveAuthorityError, EnclaveConflict, EnclaveFact, EnclaveSourceKind, EnclaveStore,
    )
    kernel, first = start(sk, tmp_path)
    store = EnclaveStore(sk.SessionLocator(tmp_path), max_bytes=4096)
    before = store.read(first.session.id)
    value = EnclaveFact(value="keep", source_kind=EnclaveSourceKind.USER,
                        source_turn_id=sk.TurnId("turn"))
    after = store.set(first.session.id, first.session.root_actor_id, "policy", value,
                      expected_digest=before.digest)
    assert after.digest != before.digest
    assert store.read(first.session.id).facts["policy"].value == "keep"
    assert not sk.SessionLocator(tmp_path).locate(first.session.id).enclave.exists()
    with pytest.raises(EnclaveConflict):
        store.delete(first.session.id, first.session.root_actor_id, "policy",
                     expected_digest=before.digest)
    kernel.apply(sk.ActorStarted(session_id=first.session.id, actor_id=sk.ActorId("child"),
        parent_actor_id=first.session.root_actor_id, kind=sk.ActorKind.SUBAGENT,
        idempotency_key="child"))
    with pytest.raises(EnclaveAuthorityError):
        store.set(first.session.id, sk.ActorId("child"), "policy", value,
                  expected_digest=after.digest)


def test_sqlite_core_runtime_contracts(tmp_path):
    """Run existing kernel/lifecycle contracts in the project's isolated kit fixture."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    files = ["test_session_kernel.py", "test_enclave_store.py", "test_session_retention.py",
             "test_session_rehydration.py", "test_artifact_store.py", "test_worktree_registry.py",
             "test_worktree_hook.py", "test_material_action.py", "test_agent_continuation_hook.py",
             "test_distribution_boundary.py"]
    result = subprocess.run([sys.executable, str(root / "tools/run_core_regressions.py"),
        "--target", str(tmp_path / "kit"),
        *["scripts/agent_harness/tests/" + name for name in files],
        *["scripts/skill_harness/tests/" + name for name in (
            "test_merge_cleanup.py", "test_phase_runner.py", "test_publish_final_review.py",
            "test_session_phase_store.py")]],
        cwd=root, capture_output=True, text=True, timeout=120)
    diagnostics = result.stdout + result.stderr
    if result.returncode:
        report = tmp_path / "runtime-diagnostics.log"
        report.write_text(diagnostics)
        pytest.fail(f"Runtime diagnostics: {report}\n{diagnostics[:6000]}\n{diagnostics[-6000:]}")


def test_sqlite_monitor_runtime_contracts(tmp_path):
    """Exercise monitor migration and its actual installed skill consumers."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    files = ["test_monitor_observation_store.py", "test_local_pr_monitor.py",
             "test_monitor_launch_lock.py", "test_monitor_runtime_handoff.py",
             "test_merge_cleanup.py", "test_app_server_resume.py"]
    result = subprocess.run([sys.executable, str(root / "tools/run_core_regressions.py"),
        "--target", str(tmp_path / "kit"),
        *["scripts/skill_harness/tests/" + name for name in files]],
        cwd=root, capture_output=True, text=True, timeout=240)
    diagnostics = result.stdout + result.stderr
    if result.returncode:
        report = tmp_path / "monitor-diagnostics.log"
        report.write_text(diagnostics)
        pytest.fail(f"Runtime diagnostics: {report}\n{diagnostics[:5000]}\n{diagnostics[-7000:]}")


def test_native_answer_runtime_contracts(tmp_path):
    """Exercise legacy decisions and active native steering in the isolated kit."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    files = ["test_adaptive_user_decision.py", "test_adaptive_control_authority.py"]
    result = subprocess.run([sys.executable, str(root / "tools/run_core_regressions.py"),
        "--target", str(tmp_path / "kit"),
        *["scripts/agent_harness/tests/" + name for name in files]],
        cwd=root, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, (result.stdout + result.stderr)[-16000:]


def test_sqlite_prompt_history_preserves_original_instruction_receipt(tmp_path, session_types):
    import json
    sk = session_types
    from scripts.agent_harness.runtime_database import RuntimeDatabase

    kernel, first = start(sk, tmp_path)
    kernel.apply(sk.ForegroundTurnProvisioned(session_id=first.session.id,
        actor_id=first.session.root_actor_id, idempotency_key="provision"))
    prompted = kernel.apply(sk.ForegroundTurnPrompted(session_id=first.session.id,
        actor_id=first.session.root_actor_id, vendor_turn_id="turn", prompt_digest="a" * 64,
        idempotency_key="original"))
    original = prompted.foreground_turns[first.session.root_actor_id].user_prompt_receipt
    current = kernel.apply(sk.ForegroundTurnPrompted(session_id=first.session.id,
        actor_id=first.session.root_actor_id, vendor_turn_id="turn", prompt_digest="b" * 64,
        idempotency_key="side-question"))
    assert current.foreground_turns[first.session.root_actor_id].user_prompt_receipt.prompt_digest == "b" * 64
    with RuntimeDatabase(tmp_path).transaction() as tx:
        record = tx.get("prompt:one", original.authority_reference)
        assert json.loads(record.payload)["prompt_digest"] == "a" * 64
        assert json.loads(record.payload)["actor_id"] == "root-one"
