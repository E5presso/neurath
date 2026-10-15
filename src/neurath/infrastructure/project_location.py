"""Resolve local Git common directories; never merge by remote URL or host UI name."""

import os
import subprocess
from pathlib import Path

from neurath.domain.core import CoreError, ProjectLocation


class LocalProjects:
    def resolve(self, working_directory: str) -> ProjectLocation:
        cwd = Path(working_directory).expanduser().resolve(strict=True)
        if not cwd.is_dir():
            raise ValueError("working_directory must be a directory")
        # The caller's Git environment may address an unrelated repository.
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env["LC_ALL"] = "C"

        def git(*args: str) -> subprocess.CompletedProcess:
            try:
                return subprocess.run(
                    ["git", "-C", str(cwd), *args],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise CoreError(f"Cannot inspect local Git project: {error}") from error

        common = git("rev-parse", "--path-format=absolute", "--git-common-dir")
        if common.returncode:
            if "not a git repository" not in common.stderr:
                raise CoreError(f"Cannot inspect local Git project: {common.stderr.strip()}")
            return ProjectLocation("folder", str(cwd), str(cwd), str(cwd))
        listing = git("worktree", "list", "--porcelain", "-z")
        if listing.returncode:
            raise CoreError(f"Cannot inspect Git worktrees: {listing.stderr.strip()}")
        first = listing.stdout.split("\0", 1)[0]
        if not first.startswith("worktree "):
            raise CoreError("Git did not return a primary worktree")
        root = Path(first.removeprefix("worktree ")).resolve()
        return ProjectLocation(
            "git", str(Path(common.stdout.strip()).resolve()), str(root), str(cwd)
        )
