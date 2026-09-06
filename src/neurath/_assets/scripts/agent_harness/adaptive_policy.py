"""Adaptive control을 우회할 수 없는 workflow applicability 경계를 고정합니다."""

from collections.abc import Mapping
from typing import Final

ADAPTIVE_CONTROL_OPERATIONAL_EXEMPT_WORKFLOW_KINDS: Final[frozenset[str]] = frozenset({
    "checkpoint",
    "commit",
    "create-pr",
    "create-ticket",
    "create-worktree",
    "monitor-pr",
    "finish-session",
    "update-project-status",
})
"""승인된 외부·작업공간 lifecycle만 투영하는 exact workflow kind입니다."""


def requires_adaptive_control(workflow_kind: str) -> bool:
    """Workflow kind가 adaptive completion gate 대상인지 반환합니다.

    Runtime은 contract metadata를 신뢰하지 않고 좁은 operational projection만
    면제합니다. 새롭거나 해석할 수 없는 kind는 semantic workflow로 간주해 fail closed합니다.

    Args:
        workflow_kind: SessionKernel workflow가 시작할 때 고정한 skill 또는 process kind입니다.

    Returns:
        Current workflow가 adaptive snapshot 없이 완료될 수 없으면 `True`입니다.
    """
    return workflow_kind not in ADAPTIVE_CONTROL_OPERATIONAL_EXEMPT_WORKFLOW_KINDS


def persisted_adaptive_control_requirement(
    payload: Mapping[str, object],
) -> bool | None:
    """Phase-run payload에 저장된 immutable applicability 결정을 읽습니다.

    Args:
        payload: Workflow aggregate의 current operational projection입니다.

    Returns:
        Explicit phase-run policy가 있으면 boolean, 없으면 `None`입니다.

    Raises:
        TypeError: Persisted marker가 boolean이 아니면 발생합니다.
    """
    phase_run = payload.get("phase_run")
    if not isinstance(phase_run, Mapping) or "adaptive_control_required" not in phase_run:
        return None
    required = phase_run["adaptive_control_required"]
    if not isinstance(required, bool):
        raise TypeError("phase adaptive_control_required must be a boolean")
    return required


def requires_adaptive_control_for_workflow(
    workflow_kind: str,
    payload: Mapping[str, object],
) -> bool:
    """Workflow 시작 때 저장된 policy를 우선해 completion requirement를 반환합니다.

    이미 시작된 run의 명시적 policy를 보존하므로 global 분류 변경이 active run에
    소급되어 terminal state를 영원히 막지 않습니다. Marker가 없는 workflow만 current
    fail-closed kind policy를 사용합니다.

    Args:
        workflow_kind: Persisted workflow implementation kind입니다.
        payload: Workflow aggregate의 current operational projection입니다.

    Returns:
        Current workflow가 adaptive completion authority를 요구하면 `True`입니다.

    Raises:
        TypeError: Persisted marker가 boolean이 아니면 발생합니다.
    """
    persisted = persisted_adaptive_control_requirement(payload)
    return requires_adaptive_control(workflow_kind) if persisted is None else persisted


def validate_adaptive_control_policy_transition(
    workflow_kind: str,
    current_payload: Mapping[str, object] | None,
    candidate_payload: Mapping[str, object],
) -> None:
    """Phase-run applicability를 workflow 시작 때 고정하고 이후 변경을 거부합니다.

    Args:
        workflow_kind: Workflow가 시작할 때 고정한 implementation kind입니다.
        current_payload: Start에서는 `None`, 이후에는 current workflow projection입니다.
        candidate_payload: Start, advance 또는 finalize가 제출한 다음 projection입니다.

    Raises:
        TypeError: Persisted marker가 boolean이 아니면 발생합니다.
        ValueError: Workflow 시작 뒤 persisted marker를 추가·삭제·변경하면 발생합니다.
    """
    candidate = persisted_adaptive_control_requirement(candidate_payload)
    if current_payload is None:
        return
    current = persisted_adaptive_control_requirement(current_payload)
    if current is None and candidate is False:
        return
    if candidate is not current:
        raise ValueError("persisted workflow adaptive policy is immutable")
