"""Repository runtime wiring과 host-provided assurance를 분리해 inventory합니다."""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Self

from scripts.agent_harness.session_kernel import SessionRuntime


class RuntimeAssuranceError(ValueError):
    """Runtime config 또는 assurance profile을 안전하게 읽을 수 없을 때 발생합니다."""


class RuntimeAssurance(StrEnum):
    """Runtime별로 독립 증거가 필요한 lifecycle과 host control assurance입니다."""

    CHILD_START_SENSOR = "child-start-sensor"
    """Child actor 시작을 repository hook이 관측할 수 있습니다."""

    CHILD_STOP_SENSOR = "child-stop-sensor"
    """Child actor 종료를 repository hook이 관측할 수 있습니다."""

    SESSION_END_SENSOR = "session-end-sensor"
    """Root session terminal lifecycle을 repository hook이 관측할 수 있습니다."""

    MATERIAL_ACTION_FAILURE_SENSOR = "material-action-failure-sensor"
    """실패한 material action 결과를 repository hook이 관측할 수 있습니다."""

    PERMISSION_DENIED_SENSOR = "permission-denied-sensor"
    """Host가 거부한 mutation permission을 repository hook이 관측할 수 있습니다."""

    IMMEDIATE_PARENT_LINEAGE = "immediate-parent-lineage"
    """Host가 child actor의 immediate parent identity를 증명합니다."""

    HOST_MANAGED_MUTATION_AUTHORITY = "host-managed-mutation-authority"
    """Host-managed mutation이 repository authorization을 거쳤음을 증명합니다."""

    EVENT_DELIVERY_SEMANTICS = "event-delivery-semantics"
    """Host가 lifecycle event의 delivery와 retry 의미를 증명합니다."""


class AssuranceAvailability(StrEnum):
    """Evidence가 config declaration인지 host admission인지 구분합니다."""

    AVAILABLE = "available"
    """Host attestation이 admission에 사용할 수 있는 assurance를 제공합니다."""

    DECLARED = "declared"
    """Repository config에 sensor가 선언됐지만 host delivery는 증명되지 않았습니다."""

    UNAVAILABLE = "unavailable"
    """지정된 evidence source에서 현재 assurance 근거를 얻을 수 없습니다."""


class AssuranceEvidenceSource(StrEnum):
    """Assurance availability를 판단하는 독립 evidence plane입니다."""

    REPOSITORY_WIRING = "repository-wiring"
    """Version-controlled runtime hook configuration이 evidence source입니다."""

    HOST_ATTESTATION = "host-attestation"
    """Repository 밖 runtime host의 typed attestation이 필요합니다."""


class RuntimeConfigDigest(str):
    """Exact runtime config bytes에 결속된 SHA-256 content identity입니다."""

    _PATTERN = re.compile(r"sha256:[0-9a-f]{64}")

    def __new__(cls, value: str) -> Self:
        """Canonical SHA-256 reference를 immutable typed string으로 생성합니다.

        Args:
            value: `sha256:` prefix와 lowercase hex digest를 포함한 reference입니다.

        Returns:
            검증된 typed config digest입니다.

        Raises:
            RuntimeAssuranceError: 값이 canonical SHA-256 reference가 아니면 발생합니다.
        """
        if not isinstance(value, str) or cls._PATTERN.fullmatch(value) is None:
            raise RuntimeAssuranceError(
                "runtime config digest must be a canonical sha256 reference"
            )
        return str.__new__(cls, value)


@dataclass(frozen=True, slots=True)
class RuntimeAssuranceEvidence:
    """Assurance 하나의 availability와 그 판정 evidence plane입니다."""

    assurance: RuntimeAssurance
    """검증 대상 lifecycle sensor 또는 host control 의미입니다."""

    availability: AssuranceAvailability
    """현재 evidence가 DECLARED, AVAILABLE 또는 UNAVAILABLE인지 나타냅니다."""

    evidence_source: AssuranceEvidenceSource
    """Declaration 또는 admission 상태를 판정한 evidence plane입니다."""


@dataclass(frozen=True, slots=True)
class RuntimeAssuranceProfile:
    """Runtime config identity와 evidence-scoped assurance의 immutable projection입니다."""

    runtime: SessionRuntime
    """Profile이 관측한 coding-agent runtime입니다."""

    config_path: Path
    """Repository root 기준 runtime hook config 경로입니다."""

    config_digest: RuntimeConfigDigest
    """Inventory 시점의 exact config bytes SHA-256입니다."""

    wired_events: frozenset[str]
    """Runtime config의 hooks object에 선언된 event 이름입니다."""

    assurances: tuple[RuntimeAssuranceEvidence, ...]
    """모든 assurance의 evidence-scoped availability입니다."""

    def is_declared(self, assurance: RuntimeAssurance) -> bool:
        """Exact sensor가 repository config에 선언됐는지 반환합니다.

        Args:
            assurance: Consumer admission이 필요로 하는 exact assurance입니다.

        Returns:
            Repository-wiring evidence가 DECLARED이면 참입니다. 이는 host가 config를
            load했거나 event를 전달했다는 뜻이 아닙니다.

        Raises:
            RuntimeAssuranceError: Profile이 요청한 assurance를 누락하거나
                중복해서 canonical 판정을 낼 수 없으면 발생합니다.
        """
        matches = tuple(item for item in self.assurances if item.assurance is assurance)
        if len(matches) != 1:
            raise RuntimeAssuranceError(
                f"runtime assurance profile must contain one exact entry: {assurance.value}"
            )
        evidence = matches[0]
        return (
            evidence.evidence_source is AssuranceEvidenceSource.REPOSITORY_WIRING
            and evidence.availability is AssuranceAvailability.DECLARED
        )

    def is_admissible(self, assurance: RuntimeAssurance) -> bool:
        """Exact assurance가 host-attested admission에 사용 가능한지 반환합니다.

        Repository declaration은 이 query를 통과하지 못합니다. Consumer는 config presence를
        live delivery, block semantics 또는 actor authority로 승격할 수 없습니다.

        Args:
            assurance: Consumer admission이 요구하는 exact host assurance입니다.

        Returns:
            Host-attestation evidence가 AVAILABLE일 때만 참입니다.

        Raises:
            RuntimeAssuranceError: Profile이 요청한 assurance를 누락하거나 중복해
                canonical admission 판정을 만들 수 없으면 발생합니다.
        """
        matches = tuple(item for item in self.assurances if item.assurance is assurance)
        if len(matches) != 1:
            raise RuntimeAssuranceError(
                f"runtime assurance profile must contain one exact entry: {assurance.value}"
            )
        evidence = matches[0]
        return (
            evidence.evidence_source is AssuranceEvidenceSource.HOST_ATTESTATION
            and evidence.availability is AssuranceAvailability.AVAILABLE
        )


