"""현재 enclave와 소유 변경 이력을 선언형 관계로 저장한다."""

from datetime import UTC, datetime
from typing import Self, override
from uuid import UUID

from spakky.plugins.sqlalchemy.orm.table import AbstractMappableTable, AbstractTable, Table
from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from neurath.domain.aggregates.enclave import Enclave
from neurath.domain.enclave_records import EnclaveChange, EnclaveFact, EnclaveKind
from neurath.infrastructure.uuid_type import UUIDText


@Table(Enclave)
class EnclaveModel(AbstractMappableTable[Enclave]):
    """세션·작업 범위와 개정별 저장·삭제 이력을 매핑한다.

    Attributes:
        id: 저장된 aggregate의 식별자.
        version: 프레임워크 변경 토큰.
        created_at: 최초 기록의 UTC 시각.
        updated_at: 마지막 변경의 UTC 시각.
        project_id: 소속 프로젝트의 외래 키.
        session_id: 현재 맥락 또는 원래 기억 작성 세션.
        task_id: 관련 작업의 선택적 외래 키.
        revision: 낙관적 잠금과 예상 개정 비교 값.
        changes: aggregate가 소유하는 개정 순서의 저장·삭제 이력.
    """

    __tablename__ = "core_enclaves"
    __table_args__ = (
        Index(
            "uq_core_enclave_task",
            "session_id",
            "task_id",
            unique=True,
            sqlite_where=text("task_id IS NOT NULL"),
        ),
        Index(
            "uq_core_enclave_session",
            "session_id",
            unique=True,
            sqlite_where=text("task_id IS NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(UUIDText, primary_key=True)
    version: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(
        UUIDText, ForeignKey("core_projects.id"), nullable=False
    )
    session_id: Mapped[UUID] = mapped_column(
        UUIDText, ForeignKey("core_sessions.id"), nullable=False
    )
    task_id: Mapped[UUID | None] = mapped_column(UUIDText, ForeignKey("core_tasks.id"))
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    __mapper_args__ = {"version_id_col": revision}
    changes: Mapped[list[EnclaveChangeModel]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="EnclaveChangeModel.number"
    )

    @classmethod
    @override
    def from_domain(cls, domain: Enclave) -> Self:
        """enclave와 소유 이력을 저장용 레코드로 변환한다.

        Args:
            domain: 동일성을 유지할 현재 맥락.

        Returns:
            Self: 개정·삭제 이력을 포함한 ORM 레코드.
        """
        return cls(
            id=domain.uid,
            version=domain.version,
            created_at=domain.created_at.astimezone(UTC).replace(tzinfo=None),
            updated_at=domain.updated_at.astimezone(UTC).replace(tzinfo=None),
            project_id=domain.project_id,
            session_id=domain.session_id,
            task_id=domain.task_id,
            revision=domain.revision,
            changes=[EnclaveChangeModel.from_domain(item, domain.uid) for item in domain.history],
        )

    @override
    def to_domain(self) -> Enclave:
        """저장 시각과 이력을 복원하며 현재 항목 판단은 aggregate에 맡긴다.

        Returns:
            Enclave: 현재 내용과 과거 변경을 구분하는 aggregate.
        """
        return Enclave(
            uid=self.id,
            version=self.version,
            created_at=self.created_at.replace(tzinfo=UTC),
            updated_at=self.updated_at.replace(tzinfo=UTC),
            project_id=self.project_id,
            session_id=self.session_id,
            task_id=self.task_id,
            revision=self.revision,
            history=tuple(item.to_domain() for item in self.changes),
        )


@Table()
class EnclaveChangeModel(AbstractTable):
    """enclave가 소유하는 변경 한 건을 저장한다.

    Attributes:
        enclave_id: 이력을 소유하는 enclave의 외래 키.
        number: 낙관적 잠금과 예상 개정 비교 값.
        key: 변경한 현재 맥락 항목의 이름.
        value: 저장 내용이며 명시적인 삭제는 None.
        kind: 기억 또는 사실의 종류.
        references: 원문·산출물·상세 자료의 참조 목록.
    """

    __tablename__ = "core_enclave_changes"
    enclave_id: Mapped[UUID] = mapped_column(
        UUIDText, ForeignKey("core_enclaves.id"), primary_key=True
    )
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str | None] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    references: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_domain(cls, change: EnclaveChange, enclave_id: UUID) -> Self:
        """명시적인 삭제와 저장 내용을 서로 다른 값으로 매핑한다.

        Args:
            change: 저장할 변경 기록.
            enclave_id: 이력을 소유하는 enclave ID.

        Returns:
            Self: 삭제는 value=None인 이력 행.
        """
        fact = change.fact
        return cls(
            enclave_id=enclave_id,
            number=change.number,
            key=change.key,
            value=None if fact is None else fact.value,
            kind="" if fact is None else fact.kind.value,
            references=[] if fact is None else list(fact.references),
        )

    def to_domain(self) -> EnclaveChange:
        """저장한 사실 또는 삭제 표식을 복원한다.

        Returns:
            EnclaveChange: 해당 개정의 저장·삭제 기록.
        """
        fact = (
            None
            if self.value is None
            else EnclaveFact(
                key=self.key,
                value=self.value,
                kind=EnclaveKind(self.kind),
                references=self.references,
            )
        )
        return EnclaveChange(number=self.number, key=self.key, fact=fact)
