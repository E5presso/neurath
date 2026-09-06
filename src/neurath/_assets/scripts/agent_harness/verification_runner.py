"""Effectful repository checks를 closed command와 before/after readback으로 실행합니다."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

from scripts.agent_harness.harness_incident import (
    HarnessIncidentValidationError,
    HarnessRegressionExecutionError,
    run_regression_commands,
)
from scripts.agent_harness.repository_readback import (
    RepositoryReadbackError,
    RepositoryWorktreeReadback,
)


class VerificationRunnerError(RuntimeError):
    """Typed repository verification이 valid receipt를 만들지 못했음을 나타냅니다."""


class VerificationRequestInvalid(VerificationRunnerError):
    """Verifier kind, node 또는 repository target이 closed grammar와 다릅니다."""


class VerificationExecutionFailed(VerificationRunnerError):
    """Allowlisted verifier command가 실행 또는 결과 검증에 실패했습니다."""

    def __init__(
        self,
        reason: str,
        before: str,
        after: str,
        *,
        diagnostic_tail: str = "",
        output_sha256: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        """실행 실패와 mandatory after-readback identity를 함께 보존합니다.

        Args:
            reason: Bounded verifier failure 설명입니다.
            before: 실행 직전 repository fingerprint입니다.
            after: 실패 뒤 repository fingerprint입니다.
            diagnostic_tail: Durable state에 저장하지 않는 bounded process diagnostic입니다.
            output_sha256: 전체 process output의 optional SHA-256입니다.
            exit_code: Process가 시작된 경우의 optional nonzero exit code입니다.
        """
        super().__init__(reason)
        self.before = before
        """Verifier 실행 직전 repository fingerprint입니다."""
        self.after = after
        """실패한 verifier 종료 뒤 repository fingerprint입니다."""
        self.diagnostic_tail = diagnostic_tail
        """Durable state에 저장하지 않는 capped transient process diagnostic입니다."""
        self.output_sha256 = output_sha256
        """전체 process output의 optional SHA-256 identity입니다."""
        self.exit_code = exit_code
        """Process가 시작된 경우의 optional nonzero exit code입니다."""

    @property
    def worktree_changed(self) -> bool:
        """Command failure와 별개로 repository bytes/index가 바뀌었는지 반환합니다.

        Returns:
            Before와 after fingerprint가 다르면 참입니다.
        """
        return self.before != self.after

    def to_payload(self) -> Mapping[str, object]:
        """CLI가 Red 진단과 repository conflict를 함께 반환할 bounded payload입니다.

        Returns:
            Raw output 없이 실패 identity와 bounded diagnostic을 담은 JSON-compatible 값입니다.
        """
        return {
            "schema": "neurath.verification-receipt.v1",
            "status": "failed",
            "error": type(self).__name__,
            "reason": str(self)[:512],
            "before_fingerprint": self.before,
            "after_fingerprint": self.after,
            "worktree_changed": self.worktree_changed,
            "exit_code": self.exit_code,
            "output_sha256": self.output_sha256,
            "diagnostic_tail": self.diagnostic_tail,
        }


class VerificationWorktreeChanged(VerificationRunnerError):
    """Verifier 실행 중 current worktree bytes가 달라져 receipt 발행을 거부합니다."""

    def __init__(self, before: str, after: str) -> None:
        """충돌 전후 fingerprint를 bounded diagnostic으로 보존합니다.

        Args:
            before: Verifier 실행 직전 repository fingerprint입니다.
            after: Verifier 종료 직후 repository fingerprint입니다.
        """
        super().__init__("repository bytes changed during verification")
        self.before = before
        """Verifier 실행 직전 current worktree fingerprint입니다."""
        self.after = after
        """Verifier 종료 직후 current worktree fingerprint입니다."""

    def to_payload(self) -> Mapping[str, object]:
        """CLI가 repository change를 숨기지 않는 bounded failure payload를 반환합니다.

        Returns:
            Conflict 전후 fingerprint를 담은 JSON-compatible failure payload입니다.
        """
        return {
            "schema": "neurath.verification-receipt.v1",
            "status": "failed",
            "error": type(self).__name__,
            "reason": str(self),
            "before_fingerprint": self.before,
            "after_fingerprint": self.after,
            "worktree_changed": True,
        }


class VerificationKind(StrEnum):
    """Runner가 허용하는 closed repository verification entrypoint입니다."""

    PYTEST = "pytest"
    """하나 이상의 exact public pytest node를 실행합니다."""
    PRE_COMMIT = "pre-commit"
    """Exact all-files pre-commit entrypoint를 실행합니다."""
    CHECK = "check"
    """대상 프로젝트가 바인딩한 repository-wide check task를 실행합니다."""
    AGENT_HARNESS = "agent-harness"
    """Agent harness public CLI를 실행합니다."""
    DEPLOYMENT_HARNESS = "deployment-harness"
    """대상 프로젝트의 배포 검증를 실행합니다."""
    E2E_HARNESS = "e2e-harness"
    """Full-product e2e naming과 topology harness를 실행합니다."""
    FRONTEND_HARNESS = "frontend-harness"
    """Frontend stack과 scaffold harness를 실행합니다."""
    SKILL_HARNESS = "skill-harness"
    """Skill contract public CLI를 실행합니다."""
    STATIC_HARNESS = "static-harness"
    """Repository static-harness public CLI를 실행합니다."""
    HARNESS_LINT = "harness-lint"
    """Runtime wiring과 rule budget public lint를 실행합니다."""
    LOCAL_SURFACE_HARNESS = "local-surface-harness"
    """대상 프로젝트의 로컬 앱 검증를 실행합니다."""
    PACKAGE_CHECK = "package-check"
    """Affected package pre-commit orchestration을 all-package mode로 실행합니다."""
    WORKSPACE_HARNESS = "workspace-harness"
    """대상 프로젝트의 workspace 검증를 실행합니다."""


@dataclass(frozen=True, slots=True)
class VerificationRequest:
    """한 typed verifier invocation의 kind와 exact pytest node 집합입니다."""

    kind: VerificationKind
    """Closed verifier operation입니다."""
    nodes: tuple[str, ...] = ()
    """Pytest operation에만 허용되는 unique public node identity입니다."""

    _NODE_PATTERN = re.compile(
        r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_./-]+\.py::"
        r"(?:[A-Za-z_][A-Za-z0-9_]*::)?test_[A-Za-z0-9_]+"
    )

    def __post_init__(self) -> None:
        """Kind별 node cardinality와 shell-free identity를 검증합니다.

        Raises:
            TypeError: Kind가 closed enum이 아니면 발생합니다.
            VerificationRequestInvalid: Kind와 node cardinality 또는 identity가 다르면 발생합니다.
        """
        if not isinstance(self.kind, VerificationKind):
            raise TypeError("kind must be a VerificationKind")
        if self.kind is not VerificationKind.PYTEST:
            if self.nodes:
                raise VerificationRequestInvalid("only pytest accepts node arguments")
            return
        if not self.nodes or len(set(self.nodes)) != len(self.nodes):
            raise VerificationRequestInvalid("pytest requires unique public nodes")
        if any(self._NODE_PATTERN.fullmatch(node) is None for node in self.nodes):
            raise VerificationRequestInvalid(
                "pytest nodes must be canonical repository path and public test identities"
            )

    @property
    def commands(self) -> tuple[str, ...]:
        """Shell expansion 없는 exact regression command tuple을 반환합니다.

        Returns:
            Closed kind와 exact node에서 파생한 allowlisted command tuple입니다.
        """
        suffix = "".join(f" --node {node}" for node in self.nodes)
        return (f".neurath/run verify {self.kind.value}{suffix}",)



@dataclass(frozen=True, slots=True)
class VerificationReceipt:
    """Stable worktree에서 실제 실행된 verifier의 raw-free bounded receipt입니다."""

    kind: VerificationKind
    """실행한 closed verifier operation입니다."""
    worktree_fingerprint: str
    """실행 전후 동일했던 current repository byte identity입니다."""
    command_receipts: tuple[Mapping[str, object], ...]
    """Allowlisted runner가 발행한 command/head/output-digest receipt입니다."""

    def to_payload(self) -> Mapping[str, object]:
        """Raw stdout/stderr 없이 canonical JSON-compatible payload를 반환합니다.

        Returns:
            Stable worktree identity와 command receipt를 담은 JSON-compatible payload입니다.
        """
        return {
            "schema": "neurath.verification-receipt.v1",
            "status": "passed",
            "kind": self.kind.value,
            "worktree_fingerprint": self.worktree_fingerprint,
            "command_receipts": [dict(receipt) for receipt in self.command_receipts],
        }


ExecuteCommands = Callable[[Path, list[str]], list[dict[str, object]]]


class VerificationRunner:
    """Current repository에서 closed verifier를 실행하고 byte stability를 판정합니다."""

    def __init__(
        self,
        repository_root: Path,
        *,
        execute_commands: ExecuteCommands = run_regression_commands,
    ) -> None:
        """Exact Git root와 allowlisted command executor를 고정합니다.

        Args:
            repository_root: 검증할 exact Git worktree root입니다.
            execute_commands: Closed command를 실행하고 receipt를 만드는 executor입니다.
        """
        self._root = repository_root.resolve()
        self._readback = RepositoryWorktreeReadback(self._root)
        self._execute_commands = execute_commands

    def run(self, request: VerificationRequest) -> VerificationReceipt:
        """Request를 실행하고 unchanged current-worktree receipt만 발행합니다.

        Args:
            request: Closed kind와 optional exact pytest nodes입니다.

        Returns:
            실행 전후 repository fingerprint가 같은 raw-free receipt입니다.

        Raises:
            VerificationRequestInvalid: Pytest node가 current repository에 없으면 발생합니다.
            VerificationExecutionFailed: Command가 실패하거나 after readback을 만들 수 없으면 발생합니다.
            VerificationWorktreeChanged: 실행 중 repository bytes 또는 index가 바뀌면 발생합니다.
        """
        self._validate_nodes(request)
        before = self._readback.worktree_fingerprint()
        execution_error: HarnessIncidentValidationError | None = None
        command_receipts: list[dict[str, object]] = []
        try:
            command_receipts = self._execute_commands(self._root, list(request.commands))
        except HarnessIncidentValidationError as error:
            execution_error = error
        after = self._readback.worktree_fingerprint()
        if execution_error is not None:
            diagnostic_tail = ""
            output_sha256: str | None = None
            exit_code: int | None = None
            if isinstance(execution_error, HarnessRegressionExecutionError):
                diagnostic_tail = execution_error.diagnostic_tail
                output_sha256 = execution_error.output_sha256
                exit_code = execution_error.exit_code
            raise VerificationExecutionFailed(
                str(execution_error),
                before,
                after,
                diagnostic_tail=diagnostic_tail,
                output_sha256=output_sha256,
                exit_code=exit_code,
            ) from execution_error
        if before != after:
            raise VerificationWorktreeChanged(before, after)
        return VerificationReceipt(
            kind=request.kind,
            worktree_fingerprint=after,
            command_receipts=tuple(command_receipts),
        )

    def _validate_nodes(self, request: VerificationRequest) -> None:
        """Pytest node path가 exact current repository file인지 확인합니다."""
        for node in request.nodes:
            reference = node.split("::", maxsplit=1)[0]
            parsed = PurePosixPath(reference)
            if parsed.is_absolute() or ".." in parsed.parts or str(parsed) != reference:
                raise VerificationRequestInvalid("pytest node path must be canonical and relative")
            candidate = (self._root / reference).resolve()
            if not candidate.is_relative_to(self._root) or not candidate.is_file():
                raise VerificationRequestInvalid(
                    f"pytest node path does not exist in current repository: {reference}"
                )


class VerificationRunnerApplication:
    """Closed CLI argv를 request로 바꾸고 bounded JSON receipt 또는 error를 출력합니다."""

    def run(self, arguments: Sequence[str], repository_root: Path) -> int:
        """CLI arguments를 실행하고 process exit code를 반환합니다.

        Args:
            arguments: Closed argparse subcommand와 optional node arguments입니다.
            repository_root: 검증할 current repository root입니다.

        Returns:
            Passed receipt면 0, bounded failure payload면 2입니다.
        """
        try:
            request = self._request(arguments)
            receipt = VerificationRunner(repository_root).run(request)
        except (VerificationExecutionFailed, VerificationWorktreeChanged) as error:
            print(
                json.dumps(
                    error.to_payload(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            return 2
        except (VerificationRunnerError, RepositoryReadbackError) as error:
            payload = {
                "schema": "neurath.verification-receipt.v1",
                "status": "failed",
                "error": type(error).__name__,
                "reason": str(error)[:512],
            }
            print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            return 2
        print(
            json.dumps(
                receipt.to_payload(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0

    def _request(self, arguments: Sequence[str]) -> VerificationRequest:
        """Argparse surface를 closed typed request로 변환합니다."""
        parser = argparse.ArgumentParser(prog="verification_runner")
        subparsers = parser.add_subparsers(dest="kind", required=True)
        pytest_parser = subparsers.add_parser(VerificationKind.PYTEST.value)
        pytest_parser.add_argument("--node", action="append", required=True)
        for kind in VerificationKind:
            if kind is not VerificationKind.PYTEST:
                subparsers.add_parser(kind.value)
        namespace = parser.parse_args(list(arguments))
        kind = VerificationKind(namespace.kind)
        nodes = tuple(namespace.node) if kind is VerificationKind.PYTEST else ()
        return VerificationRequest(kind=kind, nodes=nodes)


def main() -> int:
    """Current working repository에서 CLI verification을 실행합니다.

    Returns:
        Verification application의 process exit code입니다.
    """
    return VerificationRunnerApplication().run(sys.argv[1:], Path.cwd())


if __name__ == "__main__":
    raise SystemExit(main())
