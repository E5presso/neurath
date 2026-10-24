"""SQLite 연결 관찰·exclusive 잠금·원자적 경로 퇴역과 실제 사건 파일을 관리한다."""

import json
import os
import shutil
import sqlite3
import subprocess
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from typing import Any, override
from urllib.parse import unquote
from uuid import UUID, uuid7

from spakky.core.pod.annotations.pod import Pod
from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from sqlalchemy.engine import URL

from neurath.application.ports.services.historical_store import IHistoricalStoreService
from neurath.application.ports.services.store_transition import (
    IStoreTransitionService,
    StoreFence,
    TransitionEvent,
)
from neurath.serialization import encode_uuid


@Pod()
class PosixStoreTransitionService(IStoreTransitionService):
    """실제 원 경로를 퇴역하며 과거 신원·임대·성공을 만들지 않는다."""

    def __init__(
        self, historical: IHistoricalStoreService, connection: AsyncConnectionManager
    ) -> None:
        """원본 보존과 사본 검증 계약을 받는다.

        Args:
            historical: SQLite backup 기반 사본 생성.
            connection: 실제 요청에 주입된 코어 연결 설정.
        """
        self.historical = historical
        self.connection = connection

    @staticmethod
    def _read_fence(directory: Path) -> StoreFence:
        """실제 전환 폴더의 기술 기록을 읽는다.

        Args:
            directory: 원 경로가 가리키는 전환 폴더.

        Returns:
            StoreFence: 원 접속 경로와 보존 위치.

        Raises:
            ValueError: Neurath 전환 기록으로 인식할 수 없는 경우.
        """
        data = json.loads((directory / "transition.json").read_text())
        if data.get("format") != "neurath-transition-v1":
            raise ValueError("Unrecognized transition record; no event was consumed")
        return StoreFence(
            source=data["source"],
            directory=str(directory),
            snapshot=data["snapshot"],
            retired=data["retired"],
        )

    @staticmethod
    def _require_disconnected(source: Path) -> None:
        """OS 파일 연결 관찰을 못 하거나 다른 프로세스가 열고 있으면 전환하지 않는다.

        Args:
            source: 실제 원 SQLite 파일.

        Raises:
            ValueError: 관찰 실패 또는 열린 외부 연결이 있는 경우.
        """
        executable = shutil.which("lsof")
        if executable is None:
            raise ValueError("Cannot observe SQLite file users; source was not fenced")
        result = subprocess.run(
            [executable, "-F", "p", "--", str(source)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode not in (0, 1) or result.stderr.strip():
            raise ValueError("SQLite file-user observation was unsuccessful; source was not fenced")
        pids = {int(line[1:]) for line in result.stdout.splitlines() if line.startswith("p")}
        if pids - {os.getpid()}:
            raise ValueError("Existing SQLite connections must be stopped before cutover")

    @override
    def fence(self, source: str, archive_directory: str) -> StoreFence:
        """원본/WAL 보존 후 실제 쓰기 잠금을 확인하고 원 경로를 원자적으로 퇴역한다.

        Args:
            source: 퇴역할 실제 SQLite 파일.
            archive_directory: 일관된 사본과 원본 파일 보관 위치.

        Returns:
            StoreFence: 새 연결이 SQLite로 열 수 없는 원 경로와 복구 자료.

        Raises:
            ValueError: 형식·연결 정지·사본 이후 불변 상태를 확인하지 못한 경우.
        """
        path = Path(source).expanduser().resolve(strict=True)
        if path.is_dir():
            return self._read_fence(path)
        inspection = self.historical.inspect(str(path))
        if inspection.format == "unknown":
            raise ValueError("Unrecognized SQLite source was preserved without cutover")
        self._require_disconnected(path)
        with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=0)) as db:
            version = db.execute("PRAGMA data_version").fetchone()[0]
            snapshot = self.historical.snapshot(str(path), archive_directory, ())
            db.execute("PRAGMA journal_mode=DELETE").fetchone()
            db.execute("BEGIN EXCLUSIVE")
            try:
                self._require_disconnected(path)
                if db.execute("PRAGMA data_version").fetchone()[0] != version:
                    raise ValueError("Source changed after snapshot; preserve and prepare again")
                return self._seal(path, snapshot.path)
            finally:
                db.rollback()

    @staticmethod
    def _seal(path: Path, snapshot: str) -> StoreFence:
        """원 데이터 inode를 보존하고 원 접속 경로를 디렉터리 링크로 원자 교체한다.

        Args:
            path: SQLite exclusive 잠금을 가진 원 경로.
            snapshot: 먼저 보존한 일관된 사본.

        Returns:
            StoreFence: 실제 원 경로 퇴역 결과.
        """
        directory = path.with_name(path.name + ".transition-" + str(uuid7()))
        directory.mkdir(mode=0o700)
        retired = directory / "retired.sqlite3"
        os.link(path, retired)
        marker = directory / "transition.json"
        marker.write_text(
            json.dumps(
                {
                    "format": "neurath-transition-v1",
                    "source": str(path),
                    "snapshot": snapshot,
                    "retired": str(retired),
                    "recovery": "Use a compatible recovery copy; do not reactivate an older database over newer records",
                }
            )
        )
        marker.chmod(0o600)
        with marker.open("rb") as stream:
            os.fsync(stream.fileno())
        link = directory / "source-link"
        link.symlink_to(directory, target_is_directory=True)
        os.replace(link, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return StoreFence(
            source=str(path), directory=str(directory), snapshot=snapshot, retired=str(retired)
        )

    @staticmethod
    def _path_for(url: URL) -> Path:
        """실제 주입된 연결 URL에서 SQLite 파일 경로를 읽는다.

        Args:
            url: 요청에 사용하는 실제 SQLAlchemy 연결 주소.

        Returns:
            Path: 현재 코어 접속 경로.

        Raises:
            ValueError: SQLite 파일 경로로 해석할 수 없는 설정인 경우.
        """
        if not url.drivername.startswith("sqlite") or url.database is None:
            raise ValueError("Transition event storage requires a SQLite file path")
        return Path(unquote(url.database.removeprefix("file:"))).expanduser().resolve()

    @staticmethod
    def _append(path: Path, data: dict[str, Any]) -> None:
        """프로세스 사이 접수 순서를 잠금과 fsync로 보존한다.

        Args:
            path: 전환 폴더 안의 사건 또는 적용 기록.
            data: 한 번 기록할 JSON 자료.
        """
        import fcntl

        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            stream.write(json.dumps(data, default=encode_uuid, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    @override
    def enqueue(self, command: dict[str, Any], payload: dict[str, Any]) -> UUID | None:
        """현재 코어의 실제 퇴역 경로일 때만 사건을 파일에 남긴다.

        Args:
            command: 정규화한 훅 입력.
            payload: 원 호스트 JSON.

        Returns:
            UUID | None: 내구적으로 기록한 사건 또는 정상 경로의 None.
        """
        path = self._path_for(self.connection.connection.url)
        if not path.is_dir() or not (path / "transition.json").is_file():
            return None
        fence = self._read_fence(path)
        uid = uuid7()
        self._append(
            Path(fence.directory) / "events.jsonl",
            {"uid": uid, "command": command, "payload": payload},
        )
        return uid

    @override
    def pending(self, directory: str) -> Sequence[TransitionEvent]:
        """원 접수 순서를 유지하며 적용 확인되지 않은 사건을 읽는다.

        Args:
            directory: 실제 전환 폴더.

        Returns:
            Sequence[TransitionEvent]: 미처리 사건 원문과 내부 ID.
        """
        root = Path(self._read_fence(Path(directory).resolve()).directory)
        events = root / "events.jsonl"
        applied = root / "applied.jsonl"
        completed = (
            {json.loads(line)["uid"] for line in applied.read_text().splitlines()}
            if applied.exists()
            else set()
        )
        if not events.exists():
            return ()
        result = []
        for line in events.read_text().splitlines():
            item = json.loads(line)
            if item["uid"] not in completed:
                result.append(
                    TransitionEvent(
                        uid=UUID(item["uid"]), command=item["command"], payload=item["payload"]
                    )
                )
        return tuple(result)

    @override
    def acknowledge(self, directory: str, event_id: UUID) -> None:
        """현재 코어에 커밋한 사건만 적용 기록으로 남긴다.

        Args:
            directory: 원 사건 폴더.
            event_id: 실제 코어에 반영한 내부 ID.
        """
        fence = self._read_fence(Path(directory).resolve())
        self._append(
            Path(fence.directory) / "applied.jsonl",
            {"uid": event_id, "host_response_delivery": "unverified"},
        )
