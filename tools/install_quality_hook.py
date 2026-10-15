"""Install a worktree-local quality hook while preserving an existing user hook."""

import os
import shlex
import subprocess
from pathlib import Path

MARKER = "# neurath-quality-hook-v1"


def git_environment() -> dict[str, str]:
    """Ignore inherited hook repository overrides when targeting a checkout explicitly.

    Returns:
        dict[str, str]: Process environment without inherited Git repository overrides.
    """
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def git(root: Path, *arguments: str) -> str:
    """Read or update Git configuration for the explicitly selected checkout.

    Args:
        root: Root directory of the checkout to inspect.
        *arguments: Git arguments passed without shell interpolation.

    Returns:
        str: Git standard output with surrounding whitespace removed.
    """
    return subprocess.check_output(
        ["git", "-C", str(root), *arguments], text=True, env=git_environment()
    ).strip()


def optional_config(root: Path, scope: str, key: str) -> str | None:
    """Read a configuration value without confusing absence with an execution failure.

    Args:
        root: Root directory of the checkout to inspect.
        scope: Git configuration scope flag, or an empty string for effective settings.
        key: Git configuration key to read.

    Returns:
        str | None: Effective value, or None when Git reports an absent key.
    """
    result = subprocess.run(
        ["git", "-C", str(root), "config", *([scope] if scope else []), "--get", key],
        text=True,
        capture_output=True,
        env=git_environment(),
        check=False,
    )
    if result.returncode == 1:
        return None
    result.check_returncode()
    return result.stdout.strip()


def install(root: Path) -> Path:
    """Install only in this worktree's private Git directory and chain its prior hook.

    Args:
        root: Root directory of the checkout to inspect.

    Returns:
        Path: Installed worktree-private hook path, preserving the previous hook.

    Raises:
        RuntimeError: The operation would overwrite existing configuration or destroy retained records.
    """
    root = Path(git(root, "rev-parse", "--show-toplevel"))
    git_directory = Path(git(root, "rev-parse", "--absolute-git-dir"))
    destination = git_directory / "neurath-quality-hooks"
    hook = destination / "pre-commit"
    current_hooks = optional_config(root, "", "core.hooksPath")
    if current_hooks is not None and Path(current_hooks) == destination:
        if hook.is_file() and MARKER in hook.read_text():
            return hook
        raise RuntimeError("Managed hook path exists without the expected hook; inspect manually")
    if destination.exists():
        raise RuntimeError("Refusing to overwrite an existing hook directory")
    if optional_config(root, "--local", "core.worktree") is not None:
        raise RuntimeError("Explicit core.worktree requires manual worktreeConfig migration")
    if optional_config(root, "--local", "core.bare") == "true":
        raise RuntimeError("Bare repositories do not support this checkout hook")
    if current_hooks is None:
        previous = Path(git(root, "rev-parse", "--git-path", "hooks/pre-commit"))
    else:
        previous = Path(current_hooks) / "pre-commit"
    if not previous.is_absolute():
        previous = root / previous
    script = "#!/bin/sh\nset -eu\n" + MARKER + "\n"
    script += f"previous={shlex.quote(str(previous))}\n"
    script += 'if [ -x "$previous" ]; then "$previous" "$@"; fi\n'
    script += "exec uv run --locked pre-commit run --hook-stage pre-commit\n"
    destination.mkdir()
    hook.write_text(script)
    hook.chmod(0o755)
    # This extension enables isolated per-worktree settings; no existing values are replaced.
    git(root, "config", "--local", "extensions.worktreeConfig", "true")
    git(root, "config", "--worktree", "core.hooksPath", str(destination))
    return hook


def main() -> None:
    """Install the hook for the checkout containing this tool."""
    print(install(Path(__file__).resolve().parents[1]))


if __name__ == "__main__":
    main()
