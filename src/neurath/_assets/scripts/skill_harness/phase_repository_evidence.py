"""Repository identity and bounded test execution used by phase evidence validation."""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
from enum import IntEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from scripts.agent_harness.bounded_process import run_bounded_process


class RegressionNodeOutcome(IntEnum):
    """직접 실행한 pytest node의 의미 있는 test 결과와 실행 오류를 구분합니다."""

    PASS = 0
    """하나 이상의 testcase가 skip이나 오류 없이 통과했습니다."""

    FAILURE = 1
    """Test-call failure가 있으며 setup·collection 오류나 skip은 없습니다."""

    ERROR = 2
    """실행·수집·setup·skip 또는 결과 artifact 오류로 test 결과를 증명하지 못했습니다."""


class PhaseRepositoryEvidence:
    """Read live Git identity and execute bounded regression proof for one root."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def upstream_head(self) -> str:
        """현재 branch upstream의 live remote exact head를 반환합니다."""
        branch = self.git_read("branch", "--show-current")
        if not branch:
            return ""
        remote = self.git_read("config", "--get", f"branch.{branch}.remote")
        merge = self.git_read("config", "--get", f"branch.{branch}.merge")
        if not remote or not merge:
            return ""
        lines = self.git_read("ls-remote", "--exit-code", remote, merge).splitlines()
        if len(lines) != 1:
            return ""
        parts = lines[0].split()
        if len(parts) != 2 or parts[1] != merge:
            return ""
        return parts[0] if re.fullmatch(r"[0-9a-f]{40}", parts[0]) else ""

    def git_read(self, *args: str) -> str:
        """Repository에서 read-only Git 결과를 읽고 실패 시 빈 문자열을 반환합니다."""
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("GIT_")
        }
        result = subprocess.run(
            ["git", "-C", str(self._root), *args],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    def valid_regression_node(self, node: str) -> bool:
        """Repository 안의 exact executable pytest node인지 구조적으로 검증합니다."""
        node_path, separator, test_name = node.partition("::")
        candidate = (self._root / node_path).resolve()
        return bool(
            separator
            and "::test_" in f"::{test_name}"
            and node_path.startswith("scripts/")
            and candidate.is_relative_to(self._root)
            and candidate.is_file()
            and self._regression_node_exists(candidate, test_name)
        )

    def run_regression_node(self, node: str) -> RegressionNodeOutcome:
        """Node를 직접 실행하고 JUnit으로 test-call 결과와 실행 오류를 구분합니다."""
        try:
            with TemporaryDirectory(prefix="neurath-harness-pytest-") as directory:
                report_path = Path(directory) / "result.xml"
                result = run_bounded_process(
                    (
                        sys.executable,
                        "-m",
                        "pytest",
                        "-q",
                        node,
                        "--no-cov",
                        "-p",
                        "no:cacheprovider",
                        "-o",
                        "addopts=",
                        "--junitxml",
                        str(report_path),
                    ),
                    cwd=self._root,
                    timeout_seconds=120,
                    environment={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                )
                if result.returncode not in {0, 1}:
                    return RegressionNodeOutcome.ERROR
                report = ElementTree.parse(report_path)
                cases = tuple(report.iter("testcase"))
                if not cases or any(
                    case.find("error") is not None or case.find("skipped") is not None
                    for case in cases
                ):
                    return RegressionNodeOutcome.ERROR
                has_failure = any(case.find("failure") is not None for case in cases)
                if result.returncode == 0 and not has_failure:
                    return RegressionNodeOutcome.PASS
                if result.returncode == 1 and has_failure:
                    return RegressionNodeOutcome.FAILURE
        except OSError, ElementTree.ParseError:
            return RegressionNodeOutcome.ERROR
        return RegressionNodeOutcome.ERROR

    def _regression_node_exists(self, path: Path, node_name: str) -> bool:
        """Pytest node가 실제 test function 또는 class method를 가리키는지 확인합니다."""
        if path.suffix != ".py":
            return False
        parts = [part.split("[", 1)[0] for part in node_name.split("::") if part]
        if not parts or len(parts) > 2 or not parts[-1].startswith("test_"):
            return False
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except OSError, SyntaxError, UnicodeError:
            return False
        functions = (ast.FunctionDef, ast.AsyncFunctionDef)
        if len(parts) == 1:
            return any(isinstance(item, functions) and item.name == parts[0] for item in tree.body)
        class_name, method_name = parts
        return any(
            isinstance(item, ast.ClassDef)
            and item.name == class_name
            and any(
                isinstance(member, functions) and member.name == method_name for member in item.body
            )
            for item in tree.body
        )

    def head(self) -> str:
        """Git fixture가 있을 때 repository exact head를 반환합니다."""
        head = self.git_read("rev-parse", "HEAD")
        return head if re.fullmatch(r"[0-9a-f]{40}", head) else ""

    def worktree_sha(self) -> str:
        """HEAD와 ignored file을 뺀 tracked/untracked current bytes를 digest합니다."""
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("GIT_")
        }
        head_result = subprocess.run(
            ("git", "-C", str(self._root), "rev-parse", "HEAD"),
            capture_output=True,
            check=False,
            env=environment,
        )
        head = head_result.stdout.strip() if head_result.returncode == 0 else b""
        files_result = subprocess.run(
            (
                "git",
                "-C",
                str(self._root),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ),
            capture_output=True,
            check=False,
            env=environment,
        )
        if files_result.returncode != 0:
            return ""
        relative_paths = sorted(
            value.decode("utf-8", errors="surrogateescape")
            for value in files_result.stdout.split(b"\0")
            if value and not value.startswith(b".agents/runs/")
        )
        digest = hashlib.sha256()
        digest.update(b"head\0" + head + b"\0")
        try:
            for relative_path in relative_paths:
                candidate = self._root / relative_path
                digest.update(relative_path.encode("utf-8", errors="surrogateescape") + b"\0")
                if candidate.is_symlink():
                    digest.update(b"symlink\0" + os.fsencode(candidate.readlink()) + b"\0")
                elif candidate.is_file():
                    executable = b"x" if candidate.stat().st_mode & 0o111 else b"-"
                    digest.update(b"file\0" + executable + b"\0" + candidate.read_bytes() + b"\0")
                elif candidate.exists():
                    digest.update(b"directory\0")
                else:
                    digest.update(b"missing\0")
        except OSError:
            return ""
        return digest.hexdigest()

    def contains_commit(self, merge_commit_oid: str) -> bool:
        """Merge commit이 local object database에 존재하는지 확인합니다."""
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("GIT_")
        }
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self._root),
                "cat-file",
                "-e",
                f"{merge_commit_oid}^{{commit}}",
            ],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
        return result.returncode == 0
