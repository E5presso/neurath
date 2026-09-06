"""Host adapters preserve raw tool outcomes and defer to portable authority gates."""

import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from neurath.hosts.hooks import hook


class MaterialActionHookWiringTest(TestCase):
    def setUp(self):
        restore = patch.dict(os.environ, dict(os.environ), clear=True)
        restore.start()
        self.addCleanup(restore.stop)
        paths = patch.object(sys, "path", list(sys.path))
        paths.start()
        self.addCleanup(paths.stop)

    def invoke(self, event, host="codex", response=None):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = {
                "hook_event_name": event,
                "cwd": temporary,
                "tool_name": "Write",
                "tool_input": {"file_path": str(root / "sample.txt"), "content": "raw"},
                "tool_response": response or {},
            }
            with patch(
                "scripts.agent_harness.material_action_runtime_hook.MaterialActionRuntimeHookApplication.run",
                return_value=SimpleNamespace(exit_code=2, stderr="verifier rejected"),
            ) as run:
                result = hook(root, host, json.dumps(payload), {})
                self.assertEqual(2, result[0])
                return run.call_args

    def test_pre_tool_wrapper_records_action_only_after_worktree_allow(self):
        with TemporaryDirectory() as temporary:
            with patch(
                "scripts.agent_harness.worktree_hook.WorktreeHookCommand.run_payload",
                return_value=(2, "{}", "claim denied"),
            ) as run:
                result = hook(
                    Path(temporary),
                    "codex",
                    json.dumps(
                        {
                            "hook_event_name": "PreToolUse",
                            "cwd": temporary,
                            "tool_name": "Write",
                            "tool_input": {
                                "file_path": str(Path(temporary) / "test.txt"),
                                "content": "x",
                            },
                        }
                    ),
                    {},
                )
                self.assertEqual(2, result[0])
                run.assert_called_once()
                self.assertFalse((Path(temporary) / "test.txt").exists())

    def test_post_tool_wrapper_preserves_nonzero_process_exit_shape(self):
        args = self.invoke("PostToolUse", response={"exit_code": 7})
        self.assertEqual(7, json.loads(args.args[1])["tool_response"]["exit_code"])

    def test_post_tool_preserves_target_content_without_language_normalization(self):
        args = self.invoke("PostToolUse")
        self.assertEqual("raw", json.loads(args.args[1])["tool_input"]["content"])

    def test_post_tool_propagates_material_validator_failure(self):
        args = self.invoke("PostToolUse")
        self.assertEqual("post", args.args[0])

    def test_codex_and_claude_share_one_structured_edit_post_tool_wrapper(self):
        self.assertEqual(
            self.invoke("PostToolUse", "codex").args[0],
            self.invoke("PostToolUse", "claude-code").args[0],
        )

    def test_claude_failure_event_uses_the_same_structured_edit_receipt_wrapper(self):
        self.assertEqual("post", self.invoke("PostToolUseFailure", "claude-code").args[0])

    def test_claude_permission_denial_terminalizes_the_unexecuted_invocation(self):
        self.assertEqual(
            "permission-denied", self.invoke("PermissionDenied", "claude-code").args[0]
        )

    def test_post_tool_wrapper_preserves_original_tool_failure_exit(self):
        args = self.invoke("PostToolUseFailure", "claude-code", {"exit_code": 42})
        self.assertEqual(42, json.loads(args.args[1])["tool_response"]["exit_code"])

    def test_runtime_wiring_limits_repository_gates_to_structured_edits(self):
        with TemporaryDirectory() as temporary:
            with patch(
                "scripts.agent_harness.worktree_hook.WorktreeHookCommand.run_payload"
            ) as run:
                result = hook(
                    Path(temporary),
                    "codex",
                    json.dumps(
                        {
                            "hook_event_name": "PreToolUse",
                            "cwd": temporary,
                            "tool_name": "Read",
                            "tool_input": {"file_path": "README.md"},
                        }
                    ),
                    {},
                )
                self.assertEqual(0, result[0])
                run.assert_not_called()
