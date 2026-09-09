"""Session-local enclave facts를 bounded latest-only snapshot으로 보존합니다."""

import hashlib
import json
from collections.abc import Callable, Mapping
from enum import StrEnum
from functools import partial
from pathlib import Path
from types import MappingProxyType
from scripts.agent_harness.runtime_database import RuntimeDatabase

from scripts.agent_harness.session_kernel import (
    ActorId,
    ProcessState,
    SessionId,
    SessionKernel,
    SessionLocator,
    SessionStatus,
    SessionStateStore,
    TurnId,
)


class EnclaveSourceKind(StrEnum):
    """Enclave fact를 확정한 근거의 종류입니다."""

    USER = "user"
    """사용자가 현재 session invariant를 직접 확정했습니다."""
    AGENT = "agent"
    """Root agent가 session 문맥에서 현재 invariant를 판단했습니다."""
    HARNESS = "harness"
    """Deterministic harness가 관찰 가능한 사실을 확정했습니다."""


class EnclaveStoreError(RuntimeError):
    """Enclave persistence contract가 요청을 처리할 수 없음을 나타냅니다."""


class EnclaveAuthorityError(EnclaveStoreError):
    """Session root actor가 아닌 actor의 authoritative mutation을 거부합니다."""


class EnclaveBudgetExceeded(EnclaveStoreError):
    """Mutation 결과가 enclave byte budget을 넘었음을 나타냅니다."""


class EnclaveConflict(EnclaveStoreError):
    """Expected digest와 lock 안에서 읽은 최신 snapshot이 다름을 나타냅니다."""

    def __init__(self, expected_digest: str, actual_digest: str) -> None:
        """충돌 진단에 필요한 expected/current digest를 보존합니다.

        Args:
            expected_digest: Caller가 read한 snapshot digest입니다.
            actual_digest: Exclusive lock 안에서 다시 읽은 current digest입니다.
        """
        self.expected_digest = expected_digest
        self.actual_digest = actual_digest
        super().__init__(
            f"enclave digest conflict: expected {expected_digest}, actual {actual_digest}"
        )


class EnclaveRetryExhausted(EnclaveStoreError):
    """Implicit optimistic mutation이 bounded retry 안에 수렴하지 못했을 때 발생합니다."""


class AuthorityRevisionConflictError(EnclaveStoreError):
    """Active/root authority는 같지만 optimistic session revision이 바뀌었습니다."""


class InvalidEnclaveRetryLimit(EnclaveStoreError):
    """Enclave optimistic retry 상한이 양수가 아닐 때 발생합니다."""


class EnclaveStateInvalid(EnclaveStoreError):
    """Canonical enclave가 schema 또는 identity contract를 위반했음을 나타냅니다."""


class EnclaveFact:
    """현재 session invariant 하나와 최소 provenance를 표현합니다."""

    __slots__ = ("_source_kind", "_source_turn_id", "_value")

    def __init__(
        self,
        *,
        value: str,
        source_kind: EnclaveSourceKind,
        source_turn_id: TurnId,
    ) -> None:
        """History를 포함하지 않는 current fact를 구성합니다.

        Args:
            value: 현재 보존해야 하는 fact 본문입니다.
            source_kind: Fact를 확정한 근거의 종류입니다.
            source_turn_id: 현재 값을 확정한 session turn입니다.

        Raises:
            EnclaveStateInvalid: Fact field가 비어 있으면 발생합니다.
        """
        if not value:
            raise EnclaveStateInvalid("enclave fact value must not be empty")
        if not str(source_turn_id):
            raise EnclaveStateInvalid("enclave fact source_turn_id must not be empty")
        self._value = value
        self._source_kind = source_kind
        self._source_turn_id = source_turn_id

    @property
    def value(self) -> str:
        """현재 fact 본문을 반환합니다.

        Returns:
            Enclave에 보존된 현재 fact 본문입니다.
        """
        return self._value

    @property
    def source_kind(self) -> EnclaveSourceKind:
        """현재 fact의 provenance 종류를 반환합니다.

        Returns:
            Fact를 확정한 근거의 종류입니다.
        """
        return self._source_kind

    @property
    def source_turn_id(self) -> TurnId:
        """현재 fact를 확정한 turn identity를 반환합니다.

        Returns:
            Fact의 current value를 확정한 session turn identity입니다.
        """
        return self._source_turn_id

    def to_payload(self) -> dict[str, str]:
        """Latest-only JSON fact shape를 반환합니다.

        Returns:
            Value와 최소 provenance만 포함한 JSON object입니다.
        """
        return {
            "value": self._value,
            "source_kind": self._source_kind.value,
            "source_turn_id": str(self._source_turn_id),
        }


