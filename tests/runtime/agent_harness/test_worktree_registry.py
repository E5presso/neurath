"""Shared worktree registry의 배타 claim과 read-only 비목표를 검증합니다."""

from __future__ import annotations

import fcntl
import json
import multiprocessing
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from inspect import signature
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock
from unittest import TestCase
from unittest.mock import patch

from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorKind,
    ActorStarted,
    ActorStatus,
    ActorStopped,
    ResumeId,
    SessionEnded,
    SessionId,
    SessionKernel,
    SessionLocator,
    SessionRuntime,
    SessionStarted,
    WorktreeId,
)
from scripts.agent_harness.worktree_registry import (
    CanonicalWorktreeIdentity,
    WorktreeAccess,
    WorktreeAlreadyClaimed,
    WorktreeClaim,
    WorktreeClaimInvalid,
    WorktreeClaimStatus,
    WorktreeCleanupInProgress,
    WorktreeIdentityAmbiguous,
    WorktreeIdentityResolver,
    WorktreeIdentityUnavailable,
    WorktreeLeaseConflict,
    WorktreeNotClaimed,
    WorktreeOperation,
    WorktreeRegistry,
)


def _claim_worktree(
    control_root: str,
    worktree_path: str,
    worktree_id: str,
    session_id: str,
    actor_id: str,
) -> tuple[str, str]:
    """별도 process에서 shared worktree claim을 시도합니다."""
    registry = WorktreeRegistry(SessionLocator(Path(control_root)))
    claim = WorktreeClaim(
        worktree_id=WorktreeId(worktree_id),
        path=Path(worktree_path),
        session_id=SessionId(session_id),
        actor_id=ActorId(actor_id),
    )
    try:
        registry.claim(claim)
    except WorktreeAlreadyClaimed:
        return ("denied", actor_id)
    return ("claimed", actor_id)


