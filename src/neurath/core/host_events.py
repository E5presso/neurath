"""Small native event translations; no host policy or progress state lives here.

Shell classification is conservative. It describes observed commands, not every
possible effect of arbitrary program internals. Unknown programs retain execute.
"""

import re
import shlex
from pathlib import Path, PurePath

from neurath.core.domain import require
from neurath.core.service import Context

READ_TOOLS = frozenset(
    {
        "Read",
        "Glob",
        "Grep",
        "read_file",
        "view_image",
        "list_mcp_resources",
        "list_mcp_resource_templates",
        "read_mcp_resource",
        "ToolSearch",
        "tool_search",
    }
)
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "apply_patch"})
DELEGATE_TOOLS = frozenset(
    {
        "Agent",
        "Task",
        "spawn_agent",
        "collaborationspawn_agent",
        "collaboration.spawn_agent",
        "followup_task",
        "collaborationfollowup_task",
        "collaboration.followup_task",
        "create_thread",
        "fork_thread",
    }
)
SHELL_TOOLS = frozenset({"Bash", "exec_command", "shell", "shell_command"})
GIT_READ = frozenset(
    {
        "status",
        "diff",
        "log",
        "show",
        "rev-parse",
        "ls-files",
        "ls-remote",
        "for-each-ref",
        "cat-file",
        "describe",
        "blame",
    }
)
GIT_EDIT = frozenset(
    {
        "add",
        "commit",
        "checkout",
        "switch",
        "restore",
        "reset",
        "merge",
        "rebase",
        "cherry-pick",
        "revert",
        "stash",
        "am",
        "apply",
        "init",
        "clone",
        "pull",
    }
)
READ_PROGRAMS = frozenset(
    {"cat", "head", "tail", "wc", "pwd", "ls", "rg", "grep", "find", "nl", "which", "ps"}
)


def context_from_event(provider, payload, receipt_id):
    require(provider in {"codex", "claude-code"}, "provider")
    session = payload.get("session_id")
    require(isinstance(session, str) and bool(session), "native-session-required")
    require(isinstance(receipt_id, str) and bool(receipt_id), "native-receipt-required")
    agent = payload.get("agent_id")
    require(agent is None or isinstance(agent, str) and bool(agent), "native-agent-required")
    actor = f"{provider}:agent:{agent}" if agent else f"{provider}:session:{session}"
    return Context(actor, session, receipt_id)


def _git_effect(tokens, index):
    index += 1
    extra = set()
    while index < len(tokens) and tokens[index].startswith("-"):
        option = tokens[index]
        if option.startswith(("-c", "--config-env")):
            extra.add("execute")
        index += 2 if option in {"-C", "-c", "--git-dir", "--work-tree", "--config-env"} else 1
    command = tokens[index] if index < len(tokens) else ""
    options = tokens[index + 1 :]
    if command == "remote" and (not options or options[0] in {"-v", "--verbose", "get-url"}):
        return extra | {"read"}
    if command == "branch" and (
        not options
        or all(
            t
            in {
                "--show-current",
                "-a",
                "--all",
                "-r",
                "--remotes",
                "-v",
                "-vv",
                "--verbose",
                "--no-color",
            }
            for t in options
        )
    ):
        return extra | {"read"}
    if command == "config" and any(
        t in {"--get", "--get-all", "--get-regexp", "--list", "-l"} for t in options
    ):
        return extra | {"read"}
    if command == "push":
        return extra | {"publish"}
    if command in {"add", "commit", "tag", "update-index"}:
        return extra | {"git"}
    if command in GIT_READ:
        if any(t.startswith("--output") for t in tokens[index + 1 :]):
            return extra | {"edit"}
        if any(t in {"--ext-diff", "--textconv"} for t in tokens[index + 1 :]):
            return extra | {"execute"}
        return extra | {"read"}
    if command in GIT_EDIT:
        return extra | {"edit"}
    if command in {"clean", "gc", "prune"}:
        return extra | {"cleanup"}
    return extra | {"execute"}


