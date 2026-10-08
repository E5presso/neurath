"""Transactional use-case tests with a rollback-capable in-memory adapter."""
from copy import deepcopy
import pytest
from neurath.application import Application
from neurath.domain.errors import AuthorizationError, ConflictError, DomainError, ValidationError


class MemoryRepository:
    def __init__(self, rows):
        self.rows = rows

    def get(self, entity_id):
        return deepcopy(self.rows.get(entity_id))

    def add(self, entity):
        if entity.id in self.rows:
            raise ConflictError("Duplicate")
        self.rows[entity.id] = deepcopy(entity)

    def save(self, entity, expected_revision):
        old = self.rows.get(entity.id)
        if old is None or old.revision != expected_revision:
            raise ConflictError("Stale")
        assert entity.revision == expected_revision + 1
        self.rows[entity.id] = deepcopy(entity)

    def list(self, **filters):
        return [deepcopy(row) for row in self.rows.values() if all(getattr(row, key) == value for key, value in filters.items())]


class MemoryUow:
    def __init__(self, database):
        self.database = database

    def __enter__(self):
        self.rows = deepcopy(self.database)
        return self

    def repo(self, kind):
        return MemoryRepository(self.rows.setdefault(kind, {}))

    def commit(self):
        self.database.clear()
        self.database.update(deepcopy(self.rows))

    def __exit__(self, *args):
        pass


@pytest.fixture(params=["memory", "sqlite"])
def app(request, tmp_path):
    if request.param == "sqlite":
        from neurath.infrastructure.storage import Database
        database = Database(tmp_path / "application.sqlite3")
        database.initialize()
        application = Application(database.uow)
    else:
        database = {}
        application = Application(lambda: MemoryUow(database))
    application.register_session(host="fixture", native_id="native-owner", session_id="owner")
    application.register_session(host="fixture", native_id="native-child", session_id="child", parent_id="owner")
    return application


def create(app, *, phases=None):
    source = app.register_source(session_id="owner", event_id="prompt", text="Produce an independently verified result")
    return app.execute("task.create", "owner", {"request_id": "create", "source_id": source["id"], "goal": "Deliver result", "criteria": [{"id": "correct", "description": "Result verified"}], "phases": phases or []})


def mutate(app, command, task, key, **extras):
    return app.execute(command, "owner", {"request_id": key, "task_id": task["id"], "expected_revision": task["revision"], **extras})


def test_idempotency_cas_and_unknown_identity_fields(app):
    item = create(app)
    args = {"request_id": "start", "task_id": item["id"], "expected_revision": 0}
    started = app.execute("task.activate", "owner", args)
    assert app.execute("task.activate", "owner", args) == started
    with pytest.raises(ConflictError):
        app.execute("task.wait", "owner", {**args, "reason": "blocked"})
    with pytest.raises(ConflictError):
        app.execute("task.wait", "owner", {**args, "request_id": "new", "reason": "blocked"})
    with pytest.raises(ValidationError):
        app.execute("task.get", "owner", {"task_id": item["id"], "actor_id": "child"})
    assert app.execute("task.get", "owner", {"task_id": item["id"]})["status"] == "active"


def test_user_source_intake_and_ownership_cannot_be_forged(app):
    source = app.register_source(session_id="child", event_id="report", text="Agent interpretation", source_type="report")
    with pytest.raises(AuthorizationError):
        app.execute("task.create", "child", {"request_id": "x", "source_id": source["id"], "goal": "Fake", "criteria": [{"id": "a", "description": "A"}]})
    item = create(app)
    with pytest.raises(AuthorizationError):
        app.execute("task.activate", "child", {"request_id": "x", "task_id": item["id"], "expected_revision": 0})


def test_report_failed_observation_and_wait_preserve_task(app):
    item = create(app)
    item = mutate(app, "task.activate", item, "active")
    report = app.execute("evidence.record", "owner", {"request_id": "report", "task_id": item["id"], "criterion_id": "correct", "content": "Seems done"})
    failed = app.register_evidence(session_id="owner", event_id="failed-call", task_id=item["id"], evidence_type="tool", content="Exit code 1", success=False, criterion_id="correct")
    for evidence in [report, failed]:
        with pytest.raises(DomainError):
            mutate(app, "criterion.satisfy", item, evidence["id"], criterion_id="correct", evidence_ids=[evidence["id"]])
    item = mutate(app, "task.wait", item, "wait", reason="Host execution failed")
    assert item["status"] == "waiting"
    assert item["criteria"][0]["satisfied"] is False
    item = mutate(app, "task.resume", item, "resume")
    evidence = app.register_evidence(session_id="owner", event_id="passing-call", task_id=item["id"], evidence_type="tool", content="Exit code 0; assertion passed", success=True, criterion_id="correct")
    item = mutate(app, "criterion.satisfy", item, "satisfy", criterion_id="correct", evidence_ids=[evidence["id"]])
    assert item["status"] == "active"
    item = mutate(app, "task.complete", item, "complete")
    assert item["status"] == "completed"