class WorktreeIdentityResolverTest(TestCase):
    """Git topology에서 canonical worktree identity를 scan 없이 파생합니다."""

    def setUp(self) -> None:
        """Root와 linked worktree를 가진 실제 Git fixture를 준비합니다."""
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.fixture_root = Path(self.temporary_directory.name)
        self.repository = self.fixture_root / "repository"
        self.repository.mkdir()
        self._git("init", "-q", "-b", "develop", cwd=self.repository)
        self._git(
            "-c",
            "user.name=Neurath Test",
            "-c",
            "user.email=neurath@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "initial",
            cwd=self.repository,
        )
        self.linked_worktree = self.fixture_root / "linked"
        self._git(
            "worktree",
            "add",
            "-q",
            "-b",
            "feature/linked",
            str(self.linked_worktree),
            cwd=self.repository,
        )
        self.resolver = WorktreeIdentityResolver()

    def _git(self, *arguments: str, cwd: Path) -> None:
        """Git fixture command를 외부 설정과 격리해 실행합니다.

        Args:
            arguments: Git executable에 전달할 argument sequence입니다.
            cwd: Command가 해석할 repository 또는 fixture directory입니다.
        """
        subprocess.run(
            ("git", "-C", str(cwd), *arguments),
            check=True,
            capture_output=True,
            text=True,
            env={
                "PATH": os.environ.get("PATH", ""),
                "GIT_CONFIG_NOSYSTEM": "1",
                "HOME": str(self.fixture_root),
            },
        )

    def test_root_worktree_is_deterministic_from_nested_directory(self) -> None:
        """Root 내부 어느 cwd에서도 같은 ID와 canonical top-level을 반환합니다."""
        nested = self.repository / "packages/component"
        nested.mkdir(parents=True)

        root_identity = self.resolver.resolve(self.repository)
        nested_identity = self.resolver.resolve(nested)

        self.assertEqual(root_identity.worktree_id, nested_identity.worktree_id)
        self.assertEqual(self.repository.resolve(), root_identity.path)
        self.assertEqual(self.repository.resolve(), nested_identity.path)
        self.assertEqual(self.repository.resolve(), root_identity.repository_control_root)
        self.assertEqual(
            SessionLocator.from_worktree(self.repository).control_root,
            root_identity.repository_control_root,
        )
        self.assertTrue(str(root_identity.worktree_id).startswith("git-worktree-"))

    def test_linked_worktree_has_distinct_id_and_shared_control_root(self) -> None:
        """Linked worktree는 root와 registry root를 공유하지만 resource ID는 다릅니다."""
        nested = self.linked_worktree / "apps/web"
        nested.mkdir(parents=True)

        root_identity = self.resolver.resolve(self.repository)
        linked_identity = self.resolver.resolve(self.linked_worktree)
        nested_identity = self.resolver.resolve(nested)

        self.assertNotEqual(root_identity.worktree_id, linked_identity.worktree_id)
        self.assertEqual(linked_identity.worktree_id, nested_identity.worktree_id)
        self.assertEqual(self.linked_worktree.resolve(), linked_identity.path)
        self.assertEqual(
            root_identity.repository_control_root,
            linked_identity.repository_control_root,
        )
        self.assertEqual(
            SessionLocator.from_worktree(self.linked_worktree).control_root,
            linked_identity.repository_control_root,
        )

    def test_independent_repository_at_another_path_has_distinct_id(self) -> None:
        """같은 branch 이름을 쓰는 별도 repository는 같은 resource로 충돌하지 않습니다."""
        other_repository = self.fixture_root / "other-repository"
        other_repository.mkdir()
        self._git("init", "-q", "-b", "develop", cwd=other_repository)

        root_identity = self.resolver.resolve(self.repository)
        other_identity = self.resolver.resolve(other_repository)

        self.assertNotEqual(root_identity.worktree_id, other_identity.worktree_id)
        self.assertNotEqual(
            root_identity.repository_control_root,
            other_identity.repository_control_root,
        )

    def test_non_git_missing_file_and_bare_paths_fail_closed(self) -> None:
        """Git worktree로 증명되지 않는 path는 typed unavailable error를 반환합니다."""
        non_git = self.fixture_root / "non-git"
        non_git.mkdir()
        regular_file = self.fixture_root / "file.txt"
        regular_file.write_text("not a directory", encoding="utf-8")
        missing = self.fixture_root / "missing"
        bare_repository = self.fixture_root / "bare.git"
        self._git("init", "-q", "--bare", str(bare_repository), cwd=self.fixture_root)

        for candidate in (non_git, regular_file, missing, bare_repository):
            with (
                self.subTest(candidate=candidate),
                self.assertRaises(WorktreeIdentityUnavailable),
            ):
                self.resolver.resolve(candidate)

    def test_ambient_git_environment_cannot_rebind_non_git_path(self) -> None:
        """GIT_DIR/GIT_WORK_TREE는 cwd identity를 다른 repository로 위조하지 못합니다."""
        non_git = self.fixture_root / "ambient-non-git"
        non_git.mkdir()

        with (
            patch.dict(
                os.environ,
                {
                    "GIT_DIR": str(self.repository / ".git"),
                    "GIT_WORK_TREE": str(self.repository),
                },
            ),
            self.assertRaises(WorktreeIdentityUnavailable),
        ):
            self.resolver.resolve(non_git)

    def test_malformed_git_identity_is_typed_ambiguous(self) -> None:
        """Git output shape가 불완전하면 path나 registry를 추측하지 않습니다."""
        completed = subprocess.CompletedProcess(
            args=("git",),
            returncode=0,
            stdout="only-one-field\n",
            stderr="",
        )

        with (
            patch("scripts.agent_harness.worktree_registry.subprocess.run", return_value=completed),
            self.assertRaises(WorktreeIdentityAmbiguous),
        ):
            self.resolver.resolve(self.repository)

    def test_public_surface_has_no_user_id_or_state_path(self) -> None:
        """Resolver는 cwd만 받고 canonical identity 외 persistence path를 노출하지 않습니다."""
        identity = self.resolver.resolve(self.repository)

        self.assertIsInstance(identity, CanonicalWorktreeIdentity)
        self.assertEqual(("path",), tuple(signature(self.resolver.resolve).parameters))
        self.assertFalse(hasattr(identity, "state_path"))
        self.assertFalse(hasattr(identity, "registry_path"))
        self.assertFalse(hasattr(self.resolver, "state_path"))


