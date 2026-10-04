"""Host-neutral skill projections and explicit stack profile selection."""

import json
import os
import re
import shlex
import sys
import tomllib
from pathlib import Path

from neurath.resources import BUNDLE
from neurath.skill_names import SKILL_NAMES, public_name, validate_skill_prefix

PROFILES = ("generic",)
HOSTS = ("codex", "claude-code")
COMMON_RULES = {
    "behavioral.md",
    "deterministic-harness.md",
    "evaluation-loops.md",
    "harness-writing.md",
    "knowledge-graph.md",
    "tool-runtime-map.md",
    "worktree-isolation.md",
    "domain-dictionary.md",
    "constructive-skeptic-policy.json",
}
EVENTS = (
    "SessionStart",
    "SessionEnd",
    "SubagentStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PreCompact",
    "Stop",
    "SubagentStop",
)
PROFILE_MODULES = {"generic": []}

CODEX_TODO_DEFAULT = (
    "\n# neurath:native-todo\n[tools.update_plan]\nenabled = true\n# /neurath:native-todo\n"
)
CLAUDE_TODO_DEFAULTS = {"CLAUDE_CODE_ENABLE_TODO_TOOLS": "1", "CLAUDE_CODE_ENABLE_TASKS": "0"}


def native_todo_defaults(host):
    """Opt in to native display tools without overriding explicit user defaults."""
    if host == "codex":
        path = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
        config = tomllib.loads(path.read_text()) if path.exists() else {}
        return "update_plan" not in config.get("tools", {})
    path = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))) / "settings.json"
    config = json.loads(path.read_text()) if path.exists() else {}
    configured = config.get("env", {})
    return {
        key: value
        for key, value in CLAUDE_TODO_DEFAULTS.items()
        if key not in configured and key not in os.environ
    }


AGENT_TOOL_GUIDANCE = """
Use the named `neurath_collaboration` MCP tools for work state and the host's native
editing and command tools for actual changes and checks.

- Recover `session_status` and `task_list`; retain the original user's goal. Define
  concrete required work once with `task_define`, use `task_start`, and display returned `native_todo`.
- Start the applicable skill on that Task. Follow `phase_read` and satisfy every
  `phase_complete` condition in order. Only fulfilled user acceptance permits
  `task_complete`. A failure, blocker, timeout or worker return never cancels work.
- Use `worktree_read`, `worktree_claim` and `worktree_release` for actual writer ownership. Reads and failure
  reports require no writer lease. Never force another actor's lease or impersonate it.
- Choose `subagent`, `session` or `cross-provider` by scope, difficulty and need.
  A worker is a role; a different checkout does not require a new session or project.
  Use `assignment_prepare`, native dispatch or `provider_prepare`, actual recipient
  reports and owner acceptance.
- Keep source kinds honest. Quote retained original input with `source_read/quote`.
  `approval_record` records an interpretation of exact input, never new host permissions.
- Reuse relevant `memory_recall`; record decisions and remaining work with
  `memory_checkpoint`. `memory_pull` is reference-only; actual adoption is explicit.
- Use `collaboration_discover`, `collaboration_inbox`, `collaboration_send` and
  `collaboration_reply` for authorized coordination. Read
  before acknowledging. Mailbox delivery alone does not wake a peer or authorize work.
  Share concrete reusable findings through `newsroom_publish`; use
  `newsroom_headlines` and `newsroom_read` for relevant findings.
- On a real harness malfunction, preserve unfinished tasks and explain the actual
  state error. Repair within the authorized scope using native tools. Native host
  permissions remain authoritative; task and phase completion still require evidence.
"""


def skills():
    return sorted(p.parent.name for p in (BUNDLE / ".agents/skills").glob("*/SKILL.md"))


