"""PreToolUse worktree fence의 resource-based decision matrix를 검증합니다."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.agent_harness.runtime_hook import RuntimeHookApplication
from scripts.agent_harness.session_kernel import (
    ActorId,
    ResumeId,
    SessionId,
    SessionKernel,
    SessionLocator,
    SessionRuntime,
    SessionStarted,
    WorkflowId,
    WorkflowStarted,
)
from scripts.agent_harness.worktree_hook import (
    WorktreeHookApplication,
    WorktreeHookCommand,
    WorktreeHookDecisionCode,
    WorktreeHookDisposition,
    WorktreeHookResult,
)
from scripts.agent_harness.worktree_registry import (
    WorktreeClaim,
    WorktreeIdentityResolver,
    WorktreeNotClaimed,
    WorktreeRegistry,
)


class WorktreeHookApplicationTest(TestCase):
    """Hook payload를 canonical worktree claim과 대조합니다."""

    def setUp(self) -> None:
        """Root와 linked worktree, 두 runtime session을 준비합니다."""
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
        self.worktree = self.fixture_root / "worker"
        self._git(
            "worktree",
            "add",
            "-q",
            "-b",
            "feature/worker",
            str(self.worktree),
            cwd=self.repository,
        )
        (self.worktree / "src").mkdir()
        (self.worktree / "src/example.py").write_text("value = 1\n", encoding="utf-8")
        self.locator = SessionLocator.from_worktree(self.repository)
        self.kernel = SessionKernel(self.locator)
        self.owner_environment = {"CODEX_THREAD_ID": "owner-session"}
        self.other_environment = {"CODEX_THREAD_ID": "other-session"}
        self.owner_actor = ActorId("codex:session:owner-session")
        self.other_actor = ActorId("codex:session:other-session")
        self._start_session(SessionId("owner-session"), self.owner_actor)
        self._start_session(SessionId("other-session"), self.other_actor)
        self.identity = WorktreeIdentityResolver().resolve(self.worktree)
        WorktreeRegistry(self.locator).claim(
            WorktreeClaim(
                worktree_id=self.identity.worktree_id,
                path=self.identity.path,
                session_id=SessionId("owner-session"),
                actor_id=self.owner_actor,
            )
        )
        self.application = WorktreeHookApplication()

    def _git(self, *arguments: str, cwd: Path) -> None:
        """Test Git topology를 host 설정과 격리해 구성합니다."""
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

    def _start_session(
        self,
        session_id: SessionId,
        root_actor_id: ActorId,
        runtime: SessionRuntime = SessionRuntime.CODEX,
    ) -> None:
        """Hook authority가 attach할 exact active session을 만듭니다."""
        self.kernel.apply(
            SessionStarted(
                session_id=session_id,
                resume_id=ResumeId(f"resume:{session_id}"),
                runtime=runtime,
                root_actor_id=root_actor_id,
                idempotency_key=f"start:{session_id}",
            )
        )

    def _run(
        self,
        payload: object,
        *,
        environment: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> WorktreeHookResult:
        """JSON hook payload를 application에 전달합니다."""
        return self.application.run(
            json.dumps(payload),
            self.owner_environment if environment is None else environment,
            self.repository if cwd is None else cwd,
        )

    def test_host_managed_read_bypasses_claimed_worktree(self) -> None:
        """Read authority는 host가 소유하며 repository ownership state를 열지 않습니다."""
        result = self._run(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": str(self.worktree / "src/example.py")},
            },
            environment=self.other_environment,
        )

        self.assertEqual(0, result.exit_code)
        self.assertIs(WorktreeHookDisposition.DEFER_TO_HOST, result.decision.disposition)
        self.assertEqual(WorktreeHookDecisionCode.HOST_MANAGED, result.decision.code)

    def test_host_managed_tools_require_neither_identity_nor_worktree_claim(self) -> None:
        """Web과 PTY control은 repository identity와 worktree claim을 요구하지 않습니다."""
        payloads = (
            {
                "tool_name": "WebSearch",
                "tool_use_id": "research-1",
                "tool_input": {"query": "current evidence"},
            },
            {
                "tool_name": "functions.write_stdin",
                "tool_use_id": "interrupt-1",
                "tool_input": {"session_id": 123, "chars": "\u0003"},
            },
        )
        for payload in payloads:
            with self.subTest(tool_name=payload["tool_name"]):
                with (
                    patch(
                        "scripts.agent_harness.worktree_hook.SessionLocator.from_worktree",
                        side_effect=AssertionError("host-managed tool opened session state"),
                    ),
                    patch(
                        "scripts.agent_harness.worktree_hook.RuntimeEnvironmentResolver.resolve",
                        side_effect=AssertionError("host-managed tool resolved runtime identity"),
                    ),
                    patch(
                        "scripts.agent_harness.worktree_hook.WorktreeRegistry.authorize",
                        side_effect=AssertionError("host-managed tool opened worktree registry"),
                    ),
                ):
                    result = self._run(
                        payload,
                        environment={},
                        cwd=self.worktree,
                    )

                self.assertEqual(0, result.exit_code, result.stderr)
                self.assertIs(
                    WorktreeHookDisposition.DEFER_TO_HOST,
                    result.decision.disposition,
                )
                self.assertEqual(
                    WorktreeHookDecisionCode.HOST_MANAGED,
                    result.decision.code,
                )

    def test_pretool_recovers_exact_codex_session_when_session_start_was_skipped(self) -> None:
        """Trusted PreTool이 완전히 없는 root state를 startup lifecycle로 한 번 복구합니다."""
        session_id = "session-start-was-skipped"
        payload = json.dumps({
            "hook_event_name": "PreToolUse",
            "session_id": session_id,
            "tool_name": "WebSearch",
            "tool_use_id": "research-after-skipped-start",
            "tool_input": {"query": "current evidence"},
        })

        exit_code, stdout, stderr = WorktreeHookCommand().run_payload(
            payload,
            {"CODEX_THREAD_ID": session_id},
            self.repository,
        )

        self.assertEqual(0, exit_code, stderr)
        state = SessionKernel(self.locator).inspect(SessionId(session_id))
        self.assertEqual(SessionId(session_id), state.session.id)
        self.assertEqual(
            ActorId(f"codex:session:{session_id}"),
            state.session.root_actor_id,
        )
        output = json.loads(stdout)
        specific = output["hookSpecificOutput"]
        self.assertEqual("PreToolUse", specific["hookEventName"])
        self.assertEqual("allow", specific["permissionDecision"])
        self.assertIn("additionalContext", specific)

    def test_codex_pretool_uses_required_payload_session_without_thread_environment(self) -> None:
        """Codex adapter는 공식 PreToolUse session_id로 existing root actor를 결속합니다."""
        payload = json.dumps({
            "hook_event_name": "PreToolUse",
            "session_id": "owner-session",
            "tool_name": "WebSearch",
            "tool_use_id": "research-without-thread-env",
            "tool_input": {"query": "current evidence"},
        })

        exit_code, _, stderr = WorktreeHookCommand().run_payload(
            payload,
            {},
            self.repository,
            hook_runtime=SessionRuntime.CODEX,
        )

        self.assertEqual(0, exit_code, stderr)

    def test_official_codex_state_free_child_cannot_mutate_as_root(self) -> None:
        """Unregistered official agent_id는 claimed root worktree authority로 승격되지 않습니다."""
        before = self.kernel.inspect(SessionId("owner-session")).to_payload()
        payload = json.dumps({
            "hook_event_name": "PreToolUse",
            "session_id": "owner-session",
            "agent_id": "state-free-worker",
            "agent_type": "explorer",
            "tool_name": "Write",
            "tool_use_id": "state-free-write",
            "tool_input": {"file_path": str(self.worktree / "src/example.py")},
        })

        exit_code, stdout, stderr = WorktreeHookCommand().run_payload(
            payload,
            {},
            self.repository,
            hook_runtime=SessionRuntime.CODEX,
        )

        self.assertEqual(2, exit_code)
        self.assertEqual("", stdout)
        self.assertIn("permissionDecision", stderr)
        self.assertEqual(before, self.kernel.inspect(SessionId("owner-session")).to_payload())
        claim = WorktreeRegistry(self.locator).get(self.identity.worktree_id)
        self.assertEqual(self.owner_actor, claim.actor_id)

    def test_unattested_claude_parent_pointer_cannot_create_mutation_authority(self) -> None:
        """Raw parent_agent_id가 있어도 unattested child는 attach나 mutation을 할 수 없습니다."""
        session_id = SessionId("claude-unattested-parent")
        root_actor = ActorId("claude-code:session:claude-unattested-parent")
        self._start_session(session_id, root_actor, SessionRuntime.CLAUDE_CODE)
        before = self.kernel.inspect(session_id).to_payload()
        runtime = RuntimeHookApplication(
            self.locator,
            enclave_max_bytes=4096,
            additional_context_max_bytes=2048,
        )

        started = runtime.run(
            json.dumps({
                "hook_event_name": "SubagentStart",
                "session_id": str(session_id),
                "agent_id": "unattested-worker",
                "parent_agent_id": f"session:{session_id}",
                "agent_type": "general-purpose",
                "cwd": str(self.repository),
                "transcript_path": str(self.repository / "unattested.jsonl"),
            }),
            {"CLAUDE_PROJECT_DIR": str(self.repository)},
        )
        mutation = WorktreeHookApplication(SessionRuntime.CLAUDE_CODE).run(
            json.dumps({
                "hook_event_name": "PreToolUse",
                "session_id": str(session_id),
                "agent_id": "unattested-worker",
                "tool_name": "Write",
                "tool_use_id": "unattested-write",
                "tool_input": {"file_path": str(self.worktree / "src/example.py")},
            }),
            {"CLAUDE_CODE_SESSION_ID": str(session_id)},
            self.repository,
        )

        self.assertEqual(0, started.exit_code, started.diagnostic)
        self.assertIsNone(started.pending_effect)
        self.assertEqual(before, self.kernel.inspect(session_id).to_payload())
        self.assertNotIn(
            ActorId("claude-code:unattested-worker"), self.kernel.inspect(session_id).actors
        )
        self.assertEqual(2, mutation.exit_code)
        self.assertEqual(WorktreeHookDecisionCode.IDENTITY_UNAVAILABLE, mutation.decision.code)

    def test_pretool_never_reinitializes_partial_or_corrupt_session_state(self) -> None:
        """State artifact가 존재하면 skipped-start 복구로 덮어쓰지 않고 fail-closed합니다."""
        session_id = SessionId("corrupt-session-start")
        paths = self.locator.locate(session_id)
        paths.directory.mkdir(parents=True)
        paths.process_state.write_text("{}\n", encoding="utf-8")
        payload = json.dumps({
            "hook_event_name": "PreToolUse",
            "session_id": str(session_id),
            "tool_name": "WebSearch",
            "tool_use_id": "research-after-corrupt-start",
            "tool_input": {"query": "current evidence"},
        })

        exit_code, stdout, stderr = WorktreeHookCommand().run_payload(
            payload,
            {"CODEX_THREAD_ID": str(session_id)},
            self.repository,
        )

        self.assertEqual(2, exit_code)
        self.assertEqual("", stdout)
        self.assertIn("session-uninitialized", stderr)
        self.assertEqual("{}\n", paths.process_state.read_text(encoding="utf-8"))

    def test_exact_owner_can_edit_claimed_worktree(self) -> None:
        """Target worktree의 exact owner actor는 product mutation을 수행할 수 있습니다."""
        result = self._run({
            "tool_name": "Edit",
            "tool_input": {"file_path": str(self.worktree / "src/example.py")},
        })

        self.assertEqual(0, result.exit_code)
        self.assertIs(WorktreeHookDisposition.REPOSITORY_ALLOW, result.decision.disposition)
        self.assertEqual(WorktreeHookDecisionCode.OWNER, result.decision.code)

    def test_evaluate_harness_terminal_candidate_denies_further_repository_mutation(self) -> None:
        """Frozen matrix 통과 뒤의 추가 patch는 새 사용자 승인 전까지 거부합니다."""
        self._start_evaluate_harness_workflow(current_phase_id=None)

        result = self._run({
            "tool_name": "Edit",
            "tool_input": {"file_path": str(self.worktree / "src/example.py")},
        })

        self.assertEqual(2, result.exit_code)
        self.assertEqual(
            WorktreeHookDecisionCode.EVALUATION_LOOP_TERMINAL,
            result.decision.code,
        )

    def test_evaluate_harness_terminal_candidate_preserves_host_managed_fast_path(self) -> None:
        """Terminal control state도 host-managed inspection을 가로채지 않습니다."""
        self._start_evaluate_harness_workflow(current_phase_id=None)

        result = self._run({
            "tool_name": "Read",
            "tool_input": {"file_path": str(self.worktree / "src/example.py")},
        })

        self.assertEqual(0, result.exit_code)
        self.assertEqual(WorktreeHookDecisionCode.HOST_MANAGED, result.decision.code)

    def test_evaluate_harness_budget_denies_patch_but_allows_terminal_control_command(
        self,
    ) -> None:
        """Wall-clock watchdog 뒤에는 patch 대신 blocked/finalize control만 허용합니다."""
        self._start_evaluate_harness_workflow(current_phase_id=2, started_at_epoch=1.0)

        patch_result = self._run({
            "tool_name": "Edit",
            "tool_input": {"file_path": str(self.worktree / "src/example.py")},
        })
        control_result = self._run({
            "tool_name": "exec_command",
            "tool_input": {
                "cmd": (
                    "uv run python -m scripts.skill_harness.phase_runner complete "
                    "--workflow-id evaluation-budget --phase-id 2 --status blocked "
                    "--summary bounded --reason user-approval-required"
                ),
                "workdir": str(self.worktree),
            },
        })

        self.assertEqual(2, patch_result.exit_code)
        self.assertEqual(
            WorktreeHookDecisionCode.EVALUATION_BUDGET_EXHAUSTED,
            patch_result.decision.code,
        )
        self.assertEqual(0, control_result.exit_code, control_result.stderr)
        self.assertEqual(WorktreeHookDecisionCode.HOST_MANAGED, control_result.decision.code)

    def test_non_owner_cannot_edit_claimed_worktree(self) -> None:
        """다른 session의 mutation은 exact claim이 존재하면 fail closed합니다."""
        result = self._run(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(self.worktree / "src/example.py")},
            },
            environment=self.other_environment,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIs(WorktreeHookDisposition.REPOSITORY_DENY, result.decision.disposition)
        self.assertEqual(WorktreeHookDecisionCode.NON_OWNER, result.decision.code)
        self.assertIn("permissionDecision", result.stderr)

    def _start_evaluate_harness_workflow(
        self,
        *,
        current_phase_id: int | None,
        started_at_epoch: float | None = None,
    ) -> None:
        """Owner session에 budget 판정용 evaluate-harness phase projection을 만듭니다."""
        started_at = time.time() if started_at_epoch is None else started_at_epoch
        self.kernel.apply(
            WorkflowStarted(
                session_id=SessionId("owner-session"),
                workflow_id=WorkflowId("evaluation-budget"),
                owner_actor_id=self.owner_actor,
                kind="evaluate-harness",
                goal="bounded harness evaluation",
                payload={
                    "phase_run": {
                        "schema_version": 1,
                        "skill": "evaluate-harness",
                        "run_id": "run-001",
                        "north_star": "bounded harness evaluation",
                        "current_phase_id": current_phase_id,
                        "terminal_state": None,
                        "phases": [],
                        "adaptive_control_required": True,
                        "started_at_epoch": started_at,
                    },
                    "skill_state": {},
                },
                idempotency_key="evaluation-budget:start",
            )
        )

    def test_claimed_mutation_without_runtime_identity_is_denied(self) -> None:
        """Claimed resource를 mutate할 actor identity가 없으면 추측하지 않습니다."""
        result = self._run(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(self.worktree / "src/new.py")},
            },
            environment={},
        )

        self.assertEqual(2, result.exit_code)
        self.assertEqual(WorktreeHookDecisionCode.IDENTITY_UNAVAILABLE, result.decision.code)

    def test_unclaimed_worktree_mutation_requires_exact_active_actor(self) -> None:
        """Unclaimed mutation도 session이 없는 native child를 root로 승격하지 않습니다."""
        target = self.repository / "README.md"
        result = self._run(
            {"tool_name": "Write", "tool_input": {"file_path": str(target)}},
            environment={},
        )

        self.assertEqual(2, result.exit_code)
        self.assertEqual(WorktreeHookDecisionCode.IDENTITY_UNAVAILABLE, result.decision.code)

    def test_unclaimed_worktree_requires_explicit_typed_claim_before_mutation(self) -> None:
        """첫 mutation 자체는 claim을 만들지 않고 typed claim command를 요구합니다."""
        target = self.repository / "README.md"

        result = self._run({
            "tool_name": "Write",
            "tool_input": {"file_path": str(target)},
        })
        identity = WorktreeIdentityResolver().resolve(self.repository)

        self.assertEqual(2, result.exit_code)
        self.assertEqual(WorktreeHookDecisionCode.RESOURCE_UNAVAILABLE, result.decision.code)
        with self.assertRaises(WorktreeNotClaimed):
            WorktreeRegistry(self.locator).get(identity.worktree_id)

    def test_denied_composite_pretool_does_not_claim_an_unexecuted_mutation(self) -> None:
        """Material intent가 없는 denied invocation은 unclaimed worktree를 선점하지 않습니다."""
        identity = WorktreeIdentityResolver().resolve(self.repository)
        registry = WorktreeRegistry(self.locator)
        with self.assertRaises(WorktreeNotClaimed):
            registry.get(identity.worktree_id)
        payload = json.dumps({
            "tool_name": "Write",
            "tool_use_id": "unprepared-write-1",
            "tool_input": {"file_path": str(self.repository / "README.md")},
        })

        exit_code, _, _ = WorktreeHookCommand().run_payload(
            payload,
            self.owner_environment,
            self.repository,
        )

        self.assertEqual(2, exit_code)
        with self.assertRaises(WorktreeNotClaimed):
            registry.get(identity.worktree_id)

    def test_other_session_cannot_mutate_after_explicit_typed_claim(self) -> None:
        """Typed claim을 가진 checkout은 뒤늦은 다른 root session에도 열리지 않습니다."""
        target = self.repository / "README.md"
        identity = WorktreeIdentityResolver().resolve(self.repository)
        WorktreeRegistry(self.locator).claim(
            WorktreeClaim(
                worktree_id=identity.worktree_id,
                path=identity.path,
                session_id=SessionId("owner-session"),
                actor_id=self.owner_actor,
            )
        )
        first = self._run({
            "tool_name": "Write",
            "tool_input": {"file_path": str(target)},
        })
        second = self._run(
            {"tool_name": "Write", "tool_input": {"file_path": str(target)}},
            environment=self.other_environment,
        )

        self.assertEqual(WorktreeHookDecisionCode.OWNER, first.decision.code)
        self.assertEqual(WorktreeHookDecisionCode.NON_OWNER, second.decision.code)
        self.assertEqual(2, second.exit_code)

    def test_unknown_provider_tool_is_host_managed(self) -> None:
        """새 provider tool은 repository mutation authority를 얻거나 요구하지 않습니다."""
        result = self._run({
            "tool_name": "FutureConnector",
            "tool_input": {
                "payload": "opaque",
                "workdir": str(self.worktree),
            },
        })

        self.assertEqual(0, result.exit_code)
        self.assertEqual(WorktreeHookDecisionCode.HOST_MANAGED, result.decision.code)

    def test_multiedit_authorizes_every_nested_edit_target(self) -> None:
        """MultiEdit의 ``edits[]`` 내부 target도 각각 exact claim을 따릅니다."""
        result = self._run(
            {
                "tool_name": "MultiEdit",
                "tool_input": {
                    "edits": [
                        {
                            "file_path": str(self.worktree / "src/example.py"),
                            "old_string": "value = 1",
                            "new_string": "value = 2",
                        }
                    ],
                    "workdir": str(self.repository),
                },
            },
            environment=self.other_environment,
        )

        self.assertEqual(2, result.exit_code)
        self.assertEqual(WorktreeHookDecisionCode.NON_OWNER, result.decision.code)

    def test_apply_patch_move_authorizes_destination_target(self) -> None:
        """Patch rename은 source뿐 아니라 ``Move to`` destination도 authorize합니다."""
        external_target = self.fixture_root / "outside.py"
        patch = "\n".join((
            "*** Begin Patch",
            f"*** Update File: {self.worktree / 'src/example.py'}",
            f"*** Move to: {external_target}",
            "@@",
            "-value = 1",
            "+value = 2",
            "*** End Patch",
        ))
        result = self._run({
            "tool_name": "apply_patch",
            "tool_input": {
                "input": patch,
                "workdir": str(self.worktree),
            },
        })

        self.assertEqual(2, result.exit_code)
        self.assertEqual(WorktreeHookDecisionCode.RESOURCE_UNAVAILABLE, result.decision.code)

    def test_claimed_worktree_command_cannot_escape_to_external_target(self) -> None:
        """Claim authority는 repository 밖의 임의 경로까지 확장되지 않습니다."""
        external_target = self.fixture_root / "outside.txt"
        result = self._run({
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(external_target),
                "workdir": str(self.worktree),
            },
        })

        self.assertEqual(2, result.exit_code)
        self.assertEqual(WorktreeHookDecisionCode.RESOURCE_UNAVAILABLE, result.decision.code)

    def test_canonical_state_direct_mutation_is_always_denied(self) -> None:
        """Canonical state는 owner라도 StateHandle 밖에서 쓸 수 없습니다."""
        state_path = self.locator.locate(SessionId("owner-session")).process_state
        result = self._run({"tool_name": "Write", "tool_input": {"file_path": str(state_path)}})

        self.assertEqual(2, result.exit_code)
        self.assertEqual(WorktreeHookDecisionCode.CANONICAL_STATE, result.decision.code)

    def test_external_publication_approval_is_host_owned(self) -> None:
        """Repository hook은 외부 publication approval을 승인하거나 거부하지 않습니다."""
        without_annotation = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": "gh pr merge 42 --squash",
                "workdir": str(self.worktree),
            },
        })
        with_annotation = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": "gh pr merge 42 --squash",
                "workdir": str(self.worktree),
                "explicit_user_approval": True,
                "approved_by": "user",
            },
        })

        self.assertEqual(0, without_annotation.exit_code)
        self.assertEqual(
            WorktreeHookDecisionCode.HOST_MANAGED,
            without_annotation.decision.code,
        )
        self.assertEqual(0, with_annotation.exit_code)
        self.assertEqual(WorktreeHookDecisionCode.HOST_MANAGED, with_annotation.decision.code)

    def test_invalid_payload_fails_closed_without_scanning_for_owner(self) -> None:
        """Invalid input은 다른 session이나 flat state를 검색하지 않습니다."""
        result = self.application.run("[]", self.owner_environment, self.repository)

        self.assertEqual(2, result.exit_code)
        self.assertEqual(WorktreeHookDecisionCode.INVALID_INPUT, result.decision.code)
