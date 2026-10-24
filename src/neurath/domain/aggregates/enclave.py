"""현재 작업의 짧은 맥락과 그 정정·삭제 이력을 함께 관리한다."""

from collections.abc import Sequence
from typing import Self, override
from uuid import UUID, uuid7

from spakky.core.common.mutability import mutable
from spakky.domain.models.aggregate_root import AbstractAggregateRoot

from neurath.domain.errors import ContextNotFound, RevisionConflict
from neurath.domain.values.enclave_fact import EnclaveChange, EnclaveFact


@mutable
class Enclave(AbstractAggregateRoot[UUID]):
    """한 프로젝트·세션·작업 범위의 현재 내용만 복원 대상으로 제공한다.

    Attributes:
        project_id: 기억이 속한 프로젝트.
        session_id: 현재 맥락을 소유하는 세션.
        task_id: 작업별 맥락이면 해당 작업 ID, 세션 공통 맥락이면 None.
        revision: 저장소가 갱신하며 쓰기 요청에서 비교하는 낙관적 개정.
        history: 이전 값과 명시적 삭제를 보존하는 변경 이력.
    """

    project_id: UUID
    session_id: UUID
    task_id: UUID | None
    revision: int
    history: Sequence[EnclaveChange] = ()

    @property
    def facts(self) -> Sequence[EnclaveFact]:
        """정정·삭제 이력에서 각 키의 최신 현재 항목만 반환한다.

        Returns:
            Sequence[EnclaveFact]: 삭제된 키와 과거 값이 제외된 현재 맥락.
        """
        current: dict[str, EnclaveFact] = {}
        for change in self.history:
            if change.fact is None:
                current.pop(change.key, None)
            else:
                current.pop(change.key, None)
                current[change.key] = change.fact
        return tuple(current.values())

    @classmethod
    @override
    def next_id(cls) -> UUID:
        """세션·태스크 ID와 구분되는 enclave 식별자를 만든다.

        Returns:
            UUID: 새 UUID 값.
        """
        return uuid7()

    @classmethod
    def create(cls, project_id: UUID, session_id: UUID, task_id: UUID | None = None) -> Self:
        """사실이 없는 정상적인 초기 맥락을 만든다.

        Args:
            project_id: 요청이 확인한 프로젝트 ID.
            session_id: 요청이 확인한 소유 세션 ID.
            task_id: 선택한 작업 ID 또는 세션 공통 범위의 None.

        Returns:
            Self: 현재 항목과 이력이 비어 있는 개정 1의 enclave.
        """
        return cls(
            uid=cls.next_id(),
            project_id=project_id,
            session_id=session_id,
            task_id=task_id,
            revision=1,
        )

    def set(self, fact: EnclaveFact, expected_revision: int) -> None:
        """읽은 개정이 현재와 일치할 때 같은 키를 정정하거나 새 항목을 저장한다.

        Args:
            fact: 현재 내용과 구분·근거를 가진 항목.
            expected_revision: 호출자가 읽고 수정 대상으로 지정한 개정.

        Raises:
            RevisionConflict: 다른 변경 이후의 오래된 개정으로 쓰기를 요청한 경우.
            ValueError: 현재 내용이 16 KiB를 넘어 상세 자료 참조로 저장해야 하는 경우.
        """
        if self.revision != expected_revision:
            raise RevisionConflict("Enclave revision changed")
        current = next((item for item in self.facts if item.key == fact.key), None)
        if current == fact:
            return
        size = sum(len(item.value.encode("utf-8")) for item in self.facts if item.key != fact.key)
        if size + len(fact.value.encode("utf-8")) > 16384:
            raise ValueError("Enclave exceeds 16 KiB; store details as a memory reference")
        self.history = (
            *self.history,
            EnclaveChange(number=len(self.history) + 1, key=fact.key, fact=fact),
        )

    def remove(self, key: str, expected_revision: int) -> None:
        """현재 항목만 제거하고 이전 내용과 삭제 개정을 이력으로 남긴다.

        원문이나 태스크를 삭제하지 않는다. 빈 내용의 저장과 명시적 삭제를 구분한다.

        Args:
            key: 명시적으로 삭제할 현재 항목의 이름.
            expected_revision: 호출자가 읽은 삭제 대상 개정.

        Raises:
            RevisionConflict: 읽은 뒤 다른 변경이 발생한 경우.
            ContextNotFound: 현재 범위에 해당 키가 없는 경우.
        """
        if self.revision != expected_revision:
            raise RevisionConflict("Enclave revision changed")
        if not any(item.key == key for item in self.facts):
            raise ContextNotFound("Current enclave fact not found")
        self.history = (
            *self.history,
            EnclaveChange(number=len(self.history) + 1, key=key, fact=None),
        )

    def transfer(self, source_session_id: UUID, target_session_id: UUID) -> None:
        """원 소유자가 일치할 때 현재 소유만 옮기고 과거 이력을 유지한다.

        Args:
            source_session_id: 인수 전 확인한 소유 세션.
            target_session_id: 같은 프로젝트로 확인된 후속 세션.

        Raises:
            ContextNotFound: 현재 소유자가 원 세션과 다른 경우.
        """
        if self.session_id != source_session_id:
            raise ContextNotFound("Ownership changed before handoff")
        self.session_id = target_session_id
