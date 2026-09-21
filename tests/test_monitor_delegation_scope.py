"""Unrelated generic delegations cannot prevent a workflow-local PR monitor."""
import json
from types import SimpleNamespace

import pytest

from neurath.runtime.bundled_services import service
from neurath.runtime.engine import activate


@pytest.mark.parametrize("assignment", ["Review a separate task", "[1, 2]", '{"incomplete":'])
def test_monitor_ignores_non_workflow_assignments_without_changing_them(tmp_path, assignment):
    activate(tmp_path)
    from scripts.agent_harness.session_kernel import DelegationStatus
    monitor = service("monitor")
    unrelated = SimpleNamespace(id="unrelated", owner_actor_id="owner",
        target_actor_id="child", status=DelegationStatus.PENDING, assignment=assignment)
    related = SimpleNamespace(id="current", owner_actor_id="owner", target_actor_id="child2",
        status=DelegationStatus.PENDING, assignment=json.dumps({"workflow_id": "current-workflow",
            "kind": "review-code", "scope": "Current work", "started_at": "now", "target": "reviewer"}))
    state = SimpleNamespace(delegations={"unrelated": unrelated, "current": related})
    handle = SimpleNamespace(actor_id="owner", inspect=lambda: state)
    result = monitor.MonitorDelegationReader(handle, "current-workflow").active()
    assert [item.claim["delegation_id"] for item in result] == ["current"]
    assert unrelated.assignment == assignment
    assert unrelated.status is DelegationStatus.PENDING


def test_monitor_still_rejects_incomplete_assignment_for_its_workflow(tmp_path):
    activate(tmp_path)
    from scripts.agent_harness.session_kernel import DelegationStatus
    monitor = service("monitor")
    record = SimpleNamespace(id="current", owner_actor_id="owner", status=DelegationStatus.PENDING,
        assignment=json.dumps({"workflow_id": "current-workflow"}))
    handle = SimpleNamespace(actor_id="owner", inspect=lambda: SimpleNamespace(delegations={"current": record}))
    with pytest.raises(monitor.MonitorWorkflowStateError, match="identity is incomplete"):
        monitor.MonitorDelegationReader(handle, "current-workflow").active()
