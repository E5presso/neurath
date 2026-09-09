"""Operational phase evidence is prepared without argv or caller-forged authority."""
import subprocess
import pytest
from tests.test_workflow_tasks import call, start, define_task, assess_task
pytest_plugins = ["tests.test_agent_hooks"]


def prepare(sessions, labels, notes=None, revision=0, key="evidence"):
    return call(sessions, "phase_evidence_prepare", {"workflow_id":"phase", "expected_revision":revision,
        "labels":labels, "notes":notes or [], "key":key}, invocation=key)


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
    assessment = assess_task(sessions, task_id, final["workflow_revision"], "succeeded")
    resolved = call(sessions, "task_resolve", {"task_id": task_id, "expected_revision": 1,
        "expected_task_revision": 1, "key": "task-succeeded", "status": "succeeded",
        "references": [f"workflow:phase:{final['workflow_revision']}"], "assessment": assessment})
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
