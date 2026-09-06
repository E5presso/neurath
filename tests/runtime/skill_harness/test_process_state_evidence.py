"""Process-ticket evidence가 exact session workflow에 보존되는 CLI 계약입니다."""

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.agent_harness.session_kernel import SessionLocator, WorkflowId, WorkflowStarted
from scripts.agent_harness.skill_state_store import SkillStateStore
from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver, StateHandle
from scripts.agent_harness.worktree_registry import WorktreeIdentityResolver

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".agents/skills/process-ticket/scripts/process_state_evidence.py"


class ProcessStateEvidenceTest(TestCase):
    """Evidence helper의 runtime identity, validation, optimistic state mutation을 검증합니다."""

    def setUp(self) -> None:
        """독립 Git repository와 process-ticket workflow를 준비합니다."""
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.worktree = Path(self.directory.name)
        subprocess.run(
            ("git", "init", "--quiet", str(self.worktree)),
            check=True,
            capture_output=True,
            text=True,
        )
        self.locator = SessionLocator.from_worktree(self.worktree)
        self.worktree_id = str(WorktreeIdentityResolver().resolve(self.worktree).worktree_id)
        self.resolver = RuntimeEnvironmentResolver()
        self.session_id = "session-a"
        self.monitor_heartbeat = time.time()
        self.workflow_id = WorkflowId("process-ticket-42")
        self.handle = self._open_workflow(self.session_id, self.workflow_id)
        self.store = SkillStateStore(self.handle, self.workflow_id)

    def _open_workflow(self, session_id: str, workflow_id: WorkflowId) -> StateHandle:
        """Runtime root session에 active process-ticket workflow를 생성합니다."""
        binding = self.resolver.resolve({"CODEX_THREAD_ID": session_id})
        handle = StateHandle.initialize(self.locator, binding)
        handle.apply(
            WorkflowStarted(
                session_id=handle.session_id,
                workflow_id=workflow_id,
                owner_actor_id=handle.actor_id,
                kind="process-ticket",
                goal="Issue #42를 완료한다",
                payload={
                    "phase_run": {"phase": 5, "status": "active"},
                    "skill_state": {
                        "delegate_pending": {
                            "delegation_id": "delegation-1",
                            "target_actor_id": "codex:reviewer",
                        }
                    },
                },
                idempotency_key=f"workflow-started:{session_id}:{workflow_id}",
            )
        )
        return handle

    def _environment(self, session_id: str | None = None) -> dict[str, str]:
        """Inherited identity를 제거하고 test가 소유한 Codex session만 바인딩합니다."""
        environment = dict(os.environ)
        for key in (
            "CLAUDE_CODE_SESSION_ID",
            "CODEX_THREAD_ID",
            "NEURATH_AGENT_SESSION_ID",
            "NEURATH_AGENT_ACTOR_ID",
            "NEURATH_AGENT_RUNTIME",
        ):
            environment.pop(key, None)
        environment["CODEX_THREAD_ID"] = self.session_id if session_id is None else session_id
        current_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            str(ROOT) if not current_python_path else f"{ROOT}{os.pathsep}{current_python_path}"
        )
        return environment

    def _run(
        self,
        field: str,
        value_json: str,
        *,
        workflow_id: str | None = None,
        session_id: str | None = None,
        path_prefix: Path | None = None,
        extra_arguments: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        """Evidence helper를 runtime identity와 cwd만으로 실행합니다."""
        environment = self._environment(session_id)
        if path_prefix is not None:
            environment["PATH"] = f"{path_prefix}{os.pathsep}{environment.get('PATH', '')}"
        arguments = [
            sys.executable,
            str(SCRIPT),
            "--workflow-id",
            str(self.workflow_id) if workflow_id is None else workflow_id,
            "--field",
            field,
            "--value-json",
            value_json,
            *extra_arguments,
        ]
        return subprocess.run(
            arguments,
            cwd=self.worktree,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def _skill_state(self, store: SkillStateStore | None = None) -> dict[str, object]:
        """Canonical workflow의 current skill-state object를 반환합니다."""
        snapshot = self.store.read() if store is None else store.read()
        return dict(snapshot.skill_state)

    def _object(self, value: object, label: str) -> dict[str, object]:
        """Nested skill-state value가 string-keyed JSON object인지 검증합니다."""
        if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
            self.fail(f"{label} must be a string-keyed JSON object")
        return {str(key): entry for key, entry in value.items()}

    def _subscription(
        self,
        *,
        session_id: str | None = None,
        workflow_id: str | None = None,
        runtime_id: str = "monitor-runtime-7",
        worktree_id: str | None = None,
        observation_resource: object | None = None,
    ) -> dict[str, object]:
        """Session/workflow identity를 보존한 local monitor subscription을 만듭니다."""
        selected_session = self.session_id if session_id is None else session_id
        selected_workflow = str(self.workflow_id) if workflow_id is None else workflow_id
        selected_worktree_id = self.worktree_id if worktree_id is None else worktree_id
        selected_resource = (
            {
                "kind": "monitor-observation-cache",
                "worktree_id": selected_worktree_id,
            }
            if observation_resource is None
            else observation_resource
        )
        return {
            "provider": "local-pr-monitor",
            "repo": "octo/neurath",
            "pr_number": 7,
            "session_id": selected_session,
            "workflow_id": selected_workflow,
            "runtime_id": runtime_id,
            "worktree_id": selected_worktree_id,
            "observation_resource": selected_resource,
            "poll_interval_seconds": 30,
            "resume_adapter": "command",
            "pid": os.getpid(),
            "heartbeat_at_epoch": self.monitor_heartbeat,
            "last_seen": {"snapshot": {}},
        }

    def _write_monitor_state(
        self,
        *,
        session_id: str | None = None,
        workflow_id: str | None = None,
        runtime_id: str = "monitor-runtime-7",
        worktree_id: str | None = None,
    ) -> Path:
        """Live monitor가 남긴 session/workflow-bound runtime state를 작성합니다."""
        subscription = self._subscription(
            session_id=session_id,
            workflow_id=workflow_id,
            runtime_id=runtime_id,
            worktree_id=worktree_id,
        )
        path = self.worktree / ".monitor-pr/monitor-state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({
                "provider": subscription["provider"],
                "repo": subscription["repo"],
                "pr_number": subscription["pr_number"],
                "session_id": subscription["session_id"],
                "workflow_id": subscription["workflow_id"],
                "runtime_id": subscription["runtime_id"],
                "worktree_id": subscription["worktree_id"],
                "resume_adapter": subscription["resume_adapter"],
                "pid": os.getpid(),
                "heartbeat_at_epoch": self.monitor_heartbeat,
                "last_seen": subscription["last_seen"],
            }),
            encoding="utf-8",
        )
        return path

    def _write_fake_gh(self, payload: str) -> Path:
        """Invocation을 기록하고 고정 JSON을 반환하는 fake gh를 설치합니다."""
        bin_directory = self.worktree / "fake-bin"
        bin_directory.mkdir(exist_ok=True)
        gh = bin_directory / "gh"
        gh.write_text(
            "#!/usr/bin/env bash\n"
            f"printf '%s ' \"$@\" > {self.worktree / 'gh-args.txt'}\n"
            f"printf '%s' '{payload}'\n",
            encoding="utf-8",
        )
        gh.chmod(0o755)
        return bin_directory

    def test_sets_allowed_evidence_through_skill_state_optimistic_transaction(self) -> None:
        """Commit evidence는 workflow skill_state를 갱신하고 sibling namespace를 보존합니다."""
        before = self.store.read()

        result = self._run("commit_done", '{"sha":"abc","subject":"test"}')

        current = self.handle.inspect().workflows[self.workflow_id]
        saved = self._skill_state()
        commit_done = self._object(saved["commit_done"], "commit_done")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("abc", commit_done["sha"])
        self.assertIsInstance(saved["updated_at"], str)
        self.assertEqual(before.workflow_revision + 1, current.revision)
        self.assertEqual({"phase": 5, "status": "active"}, current.payload["phase_run"])
        self.assertEqual({"phase_run", "skill_state"}, set(current.payload))
        self.assertFalse((self.worktree / ".process-state.json").exists())

    def test_public_cli_has_no_state_path_or_repository_selector(self) -> None:
        """Public command는 cwd, runtime env, workflow ID 외 state path selector를 받지 않습니다."""
        source = SCRIPT.read_text(encoding="utf-8")

        result = self._run(
            "commit_done",
            "true",
            extra_arguments=("--state", ".process-state.json"),
        )

        self.assertEqual(2, result.returncode)
        self.assertNotIn("--state", source)
        self.assertNotIn(".process-state.json", source)
        self.assertNotIn("update_json_object", source)
        self.assertFalse((self.worktree / ".process-state.json").exists())

    def test_required_workflow_id_and_runtime_identity_fail_closed(self) -> None:
        """Workflow selector나 vendor session identity가 없으면 fallback 없이 거부합니다."""
        environment = self._environment()
        environment.pop("CODEX_THREAD_ID")
        missing_workflow = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--field",
                "commit_done",
                "--value-json",
                "true",
            ],
            cwd=self.worktree,
            env=self._environment(),
            capture_output=True,
            text=True,
            check=False,
        )
        missing_identity = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--workflow-id",
                str(self.workflow_id),
                "--field",
                "commit_done",
                "--value-json",
                "true",
            ],
            cwd=self.worktree,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(2, missing_workflow.returncode)
        self.assertEqual(2, missing_identity.returncode)
        current = self._skill_state()
        self.assertNotIn("commit_done", current)

    def test_same_workflow_id_in_two_sessions_is_strictly_isolated(self) -> None:
        """같은 workflow ID도 runtime session이 다르면 독립 state를 갱신합니다."""
        handle_b = self._open_workflow("session-b", self.workflow_id)
        store_b = SkillStateStore(handle_b, self.workflow_id)

        result = self._run(
            "commit_done",
            '{"sha":"session-b"}',
            session_id="session-b",
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("commit_done", self._skill_state())
        state_b = self._skill_state(store_b)
        commit_done_b = self._object(state_b["commit_done"], "session-b commit_done")
        self.assertEqual("session-b", commit_done_b["sha"])

    def test_rejects_reserved_delegate_owner_incident_and_ack_fields(self) -> None:
        """Delegate, owner, incident, ACK namespace는 generic evidence mutation으로 바꾸지 못합니다."""
        for field in (
            "delegate_pending",
            "delegate_completion",
            "harness_incidents",
            "agent_session",
            "monitor_event_ack",
        ):
            with self.subTest(field=field):
                result = self._run(field, "null")

            self.assertEqual(2, result.returncode)
            self.assertIn("reserved", result.stderr)
        current = self._skill_state()
        delegation = self._object(current["delegate_pending"], "delegate_pending")
        self.assertEqual("delegation-1", delegation["delegation_id"])

    def test_rejects_merged_evidence_without_registered_subscription(self) -> None:
        """등록된 monitor subscription 없이 merged receipt를 쓰지 못합니다."""
        result = self._run("merged", "true")

        self.assertEqual(2, result.returncode)
        self.assertIn("monitor_event_subscription", result.stderr)
        self.assertNotIn("merged", self._skill_state())

    def test_rejects_merged_evidence_when_github_pr_is_not_merged(self) -> None:
        """GitHub read-back이 MERGED가 아니면 current state를 보존합니다."""
        self.store.update({"monitor_event_subscription": self._subscription()})
        gh_bin = self._write_fake_gh('{"state":"OPEN","mergedAt":null,"mergeCommit":null}')

        result = self._run("merged", "true", path_prefix=gh_bin)

        self.assertEqual(2, result.returncode)
        self.assertIn("not merged", result.stderr)
        self.assertNotIn("merged", self._skill_state())

    def test_records_verified_merged_receipt_from_current_subscription(self) -> None:
        """등록된 PR의 MERGED read-back만 receipt로 optimistic commit합니다."""
        self.store.update({"monitor_event_subscription": self._subscription()})
        gh_bin = self._write_fake_gh(
            '{"state":"MERGED","mergedAt":"2026-07-14T00:00:00Z","mergeCommit":{"oid":"abc123"}}'
        )

        result = self._run("merged", "true", path_prefix=gh_bin)

        saved = self._skill_state()
        merged = self._object(saved["merged"], "merged")
        gh_args = (self.worktree / "gh-args.txt").read_text(encoding="utf-8")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("MERGED", merged["state"])
        self.assertEqual("octo/neurath", merged["repo"])
        self.assertEqual(7, merged["pr_number"])
        self.assertEqual("abc123", merged["merge_commit_oid"])
        self.assertIn("octo/neurath", gh_args)
        self.assertIn("7", gh_args)

    def test_external_merge_readback_conflict_requires_whole_command_retry(self) -> None:
        """External read-back 중 revision이 바뀌면 stale receipt를 재사용하지 않습니다."""
        self.store.update({"monitor_event_subscription": self._subscription()})
        bin_directory = self.worktree / "blocking-bin"
        bin_directory.mkdir()
        started = self.worktree / "gh-started"
        release = self.worktree / "gh-release"
        gh = bin_directory / "gh"
        gh.write_text(
            "#!/usr/bin/env bash\n"
            f": > {started}\n"
            f"while [[ ! -f {release} ]]; do sleep 0.01; done\n"
            "printf '%s' "
            '\'{"state":"MERGED","mergedAt":"2026-07-14T00:00:00Z",'
            '"mergeCommit":{"oid":"abc123"}}\'\n',
            encoding="utf-8",
        )
        gh.chmod(0o755)
        environment = self._environment()
        environment["PATH"] = f"{bin_directory}{os.pathsep}{environment.get('PATH', '')}"
        process = subprocess.Popen(
            (
                sys.executable,
                str(SCRIPT),
                "--workflow-id",
                str(self.workflow_id),
                "--field",
                "merged",
                "--value-json",
                "true",
            ),
            cwd=self.worktree,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 5
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(started.exists(), "fake GitHub read-back did not start")
        self.store.update({"push_done": {"sha": "concurrent"}})
        release.write_text("continue\n", encoding="utf-8")
        stdout, stderr = process.communicate(timeout=5)

        self.assertEqual("", stdout)
        self.assertEqual(2, process.returncode)
        self.assertIn("workflow changed", stderr)
        current = self._skill_state()
        self.assertNotIn("merged", current)
        self.assertEqual({"sha": "concurrent"}, current["push_done"])

    def test_rejects_monitor_subscription_without_matching_live_runtime(self) -> None:
        """Live runtime이 없거나 session/workflow identity가 다르면 등록을 거부합니다."""
        missing = self._run(
            "monitor_event_subscription",
            json.dumps(self._subscription()),
        )
        self._write_monitor_state(session_id="foreign-session")
        foreign = self._run(
            "monitor_event_subscription",
            json.dumps(self._subscription(session_id="foreign-session")),
        )

        self.assertEqual(2, missing.returncode)
        self.assertEqual(2, foreign.returncode)
        self.assertIn("session", foreign.stderr)
        self.assertNotIn("monitor_event_subscription", self._skill_state())

    def test_rejects_legacy_paths_and_mismatched_observation_resource(self) -> None:
        """Subscription은 path selector를 거부하고 opaque local resource identity만 허용합니다."""
        self._write_monitor_state()
        legacy = self._subscription()
        legacy["process_state_path"] = str(self.worktree / ".process-state.json")
        legacy["state_path"] = str(self.worktree / ".monitor-pr/monitor-state.json")
        rogue = self._subscription(
            observation_resource={
                "kind": "monitor-observation-cache",
                "worktree_id": "foreign-worktree",
            }
        )

        legacy_result = self._run(
            "monitor_event_subscription",
            json.dumps(legacy),
        )
        rogue_result = self._run(
            "monitor_event_subscription",
            json.dumps(rogue),
        )

        self.assertEqual(2, legacy_result.returncode)
        self.assertIn("legacy path", legacy_result.stderr)
        self.assertEqual(2, rogue_result.returncode)
        self.assertIn("observation resource", rogue_result.stderr)

    def test_records_monitor_subscription_with_session_workflow_runtime_readback(self) -> None:
        """Live runtime의 exact session/workflow route를 검증한 subscription만 저장합니다."""
        self._write_monitor_state()
        subscription = self._subscription()

        result = self._run(
            "monitor_event_subscription",
            json.dumps(subscription),
        )

        current = self._skill_state()
        saved = self._object(
            current["monitor_event_subscription"],
            "monitor_event_subscription",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(self.session_id, saved["session_id"])
        self.assertEqual(str(self.workflow_id), saved["workflow_id"])
        self.assertEqual("monitor-runtime-7", saved["runtime_id"])
        self.assertEqual(self.worktree_id, saved["worktree_id"])
        self.assertEqual(
            {
                "kind": "monitor-observation-cache",
                "worktree_id": self.worktree_id,
            },
            saved["observation_resource"],
        )
        self.assertEqual(7, saved["pr_number"])
        self.assertNotIn("process_state_path", saved)
        self.assertNotIn("state_path", saved)
        self.assertNotIn("worktree", saved)


if __name__ == "__main__":  # pragma: no cover - test entrypoint
    unittest.main()
