"""Repository mutation harness와 host-managed tool의 책임 경계를 검증합니다."""

import json
from pathlib import Path
from unittest import TestCase

from scripts.agent_harness.material_action_runtime_hook import (
    MaterialActionHookDecisionCode,
    MaterialActionRuntimeHookApplication,
)
from scripts.agent_harness.tool_action_parser import ToolActionEffect, ToolActionParser
from scripts.agent_harness.worktree_hook import (
    WorktreeHookApplication,
    WorktreeHookDecisionCode,
)


class ToolAuthorityBoundaryTest(TestCase):
    """Harness는 구조화된 repository edit만 사전 authorization 대상으로 삼습니다."""

    def setUp(self) -> None:
        """실제 repository root와 stateless parser를 준비합니다."""
        self.root = Path(__file__).resolve().parents[3]
        self.parser = ToolActionParser()

    def test_shell_and_external_tools_are_host_managed_without_content_inference(self) -> None:
        """Shell 문법, 웹, coordination과 unknown plugin은 repository gate가 판별하지 않습니다."""
        action_prepare = (
            "uv run python -m scripts.agent_harness.state_cli action prepare "
            "--batch-id batch-1 --kind local-mutation "
            "--target scripts/agent_harness/tool_action_parser.py "
            "--expectations-json "
            '\'[{"observable_id":"scripts/agent_harness/tool_action_parser.py",'
            '"expected_delta":"changed","expected_digest":"' + "a" * 64 + "\"}]'"
        )
        payloads = (
            self._payload("functions.exec_command", {"cmd": "rg -n 'a|b;[c]' AGENTS.md"}),
            self._payload("functions.exec_command", {"cmd": "'unterminated"}),
            self._payload("functions.exec_command", {"cmd": action_prepare}),
            self._payload("web.run", {"search_query": [{"q": "ASD-STE100"}]}),
            self._payload("collaboration.send_message", {"target": "child", "message": "done"}),
            self._payload("mcp__future__unknown_tool", {"operation": "provider-owned"}),
        )

        for raw_input in payloads:
            with self.subTest(raw_input=raw_input):
                request = self.parser.parse_request(raw_input, self.root)

                self.assertIs(ToolActionEffect.HOST_MANAGED, request.effect)
                self.assertEqual((), request.targets)
                self.assertFalse(hasattr(request, "targets_are_transparent"))
                self.assertFalse(hasattr(request, "requires_worktree_ownership"))

    def test_only_structured_edit_tools_create_material_mutation_requests(self) -> None:
        """Structured edit payload의 literal path만 material-action target이 됩니다."""
        target = self.root / "scripts/agent_harness/tool_action_parser.py"
        direct = self.parser.parse_request(
            self._payload("Edit", {"file_path": str(target), "new_string": "changed"}),
            self.root,
        )
        patch = self.parser.parse_request(
            self._payload(
                "functions.apply_patch",
                {"input": "*** Begin Patch\n*** Update File: AGENTS.md\n*** End Patch"},
            ),
            self.root,
        )

        self.assertIs(ToolActionEffect.MATERIAL_MUTATION, direct.effect)
        self.assertEqual((str(target.resolve()),), direct.targets)
        self.assertIs(ToolActionEffect.MATERIAL_MUTATION, patch.effect)
        self.assertEqual((str((self.root / "AGENTS.md").resolve()),), patch.targets)

    def test_host_managed_tools_bypass_worktree_and_material_authorization(self) -> None:
        """Non-edit tool은 runtime identity나 prepared batch 없이 두 repository gate를 통과합니다."""
        payloads = (
            self._payload("functions.exec_command", {"cmd": "rm -f local.txt"}),
            self._payload("web.run", {"search_query": [{"q": "evidence"}]}),
            self._payload("collaboration.spawn_agent", {"task_name": "audit"}),
            self._payload("mcp__future__unknown_tool", {"operation": "provider-owned"}),
        )

        for raw_input in payloads:
            with self.subTest(raw_input=raw_input):
                worktree = WorktreeHookApplication().run(raw_input, {}, self.root)
                material_pre = MaterialActionRuntimeHookApplication().run(
                    "pre", raw_input, {}, self.root
                )
                material_post = MaterialActionRuntimeHookApplication().run(
                    "post",
                    self._with_response(raw_input),
                    {},
                    self.root,
                )

                self.assertEqual(0, worktree.exit_code)
                self.assertEqual(WorktreeHookDecisionCode.HOST_MANAGED, worktree.decision.code)
                self.assertEqual(0, material_pre.exit_code)
                self.assertEqual(
                    MaterialActionHookDecisionCode.HOST_MANAGED,
                    material_pre.decision.code,
                )
                self.assertEqual(0, material_post.exit_code)
                self.assertEqual(
                    MaterialActionHookDecisionCode.HOST_MANAGED,
                    material_post.decision.code,
                )


    def _payload(self, tool_name: str, tool_input: dict[str, object]) -> str:
        """한 PreToolUse fixture를 canonical JSON으로 만듭니다."""
        return json.dumps({
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_use_id": "authority-boundary-tool",
            "cwd": str(self.root),
            "tool_input": tool_input,
        })

    def _with_response(self, raw_input: str) -> str:
        """PreTool fixture에 성공 응답을 붙여 PostTool payload로 바꿉니다."""
        payload = json.loads(raw_input)
        payload["hook_event_name"] = "PostToolUse"
        payload["tool_response"] = {"status": "ok"}
        return json.dumps(payload)
