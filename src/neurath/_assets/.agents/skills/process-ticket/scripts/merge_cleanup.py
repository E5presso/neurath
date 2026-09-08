"""Merged process-ticket의 claimed worktree와 root checkout을 정리합니다."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import MappingProxyType
from typing import ClassVar

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.agent_harness.session_kernel import (
    ActorId,
    SessionId,
    SessionKernelError,
    SessionLocator,
    WorkflowId,
    WorktreeId,
)
from scripts.agent_harness.skill_state_store import SkillStateStore
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityError,
    StateHandle,
)
from scripts.agent_harness.worktree_registry import (
    CanonicalWorktreeIdentity,
    WorktreeClaim,
    WorktreeClaimStatus,
    WorktreeIdentityResolver,
    WorktreeNotClaimed,
    WorktreeRegistry,
    WorktreeRegistryError,
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
        return MappingProxyType({
            **current,
            "merge_cleanup_intent": self._replacement.to_payload(),
        })


class MergedWorktreeCleanup:
    """Validated resource claim을 유지한 채 root sync와 cleanup을 수행합니다."""

    _GIT_LOCAL_ENVIRONMENT = (
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_CONFIG",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_PARAMETERS",
        "GIT_DIR",
        "GIT_GRAFT_FILE",
        "GIT_IMPLICIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_OBJECT_DIRECTORY",
        "GIT_PREFIX",
        "GIT_REPLACE_REF_BASE",
        "GIT_SHALLOW_FILE",
        "GIT_WORK_TREE",
    )

    def __init__(
        self,
        identity: CanonicalWorktreeIdentity,
        claim: WorktreeClaim,
        registry: WorktreeRegistry,
        *,
        base_branch: str | None = None,
        remote_ref: str | None = None,
        branch: str | None = None,
        ticket_head_oid: str | None = None,
        planned_reservation_fencing_token: str | None = None,
    ) -> None:
        """Git identity와 직전에 읽은 optimistic fencing claim을 고정합니다.

        Args:
            identity: CWD에서 검증한 canonical worktree identity입니다.
            claim: Registry에서 직전에 읽은 exact optimistic lease입니다.
            registry: 동일 worktree claim을 release할 shared registry입니다.
            base_branch: Cleanup 뒤 root checkout이 머물 base branch입니다.
            remote_ref: Root checkout과 exact 일치를 검증할 remote ref입니다.
            branch: Worktree 제거 전 intent에 보존한 optional ticket branch입니다.
            ticket_head_oid: Intent가 고정한 optional exact ticket HEAD입니다.
            planned_reservation_fencing_token: Intent가 고정한 optional next token입니다.
        """
        self._identity = identity
        self._claim = claim
        self._registry = registry
        self._repo_root = identity.repository_control_root.resolve()
        self._worktree = identity.path.resolve()
        self._branch = self._branch_name() if branch is None else branch
        self._resource_key = hashlib.sha256(str(identity.worktree_id).encode()).hexdigest()
        self._base_branch = base_branch or self._run_git("-C", str(self._repo_root), "branch", "--show-current").stdout.strip()
        if not self._base_branch:
            raise MergeCleanupError("explicit base branch required for detached root")
        self._remote_ref = remote_ref or f"origin/{self._base_branch}"
        self._ticket_head_oid = ticket_head_oid
        self._planned_reservation_fencing_token = planned_reservation_fencing_token

    def resume_plan_for(
        self,
        workflow_id: WorkflowId,
        workflow_revision: int,
    ) -> CleanupResumePlan:
        """Exact workflow revision에 결속된 resumable plan을 반환합니다.

        Args:
            workflow_id: Plan을 저장할 exact workflow identity입니다.
            workflow_revision: Intent explicit CAS에 사용할 original revision입니다.

        Returns:
            Current worktree/claim/ref identity를 모두 담은 immutable plan입니다.
        """
        self._validate_identity()
        ticket_head_oid = self._current_ticket_head()
        self._require_clean_ticket_worktree()
        return CleanupResumePlan(
            identity=self._identity,
            claim=self._claim,
            branch=self._branch,
            base_branch=self._base_branch,
            remote_ref=self._remote_ref,
            workflow_id=workflow_id,
            workflow_revision=workflow_revision,
            ticket_head_oid=ticket_head_oid,
            planned_reservation_fencing_token=secrets.token_hex(32),
        )

    def validate_ticket_before_reservation(self) -> None:
        """Intent의 ticket branch/head/clean prerequisite를 read-only로 재검증합니다.

        Raises:
            MergeCleanupPlanConflict: Branch, HEAD 또는 clean status가 intent와 다르면
                발생합니다.
        """
        if not self._worktree.exists():
            if self._claim.status is WorktreeClaimStatus.ACTIVE:
                raise MergeCleanupPlanConflict("active cleanup claim lost its ticket worktree")
            return
        actual_branch = self._branch_name()
        if actual_branch != self._branch:
            raise MergeCleanupPlanConflict(
                f"ticket branch changed before reservation: current={actual_branch}"
            )
        self._require_clean_ticket_worktree()
        actual_head = self._current_ticket_head()
        if self._ticket_head_oid is None:
            self._ticket_head_oid = actual_head
        elif actual_head != self._ticket_head_oid:
            raise MergeCleanupPlanConflict(
                f"ticket HEAD changed before reservation: current={actual_head}"
            )

    def complete(self) -> dict[str, object]:
        """Root sync, worktree removal, exact-lease release와 receipt를 수행합니다.

        Returns:
            Cleanup identity와 Git read-back을 담은 immutable receipt payload입니다.

        Raises:
            MergeCleanupError: Git topology나 cleanup identity 검증이 실패하면 발생합니다.
            WorktreeRegistryError: Exact lease reservation 또는 completion CAS가 충돌하면
                발생합니다.
            subprocess.CalledProcessError: Git read-back 또는 mutation command가 실패하면
                발생합니다.
        """
        self._validate_identity()
        self._validate_root_before_reservation()
        self.validate_ticket_before_reservation()
        if self._claim.status is WorktreeClaimStatus.ACTIVE:
            self._claim = self._registry.reserve_cleanup(
                self._claim,
                planned_fencing_token=self._planned_reservation_fencing_token,
            )
        elif self._claim.status is not WorktreeClaimStatus.CLEANUP_RESERVED:
            raise MergeCleanupError("worktree claim cannot authorize cleanup")
        self._require_root_branch("after reservation")
        self._refresh_remote_refs()
        self._synchronize_root_checkout()
        self._remove_ticket_worktree_and_branch()
        self._registry.complete_cleanup(self._claim)
        receipt = self._build_receipt()
        self._write_receipt(receipt)
        return receipt

    def complete_after_claim_release(self) -> dict[str, object]:
        """이미 release된 reservation의 external state를 read-back해 receipt를 완성합니다.

        Returns:
            Root, worktree, branch가 모두 완료 상태임을 재검증한 cleanup receipt입니다.

        Raises:
            MergeCleanupError: External cleanup이 완료되지 않았거나 identity가 다르면
                발생합니다.
            subprocess.CalledProcessError: Read-only Git inspection이 실패하면 발생합니다.
        """
        self._validate_identity()
        self._validate_root_before_reservation()
        self._refresh_remote_refs()
        self._synchronize_root_checkout()
        if self._worktree.exists() or self._worktree in self._registered_worktrees():
            raise MergeCleanupError("released cleanup claim still has a worktree")
        if self._read_git("branch", "--list", self._branch).stdout.strip():
            raise MergeCleanupError("released cleanup claim still has a branch")
        receipt = self._build_receipt()
        self._write_receipt(receipt)
        return receipt

    def _validate_identity(self) -> None:
        if self._worktree == self._repo_root or self._branch == self._base_branch:
            raise MergeCleanupError("cleanup requires a separate task worktree and branch")
        if (
            self._claim.worktree_id != self._identity.worktree_id
            or self._claim.path.resolve() != self._worktree
        ):
            raise MergeCleanupError("worktree claim does not match canonical Git identity")

    def _branch_name(self) -> str:
        result = self._run_git(
            "-C",
            str(self._worktree),
            "branch",
            "--show-current",
            optional_locks=False,
        )
        branch = result.stdout.strip()
        if not branch:
            raise MergeCleanupError("ticket worktree is detached")
        return branch

    def _current_ticket_head(self) -> str:
        return self._run_git(
            "-C",
            str(self._worktree),
            "rev-parse",
            "HEAD",
            optional_locks=False,
        ).stdout.strip()

    def _require_clean_ticket_worktree(self) -> None:
        status = self._run_git(
            "-C",
            str(self._worktree),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            optional_locks=False,
        ).stdout.strip()
        if status:
            raise MergeCleanupPlanConflict(f"ticket worktree changed before reservation: {status}")

    def _validate_root_before_reservation(self) -> None:
        """Cleanup reservation 전 root invariant를 read-only로 검증합니다."""
        git_dir = self._repo_root / ".git"
        if not git_dir.is_dir():
            raise MergeCleanupError(f"root checkout Git dir is missing: {git_dir}")
        bare = self._read_git_dir("config", "--bool", "--get", "core.bare", check=False)
        if bare.returncode == 0 and bare.stdout.strip() == "true":
            raise MergeCleanupError("root repository must be non-bare before cleanup")
        inside = self._read_git("rev-parse", "--is-inside-work-tree").stdout.strip()
        if inside != "true":
            raise MergeCleanupError("root repository must be an attached worktree before cleanup")
        self._require_root_branch("before reservation")
        status = self._root_status()
        if status:
            raise MergeCleanupError(f"root checkout must be clean before cleanup: {status}")

    def _refresh_remote_refs(self) -> None:
        """Durable cleanup reservation 뒤 remote refs를 갱신하고 target을 확인합니다."""
        self._git("fetch", "--prune", "origin")
        self._read_git("rev-parse", "--verify", self._remote_ref)

    def _synchronize_root_checkout(self) -> None:
        self._require_root_branch("before merge")
        root_head = self._read_git("rev-parse", "HEAD").stdout.strip()
        remote_head = self._read_git("rev-parse", self._remote_ref).stdout.strip()
        if root_head != remote_head:
            self._git("merge", "--ff-only", self._remote_ref)
        verified_head = self._read_git("rev-parse", "HEAD").stdout.strip()
        if verified_head != remote_head:
            raise MergeCleanupError("root HEAD does not match selected remote base after fast-forward")
        status = self._root_status()
        if status:
            raise MergeCleanupError(f"root checkout changed during synchronization: {status}")
        self._require_root_branch("after merge")

    def _remove_ticket_worktree_and_branch(self) -> None:
        if self._worktree in self._registered_worktrees():
            self._git("worktree", "remove", str(self._worktree))
        if self._worktree.exists():
            raise MergeCleanupError(f"ticket worktree still exists after cleanup: {self._worktree}")
        if self._read_git("branch", "--list", self._branch).stdout.strip():
            self._delete_ticket_branch_compare_and_swap()
        self._git("worktree", "prune")
        if self._read_git("branch", "--list", self._branch).stdout.strip():
            raise MergeCleanupError(f"ticket branch still exists: {self._branch}")
        if self._worktree in self._registered_worktrees():
            raise MergeCleanupError(f"ticket worktree is still registered: {self._worktree}")

    def _delete_ticket_branch_compare_and_swap(self) -> None:
        """Persisted ticket HEAD가 그대로일 때만 canonical branch ref를 삭제합니다."""
        if self._ticket_head_oid is None:
            raise MergeCleanupPlanConflict("cleanup plan has no expected ticket HEAD")
        branch_ref = f"refs/heads/{self._branch}"
        deletion = self._git(
            "update-ref",
            "-d",
            branch_ref,
            self._ticket_head_oid,
            check=False,
        )
        if deletion.returncode != 0:
            current = self._read_git("rev-parse", "--verify", branch_ref, check=False)
            current_oid = current.stdout.strip() if current.returncode == 0 else "missing"
            raise MergeCleanupPlanConflict(
                f"ticket branch changed before delete: current={current_oid}"
            )

    def _build_receipt(self) -> dict[str, object]:
        self._require_root_branch("final receipt")
        if self._ticket_head_oid is None:
            raise MergeCleanupError("cleanup receipt has no ticket HEAD provenance")
        root_head = self._read_git("rev-parse", "HEAD").stdout.strip()
        remote_head = self._read_git("rev-parse", self._remote_ref).stdout.strip()
        status = self._root_status()
        if root_head != remote_head or status:
            raise MergeCleanupError("root checkout invariant failed after ticket cleanup")
        return {
            "schema_version": 3,
            "worktree_id": str(self._identity.worktree_id),
            "owner_session_id": str(self._claim.session_id),
            "owner_actor_id": str(self._claim.actor_id),
            "worktree_id": str(self._claim.worktree_id),
            "worktree": str(self._worktree),
            "branch": self._branch,
            "base_branch": self._base_branch,
            "remote_ref": self._remote_ref,
            "root_head": root_head,
            "remote_head": remote_head,
            "ticket_head_oid": self._ticket_head_oid,
            "cleanup_reservation_fencing_token_sha256": hashlib.sha256(
                self._claim.fencing_token.encode()
            ).hexdigest(),
            "root_status_sha256": hashlib.sha256(status.encode()).hexdigest(),
            "worktree_removed": True,
            "branch_removed": True,
            "worktree_claim_released": True,
            "cleanup_reservation": self._claim.status.value,
            "released_lease_epoch": self._claim.lease_epoch,
            "completed_at": datetime.now(UTC).isoformat(),
        }

    def _require_root_branch(self, stage: str) -> None:
        root_branch = self._read_git("branch", "--show-current").stdout.strip()
        if root_branch != self._base_branch:
            raise MergeCleanupPlanConflict(
                f"root checkout branch changed {stage}: current={root_branch}"
            )

    def _write_receipt(self, receipt: dict[str, object]) -> None:
        receipt_path = self._repo_root / ".git/neurath-cleanup" / f"{self._resource_key}.json"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=receipt_path.parent,
                prefix=f".{receipt_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                json.dump(receipt, temporary, ensure_ascii=False, indent=2, sort_keys=True)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, receipt_path)
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)

    def _registered_worktrees(self) -> set[Path]:
        output = self._read_git("worktree", "list", "--porcelain").stdout
        return {
            Path(line.removeprefix("worktree ")).resolve()
            for line in output.splitlines()
            if line.startswith("worktree ")
        }

    def _root_status(self) -> str:
        return self._read_git(
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ).stdout.strip()

    def _git(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self._run_git("-C", str(self._repo_root), *arguments, check=check)

    def _read_git(
        self,
        *arguments: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self._run_git(
            "-C",
            str(self._repo_root),
            *arguments,
            check=check,
            optional_locks=False,
        )

    def _read_git_dir(
        self,
        *arguments: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self._run_git(
            f"--git-dir={self._repo_root / '.git'}",
            *arguments,
            check=check,
            optional_locks=False,
        )

    def _run_git(
        self,
        *arguments: str,
        check: bool = True,
        optional_locks: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        for name in self._GIT_LOCAL_ENVIRONMENT:
            environment.pop(name, None)
        if not optional_locks:
            environment["GIT_OPTIONAL_LOCKS"] = "0"
        return subprocess.run(
            ("git", *arguments),
            env=environment,
            check=check,
            capture_output=True,
            text=True,
        )


class MergeCleanupApplication:
    """Runtime identity와 cwd로 cleanup target/authority를 자동 선택합니다."""

    def __init__(self) -> None:
        """Runtime identity와 Git worktree identity resolver를 구성합니다."""
        self._runtime_resolver = RuntimeEnvironmentResolver()
        self._worktree_resolver = WorktreeIdentityResolver()

    def run(
        self,
        *,
        environment: dict[str, str],
        cwd: Path,
        workflow_id: WorkflowId,
        base_branch: str,
        remote_ref: str,
    ) -> dict[str, object]:
        """현재 runtime actor가 소유한 canonical worktree만 정리합니다.

        Args:
            environment: Exact session과 actor identity를 제공하는 runtime environment입니다.
            cwd: Cleanup 대상 claim을 파생할 current Git worktree입니다.
            workflow_id: Intent와 retry target을 선택하는 exact workflow identity입니다.
            base_branch: Cleanup 뒤 root checkout이 머물 base branch입니다.
            remote_ref: Root checkout과 비교할 authoritative remote ref입니다.

        Returns:
            완료된 cleanup의 exact identity와 read-back receipt입니다.

        Raises:
            MergeCleanupError: Runtime actor와 worktree claim이 일치하지 않으면 발생합니다.
        """
        locator = SessionLocator.from_worktree(cwd)
        binding = self._runtime_resolver.resolve(environment)
        handle = StateHandle.attach(locator, binding)
        return self.run_bound(handle=handle, cwd=cwd, workflow_id=workflow_id,
                              base_branch=base_branch, remote_ref=remote_ref)

    def run_bound(
        self, *, handle: StateHandle, cwd: Path, workflow_id: WorkflowId,
        base_branch: str, remote_ref: str,
    ) -> dict[str, object]:
        """Use an authenticated CLI/MCP handle while preserving cleanup intent recovery.

        Args:
            handle: Actual native caller, never a caller-supplied identity.
            cwd: Canonical current worktree selected by the adapter.
            workflow_id: Workflow owning the persisted cleanup intent.
            base_branch: Approved base branch after cleanup.
            remote_ref: Exact remote reference to verify.

        Returns:
            Existing cleanup receipt after all ownership and recovery checks.
        """
        locator = SessionLocator.from_worktree(cwd)
        registry = WorktreeRegistry(locator)
        state_store = SkillStateStore(handle, workflow_id)
        snapshot = state_store.read()
        raw_intent = snapshot.skill_state.get("merge_cleanup_intent")
        raw_receipt = snapshot.skill_state.get("merge_cleanup_receipt")
        if raw_intent is None and raw_receipt is not None:
            return self._completed_receipt(
                raw_receipt,
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                base_branch=base_branch,
                remote_ref=remote_ref,
            )
        if raw_intent is None:
            identity = self._worktree_resolver.resolve(cwd)
            if identity.repository_control_root != locator.control_root:
                raise MergeCleanupError("worktree and session control roots differ")
            claim = registry.get(identity.worktree_id)
            if claim.session_id != handle.session_id or claim.actor_id != handle.actor_id:
                raise MergeCleanupError("current runtime actor does not own the worktree claim")
            cleanup = MergedWorktreeCleanup(
                identity,
                claim,
                registry,
                base_branch=base_branch,
                remote_ref=remote_ref,
            )
            plan = cleanup.resume_plan_for(workflow_id, snapshot.workflow_revision)
            state_store.compare_and_update(
                snapshot.workflow_revision,
                PrepareCleanupIntent(plan),
            )
            cleanup = self._cleanup_from_plan(
                identity,
                claim,
                registry,
                plan,
                base_branch=base_branch,
                remote_ref=remote_ref,
            )
        else:
            if not isinstance(raw_intent, Mapping):
                raise MergeCleanupError("cleanup intent must be an object")
            plan = CleanupResumePlan.from_payload(raw_intent)
            if not plan.matches_runtime(handle.session_id, handle.actor_id):
                raise MergeCleanupError("cleanup resume plan runtime identity changed")
            if not plan.matches_configuration(base_branch, remote_ref):
                raise MergeCleanupError("cleanup retry Git refs differ from persisted plan")
            if not plan.belongs_to_workflow(workflow_id):
                raise MergeCleanupError("cleanup intent belongs to another workflow")
            identity = plan.identity
            if identity.repository_control_root != locator.control_root:
                raise MergeCleanupError("cleanup resume plan belongs to another repository")
            try:
                claim = registry.get(identity.worktree_id)
            except WorktreeNotClaimed:
                cleanup = MergedWorktreeCleanup(
                    identity,
                    plan.released_reservation(),
                    registry,
                    base_branch=base_branch,
                    remote_ref=remote_ref,
                    branch=plan.branch,
                    ticket_head_oid=plan.ticket_head_oid,
                    planned_reservation_fencing_token=(plan.planned_reservation_fencing_token),
                )
                receipt = cleanup.complete_after_claim_release()
                self._complete_intent(state_store, plan, receipt)
                return receipt
            if not plan.authorizes_claim(claim):
                raise MergeCleanupPlanConflict("cleanup intent does not authorize current claim")
            cleanup = self._cleanup_from_plan(
                identity,
                claim,
                registry,
                plan,
                base_branch=base_branch,
                remote_ref=remote_ref,
            )
            if claim.status is WorktreeClaimStatus.ACTIVE:
                try:
                    cleanup.validate_ticket_before_reservation()
                except MergeCleanupPlanConflict:
                    fresh_cleanup = MergedWorktreeCleanup(
                        identity,
                        claim,
                        registry,
                        base_branch=base_branch,
                        remote_ref=remote_ref,
                    )
                    replacement = fresh_cleanup.resume_plan_for(
                        workflow_id,
                        snapshot.workflow_revision,
                    )
                    state_store.compare_and_update(
                        snapshot.workflow_revision,
                        ReplanCleanupIntent(plan, replacement),
                    )
                    plan = replacement
                    cleanup = self._cleanup_from_plan(
                        identity,
                        claim,
                        registry,
                        plan,
                        base_branch=base_branch,
                        remote_ref=remote_ref,
                    )
        if claim.session_id != handle.session_id or claim.actor_id != handle.actor_id:
            raise MergeCleanupError("current runtime actor does not own the worktree claim")
        receipt = cleanup.complete()
        self._complete_intent(state_store, plan, receipt)
        return receipt

    def _cleanup_from_plan(
        self,
        identity: CanonicalWorktreeIdentity,
        claim: WorktreeClaim,
        registry: WorktreeRegistry,
        plan: CleanupResumePlan,
        *,
        base_branch: str,
        remote_ref: str,
    ) -> MergedWorktreeCleanup:
        """Persisted exact Git/lease plan을 cleanup executor에 전달합니다."""
        return MergedWorktreeCleanup(
            identity,
            claim,
            registry,
            base_branch=base_branch,
            remote_ref=remote_ref,
            branch=plan.branch,
            ticket_head_oid=plan.ticket_head_oid,
            planned_reservation_fencing_token=(plan.planned_reservation_fencing_token),
        )

    def _complete_intent(
        self,
        state_store: SkillStateStore,
        plan: CleanupResumePlan,
        receipt: Mapping[str, object],
    ) -> None:
        """Receipt 뒤 current exact intent를 explicit workflow CAS로 제거합니다."""
        expected_token_digest = hashlib.sha256(
            plan.planned_reservation_fencing_token.encode()
        ).hexdigest()
        if (
            receipt.get("ticket_head_oid") != plan.ticket_head_oid
            or receipt.get("cleanup_reservation_fencing_token_sha256") != expected_token_digest
        ):
            raise MergeCleanupPlanConflict(
                "cleanup receipt does not prove the persisted Git and lease plan"
            )
        snapshot = state_store.read()
        state_store.compare_and_update(
            snapshot.workflow_revision,
            CompleteCleanupIntent(plan, receipt),
        )

    def _completed_receipt(
        self,
        value: object,
        *,
        session_id: SessionId,
        actor_id: ActorId,
        base_branch: str,
        remote_ref: str,
    ) -> dict[str, object]:
        """Workflow에 commit된 terminal cleanup receipt를 strict read-back합니다."""
        if not isinstance(value, Mapping):
            raise MergeCleanupError("completed cleanup receipt must be an object")
        receipt = dict(value)
        ticket_head_oid = receipt.get("ticket_head_oid")
        reservation_digest = receipt.get("cleanup_reservation_fencing_token_sha256")
        if (
            receipt.get("schema_version") != 3
            or receipt.get("worktree_claim_released") is not True
            or receipt.get("owner_session_id") != str(session_id)
            or receipt.get("owner_actor_id") != str(actor_id)
            or receipt.get("base_branch") != base_branch
            or receipt.get("remote_ref") != remote_ref
            or not isinstance(ticket_head_oid, str)
            or not CleanupResumePlan._is_object_id(ticket_head_oid)
            or not isinstance(reservation_digest, str)
            or len(reservation_digest) != 64
            or any(character not in "0123456789abcdef" for character in reservation_digest)
        ):
            raise MergeCleanupError("completed cleanup receipt is invalid")
        return receipt


def main() -> int:
    """Caller-selected state/path/session 인자 없이 cleanup CLI를 실행합니다.

    Returns:
        성공 시 0, identity 또는 cleanup 검증 실패 시 2를 반환합니다.
    """
    parser = argparse.ArgumentParser(description="Finalize a merged process-ticket worktree")
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--base-branch", required=True)
    parser.add_argument("--remote-ref", required=True)
    args = parser.parse_args()
    try:
        receipt = MergeCleanupApplication().run(
            environment=dict(os.environ),
            cwd=Path.cwd(),
            workflow_id=WorkflowId(args.workflow_id),
            base_branch=args.base_branch,
            remote_ref=args.remote_ref,
        )
    except (
        MergeCleanupError,
        OSError,
        RuntimeIdentityError,
        SessionKernelError,
        subprocess.CalledProcessError,
        WorktreeRegistryError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
