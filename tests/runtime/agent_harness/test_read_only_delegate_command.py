"""Read-only delegate shell allowlist 회귀 테스트입니다."""

import os
import shlex
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.agent_harness.read_only_delegate_command import ReadOnlyDelegateCommandValidator

SAFE_GIT_PREFIX = (
    "env -i PATH=/usr/bin:/bin HOME=/dev/null GIT_CONFIG_NOSYSTEM=1 "
    "GIT_CONFIG_GLOBAL=/dev/null GIT_OPTIONAL_LOCKS=0 GIT_PAGER=cat PAGER=cat "
    "git -c core.fsmonitor=false -c core.hooksPath=/dev/null "
    "-c log.showSignature=false"
)


class ReadOnlyDelegateCommandValidatorTest(TestCase):
    """Review delegate가 repository inspection 외 side effect를 만들지 못하게 합니다."""

    def setUp(self) -> None:
        """각 test에 stateless validator를 제공합니다."""
        self.validator = ReadOnlyDelegateCommandValidator()

    def test_owner_root_profile_accepts_inspection_chains(self) -> None:
        """Owner-root profile은 조회 체인·분기·pipeline·assert script를 허용합니다."""
        owner_validator = ReadOnlyDelegateCommandValidator(profile="owner-root")
        for command in (
            "git status --short --branch && git worktree list --porcelain",
            "if [ -f .agents/runs/run.json ]; then echo present; else echo missing; fi",
            'rg -n "a|b" scripts/skill_harness/phase_runner.py | head -n 260',
            ".agents/skills/process-ticket/scripts/assert_worktree_isolation.sh 59",
            (
                "sed -n '1,420p' .agents/skills/process-ticket/phases/phase-4-review.md "
                "&& rg --files .agents/rules | sort | rg 'python|docstring' "
                "&& sed -n '1,360p' .agents/rules/python-code.md 2>/dev/null || true"
            ),
            "python3 .agents/skills/process-ticket/scripts/delegate_state.py --help",
        ):
            with self.subTest(command=command):
                owner_validator.validate(command)

    def test_owner_root_profile_still_rejects_mutation_surfaces(self) -> None:
        """Owner-root profile도 redirection·mutation verb·substitution은 거부합니다."""
        owner_validator = ReadOnlyDelegateCommandValidator(profile="owner-root")
        for command in (
            "git status --short && touch marker.txt",
            "echo ok > result.txt",
            "git status --short && git commit -m x",
            "ls $(pwd)",
            "cat file.txt & rm file.txt",
            ".agents/skills/process-ticket/scripts/assert_worktree_isolation.sh 59 evil",
        ):
            with self.subTest(command=command), self.assertRaises(ValueError):
                owner_validator.validate(command)

    def test_delegate_profile_keeps_rejecting_chained_inspection(self) -> None:
        """기본 delegate profile은 체인·pipeline 완화를 받지 않습니다."""
        with self.assertRaises(ValueError):
            self.validator.validate("git status --short --branch && git worktree list")

    def test_accepts_repository_inspection_commands(self) -> None:
        """일반 reader와 격리된 Git inspection만 허용합니다."""
        for command in (
            f"{SAFE_GIT_PREFIX} status --ignore-submodules=all --short",
            (
                f"{SAFE_GIT_PREFIX} -C /tmp/worktree diff --ignore-submodules=all "
                "--no-ext-diff --no-textconv --check"
            ),
            "rg -n owner_session_id .codex",
            "sed -n 1,80p file.py",
        ):
            with self.subTest(command=command):
                self.validator.validate(command)

    def test_accepts_quoted_control_characters_in_read_only_patterns(self) -> None:
        """따옴표 안의 특수문자는 shell control이 아니라 검색 데이터다. 순수 조회를 막지 않는다."""
        for command in (
            'rg -n "->" apps',
            "grep 'a|b' file.py",
            'rg -n "a<b" .',
            "rg -n 'value & other' .codex",
            "rg -n 'a;b' scripts",
            "sed -n '/pattern/p' file.py",
            "sed -n /error/p file.py",
            r"sed -n '/a\/b/p' file.py",
        ):
            with self.subTest(command=command):
                self.validator.validate(command)

    def test_accepts_representative_read_only_reader_surface(self) -> None:
        """대표적인 read-only reader command를 허용 surface로 고정해 과잉 차단이 굳지 않게 한다."""
        for command in (
            "cat AGENTS.md",
            "head -40 scripts/agent_harness/checker.py",
            "tail -20 docs/glossary.md",
            "wc -l docs/glossary.md",
            "stat .pre-commit-config.yaml",
            "ls .agents/rules",
            "rg --files .agents",
            "rg -n owner_session_id .codex",
            "jq -r '.skills' .agents/skills/contracts.json",
        ):
            with self.subTest(command=command):
                self.validator.validate(command)

    def test_still_rejects_unquoted_control_even_after_quoting_relaxation(self) -> None:
        """따옴표 완화가 진짜 shell control이나 명령 치환을 열어주지 않는다."""
        for command in (
            "rg foo|grep bar",
            "cat a>b",
            "rg owner .; touch output",
            'cat "$(rm x)"',
            "cat `rm x`",
            "grep a file && rm x",
        ):
            with self.subTest(command=command), self.assertRaises(ValueError):
                self.validator.validate(command)

    def test_rejects_interpreters_shell_control_and_mutating_commands(self) -> None:
        """Arbitrary interpreter, in-place edit, GitHub write와 compound shell은 거부합니다."""
        for command in (
            'python -c \'open("output", "w").write("x")\'',
            "sh -c 'touch output'",
            "sed -i '' file.py",
            "sed 'w /tmp/delegate-output' AGENTS.md",
            "find . -delete",
            "git push origin HEAD",
            "git config core.bare true",
            "gh api -X POST repos/E5presso/neurath/issues/131/comments",
            "gh api repos/E5presso/neurath/issues/131 --method=PATCH --field=title=x",
            "gh pr comment 131 --body duplicate",
            "uv run python -m scripts.agent_harness.harness_incident --state .process-state.json",
            "uv run python -m pytest --junitxml=delegate-report.xml scripts/agent_harness/tests",
            "git diff --output=delegate.patch",
            "git status --short",
            "env GIT_OPTIONAL_LOCKS=0 git status --short",
            "uv run python -m unittest scripts.agent_harness.tests.test_checker",
            "uv run ruff check scripts",
            "uv run ruff check --no-cache --add-noqa scripts",
            "uv run ruff check --no-cache -o delegate-report.txt scripts",
            "uv run ruff check --no-cache -odelegate-report.txt scripts",
            "uv run ruff check --no-cache -o=delegate-report.txt scripts",
            "env GIT_OPTIONAL_LOCKS=0 git -C /tmp/worktree remote -v set-url origin https://example.invalid/new.git",
            "rg --hostname-bin=/tmp/delegate-command owner .",
            "rg --hostname-bin /tmp/delegate-command owner .",
            "env PYTHONDONTWRITEBYTECODE=1 python -m unittest arbitrary.module.callable",
            "env PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s /tmp",
            f"{SAFE_GIT_PREFIX} remote -v set-url origin https://example.invalid/new.git",
            f"{SAFE_GIT_PREFIX} show --format= --patch HEAD",
            f"{SAFE_GIT_PREFIX} config --get core.bare --add core.bare true",
            "rg owner . && touch output",
            "echo value > output",
        ):
            with self.subTest(command=command), self.assertRaises(ValueError):
                self.validator.validate(command)

    def test_isolated_git_command_suppresses_repository_configured_helpers(self) -> None:
        """허용된 Git read는 fsmonitor와 textconv helper를 실제로 실행하지 않습니다."""
        with TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "repository"
            repository.mkdir()
            marker = Path(temporary_directory) / "helper-ran"
            helper = Path(temporary_directory) / "helper.sh"
            helper.write_text(
                f"#!/bin/sh\n/usr/bin/touch {shlex.quote(str(marker))}\n",
                encoding="utf-8",
            )
            helper.chmod(0o755)
            foreign_git_dir = Path(temporary_directory) / "foreign.git"
            with patch.dict(
                os.environ,
                {
                    "GIT_DIR": str(foreign_git_dir),
                    "GIT_INDEX_FILE": str(Path(temporary_directory) / "foreign-index"),
                    "PRE_COMMIT": "1",
                },
            ):
                self._git(repository, "init", "-b", "develop")
            self.assertFalse(foreign_git_dir.exists())
            self._git(repository, "config", "user.email", "test@example.invalid")
            self._git(repository, "config", "user.name", "Neurath Harness Test")
            (repository / ".gitattributes").write_text(
                "*.bin diff=delegate-helper\n", encoding="utf-8"
            )
            (repository / "payload.bin").write_bytes(b"before\n")
            self._git(repository, "add", ".")
            self._git(repository, "commit", "-m", "seed")
            self._git(repository, "config", "core.fsmonitor", str(helper))
            self._git(repository, "config", "diff.delegate-helper.textconv", str(helper))

            status_command = f"{SAFE_GIT_PREFIX} status --ignore-submodules=all --short"
            show_command = (
                f"{SAFE_GIT_PREFIX} show --ignore-submodules=all --no-ext-diff "
                "--no-textconv --format= --patch HEAD"
            )
            for command in (status_command, show_command):
                self.validator.validate(command)
                result = subprocess.run(
                    shlex.split(command),
                    cwd=repository,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)

        self.assertFalse(marker.exists())

    def _git(self, repository: Path, *arguments: str) -> None:
        """Fixture repository에 setup Git command를 적용합니다.

        Args:
            repository: 임시 Git repository입니다.
            arguments: Git CLI 인자입니다.
        """
        subprocess.run(
            ["git", "-C", str(repository), *arguments],
            env={
                key: value
                for key, value in os.environ.items()
                if not key.startswith("GIT_") and key != "PRE_COMMIT"
            },
            text=True,
            capture_output=True,
            check=True,
        )
