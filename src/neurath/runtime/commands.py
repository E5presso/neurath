"""Resolve explicitly configured project checks without assuming a toolchain."""

import json
import math
import re
from pathlib import Path


def bound_command(root, name, nodes=()):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", name):
        raise ValueError("invalid verification binding name")
    config = json.loads((Path(root) / ".neurath/project.json").read_text())
    binding = config.get("verification", {}).get(name)
    if not isinstance(binding, dict):
        raise ValueError(f"unbound verifier: {name}; configure project.json verification")
    argv = binding.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or any(not isinstance(value, str) or not value or "\0" in value for value in argv)
    ):
        raise ValueError("verification argv must be a nonempty string array")
    cwd = binding.get("cwd", ".")
    if not isinstance(cwd, str) or Path(cwd).is_absolute():
        raise ValueError("verification cwd must be repository relative")
    directory = (Path(root) / cwd).resolve()
    if not directory.is_relative_to(Path(root).resolve()) or not directory.is_dir():
        raise ValueError("verification cwd escapes repository or does not exist")
    if binding.get("success_codes", [0]) != [0]:
        raise ValueError("typed regression checks require success_codes [0]")
    timeout = binding.get("timeout_seconds", 1800)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise ValueError("timeout_seconds must be positive and at most 3600")
    expected = binding.get("stdout_contains")
    if expected is not None and (not isinstance(expected, str) or not expected):
        raise ValueError("stdout_contains must be a nonempty string")
    if nodes:
        executable = Path(argv[0]).name
        pytest = (
            executable == "pytest"
            or (executable.startswith("python") and argv[1:3] == ["-m", "pytest"])
            or (executable == "uv" and argv[1:3] == ["run", "pytest"])
        )
        if name != "pytest" or not pytest or directory != Path(root).resolve():
            raise ValueError("exact pytest nodes require a root-relative pytest argv binding")
        prefix = 1 if executable == "pytest" else 3
        if any(option not in ("-q", "--no-cov", "--disable-warnings") for option in argv[prefix:]):
            raise ValueError(
                "exact pytest binding cannot add selectors, paths or configuration overrides"
            )
        argv = [
            *argv[:prefix],
            *[o for o in argv[prefix:] if o != "-q"],
            "-v",
            "-o",
            "addopts=",
            "-o",
            "console_output_style=classic",
            "--color=no",
        ]
        for node in nodes:
            path = Path(node.partition("::")[0])
            if (
                path.is_absolute()
                or ".." in path.parts
                or not (directory / path).is_file()
                or not (directory / path).resolve().is_relative_to(directory)
            ):
                raise ValueError("pytest node must belong to the target repository")
        argv = [*argv, *nodes]
    return list(argv), directory, timeout, expected
