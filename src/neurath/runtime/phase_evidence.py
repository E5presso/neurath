"""Structured phase evidence over current Git facts and explicit agent reports.

This producer binds provenance, not success. Existing phase, adaptive authority,
review and runtime validators remain responsible for accepting the evidence.
"""
import json
import re
import subprocess
from pathlib import Path

from neurath.agents.store import MessageStore
from neurath.memory.store import canonical
from neurath.resources import distribution_id

GIT_LABELS = ("git_status", "staged_files", "commit_sha", "branch_name", "worktree_absolute_path",
              "remote_branch", "remote_head", "push_head_match")
SOURCE_LABELS = (*GIT_LABELS, "worktree_release_receipt")
AUTHORITY_LABELS = {"adaptive_control_initialized", "adaptive_control_receipt"}


def schema():
    from neurath.runtime.task_schema import strings, text_field
    return {"workflow_id":text_field(256), "expected_revision":{"type":"integer","minimum":0,"maximum":2**53-1},
        "labels":strings(), "notes":{"type":"array","default":[],"maxItems":128,"items":{
            "type":"object","additionalProperties":False,"required":["label","text"],
            "properties":{"label":{**text_field(128),"description":"A current required label, or supplemental_<name> for an additional observation needed by the phase's minimum count."},"text":text_field()}}}, "key":text_field(512)}


def _git(root, *args):
    import os
    env = {k:v for k,v in os.environ.items() if not k.startswith("GIT_")}
    value = subprocess.run(["git","-C",str(root),*args],capture_output=True,text=True,
                           timeout=30,env=env,check=False)
    if value.returncode:
        raise ValueError("Git evidence is unavailable: " + value.stderr[-1000:])
    return value.stdout.strip()


def _basis(root):
    # Read-only snapshot, including untracked contents. No filenames are trusted
    # as evidence that content stayed unchanged between prepare and completion.
    from scripts.agent_harness.repository_readback import RepositoryWorktreeReadback
    return RepositoryWorktreeReadback(Path(root)).worktree_fingerprint()


def _context(root, handle, workflow_id):
    from scripts.skill_harness.phase_runner import PhaseRunner, SkillContractRepository
    from scripts.skill_harness.session_phase_store import SessionPhaseRunnerStore
    workflow = handle.inspect().workflows.get(workflow_id)
    if workflow is None or workflow.owner_actor_id != handle.actor_id or workflow.status.value != "active":
        raise ValueError("phase evidence requires its active owned workflow")
    state = SessionPhaseRunnerStore.open_existing(handle, workflow_id).read()
    current = PhaseRunner(SkillContractRepository(root)).current(SessionPhaseRunnerStore.open_existing(handle, workflow_id))
    if not isinstance(current.get("phase"), dict):
        raise ValueError("workflow has no current phase for evidence preparation")
    return workflow, state, set(current["phase"]["required_evidence"])


def _store(root):
    store = MessageStore(root)
    with store.connection() as db:
        db.execute("CREATE TABLE IF NOT EXISTS phase_evidence_documents (reference TEXT PRIMARY KEY,"
            "actor TEXT, session TEXT, worktree TEXT, workflow TEXT, revision INTEGER, document TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS phase_evidence_requests (actor TEXT, worktree TEXT, key TEXT,"
            "request TEXT, result TEXT, PRIMARY KEY(actor,worktree,key))")
    return store