def _neurath_invocation(tokens, index):
    program = PurePath(tokens[index]).name
    args = tokens[index + 1 :]
    end = next(
        (i for i, token in enumerate(args) if token in {";", "&&", "||", "|", "&", "(", ")"}),
        len(args),
    )
    args = args[:end]
    targets = []
    if program in {"python", "python3"} or re.fullmatch(r"python3\.\d+", program):
        if args[:1] == ["-I"]:
            args = args[1:]
        if args[:2] != ["-m", "neurath"]:
            return None
        args = args[2:]
    elif program != "neurath" and not tokens[index].endswith(".neurath/run"):
        return None
    elif tokens[index].endswith(".neurath/run"):
        targets.append(str(PurePath(tokens[index]).parent.parent))
    while args:
        if args[0] == "--root" and len(args) > 1:
            targets.append(args[1])
            args = args[2:]
        elif args[0].startswith("--root="):
            targets.append(args[0].split("=", 1)[1])
            args = args[1:]
        else:
            break
    if args[:1] == ["setup"]:
        position = 1
        while position < len(args):
            token = args[position]
            if token in {"--profile", "--host", "--skill-prefix", "--auto-report"}:
                position += 2
                continue
            if not token.startswith("-"):
                targets.append(token)
                break
            position += 1
    return args, targets


def _neurath_effect(tokens, index):
    invocation = _neurath_invocation(tokens, index)
    if invocation is None:
        return None
    args, _targets = invocation
    if args[:2] == ["report", "submit"]:
        return {"execute", "publish"}
    if (
        args[:2] in (["report", "consent"], ["report", "approve"], ["releases", "choose"])
        or args[:1] == ["setup"]
        and any(value == "--auto-report" or value.startswith("--auto-report=") for value in args)
    ):
        return {"execute", "decision"}
    return {"execute"}


def _shell_effects(command):
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return frozenset({"execute"})
    effects = set()
    start = True
    for index, token in enumerate(tokens):
        if token in {";", "&&", "||", "|", "&", "(", ")"}:
            start = True
            continue
        if ">" in token and set(token) <= {">", "&", "|"}:
            following = tokens[index + 1] if index + 1 < len(tokens) else ""
            if following != "/dev/null" and not (
                token.endswith(">&") and (following.isdigit() or following == "-")
            ):
                effects.add("edit")
            continue
        program = PurePath(token).name
        # Recognize known dangerous effects even inside wrappers/substitutions;
        # a generic execute classification never erases these effects.
        if start and (
            program in {"env", "command", "exec", "nohup", "sudo", "time"}
            or token.startswith("-")
            or "=" in token
            and token.split("=", 1)[0].isidentifier()
        ):
            effects.add("execute")
            continue
        maintenance = _neurath_effect(tokens, index) if start else None
        if maintenance is not None:
            effects.update(maintenance)
        elif start and program == "git":
            effects.update(_git_effect(tokens, index))
        elif start and program == "gh" and index + 2 < len(tokens):
            group, action = tokens[index + 1 : index + 3]
            if group in {"pr", "issue", "release"} and action in {
                "create",
                "edit",
                "merge",
                "close",
                "reopen",
                "review",
                "comment",
                "delete",
                "upload",
            }:
                effects.add("publish")
            elif group in {"pr", "issue", "release", "run", "repo"} and action in {
                "view",
                "list",
                "diff",
                "checks",
                "status",
                "download",
            }:
                effects.add("read" if action != "download" else "edit")
            else:
                effects.add("execute")
        elif start:
            if (
                program == "launchctl"
                and tokens[index + 1 : index + 2] == ["print"]
                or (
                    program == "sed"
                    and tokens[index + 1 : index + 2] == ["-n"]
                    and index + 2 < len(tokens)
                    and re.fullmatch(r"\d+(?:,\d+|,\$)?p", tokens[index + 2])
                )
            ):
                effects.add("read")
            elif program in {"rm", "rmdir"}:
                effects.add("cleanup")
            elif program in {"mv", "cp", "mkdir", "touch", "tee", "install"}:
                effects.add("edit")
            elif program in READ_PROGRAMS:
                options = tokens[index + 1 :]
                effects.add(
                    "execute"
                    if any(
                        t in {"-exec", "-execdir", "--pre"} or t.startswith("--pre=")
                        for t in options
                    )
                    else "read"
                )
                if program == "find" and "-delete" in options:
                    effects.add("cleanup")
            else:
                effects.add("execute")
        start = False
    return frozenset(effects or {"execute"})


def effects_for_tool(name, tool_input, *, checks=(), cwd=None):
    name = name.rsplit("__", 1)[-1]
    if name in READ_TOOLS:
        return frozenset({"read"})
    if name in EDIT_TOOLS:
        return frozenset({"edit"})
    if name in DELEGATE_TOOLS:
        return frozenset({"delegate"})
    if name in SHELL_TOOLS:
        command = tool_input.get("command", tool_input.get("cmd"))
        if isinstance(command, str):
            effects = _shell_effects(command)
            directory = tool_input.get("workdir") or tool_input.get("cwd") or cwd
            if isinstance(directory, str) and any(
                command == check["command"]
                and Path(directory).resolve() == Path(check["cwd"]).resolve()
                for check in checks
            ):
                return (effects - {"read", "execute"}) | {"check"}
            return effects
    return frozenset({"execute"})


