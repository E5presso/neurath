"""Structured edit 정규화와 host authority 경계를 검증합니다."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.agent_harness.tool_action_parser import (
    ToolActionEffect,
    ToolActionParser,
    ToolActionPayloadError,
)


class ToolActionParserTest(TestCase):
    """Parser가 file path만 증명하고 host tool 의미는 해석하지 않는지 검증합니다."""

    def setUp(self) -> None:
        """격리된 target root와 stateless parser를 준비합니다."""
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.parser = ToolActionParser()

    def _payload(
        self,
        tool_name: str,
        tool_input: object,
        *,
        event: str = "PreToolUse",
        invocation_id: str = "tool-1",
        response: object = ...,
    ) -> str:
        payload: dict[str, object] = {
            "hook_event_name": event,
            "session_id": "session-1",
            "tool_name": tool_name,
            "tool_use_id": invocation_id,
            "cwd": str(self.root),
            "tool_input": tool_input,
        }
        if response is not ...:
            payload["tool_response"] = response
        return json.dumps(payload)

    def test_host_managed_tools_are_not_content_classified(self) -> None:
        """Shell, web, coordination과 unknown provider payload를 내용으로 분류하지 않습니다."""
        payloads = (
            self._payload("functions.exec_command", {"cmd": "rm -rf ./local"}),
            self._payload("Bash", {"command": "rg 'a|b;[c]' file"}),
            self._payload("Bash", {"command": "'unterminated"}),
            self._payload("web.run", {"search_query": [{"q": "evidence"}]}),
            self._payload("collaboration.spawn_agent", {"task_name": "review"}),
            self._payload("functions.write_stdin", {"session_id": 7, "chars": "any bytes"}),
            self._payload("mcp__future__unknown", {"opaque": True}),
        )

        for raw_input in payloads:
            with self.subTest(raw_input=raw_input):
                request = self.parser.parse_request(raw_input, self.root)
                self.assertIs(ToolActionEffect.HOST_MANAGED, request.effect)
                self.assertEqual((), request.targets)

    def test_multifile_patch_targets_match_the_material_ledger_order(self) -> None:
        """역순으로 쓴 다중 파일 패치도 ledger와 같은 canonical 순서로 정규화합니다."""
        patch_text = (
            "*** Begin Patch\n*** Add File: z.py\n+x=1\n*** Add File: a.py\n+y=1\n*** End Patch"
        )
        request = self.parser.parse_request(
            self._payload("apply_patch", {"input": patch_text}),
            self.root,
        )
        self.assertEqual((str(self.root / "a.py"), str(self.root / "z.py")), request.targets)

    def test_only_structured_edit_tools_are_material_mutations(self) -> None:
        """Structured edit tool만 repository material mutation이 됩니다."""
        target = self.root / "src/example.py"
        tools = (
            ("Edit", {"file_path": str(target)}),
            ("Write", {"file_path": str(target)}),
            ("NotebookEdit", {"notebook_path": str(target)}),
            ("functions.edit", {"file_path": str(target)}),
        )

        for tool_name, tool_input in tools:
            with self.subTest(tool_name=tool_name):
                request = self.parser.parse_request(
                    self._payload(tool_name, tool_input),
                    self.root,
                )
                self.assertIs(ToolActionEffect.MATERIAL_MUTATION, request.effect)
                self.assertEqual((str(target),), request.targets)

    def test_structured_edit_targets_are_exact_and_complete(self) -> None:
        """MultiEdit와 patch의 모든 literal target을 canonical 순서로 보존합니다."""
        first = self.root / "src/first.py"
        second = self.root / "src/second.py"
        multi = self.parser.parse_request(
            self._payload(
                "MultiEdit",
                {
                    "edits": [
                        {"file_path": str(first)},
                        {"file_path": str(second)},
                        {"file_path": str(first)},
                    ]
                },
            ),
            self.root,
        )
        patch = self.parser.parse_request(
            self._payload(
                "functions.apply_patch",
                {
                    "input": (
                        "*** Begin Patch\n"
                        "*** Update File: src/first.py\n"
                        "*** Move to: src/moved.py\n"
                        "*** Add File: src/added.py\n"
                        "*** Delete File: src/second.py\n"
                        "*** End Patch"
                    )
                },
            ),
            self.root,
        )

        self.assertEqual((str(first), str(second)), multi.targets)
        self.assertEqual(
            (
                str(self.root / "src/added.py"),
                str(first),
                str(self.root / "src/moved.py"),
                str(second),
            ),
            patch.targets,
        )

    def test_relative_targets_resolve_from_payload_workdir(self) -> None:
        """Relative target은 payload가 선언한 workdir에서 해석합니다."""
        workdir = self.root / "nested"
        request = self.parser.parse_request(
            self._payload(
                "Edit",
                {"file_path": "src/example.py", "workdir": str(workdir)},
            ),
            self.root,
        )

        self.assertEqual(workdir, request.workdir)
        self.assertEqual((str(workdir / "src/example.py"),), request.targets)

    def test_empty_structured_target_remains_unproven_for_downstream_denial(self) -> None:
        """Target이 없는 structured edit는 broad workdir authority로 추정하지 않습니다."""
        edit = self.parser.parse_request(self._payload("Edit", {}), self.root)
        patch = self.parser.parse_request(
            self._payload("apply_patch", {"input": "*** Begin Patch\n*** End Patch"}),
            self.root,
        )

        self.assertIs(ToolActionEffect.MATERIAL_MUTATION, edit.effect)
        self.assertEqual((), edit.targets)
        self.assertEqual((), patch.targets)

    def test_pre_and_post_payloads_bind_the_same_request(self) -> None:
        """PreTool과 PostTool receipt가 같은 request identity와 target에 결속됩니다."""
        target = self.root / "src/example.py"
        pre = self.parser.parse_request(
            self._payload("Edit", {"file_path": str(target)}),
            self.root,
        )
        post = self.parser.parse_result(
            self._payload(
                "Edit",
                {"file_path": str(target)},
                event="PostToolUse",
                response={"status": "ok"},
            ),
            self.root,
        )

        self.assertEqual("tool-1", pre.invocation_id)
        self.assertEqual(pre.request_digest, post.request.request_digest)
        self.assertEqual(pre.targets, post.request.targets)
        self.assertTrue(post.succeeded)
        self.assertEqual(
            hashlib.sha256(b'{"status":"ok"}').hexdigest(),
            post.output_digest,
        )

    def test_result_failure_and_duration_are_bounded(self) -> None:
        """실패와 duration은 raw output 없이 bounded receipt로 남습니다."""
        target = self.root / "src/example.py"
        failed = self.parser.parse_result(
            json.dumps({
                **json.loads(self._payload("Edit", {"file_path": str(target)})),
                "hook_event_name": "PostToolUse",
                "tool_response": {"error": "edit failed", "large": "x" * 10000},
                "duration_ms": 0,
            }),
            self.root,
        )
        denied = self.parser.parse_result(
            self._payload(
                "Edit",
                {"file_path": str(target)},
                event="PermissionDenied",
                response={"reason": "user denied"},
            ),
            self.root,
        )
        process = self.parser.parse_result(
            self._payload(
                "functions.exec_command",
                {"cmd": "false"},
                event="PostToolUse",
                response={"exit_code": 9},
            ),
            self.root,
        )

        self.assertFalse(failed.succeeded)
        self.assertEqual(0, failed.duration_milliseconds)
        self.assertFalse(denied.succeeded)
        self.assertFalse(process.succeeded)
        self.assertEqual(64, len(failed.output_digest))
        self.assertNotIn("large", failed.output_digest)

    def test_claude_duration_is_preserved_as_optional_bounded_runtime_telemetry(self) -> None:
        """Runtime duration은 raw output과 분리된 bounded integer receipt입니다."""
        target = self.root / "src/example.py"
        payload = json.loads(self._payload("Edit", {"file_path": str(target)}))
        payload.update({
            "hook_event_name": "PostToolUse",
            "tool_response": {"status": "ok"},
            "duration_ms": 83,
        })

        result = self.parser.parse_result(json.dumps(payload), self.root)

        self.assertEqual(83, result.duration_milliseconds)
        self.assertTrue(result.succeeded)

    def test_invalid_payloads_fail_closed(self) -> None:
        """Malformed identity, input과 telemetry는 canonical request를 만들지 못합니다."""
        invalid = (
            "[]",
            json.dumps({"tool_input": {}}),
            json.dumps({"tool_name": "Edit", "tool_input": []}),
            json.dumps({
                "tool_name": "Edit",
                "agent_id": "not valid",
                "tool_input": {"file_path": "src/example.py"},
            }),
            json.dumps({
                **json.loads(self._payload("Edit", {"file_path": "src/example.py"})),
                "duration_ms": -1,
                "tool_response": {"status": "ok"},
            }),
        )

        for raw_input in invalid[:4]:
            with self.subTest(raw_input=raw_input), self.assertRaises(ToolActionPayloadError):
                self.parser.parse_request(raw_input, self.root)
        with self.assertRaises(ToolActionPayloadError):
            self.parser.parse_result(invalid[4], self.root)

    def test_request_and_result_are_immutable(self) -> None:
        """Canonical request와 result는 생성 뒤 변경할 수 없습니다."""
        target = self.root / "src/example.py"
        request = self.parser.parse_request(
            self._payload("Edit", {"file_path": str(target)}),
            self.root,
        )
        result = self.parser.parse_result(
            self._payload(
                "Edit",
                {"file_path": str(target)},
                event="PostToolUse",
                response={"status": "ok"},
            ),
            self.root,
        )

        with self.assertRaises(AttributeError):
            request.effect = ToolActionEffect.HOST_MANAGED
        with self.assertRaises(AttributeError):
            result.succeeded = False


if __name__ == "__main__":
    raise SystemExit()
