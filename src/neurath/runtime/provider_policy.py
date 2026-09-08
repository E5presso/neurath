"""Map native-bound policy observations; disk presence is not loaded policy.

The native readiness/controlled-launch owner supplies configuration_observation
(and target_configuration_observation) only after observing the actual scopes,
managed policy and runtime overrides. These are internal evidence fields, never
public task inputs. A target observation may describe a prepared launch; it is
not actual application evidence and must be checked again before assignment.
"""

import ast
import hashlib
import json
import os
import tomllib
from pathlib import Path

from neurath.memory.store import canonical
from neurath.providers.permission_inheritance import (
    MAPPING_REVISION, METADATA, inherit_policy, snapshot_from_evidence,
)

COVERAGE = frozenset({"settings_sources", "managed", "runtime_overrides", "rules",
                      "hook_activation", "confinement"})


class PolicyObservationError(ValueError):
    """A precise unsupported observation boundary for structured task errors."""

    def __init__(self, dimension, *, scope="source", status="unobserved"):
        self.dimension, self.scope, self.status = dimension, scope, status
        super().__init__(f"permission inheritance {status}: {scope}.{dimension}")

    def as_payload(self):
        return {"status": self.status, "scope": self.scope, "dimension": self.dimension}


def _hash(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _configuration(root, provider, evidence, *, scope="source"):
    observation = evidence.get("configuration_observation")
    allowed = {"verified", "prepared"} if scope == "target" else {"verified"}
    if observation is None:
        return _configured(root, provider, evidence, scope=scope)
    if not isinstance(observation, dict) or observation.get("status") not in allowed:
        raise PolicyObservationError("configuration_observation", scope=scope)
    if (observation.get("provider") != provider
            or observation.get("root") != str(Path(root).resolve())
            or not isinstance(observation.get("source"), str) or not observation["source"]):
        raise PolicyObservationError("configuration_binding", scope=scope)
    coverage = observation.get("coverage")
    if not isinstance(coverage, list) or not all(isinstance(v, str) for v in coverage):
        raise PolicyObservationError("configuration_coverage", scope=scope)
    missing = COVERAGE - set(coverage)
    if missing:
        raise PolicyObservationError("configuration_coverage:" + ",".join(sorted(missing)), scope=scope)
    config = observation.get("effective_settings")
    rules = observation.get("rules")
    if not isinstance(config, dict) or not isinstance(rules, list):
        raise PolicyObservationError("effective_configuration", scope=scope)
    # The adapter must resolve precedence and paths before constructing these
    # effective values. No user/project/local union or SDK-default inference here.
    for name in ("filesystem", "network"):
        if observation.get(name) not in {"unrestricted", "provider-native", "restricted", "unobserved"}:
            raise PolicyObservationError(name, scope=scope)
    return observation


def _hooks(root, provider, config):
    from neurath.install.projection import host_hooks
    from neurath.install.transaction import read_state

    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        raise PolicyObservationError("hooks")
    remainder = {event: list(entries) for event, entries in hooks.items()
                 if isinstance(entries, list)}
    if len(remainder) != len(hooks):
        raise PolicyObservationError("hooks")
    result = []
    expected = host_hooks(root, provider)
    installed = read_state(root)
    # Normalize only the COMPLETE installed native contract, including event,
    # matcher, timeout and options. A partial/disabled bundle is never equivalent.
    complete = (installed and config.get("disableAllHooks", False) is False
                and all(all(group in remainder.get(event, []) for group in groups)
                        for event, groups in expected.items()))
    if complete:
        for event, groups in expected.items():
            for group in groups:
                remainder[event].remove(group)
        result.append("neurath:" + installed["distribution"])
    remainder = {event: entries for event, entries in remainder.items() if entries}
    if remainder or config.get("disableAllHooks", False):
        result.append(provider + ":native-hooks:" + _hash({
            "hooks": remainder, "disableAllHooks": config.get("disableAllHooks", False)}))
    return result


def controls(root, provider, evidence, *, scope="source"):
    observation = _configuration(root, provider, evidence, scope=scope)
    config = observation["effective_settings"]
    permissions = config.get("permissions", {})
    if not isinstance(permissions, dict):
        raise PolicyObservationError("permissions", scope=scope)
    allow, deny = [], []
    for name, output in (("allow", allow), ("deny", deny)):
        values = permissions.get(name, [])
        if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
            raise PolicyObservationError("permissions." + name, scope=scope)
        output.extend(values)
    for rule in observation["rules"]:
        if not isinstance(rule, dict) or rule.get("decision") not in {"allow", "prompt", "forbidden"}:
            raise PolicyObservationError("native_rule", scope=scope, status="unsupported")
        (allow if rule["decision"] == "allow" else deny).append(provider + ":native-rule:" + _hash(rule))
    extra_permissions = {k: v for k, v in permissions.items() if k not in {"allow", "deny", "defaultMode"}}
    # Native opaque dimensions remain conservative but are never dropped. This
    # includes ask, additionalDirectories, managed restrictions and sandbox detail.
    extra_config = {k: v for k, v in config.items() if k not in {"permissions", "hooks", "disableAllHooks"}}
    if extra_permissions:
        deny.append(provider + ":native-permissions:" + _hash(extra_permissions))
    if extra_config:
        deny.append(provider + ":native-controls:" + _hash(extra_config))
    return {"filesystem": observation["filesystem"], "network": observation["network"],
            "tool_allowlist": sorted(set(allow)), "tool_denylist": sorted(set(deny)),
            "hooks": sorted(set(_hooks(Path(root), provider, config)))}


def planning_policy(root, identity, fields, evidence):
    """Return observation inputs only, not a mapped/actual target policy.

    Native owners attach target_configuration_observation after inspecting a
    controlled launch's resolved scopes. Do not obtain it from public fields.
    """
    source_observation = _configuration(root, identity.host, evidence)
    source_controls = controls(root, identity.host, evidence)
    target_observation = evidence.get("target_configuration_observation")
    if target_observation is None and identity.host == fields["provider"] and Path(root).resolve() == Path(fields["worktree"]).resolve():
        target_observation = evidence.get("configuration_observation")
    target_native = evidence if identity.host == fields["provider"] else {}
    target_evidence = {**target_native, "configuration_observation": target_observation}
    target_observation = _configuration(fields["worktree"], fields["provider"], target_evidence, scope="target")
    target_controls = controls(fields["worktree"], fields["provider"], target_evidence, scope="target")
    native = {k: v for k, v in evidence.items() if k not in METADATA | {
        "configuration_observation", "target_configuration_observation", "model", "reasoning_effort", "host_confinement"}}
    return {**native, "native_fields": native, "source_controls": source_controls,
            "target_controls": target_controls, "mapping_revision": MAPPING_REVISION,
            "source_observation": source_observation["source"],
            "source_observation_status": source_observation["status"],
            "host_confinement": evidence.get("host_confinement", {"status": "unobserved", "scope": "ambient-os"}),
            "target_observation": target_observation["source"],
            "target_observation_status": target_observation["status"]}


def resolve_policy(root, identity, fields, evidence):
    provider = fields["provider"]
    observed = planning_policy(root, identity, fields, evidence)
    snapshot = snapshot_from_evidence(identity.host, observed["native_fields"], source="current-native-readiness",
                                      controls=observed["source_controls"], controls_source=observed["source_observation"])
    requested = {k: fields[k] for k in ("approval_policy", "approvals_reviewer", "collaboration_mode", "permission_mode") if fields.get(k)}
    mapped = inherit_policy(snapshot, provider, requested=requested, target_controls=observed["target_controls"])
    if mapped.status != "mapped":
        raise ValueError("permission inheritance unsupported: " + ", ".join(mapped.unsupported_dimensions))
    settings = mapped.settings
    mode = fields.get("mode")
    if mode not in (None, "", "inherit", "native"):
        if provider != "codex" or settings.get("sandbox_policy", {}).get("type") != mode:
            raise ValueError("permission inheritance unsupported: requested:sandbox_policy.type")
    result = {**fields}
    if provider == "codex":
        sandbox = settings["sandbox_policy"]
        if sandbox.get("type") not in {"read-only", "workspace-write", "danger-full-access"}:
            raise ValueError("permission inheritance unsupported: sandbox_policy")
        result.update(mode=sandbox["type"], approval_policy=settings["approval_policy"],
                      approvals_reviewer=settings.get("approvals_reviewer"),
                      collaboration_mode=settings.get("collaboration_mode") or "default", permission_mode=None)
        result["inherited_sandbox"] = sandbox
    else:
        result.update(mode="native", permission_mode=settings["permission_mode"], approval_policy=None,
                      approvals_reviewer=None, collaboration_mode=None)
    result["policy_inheritance"] = {"source_provider": identity.host, "mapping_revision": mapped.mapping_revision,
                                    "settings": settings, "controls": mapped.controls,
                                    "source_observation": observed["source_observation"],
                                    "source_observation_status": observed["source_observation_status"],
                                    "host_confinement": observed["host_confinement"],
                                    "target_observation": observed["target_observation"],
                                    "target_observation_status": observed["target_observation_status"]}
    return result


def _mcp_controls(value):
    """Retain exposure policy without copying transport credentials or commands."""
    result = {}
    for namespace in ("mcp_servers", "mcpServers"):
        if namespace not in value:
            continue
        servers = value[namespace]
        if not isinstance(servers, dict):
            raise ValueError("MCP servers must be an object")
        selected = {}
        for server, settings in servers.items():
            if not isinstance(settings, dict):
                raise ValueError("MCP server settings must be an object")
            policy = {}
            for name in ("enabled", "enabled_tools", "disabled_tools"):
                if name not in settings:
                    continue
                entry = settings[name]
                if name == "enabled":
                    valid = isinstance(entry, bool)
                else:
                    valid = isinstance(entry, list) and all(isinstance(v, str) for v in entry)
                if not valid:
                    raise ValueError("invalid MCP exposure policy")
                policy[name] = entry
            if "tools" in settings:
                tool_settings = settings["tools"]
                if not isinstance(tool_settings, dict):
                    raise ValueError("MCP tools must be an object")
                tool_policy = {}
                for tool, details in tool_settings.items():
                    if not isinstance(details, dict):
                        raise ValueError("MCP tool policy must be an object")
                    selected_details = {k: v for k, v in details.items()
                                        if k in {"enabled", "approval_mode"}}
                    if ("enabled" in selected_details and not isinstance(selected_details["enabled"], bool)
                            or "approval_mode" in selected_details and not isinstance(selected_details["approval_mode"], str)):
                        raise ValueError("invalid MCP tool policy")
                    if selected_details:
                        tool_policy[tool] = selected_details
                if tool_policy:
                    policy["tools"] = tool_policy
            if policy:
                selected[server] = policy
        if selected:
            result[namespace] = selected
    for name in ("disabledMcpjsonServers", "enabledMcpjsonServers", "enableAllProjectMcpServers",
                 "disabledMcpServers", "enabledMcpServers", "allowedMcpServers", "deniedMcpServers"):
        if name in value:
            entry = value[name]
            if name == "enableAllProjectMcpServers":
                valid = isinstance(entry, bool)
            elif name in {"disabledMcpjsonServers", "enabledMcpjsonServers", "disabledMcpServers", "enabledMcpServers"}:
                valid = isinstance(entry, list) and all(isinstance(v, str) for v in entry)
            else:
                valid = isinstance(entry, list) and all(isinstance(v, dict) for v in entry)
            if not valid:
                raise ValueError("invalid MCP server selection policy")
            result[name] = entry
    return result


def _configured(root, provider, evidence, *, scope):
    """Conservative configured controls; explicitly NOT a loaded-settings claim.

    This ordinary path inherits observed native mode without requiring global OS
    introspection. Detected provider restrictions remain comparable/unsupported.
    A precise native producer may replace this path with verified observations.
    """
    root = Path(root).resolve()
    home = Path.home()
    native_config = None
    if provider == "claude-code":
        user = Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude"))
        native_config = user / ".claude.json" if os.environ.get("CLAUDE_CONFIG_DIR") else home / ".claude.json"
        paths = [user / "settings.json", root / ".claude/settings.json", root / ".claude/settings.local.json",
                 native_config, root / ".mcp.json"]
        directories = []
    else:
        user = Path(os.environ.get("CODEX_HOME", home / ".codex"))
        directories = [user, root / ".codex"]
        paths = [d / "config.toml" for d in directories] + [d / "hooks.json" for d in directories]
    config = {"permissions": {"allow": [], "deny": []}, "hooks": {}}
    opaque, rules = [], []
    for path in paths:
        if not path.exists():
            continue
        if path.is_symlink() or path.stat().st_size > 1048576:
            raise PolicyObservationError("configured_file", scope=scope, status="unsupported")
        try:
            value = tomllib.loads(path.read_text()) if path.suffix == ".toml" else json.loads(path.read_text())
            if not isinstance(value, dict):
                raise ValueError("configuration must be an object")
            if path == native_config:
                # The native file also holds account data and other projects.
                # Only MCP policy for this exact working directory is relevant.
                projects = value.get("projects", {})
                if not isinstance(projects, dict):
                    raise ValueError("native project settings must be an object")
                project = projects.get(str(root), {})
                if not isinstance(project, dict):
                    raise ValueError("native project settings must be an object")
                for selected in (value, project):
                    mcp_policy = _mcp_controls(selected)
                    if mcp_policy:
                        opaque.append(mcp_policy)
                continue
            permissions = value.get("permissions", {})
            if not isinstance(permissions, dict):
                raise ValueError("permissions must be an object")
            for name in ("allow", "deny"):
                entries = permissions.get(name, [])
                if not isinstance(entries, list) or any(not isinstance(v, str) for v in entries):
                    raise ValueError("permission entries must be strings")
                config["permissions"][name].extend(entries)
            extra = {k: v for k, v in permissions.items() if k not in {"allow", "deny", "defaultMode"}}
            if extra:
                opaque.append({"permissions": extra})
            mcp_policy = _mcp_controls(value)
            if mcp_policy:
                opaque.append(mcp_policy)
            # These are authorization settings only; model/UI/cost preferences
            # cannot cause unrelated permission inheritance failures.
            for name in ("sandbox", "sandbox_workspace_write", "apps", "browser_use", "computer_use",
                         "allowManagedPermissionRulesOnly", "allowManagedHooksOnly", "allowManagedMcpServersOnly"):
                if name == "sandbox_workspace_write" and evidence.get("sandbox_policy", {}).get("type") == "danger-full-access":
                    continue  # Inactive workspace defaults do not restrict this observed mode.
                if name == "sandbox" and isinstance(value.get(name), dict) and value[name].get("enabled") is False:
                    continue  # Disabled provider confinement says nothing about ambient OS access.
                if name in value:
                    opaque.append({name: value[name]})
            tool_options = value.get("tools", {})
            if isinstance(tool_options, dict):
                restrictions = {name: {k: v for k, v in details.items() if k in {"enabled", "approval_mode", "allowed_domains"}}
                                for name, details in tool_options.items() if isinstance(details, dict)}
                restrictions = {k: v for k, v in restrictions.items() if v}
                if restrictions:
                    opaque.append({"tools": restrictions})
            hook_config = dict(value.get("hooks", {}))
            if provider == "codex" and path.suffix == ".toml" and "state" in hook_config:
                trust = hook_config.pop("state")
                # Codex stores trusted hashes here, not event handler arrays.
                # Other fields (such as explicit disabling) remain restrictive.
                if not (isinstance(trust, dict) and all(isinstance(row, dict) and
                        set(row) <= {"trusted_hash"} for row in trust.values())):
                    opaque.append({"hook_state": trust})
            for event, entries in hook_config.items():
                if not isinstance(entries, list):
                    raise ValueError("hooks must be arrays")
                config["hooks"].setdefault(event, []).extend(entries)
            if value.get("disableAllHooks") is True:
                config["disableAllHooks"] = True
        except (ValueError, TypeError, AttributeError, OSError) as error:
            raise PolicyObservationError("configured_file", scope=scope, status="unsupported") from error
    for directory in directories:
        for path in sorted((directory / "rules").glob("*.rules")):
            if path.is_symlink() or path.stat().st_size > 1048576:
                raise PolicyObservationError("configured_rule", scope=scope, status="unsupported")
            try:
                for node in ast.parse(path.read_text()).body:
                    if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                            and isinstance(node.value.func, ast.Name) and node.value.func.id == "prefix_rule"
                            and not node.value.args):
                        raise ValueError("unmapped rule")
                    rules.append({k.arg: ast.literal_eval(k.value) for k in node.value.keywords})
            except (ValueError, TypeError, SyntaxError, OSError) as error:
                raise PolicyObservationError("configured_rule", scope=scope, status="unsupported") from error
    if opaque:
        config["configured_native_restrictions"] = opaque
    sandbox = evidence.get("sandbox_policy", {})
    mode = sandbox.get("type")
    filesystem = network = "unobserved"
    if provider == "codex" and mode in {"read-only", "workspace-write", "danger-full-access", "external-sandbox"}:
        filesystem = "unrestricted" if mode == "danger-full-access" else "provider-native"
        network = "unrestricted" if mode == "danger-full-access" or sandbox.get("network_access") is True else "restricted"
    # Above labels cover native provider restrictions, never ambient OS access.
    # Claude mode alone supplies no filesystem/network observation at all.
    return {"status": "configured", "provider": provider, "root": str(root),
            "source": "configured-candidates-plus-current-native-mode", "coverage": [],
            "effective_settings": config, "rules": rules, "filesystem": filesystem, "network": network}
