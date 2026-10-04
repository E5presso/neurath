"""Ownership-aware preservation of user instructions and host configuration.

Adoption and rebase return snapshot values without mutating repository files or
installation state. Only verified Neurath-owned entries may be removed.
"""

import copy
import json
import re
import subprocess
import tomllib

from neurath.install.file_values import InstallError, bytes_of, file_value
from neurath.install.projection import CODEX_TODO_DEFAULT, host_hooks

MARKER = "<!-- neurath:managed -->"


def _checkout_bootstrap(root, path, value):
    """Recognize only the exact, Git-tracked source checkout host registration."""
    if path not in {
        ".codex/hooks.json",
        ".claude/settings.json",
        ".codex/config.toml",
        ".mcp.json",
    }:
        return False
    if value is None or value.get("kind") != "file":
        return False
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", "tools/checkout_host", path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if tracked.returncode:
        return False
    try:
        raw = bytes_of(value).decode()
        return _matches_checkout_bootstrap(root, path, raw)
    except UnicodeDecodeError, ValueError, TypeError, AttributeError:
        return False


def _matches_checkout_bootstrap(root, path, raw):
    from neurath.core.commands import COMMANDS

    provider = "codex" if path == ".codex/config.toml" else "claude-code"
    launcher = (
        'exec "$(git rev-parse --show-toplevel)/tools/checkout_host" mcp --provider ' + provider
    )
    server = {"command": "sh", "args": ["-c", launcher]}
    if path == ".codex/config.toml":
        parsed = tomllib.loads(raw)
        return raw.startswith("# neurath:checkout-bootstrap\n") and parsed.get(
            "mcp_servers", {}
        ).get("neurath_collaboration") == {
            **server,
            "startup_timeout_sec": 600,
            "enabled_tools": sorted(COMMANDS),
        }
    if path == ".mcp.json":
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return False
        return parsed.get("mcpServers", {}).get("neurath_collaboration") == server
    host = "codex" if path == ".codex/hooks.json" else "claude-code"
    events = list(host_hooks(root, host))
    command = (
        'hook_root="$(git rev-parse --show-toplevel)"; '
        '"$hook_root/tools/checkout_host" hook --host ' + host
    )
    expected = {
        event: [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                        "timeout": (
                            600
                            if event in {"SessionStart", "UserPromptSubmit", "PreToolUse"}
                            else 3
                            if event == "SessionEnd" and host == "codex"
                            else 30
                        ),
                    }
                ]
            }
        ]
        for event in events
    }
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        return False
    if host == "codex" and set(parsed) - {"description", "hooks"}:
        return False
    hooks = parsed.get("hooks", {})
    return all(
        isinstance(hooks.get(event), list) and hooks[event].count(groups[0]) == 1
        for event, groups in expected.items()
    )


def _portable_hook_group(host, event):
    command = (
        'hook_root="$(git rev-parse --show-toplevel)"; '
        '"$hook_root/tools/checkout_host" hook --host ' + host
    )
    return {
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": (
                    600
                    if event in {"SessionStart", "UserPromptSubmit", "PreToolUse"}
                    else 3
                    if event == "SessionEnd" and host == "codex"
                    else 30
                ),
            }
        ]
    }


