"""훅 설치가 이전 훅을 보존하며 선택한 체크아웃에만 영향을 주는지 검증한다."""

import os
import signal
import subprocess
from pathlib import Path

import pytest

from tests.conftest import git, initialize_git
from tools.install_quality_hook import git_environment, install


def run_hook(hook, root, environment, timeout=5):
    process = subprocess.Popen(
        [str(hook)],
        cwd=root,
        env=environment,
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=5)
        raise
    return process.returncode


def test_worktree_hook_chains_existing_user_hook_and_is_idempotent(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    initialize_git(root)
    shared = root / ".git" / "hooks" / "pre-commit"
    shared.write_text('#!/bin/sh\nprintf previous >> "$HOOK_LOG"\n')
    shared.chmod(0o755)
    original = shared.read_bytes()
    linked = tmp_path / "linked"
    git(root, "worktree", "add", "-b", "feature", str(linked))
    hook = install(linked)
    assert install(linked) == hook
    assert shared.read_bytes() == original
    assert (
        subprocess.run(
            ["git", "-C", str(root), "config", "--get", "core.hooksPath"],
            capture_output=True,
            env=git_environment(),
        ).returncode
        == 1
    )
    assert git(linked, "config", "--get", "core.hooksPath") == str(hook.parent)
    executable = tmp_path / "bin"
    executable.mkdir()
    uv = executable / "uv"
    uv.write_text('#!/bin/sh\nprintf " quality:$*" >> "$HOOK_LOG"\n')
    uv.chmod(0o755)
    log = tmp_path / "log"
    environment = dict(
        os.environ, PATH=str(executable) + os.pathsep + os.environ["PATH"], HOOK_LOG=str(log)
    )
    assert run_hook(hook, linked, environment) == 0
    assert log.read_text() == "previous quality:run --locked pre-commit run --hook-stage pre-commit"


def test_custom_hooks_path_is_chained_without_overwriting_settings(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    initialize_git(root)
    custom = root / "custom-hooks"
    custom.mkdir()
    old = custom / "pre-commit"
    old.write_text("#!/bin/sh\nexit 7\n")
    old.chmod(0o755)
    git(root, "config", "--local", "core.hooksPath", "custom-hooks")
    hook = install(root)
    assert git(root, "config", "--local", "--get", "core.hooksPath") == "custom-hooks"
    assert old.read_text() == "#!/bin/sh\nexit 7\n"
    assert run_hook(hook, root, git_environment()) == 7


def test_existing_private_hook_directory_is_never_overwritten(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    initialize_git(root)
    private = root / ".git" / "neurath-quality-hooks"
    private.mkdir()
    marker = private / "user-file"
    marker.write_text("preserve")
    with pytest.raises(RuntimeError, match="overwrite"):
        install(root)
    assert marker.read_text() == "preserve"
    assert (
        subprocess.run(
            ["git", "-C", str(root), "config", "--get", "extensions.worktreeConfig"],
            capture_output=True,
            env=git_environment(),
        ).returncode
        == 1
    )


def test_precommit_and_required_runner_share_static_checks_without_nested_test_suites():
    root = Path(__file__).resolve().parents[1]
    assert (
        "uv run --locked python tools/quality.py" in (root / ".pre-commit-config.yaml").read_text()
    )
    for script in ("tools/quality.py", "tools/check.py"):
        assert '["tools/static_quality.py"]' in (root / script).read_text()
    assert (
        "uv run --locked python tools/check.py"
        in (root / ".github/workflows/check.yml").read_text()
    )


def test_inherited_git_hook_environment_cannot_redirect_installation(tmp_path, monkeypatch):
    caller = tmp_path / "caller"
    target = tmp_path / "target"
    for directory in (caller, target):
        directory.mkdir()
        initialize_git(directory)
    monkeypatch.setenv("GIT_DIR", str(caller / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(caller))
    monkeypatch.setenv("GIT_INDEX_FILE", str(caller / ".git" / "index"))
    hook = install(target)
    assert hook == target / ".git" / "neurath-quality-hooks" / "pre-commit"
    assert not (caller / ".git" / "neurath-quality-hooks").exists()


def test_hook_fixture_timeout_reaps_its_process_group(tmp_path):
    hook = tmp_path / "blocking-hook"
    hook.write_text("#!/bin/sh\nsleep 30 &\nwait\n")
    hook.chmod(0o755)
    with pytest.raises(subprocess.TimeoutExpired):
        run_hook(hook, tmp_path, git_environment(), timeout=0.1)


def test_required_runner_executes_full_suite_once_with_coverage_and_build_gates(monkeypatch):
    from tools import check

    calls = []
    monkeypatch.setattr(
        check.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs))
    )
    check.main()
    commands = [command for command, _ in calls]
    pytest = [command for command in commands if command[1:3] == ["-m", "pytest"]]
    assert len(pytest) == 1
    assert pytest[0][pytest[0].index("-n") + 1] == "auto"
    assert {"--maxprocesses=4", "--dist=worksteal"} <= set(pytest[0])
    assert {"--cov=src/neurath", "--cov-branch", "--cov-fail-under=100"} <= set(pytest[0])
    assert not any(
        argument.startswith("tests/") or argument in {"-k", "-m", "--ignore", "--deselect"}
        for argument in pytest[0][3:]
    )
    assert commands[0][1:] == ["tools/static_quality.py"]
    assert commands.index(pytest[0]) < next(
        i for i, command in enumerate(commands) if "tools/check_coverage.py" in command
    )
    assert commands[-1][1:3] == ["-m", "build"]
    assert all(options["check"] is True for _, options in calls)


def test_precommit_keeps_regression_tests_after_shared_static_checks(monkeypatch):
    from tools import quality, static_quality

    calls = []
    monkeypatch.setattr(quality.subprocess, "run", lambda command, **kwargs: calls.append(command))
    quality.main()
    assert calls[0][1:] == ["tools/static_quality.py"]
    assert len([command for command in calls if command[1:3] == ["-m", "pytest"]]) == 1
    assert calls[1][calls[1].index("-n") + 1] == "auto"
    assert {"--maxprocesses=4", "--dist=worksteal"} <= set(calls[1])
    assert {
        "tests/test_architecture.py",
        "tests/test_review_contracts.py",
        "tests/test_monitoring.py",
        "tests/test_coverage_gate.py",
    } <= set(calls[1])
    calls.clear()
    static_quality.main()
    assert all("pytest" not in command for command in calls)
    assert any("tools/architecture.py" in command for command in calls)
    assert any(command[1:3] == ["-m", "pyrefly"] for command in calls)


@pytest.mark.parametrize("failed_stage", [0, 1, 2])
def test_required_runner_stops_before_build_when_a_required_stage_fails(monkeypatch, failed_stage):
    from tools import check

    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        if len(calls) == failed_stage + 1:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(check.subprocess, "run", execute)
    with pytest.raises(subprocess.CalledProcessError):
        check.main()
    assert len(calls) == failed_stage + 1
    assert not any(command[1:3] == ["-m", "build"] for command in calls)