def stop_response(result):
    if result["allowed"]:
        return {}
    pending = ", ".join(dict.fromkeys(item["task_id"] for item in result["pending"]))
    return {
        "decision": "block",
        "reason": f"Unfinished work: {pending}. Continue the existing task; inspect task_list for its current phase and obligations.",
    }


def write_targets(name, values, cwd):
    """Resolve explicit native write destinations before checking checkout leases."""
    paths = []
    if name in {"Write", "Edit", "MultiEdit"}:
        require(isinstance(values.get("file_path"), str), "write-target-required")
        paths.append(values["file_path"])
    elif name == "apply_patch":
        patch = values.get("command", values.get("patch", ""))
        require(isinstance(patch, str), "write-target-required")
        for line in patch.splitlines():
            for marker in (
                "*** Add File: ",
                "*** Update File: ",
                "*** Delete File: ",
                "*** Move to: ",
            ):
                if line.startswith(marker):
                    paths.append(line[len(marker) :])
        require(bool(paths), "write-target-required")
    elif name in SHELL_TOOLS:
        paths.append(values.get("workdir") or values.get("cwd") or cwd)
        command = values.get("command", values.get("cmd", ""))
        try:
            lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
            lexer.whitespace_split = True
            tokens = list(lexer)
            for index, token in enumerate(tokens):
                following = tokens[index + 1] if index + 1 < len(tokens) else None
                program = PurePath(token).name
                maintenance = _neurath_invocation(tokens, index)
                if maintenance is not None:
                    paths.extend(maintenance[1])
                if token == "-C" and following is not None and "git" in tokens[:index]:
                    paths.append(tokens[index + 1])
                if token == "cd" and following is not None:
                    paths.append(tokens[index + 1])
                if ">" in token and set(token) <= {">", "&", "|"}:
                    require(following is not None, "write-target-unresolved")
                    target = following
                    if target != "/dev/null" and not (
                        token.endswith(">&") and (target.isdigit() or target == "-")
                    ):
                        paths.append(target)
                if token.startswith("--output="):
                    paths.append(token.split("=", 1)[1])
                if token == "--output" and following is not None:
                    paths.append(tokens[index + 1])
                if program in {"touch", "mkdir", "rm", "rmdir", "tee", "cp", "mv", "install"}:
                    operands = []
                    skip = False
                    for argument in tokens[index + 1 :]:
                        if argument in {";", "&&", "||", "|", "&", "(", ")", ">", ">>"}:
                            break
                        if skip:
                            skip = False
                            continue
                        if argument in {
                            "-r",
                            "--reference",
                            "-d",
                            "--date",
                            "-t",
                            "-m",
                            "--mode",
                            "-o",
                            "--owner",
                            "-g",
                            "--group",
                        } and program in {"touch", "mkdir", "install"}:
                            skip = True
                            continue
                        if not argument.startswith("-"):
                            operands.append(argument)
                    paths.extend(operands[-1:] if program in {"cp", "install"} else operands)
                if program == "find" and "-delete" in tokens[index + 1 :]:
                    for argument in tokens[index + 1 :]:
                        if argument.startswith("-") or argument in {"(", ";", "&&", "|"}:
                            break
                        paths.append(argument)
        except ValueError:
            require(False, "write-target-unresolved")
    else:
        paths.append(cwd)
    result = []
    for raw in paths:
        require(isinstance(raw, str) and bool(raw), "write-target-required")
        require(
            not any(marker in raw for marker in ("$", "`", "*", "?", "[", "~")),
            "write-target-unresolved",
        )
        path = Path(raw)
        if not path.is_absolute():
            require(isinstance(cwd, str) and bool(cwd), "write-target-required")
            path = Path(cwd) / path
        path = path.resolve()
        while not path.exists() and path.parent != path:
            path = path.parent
        if path.is_file():
            path = path.parent
        result.append(path)
    return tuple(dict.fromkeys(result))


def effect_target(name, values, cwd):
    if name in SHELL_TOOLS:
        directory = values.get("workdir") or values.get("cwd") or cwd
        require(isinstance(directory, str), "effect-target-required")
        return {
            "command": values.get("command", values.get("cmd")),
            "cwd": str(Path(directory).resolve()),
        }
    return {"tool": name, "input": values}