def test_phase_evidence_must_be_bound_and_ordered(app):
    item = create(app, phases=[{"id": "implement", "name": "Implement"}, {"id": "verify", "name": "Verify"}])
    item = mutate(app, "task.activate", item, "active")
    with pytest.raises(DomainError):
        mutate(app, "phase.start", item, "skip", phase_id="verify")
    item = mutate(app, "phase.start", item, "start-first", phase_id="implement")
    evidence = app.register_evidence(session_id="owner", event_id="done", task_id=item["id"], evidence_type="tool", content="Implementation built", success=True, phase_id="implement")
    item = mutate(app, "phase.complete", item, "finish-first", phase_id="implement", evidence_ids=[evidence["id"]])
    item = mutate(app, "phase.start", item, "start-second", phase_id="verify")
    with pytest.raises(DomainError):
        mutate(app, "phase.complete", item, "wrong-evidence", phase_id="verify", evidence_ids=[evidence["id"]])


def test_delegation_report_message_ack_and_accept_are_distinct(app):
    item = create(app)
    result = mutate(app, "delegation.prepare", item, "prepare", recipient_id="child", instruction="Review the result")
    delegation, item = result["delegation"], result["task"]
    delegation = app.execute("delegation.start", "child", {"request_id": "start", "delegation_id": delegation["id"], "expected_revision": 0})
    delegation = app.execute("delegation.report", "child", {"request_id": "report", "delegation_id": delegation["id"], "expected_revision": 1, "report": "Review complete"})
    message = app.execute("message.send", "child", {"request_id": "msg", "recipient_id": "owner", "content": "Result ready", "task_id": item["id"]})
    app.execute("message.ack", "owner", {"request_id": "ack", "message_id": message["id"], "expected_revision": 0})
    assert app.execute("delegation.list", "owner", {"task_id": item["id"]})["items"][0]["status"] == "reported"
    with pytest.raises(AuthorizationError):
        app.execute("delegation.accept", "child", {"request_id": "bad-accept", "delegation_id": delegation["id"], "expected_revision": 2})
    app.execute("delegation.accept", "owner", {"request_id": "accept", "delegation_id": delegation["id"], "expected_revision": 2})
    assert app.execute("task.get", "owner", {"task_id": item["id"]})["status"] == "pending"


def test_lease_release_reacquire_preserves_generation(app):
    first = app.execute("lease.acquire", "owner", {"request_id": "a", "resource": "/workspace"})
    with pytest.raises(ConflictError):
        app.execute("lease.acquire", "child", {"request_id": "a", "resource": "/workspace"})
    app.execute("lease.release", "owner", {"request_id": "b", "resource": "/workspace", "generation": 1, "expected_revision": 0})
    second = app.execute("lease.acquire", "child", {"request_id": "c", "resource": "/workspace"})
    assert second["generation"] == first["generation"] + 1
    with pytest.raises(ConflictError):
        app.execute("lease.check", "owner", {"resource": "/workspace", "generation": 1})


def test_scope_revision_invalidates_evidence_and_retains_sources(app):
    item = create(app)
    evidence = app.register_evidence(session_id="owner", event_id="old-result", task_id=item["id"], evidence_type="tool", content="Old scope passed", success=True, criterion_id="correct")
    source = app.register_source(session_id="owner", event_id="new-prompt", text="Change the requested result")
    item = mutate(app, "task.revise", item, "revise", source_id=source["id"], goal="Changed goal", criteria=[{"id": "correct", "description": "New result verified"}])
    assert len(item["source_ids"]) == 2
    assert item["scope_version"] == 2
    with pytest.raises(DomainError):
        mutate(app, "criterion.satisfy", item, "stale-evidence", criterion_id="correct", evidence_ids=[evidence["id"]])


def test_approval_requires_native_source_and_specific_purpose(app):
    item = create(app)
    with pytest.raises(ValidationError):
        app.register_evidence(session_id="owner", event_id="made-up", task_id=item["id"], evidence_type="approval", content="yes", approved=True)
    source = app.register_source(session_id="owner", event_id="real-choice", text="Withdraw this task", source_type="approval")
    approval = app.register_evidence(session_id="owner", event_id="choice-record", task_id=item["id"], evidence_type="approval", content="Withdraw this task", approved=True, source_id=source["id"], purpose="task.withdraw")
    item = mutate(app, "task.withdraw", item, "withdraw", approval_id=approval["id"])
    assert item["status"] == "withdrawn"


