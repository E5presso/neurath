"""Read current local Codex app affiliation without modifying app state."""
import json
import os

from neurath.hosts.identity import host_storage

MAX_STATE_BYTES = 16 * 1024 * 1024


def observe_app_project(native_session):
    result = {"status": "unobserved", "authority": "diagnostic", "source": "codex-app-local-state"}
    path = host_storage("codex", os.environ).parent / ".codex-global-state.json"
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_STATE_BYTES + 1)
        if len(raw) > MAX_STATE_BYTES:
            return {**result, "reason": "state-too-large"}
        data = json.loads(raw)
    except (OSError, ValueError):
        return {**result, "reason": "state-unavailable"}
    if not isinstance(data, dict):
        return {**result, "reason": "invalid-state"}
    assignments = data.get("thread-project-assignments", {})
    projects = data.get("local-projects", {})
    projectless = data.get("projectless-thread-ids", [])
    if not isinstance(assignments, dict) or not isinstance(projects, dict) or not isinstance(projectless, list):
        return {**result, "reason": "invalid-state"}
    assignment = assignments.get(native_session)
    if assignment is None:
        return ({**result, "status": "unassigned"} if native_session in projectless
                else {**result, "reason": "not-recorded"})
    if native_session in projectless:
        return {**result, "reason": "conflicting-records"}
    if not isinstance(assignment, dict) or assignment.get("projectKind") != "local":
        return {**result, "reason": "unsupported-project-record"}
    project_id = assignment.get("projectId")
    project = projects.get(project_id) if isinstance(project_id, str) else None
    if (not isinstance(project_id, str) or not 0 < len(project_id) <= 128
            or not isinstance(project, dict) or project.get("id") != project_id):
        return {**result, "reason": "project-not-observed"}
    return {**result, "status": "assigned", "project_id": project_id, "project_kind": "local"}
