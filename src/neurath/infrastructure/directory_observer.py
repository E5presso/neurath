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
        """상속된 GIT_* 환경을 제거하고 지정 디렉터리에서 Git 조회를 실행한다.

        호출자가 읽기 전용 인자를 전달하며 실행 제한은 10초다. 종료 코드가 0이
        아니어도 결과를 반환하여 호출자가 저장소 부재와 실제 오류를 구분하게 한다.

        Args:
            directory: Git을 실행할 정규 디렉터리.
            *arguments: 셸 보간 없이 전달하는 Git 인자들.

        Returns:
            subprocess.CompletedProcess[str]: 캡처한 Git 종료 상태와 출력 및 진단 정보.

        Raises:
            NeurathError: Git 프로세스를 시작할 수 없거나 실행이 10초를 초과한 경우.
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
        """실제 작업 경로와 Git 공통 디렉터리·첫 작업 트리를 조회한다.

        Git이 저장소가 아니라고 응답한 경우에만 일반 폴더 관찰을 반환한다.
        경로 확인 중 파일 시스템 오류는 그대로 전파하고, 그 밖의 Git 오류는
        NeurathError로 보고한다. 프로젝트 선택·등록은 수행하지 않는다.

        Args:
            working_directory: 호스트 요청이 제공한 기존 디렉터리.

        Returns:
            DirectoryObservation: 식별 정책을 포함하지 않는 정규 파일 시스템 경로와 해석한 Git 메타데이터.

        Raises:
            NeurathError: Git 조사가 실패하거나 잘못된 작업 트리 메타데이터를 반환한 경우.
            ValueError: 실재하는 입력 경로가 디렉터리가 아닌 경우.
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
