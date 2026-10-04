"""Checkout identity is a resource address, never an actor or session identity."""

import os
import subprocess
from hashlib import sha256
from pathlib import Path

from neurath.core.domain import CoreError, require
from neurath.project_paths import control_root


def checkout(project_root, path):
    target = Path(path).resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        root = Path(result.stdout.strip()).resolve()
        require(control_root(root) == Path(project_root).resolve(), "foreign-project-checkout")
        return str(root)
    except (OSError, subprocess.CalledProcessError) as error:
        raise CoreError("checkout-unavailable", path=str(target)) from error


def source_subject(root):
    """Identify the current source bytes, including uncommitted work.

    Local progress records cannot invalidate their own observations. Symlink
    destinations are hashed as links and never opened outside the checkout.
    """
    root = Path(root).resolve()
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "-c", "-o", "--exclude-standard"],
        capture_output=True,
        check=True,
    )
    # A commit records the checked bytes; it does not change them. Publication
    # and review evidence carry their own exact head/subject separately.
    digest = sha256(b"neurath-source-v1\0")
    for name in sorted(set(result.stdout.split(b"\0")) - {b""}):
        relative = Path(os.fsdecode(name))
        if relative.parts[:2] == (".neurath", "local"):
            continue
        path = root / relative
        digest.update(len(name).to_bytes(8, "big") + name)
        if path.is_symlink():
            content = b"link:" + os.fsencode(os.readlink(path))
        elif path.is_file():
            content = (
                b"file:" + str(path.stat().st_mode & 0o777).encode() + b":" + path.read_bytes()
            )
        elif path.is_dir():
            content = b"submodule:" + source_subject(path).encode()
        else:
            content = b"deleted"
        digest.update(sha256(content).digest())
    return "source-sha256:" + digest.hexdigest()


def worktree_operation(command, cwd):
    """Recognize standalone Git worktree management without changing actor identity."""
    import shlex

    try:
        args = shlex.split(command)
    except ValueError:
        return None
    if (
        not args
        or Path(args[0]).name != "git"
        or any(item in {";", "&&", "||", "|"} for item in args)
    ):
        return None
    directory = Path(cwd).resolve()
    index = 1
    while index + 1 < len(args) and args[index] == "-C":
        directory = (directory / args[index + 1]).resolve()
        index += 2
    if args[index : index + 1] != ["worktree"] or index + 2 >= len(args):
        return None
    action = args[index + 1]
    if action not in {"add", "remove"}:
        return None
    operands = []
    position = index + 2
    while position < len(args):
        argument = args[position]
        if argument in {"-b", "-B", "--reason"}:
            position += 2
            continue
        if argument.startswith("-"):
            require(
                argument in {"--detach", "--lock", "--no-checkout"}, "worktree-option-unsupported"
            )
        else:
            operands.append(argument)
        position += 1
    require(bool(operands), "worktree-target-required")
    return {
        "action": action,
        "repository": str(directory),
        "target": str((directory / operands[0]).resolve()),
    }
