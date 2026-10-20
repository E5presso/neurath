"""호출자가 설정한 Git 환경을 신뢰하지 않고 로컬 공통 디렉터리를 관찰한다."""

import os
import subprocess
from pathlib import Path
from typing import override

from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.directory_observer import IDirectoryObserver
from neurath.domain.errors import NeurathError
from neurath.domain.observations import DirectoryObservation


@Pod()
class GitDirectoryObserver(IDirectoryObserver):
    """프로젝트 동일성을 선택하지 않고 파일 시스템과 Git의 정규화된 사실을 읽는다."""

    def _git(self, directory: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        """지정한 디렉터리에서 시간과 범위를 제한한 읽기 전용 Git 관찰을 실행한다.

        Args:
            directory: Git을 실행할 정규 디렉터리.
            *arguments: 셸 보간 없이 전달하는 Git 인자들.

        Returns:
            subprocess.CompletedProcess[str]: 캡처한 Git 종료 상태와 출력 및 진단 정보.

        Raises:
            NeurathError: Git 조사가 실패하거나 잘못된 작업 트리 메타데이터를 반환한 경우.
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
        """정규화된 사실을 읽으며 Git 실패를 일반 폴더 관찰로 바꾸지 않는다.

        Args:
            working_directory: 호스트 요청이 제공한 기존 디렉터리.

        Returns:
            DirectoryObservation: 식별 정책을 포함하지 않는 정규 파일 시스템 경로와 해석한 Git 메타데이터.

        Raises:
            NeurathError: Git 조사가 실패하거나 잘못된 작업 트리 메타데이터를 반환한 경우.
            ValueError: 입력 경로·식별자·디렉터리가 작업에 적합하지 않은 경우.
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
