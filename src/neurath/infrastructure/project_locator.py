"""Observe local Git common directories without trusting caller Git overrides."""

import os
import subprocess
from pathlib import Path
from typing import override

from neurath.application.ports.services.project_locator import IProjectLocator
from neurath.domain.aggregates.project import ProjectKind, ProjectLocation
from neurath.domain.errors import NeurathError


class GitProjectLocator(IProjectLocator):
    """Distinguish clones while unifying primary and linked worktrees."""

    def _git(self, directory: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        """Run a bounded, read-only Git observation against the requested directory."""
        environment = dict(os.environ)
        for key in tuple(environment):
            if key.startswith("GIT_"):
                del environment[key]
        environment["LC_ALL"] = "C"
        try:
            return subprocess.run(
                ["git", "-C", str(directory), *arguments],
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise NeurathError(f"Cannot inspect local Git project: {error}") from error

    @override
    def locate(self, working_directory: str) -> ProjectLocation:
        """Return canonical identity; Git failures never silently create folder projects."""
        directory = Path(working_directory).expanduser().resolve(strict=True)
        if not directory.is_dir():
            raise ValueError("working_directory must be a directory")
        common = self._git(directory, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if common.returncode != 0:
            if "not a git repository" not in common.stderr:
                raise NeurathError(f"Cannot inspect local Git project: {common.stderr.strip()}")
            return ProjectLocation(
                kind=ProjectKind.FOLDER,
                identity_path=str(directory),
                root_path=str(directory),
                working_directory=str(directory),
            )
        listing = self._git(directory, "worktree", "list", "--porcelain", "-z")
        if listing.returncode != 0:
            raise NeurathError(f"Cannot inspect Git worktrees: {listing.stderr.strip()}")
        first_record = listing.stdout.split("\0", 1)[0]
        if not first_record.startswith("worktree "):
            raise NeurathError("Git did not return a primary worktree")
        root = Path(first_record.removeprefix("worktree ")).resolve()
        return ProjectLocation(
            kind=ProjectKind.GIT,
            identity_path=str(Path(common.stdout.strip()).resolve()),
            root_path=str(root),
            working_directory=str(directory),
        )
