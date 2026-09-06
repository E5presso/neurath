"""Runtime-bound harness incident lifecycle과 resolution receipt를 검증합니다."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.agent_harness import harness_incident as incident_module
from scripts.agent_harness.session_kernel import (
    HarnessIncidentStatus,
    SessionLocator,
    TransitionRejected,
)
from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver, StateHandle

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/agent_harness/harness_incident.py"


class HarnessIncidentTest(TestCase):
    """Incident가 caller path나 split writer 없이 exact session에서 전이되는지 검증합니다."""

    def test_application_writes_only_runtime_bound_session_state(self) -> None:
        """Application은 caller path 없이 exact runtime session projection만 갱신합니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            handle, application = self._application(worktree)

            incident = application.record(
                "monitor-loop-stopped",
                "approval 전에 monitor loop가 중단됨",
            )
            state = handle.inspect()

            self.assertEqual(HarnessIncidentStatus.OPEN, incident.status)
            self.assertEqual({incident.id}, set(state.incidents))
            self.assertFalse((worktree / ".process-state.json").exists())
            self.assertTrue(
                SessionLocator
                .from_worktree(worktree)
                .locate(handle.session_id)
                .process_state.is_file()
            )

    def test_cli_requires_runtime_identity_and_rejects_state_selector(self) -> None:
        """CLI는 runtime-owned identity만 수용하고 공개 `--state` selector를 제공하지 않습니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            self._application(worktree)

            missing_runtime = self._run_cli(
                worktree,
                {},
                "record",
                "--id",
                "missing-runtime",
                "--symptom",
                "identity가 없음",
            )
            selected_path = self._run_cli(
                worktree,
                {"CODEX_THREAD_ID": "incident-session"},
                "--state",
                str(worktree / "arbitrary.json"),
                "record",
                "--id",
                "selected-path",
                "--symptom",
                "caller가 path를 선택함",
            )

        self.assertEqual(2, missing_runtime.returncode)
        self.assertIn("runtime-owned session identity", missing_runtime.stderr)
        self.assertEqual(2, selected_path.returncode)
        self.assertIn("invalid choice", selected_path.stderr)

    def test_canonical_cli_entrypoint_uses_runtime_bound_application(self) -> None:
        """Canonical CLI는 runtime identity로 결속된 state만 변경합니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            handle, _application = self._application(worktree)

            result = self._run_cli(
                worktree,
                {"CODEX_THREAD_ID": "incident-session"},
                "record",
                "--id",
                "entrypoint-rule",
                "--symptom",
                "entrypoint failure",
            )
            payload = json.loads(result.stdout)
            state = handle.inspect()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("entrypoint-rule", payload["rule_id"])
        self.assertEqual(1, len(state.incidents))

    def test_records_then_resolves_incident_with_complete_evidence(self) -> None:
        """Resolve는 open occurrence에 root cause, durable fix, executed receipt를 원자 반영합니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            handle, application = self._application(worktree)
            command = self._commit_gate(worktree, "scripts/test_incident_gate.py")
            application.record("monitor-loop-stopped", "approval 전에 monitor loop가 중단됨")

            resolved = application.resolve(
                "monitor-loop-stopped",
                "terminal delivery 소비 여부를 확인하지 않음",
                ["scripts/test_incident_gate.py"],
                [command],
            )
            persisted = handle.inspect().incidents[resolved.id]

        self.assertEqual(HarnessIncidentStatus.RESOLVED, persisted.status)
        self.assertTrue(persisted.root_cause)
        self.assertEqual(("scripts/test_incident_gate.py",), persisted.harness_fix)
        self.assertEqual(1, len(persisted.regression_evidence))
        self.assertEqual(0, persisted.regression_evidence[0].exit_code)
        self.assertEqual(40, len(persisted.regression_evidence[0].head_sha))
        self.assertEqual(64, len(persisted.regression_evidence[0].output_sha256))

    def test_regression_command_does_not_inherit_parent_pythonpath(self) -> None:
        """Receipt command는 부모 hook의 import path가 아니라 target worktree를 검사합니다."""
        with TemporaryDirectory() as temporary_directory:
            fixture_root = Path(temporary_directory)
            worktree = fixture_root / "worktree"
            worktree.mkdir()
            foreign_root = fixture_root / "foreign"
            foreign_scripts = foreign_root / "scripts"
            foreign_scripts.mkdir(parents=True)
            (foreign_scripts / "__init__.py").write_text("", encoding="utf-8")
            self._initialize_worktree(worktree)
            command = self._commit_gate(worktree, "scripts/test_incident_gate.py")

            with patch.dict(os.environ, {"PYTHONPATH": str(foreign_root)}):
                receipt = incident_module.run_regression_commands(worktree, [command])[0]

        self.assertEqual(0, receipt["exit_code"])

    def test_regression_command_cannot_leave_worktree_or_index_mutation(self) -> None:
        """Passing regression도 unrelated bytes/index를 바꾸면 durable receipt를 얻지 못합니다."""
        sources = {
            "worktree": (
                "from pathlib import Path\n"
                "from unittest import TestCase\n\n"
                "class MutatingGateTest(TestCase):\n"
                "    def test_gate(self):\n"
                "        Path('unrelated.txt').write_text('changed\\n', encoding='utf-8')\n"
                "        self.assertTrue(True)\n"
            ),
            "index": (
                "import subprocess\n"
                "from unittest import TestCase\n\n"
                "class MutatingGateTest(TestCase):\n"
                "    def test_gate(self):\n"
                "        blob = subprocess.run(\n"
                "            ('git', 'hash-object', '-w', '--stdin'),\n"
                "            input=b'staged-only\\n', capture_output=True, check=True,\n"
                "        ).stdout.decode().strip()\n"
                "        subprocess.run(\n"
                "            ('git', 'update-index', '--cacheinfo', '100644', blob, 'unrelated.txt'),\n"
                "            check=True,\n"
                "        )\n"
                "        self.assertTrue(True)\n"
            ),
        }
        for kind, source in sources.items():
            with self.subTest(kind=kind), TemporaryDirectory() as temporary_directory:
                worktree = Path(temporary_directory)
                self._initialize_worktree(worktree)
                unrelated = worktree / "unrelated.txt"
                unrelated.write_text("before\n", encoding="utf-8")
                gate = worktree / f"scripts/test_{kind}_mutation.py"
                gate.parent.mkdir(parents=True, exist_ok=True)
                gate.write_text(source, encoding="utf-8")
                self._commit_path(worktree, unrelated, "add unrelated source")
                self._commit_path(worktree, gate, f"add {kind} mutation gate")
                command = f"{sys.executable} -m unittest {gate.relative_to(worktree)}"

                with self.assertRaisesRegex(
                    incident_module.HarnessIncidentValidationError,
                    "changed current repository bytes or index",
                ):
                    incident_module.run_regression_commands(worktree, [command])

    def test_records_then_escalates_incident_to_loop_owner(self) -> None:
        """Escalate는 수정 없이 handoff summary와 재현 command로 소유권을 이관합니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            _handle, application = self._application(worktree)
            application.record("typed-helper-denied", "공식 helper가 거부됨")

            escalated = application.escalate(
                "typed-helper-denied",
                "loop owner가 runtime adapter를 수정해야 함",
                ["uv run pytest scripts/agent_harness/tests -q"],
            )

        self.assertEqual(HarnessIncidentStatus.ESCALATED, escalated.status)
        self.assertEqual("loop owner가 runtime adapter를 수정해야 함", escalated.escalation_summary)
        self.assertEqual(
            ("uv run pytest scripts/agent_harness/tests -q",),
            escalated.reproduction_commands,
        )

    def test_rejects_escalation_with_blank_reproduction_command(self) -> None:
        """공백 재현 command만 있는 handoff는 label-only 회피이므로 거부합니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            _handle, application = self._application(worktree)
            application.record("typed-helper-denied", "공식 helper가 거부됨")

            with self.assertRaisesRegex(
                incident_module.HarnessIncidentValidationError,
                "reproduction command",
            ):
                application.escalate("typed-helper-denied", "이관 요약", ["   "])

    def test_concurrent_duplicate_open_record_keeps_one_occurrence(self) -> None:
        """같은 rule의 concurrent record는 optimistic retry 뒤 occurrence 하나만 남깁니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            handle, application = self._application(worktree)

            def record_once() -> str:
                """동시 record 하나가 commit됐는지 typed conflict를 받았는지 반환합니다."""
                try:
                    application.record("same-rule", "같은 결함")
                except TransitionRejected:
                    return "conflict"
                return "committed"

            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = sorted(executor.map(lambda _index: record_once(), range(2)))
            state = handle.inspect()

        self.assertEqual(["committed", "conflict"], outcomes)
        self.assertEqual(1, len(state.incidents))

    def test_concurrent_distinct_rules_preserve_every_occurrence(self) -> None:
        """서로 다른 rule의 concurrent optimistic transaction은 lost update 없이 모두 남습니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            handle, application = self._application(worktree)

            def record_rule(rule_id: str) -> str:
                """한 stable rule occurrence를 기록하고 committed identity를 반환합니다."""
                return str(application.record(rule_id, f"{rule_id} failure").id)

            with ThreadPoolExecutor(max_workers=2) as executor:
                occurrence_ids = tuple(executor.map(record_rule, ("rule-a", "rule-b")))
            state = handle.inspect()

        self.assertEqual(2, len(set(occurrence_ids)))
        self.assertEqual({"rule-a", "rule-b"}, {item.rule_id for item in state.incidents.values()})

    def test_records_new_occurrence_after_same_rule_is_resolved(self) -> None:
        """같은 stable rule도 이전 occurrence가 terminal이면 새 occurrence를 기록할 수 있습니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            handle, application = self._application(worktree)
            command = self._commit_gate(worktree, "scripts/test_incident_gate.py")
            first = application.record("recurring-rule", "첫 번째 실패")
            application.resolve(
                str(first.id),
                "첫 번째 원인",
                ["scripts/test_incident_gate.py"],
                [command],
            )

            second = application.record("recurring-rule", "두 번째 실패")
            state = handle.inspect()

        self.assertNotEqual(first.id, second.id)
        self.assertEqual(2, len(state.incidents))
        self.assertEqual(HarnessIncidentStatus.OPEN, state.incidents[second.id].status)

    def test_refreshes_resolved_receipt_after_later_commit(self) -> None:
        """Refresh는 stored command를 latest head에서 재실행해 receipt만 교체합니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            _handle, application = self._application(worktree)
            command = self._commit_gate(worktree, "scripts/test_incident_gate.py")
            recorded = application.record("refresh-rule", "receipt가 오래됨")
            original = application.resolve(
                str(recorded.id),
                "head가 바뀌어도 stored receipt를 그대로 사용함",
                ["scripts/test_incident_gate.py"],
                [command],
            )
            self._empty_commit(worktree, "later harness change")

            refreshed = application.refresh([str(recorded.id)])[0]

        self.assertEqual(original.id, refreshed.id)
        self.assertEqual(original.root_cause, refreshed.root_cause)
        self.assertNotEqual(
            original.regression_evidence[0].head_sha,
            refreshed.regression_evidence[0].head_sha,
        )
        self.assertTrue(refreshed.evidence_refreshed_at)

    def test_batch_refresh_executes_shared_regression_once(self) -> None:
        """여러 resolved occurrence의 batch refresh는 shared regression을 한 번만 실행합니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            _handle, application = self._application(worktree)
            command = self._commit_gate(worktree, "scripts/test_incident_gate.py")
            incidents = []
            for rule_id in ("rule-a", "rule-b"):
                recorded = application.record(rule_id, f"{rule_id} failure")
                incidents.append(
                    application.resolve(
                        str(recorded.id),
                        f"{rule_id} root cause",
                        ["scripts/test_incident_gate.py"],
                        [command],
                    )
                )
            self._empty_commit(worktree, "later harness change")

            with patch.object(
                incident_module,
                "run_regression_commands",
                wraps=incident_module.run_regression_commands,
            ) as regression:
                refreshed = application.refresh(
                    [str(incident.id) for incident in incidents],
                    [command],
                )

        self.assertEqual(1, regression.call_count)
        self.assertEqual(2, len(refreshed))
        self.assertEqual(
            refreshed[0].regression_evidence,
            refreshed[1].regression_evidence,
        )

    def test_rejects_refresh_for_open_or_missing_incident(self) -> None:
        """Refresh는 resolved lifecycle만 허용하며 open 또는 missing selector를 거부합니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            _handle, application = self._application(worktree)
            open_incident = application.record("open-rule", "아직 open")

            with self.assertRaises(TransitionRejected):
                application.refresh([str(open_incident.id)])
            with self.assertRaises(TransitionRejected):
                application.refresh(["missing-rule"])

    def test_supersedes_deleted_resolution_gate_without_erasing_audit_history(self) -> None:
        """Supersede는 previous evidence를 archive하고 검증된 replacement를 current로 만듭니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            _handle, application = self._application(worktree)
            old_command = self._commit_gate(worktree, "scripts/old_incident_gate.py")
            recorded = application.record("obsolete-gate", "gate가 낡음")
            resolved = application.resolve(
                str(recorded.id),
                "낡은 gate를 current로 간주함",
                ["scripts/old_incident_gate.py"],
                [old_command],
            )
            new_command = self._commit_gate(worktree, "scripts/new_incident_gate.py")

            superseded = application.supersede(
                str(resolved.id),
                ["scripts/new_incident_gate.py"],
                [new_command],
            )

        self.assertEqual(("scripts/new_incident_gate.py",), superseded.harness_fix)
        self.assertEqual(1, len(superseded.superseded_resolution_evidence))
        self.assertEqual(
            ("scripts/old_incident_gate.py",),
            superseded.superseded_resolution_evidence[0].harness_fix,
        )

    def test_rejects_supersede_for_open_incident(self) -> None:
        """Open occurrence는 resolution evidence가 없으므로 supersede할 수 없습니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            _handle, application = self._application(worktree)
            application.record("open-rule", "아직 open")
            command = self._commit_gate(worktree, "scripts/new_incident_gate.py")

            with self.assertRaises(TransitionRejected):
                application.supersede(
                    "open-rule",
                    ["scripts/new_incident_gate.py"],
                    [command],
                )

    def test_rejects_resolve_without_recorded_incident(self) -> None:
        """Record 없이 label만 지정한 resolve는 incident lifecycle을 생성하지 않습니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            _handle, application = self._application(worktree)
            command = self._commit_gate(worktree, "scripts/test_incident_gate.py")

            with self.assertRaises(TransitionRejected):
                application.resolve(
                    "missing-rule",
                    "원인",
                    ["scripts/test_incident_gate.py"],
                    [command],
                )

    def test_stop_validation_does_not_replay_exact_head_regression_receipt(self) -> None:
        """Stop validation은 resolve/refresh에서 생성한 exact-head receipt를 재실행하지 않습니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            handle, application = self._application(worktree)
            command = self._commit_gate(worktree, "scripts/test_incident_gate.py")
            recorded = application.record("stop-replay", "Stop이 command를 반복함")
            application.resolve(
                str(recorded.id),
                "Mutation과 validation이 모두 command를 실행함",
                ["scripts/test_incident_gate.py"],
                [command],
            )

            with patch.object(
                incident_module,
                "_execute_regression_command",
                side_effect=AssertionError("validation replayed regression"),
            ) as replay:
                incident_module.validate_harness_incidents(handle.inspect(), worktree)

        replay.assert_not_called()

    def test_stop_validation_rejects_open_and_accepts_escalated_incident(self) -> None:
        """Final validation은 open occurrence를 막고 complete loop-owner handoff는 허용합니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            handle, application = self._application(worktree)
            application.record("handoff-rule", "하네스 수정 소유가 아님")

            with self.assertRaisesRegex(
                incident_module.HarnessIncidentValidationError,
                "unresolved harness incident",
            ):
                incident_module.validate_harness_incidents(handle.inspect(), worktree)
            application.escalate(
                "handoff-rule",
                "loop owner가 수정함",
                ["uv run pytest scripts/agent_harness/tests -q"],
            )
            incident_module.validate_harness_incidents(handle.inspect(), worktree)

    def test_changed_fix_path_invalidates_ancestor_receipt(self) -> None:
        """Receipt 이후 current fix path가 바뀌면 ancestor receipt를 재사용하지 못합니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            command = self._commit_gate(worktree, "scripts/test_incident_gate.py")
            receipt = incident_module.run_regression_commands(worktree, [command])[0]
            gate = worktree / "scripts/test_incident_gate.py"
            gate.write_text(
                self._test_gate_source().replace("assertTrue", "assertEqual"), encoding="utf-8"
            )
            self._commit_path(worktree, gate, "change incident gate")

            with self.assertRaisesRegex(
                incident_module.HarnessIncidentValidationError,
                "fix path changed after regression receipt",
            ):
                incident_module.validate_resolution_evidence(
                    worktree,
                    ["scripts/test_incident_gate.py"],
                    [receipt],
                    replay_commands=False,
                )

    def test_unrelated_commit_keeps_unchanged_fix_receipt_valid(self) -> None:
        """Receipt 이후 fix path가 그대로면 unrelated commit은 evidence를 무효화하지 않습니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            command = self._commit_gate(worktree, "scripts/test_incident_gate.py")
            receipt = incident_module.run_regression_commands(worktree, [command])[0]
            subprocess.run(["git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/develop"], cwd=worktree, check=True)
            self._empty_commit(worktree, "unrelated change")

            incident_module.validate_resolution_evidence(
                worktree,
                ["scripts/test_incident_gate.py"],
                [receipt],
                replay_commands=False,
            )

    def test_rejects_help_zero_test_and_all_skipped_regression(self) -> None:
        """Help, zero-test, all-skipped 실행은 successful regression receipt가 아닙니다."""
        help_command = f"{sys.executable} -m unittest --help"
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            self._initialize_worktree(worktree)
            with self.assertRaisesRegex(
                incident_module.HarnessIncidentValidationError,
                "must execute checks",
            ):
                incident_module.run_regression_commands(worktree, [help_command])

        zero = subprocess.CompletedProcess(
            args=[sys.executable, "-m", "unittest"],
            returncode=0,
            stdout=b"",
            stderr=b"Ran 0 tests in 0.00s\n\nOK\n",
        )
        skipped = subprocess.CompletedProcess(
            args=[sys.executable, "-m", "unittest"],
            returncode=0,
            stdout=b"",
            stderr=b"Ran 3 tests in 0.00s\n\nOK (skipped=3)\n",
        )
        for result in (zero, skipped):
            with self.assertRaisesRegex(
                incident_module.HarnessIncidentValidationError,
                "executed zero tests",
            ):
                incident_module._require_effective_regression_result(
                    [sys.executable, "-m", "unittest"],
                    result,
                    "python -m unittest",
                )

    def test_passing_regression_with_some_skips_resolves_incident(self) -> None:
        """실제로 통과한 test가 하나라도 있으면 일부 skip이 섞인 receipt를 인정합니다."""
        result = subprocess.CompletedProcess(
            args=[sys.executable, "-m", "unittest"],
            returncode=0,
            stdout=b"",
            stderr=b"Ran 5 tests in 0.01s\n\nOK (skipped=2)\n",
        )

        incident_module._require_effective_regression_result(
            [sys.executable, "-m", "unittest"],
            result,
            "python -m unittest",
        )

    def test_rejects_arbitrary_allowlisted_namespace_module(self) -> None:
        """`scripts.*` namespace만 같은 arbitrary module은 deterministic gate가 아닙니다."""
        with self.assertRaisesRegex(
            incident_module.HarnessIncidentValidationError,
            "not an allowlisted Python test/check",
        ):
            incident_module._allowed_regression_arguments(
                "uv run python -m scripts.workspace_hooks.git"
            )

    def _application(
        self,
        worktree: Path,
        session_id: str = "incident-session",
    ) -> tuple[StateHandle, incident_module.HarnessIncidentApplication]:
        """Fixture runtime identity로 canonical session을 초기화하고 application을 만듭니다."""
        binding = RuntimeEnvironmentResolver().resolve({"CODEX_THREAD_ID": session_id})
        handle = StateHandle.initialize(SessionLocator.from_worktree(worktree), binding)
        return handle, incident_module.HarnessIncidentApplication(handle, worktree)

    def _initialize_worktree(self, worktree: Path) -> None:
        """Regression receipt용 isolated Git repository와 empty baseline을 초기화합니다."""
        environment = self._isolated_git_environment()
        subprocess.run(["git", "init", "--quiet"], cwd=worktree, env=environment, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Neurath Test",
                "-c",
                "user.email=neurath@example.com",
                "-c",
                "core.hooksPath=/dev/null",
                "commit",
                "--quiet",
                "--allow-empty",
                "-m",
                "test baseline",
            ],
            cwd=worktree,
            env=environment,
            check=True,
        )
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/develop", "HEAD"],
            cwd=worktree,
            env=environment,
            check=True,
        )

    def _commit_gate(self, worktree: Path, relative_path: str) -> str:
        """실제 unittest gate를 commit하고 allowlisted 실행 command를 반환합니다."""
        path = worktree / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._test_gate_source(), encoding="utf-8")
        self._commit_path(worktree, path, f"add {relative_path}")
        return f"{sys.executable} -m unittest {relative_path}"

    def _commit_path(self, worktree: Path, path: Path, message: str) -> None:
        """Fixture path를 current head에 commit합니다."""
        environment = self._isolated_git_environment()
        subprocess.run(["git", "add", str(path)], cwd=worktree, env=environment, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Neurath Test",
                "-c",
                "user.email=neurath@example.com",
                "-c",
                "core.hooksPath=/dev/null",
                "commit",
                "--quiet",
                "-m",
                message,
            ],
            cwd=worktree,
            env=environment,
            check=True,
        )

    def _empty_commit(self, worktree: Path, message: str) -> None:
        """Receipt ancestry 검증용 empty commit을 추가합니다."""
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Neurath Test",
                "-c",
                "user.email=neurath@example.com",
                "-c",
                "core.hooksPath=/dev/null",
                "commit",
                "--quiet",
                "--allow-empty",
                "-m",
                message,
            ],
            cwd=worktree,
            env=self._isolated_git_environment(),
            check=True,
        )

    def _run_cli(
        self,
        worktree: Path,
        runtime_environment: dict[str, str],
        *arguments: str,
    ) -> subprocess.CompletedProcess[str]:
        """Thin skill entrypoint를 isolated worktree와 explicit runtime identity에서 실행합니다."""
        environment = self._isolated_git_environment()
        for identity_key in (
            "NEURATH_AGENT_ACTOR_ID",
            "NEURATH_AGENT_RUNTIME",
            "NEURATH_AGENT_SESSION_ID",
            "CLAUDE_CODE_SESSION_ID",
            "CODEX_THREAD_ID",
        ):
            environment.pop(identity_key, None)
        environment.update(runtime_environment)
        environment["PYTHONPATH"] = str(ROOT)
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            cwd=worktree,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def _isolated_git_environment(self) -> dict[str, str]:
        """부모 hook의 repository-scoped Git context를 fixture에 전파하지 않습니다."""
        return {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_") and key != "PRE_COMMIT"
        }

    def _test_gate_source(self) -> str:
        """Fixture에서 실제 test 하나를 실행하는 deterministic gate source를 반환합니다."""
        return (
            "from unittest import TestCase\n\n"
            "class IncidentGateTest(TestCase):\n"
            "    def test_gate(self):\n"
            "        self.assertTrue(True)\n"
        )


class DeterministicGatePathTest(TestCase):
    """Harness fix path의 deterministic enforcement 분류를 검증합니다."""

    def test_accepts_deterministic_enforcement_surfaces(self) -> None:
        """Executable gate, machine contract, package pre-commit은 deterministic surface입니다."""
        for candidate in (
            ".agents/skills/contracts.json",
            ".pre-commit-config.yaml",
            "apps/backend/shared/.pre-commit-config.yaml",
            "scripts/agent_harness/checker.py",
            ".codex/hooks/check-worktree-isolation.sh",
            "scripts/agent_harness/harness_incident.py",
        ):
            with self.subTest(candidate=candidate):
                self.assertTrue(incident_module._is_deterministic_gate_path(Path(candidate)))

    def test_rejects_prose_only_harness_surfaces(self) -> None:
        """Prose rule, skill, product docs는 executable deterministic gate가 아닙니다."""
        for candidate in (
            ".agents/rules/behavioral.md",
            ".agents/skills/process-ticket/SKILL.md",
            "AGENTS.md",
            "docs/context/product-intent.md",
        ):
            with self.subTest(candidate=candidate):
                self.assertFalse(incident_module._is_deterministic_gate_path(Path(candidate)))
