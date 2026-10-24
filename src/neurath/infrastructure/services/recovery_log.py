"""장애 원인을 코어 DB와 독립된 append-only 복구 파일과 stderr에 남긴다."""

import hashlib
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import override

from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.recovery_log import (
    IRecoveryLogService,
    RecoveryReceipt,
    RecoveryRecord,
)


@Pod()
class PosixRecoveryLogService(IRecoveryLogService):
    """출력이나 기록 실패로 모델 호출·무한 재시도를 만들지 않는다."""

    @override
    def record(self, detail: str, reference: str) -> RecoveryReceipt:
        """두 독립 경로를 한 번씩 시도하고 둘 다 실패하면 미확인으로 남긴다.

        Args:
            detail: 실제 오류의 본문.
            reference: 실패한 원 사건 참조.

        Returns:
            RecoveryReceipt: 로컬 기록 위치·stderr 제출·실패 원인. 전달 성공은 추정하지 않는다.
        """
        record = (
            json.dumps(
                {
                    "time": datetime.now(UTC).isoformat(),
                    "detail": detail,
                    "reference": reference,
                    "work": "unfinished state preserved; outcome unverified",
                    "delivery": "unverified",
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        errors = []
        submitted = False
        path = None
        try:
            sys.stderr.write(record)
            sys.stderr.flush()
            submitted = True
        except OSError as error:
            errors.append(f"host output failed: {error}")
        try:
            destination = self._destination()
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(destination, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
                stream.write(record)
                stream.flush()
                os.fsync(stream.fileno())
            path = str(destination)
        except (OSError, ValueError) as error:
            errors.append(f"recovery record failed: {error}")
        return RecoveryReceipt(record_path=path, host_submitted=submitted, error="; ".join(errors))

    @override
    def read(self, path: str | None = None) -> Sequence[RecoveryRecord]:
        """원문을 모두 검증한 뒤 반환하며 손상된 행을 빈 기록으로 숨기지 않는다.

        Args:
            path: 선택한 실제 journal 또는 기본 파일.

        Returns:
            Sequence[RecoveryRecord]: 파일을 바꾸지 않고 읽은 원 증상.

        Raises:
            ValueError: 행이 독립 복구 기록 형식이 아닌 경우.
        """
        source = self._destination() if path is None else Path(path).expanduser().resolve()
        if not source.exists() and path is None:
            return ()
        records = []
        with source.open() as stream:
            for number, line in enumerate(stream, 1):
                item = json.loads(line)
                if not isinstance(item, dict) or any(
                    not isinstance(item.get(key), str) or not item[key].strip()
                    for key in ("time", "detail", "reference")
                ):
                    raise ValueError(
                        f"Invalid recovery journal record at {source}:{number}; original preserved"
                    )
                records.append(
                    RecoveryRecord(
                        origin="recovery:" + hashlib.sha256(line.encode()).hexdigest(),
                        detail=item["detail"],
                        reference=item["reference"],
                        journal_reference=f"{source}#L{number}",
                    )
                )
        return tuple(records)

    @staticmethod
    def _destination() -> Path:
        """사용자 상태 디렉터리 안의 독립 복구 기록 경로를 선택한다.

        Returns:
            Path: 코어 DB와 분리된 append-only 파일.

        Raises:
            ValueError: 상태 디렉터리가 절대 경로가 아닌 경우.
        """
        configured = os.environ.get("XDG_STATE_HOME")
        directory = (
            Path(configured).expanduser() if configured else Path.home() / ".local" / "state"
        )
        if not directory.is_absolute():
            raise ValueError("XDG_STATE_HOME must be absolute")
        return directory / "neurath" / "recovery.jsonl"