def _prefix_references(text, skill_prefix):
    """Project public references once; canonical JSON contract IDs stay unchanged."""
    validate_skill_prefix(skill_prefix)
    if not skill_prefix:
        return text
    names = "|".join(re.escape(public_name(name)) for name in skills())
    pattern = (
        rf"(?P<path>\.agents/skills/)(?P<path_name>{names})(?=/)|"
        rf"(?P<slash>(?<![\w-])/)(?P<slash_name>{names})(?![\w-])|"
        rf"(?P<command>\.neurath/run skill )(?P<command_name>{names})(?![\w-])"
    )

    def projected(match):
        for kind in ("path", "slash", "command"):
            if match[kind] is not None:
                return match[kind] + skill_prefix + match[kind + "_name"]
        raise ValueError("unrecognized skill reference")

    return re.sub(pattern, projected, text)


def project_text(text, profile, skill_prefix=""):
    references = {
        ".agents/runs": ".neurath/local/runs",
        ".agents/resources": ".neurath/local/resources",
        ".agents/HARNESS_INDEX.md": ".neurath/reference/HARNESS_INDEX.md",
        ".agents/HARNESS_AUDIT.md": ".neurath/reference/HARNESS_AUDIT.md",
        ".agents/design-collaboration-policy.json": ".neurath/reference/design-collaboration-policy.json",
        ".agents/skills/core-skills.json": ".neurath/reference/core-skills.json",
        ".agents/skills/intent-routing-evals.json": ".neurath/reference/intent-routing-evals.json",
    }
    for original, projected in references.items():
        text = text.replace(original, projected)
    for internal, public in SKILL_NAMES.items():
        text = text.replace(f".agents/skills/{internal}/", f".agents/skills/{public}/")
        text = re.sub(rf"(?<![\w-])/{re.escape(internal)}(?![\w-])", f"/{public}", text)
        text = text.replace(f"`{internal}`", f"`{public}`")
        text = re.sub(
            rf"(\.neurath/run skill ){re.escape(internal)}(?![\w-])", rf"\g<1>{public}", text
        )
    text = re.sub(
        r"\.agents/rules/([A-Za-z0-9_.-]+)",
        lambda match: (
            f".neurath/rules/{match[1]}" if match[1] in COMMON_RULES else ".neurath/policy.md"
        ),
        text,
    )
    text = re.sub(
        r"docs/(?:context|decisions|plans)/[A-Za-z0-9_./-]+\.md|docs/(?:README|glossary)\.md",
        ".neurath/project.json (documents 슬롯)",
        text,
    )
    return _prefix_references(text, skill_prefix)


