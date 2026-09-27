"""Persist session transitions with optimistic CAS and atomic native task admission."""

from __future__ import annotations

import fcntl
import json
from collections.abc import Callable
from pathlib import Path

from scripts.agent_harness.session_events import ForegroundTurnReplaced, KernelEvent
from scripts.agent_harness.session_model import (
    CommitStage,
    ForegroundTurnStatus,
    InvalidRetryLimit,
    InvalidSessionState,
    OptimisticRetryExhausted,
    ProcessState,
    RevisionConflict,
    SessionId,
    SessionNotFound,
    TransitionRejected,
)
from scripts.agent_harness.session_reducer import SessionStateReducer
from scripts.agent_harness.session_state_codec import SessionStateCodec


class SessionStateStore:
    """Revision-based optimistic CAS와 짧은 commit mutex로 snapshot을 저장합니다."""

    def __init__(
        self,
        process_state_path: Path,
        commit_observer: Callable[[CommitStage], None] | None = None,
        max_retries: int = 64,
    ) -> None:
        """Canonical snapshot path에 optimistic transaction boundary를 구성합니다.

        Args:
            process_state_path: Exact session의 canonical process-state JSON path입니다.
            commit_observer: Crash-safety 검증이 durable commit 경계를 관찰할 callback입니다.
            max_retries: Implicit transaction이 revision conflict 뒤 재시도할 상한입니다.

        Raises:
            InvalidRetryLimit: Retry 상한이 1보다 작으면 발생합니다.
        """
        if max_retries < 1:
            raise InvalidRetryLimit("max_retries must be positive")
        self._path = process_state_path
        self._lock_path = process_state_path.with_name(f"{process_state_path.name}.lock")
        from scripts.agent_harness.runtime_database import RuntimeDatabase

        # The old address remains a migration key, never a new JSON snapshot.
        path = process_state_path.absolute()
        if path.parents[1].name != "runs":
            raise InvalidSessionState("session address must belong to the runtime runs directory")
        if path.parents[2].name == ".agents":
            control_root = path.parents[3]
        elif path.parents[2].name == "local" and path.parents[3].name == ".neurath":
            control_root = path.parents[4]
        else:
            raise InvalidSessionState("session address has no common runtime root")
        self._database = RuntimeDatabase(control_root)
        self._record_key = path.parent.name
        self._codec = SessionStateCodec()
        self._reducer = SessionStateReducer()
        self._commit_observer = commit_observer
        self._max_retries = max_retries

    def read(self, expected_session_id: SessionId | None = None) -> ProcessState:
        """Atomic snapshot file을 lock-free로 읽고 typed state로 검증합니다.

        Args:
            expected_session_id: 다른 session의 snapshot을 수용하지 않도록 확인할 identity입니다.

        Returns:
            Schema와 cross-record invariant를 통과한 latest immutable snapshot입니다.

        Raises:
            SessionNotFound: Canonical snapshot file이 존재하지 않으면 발생합니다.
            InvalidSessionState: File이 유효한 JSON snapshot이 아니거나 identity가 다르면
                발생합니다.
        """
        state = self._read_snapshot(expected_session_id, missing_allowed=False)
        if state is None:
            raise SessionNotFound(f"session state is missing: {self._path}")
        return state

    def transact(
        self,
        event: KernelEvent,
        expected_revision: int | None = None,
    ) -> ProcessState:
        """Event를 optimistic CAS로 commit하며 implicit 호출은 충돌 시 재시도합니다.

        Args:
            event: Exact session snapshot에 적용할 typed state transition입니다.
            expected_revision: Caller가 읽은 원본을 강제할 explicit compare version입니다.

        Returns:
            Canonical file에 atomic replace된 snapshot 또는 idempotent 기존 snapshot입니다.

        Raises:
            RevisionConflict: Explicit expected revision이 latest snapshot과 다르면 발생합니다.
            OptimisticRetryExhausted: Implicit transaction이 retry 상한 안에 commit하지
                못하면 발생합니다.
            SessionNotFound: Session 시작 외 event의 snapshot이 존재하지 않으면 발생합니다.
            TransitionRejected: Event가 현재 session state의 invariant와 충돌하면 발생합니다.
            InvalidSessionState: Existing canonical snapshot을 검증할 수 없으면 발생합니다.
        """
        for _attempt in range(self._max_retries):
            snapshot = self._read_snapshot(event.session_id, missing_allowed=True)
            snapshot_revision = None if snapshot is None else snapshot.revision
            if expected_revision is not None and snapshot_revision != expected_revision:
                raise RevisionConflict(
                    f"expected revision {expected_revision}, got {snapshot_revision}"
                )
            candidate = self._reducer.reduce(snapshot, event)
            if candidate is snapshot:
                if snapshot_revision is None:
                    raise InvalidSessionState("no-op transition requires a canonical snapshot")
                try:
                    self._compare_revision_under_lock(event.session_id, snapshot_revision)
                except RevisionConflict:
                    if expected_revision is not None:
                        raise
                    continue
                return candidate
            try:
                return self._compare_and_commit(
                    event.session_id,
                    snapshot_revision,
                    candidate,
                    enforce_task_gate=not isinstance(event, ForegroundTurnReplaced),
                )
            except RevisionConflict:
                if expected_revision is not None:
                    raise
        raise OptimisticRetryExhausted(
            f"session {event.session_id} did not converge after {self._max_retries} retries"
        )

    def _compare_revision_under_lock(
        self,
        session_id: SessionId,
        expected_revision: int,
    ) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                with self._database.transaction() as tx:
                    latest = self._decode_record(tx.get("session", self._record_key), session_id)
                    latest_revision = None if latest is None else latest.revision
                    if latest_revision != expected_revision:
                        raise RevisionConflict(
                            f"expected revision {expected_revision}, got {latest_revision}"
                        )
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _compare_and_commit(
        self,
        session_id: SessionId,
        expected_revision: int | None,
        candidate: ProcessState,
        *,
        enforce_task_gate: bool = True,
    ) -> ProcessState:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                with self._database.transaction() as tx:
                    latest = self._decode_record(tx.get("session", self._record_key), session_id)
                    latest_revision = None if latest is None else latest.revision
                    if latest_revision != expected_revision:
                        raise RevisionConflict(
                            f"expected revision {expected_revision}, got {latest_revision}"
                        )
                    next_revision = 0 if latest_revision is None else latest_revision + 1
                    committed = candidate.with_revision(next_revision)
                    from scripts.agent_harness.task_service import (
                        validate_native_task_grants,
                    )

                    try:
                        validate_native_task_grants(tx, latest, committed)
                    except ValueError as error:
                        raise TransitionRejected(f"native task scope: {error}") from error
                    root_turn = committed.foreground_turns.get(committed.session.root_actor_id)
                    old_turn = (
                        None
                        if latest is None
                        else latest.foreground_turns.get(latest.session.root_actor_id)
                    )
                    if (
                        enforce_task_gate
                        and root_turn is not None
                        and root_turn.status is ForegroundTurnStatus.CLOSED
                        and (old_turn is None or old_turn.status is not ForegroundTurnStatus.CLOSED)
                    ):
                        from scripts.agent_harness.task_service import (
                            require_settled_tasks,
                        )

                        try:
                            require_settled_tasks(tx, committed)
                        except ValueError as error:
                            raise TransitionRejected(f"task Stop gate: {error}") from error
                    tx.put(
                        "session",
                        self._record_key,
                        self._codec.encode(committed),
                        expected_revision=latest_revision,
                    )
                    for actor_id, turn in committed.foreground_turns.items():
                        prompt = turn.user_prompt_receipt
                        if prompt is None or actor_id != committed.session.root_actor_id:
                            continue
                        payload = json.dumps(
                            {"actor_id": str(actor_id), **prompt.to_payload()},
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                        namespace = f"prompt:{session_id}"
                        old_prompt = tx.get(namespace, prompt.authority_reference)
                        if old_prompt is None:
                            tx.put(
                                namespace,
                                prompt.authority_reference,
                                payload,
                                expected_revision=None,
                            )
                        elif old_prompt.payload != payload:
                            raise InvalidSessionState("native prompt reference changed its content")
                    if self._commit_observer is not None:
                        self._commit_observer(CommitStage.BEFORE_REPLACE)
                return committed
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _read_snapshot(
        self,
        expected_session_id: SessionId | None,
        missing_allowed: bool,
    ) -> ProcessState | None:
        import sqlite3

        from scripts.agent_harness.runtime_database import (
            CorruptRecord,
            LegacyStateChanged,
        )

        try:
            return self._load_snapshot(expected_session_id, missing_allowed)
        except (
            CorruptRecord,
            LegacyStateChanged,
            json.JSONDecodeError,
            UnicodeError,
            OSError,
            sqlite3.Error,
        ) as error:
            raise InvalidSessionState("cannot read canonical session state") from error

    def _load_snapshot(self, expected_session_id, missing_allowed):
        with self._database.transaction() as tx:
            record = tx.get("session", self._record_key)
            deleted = tx.was_deleted("session", self._record_key)
        if record is None and not deleted and self._path.is_file():

            def validate(content):
                return self._codec.decode(json.loads(content), expected_session_id).revision

            record = self._database.import_legacy("session", self._record_key, self._path, validate)
        state = self._decode_record(record, expected_session_id)
        if state is None and not missing_allowed:
            raise SessionNotFound(f"session state is missing: {self._record_key}")
        return state

    def _decode_record(self, record, expected_session_id):
        if record is None:
            return None
        try:
            state = self._codec.decode(json.loads(record.payload), expected_session_id)
        except (json.JSONDecodeError, UnicodeError) as error:
            raise InvalidSessionState("cannot decode persisted session") from error
        if state.revision != record.revision:
            raise InvalidSessionState("session and database revisions differ")
        return state

    def exists(self) -> bool:
        """Check canonical state, including a validated pre-cutover import."""
        return self._read_snapshot(None, missing_allowed=True) is not None

    def read_transaction(self, transaction, expected_session_id: SessionId) -> ProcessState:
        """Read authority inside a caller's shared task or Stop transaction.

        This performs no nested connection, migration or domain transition.
        The caller must use this project's database and the exact session key.
        """
        databases = transaction.connection.execute("PRAGMA database_list").fetchall()
        main = next((row[2] for row in databases if row[1] == "main"), None)
        if main is None or Path(main).resolve() != self._database.path.resolve():
            raise InvalidSessionState("session transaction belongs to another project")
        if self._record_key != str(expected_session_id):
            raise InvalidSessionState("session transaction identity mismatch")
        state = self._decode_record(
            transaction.get("session", self._record_key), expected_session_id
        )
        if state is None:
            raise SessionNotFound(f"session state is missing: {expected_session_id}")
        return state

    def modified_at(self) -> float:
        self.read()
        with self._database.transaction() as tx:
            return tx.connection.execute(
                "SELECT updated FROM runtime_records WHERE namespace='session' AND key=?",
                (self._record_key,),
            ).fetchone()[0]