class RuntimeAssuranceInventory:
    """Version-controlled hook config만 읽어 runtime assurance profile을 만듭니다."""

    def __init__(self, repository_root: Path) -> None:
        """Inventory가 읽을 exact repository root를 고정합니다.

        Args:
            repository_root: Claude와 Codex hook config를 포함한 repository root입니다.
        """
        self._repository_root = repository_root.resolve()

    def profile(self, runtime: SessionRuntime) -> RuntimeAssuranceProfile:
        """Runtime config와 host-only 경계를 immutable assurance profile로 읽습니다.

        Args:
            runtime: Inventory할 supported coding-agent runtime입니다.

        Returns:
            Exact config digest, wired event inventory, scoped assurance를 담은 profile입니다.

        Raises:
            RuntimeAssuranceError: Runtime 또는 config shape가 지원되지 않으면 발생합니다.
        """
        config_path = self._config_path(runtime)
        config_bytes = self._read_config(config_path)
        wired_events = self._wired_events(config_bytes, config_path)
        return RuntimeAssuranceProfile(
            runtime=runtime,
            config_path=config_path,
            config_digest=RuntimeConfigDigest(f"sha256:{hashlib.sha256(config_bytes).hexdigest()}"),
            wired_events=wired_events,
            assurances=self._assurances(wired_events),
        )

    def _config_path(self, runtime: SessionRuntime) -> Path:
        if runtime is SessionRuntime.CLAUDE_CODE:
            return Path(".claude/settings.json")
        if runtime is SessionRuntime.CODEX:
            return Path(".codex/hooks.json")
        raise RuntimeAssuranceError(f"unsupported runtime assurance profile: {runtime}")

    def _read_config(self, config_path: Path) -> bytes:
        try:
            return (self._repository_root / config_path).read_bytes()
        except OSError as error:
            raise RuntimeAssuranceError(
                f"runtime assurance config is unavailable: {config_path}"
            ) from error

    def _wired_events(self, config_bytes: bytes, config_path: Path) -> frozenset[str]:
        try:
            payload = json.loads(config_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise RuntimeAssuranceError(
                f"runtime assurance config is invalid JSON: {config_path}"
            ) from error
        if not isinstance(payload, Mapping):
            raise RuntimeAssuranceError(
                f"runtime assurance config must be an object: {config_path}"
            )
        hooks = payload.get("hooks")
        if not isinstance(hooks, Mapping) or any(not isinstance(key, str) for key in hooks):
            raise RuntimeAssuranceError(
                f"runtime assurance config requires string-keyed hooks: {config_path}"
            )
        return frozenset(hooks)

    def _assurances(
        self,
        wired_events: frozenset[str],
    ) -> tuple[RuntimeAssuranceEvidence, ...]:
        repository_sensors = (
            (RuntimeAssurance.CHILD_START_SENSOR, "SubagentStart"),
            (RuntimeAssurance.CHILD_STOP_SENSOR, "SubagentStop"),
            (RuntimeAssurance.SESSION_END_SENSOR, "SessionEnd"),
            (
                RuntimeAssurance.MATERIAL_ACTION_FAILURE_SENSOR,
                "PostToolUseFailure",
            ),
            (RuntimeAssurance.PERMISSION_DENIED_SENSOR, "PermissionDenied"),
        )
        host_only = (
            RuntimeAssurance.IMMEDIATE_PARENT_LINEAGE,
            RuntimeAssurance.HOST_MANAGED_MUTATION_AUTHORITY,
            RuntimeAssurance.EVENT_DELIVERY_SEMANTICS,
        )
        repository_evidence = tuple(
            RuntimeAssuranceEvidence(
                assurance=assurance,
                availability=(
                    AssuranceAvailability.DECLARED
                    if event_name in wired_events
                    else AssuranceAvailability.UNAVAILABLE
                ),
                evidence_source=AssuranceEvidenceSource.REPOSITORY_WIRING,
            )
            for assurance, event_name in repository_sensors
        )
        host_evidence = tuple(
            RuntimeAssuranceEvidence(
                assurance=assurance,
                availability=AssuranceAvailability.UNAVAILABLE,
                evidence_source=AssuranceEvidenceSource.HOST_ATTESTATION,
            )
            for assurance in host_only
        )
        return repository_evidence + host_evidence
