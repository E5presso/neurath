"""기사 개정을 실제 사용한다고 연결한 작업의 범위다."""

from uuid import UUID

from spakky.core.common.mutability import immutable


@immutable
class ArticleUse:
    """기사 개정을 실제 사용한다고 연결한 작업의 범위다.

    Attributes:
        task_id: 기사 내용을 사용한 태스크.
        definition_number: 사용 당시 태스크 요구 개정.
        revision_number: 사용한 기사 개정.
        peer_id: 작업 사용을 연결한 피어.
    """

    task_id: UUID
    definition_number: int
    revision_number: int
    peer_id: UUID