def test_unresolved_delegation_prevents_completion_without_mutating_parent(app):
    item = create(app)
    item = mutate(app, "task.activate", item, "active")
    evidence = app.register_evidence(session_id="owner", event_id="verified", task_id=item["id"], evidence_type="tool", content="Verified", success=True, criterion_id="correct")
    item = mutate(app, "criterion.satisfy", item, "satisfy", criterion_id="correct", evidence_ids=[evidence["id"]])
    result = mutate(app, "delegation.prepare", item, "prepare", recipient_id="child", instruction="Review")
    item, delegation = result["task"], result["delegation"]
    with pytest.raises(DomainError):
        mutate(app, "task.complete", item, "complete")
    assert app.execute("task.get", "owner", {"task_id": item["id"]}) == item
    app.execute("delegation.cancel", "owner", {"request_id": "cancel", "delegation_id": delegation["id"], "expected_revision": 0, "reason": "Review no longer needed"})
    assert mutate(app, "task.complete", item, "complete")["status"] == "completed"


def test_checkpoint_is_observation_not_completion_and_source_replay_is_strict(app):
    item = create(app)
    checkpoint = mutate(app, "checkpoint.save", item, "checkpoint", note="Implementation interrupted", state={"next": "resume verification"})
    assert checkpoint["task_revision"] == item["revision"]
    assert app.execute("task.get", "owner", {"task_id": item["id"]}) == item
    with pytest.raises(ConflictError):
        app.register_source(session_id="owner", event_id="prompt", text="Different instruction under reused event")
    with pytest.raises(ConflictError):
        app.register_session(host="other-host", native_id="other-session", session_id="owner")


def end_session(app, session_id):
    with app.uow_factory() as uow:
        session = uow.repo("session").get(session_id)
        previous = session.revision
        session.status = "ended"
        session.changed()
        uow.repo("session").save(session, previous)
        uow.commit()


def test_only_trusted_matching_native_identity_reactivates_session(app):
    item = create(app)
    end_session(app, "owner")
    with pytest.raises(AuthorizationError):
        app.execute("task.get", "owner", {"task_id": item["id"]})
    assert app.register_session(host="fixture", native_id="native-owner", session_id="owner")["status"] == "ended"
    with pytest.raises(AuthorizationError):
        app.activate_session(session_id="owner", host="fixture", native_id="wrong-id")
    assert app.activate_session(session_id="owner", host="fixture", native_id="native-owner")["status"] == "active"
    assert app.execute("task.get", "owner", {"task_id": item["id"]}) == item


def test_adoption_requires_ended_owner_and_preserves_work_and_delegation(app):
    item = create(app)
    result = mutate(app, "delegation.prepare", item, "prepare", recipient_id="child", instruction="Review")
    item = result["task"]
    app.register_session(host="fixture", native_id="native-successor", session_id="successor")
    source = app.register_source(session_id="successor", event_id="adopt-instruction", text="Take responsibility for the interrupted task")
    args = {"request_id": "adopt", "task_id": item["id"], "expected_revision": item["revision"], "source_id": source["id"]}
    with pytest.raises(AuthorizationError):
        app.execute("task.adopt", "successor", args)
    end_session(app, "owner")
    adopted = app.execute("task.adopt", "successor", args)
    assert adopted["owner_id"] == "successor"
    assert adopted["goal"] == item["goal"]
    assert adopted["source_id"] == item["source_id"]
    assert adopted["status"] == item["status"]
    assert len(adopted["source_ids"]) == 2
    assert app.execute("delegation.list", "successor", {"task_id": item["id"]})["items"][0]["owner_id"] == "successor"


def test_late_native_observation_preserves_old_scope_after_definition_changed(app):
    item = create(app)
    source = app.register_source(session_id="owner", event_id="change", text="Replace the previous acceptance criterion")
    item = mutate(app, "task.revise", item, "revise", source_id=source["id"], goal="New goal", criteria=[{"id": "new", "description": "New acceptance"}])
    evidence = app.register_evidence(session_id="owner", event_id="late-result", task_id=item["id"], evidence_type="tool", content="Old process eventually returned", success=True, criterion_id="correct", scope_version=1)
    assert evidence["scope_version"] == 1
    with pytest.raises(DomainError):
        mutate(app, "criterion.satisfy", item, "satisfy", criterion_id="new", evidence_ids=[evidence["id"]])


def test_open_recipient_cannot_adopt_and_accept_its_own_result(app):
    item = create(app)
    result = mutate(app, "delegation.prepare", item, "prepare", recipient_id="child", instruction="Independent review")
    item = result["task"]
    source = app.register_source(session_id="child", event_id="adopt", text="Continue this interrupted task")
    end_session(app, "owner")
    with pytest.raises(AuthorizationError):
        app.execute("task.adopt", "child", {"request_id": "adopt", "task_id": item["id"], "expected_revision": item["revision"], "source_id": source["id"]})
