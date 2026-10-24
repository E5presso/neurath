"""실제 Typer 정의에서 설치용 CLI 가이드를 결정적으로 생성·검증한다."""

import argparse
from importlib.metadata import version
from pathlib import Path

from spakky.plugins.typer.stereotypes.cli_controller import CliController
from typer import Typer
from typer.core import TyperGroup
from typer.main import get_command

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
            "Start with `@NEURATH_COMMAND@ context show`. Read original sources with `context show --section sources`; select messages and work from `context show --section collaboration`. Use the host tools for actual work. Simple conversation needs no workflow.",
            "",
            "Context lists default to 20 items (maximum 100). Follow each non-null cursor with the same session, section and task filter plus `--after ID`; collect that cursor's named list independently until its cursor is null. The sources section returns `{sources, next_after_id}`. Memory search also returns `next_after_id`; a full final page may require one empty follow-up. A page is not the complete TODO or all original instructions. `--task-id` filters only the current section and retains session-wide original-source references.",
            "Use `maintenance version` to inspect the invoked distribution without opening the store. JSON stdout is the result; successful command execution alone is not task success.",
            "",
            "Built-in skill definitions and installed SKILL.md instructions share the packaged catalog. Start a selected project/user procedure with `workflow start --task-id ID --skill NAME --definition @file.json` (or `--definition -` with stdin). The JSON object supplies version, phases with key/purpose/checks, optional string-valued inputs and optional source pointing to the selected SKILL.md; its source text is snapshotted without editing that file. Starting records the procedure, not completed work.",
            "Read an existing run with `workflow show --run-id ID`; its definition and attempts survive catalog or source changes. Use `workflow revise` for method changes in the same run and retain required result evaluation. For nested or finishing work, reuse an unchanged valid evaluation instead of creating a new review task or recursive reviewer. Report only the current phase's actually verified checks.",
            "",
            "## Commands",
            "",
        ]
        for group_name in sorted(name for name in groups if name is not None):
            group = root.commands[group_name]
            assert isinstance(group, TyperGroup)
            for name, command in sorted(group.commands.items()):
                description = (command.help or "").splitlines()[0]
                lines.append(f"- `{group_name} {name}` — {description}")
                for parameter in command.params:
                    if parameter.name == "auth_token":
                        continue
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
                "Create work from the observed original source, select a matching skill, perform its steps with host tools, and report actual evidence. Independent evaluation reads original sources and the full TODO; delivery is not task success. A changed method does not require a new user goal. Preserve required result evaluation.",
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


def main() -> None:
    """생성 본문을 저장하거나 배포 가이드가 현재 정의와 같은지 검사한다.

    Raises:
        SystemExit: 검증 모드에서 가이드가 없거나 오래된 경우.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / "src/neurath/resources/cli-guide.md"
    content = render()
    if arguments.check:
        if not path.exists() or path.read_text() != content:
            raise SystemExit("CLI guide is stale; run tools/generate_cli_guide.py")
        print("CLI_GUIDE_CHECK_OK")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(path)


if __name__ == "__main__":
    main()
