"""Observe local Git common directories without trusting caller Git overrides."""

import os
import subprocess
from pathlib import Path
from typing import override

from neurath.application.ports.services.directory_observer import IDirectoryObserver
from neurath.domain.errors import NeurathError
from neurath.domain.observations import DirectoryObservation


class GitDirectoryObserver(IDirectoryObserver):
    """Read canonical filesystem and Git facts without selecting project identities."""

    def _git(self, directory: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        """Run a bounded, read-only Git observation against the requested directory.

        Args:
            directory: Canonical directory in which to execute Git.
            *arguments: Git arguments passed without shell interpolation.

        Returns:
            subprocess.CompletedProcess[str]: Captured Git exit status, output, and diagnostics.

        Raises:
            NeurathError: Git inspection fails or returns malformed worktree metadata.
        """
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
    def observe(self, working_directory: str) -> DirectoryObservation:
        """Read canonical facts; Git failures never silently become non-Git observations.

        Args:
            working_directory: Existing directory supplied by the host request.

        Returns:
            DirectoryObservation: Canonical filesystem and parsed Git metadata without identity policy.

        Raises:
            NeurathError: Git inspection fails or returns malformed worktree metadata.
            ValueError: A supplied path, identifier, or directory is invalid for the operation.
        """
        directory = Path(working_directory).expanduser().resolve(strict=True)
        if not directory.is_dir():
            raise ValueError("working_directory must be a directory")
        common = self._git(directory, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if common.returncode != 0:
            if "not a git repository" not in common.stderr:
                raise NeurathError(f"Cannot inspect local Git project: {common.stderr.strip()}")
            return DirectoryObservation(working_directory=str(directory))
        listing = self._git(directory, "worktree", "list", "--porcelain", "-z")
        if listing.returncode != 0:
            raise NeurathError(f"Cannot inspect Git worktrees: {listing.stderr.strip()}")
        first_record = listing.stdout.split("\0", 1)[0]
        if not first_record.startswith("worktree "):
            raise NeurathError("Git did not return a primary worktree")
        root = Path(first_record.removeprefix("worktree ")).resolve()
        return DirectoryObservation(
            working_directory=str(directory),
            git_common_directory=str(Path(common.stdout.strip()).resolve()),
            primary_worktree=str(root),
        )
