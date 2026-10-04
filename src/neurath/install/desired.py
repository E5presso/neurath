"""Build desired installation snapshots while recording observed preconditions.

The projection builder owns no persistence or filesystem writes. Every source
snapshot comes from the planner's observer, keeping user-file and parent checks
attached to the plan that the transaction will revalidate under its lock.
"""

import json
import tomllib

from neurath.install.configuration import MARKER, _checkout_bootstrap, _shared_span
from neurath.install.file_values import InstallError, bytes_of, file_value
from neurath.install.projection import (
    AGENT_TOOL_GUIDANCE,
    CODEX_TODO_DEFAULT,
    asset_files,
    host_hooks,
    native_todo_defaults,
    skills,
)
from neurath.skill_names import public_name


class InstallationProjection:
    def __init__(self, root, owned, observe):
        self.root = root
        self.owned = owned
        self.observe = observe
        self.desired = {}

    def original(self, path):
        return self.owned[path]["original"] if path in self.owned else self.observe(path)

    def managed_text(self, path, addition, legacy=()):
        if path in self.owned:
            current = self.owned[path]["installed"]
            content = bytes_of(current)
            start, end = _shared_span(path, content)
            new = addition.encode()
            new_start, new_end = _shared_span(path, new)
            self.desired[path] = file_value(
                content[:start] + new[new_start:new_end] + content[end:], current["mode"]
            )
            return
        old = self.original(path)
        content = bytes_of(old)
        if MARKER.encode() in content:
            # A checkout can contain public instructions without a private installation record.
            # Preserve a single byte-exact known block; never adopt edited policy.
            if content.count(MARKER.encode()) == 1 and addition.encode() in content:
                self.desired[path] = old
                return
            for previous in legacy:
                if content.count(MARKER.encode()) == 1 and previous.encode() in content:
                    self.desired[path] = file_value(
                        content.replace(previous.encode(), addition.encode(), 1), old["mode"]
                    )
                    return
            raise InstallError(f"unowned managed block conflict: {path}")
        data = (
            content
            + (b"\n" if content and not content.endswith(b"\n") else b"")
            + addition.encode()
        )
        self.desired[path] = file_value(data, old["mode"] if old else 0o644)

    def build(self, profile, hosts, skill_prefix):
        self._instructions(profile, hosts, skill_prefix)
        self._assets(profile, hosts, skill_prefix)
        self._host_settings(hosts)
        self._project_binding()
        self._mcp_settings(hosts)
        self.managed_text(
            ".gitignore",
            f"\n{MARKER}\n.agents/runs/\n.agents/worktrees/\n.agents/resources/worktrees/\n.monitor-pr/\n.neurath/local/\n.neurath/install.json\n.neurath/*plan*.json\n<!-- /neurath:managed -->\n".replace(
                "<!--", "# <!--"
            ).replace("##", "#"),
        )
        return self.desired

    def _instructions(self, profile, hosts, skill_prefix):
        root = self.root
        desired = self.desired
        block = f"\n{MARKER}\n## Neurath\n\nRead `.neurath/policy.md` and `.neurath/project.json` for the {profile} profile.\nUse the skills in `.agents/skills`; execute through `.neurath/run`.\n<!-- /neurath:managed -->\n"
        old_block = block
        legacy_block = block.replace("Use the skills", "Use the `neurath-` skills")
        block = block.replace(
            "execute through `.neurath/run`.",
            "use the named MCP task tools. Consult `.neurath/policy.md` for explicit native execution exceptions.",
        )
        legacy_blocks = [old_block, legacy_block]
        if skill_prefix:
            block = block.replace("Use the skills", f"Use the `{skill_prefix}` skills")
            legacy_blocks.append(
                old_block.replace("Use the skills", f"Use the `{skill_prefix}` skills")
            )
        legacy_blocks.append(block)
        block = block.replace(
            "<!-- /neurath:managed -->", AGENT_TOOL_GUIDANCE + "<!-- /neurath:managed -->"
        )
        self.managed_text("AGENTS.md", block, legacy=tuple(legacy_blocks))
        if "claude-code" in hosts:
            claude = self.original("CLAUDE.md")
            if claude and claude["kind"] == "symlink":
                if (root / "CLAUDE.md").resolve() != (root / "AGENTS.md").resolve():
                    raise InstallError("CLAUDE.md symlink conflict")
            elif claude is None:
                desired["CLAUDE.md"] = {"kind": "symlink", "target": "AGENTS.md"}
            else:
                self.managed_text(
                    "CLAUDE.md", f"\n{MARKER}\n@AGENTS.md\n<!-- /neurath:managed -->\n"
                )

    def _assets(self, profile, hosts, skill_prefix):
        root = self.root
        owned = self.owned
        observe = self.observe
        desired = self.desired
        for name in skills():
            directory = f".agents/skills/{public_name(name, skill_prefix)}"
            current = observe(directory)
            if (
                current is not None
                and not any(p.startswith(directory + "/") for p in owned)
                and (
                    current["kind"] != "directory"
                    or any(not p.is_dir() or p.is_symlink() for p in (root / directory).rglob("*"))
                )
            ):
                raise InstallError(f"unowned skill directory conflict: {directory}")
        for path, (data, mode) in asset_files(profile, hosts, skill_prefix).items():
            value = self.original(path)
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

    def _host_settings(self, hosts):
        root = self.root
        desired = self.desired
        for host in hosts:
            path = ".codex/hooks.json" if host == "codex" else ".claude/settings.json"
            old = self.original(path)
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

    def _project_binding(self):
        owned = self.owned
        observe = self.observe
        desired = self.desired
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

    def _mcp_settings(self, hosts):
        root = self.root
        desired = self.desired
        from neurath.core.mcp import server_config
        from neurath.core.service import COMMANDS

        if "codex" in hosts:
            server = server_config(root, "codex")
            path = ".codex/config.toml"
            old = self.original(path)
            if _checkout_bootstrap(root, path, old):
                desired[path] = old
            else:
                content = bytes_of(old).decode()
                try:
                    config = tomllib.loads(content)
                    if "neurath_collaboration" in config.get("mcp_servers", {}):
                        raise ValueError("reserved server name already configured")
                    if "update_plan" not in config.get("tools", {}) and native_todo_defaults(
                        "codex"
                    ):
                        content += CODEX_TODO_DEFAULT
                    addition = (
                        "\n[mcp_servers.neurath_collaboration]\ncommand = "
                        + json.dumps(server["command"], ensure_ascii=False)
                        + "\nargs = "
                        + json.dumps(server["args"], ensure_ascii=False)
                        + "\nenabled_tools = "
                        + json.dumps(sorted(COMMANDS))
                        + "\n"
                    )
                    tomllib.loads(content + addition)
                except (ValueError, TypeError) as error:
                    raise InstallError(f"MCP settings conflict: {path}") from error
                desired[path] = file_value(
                    (content + addition).encode(), old["mode"] if old else 0o644
                )
        if "claude-code" in hosts:
            server = server_config(root, "claude-code")
            path = ".mcp.json"
            old = self.original(path)
            if _checkout_bootstrap(root, path, old):
                desired[path] = old
            else:
                try:
                    config = json.loads(bytes_of(old)) if old else {}
                    if not isinstance(config, dict) or not isinstance(
                        config.setdefault("mcpServers", {}), dict
                    ):
                        raise TypeError("MCP settings must be objects")
                    if "neurath_collaboration" in config["mcpServers"]:
                        raise ValueError("reserved server name already configured")
                    config["mcpServers"]["neurath_collaboration"] = server
                except (ValueError, TypeError) as error:
                    raise InstallError(f"MCP settings conflict: {path}") from error
                desired[path] = file_value(
                    (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode(),
                    old["mode"] if old else 0o644,
                )
