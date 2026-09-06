"""Monitor와 event ACK가 공유하는 GitHub check 정규화 규칙을 제공합니다."""

from __future__ import annotations

from typing import ClassVar


class CheckSummary:
    """CheckRun과 StatusContext를 같은 failed/pending 의미로 정규화합니다."""

    _BLOCKING_CHECK_CONCLUSIONS: ClassVar[frozenset[str]] = frozenset({
        "ACTION_REQUIRED",
        "TIMED_OUT",
        "CANCELLED",
        "FAILURE",
        "STARTUP_FAILURE",
        "STALE",
    })
    _NON_BLOCKING_FAILURE_WORKFLOWS: ClassVar[set[str]] = {
        "Auto PR Code Review",
        "AI Review Auto Approve",
    }

    def __init__(self, checks: list[dict[str, object]]) -> None:
        """동일 이름의 최신 check만 남깁니다.

        Args:
            checks: GitHub statusCheckRollup 항목입니다.
        """
        self._checks = self._latest_by_name(checks)

    @property
    def failed_count(self) -> int:
        """실패한 blocking check 수를 반환합니다.

        Returns:
            실패로 정규화된 blocking check 수입니다.
        """
        return sum(1 for check in self._checks if self._failed(check))

    @property
    def pending_count(self) -> int:
        """아직 완료되지 않은 CheckRun 또는 StatusContext 수를 반환합니다.

        Returns:
            Pending으로 정규화된 check 수입니다.
        """
        return sum(1 for check in self._checks if self._pending(check))

    @property
    def ai_review_state(self) -> str:
        """최신 `ai-review` commit status state를 반환합니다.

        Returns:
            최신 `ai-review` state 또는 빈 문자열입니다.
        """
        for check in self._checks:
            name = self._str(check.get("context")) or self._str(check.get("name"))
            if name == "ai-review":
                return self._str(check.get("state"))
        return ""

    @property
    def actionable_fingerprint(self) -> list[dict[str, str]]:
        """Failed, pending, ai-review check의 stable delta fingerprint를 반환합니다.

        Returns:
            Check name/state/run timestamp를 name 순으로 정렬한 목록입니다.
        """
        rows: list[dict[str, str]] = []
        for index, check in enumerate(self._checks):
            name = (
                self._str(check.get("name"))
                or self._str(check.get("context"))
                or f"__anonymous_{index}"
            )
            if not (self._failed(check) or self._pending(check) or name == "ai-review"):
                continue
            rows.append({
                "name": name,
                "status": self._str(check.get("status")),
                "conclusion": self._str(check.get("conclusion")),
                "state": self._str(check.get("state")),
                "workflowName": self._str(check.get("workflowName")),
                "startedAt": self._str(check.get("startedAt")),
                "createdAt": self._str(check.get("createdAt")),
                "completedAt": self._str(check.get("completedAt")),
            })
        return sorted(rows, key=lambda row: row["name"])

    def _latest_by_name(self, checks: list[dict[str, object]]) -> list[dict[str, object]]:
        grouped: dict[str, dict[str, object]] = {}
        for index, check in enumerate(checks):
            name = (
                self._str(check.get("name"))
                or self._str(check.get("context"))
                or f"__anonymous_{index}"
            )
            previous = grouped.get(name)
            if previous is None or self._sort_key(check) >= self._sort_key(previous):
                grouped[name] = check
        return list(grouped.values())

    def _failed(self, check: dict[str, object]) -> bool:
        workflow_name = self._str(check.get("workflowName"))
        if workflow_name in self._NON_BLOCKING_FAILURE_WORKFLOWS:
            return False
        conclusion = self._str(check.get("conclusion"))
        state = self._str(check.get("state"))
        return conclusion in self._BLOCKING_CHECK_CONCLUSIONS or state in {"FAILURE", "ERROR"}

    def _pending(self, check: dict[str, object]) -> bool:
        status = self._str(check.get("status"))
        state = self._str(check.get("state"))
        return (bool(status) and status != "COMPLETED") or state in {"EXPECTED", "PENDING"}

    def _sort_key(self, check: dict[str, object]) -> str:
        return (
            self._str(check.get("startedAt"))
            or self._str(check.get("createdAt"))
            or self._str(check.get("completedAt"))
        )

    def _str(self, value: object) -> str:
        return value if isinstance(value, str) else ""
