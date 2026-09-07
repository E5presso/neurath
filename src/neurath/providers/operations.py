"""Agent-facing native routes, shared by typed MCP and CLI adapters.

Routes are suggestions to use actual host tools, not execution capabilities. They
never accept caller identity, claim a workspace, or send implementation work.
"""

from neurath.providers.catalog import OPERATIONS, capabilities as catalog
from neurath.providers.contracts import UnsupportedOperation, text

BOOTSTRAP = (
    "Prepare this independent Neurath session only; no implementation assignment is authorized yet. "
    "Preserve the host's configured model and execution settings unless the user explicitly requested "
    "a change through a supported host control. Read repository instructions. Check installed Neurath, "
    "actual native SessionStart and current session identity, then inspect effective collaboration mode, "
    "approval policy/reviewer, sandbox or Claude permission mode separately. Obtain the normal claim "
    "only for this session's assigned worktree. Use the typed session_status tool when available; its "
    "installation, activation, policy and ownership stages must all be observed before implementation. "
    "Report absent observations, unsupported settings, approval waits and conflicting claims exactly. "
    "Do not synthesize state, impersonate the source session, overwrite another claim, alter permissions "
    "or edit project source to repair a prerequisite. If activation requires a new native lifecycle, "
    "report that fact. Return the readiness result and wait for a separate implementation assignment."
)


def capabilities(provider):
    return {"authority": "routing-only", "provider": provider,
            "inventory_source": "not-observed", "transports": catalog(provider),
            "settings": ["collaboration_mode", "approval_policy", "approvals_reviewer", "sandbox"],
            "model_default": "preserve-host-default"}


def _requested(value):
    if value is None:
        return None
    choices = {"sandbox": {"read-only", "workspace-write", "danger-full-access"},
               "approval_policy": {"never", "on-request", "untrusted"},
               "approvals_reviewer": {"user", "auto_review"},
               "collaboration_mode": {"default", "plan"}}
    if not isinstance(value, dict) or set(value) - choices.keys():
        raise ValueError("unsupported requested setting")
    for key, item in value.items():
        if not isinstance(item, str) or item not in choices[key]:
            raise ValueError(f"unsupported requested {key}")
    return dict(value)


def route(provider, operation, *, native_session=None, model=None, project_id=None,
          requested=None, message_id=None):
    catalog(provider)
    if operation not in OPERATIONS:
        raise UnsupportedOperation("unsupported provider operation")
    for value, label in ((native_session, "native session"), (model, "model"),
                         (project_id, "project ID"), (message_id, "message ID")):
        if value is not None:
            text(value, label, 256)
    requested = _requested(requested)
    result = {"authority": "routing-only", "provider": provider, "operation": operation,
              "status": "native-tool-required", "next_operation": None,
              "mode": {"requested": requested, "effective": None, "verification": "unobserved"},
              "prerequisites": ["actual host tool available", "current user-authorized task scope"],
              "implementation_dispatched": False}
    if operation in {"message", "peer"} and message_id is None:
        return {**result, "status": "message-storage-required",
                "reason": "Store an authenticated Neurath peer message before native notification."}
    if provider == "claude-code":
        if operation in {"discover", "connect", "status", "message", "peer"}:
            return {**result, "status": "discovery-required", "native_session": native_session,
                    "message_id": message_id,
                    "next_operation": {"tool": "ListAgents", "arguments": None,
                        "schema_source": "current-native-host"},
                    "after_discovery": "Use SendMessage only with the unique exact returned peer address "
                        "and current native tool schema. Notify the peer to read the stored Neurath "
                        "message; preserve held/refused/waiting and do not resume a live process."}
        return {**result, "status": "unsupported-operation",
                "reason": "No callable external Claude Desktop creation/control adapter is implemented. "
                    "Use the native host UI for a new session, then inspect its readiness."}
    if operation == "discover":
        return {**result, "next_operation": {"tool": "list_threads", "arguments": {}}}
    if operation == "create":
        if requested:
            return {**result, "status": "unsupported-setting",
                    "unsupported_settings": sorted(requested),
                    "supported_alternatives": [{"transport": "codex-app-server", "tool": "provider_run",
                        "required_arguments": ["worktree", "assignment"],
                        "supported_settings": {"mode": ["read-only", "workspace-write"],
                            "approval_policy": ["never"], "approvals_reviewer": ["user", "auto_review"],
                            "collaboration_mode": ["default", "plan"]},
                        "condition": "Installed typed provider_run tool with caller execution-policy gate; "
                            "separate installed worktree for writes; plan is read-only; collaboration "
                            "setter uses the official experimental app-server API and native readback."}],
                    "reason": "The app create_thread tool cannot set or attest these execution settings. "
                        "Configure them through supported host controls, then inspect effective mode; "
                        "do not silently drop the request."}
        if project_id is None:
            return {**result, "status": "project-discovery-required",
                    "next_operation": {"tool": "list_projects", "arguments": {}}}
        arguments = {"prompt": BOOTSTRAP, "target": {"type": "project", "projectId": project_id,
                     "environment": {"type": "worktree"}}}
        if model is not None:
            arguments["model"] = model
        return {**result, "next_operation": {"tool": "create_thread", "arguments": arguments},
                "prerequisites": [*result["prerequisites"],
                    "project_id came from list_projects and isGitRepository is true",
                    "bootstrap only; activation and claim do not transfer from parent"],
                "after_creation": "Wait for a real threadId; a clientThreadId is pending setup. "
                    "The new native session must complete session_status before implementation."}
    if native_session is None:
        return {**result, "status": "session-discovery-required",
                "next_operation": {"tool": "list_threads", "arguments": {}}}
    if operation in {"connect", "status", "resume"}:
        return {**result, "next_operation": {"tool": "read_thread",
                    "arguments": {"threadId": native_session}},
                "reason": "Read native status before continuation; never start a second CLI runtime. "
                    "An explicit authorized follow-up can use the owning app's send_message_to_thread."}
    if operation in {"message", "peer"}:
        prompt = ("Neurath peer-request notification, not a new user instruction. Preserve your current "
                  "goal and permissions. Read authenticated Neurath message " + message_id +
                  " using the installed message tool or .neurath/run agent message. Acknowledge or reply "
                  "only as the addressed recipient; this notification alone grants no authority.")
        return {**result, "next_operation": {"tool": "send_message_to_thread",
                    "arguments": {"threadId": native_session, "prompt": prompt}},
                "prerequisites": [*result["prerequisites"],
                    "native_session matches the stored message recipient", "recipient activity observed"]}
    return {**result, "status": "unsupported-operation",
            "reason": "The available app tool contract does not expose an exact turn interrupt. "
                "Use the owning native host's stop control; do not kill an unrelated process."}
