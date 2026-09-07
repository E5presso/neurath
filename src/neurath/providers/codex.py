"""Codex JSON-RPC session control, independent of subprocess and desktop UI.

The caller supplies its own authenticated transport. Discovery/read never resumes
another client’s live session. Only sessions created here accept mutations.
"""

from pathlib import Path

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

    def create(self, worktree, model=None, policy=ExecutionPolicy()):
        if not isinstance(policy, ExecutionPolicy):
            raise ValueError("policy must be an ExecutionPolicy")
        if policy.approval not in getattr(self.transport, "approval_policies", ("never",)):
            raise UnsupportedOperation("transport cannot handle the requested approval policy")
        if policy.collaboration_mode is not None and not getattr(self.transport, "supports_collaboration_mode", False):
            raise UnsupportedOperation("transport has not enabled the official experimental collaboration mode API")
        root = str(Path(worktree).resolve())
        params = {"cwd": root, "approvalPolicy": policy.approval, "sandbox": policy.mode}
        if model is not None:
            params["model"] = text(model, "model", 256)
        if policy.approvals_reviewer is not None:
            params["approvalsReviewer"] = policy.approvals_reviewer
        state_roots = self._state_roots(Path(root)) if policy.mode == "workspace-write" else []
        if state_roots:
            params["config"] = {"sandbox_workspace_write.writable_roots": state_roots}
        response = self.transport.request("thread/start", params)
        native = text(response["thread"]["id"], "native session", 256)
        effective = {"approval_policy": response.get("approvalPolicy"),
                     "sandbox": response.get("sandbox"),
                     "worktree": response.get("cwd"), "model": response.get("model"),
                     "approvals_reviewer": response.get("approvalsReviewer"),
                     "collaboration_mode": None}
        expected_type = {"read-only": "readOnly", "workspace-write": "workspaceWrite"}[policy.mode]
        sandbox = effective["sandbox"]
        # Never submit the assignment when host policy is missing or different.
        matched = not (effective["approval_policy"] != policy.approval
                or not isinstance(sandbox, dict) or sandbox.get("type") != expected_type
                or effective["worktree"] != root or response["thread"].get("cwd") != root
                or not isinstance(effective["model"], str) or not effective["model"]
                or model is not None and effective["model"] != model
                or policy.approvals_reviewer is not None
                    and effective["approvals_reviewer"] != policy.approvals_reviewer
                or sandbox.get("networkAccess") is not False)
        if matched and policy.mode == "workspace-write":
            extra = sandbox.get("writableRoots")
            allowed = {Path(root), *(Path(path) for path in state_roots)}
            matched = isinstance(extra, list) and all(
                isinstance(path, str) and Path(path).resolve() in allowed for path in extra)
            if matched:
                matched = set(state_roots).issubset({str(Path(path).resolve()) for path in extra})
        session = Session("codex", "codex-app-server", native, root, model,
                          response.get("model"),
                          {"requested": {**policy.requested(), "state_write_roots": state_roots}, "effective": effective,
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

    def _state(self, session):
        if self._owned.get(session.native_session) is not session:
            raise ValueError("session is not owned by this adapter")
        thread = self.read(session.native_session)
        if thread.get("cwd") != session.worktree:
            raise ValueError("session workspace changed; re-evaluate access before control")
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
        if session.policy["requested"]["mode"] == "workspace-write":
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
        thread, live = self._state(session)
        if live is not None:
            raise ValueError("bootstrap requires an idle session")
        prompt = (
            "Prepare this Neurath session only. Read repository instructions. Run the installed "
            ".neurath/run integrity, then .neurath/run engine scripts.agent_harness.state_cli session inspect. "
            + ("Then obtain this worktree's normal claim with .neurath/run engine "
               "scripts.agent_harness.state_cli worktree claim. "
               if session.policy["requested"]["mode"] == "workspace-write" else "Do not claim or edit files. ") +
            "Report actual installation, native activation, effective mode and claim results. "
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
