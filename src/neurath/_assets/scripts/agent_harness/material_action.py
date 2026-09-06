"""Material mutation의 intent, tool receipt, observable delta domain을 제공합니다."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path, PurePath
from typing import Self

MAX_ACTION_INVOCATIONS = 64
MAX_ACTION_OBSERVABLES = 64
MAX_ACTION_TARGETS = 64
_SHA256 = re.compile(r"[0-9a-f]{64}")


def canonical_material_target(target: Path) -> Path:
    """Parent topology를 canonicalize하되 final symlink identity는 따라가지 않습니다.

    Args:
        target: Absolute 또는 caller base에 결속된 local target입니다.

    Returns:
        Existing parent symlink는 해소하고 final path component는 lexical하게 보존한 path입니다.
    """
    absolute = target if target.is_absolute() else target.absolute()
    return absolute.parent.resolve(strict=False) / absolute.name


def material_observable_digest(target: Path) -> str | None:
    """Regular file 또는 symlink의 repository-visible identity를 digest로 읽습니다.

    Args:
        target: Canonical local material-action observable입니다.

    Returns:
        Path가 없으면 ``None``, 존재하면 mode와 content를 결속한 SHA-256입니다.

    Raises:
        OSError: 존재하는 target이 file/symlink가 아니거나 읽을 수 없으면 발생합니다.
    """
    try:
        metadata = target.lstat()
    except FileNotFoundError:
        return None
    digest = hashlib.sha256()
    if stat.S_ISLNK(metadata.st_mode):
        digest.update(b"neurath.material-observable.v1\0symlink\0")
        digest.update(f"{metadata.st_mode & 0o7777:04o}\0".encode("ascii"))
        digest.update(os.readlink(target).encode("utf-8"))
        return digest.hexdigest()
    if not stat.S_ISREG(metadata.st_mode):
        raise OSError("material observable is not a regular file or symbolic link")
    digest.update(b"neurath.material-observable.v1\0regular\0")
    digest.update(f"{metadata.st_mode & 0o7777:04o}\0".encode("ascii"))
    with target.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class MaterialActionKind(StrEnum):
    """Read-only 호출을 제외한 material action boundary입니다."""

    LOCAL_MUTATION = "local-mutation"
    """Canonical local target의 observable state를 변경하는 action입니다."""
    EXTERNAL_MUTATION = "external-mutation"
    """Typed external resource와 readback authority를 요구하는 action입니다."""
    SEMANTIC_DECISION = "semantic-decision"
    """Adaptive goal provenance에 결속된 specification 또는 decision 변경입니다."""


class MaterialActionStatus(StrEnum):
    """Actor별 latest material-action batch lifecycle입니다."""

    OPEN = "open"
    """Prepared intent가 tool receipt와 terminal resolution을 기다리는 상태입니다."""
    RESOLVED = "resolved"
    """Observed batch가 하나의 terminal resolution으로 닫힌 상태입니다."""


class MaterialActionResolution(StrEnum):
    """Observed batch를 닫는 명시적 판정입니다."""

    COMPLETED = "completed"
    """모든 receipt와 expected delta가 일치해 의도한 변경이 완료됐습니다."""
    ABORTED = "aborted"
    """관찰 결과와 무관하게 caller가 batch 진행을 중단했습니다."""
    BLOCKED = "blocked"
    """외부 제약이나 불충분한 증거 때문에 batch를 더 진행할 수 없습니다."""


class ToolInvocationStatus(StrEnum):
    """Batch 안 한 tool invocation의 PostTool receipt 상태입니다."""

    STARTED = "started"
    """PreTool request는 기록됐지만 matching PostTool receipt가 아직 없습니다."""
    OBSERVED = "observed"
    """Matching PostTool receipt와 authoritative readback이 결속됐습니다."""


class ToolReceiptOutcome(StrEnum):
    """Runtime PostTool boundary가 보고한 bounded execution outcome입니다."""

    SUCCEEDED = "succeeded"
    """Runtime tool 실행과 후속 validator가 성공한 결과입니다."""
    FAILED = "failed"
    """Runtime tool 또는 후속 validator가 실패한 결과입니다."""
    UNKNOWN = "unknown"
    """Runtime payload만으로 성공 여부를 확정할 수 없는 결과입니다."""


class ObservableDeltaKind(StrEnum):
    """Raw content 없이 비교할 observable state transition입니다."""

    CHANGED = "changed"
    """Baseline과 current digest가 모두 존재하며 서로 다릅니다."""
    UNCHANGED = "unchanged"
    """Baseline과 current digest가 동일하거나 둘 다 부재합니다."""
    CREATED = "created"
    """Baseline에는 없고 current readback에 새 digest가 존재합니다."""
    DELETED = "deleted"
    """Baseline digest는 존재하지만 current readback에는 대상이 없습니다."""


@dataclass(frozen=True, slots=True)
class MaterialActionDeltaAssessment:
    """Prepared expectation과 effective observed delta의 deterministic 비교 결과입니다."""

    missing_observable_ids: tuple[str, ...]
    """Latest receipt 어디에도 readback이 없는 prepared observable identity입니다."""
    mismatched_observable_ids: tuple[str, ...]
    """Derived delta kind 또는 expected digest가 expectation과 다른 identity입니다."""
    unsuccessful_invocation_ids: tuple[str, ...]
    """Receipt가 없거나 successful outcome이 아닌 invocation identity입니다."""
    effective_deltas: tuple[ObservableDelta, ...]
    """Prepared baseline과 latest observation에서 파생한 observable delta입니다."""

    @property
    def is_complete(self) -> bool:
        """모든 invocation과 observable이 expected contract를 만족하는지 판정합니다.

        Returns:
            누락, 불일치, 실패 invocation이 하나도 없으면 참입니다.
        """
        return not any((
            self.missing_observable_ids,
            self.mismatched_observable_ids,
            self.unsuccessful_invocation_ids,
        ))


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _integer(value: object, field: str, *, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    return value


def _digest(value: object, field: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} must be SHA-256")
    return value


def _enum_value[EnumType: StrEnum](
    enum_type: type[EnumType],
    value: object,
    field: str,
) -> EnumType:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} is invalid") from error


def _strings(values: object, field: str, *, maximum: int) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise TypeError(f"{field} must be an array")
    normalized = tuple(_text(value, field) for value in values)
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} must contain between 1 and {maximum} entries")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field} entries must be unique")
    return tuple(sorted(normalized))


def _object(payload: object, field: str) -> Mapping[str, object]:
    if not isinstance(payload, Mapping) or any(not isinstance(key, str) for key in payload):
        raise ValueError(f"{field} must be an object")
    return payload


def _array(payload: object, field: str) -> tuple[object, ...]:
    if not isinstance(payload, (tuple, list)):
        raise TypeError(f"{field} must be an array")
    return tuple(payload)


@dataclass(frozen=True, slots=True)
class AdaptiveActionBinding:
    """Optional adaptive workflow와 exact goal authority provenance입니다."""

    workflow_id: str
    """Semantic action authority를 소유하는 exact workflow identity입니다."""
    workflow_revision: int
    """Intent 준비 시점에 검증한 workflow projection revision입니다."""
    goal_fingerprint: str
    """Raw goal text 대신 보존하는 adaptive goal contract SHA-256입니다."""

    def __post_init__(self) -> None:
        """Workflow identity, revision과 goal fingerprint를 canonical shape로 고정합니다."""
        object.__setattr__(self, "workflow_id", _text(self.workflow_id, "workflow_id"))
        object.__setattr__(
            self,
            "workflow_revision",
            _integer(self.workflow_revision, "workflow_revision", minimum=0),
        )
        object.__setattr__(
            self,
            "goal_fingerprint",
            _digest(self.goal_fingerprint, "goal_fingerprint"),
        )

    def to_payload(self) -> dict[str, object]:
        """Raw goal 없이 exact workflow binding을 직렬화합니다.

        Returns:
            Workflow identity, revision과 goal fingerprint만 담은 JSON object입니다.
        """
        return {
            "workflow_id": self.workflow_id,
            "workflow_revision": self.workflow_revision,
            "goal_fingerprint": self.goal_fingerprint,
        }

    @classmethod
    def from_payload(cls, payload: object) -> Self:
        """Untrusted JSON object를 validated adaptive binding으로 복원합니다.

        Args:
            payload: Canonical adaptive binding 후보로 검증할 외부 object입니다.

        Returns:
            모든 provenance field를 검증하고 정규화한 binding입니다.
        """
        value = _object(payload, "adaptive_binding")
        return cls(
            workflow_id=_text(value.get("workflow_id"), "workflow_id"),
            workflow_revision=_integer(
                value.get("workflow_revision"),
                "workflow_revision",
                minimum=0,
            ),
            goal_fingerprint=str(_digest(value.get("goal_fingerprint"), "goal_fingerprint")),
        )


@dataclass(frozen=True, slots=True)
class ObservableExpectation:
    """Batch가 의도한 observable delta를 content digest로 고정합니다."""

    observable_id: str
    """Target 안에서 준비 시점부터 추적할 stable observable identity입니다."""
    baseline_digest: str | None
    """Mutation 직전 observable content의 SHA-256이며 부재 대상은 None입니다."""
    expected_delta: ObservableDeltaKind
    """Baseline과 PostTool readback 사이에 의도한 transition kind입니다."""
    expected_digest: str | None
    """완료 판정이 exact final content를 요구할 때 사용하는 SHA-256입니다."""

    def __post_init__(self) -> None:
        """Observable identity와 optional digest를 canonical expectation으로 고정합니다."""
        object.__setattr__(self, "observable_id", _text(self.observable_id, "observable_id"))
        object.__setattr__(
            self,
            "baseline_digest",
            _digest(self.baseline_digest, "baseline_digest", optional=True),
        )
        object.__setattr__(
            self,
            "expected_delta",
            _enum_value(ObservableDeltaKind, self.expected_delta, "expected_delta"),
        )
        object.__setattr__(
            self,
            "expected_digest",
            _digest(self.expected_digest, "expected_digest", optional=True),
        )

    def to_payload(self) -> dict[str, object]:
        """Expectation을 raw content 없는 JSON object로 반환합니다.

        Returns:
            Observable identity, baseline, expected kind와 final digest의 직렬화입니다.
        """
        return {
            "observable_id": self.observable_id,
            "baseline_digest": self.baseline_digest,
            "expected_delta": self.expected_delta.value,
            "expected_digest": self.expected_digest,
        }

    @classmethod
    def from_payload(cls, payload: object) -> Self:
        """Untrusted JSON object를 observable expectation으로 복원합니다.

        Args:
            payload: Identity와 digest contract를 읽을 외부 object입니다.

        Returns:
            Canonical identity와 typed delta kind를 가진 expectation입니다.
        """
        value = _object(payload, "expectation")
        digest = _digest(value.get("expected_digest"), "expected_digest", optional=True)
        return cls(
            observable_id=_text(value.get("observable_id"), "observable_id"),
            baseline_digest=_digest(
                value.get("baseline_digest"),
                "baseline_digest",
                optional=True,
            ),
            expected_delta=_enum_value(
                ObservableDeltaKind,
                value.get("expected_delta"),
                "expected_delta",
            ),
            expected_digest=digest,
        )


@dataclass(frozen=True, slots=True)
class ObservableObservation:
    """PostTool readback이 관찰한 current content digest 또는 부재입니다."""

    observable_id: str
    """Prepared expectation과 결속할 readback observable identity입니다."""
    current_digest: str | None
    """PostTool 시점 current content SHA-256이며 부재 대상은 None입니다."""

    def __post_init__(self) -> None:
        """Readback identity와 optional current digest를 canonical shape로 고정합니다."""
        object.__setattr__(self, "observable_id", _text(self.observable_id, "observable_id"))
        object.__setattr__(
            self,
            "current_digest",
            _digest(self.current_digest, "current_digest", optional=True),
        )

    def to_payload(self) -> dict[str, object]:
        """Current readback을 raw content 없는 JSON object로 반환합니다.

        Returns:
            Observable identity와 optional current digest만 담은 직렬화입니다.
        """
        return {
            "observable_id": self.observable_id,
            "current_digest": self.current_digest,
        }

    @classmethod
    def from_payload(cls, payload: object) -> Self:
        """Untrusted JSON object를 current observable readback으로 복원합니다.

        Args:
            payload: PostTool readback 후보로 검증할 외부 object입니다.

        Returns:
            Canonical observable identity와 current digest를 가진 observation입니다.
        """
        value = _object(payload, "observation")
        return cls(
            observable_id=_text(value.get("observable_id"), "observable_id"),
            current_digest=_digest(
                value.get("current_digest"),
                "current_digest",
                optional=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class ObservableDelta:
    """Prepared baseline과 current readback에서만 파생되는 effective delta입니다."""

    observable_id: str
    """Expectation과 observation이 공유하는 stable observable identity입니다."""
    baseline_digest: str | None
    """Prepared intent가 고정한 mutation 이전 content SHA-256입니다."""
    current_digest: str | None
    """PostTool authoritative readback에서 얻은 current content SHA-256입니다."""
    actual_delta: ObservableDeltaKind
    """Baseline/current 존재 여부와 digest equality에서 파생한 transition입니다."""

    @classmethod
    def derive(
        cls,
        expectation: ObservableExpectation,
        observation: ObservableObservation,
    ) -> Self:
        """Caller label 없이 baseline/current digest 조합에서 actual kind를 계산합니다.

        Args:
            expectation: Mutation 이전 baseline과 expected contract를 가진 intent입니다.
            observation: Matching PostTool 시점의 authoritative current readback입니다.

        Returns:
            두 digest의 존재와 equality에서만 파생한 immutable delta입니다.

        Raises:
            ValueError: Expectation과 observation의 observable identity가 다를 때 발생합니다.
        """
        if expectation.observable_id != observation.observable_id:
            raise ValueError("observable expectation and readback identities do not match")
        baseline = expectation.baseline_digest
        current = observation.current_digest
        if baseline is None and current is not None:
            actual = ObservableDeltaKind.CREATED
        elif baseline is not None and current is None:
            actual = ObservableDeltaKind.DELETED
        elif baseline == current:
            actual = ObservableDeltaKind.UNCHANGED
        else:
            actual = ObservableDeltaKind.CHANGED
        return cls(
            observable_id=expectation.observable_id,
            baseline_digest=baseline,
            current_digest=current,
            actual_delta=actual,
        )


@dataclass(frozen=True, slots=True)
class ToolReceipt:
    """Runtime PostTool delivery의 bounded, content-addressed receipt입니다."""

    receipt_id: str
    """Matching PostTool delivery retry를 식별하는 stable receipt identity입니다."""
    request_digest: str
    """PreTool에 기록한 normalized request와 일치해야 하는 SHA-256입니다."""
    outcome: ToolReceiptOutcome
    """Runtime execution과 후속 validator를 결합한 bounded outcome입니다."""
    output_digest: str
    """Raw output을 보존하지 않고 delivery equality를 비교하는 SHA-256입니다."""
    observations: tuple[ObservableObservation, ...]
    """Prepared expectation 범위에서 읽은 current observable digest 집합입니다."""
    duration_milliseconds: int | None = None
    """Runtime이 제공한 current tool duration이며 누락은 0이 아니라 None입니다."""

    def __post_init__(self) -> None:
        """Receipt identity, digest와 bounded unique observation을 정규화합니다.

        Raises:
            ValueError: Observation 수가 상한을 넘거나 identity가 중복될 때 발생합니다.
        """
        object.__setattr__(self, "receipt_id", _text(self.receipt_id, "receipt_id"))
        object.__setattr__(
            self,
            "request_digest",
            _digest(self.request_digest, "request_digest"),
        )
        object.__setattr__(
            self, "outcome", _enum_value(ToolReceiptOutcome, self.outcome, "outcome")
        )
        object.__setattr__(
            self,
            "output_digest",
            _digest(self.output_digest, "output_digest"),
        )
        if self.duration_milliseconds is not None:
            object.__setattr__(
                self,
                "duration_milliseconds",
                _integer(
                    self.duration_milliseconds,
                    "duration_milliseconds",
                    minimum=0,
                ),
            )
        observations = tuple(self.observations)
        if len(observations) > MAX_ACTION_OBSERVABLES:
            raise ValueError("observations exceed bounded capacity")
        identities = tuple(observation.observable_id for observation in observations)
        if len(identities) != len(set(identities)):
            raise ValueError("observation identities must be unique")
        object.__setattr__(
            self,
            "observations",
            tuple(sorted(observations, key=lambda item: item.observable_id)),
        )

    def to_payload(self) -> dict[str, object]:
        """Runtime output 원문 대신 digest와 structured readback만 반환합니다.

        Returns:
            Receipt identity, request/output digest, outcome과 observation 직렬화입니다.
        """
        return {
            "receipt_id": self.receipt_id,
            "request_digest": self.request_digest,
            "outcome": self.outcome.value,
            "output_digest": self.output_digest,
            "observations": [item.to_payload() for item in self.observations],
            "duration_milliseconds": self.duration_milliseconds,
        }

    @classmethod
    def from_payload(cls, payload: object) -> Self:
        """Untrusted JSON object를 PostTool receipt로 복원합니다.

        Args:
            payload: Runtime receipt 후보로 검증할 외부 object입니다.

        Returns:
            Digest와 bounded observation을 검증한 PostTool receipt입니다.
        """
        value = _object(payload, "receipt")
        return cls(
            receipt_id=_text(value.get("receipt_id"), "receipt_id"),
            request_digest=str(_digest(value.get("request_digest"), "request_digest")),
            outcome=_enum_value(ToolReceiptOutcome, value.get("outcome"), "outcome"),
            output_digest=str(_digest(value.get("output_digest"), "output_digest")),
            observations=tuple(
                ObservableObservation.from_payload(item)
                for item in _array(value.get("observations"), "observations")
            ),
            duration_milliseconds=(
                None
                if value.get("duration_milliseconds") is None
                else _integer(
                    value.get("duration_milliseconds"),
                    "duration_milliseconds",
                    minimum=0,
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """PreTool request digest와 matching PostTool receipt를 연결합니다."""

    invocation_id: str
    """PreTool과 PostTool payload가 공유하는 exact tool-use identity입니다."""
    tool_name: str
    """Normalized request를 실행한 runtime tool의 canonical name입니다."""
    request_digest: str
    """Raw input 대신 PreTool/PostTool equality를 증명하는 request SHA-256입니다."""
    targets: tuple[str, ...]
    """Prepared batch target 범위 안에서 이 invocation이 변경하려는 exact 대상입니다."""
    status: ToolInvocationStatus
    """Request start와 matching receipt observation 사이의 lifecycle 상태입니다."""
    receipt: ToolReceipt | None
    """Observed 상태에서만 존재하는 matching PostTool receipt입니다."""

    def __post_init__(self) -> None:
        """Request metadata와 status/receipt 조합을 하나의 canonical invocation으로 고정합니다.

        Raises:
            ValueError: Status와 receipt 존재 여부 또는 request digest가 일치하지 않을 때
                발생합니다.
        """
        object.__setattr__(self, "invocation_id", _text(self.invocation_id, "invocation_id"))
        object.__setattr__(self, "tool_name", _text(self.tool_name, "tool_name"))
        object.__setattr__(
            self,
            "request_digest",
            _digest(self.request_digest, "request_digest"),
        )
        targets = _strings(self.targets, "targets", maximum=MAX_ACTION_TARGETS)
        object.__setattr__(self, "targets", targets)
        object.__setattr__(
            self,
            "status",
            _enum_value(ToolInvocationStatus, self.status, "status"),
        )
        if (self.status is ToolInvocationStatus.STARTED) != (self.receipt is None):
            raise ValueError("started invocation has no receipt and observed invocation has one")
        if self.receipt is not None and self.receipt.request_digest != self.request_digest:
            raise ValueError("PostTool receipt request digest does not match PreTool request")

    @classmethod
    def started(
        cls,
        *,
        invocation_id: str,
        tool_name: str,
        request_digest: str,
        targets: tuple[str, ...],
    ) -> Self:
        """PreTool boundary에서 receipt를 기다리는 invocation을 생성합니다.

        Args:
            invocation_id: Runtime이 PostTool에도 반복 제공할 exact tool-use identity입니다.
            tool_name: Normalized request를 실행할 canonical runtime tool name입니다.
            request_digest: Raw input 대신 request equality를 고정하는 SHA-256입니다.
            targets: Prepared batch 범위 안에서 tool이 변경하려는 exact target입니다.

        Returns:
            STARTED 상태이며 receipt가 없는 새 invocation입니다.
        """
        return cls(
            invocation_id=invocation_id,
            tool_name=tool_name,
            request_digest=request_digest,
            targets=targets,
            status=ToolInvocationStatus.STARTED,
            receipt=None,
        )

    def observe(self, receipt: ToolReceipt) -> Self:
        """Exact request와 matching PostTool receipt를 결속합니다.

        Args:
            receipt: PreTool request digest와 일치하는 PostTool observation입니다.

        Returns:
            동일 receipt retry이면 현재 객체, 최초 observation이면 OBSERVED 복사본입니다.

        Raises:
            ValueError: 이미 다른 receipt가 결속된 invocation을 덮어쓰려 할 때 발생합니다.
        """
        if self.receipt is not None:
            if self.receipt == receipt:
                return self
            raise ValueError("invocation already has a different PostTool receipt")
        return replace(self, status=ToolInvocationStatus.OBSERVED, receipt=receipt)

    def to_payload(self) -> dict[str, object]:
        """Invocation을 request/output 원문 없는 JSON object로 반환합니다.

        Returns:
            Tool identity, request digest, target, status와 optional receipt 직렬화입니다.
        """
        return {
            "invocation_id": self.invocation_id,
            "tool_name": self.tool_name,
            "request_digest": self.request_digest,
            "targets": list(self.targets),
            "status": self.status.value,
            "receipt": None if self.receipt is None else self.receipt.to_payload(),
        }

    @classmethod
    def from_payload(cls, payload: object) -> Self:
        """Untrusted JSON object를 tool invocation으로 복원합니다.

        Args:
            payload: Persisted invocation 후보로 검증할 외부 object입니다.

        Returns:
            Request metadata와 optional receipt를 검증한 invocation입니다.
        """
        value = _object(payload, "invocation")
        receipt_payload = value.get("receipt")
        return cls(
            invocation_id=_text(value.get("invocation_id"), "invocation_id"),
            tool_name=_text(value.get("tool_name"), "tool_name"),
            request_digest=str(_digest(value.get("request_digest"), "request_digest")),
            targets=_strings(value.get("targets"), "targets", maximum=MAX_ACTION_TARGETS),
            status=_enum_value(ToolInvocationStatus, value.get("status"), "status"),
            receipt=(
                None if receipt_payload is None else ToolReceipt.from_payload(receipt_payload)
            ),
        )


@dataclass(frozen=True, slots=True)
class MaterialActionBatch:
    """한 actor foreground turn에 결속된 latest bounded mutation batch입니다."""

    batch_id: str
    """Actor별 latest batch를 retry와 CAS에서 식별하는 stable identity입니다."""
    sequence: int
    """같은 actor가 resolved batch 뒤에만 증가시키는 monotonic sequence입니다."""
    session_id: str
    """Batch가 절대 벗어날 수 없는 exact runtime session identity입니다."""
    actor_id: str
    """Intent 준비와 모든 invocation mutation authority를 소유하는 actor입니다."""
    turn_generation: int
    """Intent가 결속된 actor foreground turn의 generation입니다."""
    turn_revision: int
    """Prepare 시점 foreground turn을 ABA로부터 보호하는 revision입니다."""
    kind: MaterialActionKind
    """Local, external 또는 semantic boundary를 선택하는 action 종류입니다."""
    targets: tuple[str, ...]
    """Batch 안 invocation이 절대 확장할 수 없는 normalized target 상한입니다."""
    expectations: tuple[ObservableExpectation, ...]
    """Completion을 판정할 baseline, expected transition과 optional final digest입니다."""
    adaptive_binding: AdaptiveActionBinding | None
    """Semantic decision을 exact adaptive workflow/goal에 결속하는 optional provenance입니다."""
    revision: int
    """Start, observe, resolve mutation마다 증가하는 batch-local CAS counter입니다."""
    status: MaterialActionStatus
    """Batch가 tool receipt를 기다리는지 terminal 판정으로 닫혔는지 나타냅니다."""
    invocations: tuple[ToolInvocation, ...]
    """한 번에 하나만 in-flight일 수 있는 bounded sequential tool ledger입니다."""
    resolution: MaterialActionResolution | None
    """RESOLVED 상태에서만 존재하는 explicit terminal 판정입니다."""

    def __post_init__(self) -> None:
        """Actor-turn intent와 bounded invocation lifecycle 불변식을 정규화합니다.

        Raises:
            ValueError: Semantic authority, target/expectation 범위, invocation ordering 또는
                status/resolution 조합이 material-action contract를 위반할 때 발생합니다.
        """
        object.__setattr__(self, "batch_id", _text(self.batch_id, "batch_id"))
        object.__setattr__(self, "sequence", _integer(self.sequence, "sequence", minimum=1))
        object.__setattr__(self, "session_id", _text(self.session_id, "session_id"))
        object.__setattr__(self, "actor_id", _text(self.actor_id, "actor_id"))
        object.__setattr__(
            self,
            "turn_generation",
            _integer(self.turn_generation, "turn_generation", minimum=1),
        )
        object.__setattr__(
            self,
            "turn_revision",
            _integer(self.turn_revision, "turn_revision", minimum=0),
        )
        object.__setattr__(self, "kind", _enum_value(MaterialActionKind, self.kind, "kind"))
        if self.kind is MaterialActionKind.SEMANTIC_DECISION and self.adaptive_binding is None:
            raise ValueError("semantic material action requires adaptive authority")
        targets = _strings(self.targets, "targets", maximum=MAX_ACTION_TARGETS)
        object.__setattr__(self, "targets", targets)
        expectations = tuple(self.expectations)
        if not expectations or len(expectations) > MAX_ACTION_OBSERVABLES:
            raise ValueError("expectations must be non-empty and bounded")
        expectation_ids = tuple(item.observable_id for item in expectations)
        if len(expectation_ids) != len(set(expectation_ids)):
            raise ValueError("expectation observable identities must be unique")
        if self.kind is MaterialActionKind.LOCAL_MUTATION:
            if any(
                not PurePath(target).is_absolute() or str(PurePath(target)) != target
                for target in targets
            ):
                raise ValueError("local material-action targets must be canonical absolute paths")
            if not set(expectation_ids).issubset(targets):
                raise ValueError("local observable identities must be prepared target paths")
        object.__setattr__(
            self,
            "expectations",
            tuple(sorted(expectations, key=lambda item: item.observable_id)),
        )
        object.__setattr__(self, "revision", _integer(self.revision, "revision", minimum=0))
        object.__setattr__(
            self,
            "status",
            _enum_value(MaterialActionStatus, self.status, "status"),
        )
        invocations = tuple(self.invocations)
        if len(invocations) > MAX_ACTION_INVOCATIONS:
            raise ValueError("invocations exceed bounded capacity")
        invocation_ids = tuple(item.invocation_id for item in invocations)
        if len(invocation_ids) != len(set(invocation_ids)):
            raise ValueError("invocation identities must be unique")
        in_flight = tuple(
            item for item in invocations if item.status is ToolInvocationStatus.STARTED
        )
        if len(in_flight) > 1 or (in_flight and in_flight[0] is not invocations[-1]):
            raise ValueError("only the latest invocation may be in flight")
        object.__setattr__(self, "invocations", invocations)
        if self.status is MaterialActionStatus.OPEN and self.resolution is not None:
            raise ValueError("open batch cannot have a resolution")
        if self.status is MaterialActionStatus.RESOLVED and self.resolution is None:
            raise ValueError("resolved batch requires a resolution")
        if self.status is MaterialActionStatus.RESOLVED and in_flight:
            raise ValueError("resolved batch cannot have an in-flight invocation")

    @classmethod
    def prepare(
        cls,
        *,
        batch_id: str,
        sequence: int,
        session_id: str,
        actor_id: str,
        turn_generation: int,
        turn_revision: int,
        kind: MaterialActionKind,
        targets: tuple[str, ...],
        expectations: tuple[ObservableExpectation, ...],
        adaptive_binding: AdaptiveActionBinding | None,
    ) -> Self:
        """Current foreground turn에 아직 invocation이 없는 open intent를 준비합니다.

        Args:
            batch_id: Retry와 later tool event가 공유할 stable batch identity입니다.
            sequence: Actor의 직전 resolved batch 다음 monotonic 순번입니다.
            session_id: Intent를 소유하는 exact runtime session identity입니다.
            actor_id: Prepare와 후속 mutation authority를 소유하는 actor identity입니다.
            turn_generation: Intent를 결속할 current foreground turn generation입니다.
            turn_revision: Prepare 시점 current foreground turn CAS revision입니다.
            kind: Target와 adaptive authority 규칙을 선택하는 material action 종류입니다.
            targets: Batch 안 tool call이 변경할 수 있는 normalized exact target입니다.
            expectations: Completion을 판정할 observable baseline과 expected delta입니다.
            adaptive_binding: Semantic action을 exact adaptive goal에 결속하는 provenance입니다.

        Returns:
            Revision 0, OPEN 상태이고 invocation이 없는 immutable batch입니다.
        """
        return cls(
            batch_id=batch_id,
            sequence=sequence,
            session_id=session_id,
            actor_id=actor_id,
            turn_generation=turn_generation,
            turn_revision=turn_revision,
            kind=kind,
            targets=targets,
            expectations=expectations,
            adaptive_binding=adaptive_binding,
            revision=0,
            status=MaterialActionStatus.OPEN,
            invocations=(),
            resolution=None,
        )

    @property
    def in_flight(self) -> ToolInvocation | None:
        """현재 PostTool receipt를 기다리는 invocation을 선택합니다.

        Returns:
            Latest invocation이 STARTED이면 그 객체이고, 아니면 None입니다.
        """
        if not self.invocations:
            return None
        latest = self.invocations[-1]
        return latest if latest.status is ToolInvocationStatus.STARTED else None

    @property
    def delta_assessment(self) -> MaterialActionDeltaAssessment:
        """Latest observed delta를 prepared expectation과 비교해 derived 판정을 만듭니다.

        Returns:
            Missing/mismatched observable, unsuccessful invocation과 effective delta를 분리한
            deterministic assessment입니다.
        """
        unsuccessful: list[str] = []
        latest_observations: dict[str, ObservableObservation] = {}
        for invocation in self.invocations:
            receipt = invocation.receipt
            if receipt is None or receipt.outcome is not ToolReceiptOutcome.SUCCEEDED:
                unsuccessful.append(invocation.invocation_id)
            if receipt is not None:
                latest_observations.update({
                    item.observable_id: item for item in receipt.observations
                })

        missing: list[str] = []
        mismatched: list[str] = []
        effective: list[ObservableDelta] = []
        for expectation in self.expectations:
            observation = latest_observations.get(expectation.observable_id)
            if observation is None:
                missing.append(expectation.observable_id)
                continue
            delta = ObservableDelta.derive(expectation, observation)
            effective.append(delta)
            if delta.actual_delta is not expectation.expected_delta or (
                expectation.expected_digest is not None
                and delta.current_digest != expectation.expected_digest
            ):
                mismatched.append(expectation.observable_id)
        return MaterialActionDeltaAssessment(
            missing_observable_ids=tuple(sorted(missing)),
            mismatched_observable_ids=tuple(sorted(mismatched)),
            unsuccessful_invocation_ids=tuple(unsuccessful),
            effective_deltas=tuple(effective),
        )

    def same_intent(self, other: MaterialActionBatch) -> bool:
        """Lifecycle 진행과 무관하게 두 batch가 같은 prepared intent인지 비교합니다.

        Args:
            other: Identity와 prepared boundary를 비교할 다른 batch입니다.

        Returns:
            Batch/actor/turn/target/expectation/adaptive provenance가 모두 같으면 참입니다.
        """
        return (
            self.batch_id,
            self.sequence,
            self.session_id,
            self.actor_id,
            self.turn_generation,
            self.turn_revision,
            self.kind,
            self.targets,
            self.expectations,
            self.adaptive_binding,
        ) == (
            other.batch_id,
            other.sequence,
            other.session_id,
            other.actor_id,
            other.turn_generation,
            other.turn_revision,
            other.kind,
            other.targets,
            other.expectations,
            other.adaptive_binding,
        )

    def start_tool(
        self,
        *,
        invocation_id: str,
        tool_name: str,
        request_digest: str,
        targets: tuple[str, ...],
    ) -> Self:
        """Open batch에서 normalized request 하나를 in-flight로 만듭니다.

        Args:
            invocation_id: PreTool/PostTool retry를 연결할 exact tool-use identity입니다.
            tool_name: Normalized request를 실행할 canonical runtime tool name입니다.
            request_digest: Raw tool input 대신 request equality를 고정하는 SHA-256입니다.
            targets: Prepared batch target의 부분집합인 exact mutation 대상입니다.

        Returns:
            Exact duplicate이면 현재 batch, 새 request이면 revision이 증가한 복사본입니다.

        Raises:
            ValueError: Identity 충돌, resolved/in-flight 상태, target 범위 또는 invocation
                상한을 위반할 때 발생합니다.
        """
        candidate = ToolInvocation.started(
            invocation_id=invocation_id,
            tool_name=tool_name,
            request_digest=request_digest,
            targets=targets,
        )
        existing = self._invocation(candidate.invocation_id)
        if existing is not None:
            if (
                existing.invocation_id,
                existing.tool_name,
                existing.request_digest,
                existing.targets,
            ) == (
                candidate.invocation_id,
                candidate.tool_name,
                candidate.request_digest,
                candidate.targets,
            ):
                return self
            raise ValueError("invocation identity already has a different request")
        if self.status is not MaterialActionStatus.OPEN:
            raise ValueError("resolved batch rejects tool invocation")
        if self.in_flight is not None:
            raise ValueError("batch already has an in-flight invocation")
        if not set(candidate.targets).issubset(self.targets):
            raise ValueError("tool targets exceed the prepared material-action boundary")
        if len(self.invocations) >= MAX_ACTION_INVOCATIONS:
            raise ValueError("invocations exceed bounded capacity")
        return replace(
            self,
            revision=self.revision + 1,
            invocations=(*self.invocations, candidate),
        )

    def observe_tool(self, invocation_id: str, receipt: ToolReceipt) -> Self:
        """Started invocation에 exact runtime PostTool receipt를 결속합니다.

        Args:
            invocation_id: Current in-flight request를 식별하는 tool-use identity입니다.
            receipt: Matching request digest와 prepared-scope observation을 가진 receipt입니다.

        Returns:
            Exact duplicate이면 현재 batch, 최초 receipt이면 revision이 증가한 복사본입니다.

        Raises:
            ValueError: Invocation, request digest, lifecycle 또는 observable scope가 current
                prepared batch와 일치하지 않을 때 발생합니다.
        """
        normalized_id = _text(invocation_id, "invocation_id")
        existing = self._invocation(normalized_id)
        if existing is None:
            raise ValueError("PostTool receipt has no matching invocation")
        if existing.receipt is not None:
            if existing.receipt == receipt:
                return self
            raise ValueError("invocation already has a different PostTool receipt")
        if self.status is not MaterialActionStatus.OPEN or self.in_flight is not existing:
            raise ValueError("only the in-flight invocation accepts a PostTool receipt")
        if receipt.request_digest != existing.request_digest:
            raise ValueError("PostTool receipt request digest does not match PreTool request")
        expectation_ids = {item.observable_id for item in self.expectations}
        if not {observation.observable_id for observation in receipt.observations}.issubset(
            expectation_ids
        ):
            raise ValueError("PostTool observation is outside prepared expectations")
        updated = existing.observe(receipt)
        invocations = tuple(
            updated if item.invocation_id == normalized_id else item for item in self.invocations
        )
        return replace(self, revision=self.revision + 1, invocations=invocations)

    def resolve(self, resolution: MaterialActionResolution) -> Self:
        """모든 started invocation이 관찰된 batch를 terminal 판정으로 닫습니다.

        Args:
            resolution: Completed, aborted 또는 blocked 중 explicit terminal 판정입니다.

        Returns:
            Exact terminal retry이면 현재 batch, 최초 판정이면 RESOLVED 복사본입니다.

        Raises:
            ValueError: 다른 resolution 재시도, in-flight batch 또는 invocation/evidence가
                부족한 completed 판정을 요청할 때 발생합니다.
        """
        normalized = _enum_value(MaterialActionResolution, resolution, "resolution")
        if self.status is MaterialActionStatus.RESOLVED:
            if self.resolution is normalized:
                return self
            raise ValueError("batch already has a different resolution")
        if self.in_flight is not None:
            raise ValueError("batch cannot resolve before its PostTool receipt")
        if normalized is MaterialActionResolution.COMPLETED:
            if not self.invocations:
                raise ValueError("completed batch requires one observed invocation")
            if not self.delta_assessment.is_complete:
                raise ValueError("completed batch requires successful receipts and matching deltas")
        return replace(
            self,
            revision=self.revision + 1,
            status=MaterialActionStatus.RESOLVED,
            resolution=normalized,
        )

    def to_payload(self) -> dict[str, object]:
        """Batch를 raw command/output/chain-of-thought 없는 JSON object로 반환합니다.

        Returns:
            Prepared intent, bounded invocation receipt와 terminal resolution의 직렬화입니다.
        """
        return {
            "batch_id": self.batch_id,
            "sequence": self.sequence,
            "session_id": self.session_id,
            "actor_id": self.actor_id,
            "turn_generation": self.turn_generation,
            "turn_revision": self.turn_revision,
            "kind": self.kind.value,
            "targets": list(self.targets),
            "expectations": [item.to_payload() for item in self.expectations],
            "adaptive_binding": (
                None if self.adaptive_binding is None else self.adaptive_binding.to_payload()
            ),
            "revision": self.revision,
            "status": self.status.value,
            "invocations": [item.to_payload() for item in self.invocations],
            "resolution": None if self.resolution is None else self.resolution.value,
        }

    @classmethod
    def from_payload(cls, payload: object) -> Self:
        """Untrusted process-state object를 validated material-action batch로 복원합니다.

        Args:
            payload: Canonical process-state에서 읽은 batch 후보 object입니다.

        Returns:
            Actor-turn, target, receipt와 lifecycle 불변식을 검증한 batch입니다.
        """
        value = _object(payload, "material_action")
        binding_payload = value.get("adaptive_binding")
        resolution_value = value.get("resolution")
        return cls(
            batch_id=_text(value.get("batch_id"), "batch_id"),
            sequence=_integer(value.get("sequence"), "sequence", minimum=1),
            session_id=_text(value.get("session_id"), "session_id"),
            actor_id=_text(value.get("actor_id"), "actor_id"),
            turn_generation=_integer(
                value.get("turn_generation"),
                "turn_generation",
                minimum=1,
            ),
            turn_revision=_integer(
                value.get("turn_revision"),
                "turn_revision",
                minimum=0,
            ),
            kind=_enum_value(MaterialActionKind, value.get("kind"), "kind"),
            targets=_strings(value.get("targets"), "targets", maximum=MAX_ACTION_TARGETS),
            expectations=tuple(
                ObservableExpectation.from_payload(item)
                for item in _array(value.get("expectations"), "expectations")
            ),
            adaptive_binding=(
                None
                if binding_payload is None
                else AdaptiveActionBinding.from_payload(binding_payload)
            ),
            revision=_integer(value.get("revision"), "revision", minimum=0),
            status=_enum_value(MaterialActionStatus, value.get("status"), "status"),
            invocations=tuple(
                ToolInvocation.from_payload(item)
                for item in _array(value.get("invocations"), "invocations")
            ),
            resolution=(
                None
                if resolution_value is None
                else _enum_value(MaterialActionResolution, resolution_value, "resolution")
            ),
        )

    def _invocation(self, invocation_id: str) -> ToolInvocation | None:
        return next(
            (item for item in self.invocations if item.invocation_id == invocation_id),
            None,
        )
