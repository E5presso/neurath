"""Immutable cleanup intent and pure workflow transitions for crash recovery."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar


from scripts.agent_harness.session_kernel import (
    ActorId,
    SessionId,
    WorkflowId,
    WorktreeId,
)
from scripts.agent_harness.worktree_registry import (
    CanonicalWorktreeIdentity,
    WorktreeClaim,
    WorktreeClaimStatus,
)


class MergeCleanupError(RuntimeError):
    """Cleanup identity, Git read-back 또는 fenced release가 실패했을 때의 오류입니다."""


class MergeCleanupPlanConflict(MergeCleanupError):
    """Persisted cleanup intent와 current Git/lease prerequisite가 달라졌습니다."""


class CleanupResumePlan:
    """한 workflow의 exact cleanup target을 reservation 전에 보존합니다."""

    SCHEMA = "neurath.merged-worktree-cleanup-plan.v2"
    _FIELDS: ClassVar[set[str]] = {
        "schema",
        "worktree_id",
        "worktree",
        "repository_control_root",
        "branch",
        "session_id",
        "actor_id",
        "workflow_id",
        "workflow_revision",
        "lease_epoch",
        "fencing_token",
        "transition_id",
        "base_branch",
        "remote_ref",
        "ticket_head_oid",
        "planned_reservation_fencing_token",
    }

    __slots__ = (
        "_actor_id",
        "_base_branch",
        "_branch",
        "_claim",
        "_identity",
        "_planned_reservation_fencing_token",
        "_remote_ref",
        "_session_id",
        "_ticket_head_oid",
        "_workflow_id",
        "_workflow_revision",
    )

    def __init__(
        self,
        *,
        identity: CanonicalWorktreeIdentity,
        claim: WorktreeClaim,
        branch: str,
        base_branch: str,
        remote_ref: str,
        workflow_id: WorkflowId,
        workflow_revision: int,
        ticket_head_oid: str,
        planned_reservation_fencing_token: str,
    ) -> None:
        """Recovery에 필요한 immutable external-effect identity를 고정합니다.

        Args:
            identity: Cleanup 대상 canonical worktree identity입니다.
            claim: Intent 준비 시 읽은 exact active claim입니다.
            branch: 삭제할 canonical ticket branch입니다.
            base_branch: Root checkout이 유지할 base branch입니다.
            remote_ref: Root checkout이 일치해야 할 authoritative ref입니다.
            workflow_id: Intent를 소유하는 exact workflow identity입니다.
            workflow_revision: Intent CAS에 사용한 원본 workflow revision입니다.
            ticket_head_oid: Intent 준비 시점의 exact ticket branch HEAD입니다.
            planned_reservation_fencing_token: 다음 reservation에 사용할 stable token입니다.

        Raises:
            MergeCleanupError: Identity, ref 또는 revision이 invalid하면 발생합니다.
        """
        if claim.worktree_id != identity.worktree_id or claim.path != identity.path:
            raise MergeCleanupError("cleanup plan claim does not match worktree identity")
        values = (branch, base_branch, remote_ref)
        if any(not value.strip() for value in values):
            raise MergeCleanupError("cleanup plan Git refs must not be empty")
        if workflow_revision < 0:
            raise MergeCleanupError("cleanup plan workflow revision must not be negative")
        if not self._is_object_id(ticket_head_oid):
            raise MergeCleanupError("cleanup plan ticket HEAD is invalid")
        if not planned_reservation_fencing_token.strip():
            raise MergeCleanupError("cleanup plan reservation token must not be empty")
        self._identity = identity
        self._claim = claim
        self._session_id = claim.session_id
        self._actor_id = claim.actor_id
        self._branch = branch.strip()
        self._base_branch = base_branch.strip()
        self._remote_ref = remote_ref.strip()
        self._workflow_id = workflow_id
        self._workflow_revision = workflow_revision
        self._ticket_head_oid = ticket_head_oid
        self._planned_reservation_fencing_token = planned_reservation_fencing_token

    @property
    def identity(self) -> CanonicalWorktreeIdentity:
        """Persisted canonical worktree identity를 반환합니다.

        Returns:
            삭제된 cwd 없이 registry claim을 직접 찾을 canonical identity입니다.
        """
        return self._identity

    @property
    def branch(self) -> str:
        """삭제할 canonical ticket branch를 반환합니다.

        Returns:
            Worktree 제거 뒤에도 read-back할 persisted branch입니다.
        """
        return self._branch

    @property
    def ticket_head_oid(self) -> str:
        """Intent 준비 시점의 exact ticket HEAD를 반환합니다.

        Returns:
            Reservation 전 final compare에 사용할 Git object ID입니다.
        """
        return self._ticket_head_oid

    @property
    def planned_reservation_fencing_token(self) -> str:
        """Intent가 고정한 next reservation token을 반환합니다.

        Returns:
            Registry reservation CAS가 그대로 commit해야 할 fencing token입니다.
        """
        return self._planned_reservation_fencing_token

    def matches_runtime(self, session_id: SessionId, actor_id: ActorId) -> bool:
        """Plan이 exact runtime authority에 속하는지 반환합니다.

        Args:
            session_id: StateHandle이 검증한 current session입니다.
            actor_id: StateHandle이 검증한 current actor입니다.

        Returns:
            Session과 actor가 모두 persisted owner와 같으면 참입니다.
        """
        return self._session_id == session_id and self._actor_id == actor_id

    def matches_configuration(self, base_branch: str, remote_ref: str) -> bool:
        """Retry command의 ref 인자가 persisted external plan과 같은지 반환합니다.

        Args:
            base_branch: Retry command가 요청한 root base branch입니다.
            remote_ref: Retry command가 요청한 authoritative remote ref입니다.

        Returns:
            두 ref가 intent 준비 시점 값과 모두 같으면 참입니다.
        """
        return self._base_branch == base_branch and self._remote_ref == remote_ref

    def belongs_to_workflow(self, workflow_id: WorkflowId) -> bool:
        """Plan이 requested workflow namespace에 저장된 것인지 반환합니다.

        Args:
            workflow_id: CLI가 선택한 exact workflow identity입니다.

        Returns:
            Persisted workflow identity와 같으면 참입니다.
        """
        return self._workflow_id == workflow_id

    def authorizes_claim(self, claim: WorktreeClaim) -> bool:
        """Current active/reserved claim이 persisted plan에서 연속된 lease인지 반환합니다.

        Args:
            claim: Shared registry에서 exact worktree ID로 읽은 current claim입니다.

        Returns:
            같은 resource/owner의 original active 또는 바로 다음 reservation이면 참입니다.
        """
        same_resource = (
            claim.worktree_id == self._claim.worktree_id
            and claim.path == self._claim.path
            and claim.session_id == self._claim.session_id
            and claim.actor_id == self._claim.actor_id
        )
        if not same_resource:
            return False
        if claim.status is WorktreeClaimStatus.ACTIVE:
            return (
                claim.lease_epoch == self._claim.lease_epoch
                and claim.fencing_token == self._claim.fencing_token
            )
        return (
            claim.status is WorktreeClaimStatus.CLEANUP_RESERVED
            and claim.lease_epoch == self._claim.lease_epoch + 1
            and claim.fencing_token == self._planned_reservation_fencing_token
        )

    def released_reservation(self) -> WorktreeClaim:
        """Registry release 뒤 receipt 재구성에 필요한 reservation identity를 반환합니다.

        Returns:
            Original active lease의 바로 다음 cleanup-reserved generation입니다.
        """
        return WorktreeClaim(
            worktree_id=self._claim.worktree_id,
            path=self._claim.path,
            session_id=self._claim.session_id,
            actor_id=self._claim.actor_id,
            lease_epoch=self._claim.lease_epoch + 1,
            fencing_token=self._planned_reservation_fencing_token,
            status=WorktreeClaimStatus.CLEANUP_RESERVED,
            transition_id=self._claim.transition_id,
        )

    def to_payload(self) -> dict[str, object]:
        """Crash-safe persistence용 canonical JSON payload를 반환합니다.

        Returns:
            Workflow skill_state에 저장할 exact-field JSON object입니다.
        """
        return {
            "schema": self.SCHEMA,
            "worktree_id": str(self._identity.worktree_id),
            "worktree": str(self._identity.path),
            "repository_control_root": str(self._identity.repository_control_root),
            "branch": self._branch,
            "session_id": str(self._session_id),
            "actor_id": str(self._actor_id),
            "workflow_id": str(self._workflow_id),
            "workflow_revision": self._workflow_revision,
            "lease_epoch": self._claim.lease_epoch,
            "fencing_token": self._claim.fencing_token,
            "transition_id": self._claim.transition_id,
            "base_branch": self._base_branch,
            "remote_ref": self._remote_ref,
            "ticket_head_oid": self._ticket_head_oid,
            "planned_reservation_fencing_token": self._planned_reservation_fencing_token,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> CleanupResumePlan:
        """Persisted payload를 strict exact-field plan으로 복원합니다.

        Args:
            payload: Workflow skill_state에서 읽은 cleanup intent object입니다.

        Returns:
            Canonical identity와 original lease가 검증된 immutable plan입니다.

        Raises:
            MergeCleanupError: Schema, field 또는 identity가 invalid하면 발생합니다.
        """
        if set(payload) != cls._FIELDS or payload.get("schema") != cls.SCHEMA:
            raise MergeCleanupError("cleanup resume plan shape is invalid")
        string_fields = (
            "worktree_id",
            "worktree",
            "repository_control_root",
            "branch",
            "session_id",
            "actor_id",
            "workflow_id",
            "fencing_token",
            "base_branch",
            "remote_ref",
            "ticket_head_oid",
            "planned_reservation_fencing_token",
        )
        if any(
            not isinstance(payload.get(field), str) or not str(payload[field]).strip()
            for field in string_fields
        ):
            raise MergeCleanupError("cleanup resume plan identity is invalid")
        lease_epoch = payload.get("lease_epoch")
        workflow_revision = payload.get("workflow_revision")
        transition_id = payload.get("transition_id")
        if (
            not isinstance(lease_epoch, int)
            or isinstance(lease_epoch, bool)
            or lease_epoch < 1
            or not isinstance(workflow_revision, int)
            or isinstance(workflow_revision, bool)
            or workflow_revision < 0
            or (transition_id is not None and not isinstance(transition_id, str))
        ):
            raise MergeCleanupError("cleanup resume plan lease is invalid")
        worktree_id = WorktreeId(str(payload["worktree_id"]))
        worktree = Path(str(payload["worktree"])).absolute()
        control_root = Path(str(payload["repository_control_root"])).absolute()
        identity = CanonicalWorktreeIdentity(
            worktree_id=worktree_id,
            path=worktree,
            repository_control_root=control_root,
        )
        claim = WorktreeClaim(
            worktree_id=worktree_id,
            path=worktree,
            session_id=SessionId(str(payload["session_id"])),
            actor_id=ActorId(str(payload["actor_id"])),
            lease_epoch=lease_epoch,
            fencing_token=str(payload["fencing_token"]),
            transition_id=None if transition_id is None else transition_id,
        )
        return cls(
            identity=identity,
            claim=claim,
            branch=str(payload["branch"]),
            base_branch=str(payload["base_branch"]),
            remote_ref=str(payload["remote_ref"]),
            workflow_id=WorkflowId(str(payload["workflow_id"])),
            workflow_revision=workflow_revision,
            ticket_head_oid=str(payload["ticket_head_oid"]),
            planned_reservation_fencing_token=str(payload["planned_reservation_fencing_token"]),
        )

    @staticmethod
    def _is_object_id(value: str) -> bool:
        if len(value) not in {40, 64}:
            return False
        try:
            int(value, 16)
        except ValueError:
            return False
        return True


class PrepareCleanupIntent:
    """Exact plan을 workflow skill_state에 fail-closed로 추가하는 pure mutation입니다."""

    def __init__(self, plan: CleanupResumePlan) -> None:
        """Commit할 immutable cleanup plan을 고정합니다.

        Args:
            plan: External Git mutation 전에 workflow에 기록할 exact plan입니다.
        """
        self._plan = plan

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """기존 exact intent는 재사용하고 다른 intent overwrite는 거부합니다.

        Args:
            current: Explicit CAS 원본 revision의 read-only skill state입니다.

        Returns:
            Exact intent를 보존하거나 새로 추가한 complete skill state입니다.

        Raises:
            MergeCleanupError: 같은 workflow에 다른 intent가 존재하면 발생합니다.
        """
        persisted = current.get("merge_cleanup_intent")
        payload = self._plan.to_payload()
        if persisted is not None:
            if not isinstance(persisted, Mapping) or dict(persisted) != payload:
                raise MergeCleanupError("workflow already has a different cleanup intent")
            return current
        return MappingProxyType({**current, "merge_cleanup_intent": payload})


class CompleteCleanupIntent:
    """Receipt가 durable한 exact plan만 skill_state에서 제거하는 pure mutation입니다."""

    def __init__(self, plan: CleanupResumePlan, receipt: Mapping[str, object]) -> None:
        """완료할 exact persisted cleanup plan을 고정합니다.

        Args:
            plan: Receipt와 registry read-back이 완료된 persisted plan입니다.
            receipt: External cleanup과 claim release를 증명하는 final receipt입니다.
        """
        self._plan = plan
        self._receipt = dict(receipt)

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Current intent가 exact plan과 일치할 때만 namespace에서 제거합니다.

        Args:
            current: Completion CAS 원본 revision의 read-only skill state입니다.

        Returns:
            Intent를 final receipt로 교체하고 unrelated key를 보존한 state입니다.

        Raises:
            MergeCleanupError: Current intent가 없거나 다른 plan이면 발생합니다.
        """
        persisted = current.get("merge_cleanup_intent")
        if not isinstance(persisted, Mapping) or dict(persisted) != self._plan.to_payload():
            raise MergeCleanupError("cleanup intent changed before completion")
        existing_receipt = current.get("merge_cleanup_receipt")
        if existing_receipt is not None and (
            not isinstance(existing_receipt, Mapping) or dict(existing_receipt) != self._receipt
        ):
            raise MergeCleanupError("workflow already has a different cleanup receipt")
        completed = {key: value for key, value in current.items() if key != "merge_cleanup_intent"}
        completed["merge_cleanup_receipt"] = self._receipt
        return MappingProxyType(completed)


class ReplanCleanupIntent:
    """Effect 전 stale intent를 fresh ticket snapshot으로 교체하는 pure mutation입니다."""

    def __init__(self, expected: CleanupResumePlan, replacement: CleanupResumePlan) -> None:
        """Expected stale intent와 clean replacement를 고정합니다.

        Args:
            expected: Current skill state에 반드시 존재해야 할 stale intent입니다.
            replacement: 같은 active claim에서 다시 계산한 fresh clean plan입니다.
        """
        self._expected = expected
        self._replacement = replacement

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Current intent가 exact expected일 때만 replacement를 commit합니다.

        Args:
            current: Explicit replan CAS 원본의 read-only skill state입니다.

        Returns:
            Unrelated key를 보존하고 intent만 교체한 skill state입니다.

        Raises:
            MergeCleanupPlanConflict: Current intent가 예상과 다르면 발생합니다.
        """
        persisted = current.get("merge_cleanup_intent")
        if not isinstance(persisted, Mapping) or dict(persisted) != self._expected.to_payload():
            raise MergeCleanupPlanConflict("cleanup intent changed before replan")
        return MappingProxyType(
            {
                **current,
                "merge_cleanup_intent": self._replacement.to_payload(),
            }
        )
