"""test app server resume 관련 타입과 실행 흐름을 정의합니다."""

import importlib.util
import json
import os
import signal
import subprocess
import sys
from argparse import Namespace
from collections.abc import Sequence
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Self
from unittest import TestCase
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
APP_SERVER_PATH = ROOT / ".agents/skills/monitor-pr/scripts/app_server_resume.py"
sys.path.insert(0, str(APP_SERVER_PATH.parent))
SPEC = importlib.util.spec_from_file_location("app_server_resume", APP_SERVER_PATH)
assert SPEC is not None
app_server_resume = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["app_server_resume"] = app_server_resume
SPEC.loader.exec_module(app_server_resume)


class AppServerResumeTest(TestCase):
    """skill contract와 phase runner enforcement 회귀 시나리오를 unittest fixture로 고정합니다."""

    def test_application_derives_thread_worktree_and_socket_from_runtime(self) -> None:
        """Public selector 없이 vendor session과 Git cwd를 exact app-server route로 묶습니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            subprocess.run(("git", "init", "-q", str(worktree)), check=True)

            args = app_server_resume.AppServerResumeApplication().resolve(
                (),
                {"CODEX_THREAD_ID": "owner-thread"},
                worktree,
            )

        self.assertEqual("owner-thread", args.thread_id)
        self.assertEqual(str(worktree.resolve()), args.cwd)
        self.assertEqual(
            worktree.resolve() / ".monitor-pr/app-server.sock",
            app_server_resume.resolve_socket_path(args),
        )

    def test_default_socket_path_is_worktree_local(self) -> None:
        """skill contract와 phase runner enforcement의 default socket path is worktree local 회귀 조건을 검증합니다."""
        with TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)

            socket_path = app_server_resume.default_socket_path(str(cwd))

        self.assertEqual(cwd.resolve() / ".monitor-pr/app-server.sock", socket_path)

    def test_public_cli_rejects_thread_worktree_and_socket_selectors(self) -> None:
        """App-server route authority는 runtime binding 밖에서 주입할 수 없습니다."""
        parser = app_server_resume.AppServerResumeApplication().parser()

        for option in ("--thread-id", "--cwd", "--socket-path"):
            with (
                self.subTest(option=option),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                parser.parse_args((option, "/tmp/foreign"))

    def test_ensure_app_server_records_managed_process_group(self) -> None:
        """새 worktree-local app-server는 restart 가능한 pid receipt를 남깁니다."""
        with TemporaryDirectory() as temporary_directory:
            socket_path = Path(temporary_directory) / "app-server.sock"
            process = Mock(pid=321)
            launch_options: dict[str, object] = {}

            def launch(*_args: object, **kwargs: object) -> Mock:
                """Fixture socket을 만들고 fake process를 반환합니다.

                Args:
                    _args: 사용하지 않는 Popen positional 인자입니다.
                    kwargs: 검증을 위해 보존할 Popen keyword 인자입니다.

                Returns:
                    고정 pid를 가진 fake process입니다.
                """
                launch_options.update(kwargs)
                socket_path.touch()
                return process

            with (
                patch("app_server_resume.subprocess.Popen", side_effect=launch),
                patch("app_server_resume.socket_accepts_connections", return_value=True),
            ):
                app_server_resume.ensure_app_server(socket_path, Path("/tmp/codex"))

            receipt = json.loads(
                app_server_resume.managed_app_server_pid_path(socket_path).read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(321, receipt["pid"])
        self.assertEqual(str(socket_path.resolve()), receipt["socket_path"])
        self.assertEqual(str(Path("/tmp/codex").resolve()), receipt["executable_path"])
        environment = launch_options["env"]
        self.assertIsInstance(environment, dict)
        assert isinstance(environment, dict)
        self.assertEqual("1", environment["NEURATH_MANAGED_APP_SERVER"])
        self.assertEqual(
            str(socket_path.resolve()),
            environment["NEURATH_MANAGED_APP_SERVER_SOCKET"],
        )

    def test_ensure_app_server_reaps_stale_managed_group_before_replacement(self) -> None:
        """죽은 listener의 기존 receipt를 새 pid로 덮기 전에 이전 group을 종료합니다."""
        with TemporaryDirectory() as temporary_directory:
            socket_path = Path(temporary_directory) / "app-server.sock"
            socket_path.touch()
            app_server_resume.write_managed_app_server_receipt(
                socket_path,
                321,
                Path("/tmp/codex"),
            )
            process = Mock(pid=654)

            def terminate(path: Path) -> None:
                """Fixture의 stale managed server artifact를 제거합니다.

                Args:
                    path: 제거할 fixture socket 경로입니다.
                """
                app_server_resume.cleanup_managed_app_server_paths(path)

            def launch(*_args: object, **_kwargs: object) -> Mock:
                """교체 listener socket과 fake process를 만듭니다.

                Args:
                    _args: 사용하지 않는 Popen positional 인자입니다.
                    _kwargs: 사용하지 않는 Popen keyword 인자입니다.

                Returns:
                    교체 pid를 가진 fake process입니다.
                """
                socket_path.touch()
                return process

            with (
                patch(
                    "app_server_resume.socket_accepts_connections",
                    side_effect=[False, True],
                ),
                patch(
                    "app_server_resume.terminate_managed_app_server",
                    side_effect=terminate,
                ) as terminate_group,
                patch("app_server_resume.subprocess.Popen", side_effect=launch),
            ):
                app_server_resume.ensure_app_server(socket_path, Path("/tmp/codex"))

            receipt = json.loads(
                app_server_resume.managed_app_server_pid_path(socket_path).read_text(
                    encoding="utf-8"
                )
            )

        terminate_group.assert_called_once_with(socket_path)
        self.assertEqual(654, receipt["pid"])

    def test_ensure_app_server_rejects_live_listener_without_receipt(self) -> None:
        """Connected socket도 managed identity receipt가 없으면 delivery에 재사용하지 않습니다."""
        with TemporaryDirectory() as temporary_directory:
            socket_path = Path(temporary_directory) / "app-server.sock"
            socket_path.touch()

            with (
                patch("app_server_resume.socket_accepts_connections", return_value=True),
                patch("app_server_resume.subprocess.Popen") as launch,
                self.assertRaisesRegex(RuntimeError, "receipt"),
            ):
                app_server_resume.ensure_app_server(socket_path, Path("/tmp/codex"))

        launch.assert_not_called()

    def test_ensure_app_server_reaps_group_when_listener_start_times_out(self) -> None:
        """Socket startup 실패도 새 process group과 receipt를 남기지 않습니다."""
        with TemporaryDirectory() as temporary_directory:
            socket_path = Path(temporary_directory) / "app-server.sock"
            process = Mock(pid=321)

            with (
                patch("app_server_resume.subprocess.Popen", return_value=process),
                patch("app_server_resume.time.time", side_effect=[0, 21]),
                patch("app_server_resume.terminate_managed_app_server") as terminate_group,
                self.assertRaisesRegex(RuntimeError, "socket unavailable"),
            ):
                app_server_resume.ensure_app_server(socket_path, Path("/tmp/codex"))

        terminate_group.assert_called_once_with(socket_path)

    def test_idle_managed_server_restarts_before_new_delivery(self) -> None:
        """Idle read-back 뒤 server group을 교체해 이전 turn subprocess를 제거합니다."""
        with TemporaryDirectory() as temporary_directory:
            socket_path = Path(temporary_directory) / "app-server.sock"
            app_server_resume.managed_app_server_pid_path(socket_path).write_text(
                '{"pid":321}',
                encoding="utf-8",
            )
            fake_client = FakeAppServerClient([
                {},
                {"thread": {"id": "thread-123", "status": {"type": "idle"}}},
                {},
                {"thread": {"id": "thread-123", "status": {"type": "idle"}}},
                {"turn": {"id": "turn-1"}},
                {
                    "method": "turn/completed",
                    "params": {"turn": {"id": "turn-1", "status": "completed"}},
                },
            ])
            args = Namespace(
                cwd=temporary_directory,
                socket_path=str(socket_path),
                thread_id="thread-123",
            )

            with (
                patch("app_server_resume.ensure_app_server"),
                patch("app_server_resume.select_codex_binary", return_value=Path("/tmp/codex")),
                patch("app_server_resume.AppServerClient", return_value=fake_client),
                patch("app_server_resume.restart_managed_app_server") as restart,
            ):
                result = app_server_resume.resume_thread(args, "event prompt")

        restart.assert_called_once_with(socket_path, Path("/tmp/codex"))
        self.assertEqual("completed", result["turn_completion"]["status"])
        self.assertEqual(
            1,
            [method for method, _ in fake_client.calls].count("turn/start"),
        )

    def test_terminate_managed_server_kills_exact_process_group(self) -> None:
        """Receipt와 command가 일치하면 orphan descendant를 포함한 group을 종료합니다."""
        with TemporaryDirectory() as temporary_directory:
            socket_path = Path(temporary_directory) / "app-server.sock"
            socket_path.touch()
            app_server_resume.write_managed_app_server_receipt(
                socket_path,
                321,
                Path("/tmp/codex"),
            )

            with (
                patch("app_server_resume.os.getpgid", return_value=321),
                patch("app_server_resume.managed_app_server_command_matches", return_value=True),
                patch(
                    "app_server_resume.kernel_process_executable",
                    return_value=Path("/tmp/codex"),
                ),
                patch("app_server_resume.process_owns_unix_socket", return_value=True),
                patch(
                    "app_server_resume.process_group_is_alive",
                    side_effect=[False, False],
                ),
                patch("app_server_resume.os.killpg") as kill_group,
            ):
                app_server_resume.terminate_managed_app_server(socket_path)

            receipt_exists = app_server_resume.managed_app_server_pid_path(socket_path).exists()
            socket_exists = socket_path.exists()

        kill_group.assert_called_once_with(321, signal.SIGTERM)
        self.assertFalse(receipt_exists)
        self.assertFalse(socket_exists)

    def test_terminate_managed_server_rejects_pid_reuse(self) -> None:
        """PID가 재사용돼 command identity가 다르면 다른 process group을 죽이지 않습니다."""
        with TemporaryDirectory() as temporary_directory:
            socket_path = Path(temporary_directory) / "app-server.sock"
            socket_path.touch()
            app_server_resume.write_managed_app_server_receipt(
                socket_path,
                321,
                Path("/tmp/codex"),
            )

            with (
                patch("app_server_resume.os.getpgid", return_value=321),
                patch("app_server_resume.managed_app_server_command_matches", return_value=False),
                patch("app_server_resume.os.killpg") as kill_group,
                self.assertRaisesRegex(RuntimeError, "process identity mismatch"),
            ):
                app_server_resume.terminate_managed_app_server(socket_path)

        kill_group.assert_not_called()

    def test_managed_server_identity_rejects_unrelated_argv_substring(self) -> None:
        """Exact socket 문자열을 argv에 포함한 unrelated interpreter를 Codex로 오인하지 않습니다."""
        socket_path = Path("/tmp/worktree/.monitor-pr/app-server.sock")
        expected_binary = Path("/Applications/Codex.app/Contents/Resources/codex")
        process = Mock(
            returncode=0,
            stdout=(f"python3 -c print('app-server --listen unix://{socket_path.resolve()}')"),
        )

        with patch("app_server_resume.subprocess.run", return_value=process):
            matches = app_server_resume.managed_app_server_command_matches(
                321,
                socket_path,
                expected_binary,
            )

        self.assertFalse(matches)

    def test_managed_server_identity_requires_exact_executable_and_arguments(self) -> None:
        """Receipt executable과 exact app-server argv가 모두 일치해야 process group을 소유합니다."""
        socket_path = Path("/tmp/worktree/.monitor-pr/app-server.sock")
        expected_binary = Path("/Applications/Codex.app/Contents/Resources/codex")
        process = Mock(
            returncode=0,
            stdout=(f"{expected_binary} app-server --listen unix://{socket_path.resolve()}"),
        )

        with patch("app_server_resume.subprocess.run", return_value=process):
            matches = app_server_resume.managed_app_server_command_matches(
                321,
                socket_path,
                expected_binary,
            )

        self.assertTrue(matches)

    def test_managed_server_identity_canonicalizes_socket_parent_alias(self) -> None:
        """Kernel과 argv가 같은 socket을 다른 parent alias로 표시해도 canonical identity입니다."""
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            real_parent = root / "real"
            real_parent.mkdir()
            alias_parent = root / "alias"
            alias_parent.symlink_to(real_parent, target_is_directory=True)
            socket_path = real_parent / "app-server.sock"
            expected_binary = Path("/Applications/Codex.app/Contents/Resources/codex")
            process = Mock(
                returncode=0,
                stdout=(
                    f"{expected_binary} app-server --listen "
                    f"unix://{alias_parent / 'app-server.sock'}"
                ),
            )

            with patch("app_server_resume.subprocess.run", return_value=process):
                matches = app_server_resume.managed_app_server_command_matches(
                    321,
                    socket_path,
                    expected_binary,
                )

        self.assertTrue(matches)

    def test_socket_ownership_canonicalizes_kernel_path_alias(self) -> None:
        """lsof path도 filesystem canonical path로 비교합니다."""
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            real_parent = root / "real"
            real_parent.mkdir()
            alias_parent = root / "alias"
            alias_parent.symlink_to(real_parent, target_is_directory=True)
            socket_path = real_parent / "app-server.sock"
            process = Mock(
                returncode=0,
                stdout=f"p321\nf7\nn{alias_parent / 'app-server.sock'}\n",
            )

            with (
                patch("app_server_resume.shutil.which", return_value="/usr/sbin/lsof"),
                patch("app_server_resume.subprocess.run", return_value=process),
            ):
                owns_socket = app_server_resume.process_owns_unix_socket(321, socket_path)

        self.assertTrue(owns_socket)

    def test_managed_server_identity_requires_kernel_executable_identity(self) -> None:
        """Spoof 가능한 argv0가 아니라 kernel이 보고한 executable이 receipt와 같아야 합니다."""
        with TemporaryDirectory() as temporary_directory:
            socket_path = Path(temporary_directory) / "app-server.sock"
            expected_binary = Path("/Applications/Codex.app/Contents/Resources/codex")
            app_server_resume.write_managed_app_server_receipt(
                socket_path,
                321,
                expected_binary,
            )

            with (
                patch("app_server_resume.os.getpgid", return_value=321),
                patch("app_server_resume.managed_app_server_command_matches", return_value=True),
                patch(
                    "app_server_resume.kernel_process_executable",
                    return_value=Path("/tmp/unrelated-sleeper"),
                ),
                patch("app_server_resume.process_owns_unix_socket", return_value=True),
                self.assertRaisesRegex(RuntimeError, "process identity mismatch"),
            ):
                app_server_resume.validate_managed_app_server_identity(socket_path)

    def test_managed_server_identity_requires_kernel_socket_ownership(self) -> None:
        """Exact command process가 receipt socket listener를 실제로 소유해야 합니다."""
        with TemporaryDirectory() as temporary_directory:
            socket_path = Path(temporary_directory) / "app-server.sock"
            expected_binary = Path("/Applications/Codex.app/Contents/Resources/codex")
            app_server_resume.write_managed_app_server_receipt(
                socket_path,
                321,
                expected_binary,
            )

            with (
                patch("app_server_resume.os.getpgid", return_value=321),
                patch("app_server_resume.managed_app_server_command_matches", return_value=True),
                patch(
                    "app_server_resume.kernel_process_executable",
                    return_value=expected_binary,
                ),
                patch("app_server_resume.process_owns_unix_socket", return_value=False),
                self.assertRaisesRegex(RuntimeError, "process identity mismatch"),
            ):
                app_server_resume.validate_managed_app_server_identity(socket_path)

    def test_process_group_liveness_ignores_zombie_only_group(self) -> None:
        """SIGTERM 뒤 zombie leader만 남은 group은 kill escalation 대상이 아닙니다."""
        process = Mock(returncode=0, stdout="321 Z\n321 Z+\n")

        with patch("app_server_resume.subprocess.run", return_value=process):
            is_alive = app_server_resume.process_group_is_alive(321)

        self.assertFalse(is_alive)

    def test_process_group_liveness_keeps_non_zombie_member(self) -> None:
        """같은 PGID에 실행 가능한 member가 있으면 group retirement를 계속 기다립니다."""
        process = Mock(returncode=0, stdout="321 Z\n321 S\n")

        with patch("app_server_resume.subprocess.run", return_value=process):
            is_alive = app_server_resume.process_group_is_alive(321)

        self.assertTrue(is_alive)

    def test_active_managed_server_is_not_restarted(self) -> None:
        """실행 중인 turn은 server group reset 대신 기존 pending-delivery를 유지합니다."""
        with TemporaryDirectory() as temporary_directory:
            socket_path = Path(temporary_directory) / "app-server.sock"
            app_server_resume.managed_app_server_pid_path(socket_path).write_text(
                '{"pid":321}',
                encoding="utf-8",
            )
            fake_client = FakeAppServerClient([
                {},
                {"thread": {"id": "thread-123", "status": {"type": "active"}}},
                {"data": [{"id": "turn-active", "status": "inProgress"}]},
            ])
            args = Namespace(
                cwd=temporary_directory,
                socket_path=str(socket_path),
                thread_id="thread-123",
            )

            with (
                patch("app_server_resume.ensure_app_server"),
                patch("app_server_resume.select_codex_binary", return_value=Path("/tmp/codex")),
                patch("app_server_resume.AppServerClient", return_value=fake_client),
                patch("app_server_resume.restart_managed_app_server") as restart,
            ):
                result = app_server_resume.resume_thread(args, "event prompt")

        restart.assert_not_called()
        self.assertEqual("pending-delivery", result["resume_status"])

    def test_dirty_owner_worktree_defers_before_server_delivery(self) -> None:
        """Owner 변경이 남아 있으면 별도 app-server turn을 시작하지 않습니다."""
        args = Namespace(
            cwd="/tmp/worktree",
            socket_path="/tmp/app.sock",
            thread_id="thread-123",
        )

        with (
            patch("app_server_resume.worktree_has_owner_changes", return_value=True),
            patch("app_server_resume.ensure_app_server") as ensure_server,
        ):
            result = app_server_resume.resume_thread(args, "event prompt")

        ensure_server.assert_not_called()
        self.assertEqual("pending-delivery", result["resume_status"])
        self.assertEqual("owner-worktree-dirty", result["delivery_method"])
        self.assertEqual("deferred", result["turn_completion"]["status"])

    def test_clean_unpublished_owner_head_defers_before_server_delivery(self) -> None:
        """Clean이어도 event HEAD보다 앞선 owner commit은 별도 turn delivery를 막습니다."""
        args = Namespace(
            cwd="/tmp/worktree",
            socket_path="/tmp/app.sock",
            thread_id="thread-123",
            expected_head_sha="remote-head",
        )

        with (
            patch("app_server_resume.worktree_has_owner_changes", return_value=False),
            patch(
                "app_server_resume.worktree_owner_head_state",
                return_value="local-ahead",
            ),
            patch("app_server_resume.ensure_app_server") as ensure_server,
        ):
            result = app_server_resume.resume_thread(args, "event prompt")

        ensure_server.assert_not_called()
        self.assertEqual("pending-delivery", result["resume_status"])
        self.assertEqual("owner-local-head-ahead", result["delivery_method"])
        self.assertEqual("deferred", result["turn_completion"]["status"])

    def test_worktree_owner_head_state_distinguishes_matching_and_local_ahead(self) -> None:
        """Exact event commit과 그 local descendant를 실제 Git graph로 구분합니다."""
        with TemporaryDirectory() as temporary_directory:
            worktree = Path(temporary_directory)
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("GIT_") and key != "PRE_COMMIT"
            }
            subprocess.run(
                ["git", "init", "-q", str(worktree)],
                env=environment,
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(worktree), "config", "user.email", "test@example.com"],
                env=environment,
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(worktree), "config", "user.name", "Test"],
                env=environment,
                check=True,
            )
            tracked = worktree / "tracked.txt"
            tracked.write_text("remote\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(worktree), "add", "tracked.txt"],
                env=environment,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(worktree),
                    "-c",
                    "core.hooksPath=/dev/null",
                    "commit",
                    "-qm",
                    "remote head",
                ],
                env=environment,
                check=True,
            )
            event_head = subprocess.run(
                ["git", "-C", str(worktree), "rev-parse", "HEAD"],
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

            matching = app_server_resume.worktree_owner_head_state(worktree, event_head)
            tracked.write_text("local\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(worktree), "add", "tracked.txt"],
                env=environment,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(worktree),
                    "-c",
                    "core.hooksPath=/dev/null",
                    "commit",
                    "-qm",
                    "local head",
                ],
                env=environment,
                check=True,
            )
            local_ahead = app_server_resume.worktree_owner_head_state(worktree, event_head)

        self.assertEqual("matching", matching)
        self.assertEqual("local-ahead", local_ahead)

    def test_select_codex_binary_prefers_explicit_current_binary(self) -> None:
        """skill contract와 phase runner enforcement의 select codex binary prefers explicit current binary 회귀 조건을 검증합니다."""
        with TemporaryDirectory() as tmpdir:
            codex = Path(tmpdir) / "codex"
            codex.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            codex.chmod(0o755)

            with patch.dict(os.environ, {"CODEX_APP_SERVER_BIN": str(codex)}):
                selected = app_server_resume.select_codex_binary()

        self.assertEqual(codex, selected)

    def test_select_codex_binary_prefers_app_assets_over_path_codex(self) -> None:
        """skill contract와 phase runner enforcement의 select codex binary prefers app bundle over path codex 회귀 조건을 검증합니다."""

        def executable(path: str, mode: int) -> bool:
            """요청을 처리해 호출자가 사용할 값을 반환합니다.

            Args:
                path: 호출자가 넘긴 path 값입니다.
                mode: 호출자가 넘긴 mode 값입니다.

            Returns:
                executable 처리 결과입니다."""
            return path == "/Applications/Codex.app/Contents/Resources/codex"

        with (
            patch.dict(os.environ, {"CODEX_APP_SERVER_BIN": ""}, clear=False),
            patch("app_server_resume.os.access", side_effect=executable),
            patch("app_server_resume.shutil.which", return_value="/opt/homebrew/bin/codex"),
        ):
            selected = app_server_resume.select_codex_binary()

        self.assertEqual(Path("/Applications/Codex.app/Contents/Resources/codex"), selected)

    def test_select_codex_binary_prefers_vscode_extension_over_app_assets(self) -> None:
        """skill contract와 phase runner enforcement의 select codex binary prefers vscode extension over app bundle 회귀 조건을 검증합니다."""
        with TemporaryDirectory() as tmpdir:
            extension_codex = (
                Path(tmpdir) / ".vscode/extensions/openai.chatgpt-test/bin/darwin-arm64/codex"
            )
            extension_codex.parent.mkdir(parents=True)
            extension_codex.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            extension_codex.chmod(0o755)

            def executable(path: str, mode: int) -> bool:
                """요청을 처리해 호출자가 사용할 값을 반환합니다.

                Args:
                    path: 호출자가 넘긴 path 값입니다.
                    mode: 호출자가 넘긴 mode 값입니다.

                Returns:
                    executable 처리 결과입니다."""
                return path in {
                    str(extension_codex),
                    "/Applications/Codex.app/Contents/Resources/codex",
                    "/opt/homebrew/bin/codex",
                }

            with (
                patch.dict(os.environ, {"CODEX_APP_SERVER_BIN": ""}, clear=False),
                patch("app_server_resume.Path.home", return_value=Path(tmpdir)),
                patch("app_server_resume.os.access", side_effect=executable),
                patch("app_server_resume.shutil.which", return_value="/opt/homebrew/bin/codex"),
            ):
                selected = app_server_resume.select_codex_binary()

        self.assertEqual(extension_codex, selected)

    def test_resume_thread_defers_when_target_thread_is_already_active(self) -> None:
        """Active turn에는 prompt를 섞지 않고 durable pending delivery로 보류합니다."""
        fake_client = FakeAppServerClient([
            {},
            {"thread": {"id": "thread-123", "status": {"type": "active"}}},
            {"data": [{"id": "turn-active", "status": "inProgress"}]},
        ])
        args = Namespace(cwd="/tmp/worktree", socket_path="/tmp/app.sock", thread_id="thread-123")

        with (
            patch("app_server_resume.ensure_app_server"),
            patch("app_server_resume.select_codex_binary", return_value=Path("/tmp/codex")),
            patch("app_server_resume.AppServerClient", return_value=fake_client),
        ):
            result = app_server_resume.resume_thread(args, "event prompt")

        self.assertEqual("pending-delivery", result["resume_status"])
        self.assertEqual("active-turn-deferred", result["delivery_method"])
        self.assertEqual("deferred", result["turn_completion"]["status"])
        self.assertEqual("turn-active", result["turn_completion"]["turnId"])
        self.assertNotIn("turn/start", [method for method, _ in fake_client.calls])
        self.assertNotIn("turn/steer", [method for method, _ in fake_client.calls])
        self.assertIn(("initialized", {}), fake_client.notifications)

    def test_resume_thread_starts_turn_when_target_thread_is_idle(self) -> None:
        """skill contract와 phase runner enforcement의 resume thread starts turn when target thread is idle 회귀 조건을 검증합니다."""
        fake_client = FakeAppServerClient([
            {},
            {"thread": {"id": "thread-123", "status": {"type": "idle"}}},
            {"turn": {"id": "turn-1"}},
            {
                "method": "turn/completed",
                "params": {"turn": {"id": "turn-1", "status": "completed"}},
            },
        ])
        args = Namespace(cwd="/tmp/worktree", socket_path="/tmp/app.sock", thread_id="thread-123")

        with (
            patch("app_server_resume.ensure_app_server"),
            patch("app_server_resume.select_codex_binary", return_value=Path("/tmp/codex")),
            patch("app_server_resume.AppServerClient", return_value=fake_client),
        ):
            result = app_server_resume.resume_thread(args, "event prompt")

        self.assertEqual("invoked", result["resume_status"])
        self.assertEqual("turn/start", result["delivery_method"])
        self.assertEqual("turn/start", fake_client.calls[-1][0])
        self.assertEqual("completed", result["turn_completion"]["status"])

    def test_resume_thread_defers_when_start_races_active_turn(self) -> None:
        """Idle read-back 뒤 active race가 나도 기존 turn에 prompt를 steer하지 않습니다."""
        fake_client = FakeAppServerClient([
            {},
            {"thread": {"id": "thread-123", "status": {"type": "idle"}}},
            RuntimeError("active turn already exists"),
            {"data": [{"id": "turn-race", "status": "inProgress"}]},
        ])
        args = Namespace(cwd="/tmp/worktree", socket_path="/tmp/app.sock", thread_id="thread-123")

        with (
            patch("app_server_resume.ensure_app_server"),
            patch("app_server_resume.select_codex_binary", return_value=Path("/tmp/codex")),
            patch("app_server_resume.AppServerClient", return_value=fake_client),
        ):
            result = app_server_resume.resume_thread(args, "event prompt")

        self.assertEqual("pending-delivery", result["resume_status"])
        self.assertEqual("active-turn-deferred", result["delivery_method"])
        self.assertEqual("turn-race", result["turn_completion"]["turnId"])
        self.assertEqual("deferred", result["turn_completion"]["status"])
        self.assertNotIn("turn/steer", [method for method, _ in fake_client.calls])

    def test_resume_thread_reports_pending_when_turn_does_not_complete(self) -> None:
        """skill contract와 phase runner enforcement의 resume thread reports pending when turn does not complete 회귀 조건을 검증합니다."""
        fake_client = FakeAppServerClient([
            {},
            {"thread": {"id": "thread-123", "status": {"type": "idle"}}},
            {"turn": {"id": "turn-1"}},
            TimeoutError(),
        ])
        args = Namespace(
            cwd="/tmp/worktree",
            socket_path="/tmp/app.sock",
            thread_id="thread-123",
            turn_timeout_seconds=1,
        )

        with (
            patch("app_server_resume.ensure_app_server"),
            patch("app_server_resume.select_codex_binary", return_value=Path("/tmp/codex")),
            patch("app_server_resume.AppServerClient", return_value=fake_client),
        ):
            result = app_server_resume.resume_thread(args, "event prompt")

        self.assertEqual("invoked", result["resume_status"])
        self.assertEqual("timeout", result["turn_completion"]["status"])
        self.assertEqual("turn-1", result["turn_completion"]["turnId"])

    def test_resume_thread_uses_turn_list_when_completion_notification_is_missed(self) -> None:
        """skill contract와 phase runner enforcement의 resume thread uses turn list when completion notification is missed 회귀 조건을 검증합니다."""
        fake_client = FakeAppServerClient([
            {},
            {"thread": {"id": "thread-123", "status": {"type": "idle"}}},
            {"turn": {"id": "turn-1"}},
            TimeoutError(),
            {"data": [{"id": "turn-1", "status": "completed"}]},
        ])
        args = Namespace(
            cwd="/tmp/worktree",
            socket_path="/tmp/app.sock",
            thread_id="thread-123",
            turn_timeout_seconds=1,
        )

        with (
            patch("app_server_resume.ensure_app_server"),
            patch("app_server_resume.select_codex_binary", return_value=Path("/tmp/codex")),
            patch("app_server_resume.AppServerClient", return_value=fake_client),
        ):
            result = app_server_resume.resume_thread(args, "event prompt")

        self.assertEqual("invoked", result["resume_status"])
        self.assertEqual("completed", result["turn_completion"]["status"])
        self.assertEqual("turn-1", result["turn_completion"]["turnId"])
        self.assertIn(
            ("thread/turns/list", {"threadId": "thread-123", "limit": 10}), fake_client.calls
        )

    def test_turn_from_list_treats_client_read_failures_as_missing_turn(self) -> None:
        """Turn list read 실패는 monitor recovery 자체를 중단시키지 않습니다."""
        args = Namespace(thread_id="thread-123")
        for error in (RuntimeError(), TimeoutError(), TypeError(), IndexError()):
            with self.subTest(error=type(error).__name__):
                fake_client = FakeAppServerClient([error])

                turn = app_server_resume.turn_from_list(fake_client, args, "turn-1")

                self.assertIsNone(turn)

    def test_inspect_turn_reads_status_without_start_or_steer(self) -> None:
        """Monitor retry inspector는 기존 turn을 조회할 뿐 prompt를 추가하지 않습니다."""
        fake_client = FakeAppServerClient([
            {},
            {"thread": {"id": "thread-123", "status": {"type": "active"}}},
            {"data": [{"id": "turn-active", "status": "inProgress"}]},
        ])
        args = Namespace(cwd="/tmp/worktree", socket_path="/tmp/app.sock", thread_id="thread-123")

        with (
            patch("app_server_resume.ensure_app_server"),
            patch("app_server_resume.select_codex_binary", return_value=Path("/tmp/codex")),
            patch("app_server_resume.AppServerClient", return_value=fake_client),
        ):
            result = app_server_resume.inspect_turn(args, "turn-active")

        self.assertEqual("observed", result["inspect_status"])
        self.assertEqual("inProgress", result["turn"]["status"])
        self.assertNotIn("turn/start", [method for method, _ in fake_client.calls])
        self.assertNotIn("turn/steer", [method for method, _ in fake_client.calls])

    def test_find_claimed_turn_reads_full_user_message_marker(self) -> None:
        """Crash recovery는 full turn history의 exact claim/event marker만 결속합니다."""
        marker = app_server_resume.monitor_delivery_marker("claim-1", "event-1")
        fake_client = FakeAppServerClient([
            {},
            {"thread": {"id": "thread-123", "status": {"type": "active"}}},
            {
                "data": [
                    {
                        "id": "turn-1",
                        "status": "inProgress",
                        "items": [
                            {
                                "id": "item-1",
                                "type": "userMessage",
                                "content": [{"type": "text", "text": f"{marker}\nwork"}],
                            }
                        ],
                    }
                ]
            },
        ])
        args = Namespace(cwd="/tmp/worktree", socket_path="/tmp/app.sock", thread_id="thread-123")

        with (
            patch("app_server_resume.ensure_app_server"),
            patch("app_server_resume.select_codex_binary", return_value=Path("/tmp/codex")),
            patch("app_server_resume.AppServerClient", return_value=fake_client),
        ):
            result = app_server_resume.find_claimed_turn(args, "claim-1", "event-1")

        self.assertEqual("found", result["recovery_status"])
        self.assertEqual("turn-1", result["turn"]["id"])
        self.assertIn(
            (
                "thread/turns/list",
                {"threadId": "thread-123", "limit": 20, "itemsView": "full"},
            ),
            fake_client.calls,
        )

    def test_find_claimed_turn_reports_idle_absence_without_starting_turn(self) -> None:
        """Idle history에 marker가 없으면 turn 미생성을 확정하고 prompt를 보내지 않습니다."""
        fake_client = FakeAppServerClient([
            {},
            {"thread": {"id": "thread-123", "status": {"type": "idle"}}},
            {"data": []},
        ])
        args = Namespace(cwd="/tmp/worktree", socket_path="/tmp/app.sock", thread_id="thread-123")

        with (
            patch("app_server_resume.ensure_app_server"),
            patch("app_server_resume.select_codex_binary", return_value=Path("/tmp/codex")),
            patch("app_server_resume.AppServerClient", return_value=fake_client),
        ):
            result = app_server_resume.find_claimed_turn(args, "claim-1", "event-1")

        self.assertEqual("absent", result["recovery_status"])
        self.assertEqual("idle", result["thread_status"])
        self.assertNotIn("turn/start", [method for method, _ in fake_client.calls])


class FakeAppServerClient:
    """fake app server client 관련 설정과 검증 조건을 함께 표현합니다."""

    def __init__(self, responses: Sequence[dict[str, object] | Exception]) -> None:
        """FakeAppServerClient 인스턴스가 skill contract와 phase runner enforcement 처리에 사용할 collaborator와 초기 상태를 보관합니다.

        Args:
            responses: 호출자가 넘긴 responses 값입니다."""
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.notifications: list[tuple[str, dict[str, object]]] = []

    def __enter__(self) -> Self:
        """FakeAppServerClient resource lifecycle을 열고 닫아 skill contract와 phase runner enforcement 실행 중 누수를 막습니다.

        Returns:
            enter 처리 결과입니다."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """FakeAppServerClient resource lifecycle을 열고 닫아 skill contract와 phase runner enforcement 실행 중 누수를 막습니다."""
        return

    def request(self, method: str, params: dict[str, object]) -> dict[str, object]:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Args:
            method: 호출자가 넘긴 method 값입니다.
            params: 호출자가 넘긴 params 값입니다.

        Returns:
            request 처리 결과입니다.

        Raises:
            입력 조합이나 외부 응답이 domain invariant와 맞지 않으면 예외를 발생시킵니다."""
        self.calls.append((method, params))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def notify(self, method: str, params: dict[str, object]) -> None:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Args:
            method: 호출자가 넘긴 method 값입니다.
            params: 호출자가 넘긴 params 값입니다."""
        self.notifications.append((method, params))

    def receive_message(self, _timeout_seconds: float) -> dict[str, object]:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Returns:
            receive message 처리 결과입니다.

        Raises:
            입력 조합이나 외부 응답이 domain invariant와 맞지 않으면 예외를 발생시킵니다."""
        if not self._responses:
            raise TimeoutError()
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
