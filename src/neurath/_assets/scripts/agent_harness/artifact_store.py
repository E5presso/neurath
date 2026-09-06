"""Delegation detail을 exact session에 content-addressed immutable artifact로 보존합니다."""

import fcntl
import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TextIO

from scripts.agent_harness.session_kernel import ActorStatus, SessionStatus
from scripts.agent_harness.state_handle import StateHandle


class ArtifactStoreError(RuntimeError):
    """Session artifact persistence contract를 만족할 수 없음을 나타냅니다."""


class ArtifactAuthorityError(ArtifactStoreError):
    """Terminal session 또는 terminal actor의 artifact mutation을 거부합니다."""


class ArtifactInvalid(ArtifactStoreError):
    """Artifact payload, reference 또는 persisted content가 잘못되었음을 나타냅니다."""


class ArtifactNotFound(ArtifactStoreError):
    """Exact session directory에 requested content digest가 없을 때 발생합니다."""


class ArtifactReceipt:
    """Content-addressed artifact identity와 bounded metadata를 보존합니다."""

    __slots__ = ("media_type", "reference", "size_bytes")

    def __init__(self, *, reference: str, media_type: str, size_bytes: int) -> None:
        """Artifact readback에 필요한 immutable metadata를 생성합니다.

        Args:
            reference: `sha256:<hex>` 형태의 content identity입니다.
            media_type: Persisted serialization의 media type입니다.
            size_bytes: Digest를 계산한 canonical content byte 수입니다.
        """
        object.__setattr__(self, "reference", reference)
        object.__setattr__(self, "media_type", media_type)
        object.__setattr__(self, "size_bytes", size_bytes)

    reference: str
    """Session-local artifact를 읽을 content digest reference입니다."""

    media_type: str
    """Artifact serialization의 stable media type입니다."""

    size_bytes: int
    """Canonical serialized content의 byte 크기입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성된 artifact receipt 변경을 거부합니다.

        Args:
            name: 변경하려는 attribute 이름입니다.
            value: 새로 대입하려는 값입니다.

        Raises:
            AttributeError: Receipt는 immutable입니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class SessionArtifactStore:
    """StateHandle에 바인딩된 session artifact만 scan 없이 읽고 씁니다."""

    _REFERENCE_PATTERN = re.compile(r"sha256:([0-9a-f]{64})\Z")

    def __init__(self, handle: StateHandle) -> None:
        """Runtime-bound state authority 하나에 artifact namespace를 고정합니다.

        Args:
            handle: Exact session과 current actor를 검증하는 state facade입니다.
        """
        self._handle = handle

    def put_json(self, payload: Mapping[str, object]) -> ArtifactReceipt:
        """JSON object를 canonicalize해 immutable content-addressed artifact로 저장합니다.

        같은 content의 concurrent 또는 repeated write는 같은 artifact 한 개로
        idempotently 수렴합니다. Caller가 artifact path를 선택할 수 없습니다.

        Args:
            payload: Detailed delegation result 등 bounded JSON object입니다.

        Returns:
            Owner actor가 readback할 digest reference와 content metadata입니다.

        Raises:
            ArtifactAuthorityError: Current actor가 terminal이면 발생합니다.
            ArtifactInvalid: Payload가 JSON object로 canonicalize되지 않으면 발생합니다.
        """
        self._require_active_authority()
        content = self._encode(payload)
        digest = hashlib.sha256(content).hexdigest()
        reference = f"sha256:{digest}"
        artifact_path = self._artifact_path(digest)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        with self._open_lock(artifact_path) as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                if artifact_path.exists():
                    self._verify_content(artifact_path, content, reference)
                else:
                    self._commit(artifact_path, content)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return ArtifactReceipt(
            reference=reference,
            media_type="application/json",
            size_bytes=len(content),
        )

    def read_json(self, reference: str) -> dict[str, object]:
        """Current StateHandle의 exact session에서 digest-verified JSON object를 읽습니다.

        Args:
            reference: `put_json`이 반환한 `sha256:<hex>` reference입니다.

        Returns:
            Digest와 JSON object shape를 검증한 detached mapping입니다.

        Raises:
            ArtifactInvalid: Reference, digest 또는 JSON shape가 잘못되면 발생합니다.
            ArtifactNotFound: Exact session에 artifact가 없으면 발생합니다.
        """
        self._handle.inspect()
        digest = self._parse_reference(reference)
        artifact_path = self._artifact_path(digest)
        if not artifact_path.is_file():
            raise ArtifactNotFound(
                f"artifact {reference} is missing from session {self._handle.session_id}"
            )
        try:
            content = artifact_path.read_bytes()
        except OSError as error:
            raise ArtifactInvalid(f"cannot read artifact {reference}") from error
        actual_reference = f"sha256:{hashlib.sha256(content).hexdigest()}"
        if actual_reference != reference:
            raise ArtifactInvalid(f"artifact digest mismatch: {reference}")
        try:
            decoded: object = json.loads(content)
        except json.JSONDecodeError as error:
            raise ArtifactInvalid(f"artifact is not valid JSON: {reference}") from error
        if not isinstance(decoded, dict) or any(not isinstance(key, str) for key in decoded):
            raise ArtifactInvalid(f"artifact root must be a string-keyed object: {reference}")
        return {str(key): value for key, value in decoded.items()}

    def _require_active_authority(self) -> None:
        state = self._handle.inspect()
        actor = state.actors.get(self._handle.actor_id)
        if state.session.status is not SessionStatus.ACTIVE or actor is None:
            raise ArtifactAuthorityError("terminal or missing actor cannot write artifacts")
        if actor.status not in {ActorStatus.ACTIVE, ActorStatus.IDLE}:
            raise ArtifactAuthorityError("terminal actor cannot write artifacts")

    def _encode(self, payload: Mapping[str, object]) -> bytes:
        try:
            content = json.dumps(
                dict(payload),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise ArtifactInvalid("artifact payload must be JSON serializable") from error
        try:
            decoded: object = json.loads(content)
        except json.JSONDecodeError as error:
            raise ArtifactInvalid("artifact payload canonicalization failed") from error
        if not isinstance(decoded, dict):
            raise ArtifactInvalid("artifact payload must be a JSON object")
        return content

    def _parse_reference(self, reference: str) -> str:
        match = self._REFERENCE_PATTERN.fullmatch(reference)
        if match is None:
            raise ArtifactInvalid("artifact reference must be sha256:<64 lowercase hex>")
        return match.group(1)

    def _artifact_path(self, digest: str) -> Path:
        return self._handle._session_artifact_directory() / "sha256" / f"{digest}.json"

    def _open_lock(self, artifact_path: Path) -> TextIO:
        return artifact_path.with_name(f".{artifact_path.name}.lock").open(
            "a+",
            encoding="utf-8",
        )

    def _verify_content(self, path: Path, expected: bytes, reference: str) -> None:
        try:
            current = path.read_bytes()
        except OSError as error:
            raise ArtifactInvalid(f"cannot verify artifact {reference}") from error
        if current != expected:
            raise ArtifactInvalid(f"content-addressed artifact collision: {reference}")

    def _commit(self, artifact_path: Path, content: bytes) -> None:
        temporary_name: str | None = None
        try:
            with NamedTemporaryFile(
                "wb",
                dir=artifact_path.parent,
                prefix=f".{artifact_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, artifact_path)
            directory_descriptor = os.open(artifact_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)
