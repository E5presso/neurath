"""Transactional, conservative repository installation with exact byte restoration."""

import base64
import copy
import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
import tomllib
from pathlib import Path, PurePosixPath

from neurath import __version__
from neurath.install.projection import (
    AGENT_TOOL_GUIDANCE, CODEX_TODO_DEFAULT, HOSTS, PROFILES, asset_files,
    host_hooks, native_todo_defaults, skills,
)
from neurath.install.state_store import InstallStateStore, projection
from neurath.resources import distribution_id
from neurath.skill_names import public_name, validate_skill_prefix

STATE = ".neurath/install.json"
MARKER = "<!-- neurath:managed -->"


class InstallError(RuntimeError):
    """A conflict or invalid plan prevented mutation."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def git_dir(root):
    process = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--absolute-git-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode:
        raise InstallError("target must be a Git repository")
    return Path(process.stdout.strip())


def repository(root):
    root = Path(root).resolve()
    process = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode or Path(process.stdout.strip()).resolve() != root:
        raise InstallError("target must be the Git worktree root")
    return root


def safe_path(root, relative):
    path = PurePosixPath(relative)
    if (
        not isinstance(relative, str)
        or not relative
        or path.is_absolute()
        or ".." in path.parts
        or ".git" in path.parts
        or str(path) != relative
    ):
        raise InstallError(f"unsafe path: {relative}")
    target = root / relative
    for ancestor in target.parents:
        if ancestor == root:
            break
        if ancestor.is_symlink():
            raise InstallError(f"symlink ancestor / path escape: {relative}")
        if ancestor.exists() and not ancestor.is_dir():
            raise InstallError(f"parent conflict: {relative}")
    return target


def snapshot(root, relative):
    path = safe_path(root, relative)
    if path.is_symlink():
        return {"kind": "symlink", "target": os.readlink(path)}
    if not path.exists():
        return None
    if path.is_dir():
        return {"kind": "directory"}
    if not path.is_file():
        raise InstallError(f"unsupported file: {relative}")
    return file_value(path.read_bytes(), path.stat().st_mode & 0o777)


def file_value(data, mode=0o644):
    return {"kind": "file", "data": base64.b64encode(data).decode(), "mode": mode}


def bytes_of(value):
    if value is None:
        return b""
    if value.get("kind") != "file":
        raise InstallError("conflict: expected a regular file")
    return base64.b64decode(value["data"], validate=True)


def _checkout_bootstrap(root, path, value):
    """Recognize only the exact, Git-tracked source checkout host registration."""
    if path not in {".codex/hooks.json", ".claude/settings.json",
                    ".codex/config.toml", ".mcp.json"}:
        return False
    if value is None or value.get("kind") != "file":
        return False
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", "--",
         "tools/checkout_host", path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    if tracked.returncode:
        return False
    try:
        raw = bytes_of(value).decode()
        return _matches_checkout_bootstrap(root, path, raw)
    except (UnicodeDecodeError, ValueError, TypeError, AttributeError):
        return False


def _matches_checkout_bootstrap(root, path, raw):
    from neurath.runtime.task_schema import TASKS
    launcher = 'exec "$(git rev-parse --show-toplevel)/tools/checkout_host" mcp'
    server = {"command": "sh", "args": ["-c", launcher]}
    if path == ".codex/config.toml":
        parsed = tomllib.loads(raw)
        return (raw.startswith("# neurath:checkout-bootstrap\n")
                and parsed.get("mcp_servers", {}).get("neurath_collaboration") == {
                    **server, "tool_timeout_sec": 3660, "startup_timeout_sec": 600,
                    "enabled_tools": [*TASKS, "agent"],
                    "tools": {name: {"approval_mode": "approve"} for name in (*TASKS, "agent")}})
    if path == ".mcp.json":
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return False
        return parsed.get("mcpServers", {}).get("neurath_collaboration") == server
    host = "codex" if path == ".codex/hooks.json" else "claude-code"
    events = list(host_hooks(root, host))
    command = ('hook_root="$(git rev-parse --show-toplevel)"; '
               '"$hook_root/tools/checkout_host" hook --host ' + host)
    expected = {
        event: [{"hooks": [{"type": "command", "command": command,
                            "timeout": (600 if event in {"SessionStart", "UserPromptSubmit", "PreToolUse"} else
                                        3 if event == "SessionEnd" and host == "codex" else 30)}]}]
        for event in events
    }
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        return False
    if host == "codex" and set(parsed) - {"description", "hooks"}:
        return False
    hooks = parsed.get("hooks", {})
    return all(isinstance(hooks.get(event), list)
               and hooks[event].count(groups[0]) == 1
               for event, groups in expected.items())


def _portable_hook_group(host, event):
    command = ('hook_root="$(git rev-parse --show-toplevel)"; '
               '"$hook_root/tools/checkout_host" hook --host ' + host)
    return {"hooks": [{"type": "command", "command": command,
                       "timeout": (600 if event in {"SessionStart", "UserPromptSubmit", "PreToolUse"} else
                                   3 if event == "SessionEnd" and host == "codex" else 30)}]}


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
            if ("update_plan" not in previous.get("tools", {})
                    and tools.get("update_plan") == {"enabled": True}):
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
        return all(key in current and _preserves_user_config(value, current[key])
                   for key, value in previous.items())
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
        old_user = _user_host_config(root, path, record["installed"], portable=old_portable,
                                     original=record["original"])
        new_user = _user_host_config(root, path, current, portable=True)
        if not _preserves_user_config(old_user, new_user):
            raise ValueError("user configuration changed during portable migration")
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise InstallError(f"modified managed file conflict: {path}") from error
    return {"original": current, "installed": current}


def read_state(root):
    value = snapshot(Path(root), STATE)
    try:
        visible = json.loads(bytes_of(value)) if value else None
    except (ValueError, TypeError) as error:
        raise InstallError("invalid installation state") from error
    canonical_state = InstallStateStore(root).state()
    if visible is None:
        if canonical_state is not None:
            raise InstallError("installation state projection is missing")
        return None
    if not isinstance(visible, dict):
        raise InstallError("invalid installation state")
    if visible.get("schema") == 2:
        if canonical_state is None or visible != projection(canonical_state):
            raise InstallError("installation state reference mismatch")
        state = canonical_state
    else:
        state = visible
        if canonical_state is not None and canonical_state != state:
            raise InstallError("installation state differs from canonical SQLite state")
    if state is not None and (state.get("schema") != 1 or not isinstance(state.get("owned"), dict)):
        raise InstallError("unsupported installation state")
    if state is not None:
        try:
            validate_skill_prefix(state.get("skill_prefix", ""))
        except ValueError as error:
            raise InstallError("invalid installation skill prefix") from error
    return state


_STATE_UNSPECIFIED = object()


def installation_state_matches(root, expected, *, expected_state=_STATE_UNSPECIFIED):
    """Allow only a validated schema-1/schema-2 representation difference.

    Same-schema content and permissions stay exact. The validated semantic state
    must agree with its saved bytes and with the current canonical state.
    """
    current = snapshot(Path(root), STATE)
    actual_state = read_state(root)
    try:
        expected_visible = json.loads(bytes_of(expected)) if expected is not None else None
        current_visible = json.loads(bytes_of(current)) if current is not None else None
    except (TypeError, ValueError) as error:
        raise InstallError("invalid installation state comparison") from error
    if expected_state is _STATE_UNSPECIFIED:
        if expected_visible is None or (isinstance(expected_visible, dict)
                                       and expected_visible.get("schema") == 1):
            expected_state = expected_visible
        else:
            # Without the validated state payload, only exact representation is allowed.
            return current == expected
    if expected_state is not None:
        if (not isinstance(expected_state, dict) or expected_state.get("schema") != 1
                or not isinstance(expected_state.get("owned"), dict)):
            raise InstallError("invalid expected canonical installation state")
        try:
            validate_skill_prefix(expected_state.get("skill_prefix", ""))
        except ValueError as error:
            raise InstallError("invalid expected installation skill prefix") from error
    if expected_visible != expected_state and expected_visible != projection(expected_state):
        raise InstallError("saved installation bytes differ from expected canonical state")
    if actual_state != expected_state:
        return False
    if current == expected:
        return True
    return (isinstance(current, dict) and isinstance(expected, dict)
            and current.get("kind") == expected.get("kind") == "file"
            and current.get("mode") == expected.get("mode")
            and isinstance(current_visible, dict) and isinstance(expected_visible, dict)
            and {current_visible.get("schema"), expected_visible.get("schema")} == {1, 2})


def _read_receipt(root, receipt):
    if not isinstance(receipt, str) or re.fullmatch(r"[a-f0-9]{64}", receipt) is None:
        raise InstallError("invalid installation record ID")
    try:
        stored = InstallStateStore(root).receipt(receipt)
    except ValueError as error:
        raise InstallError(str(error)) from error
    if stored is not None:
        return stored
    path = git_dir(root) / "neurath-receipts" / f"{receipt}.json"
    try:
        result = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise InstallError("installation record unavailable") from error
    if not isinstance(result, dict) or result.get("root") != str(root) or result.get("id") != receipt:
        raise InstallError("installation record belongs to a different target or ID")
    content = {key: value for key, value in result.items() if key != "id"}
    if hashlib.sha256(canonical(content).encode()).hexdigest() != receipt:
        raise InstallError("installation record integrity mismatch")
    return result


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
            r"enabled\s*=\s*true\r?\n# /neurath:native-todo\r?\n", live)
        if (CODEX_TODO_DEFAULT.encode() in bytes_of(record["installed"]).replace(b"\r\n", b"\n")
                and CODEX_TODO_DEFAULT.encode() not in bytes_of(record["original"]).replace(b"\r\n", b"\n")
                and native_block is not None):
            before = tomllib.loads(live)
            start = native_block.start()
            separator = re.search(r"(?:^|\r?\n)(\r?\n)\Z", live[:start])
            if separator:
                start -= len(separator.group(1))
            stripped = live[:start] + live[native_block.end():]
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
                owned = re.fullmatch(r"\[mcp_servers\.neurath_collaboration(?:\.[A-Za-z0-9_]+)*\]\s*(?:#.*)?", stripped) is not None
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
    if (path == ".codex/config.toml" and current is not None
            and current.get("kind") == installed.get("kind") == "file"):
        return _rebase_codex_config(record, current)
    if (path not in {"AGENTS.md", "CLAUDE.md", ".gitignore"}
            or current is None or current.get("kind") != "file"
            or installed.get("kind") != "file"):
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
        while (tail < min(len(old), len(placed)) - common
               and old[len(old) - tail - 1] == placed[len(placed) - tail - 1]):
            tail += 1
        left, right = min(common, start), max(len(placed) - tail, end)
        contribution = placed[left:right]
        position = live_start - (start - left)
        if (position < 0 or live[position:position + len(contribution)] != contribution
                or live.count(contribution) != 1):
            raise InstallError(f"managed separator conflict: {path}")
        original_part = old[left:len(old) - (len(placed) - right)]
        restored = live[:position] + original_part + live[position + len(contribution):]
    original = (None if record["original"] is None and not restored
                else file_value(restored, current["mode"]))
    return {"original": original, "installed": current}


def make_plan(root, *, action="install", profile=None, hosts=None, receipt=None, skill_prefix=None):
    root = repository(root)
    from neurath.install.cutover import require_cutover
    require_cutover(root)
    if (InstallStateStore(root).journal() is not None
            or (git_dir(root) / "neurath-journal.json").exists()):
        raise InstallError("interrupted transaction: run neurath recover")
    if action not in {"install", "update", "uninstall", "restore"}:
        raise InstallError("unsupported action")
    state = read_state(root)
    saved = _read_receipt(root, receipt) if action == "restore" else None
    before_state = state
    after_state = state
    if action == "restore":
        if "before_state" in saved:
            after_state = saved["before_state"]
        else:
            legacy = next(
                item["before"] for item in saved["changes"] if item["path"] == STATE
            )
            after_state = json.loads(bytes_of(legacy)) if legacy else None
    recorded_prefix = (
        state.get("skill_prefix", "") if state else
        saved.get("skill_prefix", "") if saved else ""
    )
    try:
        validate_skill_prefix(recorded_prefix)
        skill_prefix = validate_skill_prefix(
            recorded_prefix if skill_prefix is None else skill_prefix
        )
    except ValueError as error:
        raise InstallError(str(error)) from error
    if (state or action in {"restore", "uninstall"}) and skill_prefix != recorded_prefix:
        raise InstallError(
            "skill prefix differs from the installation record; uninstall before changing it"
        )
    profile = profile or (state["profile"] if state else "generic")
    hosts = sorted(set(hosts or (state["hosts"] if state else HOSTS)))
    if profile not in PROFILES or not hosts or any(host not in HOSTS for host in hosts):
        raise InstallError("unsupported profile or hosts")
    checks = {STATE: snapshot(root, STATE)}
    changes = []

    def observe(path):
        current = snapshot(root, path)
        checks[path] = current
        # Bind existing parent symlinks/directories to the reviewed plan as well.
        for ancestor in PurePosixPath(path).parents:
            if str(ancestor) != ".":
                checks.setdefault(str(ancestor), snapshot(root, str(ancestor)))
        return current

    def change(path, after):
        before = observe(path)
        if before != after:
            changes.append({"path": path, "before": before, "after": after})

    owned = dict(state["owned"]) if state else {}
    # Once edited, project bindings belong to the repository and are never restored away.
    project_binding = ".neurath/project.json"
    if project_binding in owned and observe(project_binding) != owned[project_binding]["installed"]:
        del owned[project_binding]
    for path, record in owned.items():
        current = observe(path)
        if (_checkout_bootstrap(root, path, current)
                and record["installed"] != current):
            owned[path] = _migrate_checkout_bootstrap(root, path, record, current)
        else:
            owned[path] = rebase_shared(path, record, current)
    if action == "restore":
        for item in saved["changes"]:
            observed = observe(item["path"])
            matches = (installation_state_matches(root, item["after"],
                       **({"expected_state": saved["after_state"]} if "after_state" in saved else {}))
                       if item["path"] == STATE else observed == item["after"])
            if not matches:
                raise InstallError(f"restore conflict: {item['path']}")
        for item in reversed(saved["changes"]):
            if item["path"] == STATE:
                continue
            change(item["path"], item["before"])
        state_value = None if after_state is None else file_value(
            (canonical(projection(after_state)) + "\n").encode(), 0o600
        )
        change(STATE, state_value)
    elif action == "uninstall":
        after_state = None
        for path, record in owned.items():
            change(path, record["original"])
        if state:
            change(STATE, None)
    else:
        desired = {}

        def original(path):
            return owned[path]["original"] if path in owned else observe(path)

        def managed_text(path, addition, legacy=()):
            if path in owned:
                current = owned[path]["installed"]
                content = bytes_of(current)
                start, end = _shared_span(path, content)
                new = addition.encode()
                new_start, new_end = _shared_span(path, new)
                desired[path] = file_value(
                    content[:start] + new[new_start:new_end] + content[end:], current["mode"]
                )
                return
            old = original(path)
            content = bytes_of(old)
            if MARKER.encode() in content:
                # A checkout can contain public instructions without a private installation record.
                # Preserve a single byte-exact known block; never adopt edited policy.
                if content.count(MARKER.encode()) == 1 and addition.encode() in content:
                    desired[path] = old
                    return
                for previous in legacy:
                    if content.count(MARKER.encode()) == 1 and previous.encode() in content:
                        desired[path] = file_value(
                            content.replace(previous.encode(), addition.encode(), 1), old["mode"]
                        )
                        return
                raise InstallError(f"unowned managed block conflict: {path}")
            data = (
                content
                + (b"\n" if content and not content.endswith(b"\n") else b"")
                + addition.encode()
            )
            desired[path] = file_value(data, old["mode"] if old else 0o644)

        block = f"\n{MARKER}\n## Neurath\n\nRead `.neurath/policy.md` and `.neurath/project.json` for the {profile} profile.\nUse the skills in `.agents/skills`; execute through `.neurath/run`.\n<!-- /neurath:managed -->\n"
        old_block = block
        legacy_block = block.replace("Use the skills", "Use the `neurath-` skills")
        block = block.replace("execute through `.neurath/run`.",
            "use the named MCP task tools. Consult `.neurath/policy.md` for explicit native execution exceptions.")
        legacy_blocks = [old_block, legacy_block]
        if skill_prefix:
            block = block.replace("Use the skills", f"Use the `{skill_prefix}` skills")
            legacy_blocks.append(old_block.replace("Use the skills", f"Use the `{skill_prefix}` skills"))
        legacy_blocks.append(block)
        block = block.replace("<!-- /neurath:managed -->", AGENT_TOOL_GUIDANCE + "<!-- /neurath:managed -->")
        managed_text("AGENTS.md", block, legacy=tuple(legacy_blocks))
        if "claude-code" in hosts:
            claude = original("CLAUDE.md")
            if claude and claude["kind"] == "symlink":
                if (root / "CLAUDE.md").resolve() != (root / "AGENTS.md").resolve():
                    raise InstallError("CLAUDE.md symlink conflict")
            elif claude is None:
                desired["CLAUDE.md"] = {"kind": "symlink", "target": "AGENTS.md"}
            else:
                managed_text("CLAUDE.md", f"\n{MARKER}\n@AGENTS.md\n<!-- /neurath:managed -->\n")
        for name in skills():
            directory = f".agents/skills/{public_name(name, skill_prefix)}"
            current = observe(directory)
            if current is not None and not any(p.startswith(directory + "/") for p in owned):
                if current["kind"] != "directory" or any(
                    not p.is_dir() or p.is_symlink() for p in (root / directory).rglob("*")
                ):
                    raise InstallError(f"unowned skill directory conflict: {directory}")
        for path, (data, mode) in asset_files(profile, hosts, skill_prefix).items():
            value = original(path)
            if path not in owned and value is not None:
                raise InstallError(f"unowned asset conflict: {path}")
            desired[path] = file_value(data, mode)
        if "claude-code" in hosts:
            native = observe(".claude/skills")
            if native and native["kind"] == "symlink":
                if (root / ".claude/skills").resolve() != (root / ".agents/skills").resolve():
                    raise InstallError(".claude/skills symlink conflict")
            else:
                for name in skills():
                    name = public_name(name, skill_prefix)
                    path = f".claude/skills/{name}"
                    if path not in owned and observe(path) is not None:
                        raise InstallError(f"skill conflict: {path}")
                    desired[path] = {
                        "kind": "symlink",
                        "target": f"../../.agents/skills/{name}",
                    }
        for host in hosts:
            path = ".codex/hooks.json" if host == "codex" else ".claude/settings.json"
            old = original(path)
            if _checkout_bootstrap(root, path, old):
                desired[path] = old
                continue
            try:
                config = json.loads(bytes_of(old)) if old else {}
                if not isinstance(config, dict):
                    raise TypeError("settings must be an object")
                if host == "claude-code":
                    defaults = native_todo_defaults(host)
                    if defaults:
                        env = config.setdefault("env", {})
                        if not isinstance(env, dict):
                            raise TypeError("settings env must be an object")
                        for key, value in defaults.items():
                            env.setdefault(key, value)
                hooks = config.setdefault("hooks", {})
                if not isinstance(hooks, dict):
                    raise TypeError("hooks must be an object")
                for event, groups in host_hooks(root, host).items():
                    if not isinstance(hooks.setdefault(event, []), list):
                        raise TypeError("event hooks must be an array")
                    hooks[event].extend(groups)
            except (ValueError, TypeError) as error:
                raise InstallError(f"invalid settings conflict: {path}") from error
            desired[path] = file_value(
                json.dumps(config, indent=2, ensure_ascii=False).encode() + b"\n",
                old["mode"] if old else 0o644,
            )
        # User configuration remains user owned; defaults are restored only if untouched.
        project = ".neurath/project.json"
        current_project = observe(project)
        if current_project is None:
            desired[project] = file_value(
                json.dumps({"schema": 1, "documents": {}, "verification": {}}, indent=2).encode()
                + b"\n"
            )
        elif project in owned:
            desired[project] = owned[project]["installed"]
        from neurath.agents.mcp import server_config
        from neurath.runtime.task_schema import TASKS

        server = server_config(root)
        if "codex" in hosts:
            path = ".codex/config.toml"
            old = original(path)
            if _checkout_bootstrap(root, path, old):
                desired[path] = old
            else:
                content = bytes_of(old).decode()
                try:
                    config = tomllib.loads(content)
                    if "neurath_collaboration" in config.get("mcp_servers", {}):
                        raise ValueError("reserved server name already configured")
                    if "update_plan" not in config.get("tools", {}) and native_todo_defaults("codex"):
                        content += CODEX_TODO_DEFAULT
                    addition = ("\n[mcp_servers.neurath_collaboration]\ncommand = "
                                + json.dumps(server["command"], ensure_ascii=False) + "\nargs = "
                                + json.dumps(server["args"], ensure_ascii=False)
                                # The verifier allows up to 3600s, plus response/readback time.
                                + "\ntool_timeout_sec = 3660"
                                + "\nenabled_tools = " + json.dumps([*TASKS, "agent"]) + "\n"
                                + "".join(f"[mcp_servers.neurath_collaboration.tools.{name}]\napproval_mode = \"approve\"\n"
                                          for name in (*TASKS, "agent")))
                    tomllib.loads(content + addition)
                except (ValueError, TypeError) as error:
                    raise InstallError(f"MCP settings conflict: {path}") from error
                desired[path] = file_value((content + addition).encode(), old["mode"] if old else 0o644)
        if "claude-code" in hosts:
            path = ".mcp.json"
            old = original(path)
            if _checkout_bootstrap(root, path, old):
                desired[path] = old
            else:
                try:
                    config = json.loads(bytes_of(old)) if old else {}
                    if not isinstance(config, dict) or not isinstance(config.setdefault("mcpServers", {}), dict):
                        raise ValueError("MCP settings must be objects")
                    if "neurath_collaboration" in config["mcpServers"]:
                        raise ValueError("reserved server name already configured")
                    config["mcpServers"]["neurath_collaboration"] = server
                except (ValueError, TypeError) as error:
                    raise InstallError(f"MCP settings conflict: {path}") from error
                desired[path] = file_value((json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode(),
                                           old["mode"] if old else 0o644)
        managed_text(
            ".gitignore",
            f"\n{MARKER}\n.agents/runs/\n.agents/worktrees/\n.agents/resources/worktrees/\n.monitor-pr/\n.neurath/local/\n.neurath/install.json\n.neurath/*plan*.json\n<!-- /neurath:managed -->\n".replace(
                "<!--", "# <!--"
            ).replace("##", "#"),
        )
        new_owned = {}
        for path, after in desired.items():
            before = original(path)
            new_owned[path] = {"original": before, "installed": after}
            change(path, after)
        for path, record in owned.items():
            if path not in desired:
                change(path, record["original"])
        after_state = {
            "schema": 1,
            "version": __version__,
            "distribution": distribution_id(),
            "profile": profile,
            "hosts": hosts,
            "skill_prefix": skill_prefix,
            "owned": new_owned,
        }
        change(
            STATE,
            file_value((canonical(projection(after_state)) + "\n").encode(), 0o600),
        )
    plan = {
        "schema": 1,
        "root": str(root),
        "distribution": distribution_id(),
        "action": action,
        "profile": profile,
        "hosts": hosts,
        "skill_prefix": skill_prefix,
        "receipt": receipt,
        "before_state": before_state,
        "after_state": after_state,
        "checks": checks,
        "changes": changes,
    }
    plan["id"] = hashlib.sha256(canonical(plan).encode()).hexdigest()
    return plan


def _write(root, relative, value):
    path = safe_path(root, relative)
    if value is None:
        if path.exists() or path.is_symlink():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if value["kind"] == "symlink":
        target = value["target"]
        resolved = (path.parent / target).resolve()
        if not resolved.is_relative_to(root):
            raise InstallError(f"symlink target escapes: {relative}")
        temporary = path.with_name(path.name + ".neurath-tmp")
        if temporary.exists() or temporary.is_symlink():
            raise InstallError(f"temporary path conflict: {temporary}")
        try:
            temporary.symlink_to(target)
            temporary.replace(path)
        finally:
            if temporary.is_symlink():
                temporary.unlink()
    else:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(bytes_of(value))
            file.flush()
            os.fsync(file.fileno())
        try:
            temporary.chmod(value["mode"])
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def _save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
        temp = Path(file.name)
        file.write((canonical(value) + "\n").encode())
        file.flush()
        os.fsync(file.fileno())
    temp.chmod(0o600)
    temp.replace(path)


def _prune_skill_directories(root, changes):
    """Remove only empty ancestors of successfully retired, owned skill files."""
    directories = set()
    for item in changes:
        parts = PurePosixPath(item["path"]).parts
        if (item["after"] is None and len(parts) > 3
                and parts[:2] == (".agents", "skills")):
            for length in range(3, len(parts)):
                directories.add(PurePosixPath(*parts[:length]))
    for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        try:
            safe_path(root, str(directory)).rmdir()
        except (OSError, InstallError):
            # User additions and cosmetic cleanup failures never invalidate an installation.
            pass


def apply_plan(root, plan):
    root = repository(root)
    from neurath.install.cutover import require_cutover
    require_cutover(root)
    if plan.get("root") != str(root):
        raise InstallError("plan belongs to another repository")
    control = git_dir(root)
    with (control / "neurath-install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        existing = InstallStateStore(root)
        if (existing.journal() is not None
                or (control / "neurath-journal.json").exists()):
            raise InstallError("interrupted transaction: run neurath recover")
        for path, expected_value in plan.get("checks", {}).items():
            if snapshot(root, path) != expected_value:
                raise InstallError(f"stale plan: {path}")
        expected = make_plan(
            root,
            action=plan["action"],
            profile=plan["profile"],
            hosts=plan["hosts"],
            receipt=plan.get("receipt"),
            skill_prefix=plan.get("skill_prefix"),
        )
        if expected != plan:
            raise InstallError("stale or modified plan: regenerate with this distribution")
        if not plan["changes"]:
            return {"id": plan["id"], "changed": 0}
        store = InstallStateStore(root, create=True)
        try:
            store.import_legacy_files(control)
            store.ensure_state(plan["before_state"])
            store.begin(plan)
        except ValueError as error:
            raise InstallError(str(error)) from error
        applied = []
        try:
            for item in plan["changes"]:
                if snapshot(root, item["path"]) != item["before"]:
                    raise InstallError(f"concurrent change: {item['path']}")
                _write(root, item["path"], item["after"])
                applied.append(item)
        except BaseException:
            rollback_conflict = False
            for item in reversed(applied):
                if snapshot(root, item["path"]) == item["after"]:
                    _write(root, item["path"], item["before"])
                elif snapshot(root, item["path"]) != item["before"]:
                    rollback_conflict = True
            if not rollback_conflict:
                store.discard(plan["id"])
            raise
        try:
            store.finish(plan, plan["after_state"])
        except ValueError as error:
            raise InstallError(str(error)) from error
        _prune_skill_directories(root, plan["changes"])
        return {"id": plan["id"], "changed": len(plan["changes"])}


def recover(root):
    root = repository(root)
    control = git_dir(root)
    with (control / "neurath-install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        store = InstallStateStore(root, create=True)
        try:
            store.import_legacy_files(control)
            plan = store.journal()
        except ValueError as error:
            raise InstallError(str(error)) from error
        if plan is None:
            return {"recovered": False}
        if plan["root"] != str(root):
            raise InstallError("journal root mismatch")
        for item in plan["changes"]:
            if snapshot(root, item["path"]) not in (item["before"], item["after"]):
                raise InstallError(f"recovery conflict: {item['path']}")
        for item in reversed(plan["changes"]):
            _write(root, item["path"], item["before"])
        store.discard(plan["id"])
        return {"recovered": True}