class WorktreeRegistryAcceptanceTest(TestCase):
    """H09의 cross-session resource ownership 불변식을 검증합니다."""

    def setUp(self) -> None:
        """같은 repository control root를 공유하는 두 session을 준비합니다."""
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.control_root = Path(self.temporary_directory.name)
        self.locator = SessionLocator(self.control_root)
        self.kernel = SessionKernel(self.locator)
        self.registry = WorktreeRegistry(self.locator)
        self.worktree_path = self.control_root / ".agents/worktrees/feature/42"
        self.worktree_path.mkdir(parents=True)
        self.worktree_id = WorktreeId("feature-42")
        self._start_session("session-a", "codex:root-a")
        self._start_session("session-b", "codex:root-b")

    def _start_session(self, session_id: str, root_actor_id: str) -> None:
        """Registry가 검증할 active owner actor를 session state에 등록합니다."""
        self.kernel.apply(
            SessionStarted(
                session_id=SessionId(session_id),
                resume_id=ResumeId(f"resume:{session_id}"),
                runtime=SessionRuntime.CODEX,
                root_actor_id=ActorId(root_actor_id),
                idempotency_key=f"session-started:{session_id}",
            )
        )

    def test_concurrent_cross_session_claim_has_exactly_one_owner(self) -> None:
        """두 session의 동시 claim은 정확히 하나만 성공하고 shared registry에 한 owner만 남깁니다."""
        context = multiprocessing.get_context("spawn")
        actors = ("codex:root-a", "codex:root-b")
        sessions = ("session-a", "session-b")

        with ProcessPoolExecutor(max_workers=2, mp_context=context) as executor:
            outcomes = tuple(
                executor.map(
                    _claim_worktree,
                    (str(self.control_root),) * 2,
                    (str(self.worktree_path),) * 2,
                    (str(self.worktree_id),) * 2,
                    sessions,
                    actors,
                )
            )

        claim = self.registry.get(self.worktree_id)
        claimed_actors = {actor for outcome, actor in outcomes if outcome == "claimed"}
        denied_actors = {actor for outcome, actor in outcomes if outcome == "denied"}

        self.assertEqual(1, len(claimed_actors))
        self.assertEqual(1, len(denied_actors))
        self.assertEqual(claimed_actors, {str(claim.actor_id)})
        self.assertEqual(denied_actors, set(actors) - claimed_actors)

    def test_non_owner_read_only_access_is_allowed_while_mutation_is_denied(self) -> None:
        """Claim은 무관 session의 read-only inspection을 막지 않지만 non-owner mutation은 거부합니다."""
        self.registry.claim(
            WorktreeClaim(
                worktree_id=self.worktree_id,
                path=self.worktree_path,
                session_id=SessionId("session-a"),
                actor_id=ActorId("codex:root-a"),
            )
        )

        read_decision = self.registry.authorize(
            WorktreeAccess(
                worktree_id=self.worktree_id,
                session_id=SessionId("session-b"),
                actor_id=ActorId("codex:root-b"),
                operation=WorktreeOperation.READ_ONLY,
            )
        )
        non_owner_mutation = self.registry.authorize(
            WorktreeAccess(
                worktree_id=self.worktree_id,
                session_id=SessionId("session-b"),
                actor_id=ActorId("codex:root-b"),
                operation=WorktreeOperation.MUTATE,
            )
        )
        owner_mutation = self.registry.authorize(
            WorktreeAccess(
                worktree_id=self.worktree_id,
                session_id=SessionId("session-a"),
                actor_id=ActorId("codex:root-a"),
                operation=WorktreeOperation.MUTATE,
            )
        )

        self.assertTrue(read_decision.allowed)
        self.assertFalse(non_owner_mutation.allowed)
        self.assertTrue(owner_mutation.allowed)

    def test_mutation_authorize_never_stale_allows_owner_after_concurrent_handoff(
        self,
    ) -> None:
        """Handoff가 먼저 commit되면 이전 owner authorization은 stale allow가 될 수 없습니다."""
        previous = self.registry.claim(
            WorktreeClaim(
                worktree_id=self.worktree_id,
                path=self.worktree_path,
                session_id=SessionId("session-a"),
                actor_id=ActorId("codex:root-a"),
            )
        )
        validation_entered = Event()
        continue_validation = Event()
        handoff_done = Event()
        completion_lock = Lock()
        completion_order: list[str] = []
        authorization_allowed: list[bool] = []
        original_validate = self.registry._validate_claim_authority

        def pause_first_authority_validation(claim: WorktreeClaim) -> None:
            """Authorize의 authority read와 decision return 사이에 handoff window를 엽니다.

            Args:
                claim: Current operation이 active authority를 확인할 owner claim입니다.
            """
            if not validation_entered.is_set():
                validation_entered.set()
                if not continue_validation.wait(timeout=5):
                    raise AssertionError("authorization race fixture timed out")
            original_validate(claim)

        def authorize_previous_owner() -> None:
            """Previous owner mutation authorization의 linearization order를 기록합니다."""
            decision = self.registry.authorize(
                WorktreeAccess(
                    worktree_id=self.worktree_id,
                    session_id=SessionId("session-a"),
                    actor_id=ActorId("codex:root-a"),
                    operation=WorktreeOperation.MUTATE,
                )
            )
            with completion_lock:
                authorization_allowed.append(decision.allowed)
                completion_order.append("authorize")

        def handoff_to_next_owner() -> None:
            """Concurrent exact-lease handoff의 commit order를 기록합니다."""
            self.registry.handoff(
                previous,
                next_session_id=SessionId("session-b"),
                next_actor_id=ActorId("codex:root-b"),
            )
            with completion_lock:
                completion_order.append("handoff")
            handoff_done.set()

        with (
            patch.object(
                self.registry,
                "_validate_claim_authority",
                side_effect=pause_first_authority_validation,
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            authorization_future = executor.submit(authorize_previous_owner)
            self.assertTrue(validation_entered.wait(timeout=5))
            handoff_future = executor.submit(handoff_to_next_owner)
            handoff_committed_before_authorize = handoff_done.wait(timeout=1)
            continue_validation.set()
            authorization_future.result(timeout=5)
            handoff_future.result(timeout=5)

        self.assertEqual(1, len(authorization_allowed))
        if handoff_committed_before_authorize:
            self.assertEqual(["handoff", "authorize"], completion_order)
            self.assertFalse(authorization_allowed[0])
        else:
            self.assertEqual(["authorize", "handoff"], completion_order)
            self.assertTrue(authorization_allowed[0])

    def test_retired_actor_cannot_reclaim_a_released_worktree(self) -> None:
        """A09: retirement fence 뒤에는 이전 resource도 다시 claim할 수 없습니다."""
        worker_id = ActorId("codex:worker-a")
        self.kernel.apply(
            ActorStarted(
                session_id=SessionId("session-a"),
                actor_id=worker_id,
                parent_actor_id=ActorId("codex:root-a"),
                kind=ActorKind.SUBAGENT,
                idempotency_key="actor-started:worker-a",
            )
        )
        active_claim = self.registry.claim(
            WorktreeClaim(
                worktree_id=self.worktree_id,
                path=self.worktree_path,
                session_id=SessionId("session-a"),
                actor_id=worker_id,
            )
        )
        self.registry.release(active_claim)
        self.kernel.apply(
            ActorStopped(
                session_id=SessionId("session-a"),
                actor_id=worker_id,
                terminal_status=ActorStatus.RETIRED,
                idempotency_key="actor-retired:worker-a",
            )
        )

        with self.assertRaises(WorktreeClaimInvalid):
            self.registry.claim(
                WorktreeClaim(
                    worktree_id=self.worktree_id,
                    path=self.worktree_path,
                    session_id=SessionId("session-a"),
                    actor_id=worker_id,
                )
            )
        with self.assertRaises(WorktreeNotClaimed):
            self.registry.get(self.worktree_id)

    def test_retired_owner_cannot_authorize_mutation_release_or_handoff_current_lease(
        self,
    ) -> None:
        """현재 lease owner가 retired되면 read만 남고 모든 owner mutation은 차단됩니다."""
        worker_id = ActorId("codex:worker-a")
        self.kernel.apply(
            ActorStarted(
                session_id=SessionId("session-a"),
                actor_id=worker_id,
                parent_actor_id=ActorId("codex:root-a"),
                kind=ActorKind.SUBAGENT,
                idempotency_key="actor-started:retiring-owner",
            )
        )
        authorize_claim = self._claim_for_owner("authorize-retired", worker_id)
        release_claim = self._claim_for_owner("release-retired", worker_id)
        handoff_claim = self._claim_for_owner("handoff-retired", worker_id)
        self.kernel.apply(
            ActorStopped(
                session_id=SessionId("session-a"),
                actor_id=worker_id,
                terminal_status=ActorStatus.RETIRED,
                idempotency_key="actor-retired:current-owner",
            )
        )

        read_decision = self.registry.authorize(
            WorktreeAccess(
                worktree_id=authorize_claim.worktree_id,
                session_id=SessionId("session-a"),
                actor_id=worker_id,
                operation=WorktreeOperation.READ_ONLY,
            )
        )
        mutation_decision = self.registry.authorize(
            WorktreeAccess(
                worktree_id=authorize_claim.worktree_id,
                session_id=SessionId("session-a"),
                actor_id=worker_id,
                operation=WorktreeOperation.MUTATE,
            )
        )

        self.assertTrue(read_decision.allowed)
        self.assertFalse(mutation_decision.allowed)
        self.assertEqual("inactive-owner", mutation_decision.reason)
        with self.assertRaises(WorktreeClaimInvalid):
            self.registry.release(release_claim)
        with self.assertRaises(WorktreeClaimInvalid):
            self.registry.handoff(
                handoff_claim,
                next_session_id=SessionId("session-b"),
                next_actor_id=ActorId("codex:root-b"),
            )
        self.assertEqual(
            release_claim.fencing_token,
            self.registry.get(release_claim.worktree_id).fencing_token,
        )
        self.assertEqual(
            handoff_claim.fencing_token,
            self.registry.get(handoff_claim.worktree_id).fencing_token,
        )

    def test_ended_owner_session_cannot_authorize_mutation_release_or_handoff_current_lease(
        self,
    ) -> None:
        """Session이 ended되면 남아 있는 owner lease는 모든 mutation authority를 잃습니다."""
        owner_id = ActorId("codex:root-a")
        authorize_claim = self._claim_for_owner("authorize-ended", owner_id)
        release_claim = self._claim_for_owner("release-ended", owner_id)
        handoff_claim = self._claim_for_owner("handoff-ended", owner_id)
        self.kernel.apply(
            SessionEnded(
                session_id=SessionId("session-a"),
                actor_id=owner_id,
                idempotency_key="session-ended:current-owner",
            )
        )

        mutation_decision = self.registry.authorize(
            WorktreeAccess(
                worktree_id=authorize_claim.worktree_id,
                session_id=SessionId("session-a"),
                actor_id=owner_id,
                operation=WorktreeOperation.MUTATE,
            )
        )

        self.assertFalse(mutation_decision.allowed)
        self.assertEqual("inactive-owner", mutation_decision.reason)
        with self.assertRaises(WorktreeClaimInvalid):
            self.registry.release(release_claim)
        with self.assertRaises(WorktreeClaimInvalid):
            self.registry.handoff(
                handoff_claim,
                next_session_id=SessionId("session-b"),
                next_actor_id=ActorId("codex:root-b"),
            )
        self.assertEqual(
            release_claim.fencing_token,
            self.registry.get(release_claim.worktree_id).fencing_token,
        )
        self.assertEqual(
            handoff_claim.fencing_token,
            self.registry.get(handoff_claim.worktree_id).fencing_token,
        )

    def _claim_for_owner(self, suffix: str, actor_id: ActorId) -> WorktreeClaim:
        """Authority lifecycle 검증용 독립 worktree lease를 준비합니다.

        Args:
            suffix: Fixture resource/path를 구분할 안전한 suffix입니다.
            actor_id: Session A에서 lease를 소유할 active actor입니다.

        Returns:
            Registry가 commit한 current fenced claim입니다.
        """
        worktree_id = WorktreeId(f"feature-42-{suffix}")
        worktree_path = self.control_root / f".agents/worktrees/feature/42-{suffix}"
        worktree_path.mkdir(parents=True)
        return self.registry.claim(
            WorktreeClaim(
                worktree_id=worktree_id,
                path=worktree_path,
                session_id=SessionId("session-a"),
                actor_id=actor_id,
            )
        )

    def test_handoff_rotates_lease_and_stale_owner_cannot_release_new_claim(self) -> None:
        """Handoff 뒤 이전 epoch/token은 새 owner의 claim을 변경할 수 없습니다."""
        previous = self.registry.claim(
            WorktreeClaim(
                worktree_id=self.worktree_id,
                path=self.worktree_path,
                session_id=SessionId("session-a"),
                actor_id=ActorId("codex:root-a"),
            )
        )

        current = self.registry.handoff(
            previous,
            next_session_id=SessionId("session-b"),
            next_actor_id=ActorId("codex:root-b"),
        )

        self.assertEqual(previous.lease_epoch + 1, current.lease_epoch)
        self.assertNotEqual(previous.fencing_token, current.fencing_token)
        self.assertIsNone(current.transition_id)
        with self.assertRaises(WorktreeLeaseConflict):
            self.registry.release(previous)
        self.assertEqual(current.fencing_token, self.registry.get(self.worktree_id).fencing_token)

    def test_proof_bound_handoff_persists_transition_through_cleanup_reservation(self) -> None:
        """Optional transition ID는 handoff generation과 cleanup reservation에 durable하게 결속됩니다."""
        previous = self.registry.claim(
            WorktreeClaim(
                worktree_id=self.worktree_id,
                path=self.worktree_path,
                session_id=SessionId("session-a"),
                actor_id=ActorId("codex:root-a"),
            )
        )

        current = self.registry.handoff(
            previous,
            next_session_id=SessionId("session-b"),
            next_actor_id=ActorId("codex:root-b"),
            transition_id="proof-sha256:abc123",
        )
        persisted = self.registry.get(self.worktree_id)
        reserved = self.registry.reserve_cleanup(current)

        self.assertEqual("proof-sha256:abc123", current.transition_id)
        self.assertEqual(current.transition_id, persisted.transition_id)
        self.assertEqual(current.transition_id, reserved.transition_id)

    def test_legacy_v2_claim_remains_readable_and_releasable_without_transition(self) -> None:
        """Transition field 전의 v2 active claim은 None provenance로 읽혀 기존 작업을 유지합니다."""
        claim_path = self.locator.worktree_registry_root / f"{self.worktree_id}.json"
        claim_path.parent.mkdir(parents=True, exist_ok=True)
        claim_path.write_text(
            json.dumps(
                {
                    "schema": WorktreeClaim.LEGACY_SCHEMA,
                    "worktree_id": str(self.worktree_id),
                    "path": str(self.worktree_path.resolve()),
                    "session_id": "session-a",
                    "actor_id": "codex:root-a",
                    "lease_epoch": 1,
                    "fencing_token": "legacy-fencing-token",
                    "status": WorktreeClaimStatus.ACTIVE.value,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        legacy = self.registry.get(self.worktree_id)

        self.assertIsNone(legacy.transition_id)
        self.registry.release(legacy)
        with self.assertRaises(WorktreeNotClaimed):
            self.registry.get(self.worktree_id)

    def test_claim_and_handoff_prepare_candidate_before_short_commit_mutex(self) -> None:
        """Serialization은 mutex 밖에서 끝나고 lock은 compare/replace만 보호합니다."""
        lock_path = self.locator.worktree_registry_root / f"{self.worktree_id}.json.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        original_serialize = self.registry._serialize_claim
        observed_unlocked: list[bool] = []

        def observe_serialization(claim: WorktreeClaim) -> bytes:
            """Serialization 시점에 commit mutex가 잡히지 않았음을 검증합니다.

            Args:
                claim: Lock 밖에서 byte candidate로 변환할 resource claim입니다.

            Returns:
                Production serializer가 만든 canonical JSON bytes입니다.
            """
            with lock_path.open("a+", encoding="utf-8") as lock:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    observed_unlocked.append(False)
                else:
                    observed_unlocked.append(True)
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            return original_serialize(claim)

        with patch.object(self.registry, "_serialize_claim", side_effect=observe_serialization):
            previous = self.registry.claim(
                WorktreeClaim(
                    worktree_id=self.worktree_id,
                    path=self.worktree_path,
                    session_id=SessionId("session-a"),
                    actor_id=ActorId("codex:root-a"),
                )
            )
            self.registry.handoff(
                previous,
                next_session_id=SessionId("session-b"),
                next_actor_id=ActorId("codex:root-b"),
            )

        self.assertEqual([True, True], observed_unlocked)

    def test_release_and_handoff_compare_owner_authority_and_lease_under_one_fence(
        self,
    ) -> None:
        """Previous owner authority와 exact lease는 두 commit mutex 안에서 함께 비교됩니다."""
        owner_id = ActorId("codex:root-a")
        release_claim = self._claim_for_owner("release-fence", owner_id)
        handoff_claim = self._claim_for_owner("handoff-fence", owner_id)
        original_validate = self.registry._validate_claim_authority
        observed_fences: list[tuple[bool, bool]] = []

        def observe_owner_authority(claim: WorktreeClaim) -> None:
            """Previous owner validation 시 두 mutex의 exclusive hold를 관찰합니다.

            Args:
                claim: Commit fence 안에서 권한을 재검증할 claim입니다.
            """
            if claim.session_id == SessionId("session-a") and claim.actor_id == owner_id:
                session_lock_path = self.locator.locate(claim.session_id).process_state_lock
                worktree_lock_path = (
                    self.locator.worktree_registry_root / f"{claim.worktree_id}.json.lock"
                )
                observed_fences.append((
                    self._lock_is_held(session_lock_path),
                    self._lock_is_held(worktree_lock_path),
                ))
            original_validate(claim)

        with patch.object(
            self.registry,
            "_validate_claim_authority",
            side_effect=observe_owner_authority,
        ):
            self.registry.release(release_claim)
            self.registry.handoff(
                handoff_claim,
                next_session_id=SessionId("session-b"),
                next_actor_id=ActorId("codex:root-b"),
            )

        self.assertEqual([(True, True), (True, True)], observed_fences)

    def _lock_is_held(self, path: Path) -> bool:
        """새 file description으로 exclusive mutex를 획득할 수 없는지 반환합니다.

        Args:
            path: Production operation이 이미 잡고 있어야 할 lock file입니다.

        Returns:
            Non-blocking exclusive acquisition이 충돌하면 True입니다.
        """
        with path.open("a+", encoding="utf-8") as competing_lock:
            try:
                fcntl.flock(
                    competing_lock.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
            except BlockingIOError:
                return True
            fcntl.flock(competing_lock.fileno(), fcntl.LOCK_UN)
            return False

    def test_claim_rechecks_actor_authority_inside_the_commit_fence(self) -> None:
        """Candidate 준비 뒤 session이 끝나면 retired actor claim을 commit하지 않습니다."""
        original_serialize = self.registry._serialize_claim

        def end_session_before_commit(claim: WorktreeClaim) -> bytes:
            """Candidate serialization 뒤 owner session을 terminal로 전이합니다.

            Args:
                claim: Lock 밖에서 준비된 desired claim입니다.

            Returns:
                원래 serializer가 만든 candidate bytes입니다.
            """
            serialized = original_serialize(claim)
            self.kernel.apply(
                SessionEnded(
                    session_id=SessionId("session-a"),
                    actor_id=ActorId("codex:root-a"),
                    idempotency_key="end-before-claim-commit",
                )
            )
            return serialized

        with (
            patch.object(
                self.registry,
                "_serialize_claim",
                side_effect=end_session_before_commit,
            ),
            self.assertRaises(WorktreeClaimInvalid),
        ):
            self.registry.claim(
                WorktreeClaim(
                    worktree_id=self.worktree_id,
                    path=self.worktree_path,
                    session_id=SessionId("session-a"),
                    actor_id=ActorId("codex:root-a"),
                )
            )
        with self.assertRaises(WorktreeNotClaimed):
            self.registry.get(self.worktree_id)

    def test_handoff_rechecks_target_authority_inside_the_commit_fence(self) -> None:
        """Candidate 준비 뒤 target session이 끝나면 ownership을 넘기지 않습니다."""
        previous = self.registry.claim(
            WorktreeClaim(
                worktree_id=self.worktree_id,
                path=self.worktree_path,
                session_id=SessionId("session-a"),
                actor_id=ActorId("codex:root-a"),
            )
        )
        original_serialize = self.registry._serialize_claim

        def end_target_before_commit(claim: WorktreeClaim) -> bytes:
            """Prepared handoff candidate의 target session을 terminal로 전이합니다.

            Args:
                claim: Lock 밖에서 준비된 next-owner claim입니다.

            Returns:
                원래 serializer가 만든 candidate bytes입니다.
            """
            serialized = original_serialize(claim)
            self.kernel.apply(
                SessionEnded(
                    session_id=SessionId("session-b"),
                    actor_id=ActorId("codex:root-b"),
                    idempotency_key="end-before-handoff-commit",
                )
            )
            return serialized

        with (
            patch.object(
                self.registry,
                "_serialize_claim",
                side_effect=end_target_before_commit,
            ),
            self.assertRaises(WorktreeClaimInvalid),
        ):
            self.registry.handoff(
                previous,
                next_session_id=SessionId("session-b"),
                next_actor_id=ActorId("codex:root-b"),
            )
        current = self.registry.get(self.worktree_id)
        self.assertEqual(previous.fencing_token, current.fencing_token)

    def test_cleanup_reservation_blocks_normal_owner_transitions(self) -> None:
        """Reservation은 long lock 없이 release, handoff, normal mutation을 차단합니다."""
        active = self.registry.claim(
            WorktreeClaim(
                worktree_id=self.worktree_id,
                path=self.worktree_path,
                session_id=SessionId("session-a"),
                actor_id=ActorId("codex:root-a"),
            )
        )

        reserved = self.registry.reserve_cleanup(active)

        self.assertEqual(WorktreeClaimStatus.CLEANUP_RESERVED, reserved.status)
        self.assertEqual(active.lease_epoch + 1, reserved.lease_epoch)
        self.assertNotEqual(active.fencing_token, reserved.fencing_token)
        decision = self.registry.authorize(
            WorktreeAccess(
                worktree_id=self.worktree_id,
                session_id=SessionId("session-a"),
                actor_id=ActorId("codex:root-a"),
                operation=WorktreeOperation.MUTATE,
            )
        )
        self.assertFalse(decision.allowed)
        self.assertEqual("cleanup-reserved", decision.reason)
        with self.assertRaises(WorktreeCleanupInProgress):
            self.registry.release(reserved)
        with self.assertRaises(WorktreeCleanupInProgress):
            self.registry.handoff(
                reserved,
                next_session_id=SessionId("session-b"),
                next_actor_id=ActorId("codex:root-b"),
            )
        with self.assertRaises(WorktreeCleanupInProgress):
            self.registry.claim(
                WorktreeClaim(
                    worktree_id=self.worktree_id,
                    path=self.worktree_path,
                    session_id=SessionId("session-a"),
                    actor_id=ActorId("codex:root-a"),
                )
            )
        self.registry.complete_cleanup(reserved)

    def test_retired_owner_cannot_complete_cleanup_reservation(self) -> None:
        """Reservation 완료도 active owner authority와 exact lease를 한 fence에서 비교합니다."""
        worker_id = ActorId("codex:cleanup-worker")
        self.kernel.apply(
            ActorStarted(
                session_id=SessionId("session-a"),
                actor_id=worker_id,
                parent_actor_id=ActorId("codex:root-a"),
                kind=ActorKind.SUBAGENT,
                idempotency_key="actor-started:cleanup-worker",
            )
        )
        active = self.registry.claim(
            WorktreeClaim(
                worktree_id=self.worktree_id,
                path=self.worktree_path,
                session_id=SessionId("session-a"),
                actor_id=worker_id,
            )
        )
        reserved = self.registry.reserve_cleanup(
            active,
            planned_fencing_token="retired-owner-cleanup-token",
        )
        self.kernel.apply(
            ActorStopped(
                session_id=SessionId("session-a"),
                actor_id=worker_id,
                terminal_status=ActorStatus.RETIRED,
                idempotency_key="actor-retired:cleanup-worker",
            )
        )

        with self.assertRaises(WorktreeClaimInvalid):
            self.registry.complete_cleanup(reserved)

        current = self.registry.get(self.worktree_id)
        self.assertEqual(reserved.fencing_token, current.fencing_token)
        self.assertEqual(WorktreeClaimStatus.CLEANUP_RESERVED, current.status)

    def test_cleanup_reservation_uses_the_planned_fencing_token(self) -> None:
        """Intent가 고정한 next token이 reservation의 exact fencing token이 됩니다."""
        active = self.registry.claim(
            WorktreeClaim(
                worktree_id=self.worktree_id,
                path=self.worktree_path,
                session_id=SessionId("session-a"),
                actor_id=ActorId("codex:root-a"),
            )
        )

        with self.assertRaises(WorktreeClaimInvalid):
            self.registry.reserve_cleanup(
                active,
                planned_fencing_token=active.fencing_token,
            )
        self.assertEqual(active.fencing_token, self.registry.get(self.worktree_id).fencing_token)

        reserved = self.registry.reserve_cleanup(
            active,
            planned_fencing_token="planned-cleanup-fencing-token",
        )

        self.assertEqual("planned-cleanup-fencing-token", reserved.fencing_token)
        self.assertEqual(active.transition_id, reserved.transition_id)
        persisted = self.registry.get(self.worktree_id)
        self.assertEqual(reserved.fencing_token, persisted.fencing_token)
        self.assertEqual(reserved.lease_epoch, persisted.lease_epoch)
        self.assertEqual(reserved.transition_id, persisted.transition_id)
        self.registry.complete_cleanup(reserved)
        with self.assertRaises(WorktreeNotClaimed):
            self.registry.get(self.worktree_id)


if __name__ == "__main__":  # pragma: no cover - test entrypoint
    import unittest

    unittest.main()