class EnclaveSnapshot:
    """한 session의 immutable current-fact view입니다."""

    SCHEMA = "neurath.coding-agent-enclave.v1"

    __slots__ = ("_digest", "_facts", "_session_id")

    def __init__(self, session_id: SessionId, facts: Mapping[str, EnclaveFact]) -> None:
        """Canonical session identity와 fact map을 snapshot으로 고정합니다.

        Args:
            session_id: 이 snapshot을 소유하는 coding-agent session입니다.
            facts: Stable key별 최신 fact입니다.
        """
        self._session_id = session_id
        self._facts = MappingProxyType(dict(facts))
        self._digest = hashlib.sha256(self._canonical_content()).hexdigest()

    @property
    def session_id(self) -> SessionId:
        """Snapshot을 소유하는 session identity를 반환합니다.

        Returns:
            Enclave와 byte-for-byte 결속된 canonical session identity입니다.
        """
        return self._session_id

    @property
    def facts(self) -> Mapping[str, EnclaveFact]:
        """Stable key별 최신 fact만 포함한 read-only mapping을 반환합니다.

        Returns:
            History와 tombstone이 없는 current fact mapping입니다.
        """
        return self._facts

    @property
    def digest(self) -> str:
        """Persisted revision 없이 optimistic CAS에 사용하는 digest를 반환합니다.

        Returns:
            Canonical snapshot content의 SHA-256 digest입니다.
        """
        return self._digest

    def to_payload(self) -> dict[str, object]:
        """History와 revision이 없는 canonical enclave payload를 반환합니다.

        Returns:
            Schema, exact session identity, current facts만 포함한 JSON object입니다.
        """
        return {
            "schema": self.SCHEMA,
            "session_id": str(self._session_id),
            "facts": {key: fact.to_payload() for key, fact in sorted(self._facts.items())},
        }

    def _canonical_content(self) -> bytes:
        return json.dumps(
            self.to_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")


class EnclaveStore:
    """Root-authoritative enclave를 digest CAS와 짧은 commit mutex로 보존합니다."""

    def __init__(
        self,
        locator: SessionLocator,
        *,
        max_bytes: int,
        max_retries: int = 64,
    ) -> None:
        """Session locator와 serialized snapshot 상한을 고정합니다.

        Args:
            locator: Exact session path를 결정하는 canonical locator입니다.
            max_bytes: UTF-8 canonical JSON 전체가 넘을 수 없는 byte 수입니다.
            max_retries: Expected digest를 지정하지 않은 mutation의 conflict retry
                상한입니다.

        Raises:
            EnclaveBudgetExceeded: Byte 상한이 양수가 아니면 발생합니다.
            InvalidEnclaveRetryLimit: Retry 상한이 양의 integer가 아니면
                발생합니다.
        """
        if max_bytes <= 0:
            raise EnclaveBudgetExceeded("enclave max_bytes must be positive")
        if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 1:
            raise InvalidEnclaveRetryLimit("max_retries must be a positive integer")
        self._locator = locator
        self._kernel = SessionKernel(locator)
        self._database = RuntimeDatabase(locator.control_root)
        self._max_bytes = max_bytes
        self._max_retries = max_retries

    def read(self, session_id: SessionId) -> EnclaveSnapshot:
        """Exact session enclave의 current snapshot을 읽습니다.

        Args:
            session_id: 읽을 session identity입니다.

        Returns:
            History를 포함하지 않는 current enclave snapshot입니다.

        Raises:
            EnclaveStateInvalid: Canonical file이 없거나 schema가 잘못되면 발생합니다.
        """
        enclave_path = self._locator.locate(session_id).enclave
        return self._read_snapshot(enclave_path, session_id)

    def set(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        key: str,
        fact: EnclaveFact,
        *,
        expected_digest: str | None = None,
    ) -> EnclaveSnapshot:
        """Stable key의 현재 fact를 완전히 교체합니다.

        Args:
            session_id: Mutation 대상 session입니다.
            actor_id: Mutation authority를 주장하는 actor입니다.
            key: Session 안에서 안정적인 fact key입니다.
            fact: 이전 값을 대체할 current fact입니다.
            expected_digest: Caller가 직전에 read한 snapshot digest입니다.

        Returns:
            Commit된 latest-only enclave snapshot입니다.

        Raises:
            EnclaveAuthorityError: Actor가 session root가 아니면 발생합니다.
            EnclaveBudgetExceeded: 결과가 byte budget을 넘으면 발생합니다.
            EnclaveConflict: Expected snapshot 이후 concurrent mutation이 발생하면
                발생합니다.
            EnclaveStateInvalid: Key 또는 canonical state가 잘못되면 발생합니다.
        """
        self._validate_key(key)
        return self._mutate(
            session_id,
            actor_id,
            partial(self._set_fact, session_id, key, fact),
            expected_digest=expected_digest,
        )

    def delete(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        key: str,
        *,
        expected_digest: str | None = None,
    ) -> EnclaveSnapshot:
        """Stable key와 그 값을 tombstone 없이 완전히 제거합니다.

        Args:
            session_id: Mutation 대상 session입니다.
            actor_id: Mutation authority를 주장하는 actor입니다.
            key: 제거할 current fact key입니다.
            expected_digest: Caller가 직전에 read한 snapshot digest입니다.

        Returns:
            Commit된 latest-only enclave snapshot입니다.

        Raises:
            EnclaveAuthorityError: Actor가 session root가 아니면 발생합니다.
            EnclaveConflict: Expected snapshot 이후 concurrent mutation이 발생하면
                발생합니다.
            EnclaveStateInvalid: Key 또는 canonical state가 잘못되면 발생합니다.
        """
        self._validate_key(key)
        return self._mutate(
            session_id,
            actor_id,
            partial(self._delete_fact, session_id, key),
            expected_digest=expected_digest,
        )

    def replace_facts(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        facts: Mapping[str, EnclaveFact],
        *,
        expected_digest: str,
    ) -> EnclaveSnapshot:
        """Current fact map 전체를 하나의 optimistic commit으로 교체합니다.

        Args:
            session_id: 전체 snapshot을 교체할 exact session입니다.
            actor_id: Authoritative mutation을 요청하는 root actor입니다.
            facts: Commit 이후 enclave가 담을 latest-only fact map입니다.
            expected_digest: Caller가 읽은 target enclave의 원본 digest입니다.

        Returns:
            Byte budget 검증 후 한 번에 commit된 complete snapshot입니다.

        Raises:
            EnclaveAuthorityError: Actor가 session root가 아니면 발생합니다.
            EnclaveBudgetExceeded: 전체 candidate가 byte budget을 넘으면 발생합니다.
            EnclaveConflict: Target과 commit mutex 사이에 원본이 바뀌면 발생합니다.
            EnclaveStateInvalid: Fact key 또는 value type이 잘못되면 발생합니다.
        """
        canonical_facts: dict[str, EnclaveFact] = {}
        for key, fact in facts.items():
            self._validate_key(key)
            if not isinstance(fact, EnclaveFact):
                raise EnclaveStateInvalid("enclave facts must contain EnclaveFact values")
            canonical_facts[key] = fact
        return self._mutate(
            session_id,
            actor_id,
            partial(
                self._replace_fact_map,
                session_id,
                MappingProxyType(canonical_facts),
            ),
            expected_digest=expected_digest,
        )

    @staticmethod
    def _set_fact(
        session_id: SessionId,
        key: str,
        fact: EnclaveFact,
        current: EnclaveSnapshot,
    ) -> EnclaveSnapshot:
        """Current snapshot에 fact 하나를 적용한 immutable candidate를 만듭니다.

        Args:
            session_id: Candidate가 소유할 exact session입니다.
            key: 추가하거나 교체할 stable fact key입니다.
            fact: Key에 대입할 latest fact입니다.
            current: Transform의 원본 snapshot입니다.

        Returns:
            Original을 변경하지 않고 fact를 반영한 candidate입니다.
        """
        facts = dict(current.facts)
        facts[key] = fact
        return EnclaveSnapshot(session_id, facts)

    @staticmethod
    def _delete_fact(
        session_id: SessionId,
        key: str,
        current: EnclaveSnapshot,
    ) -> EnclaveSnapshot:
        """Current snapshot에서 fact 하나를 제거한 immutable candidate를 만듭니다.

        Args:
            session_id: Candidate가 소유할 exact session입니다.
            key: 제거할 stable fact key입니다.
            current: Transform의 원본 snapshot입니다.

        Returns:
            Original을 변경하지 않고 key를 제거한 candidate입니다.
        """
        facts = dict(current.facts)
        facts.pop(key, None)
        return EnclaveSnapshot(session_id, facts)

    @staticmethod
    def _replace_fact_map(
        session_id: SessionId,
        facts: Mapping[str, EnclaveFact],
        _current: EnclaveSnapshot,
    ) -> EnclaveSnapshot:
        """Prepared complete fact map을 한 snapshot candidate로 고정합니다.

        Args:
            session_id: Candidate가 소유할 exact session입니다.
            facts: Lock 밖에서 검증한 complete latest-only map입니다.
            _current: CAS에서 검증할 원본 snapshot이며 map 계산에는 쓰지 않습니다.

        Returns:
            Prepared facts와 exact session이 결속된 complete candidate입니다.
        """
        return EnclaveSnapshot(session_id, facts)

    def _mutate(
        self,
        session_id: SessionId,
        actor_id: ActorId,
        transform: Callable[[EnclaveSnapshot], EnclaveSnapshot],
        *,
        expected_digest: str | None,
    ) -> EnclaveSnapshot:
        enclave_path = self._locator.locate(session_id).enclave
        for _attempt in range(self._max_retries):
            authority = self._require_root_actor(session_id, actor_id)
            current = self._read_snapshot(enclave_path, session_id)
            if expected_digest is not None and current.digest != expected_digest:
                raise EnclaveConflict(expected_digest, current.digest)
            candidate = transform(current)
            if not isinstance(candidate, EnclaveSnapshot):
                raise EnclaveStateInvalid("enclave transform must return a snapshot")
            serialized = self._serialize(candidate)
            try:
                return self._compare_and_commit(
                    enclave_path,
                    session_id,
                    authority,
                    current.digest,
                    candidate,
                    serialized,
                )
            except AuthorityRevisionConflictError:
                continue
            except EnclaveConflict:
                if expected_digest is not None:
                    raise
        raise EnclaveRetryExhausted(
            f"enclave {session_id} did not converge after {self._max_retries} retries"
        )

    def _require_root_actor(
        self,
        session_id: SessionId,
        actor_id: ActorId,
    ) -> ProcessState:
        state = self._kernel.inspect(session_id)
        if state.session.status is not SessionStatus.ACTIVE:
            raise EnclaveAuthorityError(f"terminal session rejects enclave mutation: {session_id}")
        if state.session.root_actor_id != actor_id:
            raise EnclaveAuthorityError(
                f"actor {actor_id} is not root actor for session {session_id}"
            )
        return state

    def _validate_key(self, key: str) -> None:
        if not key or key.strip() != key:
            raise EnclaveStateInvalid("enclave fact key must be a non-blank stable key")

    def _read_snapshot(
        self,
        enclave_path: Path,
        session_id: SessionId,
    ) -> EnclaveSnapshot:
        record = self._record(session_id)
        if record is None:
            raise EnclaveStateInvalid(f"canonical enclave is missing: {enclave_path}")
        return self._decode_snapshot(record.payload, session_id)

    def _decode_snapshot(self, content: bytes, session_id: SessionId) -> EnclaveSnapshot:
        try:
            raw_payload: object = json.loads(content)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise EnclaveStateInvalid("canonical enclave is invalid") from exc
        if not isinstance(raw_payload, dict):
            raise EnclaveStateInvalid("canonical enclave root must be an object")
        schema = raw_payload.get("schema")
        persisted_session_id = raw_payload.get("session_id")
        raw_facts = raw_payload.get("facts")
        if schema != EnclaveSnapshot.SCHEMA:
            raise EnclaveStateInvalid("canonical enclave schema is unsupported")
        if persisted_session_id != str(session_id):
            raise EnclaveStateInvalid("canonical enclave session identity mismatch")
        if not isinstance(raw_facts, dict):
            raise EnclaveStateInvalid("canonical enclave facts must be an object")
        facts: dict[str, EnclaveFact] = {}
        for key, raw_fact in raw_facts.items():
            if not isinstance(key, str) or not isinstance(raw_fact, dict):
                raise EnclaveStateInvalid("canonical enclave fact entry is invalid")
            facts[key] = self._parse_fact(raw_fact)
        return EnclaveSnapshot(session_id, facts)

    def _parse_fact(self, raw_fact: dict[object, object]) -> EnclaveFact:
        if set(raw_fact) != {"value", "source_kind", "source_turn_id"}:
            raise EnclaveStateInvalid("canonical enclave fact fields are invalid")
        value = raw_fact.get("value")
        source_kind = raw_fact.get("source_kind")
        source_turn_id = raw_fact.get("source_turn_id")
        if not isinstance(value, str) or not isinstance(source_kind, str):
            raise EnclaveStateInvalid("canonical enclave fact value or source_kind is invalid")
        if not isinstance(source_turn_id, str):
            raise EnclaveStateInvalid("canonical enclave source_turn_id is invalid")
        try:
            parsed_source_kind = EnclaveSourceKind(source_kind)
        except ValueError as exc:
            raise EnclaveStateInvalid("canonical enclave source_kind is unsupported") from exc
        return EnclaveFact(
            value=value,
            source_kind=parsed_source_kind,
            source_turn_id=TurnId(source_turn_id),
        )

    def _compare_and_commit(
        self,
        enclave_path: Path,
        session_id: SessionId,
        expected_authority: ProcessState,
        expected_digest: str,
        candidate: EnclaveSnapshot,
        serialized: bytes,
    ) -> EnclaveSnapshot:
        """Session authority와 enclave digest를 한 commit fence에서 비교합니다.

        Args:
            enclave_path: Exact session enclave path입니다.
            session_id: Persisted identity를 재검증할 exact session입니다.
            expected_authority: Lock 밖에서 검증한 exact active/root session revision입니다.
            expected_digest: Lock 밖에서 읽은 immutable 원본 digest입니다.
            candidate: Lock 밖에서 transform한 다음 snapshot입니다.
            serialized: Lock 밖에서 byte budget까지 검증한 canonical JSON입니다.

        Returns:
            Authority와 digest compare 뒤 commit된 current 또는 candidate snapshot입니다.

        Raises:
            EnclaveAuthorityError: Commit보다 terminal/root authority 변경이 먼저
                확정되면 발생합니다.
            EnclaveConflict: Commit 직전 current digest가 caller의 원본과 다르면
                발생합니다.
        """
        paths = self._locator.locate(session_id)
        session_store = SessionStateStore(paths.process_state)
        with self._database.transaction() as tx:
            authority = session_store.read_transaction(tx, session_id)
            self._recheck_authority(session_id, expected_authority, authority)
            record = tx.get("enclave", str(session_id))
            if record is None:
                raise EnclaveStateInvalid("canonical enclave is missing")
            latest = self._decode_snapshot(record.payload, session_id)
            if latest.digest != expected_digest:
                raise EnclaveConflict(expected_digest, latest.digest)
            if candidate.digest == latest.digest:
                return latest
            tx.put("enclave", str(session_id), serialized, expected_revision=record.revision)
            return candidate

    def _recheck_authority(
        self,
        session_id: SessionId,
        expected_authority: ProcessState,
        latest: ProcessState,
    ) -> None:
        """Commit mutex 안에서 exact revision, status, root actor를 다시 확인합니다.

        Args:
            session_id: 다른 session으로 fallback하지 않을 exact identity입니다.
            expected_authority: Candidate 계산 전에 읽은 active/root snapshot입니다.

        Raises:
            EnclaveAuthorityError: Terminal 또는 다른 root authority가 먼저 commit되면
                발생합니다.
            AuthorityRevisionConflictError: Authority는 유효하지만 다른 session event가
                expected revision보다 먼저 commit되면 발생합니다.
        """
        if latest.session.status is not expected_authority.session.status:
            raise EnclaveAuthorityError(
                f"session authority status changed during enclave mutation: {session_id}"
            )
        if latest.session.root_actor_id != expected_authority.session.root_actor_id:
            raise EnclaveAuthorityError(
                f"session root actor changed during enclave mutation: {session_id}"
            )
        if latest.revision != expected_authority.revision:
            raise AuthorityRevisionConflictError(
                f"session revision changed during enclave mutation: "
                f"expected {expected_authority.revision}, actual {latest.revision}"
            )

    def _serialize(self, snapshot: EnclaveSnapshot) -> bytes:
        """Snapshot을 commit lock 밖에서 canonical JSON으로 준비합니다.

        Args:
            snapshot: Byte budget을 검증할 immutable candidate입니다.

        Returns:
            Atomic write에 바로 사용할 UTF-8 JSON bytes입니다.

        Raises:
            EnclaveBudgetExceeded: Candidate가 configured byte budget을 넘으면
                발생합니다.
        """
        serialized = (
            json.dumps(
                snapshot.to_payload(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        if len(serialized) > self._max_bytes:
            raise EnclaveBudgetExceeded(
                f"enclave snapshot requires {len(serialized)} bytes; budget is {self._max_bytes}"
            )
        return serialized

    def _record(self, session_id: SessionId):
        with self._database.transaction() as tx:
            record = tx.get("enclave", str(session_id))
            deleted = tx.was_deleted("enclave", str(session_id))
        path = self._locator.locate(session_id).enclave
        if record is None and not deleted and path.is_file():
            def validate(content):
                self._decode_snapshot(content, session_id)
                return 0
            record = self._database.import_legacy("enclave", str(session_id), path, validate)
        return record

    def exists(self, session_id: SessionId) -> bool:
        # Presence is distinct from the typed read/validation operation.
        with self._database.transaction() as tx:
            if tx.get("enclave", str(session_id)) is not None:
                return True
            if tx.was_deleted("enclave", str(session_id)):
                return False
        return self._locator.locate(session_id).enclave.is_file()

    def initialize(self, session_id: SessionId) -> None:
        if self.exists(session_id):
            return
        store = SessionStateStore(self._locator.locate(session_id).process_state)
        with self._database.transaction() as tx:
            state = store.read_transaction(tx, session_id)
            if state.session.status is not SessionStatus.ACTIVE:
                raise EnclaveAuthorityError("terminal session cannot initialize enclave")
            if tx.get("enclave", str(session_id)) is None:
                tx.put("enclave", str(session_id), self._serialize(EnclaveSnapshot(session_id, {})),
                       expected_revision=None)

    def delete_terminal(self, session_id: SessionId) -> None:
        self._record(session_id)
        store = SessionStateStore(self._locator.locate(session_id).process_state)
        with self._database.transaction() as tx:
            state = store.read_transaction(tx, session_id)
            if state.session.status is not SessionStatus.ENDED:
                raise EnclaveAuthorityError("only a terminal session can discard its enclave")
            record = tx.get("enclave", str(session_id))
            if record is not None:
                tx.delete("enclave", str(session_id), expected_revision=record.revision)
