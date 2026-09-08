"""Maintenance tools retain native authority and do not replay uncertain effects."""
from types import SimpleNamespace
import pytest
from neurath.runtime import maintenance_tasks as m


def test_read_learning_uses_bound_identity_without_cli(monkeypatch):
    calls = []
    class Learning:
        def __init__(self, memory): pass
        def pending(self, host, session): calls.append((host, session)); return []
    monkeypatch.setattr(m, "Learning", Learning)
    monkeypatch.setattr(m, "ProjectMemory", lambda root: object())
    identity = SimpleNamespace(host="codex", session="native", address="codex:native", is_root=True)
    assert m.run(".", "learning_pending", {}, identity=identity) == []
    assert calls == [("codex", "native")]


def test_user_decision_is_never_manufactured_by_mcp_boolean():
    with pytest.raises(ValueError,match="native"):
        m.run(".", "reporting_consent", {"decision":"yes","user_choice_ref":"prompt","key":"choice"},
              identity=None)


def test_missing_identity_and_foreign_owner_reject_before_service(monkeypatch):
    with pytest.raises(ValueError, match="native"):
        m.run(".", "learning_pending", {}, identity=None)
    from neurath.runtime import tasks
    monkeypatch.setattr(tasks, "_verification_owner", lambda *a: (_ for _ in ()).throw(ValueError("owner")))
    monkeypatch.setattr(m, "Updates", lambda *a: pytest.fail("service entered before ownership"))
    identity = SimpleNamespace(host="codex", session="native", address="codex:native", is_root=True)
    with pytest.raises(ValueError, match="owner"):
        m.run(".", "releases_notice", {"key":"notice"}, identity=identity)


def test_retry_store_never_reexecutes_uncertain_mutation(tmp_path):
    store = m.MaintenanceCalls(tmp_path / "calls.sqlite3")
    calls=[]
    def action():
        calls.append(1)
        raise OSError("lost response")
    with pytest.raises(OSError):
        store.execute("owner", "key", "releases_apply", {"offer_id":"offer"}, action)
    with pytest.raises(ValueError, match="uncertain"):
        store.execute("owner", "key", "releases_apply", {"offer_id":"offer"}, action)
    assert calls == [1]


def test_retry_returns_result_and_rejects_different_input(tmp_path):
    store = m.MaintenanceCalls(tmp_path / "calls.sqlite3")
    first=store.execute("owner","key","learning_defer",{"reason":"a"},lambda: {"count":1})
    assert store.execute("owner","key","learning_defer",{"reason":"a"},
                         lambda: pytest.fail("replayed")) == first
    with pytest.raises(ValueError, match="changed"):
        store.execute("owner","key","learning_defer",{"reason":"b"},lambda:None)


def test_retry_store_rejects_symlink(tmp_path):
    target=tmp_path/"target"; target.write_text("secret")
    link=tmp_path/"link"; link.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        m.MaintenanceCalls(link)


def test_nested_report_schema_rejects_missing_and_foreign_fields():
    from neurath.runtime.task_schema import arguments
    with pytest.raises(ValueError, match="missing required"):
        arguments("reporting_prepare", {"report": {}, "privacy_reviewed": True, "key":"r"})
    with pytest.raises(ValueError, match="unexpected"):
        arguments("learning_status", {"actor":"forged"})


def test_maintenance_inventory_exposes_closed_schemas():
    from neurath.runtime.task_schema import definitions
    rows={r["name"]:r for r in definitions()}
    assert "reporting_prepare" in rows and "learning_defer" in rows
    assert rows["releases_check"]["annotations"]["readOnlyHint"] is False
    assert rows["releases_notice"]["annotations"]["readOnlyHint"] is False
    assert "argv" not in rows["reporting_submit"]["inputSchema"]["properties"]