def prepare(root, handle, fields):
    from scripts.agent_harness.session_kernel import WorkflowId
    from scripts.agent_harness.artifact_store import SessionArtifactStore
    root = Path(root).resolve()
    request = canonical(fields)
    store = _store(root)
    with store.connection() as db:
        prior = db.execute("SELECT request,result FROM phase_evidence_requests WHERE actor=? AND worktree=? AND key=?",
            (str(handle.actor_id),str(root),fields["key"])).fetchone()
    if prior is not None:
        if prior["request"] != request:
            raise ValueError("evidence key identifies different input")
        return json.loads(prior["result"])
    workflow, state, required = _context(root, handle, WorkflowId(fields["workflow_id"]))
    if workflow.revision != fields["expected_revision"]:
        raise ValueError("phase evidence requires the exact current workflow revision")
    labels = fields["labels"] + [note["label"] for note in fields["notes"]]
    supplemental = {label for label in labels if re.fullmatch(r"supplemental_[a-z][a-z0-9_]{0,99}",label)}
    if not labels or len(labels) != len(set(labels)) or not set(labels) <= required | supplemental:
        raise ValueError("evidence labels must be unique names required by the current phase")
    if not set(fields["labels"]) <= set(SOURCE_LABELS):
        raise ValueError("automatic evidence label has no Git producer; use an explicit report or current authority reference")
    if set(labels) & AUTHORITY_LABELS:
        raise ValueError("reserved adaptive authority must use its current evidence reference")
    all_labels = {item for contract in json.loads((Path(__file__).parents[1]/"_assets/.agents/skills/contracts.json").read_text())["skills"].values()
                  for phase in contract["phase_contracts"] for item in phase["required_evidence"]} | AUTHORITY_LABELS
    before = _basis(root)
    evidence, provenance = [], []
    for label in fields["labels"]:
        if label == "worktree_release_receipt":
            from neurath.runtime.finish_release import release_evidence
            value = release_evidence(root, handle)
        elif label == "git_status":
            value = _git(root,"status","--porcelain=v1","--untracked-files=all") or "clean"
        elif label == "staged_files":
            value = _git(root,"diff","--cached","--name-only")
            if not value:
                raise ValueError("no staged files were observed")
        elif label == "commit_sha":
            value = _git(root,"rev-parse","HEAD")
        elif label == "branch_name":
            value = _git(root,"branch","--show-current")
        elif label == "worktree_absolute_path":
            value = str(root)
        elif label == "remote_branch":
            branch = _git(root,"branch","--show-current")
            if not branch:
                value = "detached-head; upstream=absent"
            else:
                upstream = _git(root,"for-each-ref","--format=%(upstream)","refs/heads/"+branch)
                value = upstream or "upstream=absent; branch="+branch
        else:
            branch = _git(root,"branch","--show-current")
            remote = _git(root,"config","--get","branch."+branch+".remote")
            merge = _git(root,"config","--get","branch."+branch+".merge")
            lines = _git(root,"ls-remote","--exit-code",remote,merge).splitlines()
            if len(lines) != 1 or len(lines[0].split()) != 2:
                raise ValueError("remote head did not resolve uniquely")
            value = lines[0].split()[0]
            if label == "push_head_match":
                local = _git(root,"rev-parse","HEAD")
                if value != local:
                    raise ValueError("remote head does not match current HEAD")
                value = f"local_head={local} remote_head={value} match=true"
        evidence.append(label+": "+value)
        provenance.append({"label":label,"authority":"source-readback"})
    for note in fields["notes"]:
        label, value = note["label"], note["text"]
        if label in SOURCE_LABELS or any(re.search(r"\b"+re.escape(other)+r"\b",value) for other in all_labels-{label}):
            raise ValueError("report cannot impersonate a reserved source or another evidence label")
        evidence.append(label+": "+value+" [authority=agent-report]")
        provenance.append({"label":label,"authority":"agent-report"})
    after = _basis(root)
    if before != after:
        raise ValueError("source changed during evidence preparation")
    document = {"kind":"phase-evidence", "actor":str(handle.actor_id),"session":str(handle.session_id),"worktree":str(root),
        "workflow_id":fields["workflow_id"],"workflow_revision":workflow.revision,
        "phase_id":state.current_phase_id,"source":distribution_id(),"worktree_fingerprint":after,
        "phase_evidence":evidence,"provenance":provenance}
    receipt = SessionArtifactStore(handle).put_json(document)
    reference = "evidence:"+receipt.reference
    result = {"reference":reference,"workflow_revision":workflow.revision,"phase_id":state.current_phase_id,
              "provenance":provenance,"authority":"prepared-evidence-not-completion"}
    with store.connection() as db:
        db.execute("INSERT OR IGNORE INTO phase_evidence_documents VALUES (?,?,?,?,?,?,?)",
            (reference,str(handle.actor_id),str(handle.session_id),str(root),fields["workflow_id"],workflow.revision,canonical(document)))
        prior = db.execute("SELECT request,result FROM phase_evidence_requests WHERE actor=? AND worktree=? AND key=?",
            (str(handle.actor_id),str(root),fields["key"])).fetchone()
        if prior is not None:
            if prior["request"] != request:
                raise ValueError("evidence key identifies different input")
            return json.loads(prior["result"])
        db.execute("INSERT INTO phase_evidence_requests VALUES (?,?,?,?,?)",
            (str(handle.actor_id),str(root),fields["key"],request,canonical(result)))
    return result


def resolve(root, handle, workflow_id, reference):
    from scripts.agent_harness.artifact_store import SessionArtifactStore
    # The dispatcher supplies its verified worktree, never a document path.
    if root is None:
        raise ValueError("phase evidence has no native worktree binding")
    root = Path(root).resolve()
    with _store(root).connection() as db:
        row = db.execute("SELECT * FROM phase_evidence_documents WHERE reference=?",(reference,)).fetchone()
    workflow = handle.inspect().workflows.get(workflow_id)
    if (row is None or workflow is None or row["actor"] != str(handle.actor_id)
            or row["session"] != str(handle.session_id) or row["worktree"] != str(root)
            or row["workflow"] != str(workflow_id) or row["revision"] != workflow.revision):
        raise ValueError("evidence is not registered for this owner and exact workflow revision")
    document = SessionArtifactStore(handle).read_json(reference.removeprefix("evidence:"))
    if canonical(document) != row["document"] or document["source"] != distribution_id() or document["worktree_fingerprint"] != _basis(root):
        raise ValueError("registered evidence source changed; prepare current evidence")
    return document["phase_evidence"]
