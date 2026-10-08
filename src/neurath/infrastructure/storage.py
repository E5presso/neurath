"""Transactional SQLite persistence, packaged migrations, and lossless exports."""

from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import zlib
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, create_engine, delete, event, inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from neurath.domain.codec import entity_from_dict
from neurath.domain.errors import ConflictError, ValidationError
from neurath.domain.models import ENTITY_TYPES, Entity

from .models import (
    ArchiveChunkRow,
    ArchiveRow,
    CriterionEvidenceRow,
    CriterionRow,
    EntityVersionRow,
    LeaseRow,
    PhaseEvidenceRow,
    PhaseRow,
    RecordRow,
    TaskDelegationRow,
    TaskRow,
    TaskSourceRow,
)

_MIGRATION_LOCK = threading.RLock()
ARCHIVE_CHUNK_BYTES = 1024 * 1024
HEAD = "0002"
KNOWN_REVISIONS = {"0001", "0002"}


class StorageError(RuntimeError):
    """Persistence could not be used safely."""


class MigrationError(StorageError):
    pass


RevisionConflict = ConflictError
DuplicateEntity = ConflictError


def _guard_path(path: Path) -> Path:
    path = path.absolute()
    for component in (path, *path.parents):
        if component.is_symlink():
            raise StorageError(f"Symlink database paths are forbidden: {component}")
    if path.exists() and not path.is_file():
        raise StorageError("Database path must be a regular file")
    return path


def _canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


