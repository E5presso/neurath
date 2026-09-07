"""Transactional, conservative repository installation with exact byte restoration."""

import base64
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
from neurath.install.projection import HOSTS, PROFILES, asset_files, host_hooks, skills
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


def read_state(root):
    value = snapshot(Path(root), STATE)
    try:
        state = json.loads(bytes_of(value)) if value else None
    except (ValueError, TypeError) as error:
        raise InstallError("invalid installation state") from error
    if state is not None and (state.get("schema") != 1 or not isinstance(state.get("owned"), dict)):
        raise InstallError("unsupported installation state")
    if state is not None:
        try:
            validate_skill_prefix(state.get("skill_prefix", ""))
        except ValueError as error:
            raise InstallError("invalid installation skill prefix") from error
    return state


def _read_receipt(root, receipt):
    if not isinstance(receipt, str) or re.fullmatch(r"[a-f0-9]{64}", receipt) is None:
        raise InstallError("invalid installation record ID")
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


def rebase_shared(path, record, current):
    """Preserve edits outside one unchanged owned block without writing state."""
    installed = record["installed"]
    if current == installed:
        return record
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
    if (git_dir(root) / "neurath-journal.json").exists():
        raise InstallError("interrupted transaction: run neurath recover")
    if action not in {"install", "update", "uninstall", "restore"}:
        raise InstallError("unsupported action")
    state = read_state(root)
    saved = _read_receipt(root, receipt) if action == "restore" else None
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
        owned[path] = rebase_shared(path, record, observe(path))
    if action == "restore":
        for item in saved["changes"]:
            if observe(item["path"]) != item["after"]:
                raise InstallError(f"restore conflict: {item['path']}")
        for item in reversed(saved["changes"]):
            change(item["path"], item["before"])
    elif action == "uninstall":
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
        legacy_block = block.replace("Use the skills", "Use the `neurath-` skills")
        if skill_prefix:
            block = block.replace("Use the skills", f"Use the `{skill_prefix}` skills")
        managed_text("AGENTS.md", block, legacy=(legacy_block,))
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
            try:
                config = json.loads(bytes_of(old)) if old else {}
                if not isinstance(config, dict):
                    raise TypeError("settings must be an object")
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

        server = server_config(root)
        if "codex" in hosts:
            path = ".codex/config.toml"
            old = original(path)
            content = bytes_of(old).decode()
            try:
                config = tomllib.loads(content)
                if "neurath_collaboration" in config.get("mcp_servers", {}):
                    raise ValueError("reserved server name already configured")
                addition = ("\n[mcp_servers.neurath_collaboration]\ncommand = "
                            + json.dumps(server["command"], ensure_ascii=False) + "\nargs = "
                            + json.dumps(server["args"], ensure_ascii=False)
                            + "\nenabled_tools = [\"agent\"]\n"
                            + "[mcp_servers.neurath_collaboration.tools.agent]\napproval_mode = \"approve\"\n")
                tomllib.loads(content + addition)
            except (ValueError, TypeError) as error:
                raise InstallError(f"MCP settings conflict: {path}") from error
            desired[path] = file_value((content + addition).encode(), old["mode"] if old else 0o644)
        if "claude-code" in hosts:
            path = ".mcp.json"
            old = original(path)
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
            f"\n{MARKER}\n.agents/runs/\n.agents/worktrees/\n.neurath/local/\n.neurath/install.json\n.neurath/*plan*.json\n<!-- /neurath:managed -->\n".replace(
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
        change(STATE, file_value((canonical(after_state) + "\n").encode(), 0o600))
    plan = {
        "schema": 1,
        "root": str(root),
        "distribution": distribution_id(),
        "action": action,
        "profile": profile,
        "hosts": hosts,
        "skill_prefix": skill_prefix,
        "receipt": receipt,
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
    if plan.get("root") != str(root):
        raise InstallError("plan belongs to another repository")
    control = git_dir(root)
    with (control / "neurath-install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        journal = control / "neurath-journal.json"
        if journal.exists():
            raise InstallError("interrupted transaction: run neurath recover")
        for path, expected in plan.get("checks", {}).items():
            if snapshot(root, path) != expected:
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
        _save_json(journal, plan)
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
                journal.unlink(missing_ok=True)
            raise
        receipt_dir = control / "neurath-receipts"
        _save_json(receipt_dir / f"{plan['id']}.json", plan)
        journal.unlink()
        _prune_skill_directories(root, plan["changes"])
        return {"id": plan["id"], "changed": len(plan["changes"])}


def recover(root):
    root = repository(root)
    control = git_dir(root)
    with (control / "neurath-install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        journal = control / "neurath-journal.json"
        if not journal.exists():
            return {"recovered": False}
        plan = json.loads(journal.read_text())
        if plan["root"] != str(root):
            raise InstallError("journal root mismatch")
        for item in plan["changes"]:
            if snapshot(root, item["path"]) not in (item["before"], item["after"]):
                raise InstallError(f"recovery conflict: {item['path']}")
        for item in reversed(plan["changes"]):
            _write(root, item["path"], item["before"])
        journal.unlink()
        return {"recovered": True}
