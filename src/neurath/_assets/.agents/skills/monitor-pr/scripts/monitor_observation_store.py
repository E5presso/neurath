"""Process-local monitor observation cache의 atomic JSON resource store입니다."""

import fcntl
import json
import os
from collections.abc import Mapping
from pathlib import Path
from tempfile import NamedTemporaryFile


class MonitorObservationStore:
    """Canonical agent state와 분리된 local observation object 하나를 보존합니다."""

    def __init__(self, path: Path) -> None:
        """Runtime resource resolver가 파생한 observation cache path에 고정합니다.

        Args:
            path: Caller가 public interface로 선택할 수 없는 local cache path입니다.
        """
        self._path = path
        self._lock_path = path.with_name(f"{path.name}.lock")

    def read(self) -> dict[str, object]:
        """Shared file lock 아래 current observation object를 읽습니다.

        Returns:
            File이 없으면 빈 object, 있으면 validated JSON object입니다.

        Raises:
            TypeError: Cache JSON root가 object가 아닐 때 발생합니다.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
            try:
                return self._read_unlocked()
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def write(self, payload: Mapping[str, object]) -> None:
        """Exclusive file lock 아래 observation object 전체를 atomic replace합니다.

        Args:
            payload: Canonical state가 아닌 process-local observation receipt입니다.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                self._write_unlocked(payload)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _read_unlocked(self) -> dict[str, object]:
        if not self._path.exists():
            return {}
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError(f"{self._path} must contain a JSON object")
        return payload

    def _write_unlocked(self, payload: Mapping[str, object]) -> None:
        temporary_name = ""
        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                json.dump(dict(payload), temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, self._path)
            directory_descriptor = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
