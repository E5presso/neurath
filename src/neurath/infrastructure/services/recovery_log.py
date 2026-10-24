"""장애 원인을 코어 DB와 독립된 append-only 복구 파일과 stderr에 남긴다."""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import override

from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.recovery_log import IRecoveryLogService, RecoveryReceipt


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