class Database:
    """A database handle. Opening it never upgrades or writes existing databases."""

    def __init__(self, path: str | Path):
        self.path = _guard_path(Path(path))
        self.engine = create_engine(
            URL.create("sqlite", database=str(self.path)),
            connect_args={"timeout": 30},
            pool_pre_ping=True,
        )

        @event.listens_for(self.engine, "connect")
        def configure(dbapi_connection, _record):
            _guard_path(self.path)
            dbapi_connection.isolation_level = None
            dbapi_connection.execute("PRAGMA foreign_keys=ON")
            dbapi_connection.execute("PRAGMA busy_timeout=30000")

        @event.listens_for(self.engine, "begin")
        def begin(connection):
            # Acquire the writer lock before reading receipts or lease generations.
            connection.exec_driver_sql(
                "BEGIN"
                if connection.get_execution_options().get("neurath_read_only")
                else "BEGIN IMMEDIATE"
            )

    def migration_config(self, connection) -> Config:
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
        config.attributes["connection"] = connection
        return config

    def initialize(self, target: str = HEAD) -> None:
        if target not in KNOWN_REVISIONS:
            raise MigrationError(f"Unknown migration target: {target}")
        _guard_path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _guard_path(self.path)
        with self.engine.begin() as connection:
            tables = inspect(connection).get_table_names()
            if "alembic_version" in tables:
                versions = (
                    connection.exec_driver_sql("SELECT version_num FROM alembic_version")
                    .scalars()
                    .all()
                )
                if len(versions) != 1 or versions[0] not in KNOWN_REVISIONS:
                    raise MigrationError("Unknown, future, or inconsistent database schema version")
                if versions[0] > target:
                    raise MigrationError("Automatic downgrade is forbidden")
            elif tables:
                raise MigrationError("Unversioned existing database requires an explicit import")
            with _MIGRATION_LOCK:
                command.upgrade(self.migration_config(connection), target)

    def downgrade(self, target: str) -> None:
        """Explicit data-preserving index downgrade; base downgrade is unsupported."""
        if target != "0001":
            raise MigrationError("Only the data-preserving downgrade to 0001 is supported")
        with self.engine.begin() as connection:
            versions = (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version")
                .scalars()
                .all()
            )
            if versions not in ([HEAD], ["0001"]):
                raise MigrationError("Cannot downgrade an unknown schema")
            with _MIGRATION_LOCK:
                command.downgrade(self.migration_config(connection), target)

    def uow(self) -> UnitOfWork:
        _guard_path(self.path)
        return UnitOfWork(self)

    def close(self) -> None:
        self.engine.dispose()

    def export_records(self) -> dict[str, list[dict[str, Any]]]:
        """Read a consistent snapshot without running migrations or mutating records."""
        _guard_path(self.path)
        if not self.path.is_file():
            raise StorageError("Cannot export a missing database")
        with self.engine.connect().execution_options(neurath_read_only=True) as connection:
            with Session(bind=connection) as session:
                return {
                    kind: [entity.to_dict() for entity in Repository(session, kind).list()]
                    for kind in sorted(ENTITY_TYPES)
                }

    def read_archive(self, snapshot_id: str) -> dict[str, Any] | None:
        _guard_path(self.path)
        with self.engine.connect().execution_options(neurath_read_only=True) as connection:
            with Session(bind=connection) as session:
                row = session.get(ArchiveRow, snapshot_id)
                if row is None:
                    return None
                if row.data.get("storage") != "zlib-json-v1":
                    return json.loads(_canonical(row.data))
                decoder = zlib.decompressobj()
                archive_digest = hashlib.sha256()
                uncompressed_size = 0
                chunk_count = 0
                with tempfile.TemporaryFile(mode="w+b") as stream:
                    chunks = session.execute(
                        select(ArchiveChunkRow.position, ArchiveChunkRow.data)
                        .where(ArchiveChunkRow.archive_id == snapshot_id)
                        .order_by(ArchiveChunkRow.position)
                        .execution_options(yield_per=1)
                    )
                    for position, chunk in chunks:
                        if position != chunk_count:
                            raise StorageError("Archive chunk sequence is incomplete")
                        chunk_count += 1
                        try:
                            while chunk:
                                decoded = decoder.decompress(chunk, ARCHIVE_CHUNK_BYTES)
                                archive_digest.update(decoded)
                                uncompressed_size += len(decoded)
                                stream.write(decoded)
                                chunk = decoder.unconsumed_tail
                        except zlib.error as exc:
                            raise StorageError(
                                "Archive compression integrity check failed"
                            ) from exc
                    if (
                        not decoder.eof
                        or decoder.unused_data
                        or chunk_count != row.data["chunks"]
                        or uncompressed_size != row.data["size"]
                        or archive_digest.hexdigest() != row.data["sha256"]
                    ):
                        raise StorageError("Archive integrity check failed")
                    stream.seek(0)
                    return json.load(stream)

    def history(self, kind: str, entity_id: str) -> list[dict[str, Any]]:
        with self.engine.connect().execution_options(neurath_read_only=True) as connection:
            with Session(bind=connection) as session:
                return list(
                    session.scalars(
                        select(EntityVersionRow.data)
                        .where(EntityVersionRow.kind == kind, EntityVersionRow.id == entity_id)
                        .order_by(EntityVersionRow.revision)
                    )
                )

    def import_records(
        self,
        records: dict[str, list[dict[str, Any]]],
        *,
        snapshot_id: str | None = None,
        archive: dict[str, Any] | None = None,
    ) -> bool:
        """Atomically import records and bounded compressed archive chunks.

        Compression is incremental and spooled to disk before acquiring the writer
        transaction; no archive-size JSON string or SQLite value is constructed.
        """
        if (snapshot_id is None) != (archive is None):
            raise ValidationError("An archive requires a snapshot identity and vice versa")
        encoder = json.JSONEncoder(
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        digest = hashlib.sha256()
        for segment in encoder.iterencode(records):
            digest.update(segment.encode())
        digest.update(b"\x00archive\x00")
        compressor = zlib.compressobj(level=1)
        archive_digest = hashlib.sha256()
        archive_size = 0
        with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as compressed:
            if archive is not None:
                for segment in encoder.iterencode(archive):
                    data = segment.encode()
                    digest.update(data)
                    archive_digest.update(data)
                    archive_size += len(data)
                    compressed.write(compressor.compress(data))
                compressed.write(compressor.flush())
                compressed.seek(0)
            with self.uow() as uow:
                if snapshot_id is not None:
                    existing = uow.session.get(ArchiveRow, snapshot_id)
                    if existing:
                        if existing.digest != digest.hexdigest():
                            raise ConflictError(
                                "Snapshot identity was already imported with different content"
                            )
                        return False
                for kind, entries in records.items():
                    repository = uow.repo(kind)
                    for value in entries:
                        entity = entity_from_dict(kind, value)
                        existing = repository.get(entity.id)
                        if existing is not None:
                            if existing.to_dict() != entity.to_dict():
                                raise ConflictError(
                                    f"Import conflicts with existing {kind}: {entity.id}"
                                )
                        else:
                            repository.add(entity)
                if snapshot_id is not None:
                    archive_row = ArchiveRow(
                        id=snapshot_id, digest=digest.hexdigest(), data={"storage": "zlib-json-v1"}
                    )
                    uow.session.add(archive_row)
                    uow.session.flush()
                    position = 0
                    while chunk := compressed.read(ARCHIVE_CHUNK_BYTES):
                        uow.session.add(
                            ArchiveChunkRow(archive_id=snapshot_id, position=position, data=chunk)
                        )
                        uow.session.flush()
                        position += 1
                    archive_row.data = {
                        "storage": "zlib-json-v1",
                        "chunks": position,
                        "sha256": archive_digest.hexdigest(),
                        "size": archive_size,
                    }
                uow.commit()
        return True


class UnitOfWork:
    def __init__(self, database: Database):
        self.database = database
        self.session: Session

    def __enter__(self) -> UnitOfWork:
        _guard_path(self.database.path)
        self.session = Session(self.database.engine, expire_on_commit=False)
        self.session.begin()
        # Eager acquisition makes read-then-write atomic, including idempotency.
        self.session.connection()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.session.rollback()
        self.session.close()

    def repo(self, kind: str) -> Repository:
        return Repository(self.session, kind)

    def commit(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            raise ConflictError("Database constraint rejected the transaction") from exc


class Repository:
    def __init__(self, session: Session, kind: str):
        if kind not in ENTITY_TYPES:
            raise ValidationError(f"Unknown entity kind: {kind}")
        self.session, self.kind = session, kind
        self.model = TaskRow if kind == "task" else LeaseRow if kind == "lease" else RecordRow

    def _where(self, entity_id: str):
        terms = [self.model.id == entity_id]
        if self.model is RecordRow:
            terms.append(RecordRow.kind == self.kind)
        return terms

    def get(self, entity_id: str) -> Entity | None:
        row = self.session.scalar(select(self.model).where(*self._where(entity_id)))
        return self._entity(row) if row is not None else None

    def list(self, **filters: Any) -> list[Entity]:
        query = select(self.model).order_by(self.model.id)
        if self.model is RecordRow:
            query = query.where(RecordRow.kind == self.kind)
        entities = [self._entity(row) for row in self.session.scalars(query)]
        return [
            entity
            for entity in entities
            if all(getattr(entity, key, object()) == value for key, value in filters.items())
        ]

    def add(self, entity: Entity) -> None:
        self._validate(entity)
        if self.get(entity.id) is not None:
            raise ConflictError(f"{self.kind} already exists: {entity.id}")
        try:
            self.session.add(self.model(**self._values(entity.to_dict())))
            self.session.flush()
            if self.kind == "task":
                self._write_children(entity.to_dict())
            self._record_version(entity)
        except IntegrityError as exc:
            raise ConflictError("Entity violates an identity or relation constraint") from exc

    def save(self, entity: Entity, expected_revision: int) -> None:
        self._validate(entity)
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or entity.revision != expected_revision + 1
        ):
            raise ConflictError("A save must advance exactly one revision")
        if self.kind == "lease":
            current = self.get(entity.id)
            if current is None:
                raise ConflictError("Lease does not exist")
            if entity.resource != current.resource or entity.generation < current.generation:
                raise ConflictError("Lease identity and generation cannot regress")
            if entity.owner_id != current.owner_id and (
                current.active or entity.generation <= current.generation
            ):
                raise ConflictError(
                    "An active lease is exclusive; a new owner requires a newer generation"
                )
            if not current.active and entity.active and entity.generation <= current.generation:
                raise ConflictError("Lease reacquisition requires a newer generation")
        values = self._values(entity.to_dict())
        result = self.session.execute(
            update(self.model)
            .where(*self._where(entity.id), self.model.revision == expected_revision)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise ConflictError("Entity changed or no longer exists")
        self.session.expire_all()
        if self.kind == "task":
            self._write_children(entity.to_dict())
        self._record_version(entity)

    def _record_version(self, entity: Entity) -> None:
        self.session.add(
            EntityVersionRow(
                kind=self.kind, id=entity.id, revision=entity.revision, data=entity.to_dict()
            )
        )
        self.session.flush()

    def _validate(self, entity: Entity) -> None:
        if entity.kind != self.kind or not isinstance(entity.id, str) or not entity.id.strip():
            raise ValidationError("Repository entity kind or identity is invalid")
        if (
            isinstance(entity.revision, bool)
            or not isinstance(entity.revision, int)
            or entity.revision < 0
        ):
            raise ValidationError("Revision must be a nonnegative integer")
        _canonical(entity.to_dict())

    def _values(self, data: dict[str, Any]) -> dict[str, Any]:
        if self.kind == "task":
            fields = (
                "id",
                "revision",
                "owner_id",
                "source_id",
                "goal",
                "status",
                "scope_version",
                "wait_reason",
            )
            return {
                **{key: data[key] for key in fields},
                "extra": {
                    key: value
                    for key, value in data.items()
                    if key not in (*fields, "criteria", "phases", "delegation_ids", "source_ids")
                },
            }
        if self.kind == "lease":
            return data
        return {
            "kind": self.kind,
            "id": data["id"],
            "revision": data["revision"],
            "owner_id": data.get("owner_id"),
            "task_id": data.get("task_id"),
            "status": data.get("status"),
            "data": {
                key: value
                for key, value in data.items()
                if key not in ("id", "revision", "owner_id", "task_id", "status")
            },
        }

    def _entity(self, row) -> Entity:
        if self.kind == "lease":
            data = {
                key: getattr(row, key)
                for key in ("id", "revision", "resource", "owner_id", "generation", "active")
            }
        elif self.kind != "task":
            data = dict(row.data, id=row.id, revision=row.revision)
            fields = ENTITY_TYPES[self.kind].__dataclass_fields__
            for key in ("owner_id", "task_id", "status"):
                if key in fields:
                    data[key] = getattr(row, key)
        else:
            data = dict(
                row.extra,
                **{
                    key: getattr(row, key)
                    for key in (
                        "id",
                        "revision",
                        "owner_id",
                        "source_id",
                        "goal",
                        "status",
                        "scope_version",
                        "wait_reason",
                    )
                },
            )
            criteria = self.session.scalars(
                select(CriterionRow)
                .where(CriterionRow.task_id == row.id)
                .order_by(CriterionRow.position)
            )
            data["criteria"] = [
                {
                    "id": criterion.id,
                    "description": criterion.description,
                    "satisfied": criterion.satisfied,
                    "evidence_ids": list(
                        self.session.scalars(
                            select(CriterionEvidenceRow.evidence_id)
                            .where(
                                CriterionEvidenceRow.task_id == row.id,
                                CriterionEvidenceRow.criterion_id == criterion.id,
                            )
                            .order_by(CriterionEvidenceRow.position)
                        )
                    ),
                }
                for criterion in criteria
            ]
            phases = self.session.scalars(
                select(PhaseRow).where(PhaseRow.task_id == row.id).order_by(PhaseRow.position)
            )
            data["phases"] = [
                dict(
                    phase.extra,
                    id=phase.id,
                    name=phase.name,
                    status=phase.status,
                    evidence_ids=list(
                        self.session.scalars(
                            select(PhaseEvidenceRow.evidence_id)
                            .where(
                                PhaseEvidenceRow.task_id == row.id,
                                PhaseEvidenceRow.phase_id == phase.id,
                            )
                            .order_by(PhaseEvidenceRow.position)
                        )
                    ),
                )
                for phase in phases
            ]
            data["source_ids"] = list(
                self.session.scalars(
                    select(TaskSourceRow.source_id)
                    .where(TaskSourceRow.task_id == row.id)
                    .order_by(TaskSourceRow.position)
                )
            )
            data["delegation_ids"] = list(
                self.session.scalars(
                    select(TaskDelegationRow.delegation_id)
                    .where(TaskDelegationRow.task_id == row.id)
                    .order_by(TaskDelegationRow.position)
                )
            )
        return entity_from_dict(self.kind, data)

    def _write_children(self, data: dict[str, Any]) -> None:
        task_id = data["id"]
        for model in (
            CriterionEvidenceRow,
            PhaseEvidenceRow,
            CriterionRow,
            PhaseRow,
            TaskDelegationRow,
            TaskSourceRow,
        ):
            self.session.execute(delete(model).where(model.task_id == task_id))
        for position, item in enumerate(data["criteria"]):
            self.session.add(
                CriterionRow(
                    task_id=task_id,
                    id=item["id"],
                    position=position,
                    description=item["description"],
                    satisfied=item["satisfied"],
                )
            )
            self.session.flush()
            for index, evidence_id in enumerate(item["evidence_ids"]):
                self.session.add(
                    CriterionEvidenceRow(
                        task_id=task_id,
                        criterion_id=item["id"],
                        position=index,
                        evidence_id=evidence_id,
                    )
                )
        for position, item in enumerate(data["phases"]):
            self.session.add(
                PhaseRow(
                    task_id=task_id,
                    id=item["id"],
                    position=position,
                    name=item["name"],
                    status=item["status"],
                    extra={
                        key: value
                        for key, value in item.items()
                        if key not in ("id", "name", "status", "evidence_ids")
                    },
                )
            )
            self.session.flush()
            for index, evidence_id in enumerate(item.get("evidence_ids", [])):
                self.session.add(
                    PhaseEvidenceRow(
                        task_id=task_id,
                        phase_id=item["id"],
                        position=index,
                        evidence_id=evidence_id,
                    )
                )
        for position, source_id in enumerate(data.get("source_ids", [])):
            self.session.add(TaskSourceRow(task_id=task_id, position=position, source_id=source_id))
        for position, delegation_id in enumerate(data["delegation_ids"]):
            self.session.add(
                TaskDelegationRow(task_id=task_id, position=position, delegation_id=delegation_id)
            )
        self.session.flush()


SQLiteStore = Database
