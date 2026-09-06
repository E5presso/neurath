"""현재 session의 직접 자식 근거와 이미 시작한 평가 경로를 조회합니다."""

import json
from collections.abc import Mapping

from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorKind,
    ActorLineageAssurance,
    ActorStatus,
    DelegationStatus,
    DelegationTopologyPolicy,
    ProcessState,
    WorkflowId,
)


class EvaluationAdmissionPolicy:
    """Config 선언을 host 권한으로 승격하지 않는 순간 가용성 판정입니다."""

    def inspect(
        self,
        state: ProcessState,
        owner: ActorId,
        workflow_id: WorkflowId | None = None,
    ) -> Mapping[str, object]:
        """현재 owner의 evaluator와 기존 평가 작업을 읽고 상태를 변경하지 않습니다.

        Args:
            state: Runtime-bound handle이 읽은 exact-session snapshot입니다.
            owner: 평가를 요청한 현재 actor입니다.
            workflow_id: 기존 run의 평가 경로를 보존할 때만 지정합니다.

        Returns:
            현재 snapshot revision에 결속한 available/in-progress/unavailable 진단입니다.
            Unavailable은 host의 영구 미지원이나 semantic 실패를 뜻하지 않습니다.
        """
        children = {
            actor.id: actor
            for actor in state.actors.values()
            if actor.parent_actor_id == owner
            and actor.kind is ActorKind.SUBAGENT
            and actor.lineage_assurance is ActorLineageAssurance.HOST_ATTESTED
        }
        active = tuple(
            sorted(
                str(actor.id) for actor in children.values() if actor.status is ActorStatus.ACTIVE
            )
        )
        existing: list[str] = []
        if workflow_id is not None:
            for delegation in state.delegations.values():
                if (
                    delegation.owner_actor_id != owner
                    or delegation.target_actor_id not in children
                    or delegation.topology_policy is not DelegationTopologyPolicy.DIRECT_CHILD
                    or delegation.status is DelegationStatus.CANCELLED
                ):
                    continue
                try:
                    assignment = json.loads(delegation.assignment)
                except ValueError, TypeError:
                    continue
                if (
                    isinstance(assignment, dict)
                    and assignment.get("workflow_id") == str(workflow_id)
                    and assignment.get("kind")
                    in {
                        "adaptive-goal-evaluation",
                        "evaluate-harness-independent-evaluator",
                    }
                ):
                    existing.append(str(delegation.id))
        return {
            "schema": "neurath.evaluation-admission.v1",
            "session_id": str(state.session.id),
            "actor_id": str(owner),
            "workflow_id": None if workflow_id is None else str(workflow_id),
            "state_revision": state.revision,
            "status": "in-progress" if existing else "available" if active else "unavailable",
            "available_actor_ids": list(active),
            "existing_delegation_ids": sorted(existing),
            "semantic_completion": False,
        }
