"""실제 Typer 정의에서 설치용 CLI 가이드를 결정적으로 생성·검증한다."""

from importlib.metadata import version

from spakky.plugins.typer.stereotypes.cli_controller import CliController
from typer import Typer
from typer.core import TyperGroup
from typer.main import get_command

from neurath.application.ports.services.skill_catalog import ISkillCatalogService
from neurath.bootstrap import create_application


def render() -> str:
    """실제 스캔된 Neurath 명령의 설명·옵션으로 가이드 본문을 만든다.

    Returns:
        str: 현재 패키지의 실제 CLI 정의와 연결된 가이드.
    """
    app = create_application().start()
    try:
        groups = {
            CliController.get(pod.type_).group_name
            for pod in app.container.pods.values()
            if CliController.exists(pod.type_) and pod.type_.__module__.startswith("neurath.")
        }
        root = get_command(app.container.get(Typer))
        assert isinstance(root, TyperGroup)
        lines = [
            f"# Neurath {version('neurath')} CLI",
            "",
            "Neurath preserves the current request, work, context and collaboration across host events. The host agent performs the actual reasoning, editing, tools and native delegation.",
            "Use this installed command: `@NEURATH_COMMAND@`. The host session and project are resolved automatically. Never invent native identities or ask the user to re-enter existing instructions. No Neurath approval token is required.",
            "",
            "## Default entry and skill selection",
            "",
            "These installed rules are the default entry for ordinary requests. The user does not need to enable a Neurath mode, enter a special command, or choose a mode before you act. Choose a suitable procedure from the request's meaning and available skill descriptions; do not ask for information already present in the request or current context.",
            "An explicitly named skill takes precedence over an inferred built-in choice. Read that selected skill's actual source, including a native, project, or user skill, and follow existing host/project instruction precedence. This built-in index does not replace those skills or grant authority to rewrite them. When the named specialist procedure needs runner tracking, pass its faithful definition through the existing custom-skill CLI path below.",
            "Simple questions, explanations, and status requests do not require a skill, task, or workflow. Single host operations such as a commit or worktree creation use the host's own tools without an unrelated procedure. Use context queries only when current stored state is needed; do not create a run merely to answer a question.",
            "For work needing a procedure, read the selected SKILL.md from the index below; do not load every skill. Reuse the task/run already handling the request. Create a task only for actual work missing from the ledger. Start a new selected built-in procedure with `@NEURATH_COMMAND@ workflow start --task-id ID --skill NAME`; inspect an existing run with `workflow show` and continue or revise it instead of creating duplicate work.",
            "Reading a skill or mentioning its name is not a started run. Confirm the returned run ID and current phase, perform the actual work with host tools, and report the phase's verified checks and evidence through `workflow report`. The existing runner owns phase attempts, result evaluation and completion conditions. Skill selection never expands the user's requested scope or grants additional execution or publishing permission.",
            "",
            "When current work context is needed, use `@NEURATH_COMMAND@ context show`. Read original sources with `context show --section sources`; select messages and work from `context show --section collaboration`. Use the host tools for actual work.",
            "",
            "Context lists default to 20 items (maximum 100). Follow each non-null cursor with the same session, section and task filter plus `--after ID`; collect that cursor's named list independently until its cursor is null. The sources section returns `{sources, next_after_id}`. Memory search also returns `next_after_id`; a full final page may require one empty follow-up. A page is not the complete TODO or all original instructions. `--task-id` filters only the current section and retains session-wide original-source references.",
            "Use `maintenance version` to inspect the invoked distribution without opening the store. JSON stdout is the result; successful command execution alone is not task success.",
            "",
            "Built-in skill definitions and installed SKILL.md instructions share the packaged catalog. Start a selected project/user procedure with `workflow start --task-id ID --skill NAME --definition @file.json` (or `--definition -` with stdin). The JSON object supplies version, phases with key/purpose/checks, optional string-valued inputs and optional source pointing to the selected SKILL.md; its source text is snapshotted without editing that file. Starting records the procedure, not completed work.",
            "Read an existing run with `workflow show --run-id ID`; its definition and attempts survive catalog or source changes. Use `workflow revise` for method changes in the same run and retain required result evaluation. For nested or finishing work, reuse an unchanged valid evaluation instead of creating a new review task or recursive reviewer. Report only the current phase's actually verified checks.",
            "",
            "## Built-in procedure index",
            "",
        ]
        for entry in app.container.get(ISkillCatalogService).list("."):
            name = entry.workflow.skill
            lines.append(
                f"- [{name}](<@NEURATH_SKILLS@/{name}/SKILL.md>) — {entry.purpose}. "
                f"Use: {entry.use_when}. Exclude: {entry.exclude}."
            )
        lines.extend(["", "## Commands", ""])
        for group_name in sorted(name for name in groups if name is not None):
            group = root.commands[group_name]
            assert isinstance(group, TyperGroup)
            for name, command in sorted(group.commands.items()):
                description = (command.help or "").splitlines()[0]
                lines.append(f"- `{group_name} {name}` — {description}")
                for parameter in command.params:
                    choices = (
                        f" choices={','.join(str(value) for value in getattr(parameter.type, 'choices'))}"
                        if hasattr(parameter.type, "choices")
                        else ""
                    )
                    options = "/".join(parameter.opts)
                    required = "required" if parameter.required else "optional"
                    multiple = " repeatable" if parameter.multiple else ""
                    lines.append(f"  - `{options}`: {required}{multiple}{choices}")
        lines.extend(
            [
                "",
                "## Execution and recovery",
                "",
                "Reuse work linked to the observed original source; create only missing work, select a matching skill when needed, perform its steps with host tools, and report actual evidence. Independent evaluation reads original sources and the full TODO; delivery is not task success. A changed method does not require a new user goal. Preserve required result evaluation.",
                "",
                "The Stop hook checks the latest tasks without running a model. Cancellation, external waiting and errors are not success. Ordinary shell tools and recovery remain available. Resolve only the actual dependency; do not ask the user to repair internal revisions or repeat approvals.",
                "",
                "Use `memory update` for current facts and `memory checkpoint` for reports. After compaction the hook restores current context; if it provides a complete-context file, read it before continuing. Requested reflection is optional and retractable. Prior lessons do not override current instructions.",
                "",
                "Installations preserve unrelated instructions and hooks. Hook trust and sandbox permissions belong to the host. File installation alone does not prove activation. Never edit trust hashes or fabricate a successful native connection.",
                "",
            ]
        )
        return "\n".join(lines)
    finally:
        app.stop()