def asset_files(profile, hosts, skill_prefix=""):
    validate_skill_prefix(skill_prefix)
    files = {}
    contracted_skills = {
        value["source"]
        for value in json.loads((BUNDLE / ".agents/skills/core-skills.json").read_text())[
            "skills"
        ].values()
    }
    for skill in skills():
        name = public_name(skill, skill_prefix)
        source = BUNDLE / ".agents/skills" / skill
        for path in sorted(source.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            relative = path.relative_to(source).as_posix()
            dest = f".agents/skills/{name}/{relative}"
            if path.suffix == ".md":
                content = project_text(path.read_text(), profile, skill_prefix)
                if relative == "SKILL.md":
                    content = re.sub(r"(?m)^name:.*$", f"name: {name}", content, count=1)
                    # Frontmatter is retained; the authority boundary precedes the source body.
                    split = content.split("---", 2)
                    if len(split) == 3:
                        contract_guidance = (
                            f"내장 계약: `{public_name(skill)}`. 같은 Task에 `skill_start`하고 `phase_read`의 순서와 조건을 `phase_complete`로 모두 충족합니다. Task 완료가 phase를 대신하지 않습니다.\n"
                            if skill in contracted_skills
                            else ""
                        )
                        split[2] = (
                            f"\n\n먼저 `.neurath/policy.md`와 `.neurath/project.json`을 읽으세요.\n이 문서는 Neurath의 `{name}` 절차입니다. 대상 프로젝트의 지침과 설정에 연결하여 실행합니다.\n하네스 작업은 현재 노출된 명명 MCP 도구와 구조화 입력을 사용합니다. CLI 문법이나 --help를 탐색하지 않습니다. 현재 정책에서 실행할 수 없으면 구체적인 미지원 사유를 보고합니다.\n{contract_guidance}"
                            + split[2]
                        )
                        content = "---".join(split)
                files[dest] = (content.encode(), 0o644)
            else:
                files[dest] = (path.read_bytes(), path.stat().st_mode & 0o777)
    files[".neurath/policy.md"] = (
        _prefix_references(
            (BUNDLE / ".agents/rules/core-work.md").read_text(), skill_prefix
        ).encode(),
        0o644,
    )
    for source in (
        ".agents/HARNESS_INDEX.md",
        ".agents/HARNESS_AUDIT.md",
        ".agents/design-collaboration-policy.json",
        ".agents/skills/core-skills.json",
        ".agents/skills/intent-routing-evals.json",
    ):
        path = BUNDLE / source
        content = project_text(path.read_text(), profile, skill_prefix)
        if path.name in {"HARNESS_INDEX.md", "HARNESS_AUDIT.md"}:
            content = re.sub(r"\]\(rules/([^)]*)\)", lambda match: f"](../rules/{match[1]})" if match[1] in COMMON_RULES else "](../policy.md)", content)
            content = re.sub(
                r"\]\(skills/([\w-]+)/([^)]*)\)",
                lambda match: (
                    f"](../../.agents/skills/{public_name(match[1], skill_prefix)}/{match[2]})"
                ),
                content,
            )
        files[f".neurath/reference/{path.name}"] = (content.encode(), 0o644)
    for name in sorted(COMMON_RULES):
        path = BUNDLE / ".agents/rules" / name
        content = path.read_text()
        if path.suffix == ".md":
            content = (
                "<!-- Neurath: apply current project authority and .neurath/policy.md before source-specific conditions. -->\n"
                + project_text(content, profile, skill_prefix)
            )
        files[f".neurath/rules/{name}"] = (content.encode(), 0o644)
    files[".neurath/profile.json"] = (
        json.dumps(
            {
                "profile": profile,
                "check_modules": PROFILE_MODULES[profile],
                "contracts": "bundle:.agents/skills/core-skills.json",
            },
            indent=2,
        ).encode()
        + b"\n",
        0o644,
    )
    run = (
        '#!/bin/sh\nset -eu\nroot=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)\n'
        'if [ "${1:-}" = __mcp ]; then\n    shift\n    exec '
        + shlex.quote(sys.executable)
        + ' -I -m neurath.core.mcp --root "$root" "$@"\nfi\nexec '
        + shlex.quote(sys.executable)
        + ' -I -m neurath --root "$root" "$@"\n'
    )
    files[".neurath/run"] = (run.encode(), 0o755)
    from neurath.core.tool_schema import definitions

    available = {tool["name"] for tool in definitions()}

    retired_references = []
    for relative, (data, mode) in list(files.items()):
        if relative.endswith(".md") and (
            relative.startswith((".agents/skills/", ".neurath/rules/"))
            or relative == ".neurath/policy.md"
        ):
            text = data.decode()
            for token in sorted(
                set(
                    re.findall(
                        r"scripts\.(?:agent_harness|skill_harness)\.[\w.]+|"
                        r"\b(?:StateHandle|SkillStateStore|WorktreeRegistry)\b|"
                        r"\b(?:provider_wave_|delegation_wave_|workflow_|adaptive_)[a-z_]+",
                        text,
                    )
                )
            ):
                retired_references.append({"file": relative, "reference": token})
    files[".neurath/reference/task-operation-map.json"] = (
        json.dumps(
            {
                "schema": 2,
                "named_tools": sorted(available),
                "retired_references": retired_references,
            },
            ensure_ascii=False,
            indent=2,
        ).encode()
        + b"\n",
        0o644,
    )
    return files


def host_hooks(root, host):
    from neurath.project_paths import control_root

    events = EVENTS + (("PostToolUseFailure", "PermissionDenied") if host == "claude-code" else ())
    # Anchor callbacks in the common project, independently of native cwd. A
    # child worktree may be removed before its final Stop/SessionEnd delivery.
    command = shlex.join(
        [
            sys.executable,
            "-I",
            "-m",
            "neurath.core.hooks",
            "--root",
            str(control_root(root)),
            "--provider",
            host,
        ]
    )
    return {
        event: [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                        "timeout": 3 if event == "SessionEnd" and host == "codex" else 30,
                    }
                ]
            }
        ]
        for event in events
    }
