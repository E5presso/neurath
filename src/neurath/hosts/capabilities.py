"""Reuse retirement enforcement with repository-selected capability names and paths."""

import json
import re
import shlex
from pathlib import Path

from neurath.install.projection import skills
from neurath.install.transaction import safe_path
from neurath.runtime.engine import activate
from neurath.skill_names import public_name


def capability_policy(root):
    activate()
    from scripts.agent_harness.capability_retirement_hook import CapabilityRetirementHookApplication

    class CompoundCapabilityPolicy(CapabilityRetirementHookApplication):
        def _execution_segments(self, command, execution_root):
            from scripts.agent_harness.capability_retirement_hook import (
                CapabilityRetirementPayloadError,
            )

            try:
                return shell_segments(command, execution_root)
            except ValueError as error:
                raise CapabilityRetirementPayloadError(str(error)) from error

    config = (
        json.loads((root / ".neurath/project.json").read_text())
        if (root / ".neurath/project.json").is_file()
        else {}
    )
    protected = config.get("protected_capabilities", {})
    connectors = protected.get("connectors", [])
    paths = protected.get("paths", [])
    if not isinstance(connectors, list) or any(
        not isinstance(value, str) or not value for value in connectors
    ):
        raise ValueError("protected_capabilities.connectors must be a string array")
    if not isinstance(paths, list) or any(not isinstance(value, str) for value in paths):
        raise ValueError("protected_capabilities.paths must be a relative path array")
    for path in paths:
        safe_path(root, path)

    class RepositoryCapabilityPolicy(CompoundCapabilityPolicy):
        _PROTECTED_CONNECTORS = frozenset(value.casefold() for value in connectors)
        _PROTECTED_PATHS = (
            ".neurath",
            *paths,
            *(f"{directory}/{prefix}{name}"
              for directory in (".agents/skills", ".claude/skills")
              for prefix in ("", "neurath-") for name in skills()),
            *(f"{directory}/{public_name(name)}"
              for directory in (".agents/skills", ".claude/skills") for name in skills()),
        )

    return RepositoryCapabilityPolicy()


def _shell_command(tokens, execution_root):
    """Normalize supported execution prefixes and retain their directory effects."""
    selected = tuple(tokens)
    controls = {"if", "elif", "while", "until", "then", "do", "else", "!", "{"}
    argument_options = {
        "env": {"-u", "--unset", "-C", "--chdir"},
        "sudo": {"-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt",
                 "-C", "--close-from", "-T", "--command-timeout", "-R", "--chroot",
                 "-D", "--chdir"},
        "command": set(),
    }
    flags = {
        "env": {"-", "-i", "--ignore-environment", "-v", "--debug", "-0", "--null"},
        "sudo": {"-n", "--non-interactive", "-E", "--preserve-env", "-H", "--set-home",
                 "-k", "--reset-timestamp", "-b", "--background", "-S", "--stdin"},
        "command": {"-p"},
    }
    while selected:
        name = Path(selected[0]).name
        if selected[0] in controls or re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", selected[0]):
            selected = selected[1:]
            continue
        if name not in argument_options:
            break
        selected = selected[1:]
        while selected and selected[0].startswith("-"):
            option, *rest = selected
            selected = tuple(rest)
            if option == "--":
                break
            if name == "command" and option in {"-v", "-V", "-pv", "-pV"}:
                return (), execution_root
            key, separator, value = option.partition("=")
            if key in argument_options[name]:
                if not separator and not selected:
                    raise ValueError("execution prefix option requires an argument")
                if not separator:
                    value, *rest = selected
                    selected = tuple(rest)
                if (name == "env" and key in {"-C", "--chdir"}
                        or name == "sudo" and key in {"-D", "--chdir"}):
                    if not value or any(c in value for c in "$`~"):
                        raise ValueError("execution directory must be a literal path")
                    directory = Path(value)
                    if directory.is_absolute():
                        execution_root = directory
                    elif execution_root is not None:
                        execution_root = execution_root / directory
                elif key in {"-R", "--chroot"}:
                    raise ValueError("chroot execution cannot be inspected")
            elif option not in flags[name]:
                raise ValueError("unsupported execution prefix option")
        # Another prefix or an environment assignment may follow the options.
    return selected, execution_root


def shell_segments(command, execution_root, depth=0):
    """Split actual shell operators while preserving quoted/escaped path characters.

    This is the closed destructive-command guard, not a general shell evaluator.
    Literal shell -c wrappers are inspected with the same bounded parser.
    """
    if depth > 8:
        raise ValueError("shell wrapper nesting exceeds retirement inspection bound")
    fragments = []
    start = 0
    quote = None
    escaped = False
    comment = False
    skip_operator = False
    for index, char in enumerate(command):
        if skip_operator:
            skip_operator = False
            continue
        if comment:
            if char == "\n":
                comment = False
                start = index + 1
            continue
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote != "'":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
        elif char == "#" and (index == 0 or command[index - 1].isspace()):
            fragments.append((command[start:index], ""))
            comment = True
            start = len(command)
        elif char in ";&|()\n":
            operator = char
            if char in "&|" and command[index:index + 2] == char * 2:
                operator += char
                skip_operator = True
            fragments.append((command[start:index], operator))
            start = index + len(operator)
    if quote or escaped:
        raise ValueError("process command quoting is invalid")
    if not comment:
        fragments.append((command[start:], ""))
    segments = []
    roots = (execution_root,)
    scopes = []
    for fragment, operator in fragments:
        tokens = tuple(shlex.split(fragment, posix=True))
        destinations = []
        for root in roots:
            selected, segment_root = _shell_command(tokens, root)
            if not selected:
                continue
            segments.append((selected, segment_root))
            if selected[0] == "cd":
                arguments = selected[1:]
                while arguments and arguments[0] in {"--", "-L", "-P"}:
                    arguments = arguments[1:]
                if len(arguments) != 1 or any(c in arguments[0] for c in "$`~") or arguments[0] == "-":
                    raise ValueError("cd requires one literal directory for inspection")
                directory = Path(arguments[0])
                destinations.append(directory if directory.is_absolute() else
                                    None if segment_root is None else segment_root / directory)
            if Path(selected[0]).name in {"sh", "bash", "zsh", "dash", "ksh"}:
                for index, token in enumerate(selected[1:], 1):
                    if token.startswith("-") and "c" in token[1:] and index + 1 < len(selected):
                        segments.extend(shell_segments(selected[index + 1], segment_root, depth + 1))
                        break
        if destinations:
            # Retain every possible cwd in this scope. Shell short-circuit chains
            # can skip any later cd; relative deletion must be safe in all branches.
            roots = tuple(dict.fromkeys((*roots, *destinations)))
        if operator == "(":
            scopes.append(roots)
        elif operator == ")":
            if not scopes:
                raise ValueError("unbalanced shell scope")
            roots = scopes.pop()
        if len(roots) > 32 or len(scopes) > 32:
            raise ValueError("shell directory inspection bound exceeded")
    if scopes:
        raise ValueError("unbalanced shell scope")
    return tuple(segments)