def _user_host_config(root, path, value, *, portable, original=None):
    """Remove only a verified Neurath entry before comparing user settings."""
    if path == ".codex/config.toml":
        config = tomllib.loads(bytes_of(value).decode())
        del config["mcp_servers"]["neurath_collaboration"]
        if not config["mcp_servers"]:
            del config["mcp_servers"]
        if not portable and original is not None:
            previous = tomllib.loads(bytes_of(original).decode()) if original else {}
            tools = config.get("tools", {})
            if "update_plan" not in previous.get("tools", {}) and tools.get("update_plan") == {
                "enabled": True
            }:
                del tools["update_plan"]
                if not tools:
                    del config["tools"]
        return config
    config = json.loads(bytes_of(value))
    config.pop("_neurath_checkout_bootstrap", None)
    if path == ".mcp.json":
        del config["mcpServers"]["neurath_collaboration"]
        if not config["mcpServers"]:
            del config["mcpServers"]
        return config
    host = "codex" if path == ".codex/hooks.json" else "claude-code"
    for event, generated in host_hooks(root, host).items():
        group = _portable_hook_group(host, event) if portable else generated[0]
        groups = config["hooks"][event]
        groups.remove(group)
        if not groups:
            del config["hooks"][event]
    if not config["hooks"]:
        del config["hooks"]
    if host == "claude-code" and not portable:
        previous = json.loads(bytes_of(original)) if original else {}
        defaults = {"CLAUDE_CODE_ENABLE_TODO_TOOLS": "1", "CLAUDE_CODE_ENABLE_TASKS": "0"}
        env = config.get("env", {})
        for key, expected in defaults.items():
            if key not in previous.get("env", {}) and env.get(key) == expected:
                del env[key]
        if not env and "env" in config:
            del config["env"]
    return config


def _preserves_user_config(previous, current):
    if isinstance(previous, dict) and isinstance(current, dict):
        return all(
            key in current and _preserves_user_config(value, current[key])
            for key, value in previous.items()
        )
    return previous == current


def _migrate_checkout_bootstrap(root, path, record, current):
    """Adopt tracked portable registration only when existing user values survive."""
    try:
        old_raw = bytes_of(record["installed"]).decode()
        if path.endswith(".json"):
            old_config = json.loads(old_raw)
            old_config.pop("_neurath_checkout_bootstrap", None)
            old_raw = json.dumps(old_config)
        old_portable = _matches_checkout_bootstrap(root, path, old_raw)
        old_user = _user_host_config(
            root, path, record["installed"], portable=old_portable, original=record["original"]
        )
        new_user = _user_host_config(root, path, current, portable=True)
        if not _preserves_user_config(old_user, new_user):
            raise ValueError("user configuration changed during portable migration")
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise InstallError(f"modified managed file conflict: {path}") from error
    return {"original": current, "installed": current}


def _shared_span(path, content):
    prefix = b"# " if path == ".gitignore" else b""
    opening = prefix + MARKER.encode()
    closing = prefix + b"<!-- /neurath:managed -->"
    if content.count(MARKER.encode()) != 1 or content.count(b"<!-- /neurath:managed -->") != 1:
        raise InstallError(f"modified managed block conflict: {path}")
    start = end = None
    offset = 0
    for line in content.splitlines(keepends=True):
        if line.rstrip(b"\r\n") == opening:
            start = offset
        if line.rstrip(b"\r\n") == closing:
            end = offset + len(line)
        offset += len(line)
    if start is None or end is None or start >= end:
        raise InstallError(f"modified managed block conflict: {path}")
    return start, end


