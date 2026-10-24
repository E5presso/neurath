"""관찰한 과거 SQLite 형식을 읽고 원본과 기능 자료를 손실 없이 보존한다."""

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zlib
from collections.abc import Generator, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any, cast, override
from uuid import uuid7

import ijson
from ijson.common import ObjectBuilder
from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.historical_store import (
    HistoricalInspection,
    HistoricalPage,
    HistoricalRecord,
    HistoricalSnapshot,
    IHistoricalStoreService,
)
from neurath.infrastructure.database import create_database_engine, verify_schema


@Pod()
class PosixHistoricalStoreService(IHistoricalStoreService):
    """원본은 읽기 전용으로 열고 현재 호스트 상태나 임대를 생성하지 않는다."""

    @staticmethod
    def _connect(path: str) -> sqlite3.Connection:
        """없는 파일을 만들지 않는 읽기 연결을 연다.

        Args:
            path: 원본 또는 사본 SQLite 경로.

        Returns:
            sqlite3.Connection: query_only가 적용된 연결.
        """
        connection = sqlite3.connect(
            Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=1
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection

    @staticmethod
    def _quote(name: str) -> str:
        """과거 스키마의 식별자를 SQL 값과 구분해 인용한다.

        Args:
            name: 실제 관찰한 테이블 이름.

        Returns:
            str: 안전하게 인용한 식별자.
        """
        return '"' + name.replace('"', '""') + '"'

    @override
    def inspect(self, source: str) -> HistoricalInspection:
        """읽기 가능한 형식과 전체 테이블 행 수를 관찰한다.

        Args:
            source: 원본 SQLite 파일.

        Returns:
            HistoricalInspection: 자료가 없는 경우와 미인식을 구분한 관찰.
        """
        path = Path(source).expanduser().resolve()
        with closing(self._connect(str(path))) as db:
            names = [
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            counts = tuple(
                (name, db.execute(f"SELECT count(*) FROM {self._quote(name)}").fetchone()[0])
                for name in names
            )
            format_name = "unknown"
            if {"records", "tasks", "source_archives", "alembic_version"} <= set(names):
                versions = {row[0] for row in db.execute("SELECT version_num FROM alembic_version")}
                if versions and versions <= {"0001", "0002"}:
                    format_name = "record-store-v2"
            elif {"runtime_records", "runtime_schema", "events"} <= set(names):
                format_name = "runtime-store"
            elif "core_schema_revision" in names:
                format_name = "current-core"
        return HistoricalInspection(
            source_path=str(path),
            format=format_name,
            tables=counts,
            wal_present=Path(str(path) + "-wal").exists(),
        )

    @override
    def snapshot(
        self, source: str, archive_directory: str, configs: Sequence[str]
    ) -> HistoricalSnapshot:
        """SQLite backup의 일관된 사본과 관찰 당시 원본/WAL·설정을 각각 남긴다.

        Args:
            source: 변경하지 않을 원본 SQLite.
            archive_directory: 복구 사본을 둘 명시적 폴더.
            configs: 원본 그대로 보존할 선택한 설정 파일.

        Returns:
            HistoricalSnapshot: 원본과 분리된 일관된 읽기 사본.

        Raises:
            ValueError: 선택한 설정 경로가 파일이 아닌 경우.
        """
        path = Path(source).expanduser().resolve(strict=True)
        config_paths = sorted(
            {Path(value).expanduser().resolve(strict=True) for value in configs}, key=str
        )
        if any(not item.is_file() for item in config_paths):
            raise ValueError("Selected configuration must be an existing file")
        inspection = self.inspect(str(path))
        destination = Path(archive_directory).expanduser().resolve() / str(uuid7())
        destination.mkdir(mode=0o700, parents=True)
        snapshot = destination / "snapshot.sqlite3"
        with (
            closing(self._connect(str(path))) as original,
            closing(sqlite3.connect(snapshot)) as copied,
        ):
            original.backup(copied, pages=256, sleep=0.01)
        snapshot.chmod(0o600)
        preserved = []
        for index, item in enumerate(
            [path, Path(str(path) + "-wal"), Path(str(path) + "-shm"), *config_paths]
        ):
            if not item.is_file():
                continue
            saved = destination / f"original-{index}-{item.name}"
            shutil.copyfile(item, saved)
            saved.chmod(0o600)
            preserved.append({"source": str(item), "copy": saved.name})
        manifest = destination / "files.json"
        manifest.write_text(
            json.dumps(
                {
                    "files": preserved,
                    "raw_files": "observed copies; snapshot.sqlite3 is the consistent committed view",
                },
                ensure_ascii=False,
            )
        )
        manifest.chmod(0o600)
        with snapshot.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if config_paths:
            config_digests = []
            for item in config_paths:
                saved = next(
                    destination / entry["copy"]
                    for entry in preserved
                    if entry["source"] == str(item)
                )
                with saved.open("rb") as stream:
                    config_digests.append(
                        (str(item), hashlib.file_digest(stream, "sha256").hexdigest())
                    )
            digest = hashlib.sha256(json.dumps([digest, config_digests]).encode()).hexdigest()
        return HistoricalSnapshot(inspection=inspection, path=str(snapshot), digest=digest)

    @override
    async def recover(self, source: str, destination: str) -> HistoricalSnapshot:
        """현재 기록 전체를 호환 코어 사본으로 만들며 구버전 DB를 다시 켜지 않는다.

        Args:
            source: 보존할 현재 코어 파일.
            destination: 새로 만들 복구 파일.

        Returns:
            HistoricalSnapshot: 현재 Alembic과 읽기가 확인된 복구 사본.

        Raises:
            ValueError: 현재 코어로 인식되지 않은 자료를 복구 대상으로 지정한 경우.
        """
        inspection = self.inspect(source)
        if inspection.format != "current-core":
            raise ValueError(
                "Recover current core records with a compatible version; legacy rollback is not a lossless conversion"
            )
        engine = create_database_engine(Path(source), write=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(verify_schema)
        finally:
            await engine.dispose()
        target = Path(destination).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        with closing(self._connect(source)) as original, closing(sqlite3.connect(target)) as copied:
            original.backup(copied, pages=256, sleep=0.01)
        with target.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return HistoricalSnapshot(inspection=inspection, path=str(target), digest=digest)

    @staticmethod
    def _origin(owner: str, session: str, task: str) -> str:
        """과거 작업 계보를 현재 권한과 무관한 중복 비교값으로 표현한다.

        Args:
            owner: 과거 소유자.
            session: 과거 세션.
            task: 과거 작업 ID.

        Returns:
            str: 같은 계보의 안정적인 식별값.
        """
        return hashlib.sha256(
            json.dumps([owner, session, task], ensure_ascii=False).encode()
        ).hexdigest()

    @override
    def read(
        self, snapshot: str, category: str, offset: int = 0, limit: int = 20, key: str | None = None
    ) -> HistoricalPage:
        """사본 전체를 펼치지 않고 필요한 자료만 읽어 페이지와 미확인 경계를 반환한다.

        Args:
            snapshot: 보존된 SQLite 사본.
            category: 선택한 기능 영역.
            offset: 이전 페이지 다음 위치.
            limit: 최대 출력 수.
            key: 선택할 원 자료 식별자.

        Returns:
            HistoricalPage: 선택 자료와 아직 읽지 않은 위치.

        Raises:
            ValueError: 영역·페이지 범위가 잘못된 경우.
        """
        if (
            category
            not in {
                "tasks",
                "sources",
                "workflows",
                "enclave",
                "messages",
                "learning",
                "memory",
                "unknown",
            }
            or offset < 0
            or not 1 <= limit <= 100
        ):
            raise ValueError("Invalid historical section or page")
        seen = set()
        page = []
        count = 0
        with closing(self._scan(snapshot, category)) as records:
            for record in records:
                if category == "tasks":
                    if record.origin in seen:
                        continue
                    seen.add(record.origin)
                if key is not None and key not in (
                    record.key,
                    record.data.get("lineage", {}).get("original_task_id"),
                ):
                    continue
                if count >= offset:
                    page.append(record)
                count += 1
                if key is not None:
                    break
                if len(page) > limit:
                    return HistoricalPage(
                        records=page[:limit], total=None, next_offset=offset + limit
                    )
        return HistoricalPage(records=page, total=count, next_offset=None)

    def _scan(self, snapshot: str, category: str) -> Generator[HistoricalRecord]:
        """원 테이블과 내장 archive를 필요한 기능의 행 단위로 읽는다.

        Args:
            snapshot: 일관된 사본.
            category: 선택한 기능 영역.

        Yields:
            HistoricalRecord: 현재 권한과 구분된 과거 자료.

        Raises:
            ValueError: 해당 형식을 의미적으로 해석할 수 없는 경우.
        """
        inspection = self.inspect(snapshot)
        if inspection.format not in {"record-store-v2", "runtime-store"} and category != "unknown":
            raise ValueError(
                "Historical format has no functional projection; inspect unknown data instead"
            )
        with closing(self._connect(snapshot)) as db:
            if category == "unknown":
                for name, count in inspection.tables:
                    yield HistoricalRecord(
                        key=name,
                        category=category,
                        status="preserved; activation not inferred",
                        origin="",
                        data={"table": name, "rows": count},
                        references=("snapshot", name),
                    )
            elif inspection.format == "record-store-v2":
                tables = {}
                for name, _ in inspection.tables:
                    if self._needed(name, category, inspection.format):
                        tables[name] = [
                            dict(row)
                            for row in db.execute(f"SELECT * FROM {self._quote(name)}")
                            if self._include(name, dict(row), category)
                        ]
                yield from self._modern(tables, category, "snapshot")
            else:
                for name, _ in inspection.tables:
                    if self._needed(name, category, inspection.format):
                        for row in db.execute(f"SELECT * FROM {self._quote(name)}"):
                            if self._include(name, dict(row), category):
                                yield from self._runtime({name: [dict(row)]}, category, "snapshot")
            if inspection.format != "record-store-v2":
                return
            for archive in db.execute("SELECT id,data FROM source_archives ORDER BY id"):
                metadata = json.loads(archive["data"])
                if metadata.get("storage") != "zlib-json-v1":
                    if category == "unknown":
                        yield HistoricalRecord(
                            key=str(archive["id"]),
                            category=category,
                            status="unrecognized archive encoding",
                            origin="",
                            data={"metadata": metadata},
                            references=("source_archives",),
                        )
                    else:
                        raise ValueError(
                            "Embedded archive encoding is unrecognized; functional projection is incomplete"
                        )
                    continue
                yield from self._embedded_records(db, str(archive["id"]), metadata, category)

    @staticmethod
    def _needed(table: str, category: str, format_name: str) -> bool:
        """선택 영역에 필요한 테이블만 본문으로 읽는다.

        Args:
            table: 원 테이블 이름.
            category: 조회 영역.
            format_name: 저장 형식.

        Returns:
            bool: 본문 해석이 필요한지 여부.
        """
        if format_name == "record-store-v2":
            return table in (
                {"records", "tasks", "task_criteria", "task_phases"}
                if category == "tasks"
                else {"records", "task_phases"}
            )
        return table in {
            "runtime_records",
            *{
                "sources": ("events",),
                "messages": ("messages",),
                "memory": ("events",),
                "learning": (
                    "lessons",
                    "lesson_history",
                    "learning_observations",
                    "learning_checks",
                ),
            }.get(category, ()),
        }

    @staticmethod
    def _include(table: str, row: dict[str, Any], category: str) -> bool:
        """큰 내부 실행 기록을 관련 기능 조회에 자동 주입하지 않는다.

        Args:
            table: 읽은 테이블.
            row: 원래 행.
            category: 선택 영역.

        Returns:
            bool: 해당 기능으로 해석할 행인지 여부.
        """
        if table == "records":
            return row["kind"] in {
                "tasks": {"checkpoint", "source"},
                "sources": {"source"},
                "memory": {"checkpoint", "evidence"},
                "messages": {"message"},
                "learning": {"lesson"},
                "enclave": {"enclave"},
            }.get(category, set())
        if table == "runtime_records":
            return row["namespace"].split(":", 1)[0] in {
                "tasks": {"task-ledger"},
                "workflows": {"session"},
                "enclave": {"enclave"},
                "sources": {"prompt"},
                "memory": {"artifact"},
            }.get(category, set())
        return True

    def _embedded_records(
        self, db: sqlite3.Connection, archive_id: str, metadata: dict[str, Any], category: str
    ) -> Generator[HistoricalRecord]:
        """압축 원본 전체를 메모리에 올리지 않고 선택 테이블의 행만 복원한다.

        Args:
            db: 보존 사본의 읽기 연결.
            archive_id: 내장 원본 ID.
            metadata: 기록된 크기와 내용 식별값.
            category: 선택할 기능 영역.

        Yields:
            HistoricalRecord: 원래 필드 자료형을 복원한 관련 자료.

        Raises:
            ValueError: 보존한 압축 원본의 크기·내용이 일치하지 않는 경우.
        """
        decoder = zlib.decompressobj()
        digest = hashlib.sha256()
        size = 0
        with tempfile.TemporaryFile() as stream:
            for (chunk,) in db.execute(
                "SELECT data FROM source_archive_chunks WHERE archive_id=? ORDER BY position",
                (archive_id,),
            ):
                pending = chunk
                while pending:
                    block = decoder.decompress(pending, 1048576)
                    stream.write(block)
                    digest.update(block)
                    size += len(block)
                    pending = decoder.unconsumed_tail
            tail = decoder.flush()
            stream.write(tail)
            digest.update(tail)
            size += len(tail)
            if (
                not decoder.eof
                or size != metadata["size"]
                or digest.hexdigest() != metadata["sha256"]
            ):
                raise ValueError("Embedded historical archive does not match its recorded content")
            stream.seek(0)
            count = 0
            columns: list[str] = []
            table = ""
            builder = None
            prefix_base = "sources.item.tables.item"
            for prefix, event, value in ijson.parse(stream, use_float=True):
                if prefix == prefix_base and event == "start_map":
                    columns = []
                    table = ""
                    count = 0
                elif prefix == prefix_base + ".columns.item":
                    columns.append(str(value))
                elif prefix == prefix_base + ".name":
                    table = str(value)
                elif prefix == prefix_base + ".rows.item" and event == "start_array":
                    if category != "unknown" and self._needed(table, category, "runtime-store"):
                        builder = ObjectBuilder()
                if prefix == prefix_base + ".rows.item" and event == "end_array":
                    count += 1
                if prefix == prefix_base and event == "end_map" and category == "unknown":
                    yield HistoricalRecord(
                        key=table,
                        category=category,
                        status="embedded data preserved; activation not inferred",
                        origin="",
                        data={"table": table, "rows": count, "columns": columns},
                        references=(f"source_archives:{archive_id}", table),
                    )
                if builder is not None:
                    builder.event(event, value)
                    if prefix == prefix_base + ".rows.item" and event == "end_array":
                        row = dict(
                            zip(
                                columns,
                                (self._cell(cell) for cell in cast(list[list[Any]], builder.value)),
                                strict=True,
                            )
                        )
                        if self._include(table, row, category):
                            yield from self._runtime(
                                {table: [row]}, category, f"source_archives:{archive_id}"
                            )
                        builder = None

    @staticmethod
    def _cell(cell: list[Any]) -> object:
        """보존 archive의 명시적 SQLite 자료형 태그를 복원한다.

        Args:
            cell: null·text·integer·real·blob 태그와 값.

        Returns:
            object: 원래 SQLite 값.

        Raises:
            ValueError: 인식할 수 없는 자료형 태그인 경우.
        """
        kind, value = cell
        match kind:
            case "null" | "text":
                return value
            case "integer":
                return int(value)
            case "real":
                return float.fromhex(value)
            case "blob":
                return base64.b64decode(value, validate=True)
            case _:
                raise ValueError("Unknown archived SQLite cell type; source remains preserved")

    def _modern(
        self, tables: dict[str, list[dict[str, Any]]], category: str, reference: str
    ) -> list[HistoricalRecord]:
        """13개 테이블 형식의 태스크·원문·보고와 이전 계보를 읽는다.

        Args:
            tables: 원 테이블 자료.
            category: 선택 영역.
            reference: 원본 참조.

        Returns:
            list[HistoricalRecord]: 현재 권한으로 승격하지 않은 자료.
        """
        records = [{**row, "decoded": json.loads(row["data"])} for row in tables["records"]]
        result = []
        if category == "tasks":
            for task in tables["tasks"]:
                checkpoints = [
                    row["decoded"].get("state", {})
                    for row in records
                    if row["kind"] == "checkpoint" and row["task_id"] == task["id"]
                ]
                lineage = cast(
                    dict[str, Any],
                    next((state for state in checkpoints if "original_task_id" in state), {}),
                )
                source = next(
                    (
                        row["decoded"]
                        for row in records
                        if row["kind"] == "source" and row["id"] == task["source_id"]
                    ),
                    None,
                )
                origin = self._origin(
                    str(lineage.get("original_owner", task["owner_id"])),
                    str(lineage.get("original_session", task["owner_id"])),
                    str(lineage.get("original_task_id", task["id"])),
                )
                data = {
                    **task,
                    "source": source,
                    "lineage": lineage,
                    "dependencies": lineage.get("original_task", {})
                    .get("definition", {})
                    .get("dependencies", []),
                    "criteria": [
                        row
                        for row in tables.get("task_criteria", [])
                        if row["task_id"] == task["id"]
                    ],
                    "phases": [
                        row for row in tables.get("task_phases", []) if row["task_id"] == task["id"]
                    ],
                }
                result.append(
                    HistoricalRecord(
                        key=str(task["id"]),
                        category=category,
                        status=task["status"],
                        origin=origin,
                        data=data,
                        references=(reference, "tasks"),
                    )
                )
        elif category == "workflows":
            for row in tables.get("task_phases", []):
                result.append(
                    HistoricalRecord(
                        key=str(row["id"]),
                        category=category,
                        status=row["status"],
                        origin="",
                        data=row,
                        references=(reference, "task_phases"),
                    )
                )
        else:
            kinds = {
                "sources": {"source"},
                "memory": {"checkpoint", "evidence"},
                "messages": {"message"},
                "learning": {"lesson"},
                "enclave": {"enclave"},
            }
            for row in records:
                if row["kind"] in kinds.get(category, set()):
                    result.append(
                        HistoricalRecord(
                            key=row["id"],
                            category=category,
                            status=row["status"],
                            origin="",
                            data=row,
                            references=(reference, "records"),
                        )
                    )
        return result

    def _runtime(
        self, tables: dict[str, list[dict[str, Any]]], category: str, reference: str
    ) -> list[HistoricalRecord]:
        """원 runtime의 JSON·사건·메시지·학습을 순서와 참조를 유지해 읽는다.

        Args:
            tables: 원 runtime 행.
            category: 선택 영역.
            reference: 내장 archive 또는 원본 참조.

        Returns:
            list[HistoricalRecord]: 의미가 알려진 기능 자료와 미상 표지.

        Raises:
            ValueError: 구조화 자료를 해석할 수 없거나 태스크 원장 형식이 다른 경우.
        """
        result = []
        for row in tables.get("runtime_records", []):
            prefix = row["namespace"].split(":", 1)[0]
            if (category, prefix) not in {
                ("tasks", "task-ledger"),
                ("workflows", "session"),
                ("enclave", "enclave"),
                ("sources", "prompt"),
                ("memory", "artifact"),
            }:
                continue
            try:
                payload = json.loads(row["payload"])
            except TypeError, ValueError:
                payload = {"unparsed": row["payload"]}
            if category == "tasks" and isinstance(payload, dict):
                if not isinstance(payload.get("tasks"), list):
                    raise ValueError("Historical task ledger shape is unrecognized")
                for task in payload.get("tasks", []):
                    definition = task.get("definition", {})
                    origin = self._origin(
                        str(payload.get("owner", "unknown")),
                        str(payload.get("session", row["key"])),
                        str(task["id"]),
                    )
                    result.append(
                        HistoricalRecord(
                            key=str(task["id"]),
                            category=category,
                            status=task.get("status"),
                            origin=origin,
                            data={
                                "id": task["id"],
                                "goal": definition.get("goal", ""),
                                "owner_id": payload.get("owner"),
                                "source": None,
                                "lineage": {
                                    "original_task": task,
                                    "original_session": payload.get("session"),
                                    "original_owner": payload.get("owner"),
                                },
                                "criteria": definition.get("acceptance", []),
                                "phases": [],
                                "dependencies": definition.get("dependencies", []),
                            },
                            references=(reference, "runtime_records", str(row["key"])),
                        )
                    )
            elif category == "workflows" and isinstance(payload, dict):
                for key, value in payload.get("workflows", {}).items():
                    result.append(
                        HistoricalRecord(
                            key=key,
                            category=category,
                            status=value.get("status"),
                            origin="",
                            data=value,
                            references=(reference, "runtime_records", str(row["key"])),
                        )
                    )
            else:
                result.append(
                    HistoricalRecord(
                        key=str(row["key"]),
                        category=category,
                        status="historical",
                        origin="",
                        data={"namespace": row["namespace"], "payload": payload},
                        references=(reference, "runtime_records"),
                    )
                )
        selected = {
            "sources": ("events",),
            "messages": ("messages",),
            "learning": ("lessons", "lesson_history", "learning_observations", "learning_checks"),
            "memory": ("events",),
        }.get(category, ())
        for name in selected:
            for index, row in enumerate(tables.get(name, [])):
                result.append(
                    HistoricalRecord(
                        key=str(row.get("id", row.get("sequence", index))),
                        category=category,
                        status=row.get("status"),
                        origin="",
                        data=row,
                        references=(reference, name),
                    )
                )
        return result
