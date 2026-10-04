"""Process boundary for installed Codex/Claude hooks; work remains in the core."""

import argparse
import json
import math
import shlex
import sys
from pathlib import Path
from uuid import uuid4

from neurath.core.domain import CoreError, require
from neurath.core.hook_adapter import CONTROL_TOOLS, HookAdapter
from neurath.core.host_events import SHELL_TOOLS, effects_for_tool
from neurath.core.service import Core


def configured_checks(root):
    path = Path(root) / ".neurath/project.json"
    if not path.is_file():
        return ()
    config = json.loads(path.read_text())
    require(
        isinstance(config, dict) and isinstance(config.get("verification", {}), dict),
        "check-definition",
    )
    checks = []
    for name, value in config.get("verification", {}).items():
        require(isinstance(value, dict), "check-definition", name=name)
        argv = value.get("argv")
        require(
            isinstance(argv, list) and bool(argv) and all(isinstance(v, str) for v in argv),
            "check-definition",
            name=name,
        )
        require(isinstance(value.get("cwd", "."), str), "check-definition", name=name)
        directory = (Path(root) / value.get("cwd", ".")).resolve()
        codes = value.get("success_codes", [0])
        marker = value.get("stdout_contains")
        timeout = value.get("timeout_seconds")
        require(
            timeout is None
            or type(timeout) in {int, float}
            and math.isfinite(timeout)
            and timeout > 0,
            "check-definition",
            name=name,
        )
        require(
            isinstance(codes, list) and bool(codes) and all(type(code) is int for code in codes),
            "check-definition",
            name=name,
        )
        require(marker is None or isinstance(marker, str), "check-definition", name=name)
        checks.append(
            {
                "name": name,
                "argv": argv,
                "command": shlex.join(argv),
                "cwd": str(directory),
                "success_codes": codes,
                "stdout_contains": marker,
                "timeout_seconds": timeout,
            }
        )
    return tuple(checks)


def invoke(root, provider, payload):
    require(isinstance(payload, dict), "native-payload-required")
    event = payload.get("hook_event_name")
    require(isinstance(event, str), "native-event-required")
    checks = None
    if event == "PreToolUse":
        name, values = payload.get("tool_name"), payload.get("tool_input")
        if isinstance(name, str) and isinstance(values, dict):
            if name in CONTROL_TOOLS:
                return {}
            if name == "write_stdin":
                from neurath.core.terminal import control

                if control(values):
                    return {}
            base = effects_for_tool(name, values)
            if name in SHELL_TOOLS and base <= {"read"}:
                try:
                    from neurath.core.workspace import checkout

                    directory = values.get("workdir") or values.get("cwd") or payload.get("cwd")
                    require(isinstance(directory, str), "check-directory-required")
                    directory = Path(payload.get("cwd") or root) / directory
                    checks = configured_checks(checkout(root, directory))
                except CoreError, ValueError, OSError:
                    if base <= {"read"}:
                        return {}
                    raise
            if effects_for_tool(name, values, checks=checks or (), cwd=payload.get("cwd")) <= {
                "read"
            }:
                return {}
    core = Core(root)
    # Distinct deliveries remain distinct even when prompt text is identical.
    receipt = "hook-" + uuid4().hex
    result = HookAdapter(core, provider, checks=checks).handle(event, payload, receipt)
    if event in {"SessionStart", "UserPromptSubmit"} and not payload.get("agent_id"):
        from neurath.reporting import reporting_event
        from neurath.updates import update_event

        for notice in (reporting_event, update_event):
            try:
                result = notice(root, provider, payload, result)
            except Exception:  # advisory maintenance must not block original work
                pass
    return result


def main(arguments=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--provider", required=True, choices=("codex", "claude-code"))
    args = parser.parse_args(arguments)
    payload = {}
    try:
        payload = json.loads(sys.stdin.read(1048577))
        result = invoke(args.root, args.provider, payload)
    except Exception as error:  # noqa: BLE001 - hook boundary must deny mutations on unexpected adapter failure
        code = error.code if isinstance(error, CoreError) else "native-hook-unavailable"
        event = payload.get("hook_event_name") if isinstance(payload, dict) else None
        if event == "PreToolUse":
            result = {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "permissionDecision": "deny",
                    "permissionDecisionReason": code
                    + ": inspect the retained task and native hook inputs.",
                }
            }
        elif event in {"Stop", "SubagentStop"}:
            result = {
                "decision": "block",
                "reason": code
                + ": completion could not be verified; unfinished work remains retained.",
            }
        else:
            print(code, file=sys.stderr)
            print(json.dumps({"error": code}), flush=True)
            return 2
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