def _rebase_codex_config(record, current):
    """Keep user TOML bytes while replacing only the unchanged Neurath server.

    Text removal is deliberately conservative. Parse both sides and verify every
    remaining value so table-like text inside strings cannot silently lose data.
    """
    try:
        installed = tomllib.loads(bytes_of(record["installed"]).decode())
        live = bytes_of(current).decode()
        native_block = re.search(
            r"(?m)^# neurath:native-todo\r?\n\[tools\.update_plan\]\r?\n"
            r"enabled\s*=\s*true\r?\n# /neurath:native-todo\r?\n",
            live,
        )
        if (
            CODEX_TODO_DEFAULT.encode() in bytes_of(record["installed"]).replace(b"\r\n", b"\n")
            and CODEX_TODO_DEFAULT.encode()
            not in bytes_of(record["original"]).replace(b"\r\n", b"\n")
            and native_block is not None
        ):
            before = tomllib.loads(live)
            start = native_block.start()
            separator = re.search(r"(?:^|\r?\n)(\r?\n)\Z", live[:start])
            if separator:
                start -= len(separator.group(1))
            stripped = live[:start] + live[native_block.end() :]
            after = tomllib.loads(stripped)
            expected = copy.deepcopy(before)
            if expected.get("tools", {}).get("update_plan") != {"enabled": True}:
                raise ValueError("cannot isolate native TODO default")
            del expected["tools"]["update_plan"]
            if expected["tools"] == {} and "tools" not in after:
                expected.pop("tools")
            if after != expected:
                raise ValueError("native TODO block overlaps user values")
            live = stripped
        parsed = tomllib.loads(live)
        expected_server = installed["mcp_servers"]["neurath_collaboration"]
        if parsed["mcp_servers"]["neurath_collaboration"] != expected_server:
            raise ValueError("managed server changed")
        output, owned, found = [], False, False
        for line in live.splitlines(keepends=True):
            stripped = line.strip()
            if stripped.startswith("["):
                was_owned = owned
                owned = (
                    re.fullmatch(
                        r"\[mcp_servers\.neurath_collaboration(?:\.[A-Za-z0-9_]+)*\]\s*(?:#.*)?",
                        stripped,
                    )
                    is not None
                )
                if owned and not was_owned and output and not output[-1].strip():
                    output.pop()  # Remove the separator appended with this block.
                found |= owned
            if not owned or stripped.startswith("#"):
                output.append(line)
            elif "#" in line:
                # Do not discard user comments attached to an owned assignment.
                raise ValueError("inline comment in managed server")
        restored = "".join(output)
        actual = tomllib.loads(restored)
        del parsed["mcp_servers"]["neurath_collaboration"]
        for value in (parsed, actual):
            if value.get("mcp_servers") == {}:
                value.pop("mcp_servers")
        if not found or actual != parsed:
            raise ValueError("cannot isolate managed server without changing user values")
        return {"original": file_value(restored.encode(), current["mode"]), "installed": current}
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        raise InstallError("modified managed config conflict: .codex/config.toml") from error


def rebase_shared(path, record, current):
    """Preserve edits outside one unchanged owned block without writing state."""
    installed = record["installed"]
    if current == installed:
        return record
    if (
        path == ".codex/config.toml"
        and current is not None
        and current.get("kind") == installed.get("kind") == "file"
    ):
        return _rebase_codex_config(record, current)
    if (
        path not in {"AGENTS.md", "CLAUDE.md", ".gitignore"}
        or current is None
        or current.get("kind") != "file"
        or installed.get("kind") != "file"
    ):
        raise InstallError(f"modified managed file conflict: {path}")
    old = bytes_of(record["original"])
    placed, live = bytes_of(installed), bytes_of(current)
    start, end = _shared_span(path, placed)
    live_start, live_end = _shared_span(path, live)
    if live[live_start:live_end] != placed[start:end]:
        raise InstallError(f"modified managed block conflict: {path}")
    if old == placed:
        restored = live
    else:
        # Expand the exact insertion/replacement to include the entire block,
        # including installer-added separators that must disappear on uninstall.
        common = 0
        while common < min(len(old), len(placed)) and old[common] == placed[common]:
            common += 1
        tail = 0
        while (
            tail < min(len(old), len(placed)) - common
            and old[len(old) - tail - 1] == placed[len(placed) - tail - 1]
        ):
            tail += 1
        left, right = min(common, start), max(len(placed) - tail, end)
        contribution = placed[left:right]
        position = live_start - (start - left)
        if (
            position < 0
            or live[position : position + len(contribution)] != contribution
            or live.count(contribution) != 1
        ):
            raise InstallError(f"managed separator conflict: {path}")
        original_part = old[left : len(old) - (len(placed) - right)]
        restored = live[:position] + original_part + live[position + len(contribution) :]
    original = (
        None
        if record["original"] is None and not restored
        else file_value(restored, current["mode"])
    )
    return {"original": original, "installed": current}
