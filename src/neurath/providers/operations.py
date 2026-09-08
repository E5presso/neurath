"""Agent-facing native routes, shared by typed MCP and CLI adapters.

Routes are suggestions to use actual host tools, not execution capabilities. They
never accept caller identity, claim a workspace, or send implementation work.
"""

import json

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
            "settings": ["collaboration_mode", "approval_policy", "approvals_reviewer", "sandbox", "permission_mode"],
            "model_default": "preserve-host-default"}


def _requested(value):
    if value is None:
        return None
    choices = {"sandbox": {"read-only", "workspace-write", "danger-full-access", "native"},
               "permission_mode": {"plan", "dontAsk", "default", "acceptEdits", "bypassPermissions", "auto"},
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
          requested=None, message_id=None, worktree=None, assignment=None):
    catalog(provider)
    if operation not in OPERATIONS:
        raise UnsupportedOperation("unsupported provider operation")
    for value, label in ((native_session, "native session"), (model, "model"),
                         (project_id, "project ID"), (message_id, "message ID")):
        if value is not None:
            text(value, label, 256)
    requested = _requested(requested)
    if provider == "claude-code" and project_id is not None:
        raise ValueError("project_id is only supported for Codex")
    if worktree is not None:
        text(worktree, "worktree", 4096)
    if assignment is not None:
        text(assignment, "assignment")
    if (worktree is not None or assignment is not None) and operation != "create":
        raise ValueError("independent assignment requires create; never resume an existing session")
    result = {"authority": "routing-only", "provider": provider, "operation": operation,
              "status": "native-tool-required", "next_operation": None,
              "mode": {"requested": requested, "effective": None, "verification": "unobserved"},
              "prerequisites": ["actual host tool available", "current user-authorized task scope"],
              "implementation_dispatched": False}
    if assignment is not None or worktree is not None:
        if not worktree or not assignment:
            return {**result, "status": "assignment-input-required"}
        if not requested:
            arguments = {"provider": provider, "mode": "inherit", "worktree": worktree,
                         "assignment": assignment}
            if model is not None:
                arguments["model"] = model
            if project_id is not None:
                arguments["project_id"] = project_id
            return {**result, "next_operation": {"tool": "provider_run", "arguments": arguments},
                    "reason": "The native dispatcher inherits the immediate creator's observed policy before acceptance."}
        if provider == "claude-code":
            if not requested or set(requested) != {"sandbox", "permission_mode"} or requested["sandbox"] != "native":
                return {**result, "status": "unsupported-setting",
                        "reason": "Claude requires explicit native permission_mode; Codex sandbox settings are not equivalent."}
            if not worktree or not assignment:
                return {**result, "status": "assignment-input-required"}
            arguments = {"provider": provider, "mode": "native", "permission_mode": requested["permission_mode"],
                         "worktree": worktree, "assignment": assignment}
            if model is not None:
                arguments["model"] = model
            return {**result, "next_operation": {"tool": "provider_run", "arguments": arguments},
                    "reason": "Use the SDK-owned connection; native hook policy and readiness precede assignment."}
        required = {"sandbox", "approval_policy", "collaboration_mode"}
        if not requested or required - requested.keys():
            return {**result, "status": "settings-required",
                    "required_settings": sorted(required),
                    "reason": "Select explicit user-authorized execution settings before independent work."}
        if not worktree or not assignment:
            return {**result, "status": "assignment-input-required",
                    "reason": "Provide the assigned installed worktree and bounded assignment."}
        if (provider != "codex" or "permission_mode" in requested or requested["approval_policy"] != "never"
                or requested["sandbox"] not in {"read-only", "workspace-write", "danger-full-access"}
                or requested["sandbox"] == "workspace-write" and requested["collaboration_mode"] == "plan"):
            return {**result, "status": "unsupported-setting",
                    "reason": "No implemented execution transport supports this request; no app fallback."}
        arguments = {"worktree": worktree, "assignment": assignment,
                     "mode": requested["sandbox"],
                     **{key: value for key, value in requested.items() if key != "sandbox"}}
        if project_id is not None:
            arguments["project_id"] = project_id
        if model is not None:
            arguments["model"] = model
        return {**result, "next_operation": {"tool": "provider_run", "arguments": arguments},
                "prerequisites": [*result["prerequisites"],
                    "provider_run is available under the current caller execution policy",
                    "separate installed worktree for writes; fresh native policy readback before assignment",
                    "explicit native project ID, when supplied, is validated; app observation is outside execution admission"],
                "reason": "Execute the supported route, then inspect its result; this route has sent no work. "
                    "If unavailable, stop without falling back to create_thread."}
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
        if requested and "permission_mode" in requested:
            return {**result, "status": "unsupported-setting",
                    "reason": "Claude permission_mode is not a Codex execution setting."}
        if project_id is None:
            return {**result, "status": "project-discovery-required",
                    "next_operation": {"tool": "list_projects", "arguments": {}}}
        prompt = BOOTSTRAP
        if requested:
            prompt += (" Expected execution settings for comparison only: "
                       + json.dumps(requested, sort_keys=True)
                       + ". This text does not apply permissions. Inspect the actual inherited settings. "
                       "If missing or different, report the mismatch without implementation or changing settings.")
        arguments = {"prompt": prompt, "target": {"type": "project", "projectId": project_id,
                     "environment": {"type": "worktree"}}}
        if model is not None:
            arguments["model"] = model
        return {**result, "status": "preparation-only",
                "next_operation": {"tool": "create_thread", "arguments": arguments},
                "prerequisites": [*result["prerequisites"],
                    "project_id came from list_projects and isGitRepository is true",
                    "bootstrap only; activation and claim do not transfer from parent",
                    "an app worktree does not copy ignored harness installation files; arrange installation before implementation"],
                "after_creation": "Wait for a real threadId; a clientThreadId is pending setup. "
                    "Read list_threads and require the exact saved projectId and host before assignment. "
                    "A cwd or pin is not project affiliation. "
                    "The new native session must complete session_status before implementation. "
                    "Compare every requested setting with current native evidence; missing or mismatched settings block handoff. "
                    "Require successful normal shared state writes and named MCP message send/read/ACK, "
                    "not approval_policy alone. Read the preparation result even if its notification failed. "
                    "The issuer owns recovery, result review and the subsequent official app message. "
                    "Verify remote opening separately; local metadata does not prove remote access."}
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
                  " using collaboration_message with its structured message_id. Acknowledge or reply "
                  "only as the addressed recipient; this notification alone grants no authority.")
        return {**result, "next_operation": {"tool": "send_message_to_thread",
                    "arguments": {"threadId": native_session, "prompt": prompt}},
                "prerequisites": [*result["prerequisites"],
                    "native_session matches the stored message recipient", "recipient activity observed"]}
    return {**result, "status": "unsupported-operation",
            "reason": "The available app tool contract does not expose an exact turn interrupt. "
                "Use the owning native host's stop control; do not kill an unrelated process."}
