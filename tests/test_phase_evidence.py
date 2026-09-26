"""Operational phase evidence is prepared without argv or caller-forged authority."""
import subprocess
from pathlib import Path

import pytest
from tests.test_workflow_tasks import call, start, define_task
pytest_plugins = ["tests.test_agent_hooks"]


def prepare(sessions, labels, notes=None, revision=0, key="evidence"):
    return call(sessions, "phase_evidence_prepare", {"workflow_id":"phase", "expected_revision":revision,
        "labels":labels, "notes":notes or [], "key":key}, invocation=key)


def publication_fixture(sessions, monkeypatch):
    from scripts.skill_harness.phase_runner import SkillContract, SkillContractRepository

    root, _ = sessions
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True)
    (root / "tracked.txt").write_text("initial\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "Initial"], cwd=root, check=True)
    remote = root.parent / f"{root.name}-remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
    subprocess.run(["git", "push", "-qu", "origin", "HEAD"], cwd=root, check=True)

    bundle = Path(__file__).parents[1] / "src" / "neurath" / "_assets"
    monkeypatch.setattr("scripts._neurath_paths.asset_path", lambda _root, relative: bundle / relative)
    source_contract = SkillContractRepository(root).get("process-ticket")
    publication = next(phase for phase in source_contract.phases if phase.name == "publication")
    contract = SkillContract("phase-evidence-publication", ("merged",), (publication,))
    original_get = SkillContractRepository.get

    def get_contract(repository, skill_name):
        if skill_name == contract.name:
            return contract
        return original_get(repository, skill_name)

    monkeypatch.setattr(SkillContractRepository, "get", get_contract)
    call(sessions, "worktree_claim", {})
    start(sessions, skill=contract.name)
    monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy", lambda *a, **k: None)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    return root, publication, head


def publication_notes(head):
    return [
        {"label":"local_review_head_sha", "text":f"kind=final-local-review outcome=result-applied head_sha={head}"},
        {"label":"local_review_matrix_receipt", "text":
            f"matrix_id={'b' * 64} frozen=true head_sha={head} row_count=14 verified_rows=14 "
            "blocking_findings=0 verdict=pass harness_audit=true audit_evidence=3 "
            "kind=final-local-review outcome=result-applied"},
        {"label":"pr_readback_metadata", "text":"state=open"},
        {"label":"acceptance_handoff_result", "text":"outcome=pass"},
        {"label":"pr_review_status", "text":"status=ready"},
        {"label":"merge_gate", "text":"status=ready"},
        {"label":"github_metadata_language", "text":
            "validator=scripts.skill_harness.github_metadata_language policy_passed=true"},
    ]


def test_automatic_publication_git_evidence_round_trips_to_phase_complete(sessions, monkeypatch):
    _, publication, head = publication_fixture(sessions, monkeypatch)
    evidence = prepare(
        sessions,
        ["commit_sha", "push_head_match"],
        publication_notes(head),
        key="automatic-publication",
    )

    completed = call(sessions, "phase_complete", {
        "workflow_id":"phase", "expected_revision":0, "phase_id":publication.id,
        "status":"completed", "summary":"Exact local and remote publication head observed",
        "evidence_refs":[evidence["reference"]], "key":"complete-publication",
    })

    assert completed["completed_phase"]["status"] == "completed"


def test_automatic_publication_git_evidence_rejects_unequal_and_stale_heads(sessions, monkeypatch):
    root, publication, head = publication_fixture(sessions, monkeypatch)
    (root / "tracked.txt").write_text("local only\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "Local only"], cwd=root, check=True)
    with pytest.raises(ValueError, match="remote head does not match current HEAD"):
        prepare(sessions, ["commit_sha", "push_head_match"], key="unequal-publication")

    subprocess.run(["git", "push", "-q"], cwd=root, check=True)
    current = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    evidence = prepare(
        sessions,
        ["commit_sha", "push_head_match"],
        publication_notes(current),
        key="stale-publication",
    )
    (root / "tracked.txt").write_text("new equal head\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "New equal head"], cwd=root, check=True)
    subprocess.run(["git", "push", "-q"], cwd=root, check=True)

    with pytest.raises(ValueError, match="source changed"):
        call(sessions, "phase_complete", {
            "workflow_id":"phase", "expected_revision":0, "phase_id":publication.id,
            "status":"completed", "summary":f"Reject evidence prepared for stale head {head}",
            "evidence_refs":[evidence["reference"]], "key":"complete-stale-publication",
        })


def finish_session_committed_fixture(sessions, monkeypatch):
    root, _ = sessions
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True)
    (root / "tracked.txt").write_text("initial\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "Initial"], cwd=root, check=True)
    remote = root.parent / f"{root.name}-remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
    subprocess.run(["git", "push", "-qu", "origin", "HEAD"], cwd=root, check=True)

    call(sessions, "worktree_claim", {})
    start(sessions, skill="finish-session")
    monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy", lambda *a, **k: None)
    ready = prepare(sessions, ["git_status"], [
        {"label":"session_finish_approval", "text":
            "approved_by=user commit=true push=true graphify=true worktree_release=true"},
        {"label":"diff_review", "text":"approved change reviewed"},
    ], key="finish-ready")
    phase_one = call(sessions, "phase_complete", {
        "workflow_id":"phase", "expected_revision":0, "phase_id":1,
        "status":"completed", "summary":"Approved change reviewed",
        "evidence_refs":[ready["reference"]], "key":"finish-phase-one",
    }, invocation="finish-phase-one")

    (root / "tracked.txt").write_text("prepared\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
    staged = prepare(sessions, ["staged_files"], revision=phase_one["workflow_revision"], key="finish-staged")
    phase_two = call(sessions, "phase_complete", {
        "workflow_id":"phase", "expected_revision":phase_one["workflow_revision"], "phase_id":2,
        "status":"completed", "summary":"Exact files staged",
        "evidence_refs":[staged["reference"]], "key":"finish-phase-two",
    }, invocation="finish-phase-two")
    subprocess.run(["git", "commit", "-qm", "Prepared"], cwd=root, check=True)
    committed = prepare(sessions, ["commit_sha"], revision=phase_two["workflow_revision"], key="finish-committed")
    phase_three = call(sessions, "phase_complete", {
        "workflow_id":"phase", "expected_revision":phase_two["workflow_revision"], "phase_id":3,
        "status":"completed", "summary":"Commit observed",
        "evidence_refs":[committed["reference"]], "key":"finish-phase-three",
    }, invocation="finish-phase-three")
    return root, remote, phase_three


def finish_session_clean_fixture(sessions, monkeypatch):
    root, _ = sessions
    (root / ".gitignore").write_text(".neurath/\nhost-storage/\n")
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True)
    (root / "tracked.txt").write_text("initial\n")
    subprocess.run(["git", "add", ".gitignore", "tracked.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "Initial"], cwd=root, check=True)
    remote = root.parent / f"{root.name}-remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
    subprocess.run(["git", "push", "-qu", "origin", "HEAD"], cwd=root, check=True)

    call(sessions, "worktree_claim", {})
    start(sessions, skill="finish-session")
    monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy", lambda *a, **k: None)
    ready = prepare(sessions, ["git_status"], [
        {"label":"session_finish_approval", "text":
            "approved_by=user commit=true push=true graphify=true worktree_release=true"},
        {"label":"diff_review", "text":"No staged or unstaged changes"},
    ], key="finish-clean-ready")
    first = call(sessions, "phase_complete", {
        "workflow_id":"phase", "expected_revision":0, "phase_id":1,
        "status":"completed", "summary":"Clean tree and approval observed",
        "evidence_refs":[ready["reference"]], "key":"finish-clean-phase-one",
    }, invocation="finish-clean-phase-one")
    return root, first["workflow_revision"]


def test_finish_session_clean_tree_skips_staging_and_commit_with_source_evidence(sessions, monkeypatch):
    root, revision = finish_session_clean_fixture(sessions, monkeypatch)
    stage = prepare(sessions, ["clean_tree"], revision=revision, key="finish-clean-stage")
    skipped_stage = call(sessions, "phase_complete", {
        "workflow_id":"phase", "expected_revision":revision, "phase_id":2,
        "status":"skipped", "summary":"No files to stage",
        "evidence_refs":[stage["reference"]], "key":"finish-skip-stage",
    }, invocation="finish-skip-stage")
    assert skipped_stage["completed_phase"]["status"] == "skipped"

    revision = skipped_stage["workflow_revision"]
    commit = prepare(sessions, ["clean_tree"], revision=revision, key="finish-clean-commit")
    skipped_commit = call(sessions, "phase_complete", {
        "workflow_id":"phase", "expected_revision":revision, "phase_id":3,
        "status":"skipped", "summary":"No commit to create",
        "evidence_refs":[commit["reference"]], "key":"finish-skip-commit",
    }, invocation="finish-skip-commit")
    assert skipped_commit["completed_phase"]["status"] == "skipped"

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()
    pushed = prepare(sessions, ["push_head_match"], revision=skipped_commit["workflow_revision"],
                     key="finish-clean-push")
    readback = call(sessions, "phase_complete", {
        "workflow_id":"phase", "expected_revision":skipped_commit["workflow_revision"],
        "phase_id":4, "status":"completed", "summary":"Existing remote HEAD matches",
        "evidence_refs":[pushed["reference"]], "key":"finish-clean-push-complete",
    }, invocation="finish-clean-push-complete")
    assert f"head_sha={head}" in " ".join(readback["completed_phase"]["evidence"])


@pytest.mark.parametrize("change", ["staged", "unstaged", "untracked"])
def test_finish_session_clean_skip_rejects_changed_tree(sessions, monkeypatch, change):
    root, revision = finish_session_clean_fixture(sessions, monkeypatch)
    if change == "untracked":
        (root / "new.txt").write_text("new\n")
    else:
        (root / "tracked.txt").write_text("changed\n")
        if change == "staged":
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
    with pytest.raises(ValueError, match="clean tree|clean-tree"):
        prepare(sessions, ["clean_tree"], revision=revision, key="dirty-clean-proof")


def test_finish_session_clean_skip_rejects_stale_and_unregistered_proof(sessions, monkeypatch):
    root, revision = finish_session_clean_fixture(sessions, monkeypatch)
    with pytest.raises(ValueError, match="evidence|source"):
        call(sessions, "phase_complete", {
            "workflow_id":"phase", "expected_revision":revision, "phase_id":2,
            "status":"skipped", "summary":"Unproven clean skip", "evidence_refs":[],
            "key":"finish-unproven-skip",
        }, invocation="finish-unproven-skip")
    clean = prepare(sessions, ["clean_tree"], revision=revision, key="stale-clean-proof")
    (root / "new.txt").write_text("new\n")
    with pytest.raises(ValueError, match="source changed"):
        call(sessions, "phase_complete", {
            "workflow_id":"phase", "expected_revision":revision, "phase_id":2,
            "status":"skipped", "summary":"Stale clean skip",
            "evidence_refs":[clean["reference"]], "key":"finish-stale-skip",
        }, invocation="finish-stale-skip")


def test_finish_session_clean_skip_rejects_staged_or_agent_report_proof(sessions, monkeypatch):
    root, revision = finish_session_clean_fixture(sessions, monkeypatch)
    with pytest.raises(ValueError, match="reserved source"):
        prepare(sessions, [], [{"label":"clean_tree", "text":"head_sha=claimed index=clean worktree=clean"}],
                revision=revision, key="claimed-clean-proof")
    (root / "tracked.txt").write_text("changed\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
    staged = prepare(sessions, ["staged_files"], revision=revision, key="dirty-stage-proof")
    with pytest.raises(ValueError, match="source-produced clean_tree evidence"):
        call(sessions, "phase_complete", {
            "workflow_id":"phase", "expected_revision":revision, "phase_id":2,
            "status":"skipped", "summary":"Invalid staged skip",
            "evidence_refs":[staged["reference"]], "key":"skip-with-staged-files",
        }, invocation="skip-with-staged-files")


def test_finish_session_clean_skip_rejects_head_change_after_stage_skip(sessions, monkeypatch):
    root, revision = finish_session_clean_fixture(sessions, monkeypatch)
    stage = prepare(sessions, ["clean_tree"], revision=revision, key="stage-clean-before-head-change")
    skipped_stage = call(sessions, "phase_complete", {
        "workflow_id":"phase", "expected_revision":revision, "phase_id":2,
        "status":"skipped", "summary":"No files to stage",
        "evidence_refs":[stage["reference"]], "key":"stage-clean-before-head-change-complete",
    }, invocation="stage-clean-before-head-change-complete")
    (root / "tracked.txt").write_text("new commit\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "Unexpected"], cwd=root, check=True)
    revision = skipped_stage["workflow_revision"]
    commit = prepare(sessions, ["clean_tree"], revision=revision, key="commit-clean-after-head-change")
    with pytest.raises(ValueError, match="clean_tree_head_changed"):
        call(sessions, "phase_complete", {
            "workflow_id":"phase", "expected_revision":revision, "phase_id":3,
            "status":"skipped", "summary":"Invalid changed HEAD skip",
            "evidence_refs":[commit["reference"]], "key":"commit-skip-after-head-change",
        }, invocation="commit-skip-after-head-change")


def test_finish_session_stage_skip_cannot_complete_a_later_commit(sessions, monkeypatch):
    root, revision = finish_session_clean_fixture(sessions, monkeypatch)
    stage = prepare(sessions, ["clean_tree"], revision=revision, key="stage-clean-before-new-commit")
    skipped_stage = call(sessions, "phase_complete", {
        "workflow_id":"phase", "expected_revision":revision, "phase_id":2,
        "status":"skipped", "summary":"No files to stage",
        "evidence_refs":[stage["reference"]], "key":"stage-clean-before-new-commit-complete",
    }, invocation="stage-clean-before-new-commit-complete")
    (root / "tracked.txt").write_text("unscoped commit\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "Unscoped"], cwd=root, check=True)
    revision = skipped_stage["workflow_revision"]
    committed = prepare(sessions, ["commit_sha"], revision=revision, key="unscoped-commit-proof")
    with pytest.raises(ValueError, match="stage_scope_not_completed"):
        call(sessions, "phase_complete", {
            "workflow_id":"phase", "expected_revision":revision, "phase_id":3,
            "status":"completed", "summary":"Reject commit without staged scope",
            "evidence_refs":[committed["reference"]], "key":"unscoped-commit-complete",
        }, invocation="unscoped-commit-complete")


def test_finish_session_push_readback_rejects_remote_advanced_after_prepare(sessions, monkeypatch):
    root, remote, phase_three = finish_session_committed_fixture(sessions, monkeypatch)
    subprocess.run(["git", "push", "-q"], cwd=root, check=True)
    pushed = prepare(sessions, ["push_head_match"], revision=phase_three["workflow_revision"], key="finish-pushed")

    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    peer = root.parent / f"{root.name}-peer"
    subprocess.run(["git", "clone", "-qb", branch, str(remote), str(peer)], check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=peer, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=peer, check=True)
    (peer / "remote.txt").write_text("advanced\n")
    subprocess.run(["git", "add", "remote.txt"], cwd=peer, check=True)
    subprocess.run(["git", "commit", "-qm", "Advance remote"], cwd=peer, check=True)
    subprocess.run(["git", "push", "-q"], cwd=peer, check=True)

    with pytest.raises(ValueError, match="upstream_mismatch"):
        call(sessions, "phase_complete", {
            "workflow_id":"phase", "expected_revision":phase_three["workflow_revision"], "phase_id":4,
            "status":"completed", "summary":"Reject stale remote evidence",
            "evidence_refs":[pushed["reference"]], "key":"finish-phase-four",
        }, invocation="finish-phase-four")


def test_finish_session_push_readback_rejects_commit_phase_head_drift(sessions, monkeypatch):
    root, _, phase_three = finish_session_committed_fixture(sessions, monkeypatch)
    (root / "later.txt").write_text("later commit\n")
    subprocess.run(["git", "add", "later.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "Later commit"], cwd=root, check=True)
    subprocess.run(["git", "push", "-q"], cwd=root, check=True)
    pushed = prepare(
        sessions,
        ["push_head_match"],
        revision=phase_three["workflow_revision"],
        key="finish-pushed-later-commit",
    )

    with pytest.raises(ValueError, match="commit_sha_mismatch"):
        call(sessions, "phase_complete", {
            "workflow_id":"phase", "expected_revision":phase_three["workflow_revision"], "phase_id":4,
            "status":"completed", "summary":"Reject commit and push head drift",
            "evidence_refs":[pushed["reference"]], "key":"finish-phase-four-head-drift",
        }, invocation="finish-phase-four-head-drift")


def test_commit_phases_use_registered_git_evidence_without_cli(sessions, monkeypatch):
    root, _ = sessions
    call(sessions, "worktree_claim", {})
    task_id = define_task(sessions)
    start(sessions)
    monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy", lambda *a, **k: None)
    (root / "change.txt").write_text("approved change\n")
    evidence = prepare(sessions, ["git_status"], [{"label":"diff_review", "text":"Reviewed the intended change"}])
    first = call(sessions, "phase_complete", {"workflow_id":"phase", "expected_revision":0,
        "phase_id":1,"status":"completed","summary":"Current Git and diff reviewed",
        "evidence_refs":[evidence["reference"]],"key":"phase-one"},invocation="phase-one")
    subprocess.run(["git","add","change.txt"], cwd=root, check=True)
    staged = prepare(sessions, ["staged_files"], revision=first["workflow_revision"], key="staged")
    second = call(sessions,"phase_complete",{"workflow_id":"phase","expected_revision":first["workflow_revision"],
        "phase_id":2,"status":"completed","summary":"Exact files staged","evidence_refs":[staged["reference"]],"key":"phase-two"},invocation="phase-two")
    subprocess.run(["git","-c","user.name=Fixture","-c","user.email=fixture@example.invalid","commit","-qm","Approved change"],cwd=root,check=True)
    committed = prepare(sessions,["commit_sha"],revision=second["workflow_revision"],key="committed")
    final = call(sessions,"phase_complete",{"workflow_id":"phase","expected_revision":second["workflow_revision"],
        "phase_id":3,"status":"completed","summary":"New commit observed","terminal_state":"committed",
        "evidence_refs":[committed["reference"]],"key":"phase-three"},invocation="phase-three")
    assert final["terminal_state"] == "committed"
    resolved = call(sessions, "task_resolve", {"task_id": task_id, "expected_revision": 1,
        "expected_task_revision": 1, "key": "task-succeeded", "status": "succeeded",
        "references": [f"workflow:phase:{final['workflow_revision']}"], "summary": "Observed the requested commit"})
    assert resolved["tasks"][0]["status"] == "succeeded"
    assert resolved["all_terminal"]


def test_notes_cannot_impersonate_reserved_evidence_or_smuggle_labels(sessions):
    call(sessions,"worktree_claim",{})
    start(sessions)
    for note in ({"label":"commit_sha","text":"claimed"},
                 {"label":"diff_review","text":"adaptive_control_receipt: fabricated"}):
        with pytest.raises(ValueError, match="reserved|authority|label"):
            prepare(sessions,[],[note],key=note["label"])


def test_arbitrary_artifact_is_not_a_registered_phase_evidence_producer(sessions, monkeypatch):
    call(sessions,"worktree_claim",{})
    start(sessions)
    monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy",lambda *a,**k:None)
    artifact=call(sessions,"artifact_put",{"document":{"phase_evidence":["git_status: clean","diff_review: passed"]},"key":"forged"})
    with pytest.raises(ValueError, match="registered|evidence"):
        call(sessions,"phase_complete",{"workflow_id":"phase","expected_revision":0,"phase_id":1,
            "status":"completed","summary":"Claimed","evidence_refs":["evidence:"+artifact["reference"]],"key":"forged-completion"})


def test_registered_evidence_key_is_stable_and_source_change_is_rejected(sessions, monkeypatch):
    root,_=sessions
    call(sessions,"worktree_claim",{})
    start(sessions)
    monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy",lambda *a,**k:None)
    notes=[{"label":"diff_review","text":"Reviewed current files"}]
    original=prepare(sessions,["git_status"],notes)
    replay=call(sessions,"phase_evidence_prepare",{"workflow_id":"phase","expected_revision":0,
        "labels":["git_status"],"notes":notes,"key":"evidence"},invocation="replay")
    assert replay==original
    with pytest.raises(ValueError,match="key identifies different"):
        call(sessions,"phase_evidence_prepare",{"workflow_id":"phase","expected_revision":0,
            "labels":["git_status"],"notes":[],"key":"evidence"},invocation="changed-key")
    (root/"later.txt").write_text("later change")
    with pytest.raises(ValueError,match="source changed"):
        call(sessions,"phase_complete",{"workflow_id":"phase","expected_revision":0,"phase_id":1,
            "status":"completed","summary":"Stale source","evidence_refs":[original["reference"]],"key":"stale"})


def test_pr_preparation_observes_an_unpublished_branch(sessions, monkeypatch):
    call(sessions,"worktree_claim",{})
    start(sessions,skill="create-pr")
    monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy",lambda *a,**k:None)
    evidence=prepare(sessions,["git_status","remote_branch"])
    result=call(sessions,"phase_complete",{"workflow_id":"phase","expected_revision":0,"phase_id":1,
        "status":"completed","summary":"Branch ready for publication","evidence_refs":[evidence["reference"]],"key":"prepared"})
    assert result["completed_phase"]["status"]=="completed"


def test_supplemental_label_does_not_replace_a_required_source(sessions, monkeypatch):
    call(sessions,"worktree_claim",{})
    start(sessions)
    monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy",lambda *a,**k:None)
    evidence=prepare(sessions,[],[{"label":"supplemental_git_status","text":"clean"},
        {"label":"diff_review","text":"reviewed"}])
    with pytest.raises(ValueError,match="exact structured entry"):
        call(sessions,"phase_complete",{"workflow_id":"phase","expected_revision":0,"phase_id":1,
            "status":"completed","summary":"Substitution attempt","evidence_refs":[evidence["reference"]],"key":"substitute"})
