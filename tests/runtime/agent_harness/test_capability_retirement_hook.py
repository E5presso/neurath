"""Capability content cleanup과 retirement 권한의 실행 경계를 검증합니다."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.agent_harness.capability_retirement_hook import (
    CapabilityRetirementDecisionCode,
    CapabilityRetirementHookApplication,
)
from scripts.agent_harness.session_kernel import (
    SessionLocator,
    TransitionRejected,
    WorkflowAdvanced,
    WorkflowId,
    WorkflowStarted,
)
from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver, StateHandle


class CapabilityRetirementHookApplicationTest(TestCase):
    """Agent shell의 protected retirement만 차단하고 무관한 host command는 보존합니다."""

    def _prepare_fixture(self) -> tuple[Path, CapabilityRetirementHookApplication]:
        """독립 root와 stateless hook application을 준비합니다."""
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        class ConfiguredPolicy(CapabilityRetirementHookApplication):
            _PROTECTED_CONNECTORS = frozenset({"penpot"})
            _PROTECTED_PATHS = (".agents/design-collaboration-policy.json", ".agents/skills/explore-ui", ".agents/skills/sync-design", ".agents/skills/implement-ui", ".agents/skills/review-ui", "docs/decisions/ADR-0045-design-collaboration-harness.md", "scripts/skill_harness/tests/test_design_collaboration_harness.py", ".codex/hooks/check-capability-retirement.sh", "scripts/agent_harness/capability_retirement_hook.py", "scripts/agent_harness/tests/test_capability_retirement_hook.py")
        return root, ConfiguredPolicy()

    def _payload(self, root: Path, tool_name: str, command: str) -> str:
        """Canonical PreToolUse process payload를 생성합니다."""
        return json.dumps({
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": {"cmd": command},
            "cwd": str(root),
        })

    def test_read_only_and_unrelated_host_commands_remain_allowed(self) -> None:
        """Read-only shell과 다른 connector는 기존 host authority를 유지합니다."""
        root, application = self._prepare_fixture()
        commands = (
            "rg -n 'design' .agents",
            "git status --short",
            "git clean --dry-run -d",
            "codex mcp remove unrelated-provider",
            'printf "%s\\n" "codex mcp remove penpot"',
        )

        for command in commands:
            with self.subTest(command=command):
                result = application.run(
                    self._payload(root, "functions.exec_command", command),
                    root,
                )

                self.assertEqual(0, result.exit_code)
                self.assertIs(CapabilityRetirementDecisionCode.HOST_MANAGED, result.code)

    def test_canvas_artifact_purge_does_not_authorize_penpot_connector_removal(self) -> None:
        """Canvas artifact가 실제로 없어져도 protected connector retirement는 deny됩니다."""
        root, application = self._prepare_fixture()
        artifact = root / "test-canvas.penpot"
        artifact.write_text("temporary canvas", encoding="utf-8")
        artifact.unlink()

        result = application.run(
            self._payload(root, "functions.exec_command", "codex mcp remove penpot"),
            root,
        )

        self.assertFalse(artifact.exists())
        self.assertEqual(2, result.exit_code)
        self.assertIs(CapabilityRetirementDecisionCode.PROTECTED_CONNECTOR, result.code)
        self.assertIn('"permissionDecision":"deny"', result.stderr)


    def test_shell_cannot_delete_protected_capability_or_untracked_assets(self) -> None:
        """직접 path 삭제와 broad git clean은 agent shell에서 실행 전에 거부됩니다."""
        root, application = self._prepare_fixture()
        cases = (
            (
                "rm -rf .agents/skills/explore-ui",
                CapabilityRetirementDecisionCode.PROTECTED_CAPABILITY,
            ),
            (
                "git rm .agents/design-collaboration-policy.json",
                CapabilityRetirementDecisionCode.PROTECTED_CAPABILITY,
            ),
            (
                "find .agents/skills/explore-ui -delete",
                CapabilityRetirementDecisionCode.PROTECTED_CAPABILITY,
            ),
            ("git clean -fd", CapabilityRetirementDecisionCode.PROTECTED_CAPABILITY),
        )

        for command, expected in cases:
            with self.subTest(command=command):
                result = application.run(self._payload(root, "Bash", command), root)

                self.assertEqual(2, result.exit_code)
                self.assertIs(expected, result.code)

    def test_rejected_adaptive_transition_cannot_be_bypassed_by_shell_deletion(self) -> None:
        """실제 invalid adaptive transition 뒤 protected shell delete는 target을 바꾸지 못합니다."""
        root, application = self._prepare_fixture()
        binding = RuntimeEnvironmentResolver().resolve({"CODEX_THREAD_ID": "retirement-boundary"})
        handle = StateHandle.initialize(SessionLocator(root), binding)
        workflow_id = WorkflowId("retirement-transition")
        workflow_payload = {
            "phase_run": {
                "schema_version": 1,
                "adaptive_control_required": False,
            },
            "skill_state": {},
        }
        handle.apply(
            WorkflowStarted(
                session_id=handle.session_id,
                workflow_id=workflow_id,
                owner_actor_id=handle.actor_id,
                kind="evaluate-harness",
                goal="보호된 capability retirement 경계를 검증한다",
                payload=workflow_payload,
                idempotency_key="retirement-boundary:start",
            )
        )
        workflow = handle.inspect().workflows[workflow_id]

        with self.assertRaises(TransitionRejected):
            handle.apply(
                WorkflowAdvanced(
                    session_id=handle.session_id,
                    workflow_id=workflow_id,
                    actor_id=handle.actor_id,
                    expected_workflow_revision=workflow.revision,
                    payload={
                        **workflow_payload,
                        "phase_run": {
                            **workflow_payload["phase_run"],
                            "adaptive_control_required": True,
                        },
                    },
                    idempotency_key="retirement-boundary:invalid-transition",
                )
            )

        protected = root / ".agents/design-collaboration-policy.json"
        protected.parent.mkdir(parents=True, exist_ok=True)
        protected.write_text("preserved", encoding="utf-8")
        result = application.run(
            self._payload(
                root,
                "functions.exec_command",
                "rm -f .agents/design-collaboration-policy.json",
            ),
            root,
        )

        self.assertEqual(2, result.exit_code)
        self.assertIs(CapabilityRetirementDecisionCode.PROTECTED_CAPABILITY, result.code)
        self.assertEqual("preserved", protected.read_text(encoding="utf-8"))
