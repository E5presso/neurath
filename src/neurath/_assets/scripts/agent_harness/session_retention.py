"""Terminal coding-agent session의 bounded retention과 exact GC를 관리합니다."""

import fcntl
import os
import time
from collections.abc import Callable
from pathlib import Path

from scripts.agent_harness.session_kernel import (
    ProcessState,
    SessionEnded,
    SessionId,
    SessionLocator,
    SessionStateStore,
    SessionStatus,
)
from scripts.agent_harness.state_handle import StateHandle


class SessionRetentionError(RuntimeError):
    """Session이 retention 또는 collection invariant를 만족하지 못했음을 나타냅니다."""


class InvalidRetentionPolicy(SessionRetentionError):
    """Retention 기간이 음수일 때 발생합니다."""


class ActiveSessionRetentionError(SessionRetentionError):
    """Active session을 collection 대상으로 취급하려 할 때 발생합니다."""


class SessionRetentionReceipt:
    """Terminal transition과 operational snapshot GC 경계를 고정합니다."""

    __slots__ = (
        "eligible_at_epoch",
        "eligible_for_gc",
        "ended_revision",
        "session_id",
    )

    def __init__(
        self,
        *,
        session_id: SessionId,
        ended_revision: int,
        eligible_at_epoch: float,
        eligible_for_gc: bool,
    ) -> None:
        """Session end 결과와 retention deadline을 immutable하게 저장합니다.

        Args:
            session_id: 종료된 exact coding-agent session identity입니다.
            ended_revision: SessionEnded가 commit된 process-state revision입니다.
            eligible_at_epoch: Operational snapshot을 제거할 수 있는 epoch second입니다.
            eligible_for_gc: Receipt 생성 시점에 deadline이 지났으면 참입니다.
        """
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "ended_revision", ended_revision)
        object.__setattr__(self, "eligible_at_epoch", eligible_at_epoch)
        object.__setattr__(self, "eligible_for_gc", eligible_for_gc)

    session_id: SessionId
    """종료된 exact session identity입니다."""

    ended_revision: int
    """Terminal transition 뒤 canonical process-state revision입니다."""

    eligible_at_epoch: float
    """Bounded diagnostic retention이 끝나는 epoch second입니다."""

    eligible_for_gc: bool
    """Receipt 생성 시점에 operational snapshot을 수거할 수 있는지 나타냅니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성된 receipt의 변경을 거부합니다.

        Args:
            name: 변경하려는 attribute 이름입니다.
            value: 새로 대입하려는 값입니다.

        Raises:
            AttributeError: Receipt는 생성 뒤 항상 immutable입니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class SessionRetentionManager:
    """Exact session end와 retention-expired collection을 scan 없이 수행합니다."""

    def __init__(
        self,
        locator: SessionLocator,
        *,
        retention_seconds: float,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Canonical locator와 bounded retention policy를 결합합니다.

        Args:
            locator: Session ID를 isolated persistence path로 해석합니다.
            retention_seconds: Terminal process state를 diagnostic용으로 보존할 초입니다.
            clock: Deadline 판정에 사용할 injectable epoch-second clock입니다.

        Raises:
            InvalidRetentionPolicy: Retention 기간이 음수이면 발생합니다.
        """
        if retention_seconds < 0:
            raise InvalidRetentionPolicy("retention_seconds must not be negative")
        self._locator = locator
        self._retention_seconds = retention_seconds
        self._clock = clock

    def end(self, handle: StateHandle, *, idempotency_key: str) -> SessionRetentionReceipt:
        """Root-authorized terminal transition 뒤 enclave를 즉시 제거합니다.

        Args:
            handle: Exact runtime session과 current actor에 바인딩된 authority입니다.
            idempotency_key: 동일 SessionEnded retry를 식별하는 stable key입니다.

        Returns:
            Terminal revision과 process-state collection deadline입니다.
        """
        state = handle.apply(
            SessionEnded(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                idempotency_key=idempotency_key,
            )
        )
        paths = self._locator.locate(handle.session_id)
        from scripts.agent_harness.enclave_store import EnclaveStore
        EnclaveStore(self._locator, max_bytes=4096).delete_terminal(handle.session_id)
        eligible_at_epoch = SessionStateStore(paths.process_state).modified_at() + self._retention_seconds
        return SessionRetentionReceipt(
            session_id=handle.session_id,
            ended_revision=state.revision,
            eligible_at_epoch=eligible_at_epoch,
            eligible_for_gc=self._clock() >= eligible_at_epoch,
        )

    def collect_expired(self, session_id: SessionId) -> bool:
        """Exact terminal snapshot을 deadline 뒤 원자적 owner check와 함께 제거합니다.

        Repository의 다른 session을 scan하지 않습니다. 이미 수거된 exact session은
        idempotent하게 거짓을 반환합니다.

        Args:
            session_id: 수거 여부를 판정할 exact session identity입니다.

        Returns:
            이번 호출이 canonical process state를 제거했으면 참입니다.

        Raises:
            ActiveSessionRetentionError: Exact session이 아직 active이면 발생합니다.
        """
        paths = self._locator.locate(session_id)
        store = SessionStateStore(paths.process_state)
        if not store.exists():
            return False
        paths.directory.mkdir(parents=True, exist_ok=True)
        with paths.process_state_lock.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                with store._database.transaction() as tx:
                    record = tx.get("session", store._record_key)
                    state = store._decode_record(record, session_id)
                    if state is None:
                        return False
                    if state.session.status is not SessionStatus.ENDED:
                        raise ActiveSessionRetentionError(
                            f"active session is not eligible for collection: {session_id}"
                        )
                    modified = tx.connection.execute(
                        "SELECT updated FROM runtime_records WHERE namespace='session' AND key=?",
                        (store._record_key,),
                    ).fetchone()[0]
                    if self._clock() < modified + self._retention_seconds:
                        return False
                    if tx.get("enclave", str(session_id)) is not None:
                        raise SessionRetentionError(
                            f"terminal session enclave must be deleted before collection: {session_id}"
                        )
                    tx.delete("session", store._record_key, expected_revision=state.revision)
                    return True
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _read_exact_state(self, path: Path, session_id: SessionId) -> ProcessState:
        return SessionStateStore(path).read(session_id)

    def _delete_enclave(self, enclave_path: Path, lock_path: Path) -> None:
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                if enclave_path.exists():
                    enclave_path.unlink()
                    self._fsync_directory(enclave_path.parent)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _fsync_directory(self, directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
