"""Codex JSON-RPC session control, independent of subprocess and desktop UI.

The caller supplies its own authenticated transport. Discovery/read never resumes
another client’s live session. Only sessions created here accept mutations.
"""

from pathlib import Path
from subprocess import CalledProcessError

from neurath.providers.codex_sandbox import prepare_sandbox, sandbox_matches
from neurath.providers.contracts import (
    CreationRejected, ExecutionPolicy, Session, SessionTransport, UnsupportedOperation, text,
)


class CodexSessions:
    def __init__(self, transport: SessionTransport):
        self.transport = transport
        self._owned = {}
        self._turns = {}

    def discover(self, worktree, *, cursor=None, limit=25):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        params = {"cwd": str(Path(worktree).resolve()), "limit": limit}
        if cursor is not None:
            params["cursor"] = text(cursor, "cursor", 4096)
        return self.transport.request("thread/list", params)

    def read(self, native_session):
        result = self.transport.request("thread/read", {
            "threadId": text(native_session, "session ID", 256), "includeTurns": False})
        if result["thread"]["id"] != native_session:
            raise ValueError("host returned a different session")
        return result["thread"]

    def project(self, worktree, project_id=None):
        """Resolve an existing native project; never manufacture a temporary one."""
        from neurath.memory.store import control_root

        root = Path(worktree).resolve()
        roots = {root}
        try:
            roots.add(control_root(root).resolve())
        except (ValueError, OSError, CalledProcessError):
            pass
        if project_id is not None:
            projects = [self.transport.request("project/read", {
                "projectId": text(project_id, "project ID", 256)})["project"]]
        else:
            projects, cursor, seen = [], None, set()
            while True:
                page = self.transport.request("project/list", {"limit": 100, **({"cursor": cursor} if cursor else {})})
                if not isinstance(page.get("data"), list):
                    raise ValueError("saved project discovery unavailable")
                projects.extend(page["data"])
                cursor = page.get("nextCursor")
                if not cursor:
                    break
                if cursor in seen:
                    raise ValueError("saved project discovery repeated cursor")
                seen.add(cursor)
        matches = {item["id"] for item in projects if any(
            isinstance(entry.get("path"), str) and Path(entry["path"]).resolve() in roots
            for entry in item.get("roots", []))}
        if len(matches) != 1 or project_id and matches != {project_id}:
            raise ValueError("saved project missing, ambiguous, or unrelated to assigned worktree")
        return text(matches.pop(), "project ID", 256)

    def create(self, worktree, model=None, policy=ExecutionPolicy(), project_id=None, *,
               inherited_sandbox=None, source_worktree=None):
        return self._open(worktree, model, policy, project_id,
                          inherited_sandbox=inherited_sandbox, source_worktree=source_worktree)

    def restore(self, session):
        """Internal recovery worker only, after lease and native-exit verification."""
        if not isinstance(session, Session) or session.provider != "codex" or session.transport != "codex-app-server":
            raise ValueError("recovery requires a persisted Codex session")
        requested = session.policy["requested"]
        policy = ExecutionPolicy(requested["mode"], requested["approval_policy"],
                                 requested.get("approvals_reviewer"), requested.get("collaboration_mode"))
        restored = self._open(session.worktree, session.actual_model, policy,
                              requested.get("project_id"), native_session=session.native_session,
                              inherited_sandbox=requested.get("inherited_sandbox"))
        restored.policy["requested"].update(requested)
        return restored

    def _open(self, worktree, model, policy, project_id, native_session=None, *,
              inherited_sandbox=None, source_worktree=None):
        if not isinstance(policy, ExecutionPolicy):
            raise ValueError("policy must be an ExecutionPolicy")
        if policy.approval not in getattr(self.transport, "approval_policies", ("never",)):
            raise UnsupportedOperation("transport cannot handle the requested approval policy")
        if policy.collaboration_mode is not None and not getattr(self.transport, "supports_collaboration_mode", False):
            raise UnsupportedOperation("transport has not enabled the official experimental collaboration mode API")
        root = str(Path(worktree).resolve())
        state_roots = self._state_roots(Path(root)) if policy.mode == "workspace-write" else []
        inherited, native_sandbox, sandbox_config = prepare_sandbox(
            policy.mode, inherited_sandbox, root, state_roots, source_worktree)
        params = {"cwd": root, "approvalPolicy": policy.approval, "sandbox": policy.mode}
        if project_id is not None:
            project_id = self.project(root, project_id)
            params["projectId"] = project_id
        if model is not None:
            params["model"] = text(model, "model", 256)
        if policy.approvals_reviewer is not None:
            params["approvalsReviewer"] = policy.approvals_reviewer
        if sandbox_config:
            params["config"] = sandbox_config
        if native_session is not None:
            params["threadId"] = text(native_session, "persisted native session", 256)
            params.pop("projectId", None)
        response = self.transport.request("thread/resume" if native_session else "thread/start", params)
        native = text(response["thread"]["id"], "native session", 256)
        if native_session is not None and native != native_session:
            raise ValueError("host restored a different session")
        effective = {"approval_policy": response.get("approvalPolicy"),
                     "project_id": response["thread"].get("projectId"),
                     "sandbox": response.get("sandbox"),
                     "worktree": response.get("cwd"), "model": response.get("model"),
                     "approvals_reviewer": response.get("approvalsReviewer"),
                     "collaboration_mode": None}
        sandbox = effective["sandbox"]
        # Never submit the assignment when host policy is missing or different.
        matched = not (project_id is not None and (native_session is None or effective["project_id"] is not None) and effective["project_id"] != project_id
                or effective["approval_policy"] != policy.approval
                or not sandbox_matches(sandbox, native_sandbox, root)
                or effective["worktree"] != root or response["thread"].get("cwd") != root
                or not isinstance(effective["model"], str) or not effective["model"]
                or model is not None and effective["model"] != model
                or policy.approvals_reviewer is not None
                    and effective["approvals_reviewer"] != policy.approvals_reviewer)
        session = Session("codex", "codex-app-server", native, root, model,
                          response.get("model"),
                          {"requested": {**policy.requested(), "project_id": project_id, "state_write_roots": state_roots,
                                         "inherited_sandbox": inherited, "native_sandbox": native_sandbox}, "effective": effective,
                           "verification": "verified" if matched else "mismatch"})
        if not matched:
            raise CreationRejected(session)
        self._owned[native] = session
        return session

    @staticmethod
    def _state_roots(root):
        from neurath.memory.store import control_root

        shared = control_root(root).resolve()
        if shared == root:
            return []
        state = shared / ".neurath" / "local"
        if (shared / ".neurath").is_symlink() or state.is_symlink():
            raise ValueError("shared Neurath state must not be a symlink")
        # Exact required shared state only; never the other worktree's source tree.
        return [str(state)]

    def _persisted_thread(self, session):
        """Read durable metadata when a loaded thread omits its project field."""
        cursor, seen = None, set()
        while True:
            page = self.transport.request("thread/list", {
                "cwd": session.worktree, "limit": 100,
                "sourceKinds": ["cli", "vscode", "exec", "appServer"], "modelProviders": [],
                "useStateDbOnly": True,
                **({"cursor": cursor} if cursor else {})})
            if not isinstance(page.get("data"), list):
                raise ValueError("persistent project membership is unavailable")
            matches = [item for item in page["data"] if item.get("id") == session.native_session]
            if len(matches) > 1:
                raise ValueError("ambiguous persistent project membership")
            if matches:
                if matches[0].get("cwd") != session.worktree:
                    raise ValueError("persistent project workspace changed")
                return matches[0]
            cursor = page.get("nextCursor")
            if not cursor:
                return None
            if cursor in seen:
                raise ValueError("persistent project discovery repeated cursor")
            seen.add(cursor)

    def _state(self, session, *, preparation=False):
        if self._owned.get(session.native_session) is not session:
            raise ValueError("session is not owned by this adapter")
        thread = self.read(session.native_session)
        if thread.get("cwd") != session.worktree:
            raise ValueError("session workspace changed; re-evaluate access before control")
        project = thread.get("projectId")
        expected = session.policy["requested"].get("project_id")
        if project is None and expected is not None:
            persisted = self._persisted_thread(session)
            if persisted is not None:
                project = persisted.get("projectId")
            elif (preparation and session.native_session not in self._turns
                  and thread.get("status", {}).get("type") == "idle" and not thread.get("turns")):
                # Before the first turn, Codex has no rollout to list and its
                # loaded read omits projectId. The verified creation response
                # permits only the fixed bootstrap, never an assignment.
                project = expected
        if expected is not None and project != expected:
            raise ValueError("session project changed; re-evaluate affiliation before control")
        live = [turn for turn in thread.get("turns", []) if turn.get("status") == "inProgress"]
        if len(live) > 1:
            raise ValueError("ambiguous active native turn")
        if not live and thread.get("status", {}).get("type") == "active":
            # Paginated hosts do not hydrate turns in metadata reads. An owned
            # turn/start response supplies an exact ID; steer/interrupt still
            # ask the host to validate that ID, never guess another live turn.
            turn_id = self._turns.get(session.native_session)
            if turn_id is None:
                raise ValueError("active native turn is unobserved")
            live = [{"id": turn_id, "status": "inProgress"}]
        return thread, live[0] if live else None

    def message(self, session, message):
        text(message, "message")
        thread, live = self._state(session)
        if session.policy["requested"]["mode"] != "read-only":
            if thread.get("status", {}).get("type") == "idle":
                return {"delivery": "preparation-required", "native_session": session.native_session,
                        "next_operation": "bootstrap", "reason": "Start a preparation turn, then verify "
                            "fresh native readiness before sending implementation. A closed turn is not authority."}
            from neurath.providers.readiness import SessionNotReady, inspect_owned_session
            report = inspect_owned_session(session)
            if not report["implementation_ready"]:
                raise SessionNotReady(report)
        return self._submit(session, message, thread, live)

    def bootstrap(self, session):
        """Submit only the fixed activation/claim request, without an assignment.

        Native hooks must register this independent root. Failure stays observable;
        neither this prompt nor the transport handle supplies lifecycle authority.
        """
        thread, live = self._state(session, preparation=True)
        if live is not None:
            raise ValueError("bootstrap requires an idle session")
        prompt = (
            "Prepare this Neurath session only. Read repository instructions. Use the named "
            "session_status and session_inspect MCP tools. "
            + ("Then obtain this worktree's normal claim with the named worktree_claim MCP tool. "
               if session.policy["requested"]["mode"] != "read-only" else "Do not claim or edit files. ") +
            "Report actual installation, native activation, effective mode and claim results. "
            "If a required named operation is unavailable, report that exact preparation gap. "
            "Do not implement changes, edit source files, synthesize lifecycle state, override a "
            "conflicting claim or change permissions. Stop and report any failed prerequisite."
        )
        return self._submit(session, prompt, thread, live)

    def _submit(self, session, message, thread, live):
        state = thread.get("status", {})
        flags = state.get("activeFlags", [])
        if any(flag in flags for flag in ("waitingOnApproval", "waitingOnUserInput")):
            return {"delivery": "needs-input", "native_session": session.native_session,
                    "active_flags": flags}
        params = {"threadId": session.native_session, "input": [{"type": "text", "text": message}]}
        if live:
            params["expectedTurnId"] = live["id"]
            result = self.transport.request("turn/steer", params)
            turn = result["turnId"]
            if turn != live["id"]:
                raise ValueError("host steered a different turn")
        else:
            if state.get("type") != "idle":
                raise ValueError("session is not idle; read or connect through its owning host")
            requested = session.policy["requested"]
            if requested.get("native_sandbox") is not None:
                params["sandboxPolicy"] = requested["native_sandbox"]
            if requested.get("reasoning_effort") is not None:
                params["effort"] = requested["reasoning_effort"]
            if requested.get("collaboration_mode") is not None:
                params["collaborationMode"] = {"mode": requested["collaboration_mode"],
                    "settings": {"model": session.actual_model, "developer_instructions": None}}
            result = self.transport.request("turn/start", params)
            turn = text(result["turn"]["id"], "native turn", 256)
        self._turns[session.native_session] = turn
        return {"delivery": "submitted", "native_session": session.native_session,
                "native_turn": turn, "authority": "agent-report"}

    def cancel(self, session):
        _, live = self._state(session)
        if live is None:
            return {"status": "no-active-turn", "native_session": session.native_session}
        self.transport.request("turn/interrupt", {"threadId": session.native_session,
                                                  "turnId": live["id"]})
        return {"status": "interrupt-requested", "native_session": session.native_session,
                "native_turn": live["id"]}

    def resume(self, session, message):
        """Continue an idle owned conversation on the same connection, never reload it."""
        _, live = self._state(session)
        if live is not None:
            raise ValueError("session already has an active turn; use message to steer")
        return self.message(session, message)

    def connect(self, native_session):
        """Read an existing session without claiming it or starting a second runtime."""
        return self.read(native_session)
