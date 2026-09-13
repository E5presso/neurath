"""Host adapters preserve raw tool outcomes and defer to portable authority gates."""

import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
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

    def test_post_events_do_not_run_legacy_material_validation(self):
        for host, event in (("codex", "PostToolUse"), ("claude-code", "PostToolUse"),
                            ("claude-code", "PostToolUseFailure"), ("claude-code", "PermissionDenied")):
            with self.subTest(host=host, event=event), TemporaryDirectory() as temporary:
                root = Path(temporary)
                payload = {"hook_event_name": event, "cwd": temporary, "tool_name": "Write",
                           "tool_input": {"file_path": str(root / "sample.txt"), "content": "raw"},
                           "tool_response": {"exit_code": 7}}
                with patch("scripts.agent_harness.material_action_runtime_hook.MaterialActionRuntimeHookApplication.run",
                           side_effect=AssertionError("legacy material validator ran")):
                    self.assertEqual((0, {}, ""), hook(root, host, json.dumps(payload), {}))
                self.assertFalse((root / "sample.txt").exists())

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
