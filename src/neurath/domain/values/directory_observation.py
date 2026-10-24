"""읽기 전용 관찰로 얻은 정규 디렉터리와 선택적 Git 메타데이터다."""

from spakky.core.common.mutability import immutable


@immutable
class DirectoryObservation:
    """읽기 전용 관찰로 얻은 정규 디렉터리와 선택적 Git 메타데이터다.

    Attributes:
        working_directory: 호스트 요청에서 조사한 정규 디렉터리.
        git_common_directory: Git 메타데이터가 있을 때의 정규 공통 디렉터리.
        primary_worktree: Git이 반환한 첫 작업 트리의 정규 경로이며 없으면 None.
    """

    working_directory: str
    git_common_directory: str | None = None
    primary_worktree: str | None = None
