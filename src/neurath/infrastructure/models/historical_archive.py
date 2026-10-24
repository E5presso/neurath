"""보존 사본과 실제 선택 재개를 선언형 소유 관계로 저장한다."""

from datetime import UTC, datetime
from typing import Self, override
from uuid import UUID

from spakky.plugins.sqlalchemy.orm.table import AbstractMappableTable, AbstractTable, Table
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from neurath.domain.aggregates.historical_archive import HistoricalAdoption, HistoricalArchive


@Table(HistoricalArchive)
class HistoricalArchiveModel(AbstractMappableTable[HistoricalArchive]):
    """원본 위치·사본·전체 행 수와 재개 연결을 저장한다.

    Attributes:
        id: 보존 자료의 식별자.
        version: 프레임워크 변경 토큰.
        created_at: 사본 등록 시각.
        updated_at: 마지막 연결 변경 시각.
        revision: 낙관적 저장 개정.
        directory: 명시한 프로젝트 루트.
        source_path: 원본 파일 위치.
        snapshot_path: 읽기 가능한 일관된 사본.
        digest: 사본의 내용 식별값.
        format: 실제 인식 형식.
        tables: 미인식을 포함한 테이블별 행 수.
        adoptions: 이 사본에서 실제로 재개한 작업.
    """

    __tablename__ = "core_historical_archives"
    __table_args__ = (UniqueConstraint("source_path", "digest"),)
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    version: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    directory: Mapped[str] = mapped_column(String, nullable=False)
    source_path: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_path: Mapped[str] = mapped_column(String, nullable=False)
    digest: Mapped[str] = mapped_column(String, nullable=False)
    format: Mapped[str] = mapped_column(String, nullable=False)
    tables: Mapped[list[list[str | int]]] = mapped_column(JSON, nullable=False)
    adoptions: Mapped[list[HistoricalAdoptionModel]] = relationship(
        lazy="selectin", cascade="all, delete-orphan"
    )
    __mapper_args__ = {"version_id_col": revision}

    @classmethod
    @override
    def from_domain(cls, domain: HistoricalArchive) -> Self:
        """자료와 재개 연결의 모든 필드를 매핑한다.

        Args:
            domain: 보존 자료 aggregate.

        Returns:
            Self: 저장할 매핑 객체.
        """
        return cls(
            id=domain.uid,
            version=domain.version,
            created_at=domain.created_at.astimezone(UTC).replace(tzinfo=None),
            updated_at=domain.updated_at.astimezone(UTC).replace(tzinfo=None),
            revision=domain.revision,
            directory=domain.directory,
            source_path=domain.source_path,
            snapshot_path=domain.snapshot_path,
            digest=domain.digest,
            format=domain.format,
            tables=[[name, count] for name, count in domain.tables],
            adoptions=[
                HistoricalAdoptionModel(
                    archive_id=domain.uid,
                    directory=domain.directory,
                    origin=item.origin,
                    task_id=item.task_id,
                )
                for item in domain.adoptions
            ],
        )

    @override
    def to_domain(self) -> HistoricalArchive:
        """원래 자료와 재개 연결을 복원한다.

        Returns:
            HistoricalArchive: 현재 권한을 추가하지 않은 저장 자료.
        """
        return HistoricalArchive(
            uid=self.id,
            version=self.version,
            created_at=self.created_at.replace(tzinfo=UTC),
            updated_at=self.updated_at.replace(tzinfo=UTC),
            revision=self.revision,
            directory=self.directory,
            source_path=self.source_path,
            snapshot_path=self.snapshot_path,
            digest=self.digest,
            format=self.format,
            tables=tuple((str(name), int(count)) for name, count in self.tables),
            adoptions=tuple(
                HistoricalAdoption(origin=item.origin, task_id=item.task_id)
                for item in self.adoptions
            ),
        )


@Table()
class HistoricalAdoptionModel(AbstractTable):
    """같은 프로젝트·원 작업의 중복 재개를 DB에서도 거절한다.

    Attributes:
        archive_id: 연결을 소유한 보존 자료.
        directory: 선택한 프로젝트 루트.
        origin: 원 작업 계보 식별자.
        task_id: 실제 현재 작업의 외래 키.
    """

    __tablename__ = "core_historical_adoptions"
    __table_args__ = (UniqueConstraint("directory", "origin"),)
    archive_id: Mapped[UUID] = mapped_column(
        Uuid(), ForeignKey("core_historical_archives.id"), primary_key=True
    )
    directory: Mapped[str] = mapped_column(String, nullable=False)
    origin: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("core_tasks.id"), nullable=False)
