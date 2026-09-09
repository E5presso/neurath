"""PR monitor가 GitHub delta를 exact session workflow mailbox에 전달합니다."""

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app_server_resume import monitor_delivery_marker
from monitor_check_summary import CheckSummary
from monitor_observation_store import MonitorObservationStore

from scripts.agent_harness.session_kernel import (
    DelegationStatus,
    SessionKernelError,
    SessionLocator,
    WorkflowId,
)
from scripts.agent_harness.skill_state_store import (
    SkillStateConflict,
    SkillStateRetryExhausted,
    SkillStateSnapshot,
    SkillStateStore,
)
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityError,
    StateHandle,
)
from scripts.agent_harness.worktree_registry import (
    CanonicalWorktreeIdentity,
    WorktreeIdentityResolver,
    WorktreeRegistryError,
)

DEFAULT_REVIEW_BOT_LOGINS = (
    "claude[bot]",
    "codex[bot]",
    "chatgpt-codex-connector[bot]",
    "github-actions[bot]",
    "review bot",
)
RUNTIME_SOURCE_PATHS = (
    Path(__file__),
    Path(__file__).with_name("monitor_check_summary.py"),
    Path(__file__).with_name("monitor_observation_store.py"),
    REPOSITORY_ROOT / "scripts/agent_harness/session_kernel.py",
    REPOSITORY_ROOT / "scripts/agent_harness/skill_state_store.py",
    REPOSITORY_ROOT / "scripts/agent_harness/state_handle.py",
)
NATIVE_TURN_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})


class MonitorEventIdentity:
    """GitHub occurrence를 delivery route와 분리해 식별합니다."""

    @classmethod
    def create(cls, payload: Mapping[str, object]) -> str:
        """Route와 무관한 stable SHA-256 event identity를 생성합니다.

        Args:
            payload: Monitor가 분류한 event payload입니다.

        Returns:
            Session, workflow, delivery 상태가 바뀌어도 유지되는 occurrence identity입니다.
        """
        identity = {
            key: payload.get(key)
            for key in (
                "monitor_event",
                "reason",
                "snapshot",
                "observation",
                "repo",
                "pr_number",
                "fingerprint",
                "staleHandledIds",
                "detected_change",
            )
        }
        serialized = json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode()).hexdigest()


class MonitorEvent:
    """monitor event 관련 설정과 검증 조건을 함께 표현합니다."""

    __slots__ = (
        "detected_change",
        "fingerprint",
        "kind",
        "observation",
        "reason",
        "snapshot",
        "stale_handled_ids",
    )

    def __init__(
        self,
        kind: str,
        reason: str,
        snapshot: dict[str, object],
        fingerprint: dict[str, object] | None = None,
        stale_handled_ids: tuple[str, ...] = (),
        observation: dict[str, object] | None = None,
        detected_change: dict[str, object] | None = None,
    ) -> None:
        """분류된 immutable monitor event를 생성합니다.

        Args:
            kind: Resume route가 해석할 monitor event 분류입니다.
            reason: Event가 발생한 정책상 원인입니다.
            snapshot: Event 판단에 사용한 GitHub 상태 snapshot입니다.
            fingerprint: 중복 occurrence를 판정할 stable identity 자료입니다.
            stale_handled_ids: 더 이상 current snapshot에 없는 처리 완료 ID입니다.
            observation: Sticky state delta 비교에 사용한 관측값입니다.
            detected_change: 직전 관측과 달라진 field만 담은 증거입니다.
        """
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "snapshot", dict(snapshot))
        object.__setattr__(self, "fingerprint", None if fingerprint is None else dict(fingerprint))
        object.__setattr__(self, "stale_handled_ids", tuple(stale_handled_ids))
        object.__setattr__(self, "observation", None if observation is None else dict(observation))
        object.__setattr__(
            self,
            "detected_change",
            None if detected_change is None else dict(detected_change),
        )

    def __setattr__(self, name: str, value: object) -> None:
        """생성 이후 event mutation을 거부합니다.

        Args:
            name: 변경을 시도한 event attribute 이름입니다.
            value: Immutable event에 새로 지정하려 한 값입니다.

        Raises:
            AttributeError: 생성 이후 event field를 변경하려 할 때 발생합니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")

    kind: str
    """kind 필드는 monitor event 분류와 resume payload 생성에 필요한 상태를 보관합니다."""
    reason: str
    """reason 필드는 monitor event 분류와 resume payload 생성에 필요한 상태를 보관합니다."""
    snapshot: dict[str, object]
    """snapshot 필드는 monitor event 분류와 resume payload 생성에 필요한 상태를 보관합니다."""
    fingerprint: dict[str, object] | None
    """fingerprint 필드는 monitor event 분류와 resume payload 생성에 필요한 상태를 보관합니다."""
    stale_handled_ids: tuple[str, ...]
    """stale_handled_ids 필드는 monitor event 분류와 resume payload 생성에 필요한 상태를 보관합니다."""
    observation: dict[str, object] | None
    """observation은 sticky GitHub state의 exact delta 비교 fingerprint입니다."""
    detected_change: dict[str, object] | None
    """detected_change는 직전 consumed observation과 달라진 field만 보관합니다."""

    def as_payload(self) -> dict[str, object]:
        """현재 객체 상태를 JSON 직렬화 가능한 dict로 변환합니다.

        Returns:
            as payload 처리 결과입니다."""
        payload: dict[str, object] = {
            "monitor_event": self.kind,
            "reason": self.reason,
            "source": "local-pr-monitor",
            "snapshot": self.snapshot,
        }
        if self.fingerprint is not None:
            payload["fingerprint"] = self.fingerprint
        if self.stale_handled_ids:
            payload["staleHandledIds"] = list(self.stale_handled_ids)
        if self.observation is not None:
            payload["observation"] = self.observation
        if self.detected_change:
            payload["detected_change"] = self.detected_change
        return payload


class CommentLedger:
    """comment ledger 관련 설정과 검증 조건을 함께 표현합니다."""

    def __init__(self, payload: dict[str, object]) -> None:
        """CommentLedger 인스턴스가 PR monitor resume와 GitHub 상태 수집 처리에 사용할 collaborator와 초기 상태를 보관합니다.

        Args:
            payload: 호출자가 넘긴 payload 값입니다."""
        self._payload = payload

    def as_payload(self) -> dict[str, dict[str, str]]:
        """현재 객체 상태를 JSON 직렬화 가능한 dict로 변환합니다.

        Returns:
            as payload 처리 결과입니다."""
        return {
            "ch1": self._rows("pull_comments", timestamp_key="updated_at"),
            "ch2": self._rows("issue_comments", timestamp_key="updated_at"),
            "ch3": self._review_rows(),
        }

    def stale_ids_since(self, previous: dict[str, object]) -> tuple[str, ...]:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Args:
            previous: 호출자가 넘긴 previous 값입니다.

        Returns:
            stale ids since 처리 결과입니다."""
        current = self.as_payload()
        stale_ids: list[str] = []
        for channel, rows in current.items():
            previous_rows = previous.get(channel, {})
            if not isinstance(previous_rows, dict):
                continue
            for row_id, updated_at in rows.items():
                previous_updated_at = previous_rows.get(row_id)
                if isinstance(previous_updated_at, str) and updated_at > previous_updated_at:
                    stale_ids.append(row_id)
        return tuple(sorted(stale_ids))

    def has_new_ids_since(self, previous: dict[str, object]) -> bool:
        """현재 상태로 권한 또는 lifecycle 조건 충족 여부를 판정합니다.

        Args:
            previous: 호출자가 넘긴 previous 값입니다.

        Returns:
            조건을 만족하면 True, 아니면 False를 반환합니다."""
        current = self.as_payload()
        for channel, rows in current.items():
            previous_rows = previous.get(channel, {})
            if not isinstance(previous_rows, dict):
                previous_rows = {}
            for row_id in rows:
                if row_id not in previous_rows:
                    return True
        return False

    def _rows(self, key: str, *, timestamp_key: str) -> dict[str, str]:
        rows: dict[str, str] = {}
        handled = self._handled_target_timestamps()
        for item in self._list_payload(key):
            if self._watch_comment(item):
                row_id = str(item.get("id", ""))
                timestamp = self._str(item.get(timestamp_key)) or self._str(item.get("created_at"))
                if row_id and timestamp and self._unhandled_or_stale(row_id, timestamp, handled):
                    rows[row_id] = timestamp
        return rows

    def _review_rows(self) -> dict[str, str]:
        rows: dict[str, str] = {}
        handled = self._handled_target_timestamps()
        for item in self._list_payload("reviews"):
            if self._review_signal(item):
                row_id = str(item.get("id", ""))
                timestamp = self._str(item.get("submitted_at"))
                if row_id and timestamp and self._unhandled_or_stale(row_id, timestamp, handled):
                    rows[row_id] = timestamp
        return rows

    def _handled_target_timestamps(self) -> dict[str, str]:
        handled: dict[str, str] = {}
        for key, timestamp_key in (
            ("pull_comments", "updated_at"),
            ("issue_comments", "updated_at"),
            ("reviews", "submitted_at"),
        ):
            for item in self._list_payload(key):
                body = self._str(item.get("body"))
                timestamp = self._str(item.get(timestamp_key)) or self._str(item.get("created_at"))
                for target_id in re.findall(r"<!-- claude-agent-reply to=([0-9]+) -->", body):
                    if timestamp > handled.get(target_id, ""):
                        handled[target_id] = timestamp
        return handled

    def _unhandled_or_stale(
        self,
        row_id: str,
        timestamp: str,
        handled: dict[str, str],
    ) -> bool:
        handled_at = handled.get(row_id)
        return handled_at is None or timestamp > handled_at

    def _list_payload(self, key: str) -> list[dict[str, object]]:
        value = self._payload.get(key, [])
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _review_signal(self, item: dict[str, object]) -> bool:
        state = self._str(item.get("state"))
        body = self._str(item.get("body"))
        return self._watch_comment(item) and state not in {"APPROVED", "DISMISSED"} and bool(body)

    def _watch_comment(self, item: dict[str, object]) -> bool:
        body = self._str(item.get("body"))
        login = self._login(item)
        if login in DEFAULT_REVIEW_BOT_LOGINS or login.endswith("[bot]"):
            return False
        if "<!-- claude-agent-reply" in body:
            return False
        if "<!-- ai-review verdict=" in body:
            return False
        if body.startswith((
            "AI review 결과:",
            "## AI review 결과:",
            "AI 리뷰 결과:",
            "## AI 리뷰 결과:",
        )):
            return False
        if body.startswith("ai-review status success verified for "):
            return False
        if body.startswith("ai-review status failure verified for "):
            return False
        if body.startswith("ai-review status pending verified for "):
            return False
        if "<!-- " in body and "linkback -->" in body:
            return False
        return login not in {"codecov", "codecov[bot]", "linear", "linear[bot]"}

    def _login(self, item: dict[str, object]) -> str:
        for key in ("user", "author"):
            user = item.get(key, {})
            if isinstance(user, dict) and self._str(user.get("login")):
                return self._str(user.get("login"))
        return ""

    def _str(self, value: object) -> str:
        return value if isinstance(value, str) else ""


class EventClassifier:
    """event classifier 관련 설정과 검증 조건을 함께 표현합니다."""

    def __init__(
        self,
        *,
        review_bot_logins: tuple[str, ...] = DEFAULT_REVIEW_BOT_LOGINS,
        require_review_bot_head_eval: bool = True,
    ) -> None:
        """EventClassifier 인스턴스가 PR monitor resume와 GitHub 상태 수집 처리에 사용할 collaborator와 초기 상태를 보관합니다.

        Args:
            review_bot_logins: 호출자가 넘긴 review bot logins 값입니다.
            require_review_bot_head_eval: 호출자가 넘긴 require review bot head eval 값입니다."""
        self._review_bot_logins = review_bot_logins
        self._require_review_bot_head_eval = require_review_bot_head_eval

    def classify(
        self,
        snapshot: dict[str, object],
        last_seen: dict[str, object],
    ) -> MonitorEvent | None:
        """입력값을 해석해 해당 경계의 처리 결과를 만듭니다.

        Args:
            snapshot: 호출자가 넘긴 snapshot 값입니다.
            last_seen: 호출자가 넘긴 last seen 값입니다.

        Returns:
            classify 처리 결과입니다."""
        pr = self._dict(snapshot.get("pr"))
        ledger = CommentLedger(snapshot)
        checks = CheckSummary(self._checks(pr))
        review_decision = self._str(pr.get("reviewDecision"))
        merge_state = self._str(pr.get("mergeStateStatus"))
        pr_state = self._str(pr.get("state"))
        head_oid = self._str(pr.get("headRefOid"))
        bot_evaluated_head = self._bot_evaluated_head(snapshot, checks, head_oid)
        summary = self.snapshot_summary(snapshot)
        previous_observation = self._previous_observation(last_seen)
        observation = self._observation(
            snapshot,
            checks=checks,
            bot_evaluated_head=bot_evaluated_head,
        )

        def classified_event(
            kind: str,
            reason: str,
            fingerprint: dict[str, object] | None = None,
            stale_handled_ids: tuple[str, ...] = (),
        ) -> MonitorEvent:
            """Current observation과 delta를 포함한 event를 만듭니다.

            Args:
                kind: Work 또는 terminal event kind입니다.
                reason: Monitor event reason입니다.
                fingerprint: Comment channel fingerprint입니다.
                stale_handled_ids: 다시 처리할 stale comment id입니다.

            Returns:
                Current observation과 changed field를 포함한 monitor event입니다.
            """
            detected_change = self._observation_delta(previous_observation, observation)
            if reason == "comments-changed":
                current_comments = ledger.as_payload()
                if current_comments != previous_comments:
                    detected_change["comments"] = {
                        "before": previous_comments,
                        "after": current_comments,
                    }
            return MonitorEvent(
                kind,
                reason,
                summary,
                fingerprint,
                stale_handled_ids,
                observation,
                detected_change,
            )

        if pr_state == "MERGED":
            if self._repeated_terminal(last_seen, "merged", summary):
                return None
            return classified_event("terminal", "merged")
        if pr_state == "CLOSED":
            if self._repeated_terminal(last_seen, "closed-without-merge", summary):
                return None
            return classified_event("terminal", "closed-without-merge")

        previous_comments = self._dict(last_seen.get("comments"))
        if (
            not previous_comments
            and not self._str(last_seen.get("reviewDecision"))
            and self._initial_mergeable_clean_terminal(
                ledger,
                checks,
                review_decision,
                merge_state,
                bot_evaluated_head,
                summary,
            )
        ):
            return classified_event("terminal", "mergeable-clean")

        if checks.failed_count > 0 and self._observation_changed(
            previous_observation,
            observation,
            "headRefOid",
            "failedChecks",
            "actionableChecks",
        ):
            return classified_event("event", "ci-failed")
        if merge_state == "DIRTY" and self._observation_changed(
            previous_observation,
            observation,
            "headRefOid",
            "mergeState",
        ):
            return classified_event("event", "merge-dirty")

        stale_ids = ledger.stale_ids_since(previous_comments)
        if ledger.has_new_ids_since(previous_comments) or stale_ids:
            return classified_event(
                "event",
                "comments-changed",
                {"comments": ledger.as_payload()},
                stale_ids,
            )
        if self._mergeable_clean_terminal(
            checks,
            review_decision,
            merge_state,
            bot_evaluated_head,
            summary,
        ):
            if self._repeated_terminal(last_seen, "mergeable-clean", summary):
                return None
            return classified_event("terminal", "mergeable-clean")
        if self._unresolved_review_thread_count(snapshot) > 0 and self._observation_changed(
            previous_observation,
            observation,
            "headRefOid",
            "unresolvedReviewThreads",
            "unresolvedReviewThreadIds",
        ):
            return classified_event("event", "review-blocked")
        return None

    def snapshot_summary(self, snapshot: dict[str, object]) -> dict[str, object]:
        """현재 GitHub snapshot의 wake 판단 필드를 정규화합니다.

        Args:
            snapshot: GitHub API에서 수집한 현재 PR snapshot입니다.

        Returns:
            merge, review, CI, head, review thread 상태의 정규화된 요약입니다.
        """
        pr = self._dict(snapshot.get("pr"))
        checks = CheckSummary(self._checks(pr))
        return {
            "mergeState": self._str(pr.get("mergeStateStatus")),
            "reviewDecision": self._str(pr.get("reviewDecision")),
            "failedChecks": checks.failed_count,
            "pendingChecks": checks.pending_count,
            "headRefOid": self._str(pr.get("headRefOid")),
            "unresolvedReviewThreads": self._unresolved_review_thread_count(snapshot),
        }

    def comment_fingerprint(self, snapshot: dict[str, object]) -> dict[str, object]:
        """현재 actionable comment ledger를 wake 비교용 fingerprint로 반환합니다.

        Args:
            snapshot: GitHub API에서 수집한 현재 PR snapshot입니다.

        Returns:
            세 comment channel의 미처리 항목 fingerprint입니다.
        """
        return {"comments": CommentLedger(snapshot).as_payload()}

    def last_seen_from_snapshot(self, snapshot: dict[str, object]) -> dict[str, object]:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Args:
            snapshot: 호출자가 넘긴 snapshot 값입니다.

        Returns:
            last seen from snapshot 처리 결과입니다."""
        pr = self._dict(snapshot.get("pr"))
        checks = CheckSummary(self._checks(pr))
        review_decision = self._str(pr.get("reviewDecision"))
        merge_state = self._str(pr.get("mergeStateStatus"))
        pr_state = self._str(pr.get("state"))
        head_oid = self._str(pr.get("headRefOid"))
        unresolved_threads = self._unresolved_review_thread_count(snapshot)
        terminal: dict[str, object] = {}
        summary: dict[str, object] = {
            "mergeState": merge_state,
            "reviewDecision": review_decision,
            "failedChecks": checks.failed_count,
            "pendingChecks": checks.pending_count,
            "headRefOid": head_oid,
            "unresolvedReviewThreads": unresolved_threads,
        }
        if pr_state == "MERGED":
            terminal = self._terminal_signature("merged", summary)
        elif pr_state == "CLOSED":
            terminal = self._terminal_signature("closed-without-merge", summary)
        elif (
            review_decision == "APPROVED"
            and merge_state in {"CLEAN", "UNSTABLE"}
            and checks.pending_count == 0
            and checks.failed_count == 0
            and unresolved_threads == 0
        ):
            terminal = self._terminal_signature("mergeable-clean", summary)
        return {
            "comments": CommentLedger(snapshot).as_payload(),
            "reviewDecision": review_decision,
            "headRefOid": head_oid,
            "observation": self._observation(
                snapshot,
                checks=checks,
                bot_evaluated_head=self._bot_evaluated_head(snapshot, checks, head_oid),
            ),
            "terminal": terminal,
        }

    def _observation(
        self,
        snapshot: dict[str, object],
        *,
        checks: CheckSummary,
        bot_evaluated_head: bool,
    ) -> dict[str, object]:
        """Sticky classifier가 ACK 뒤 같은 GitHub state를 재발행하지 않을 fingerprint를 만듭니다.

        Args:
            snapshot: GitHub API snapshot입니다.
            checks: 최신 이름별로 정규화한 check summary입니다.
            bot_evaluated_head: Review bot이 current head를 평가했는지 여부입니다.

        Returns:
            PR summary, actionable check identity, bot evaluation 상태입니다.
        """
        pr = self._dict(snapshot.get("pr"))
        return {
            **self.snapshot_summary(snapshot),
            "prState": self._str(pr.get("state")),
            "actionableChecks": checks.actionable_fingerprint,
            "botEvaluatedHead": bot_evaluated_head,
            "unresolvedReviewThreadIds": list(self._unresolved_review_thread_ids(snapshot)),
        }

    def _previous_observation(self, last_seen: dict[str, object]) -> dict[str, object]:
        """마지막으로 소비한 monitor observation을 반환합니다.

        Args:
            last_seen: Monitor가 마지막으로 소비한 state입니다.

        Returns:
            Delta 비교용 observation입니다.
        """
        return self._dict(last_seen.get("observation"))

    def _observation_changed(
        self,
        previous: dict[str, object],
        current: dict[str, object],
        *fields: str,
    ) -> bool:
        """지정한 actionable field 중 consumed observation 이후 delta가 있는지 판정합니다.

        Args:
            previous: 마지막 consumed observation입니다.
            current: 현재 GitHub observation입니다.
            fields: Event reason에 의미 있는 field 이름입니다.

        Returns:
            이전 observation이 없거나 하나 이상의 field가 달라졌으면 true입니다.
        """
        return not previous or any(previous.get(field) != current.get(field) for field in fields)

    def _observation_delta(
        self,
        previous: dict[str, object],
        current: dict[str, object],
    ) -> dict[str, object]:
        """직전 consumed observation과 달라진 field만 before/after로 반환합니다.

        Args:
            previous: 마지막 consumed observation입니다.
            current: 현재 GitHub observation입니다.

        Returns:
            Changed field별 before/after object입니다.
        """
        return {
            key: {"before": previous.get(key), "after": value}
            for key, value in current.items()
            if previous.get(key) != value
        }

    def _initial_mergeable_clean_terminal(
        self,
        ledger: CommentLedger,
        checks: CheckSummary,
        review_decision: str,
        merge_state: str,
        bot_evaluated_head: bool,
        summary: dict[str, object],
    ) -> bool:
        comment_rows = ledger.as_payload()
        no_pending_comments = all(not rows for rows in comment_rows.values())
        return no_pending_comments and self._mergeable_clean_terminal(
            checks,
            review_decision,
            merge_state,
            bot_evaluated_head,
            summary,
        )

    def _mergeable_clean_terminal(
        self,
        checks: CheckSummary,
        review_decision: str,
        merge_state: str,
        bot_evaluated_head: bool,
        summary: dict[str, object],
    ) -> bool:
        return (
            review_decision == "APPROVED"
            and (not self._require_review_bot_head_eval or bot_evaluated_head)
            and merge_state in {"CLEAN", "UNSTABLE"}
            and checks.pending_count == 0
            and checks.failed_count == 0
            and summary.get("unresolvedReviewThreads") == 0
        )

    def _repeated_terminal(
        self,
        last_seen: dict[str, object],
        reason: str,
        summary: dict[str, object],
    ) -> bool:
        return self._dict(last_seen.get("terminal")) == self._terminal_signature(reason, summary)

    def _terminal_signature(
        self,
        reason: str,
        summary: dict[str, object],
    ) -> dict[str, object]:
        return {
            "reason": reason,
            "headRefOid": summary.get("headRefOid"),
            "mergeState": summary.get("mergeState"),
            "reviewDecision": summary.get("reviewDecision"),
            "failedChecks": summary.get("failedChecks"),
            "pendingChecks": summary.get("pendingChecks"),
            "unresolvedReviewThreads": summary.get("unresolvedReviewThreads"),
        }

    def _bot_evaluated_head(
        self,
        snapshot: dict[str, object],
        checks: CheckSummary,
        head_oid: str,
    ) -> bool:
        if checks.ai_review_state == "PENDING":
            return True
        latest_review = self._latest_bot_review(snapshot)
        if self._str(latest_review.get("commit_id")) == head_oid and self._str(
            latest_review.get("state")
        ) in {"COMMENTED", "APPROVED", "CHANGES_REQUESTED"}:
            return True
        head_commit_date = self._str(snapshot.get("head_commit_date"))
        latest_comment_date = self._latest_bot_issue_comment_date(snapshot)
        return bool(
            latest_comment_date and head_commit_date and latest_comment_date > head_commit_date
        )

    def _latest_bot_review(self, snapshot: dict[str, object]) -> dict[str, object]:
        reviews = [
            item
            for item in self._list(snapshot.get("reviews"))
            if self._login(item) in self._review_bot_logins
        ]
        if not reviews:
            return {}
        return max(reviews, key=lambda item: self._str(item.get("submitted_at")))

    def _latest_bot_issue_comment_date(self, snapshot: dict[str, object]) -> str:
        dates: list[str] = []
        for item in self._list(snapshot.get("issue_comments")):
            if self._login(item) in self._review_bot_logins:
                created = self._str(item.get("created_at"))
                updated = self._str(item.get("updated_at"))
                dates.append(max(created, updated))
        return max(dates) if dates else ""

    def _unresolved_review_thread_count(self, snapshot: dict[str, object]) -> int:
        return len(self._unresolved_review_thread_ids(snapshot))

    def _unresolved_review_thread_ids(self, snapshot: dict[str, object]) -> tuple[str, ...]:
        """Submitted unresolved review thread의 stable identity를 반환합니다.

        Args:
            snapshot: GitHub review thread snapshot입니다.

        Returns:
            Thread id가 없으면 deterministic anonymous index를 사용한 sorted identity입니다.
        """
        identities = [
            self._str(thread.get("id")) or f"__anonymous_{index}"
            for index, thread in enumerate(self._list(snapshot.get("review_threads")))
            if thread.get("isResolved") is not True
            and self._has_submitted_review_thread_comment(thread)
        ]
        return tuple(sorted(identities))

    def _has_submitted_review_thread_comment(self, thread: dict[str, object]) -> bool:
        comments = self._dict(thread.get("comments"))
        for comment in self._list(comments.get("nodes")):
            review = self._dict(comment.get("pullRequestReview"))
            if self._str(review.get("state")) != "PENDING" and self._external_review_comment(
                comment
            ):
                return True
        return False

    def _external_review_comment(self, comment: dict[str, object]) -> bool:
        """자동 리뷰 출력과 agent marker를 외부 review 입력에서 제외합니다."""
        body = self._str(comment.get("body"))
        login = self._login(comment)
        if login in self._review_bot_logins or login.endswith("[bot]"):
            return False
        if "<!-- claude-agent-reply" in body or "<!-- ai-review verdict=" in body:
            return False
        return not body.startswith((
            "AI review 결과:",
            "## AI review 결과:",
            "AI 리뷰 결과:",
            "## AI 리뷰 결과:",
            "ai-review status ",
        ))

    def _checks(self, pr: dict[str, object]) -> list[dict[str, object]]:
        return self._list(pr.get("statusCheckRollup"))

    def _list(self, value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _dict(self, value: object) -> dict[str, object]:
        return value if isinstance(value, dict) else {}

    def _str(self, value: object) -> str:
        return value if isinstance(value, str) else ""

    def _login(self, item: dict[str, object]) -> str:
        for key in ("user", "author"):
            user = item.get(key, {})
            if isinstance(user, dict):
                login = self._str(user.get("login"))
                if login:
                    return login
        return ""


class GitHubSnapshotClient:
    """git hub snapshot client 관련 설정과 검증 조건을 함께 표현합니다."""

    def __init__(self, repo: str, pr_number: int) -> None:
        """GitHubSnapshotClient 인스턴스가 PR monitor resume와 GitHub 상태 수집 처리에 사용할 collaborator와 초기 상태를 보관합니다.

        Args:
            repo: 호출자가 넘긴 repo 값입니다.
            pr_number: 호출자가 넘긴 pr number 값입니다."""
        self._repo = repo
        self._pr_number = pr_number

    def load(self) -> dict[str, object]:
        """입력값을 해석해 해당 경계의 처리 결과를 만듭니다.

        Returns:
            load 처리 결과입니다."""
        pr = self._json_command([
            "gh",
            "pr",
            "view",
            str(self._pr_number),
            "--repo",
            self._repo,
            "--json",
            "mergeStateStatus,reviewDecision,statusCheckRollup,comments,state,headRefOid,labels",
        ])
        pull_comments = self._json_command([
            "gh",
            "api",
            f"repos/{self._repo}/pulls/{self._pr_number}/comments",
            "--paginate",
        ])
        issue_comments = self._json_command([
            "gh",
            "api",
            f"repos/{self._repo}/issues/{self._pr_number}/comments",
            "--paginate",
        ])
        reviews = self._json_command([
            "gh",
            "api",
            f"repos/{self._repo}/pulls/{self._pr_number}/reviews",
            "--paginate",
        ])
        review_threads = self._load_review_threads()
        head_oid = pr.get("headRefOid") if isinstance(pr, dict) else ""
        head_commit_date = ""
        if isinstance(head_oid, str) and head_oid:
            head_commit_date = self._text_command([
                "gh",
                "api",
                f"repos/{self._repo}/commits/{head_oid}",
                "--jq",
                '.commit.committer.date // ""',
            ])
        return {
            "pr": pr,
            "pull_comments": pull_comments,
            "issue_comments": issue_comments,
            "reviews": reviews,
            "review_threads": review_threads,
            "head_commit_date": head_commit_date,
        }

    def _load_review_threads(self) -> object:
        owner, name = self._repo.split("/", maxsplit=1)
        query = """
          query($owner: String!, $name: String!, $number: Int!) {
            repository(owner: $owner, name: $name) {
              pullRequest(number: $number) {
                reviewThreads(first: 100) {
                  nodes {
                    id
                    isResolved
                    isOutdated
                    comments(first: 20) {
                      nodes {
                        id
                        author { login }
                        body
                        path
                        line
                        originalLine
                        url
                        pullRequestReview {
                          state
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        """
        payload = self._json_command([
            "gh",
            "api",
            "graphql",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            "-F",
            f"number={self._pr_number}",
            "-f",
            f"query={query}",
        ])
        if not isinstance(payload, dict):
            return []
        data = payload.get("data", {})
        if not isinstance(data, dict):
            return []
        repository = data.get("repository", {})
        if not isinstance(repository, dict):
            return []
        pull_request = repository.get("pullRequest", {})
        if not isinstance(pull_request, dict):
            return []
        review_threads = pull_request.get("reviewThreads", {})
        if not isinstance(review_threads, dict):
            return []
        nodes = review_threads.get("nodes", [])
        return nodes if isinstance(nodes, list) else []

    def _json_command(self, command: list[str]) -> object:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        return json.loads(result.stdout)

    def _text_command(self, command: list[str]) -> str:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        return result.stdout.strip()


class ResumeAdapter:
    """resume adapter 관련 설정과 검증 조건을 함께 표현합니다."""

    def __init__(self, command: str | None) -> None:
        """ResumeAdapter 인스턴스가 PR monitor resume와 GitHub 상태 수집 처리에 사용할 collaborator와 초기 상태를 보관합니다.

        Args:
            command: 호출자가 넘긴 command 값입니다."""
        self._command = command

    @property
    def available(self) -> bool:
        """새 owner turn을 시작할 command가 준비됐는지 반환합니다.

        Returns:
            Resume command가 있으면 True입니다.
        """
        return bool(self._command)

    def resume(self, event: dict[str, object]) -> dict[str, object]:
        """입력값을 해석해 해당 경계의 처리 결과를 만듭니다.

        Args:
            event: 호출자가 넘긴 event 값입니다.

        Returns:
            resume 처리 결과입니다."""
        if not self._command:
            return {"resume_status": "queued-no-adapter"}
        command = shlex.split(self._command)
        snapshot = event.get("snapshot")
        expected_head_sha = snapshot.get("headRefOid") if isinstance(snapshot, dict) else None
        if (
            isinstance(expected_head_sha, str)
            and expected_head_sha
            and any(Path(part).name == "app_server_resume.py" for part in command)
        ):
            command.extend(("--expected-head-sha", expected_head_sha))
        result = subprocess.run(
            command,
            input=self._resume_prompt(event),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            parsed = self._parse_resume_stdout(result.stdout)
            if parsed is not None:
                parsed["resume_command"] = command[0]
                parsed["returncode"] = result.returncode
                if result.stderr:
                    parsed["stderr"] = result.stderr[-2000:]
                return parsed
        return {
            "resume_status": "invoked" if result.returncode == 0 else "failed",
            "resume_command": command[0],
            "returncode": result.returncode,
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-2000:],
        }

    def inspect_turn(self, turn_id: str) -> dict[str, object]:
        """App-server delivery turn을 새 prompt 없이 read-back합니다.

        Args:
            turn_id: 이전 delivery가 반환한 turn id입니다.

        Returns:
            App-server inspector payload 또는 unsupported/failed marker입니다.
        """
        if not self._command:
            return {"inspect_status": "unsupported"}
        arguments = shlex.split(self._command)
        if not any(Path(part).name == "app_server_resume.py" for part in arguments):
            return {"inspect_status": "unsupported"}
        result = subprocess.run(
            [*arguments, "--inspect-turn-id", turn_id],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in reversed(result.stdout.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and isinstance(payload.get("inspect_status"), str):
                return payload
        return {
            "inspect_status": "failed",
            "returncode": result.returncode,
            "stderr": result.stderr[-2000:],
        }

    def find_claimed_turn(self, claim_id: str, event_id: str) -> dict[str, object]:
        """Persisted full turn history에서 exact claim marker를 read-back합니다.

        Args:
            claim_id: 복구할 atomic mailbox claim identity입니다.
            event_id: 복구할 monitor event identity입니다.

        Returns:
            App-server recovery payload 또는 unsupported/failed marker입니다.
        """
        if not self._command:
            return {"recovery_status": "unsupported"}
        arguments = shlex.split(self._command)
        if not any(Path(part).name == "app_server_resume.py" for part in arguments):
            return {"recovery_status": "unsupported"}
        result = subprocess.run(
            [
                *arguments,
                "--find-claim-id",
                claim_id,
                "--find-event-id",
                event_id,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in reversed(result.stdout.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and isinstance(payload.get("recovery_status"), str):
                return payload
        return {
            "recovery_status": "failed",
            "returncode": result.returncode,
            "stderr": result.stderr[-2000:],
        }

    def _parse_resume_stdout(self, stdout: str) -> dict[str, object] | None:
        for line in reversed(stdout.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and isinstance(payload.get("resume_status"), str):
                return payload
        return None

    def _resume_prompt(self, event: dict[str, object]) -> str:
        claim_id = str(event.get("claim_id", ""))
        event_id = str(event.get("event_id", ""))
        marker = monitor_delivery_marker(claim_id, event_id)
        if event.get("reason") == "delegate-result-ready":
            return (
                f"{marker}\n"
                "로컬 PR monitor가 durable delegate result 제출을 감지했습니다. "
                "GitHub 상태 변화가 아니라 중단된 owner continuation 복구 신호입니다. "
                "먼저 현재 session/workflow의 canonical delegation result를 읽고 적용하세요. "
                "필요한 수정과 검증을 수행한 뒤 같은 `outcome_ref`로 delegation을 consume하고 "
                "process-ticket "
                "루프를 계속하세요.\n\n"
                "```json\n"
                f"{json.dumps(event, ensure_ascii=False, indent=2)}\n"
                "```\n"
            )
        return (
            f"{marker}\n"
            "로컬 PR monitor가 GitHub 상태 변화를 감지했습니다.\n"
            "아래 event JSON을 근거로 같은 작업 맥락을 재개하세요. "
            "먼저 현재 session/workflow state와 monitor observation을 읽고, "
            "monitor-pr/process-ticket 계약에 따라 comments, CI, dirty merge, "
            "review-blocked, terminal state 중 해당 분기를 처리하세요. "
            "필요한 경우 검증, commit, push, PR comment/read-back까지 이어가세요.\n\n"
            "```json\n"
            f"{json.dumps(event, ensure_ascii=False, indent=2)}\n"
            "```\n"
        )


class ResumeOutcome:
    """Resume adapter 결과에서 delivery와 completion 의미를 판정합니다."""

    @classmethod
    def completed(cls, payload: Mapping[str, object]) -> bool:
        """Exact turn이 completed로 read-back됐는지 반환합니다.

        Args:
            payload: Resume adapter가 반환한 delivery와 turn completion receipt입니다.

        Returns:
            Completion receipt와 nested turn이 모두 completed이면 ``True``입니다.
        """
        completion = payload.get("turn_completion")
        if not isinstance(completion, Mapping) or completion.get("status") != "completed":
            return False
        turn = completion.get("turn")
        return isinstance(turn, Mapping) and turn.get("status") == "completed"

    @classmethod
    def succeeded(cls, payload: Mapping[str, object]) -> bool:
        """Delivery invocation과 exact turn completion이 모두 성공했는지 반환합니다.

        Args:
            payload: Resume invocation 및 exact turn read-back 결과입니다.

        Returns:
            Invocation과 terminal completion이 모두 증명되면 ``True``입니다.
        """
        return payload.get("resume_status") == "invoked" and cls.completed(payload)


class MonitorWorkflowStateError(RuntimeError):
    """Workflow-local monitor state가 identity 또는 shape invariant를 위반했습니다."""


class MonitorWorkflowMutation(Protocol):
    """SkillStateStore가 retry할 수 있는 side-effect-free transition 계약입니다."""

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Current skill state를 새 immutable candidate로 변환합니다.

        Args:
            current: CAS retry마다 다시 읽은 latest workflow-local skill state입니다.

        Returns:
            Side effect 없이 계산한 다음 workflow-local state candidate입니다.
        """


class MonitorWorkflowDocument:
    """Owner lifecycle과 mailbox shape를 한 pure mutation 안에서 정규화합니다."""

    _OWNER_STATES = frozenset({"active", "idle", "recovering", "terminal"})

    def __init__(self, current: Mapping[str, object], session_id: str) -> None:
        """Retry input을 detached mutable document로 검증합니다.

        Args:
            current: CAS retry에서 받은 latest workflow-local skill state입니다.
            session_id: Owner lifecycle과 반드시 일치해야 하는 exact session ID입니다.

        Raises:
            MonitorWorkflowStateError: Lifecycle 또는 mailbox identity와 shape가 invalid할 때 발생합니다.
        """
        self._state = dict(current)
        lifecycle = current.get("owner_lifecycle")
        if not isinstance(lifecycle, Mapping):
            raise MonitorWorkflowStateError("workflow-local owner lifecycle is missing")
        if lifecycle.get("state") not in self._OWNER_STATES:
            raise MonitorWorkflowStateError("owner lifecycle state is invalid")
        if lifecycle.get("owner_session_id") != session_id:
            raise MonitorWorkflowStateError("owner session identity mismatch")
        self._lifecycle = dict(lifecycle)
        raw_mailbox = current.get("monitor_mailbox")
        if raw_mailbox is None:
            mailbox: Mapping[str, object] = {}
        elif isinstance(raw_mailbox, Mapping):
            mailbox = raw_mailbox
        else:
            raise MonitorWorkflowStateError("monitor mailbox must be an object")
        pending = mailbox.get("pending_events", [])
        seen = mailbox.get("seen_event_ids", [])
        active_claim = mailbox.get("active_claim")
        if not isinstance(pending, list) or any(not isinstance(row, Mapping) for row in pending):
            raise MonitorWorkflowStateError("monitor mailbox pending events must be object array")
        if not isinstance(seen, list) or any(not isinstance(row, str) for row in seen):
            raise MonitorWorkflowStateError("monitor mailbox seen event ids must be string array")
        if active_claim is not None and not isinstance(active_claim, Mapping):
            raise MonitorWorkflowStateError("monitor mailbox active claim must be object or null")
        self._mailbox: dict[str, object] = {
            **mailbox,
            "pending_events": [dict(row) for row in pending],
            "seen_event_ids": list(seen),
            "active_claim": dict(active_claim) if isinstance(active_claim, Mapping) else None,
        }

    @property
    def lifecycle(self) -> dict[str, object]:
        """Detached lifecycle copy를 반환합니다.

        Returns:
            Mutation이 원본 mapping을 건드리지 않고 갱신할 lifecycle 복사본입니다.
        """
        return dict(self._lifecycle)

    @property
    def mailbox(self) -> dict[str, object]:
        """Detached mailbox copy를 반환합니다.

        Returns:
            Pending event, seen ID, active claim을 분리 복사한 mailbox입니다.
        """
        return {
            **self._mailbox,
            "pending_events": [
                dict(row)
                for row in self._list(self._mailbox.get("pending_events"))
                if isinstance(row, Mapping)
            ],
            "seen_event_ids": list(self._list(self._mailbox.get("seen_event_ids"))),
            "active_claim": (
                dict(self._mailbox["active_claim"])
                if isinstance(self._mailbox.get("active_claim"), Mapping)
                else None
            ),
        }

    def replace_lifecycle(self, lifecycle: Mapping[str, object]) -> None:
        """Transition이 계산한 lifecycle을 document에 교체합니다.

        Args:
            lifecycle: 이번 pure transition이 계산한 complete owner lifecycle입니다.
        """
        self._lifecycle = dict(lifecycle)

    def replace_mailbox(self, mailbox: Mapping[str, object]) -> None:
        """Transition이 계산한 mailbox를 document에 교체합니다.

        Args:
            mailbox: 이번 pure transition이 계산한 complete monitor mailbox입니다.
        """
        self._mailbox = dict(mailbox)

    def payload(self) -> Mapping[str, object]:
        """Unrelated key를 보존한 complete skill-state candidate를 반환합니다.

        Returns:
            새 lifecycle과 mailbox를 병합한 optimistic update candidate입니다.
        """
        return {
            **self._state,
            "owner_lifecycle": dict(self._lifecycle),
            "monitor_mailbox": self.mailbox,
        }

    def _list(self, value: object) -> list[object]:
        return list(value) if isinstance(value, list) else []


class StageMonitorEventMutation:
    """새 occurrence를 workflow FIFO mailbox에 exact-once 저장합니다."""

    def __init__(self, *, session_id: str, event: Mapping[str, object], now: float) -> None:
        """Retry 밖에서 고정된 event와 timestamp를 보관합니다.

        Args:
            session_id: Mailbox owner lifecycle과 일치해야 하는 exact session ID입니다.
            event: Stable ``event_id``를 포함한 stage 대상 occurrence입니다.
            now: 모든 CAS retry가 공유할 stage timestamp입니다.

        Raises:
            MonitorWorkflowStateError: Event에 non-empty ``event_id``가 없을 때 발생합니다.
        """
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise MonitorWorkflowStateError("monitor event requires event_id")
        self._session_id = session_id
        self._event = dict(event)
        self._event_id = event_id
        self._now = now

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Latest mailbox에 unseen event만 append합니다.

        Args:
            current: CAS retry마다 다시 읽은 latest workflow-local state입니다.

        Returns:
            Event가 처음이면 append한 candidate, 이미 seen이면 original state입니다.

        Raises:
            MonitorWorkflowStateError: Latest mailbox가 normalized list shape가 아닐 때 발생합니다.
        """
        document = MonitorWorkflowDocument(current, self._session_id)
        mailbox = document.mailbox
        seen = mailbox["seen_event_ids"]
        pending = mailbox["pending_events"]
        if not isinstance(seen, list) or not isinstance(pending, list):
            raise MonitorWorkflowStateError("monitor mailbox is not normalized")
        if self._event_id in seen:
            return current
        pending.append(dict(self._event))
        seen.append(self._event_id)
        mailbox["pending_events"] = pending
        mailbox["seen_event_ids"] = seen
        mailbox["updated_at_epoch"] = self._now
        document.replace_mailbox(mailbox)
        return document.payload()


class ClaimMonitorEventMutation:
    """Idle owner와 FIFO head를 하나의 workflow-local CAS에서 claim합니다."""

    def __init__(
        self,
        *,
        session_id: str,
        workflow_id: str,
        runtime_id: str,
        instance_id: str,
        claimant_pid: int,
        claim_id: str,
        now: float,
    ) -> None:
        """Claim identity와 clock을 retry 전에 한 번만 고정합니다.

        Args:
            session_id: Owner lifecycle과 claim에 기록할 exact session ID입니다.
            workflow_id: Claim이 속하는 exact active workflow identity입니다.
            runtime_id: Claim을 수행하는 monitor launch identity입니다.
            instance_id: 같은 runtime 안에서 claimant를 구분하는 instance identity입니다.
            claimant_pid: Claimant process 생존 검증에 사용할 PID입니다.
            claim_id: Retry 전체에서 유지할 새 claim identity입니다.
            now: Claim과 lifecycle transition이 공유할 timestamp입니다.
        """
        self._session_id = session_id
        self._workflow_id = workflow_id
        self._runtime_id = runtime_id
        self._instance_id = instance_id
        self._claimant_pid = claimant_pid
        self._claim_id = claim_id
        self._now = now

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Idle, no-active-claim, non-empty FIFO 조건에서만 claim을 생성합니다.

        Args:
            current: CAS retry마다 다시 읽은 latest workflow-local state입니다.

        Returns:
            FIFO head를 claim한 candidate 또는 prerequisite가 없으면 original state입니다.

        Raises:
            MonitorWorkflowStateError: Pending event collection 또는 head shape가 invalid할 때 발생합니다.
        """
        document = MonitorWorkflowDocument(current, self._session_id)
        lifecycle = document.lifecycle
        mailbox = document.mailbox
        pending = mailbox["pending_events"]
        if not isinstance(pending, list):
            raise MonitorWorkflowStateError("monitor mailbox is not normalized")
        if (
            lifecycle.get("state") != "idle"
            or isinstance(mailbox.get("active_claim"), Mapping)
            or not pending
        ):
            return current
        event = pending.pop(0)
        if not isinstance(event, Mapping):
            raise MonitorWorkflowStateError("pending monitor event must be an object")
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise MonitorWorkflowStateError("pending monitor event requires event_id")
        claim: dict[str, object] = {
            "claim_id": self._claim_id,
            "event_id": event_id,
            "owner_session_id": self._session_id,
            "session_id": self._session_id,
            "workflow_id": self._workflow_id,
            "claimant_runtime_id": self._runtime_id,
            "claimant_instance_id": self._instance_id,
            "claimant_pid": self._claimant_pid,
            "claimed_at_epoch": self._now,
            "event": dict(event),
        }
        mailbox["pending_events"] = pending
        mailbox["active_claim"] = claim
        mailbox["updated_at_epoch"] = self._now
        document.replace_mailbox(mailbox)
        document.replace_lifecycle({
            "state": "active",
            "owner_session_id": self._session_id,
            "source": "monitor-delivery",
            "transitioned_at_epoch": self._now,
            "activity": "claim",
            "claim_id": self._claim_id,
        })
        return document.payload()


class BindMonitorTurnMutation:
    """Exact claim에 새 runtime turn identity를 immutable하게 결속합니다."""

    def __init__(
        self,
        *,
        session_id: str,
        event_id: str,
        claim_id: str,
        turn_id: str,
        now: float,
    ) -> None:
        """Binding prerequisite와 clock을 고정합니다.

        Args:
            session_id: Active claim owner와 일치해야 하는 exact session ID입니다.
            event_id: Active claim이 참조해야 하는 staged event identity입니다.
            claim_id: Turn을 결속할 exact mailbox claim identity입니다.
            turn_id: Resume adapter가 생성한 immutable runtime turn identity입니다.
            now: 최초 binding에 기록할 timestamp입니다.

        Raises:
            MonitorWorkflowStateError: Exact turn identity가 비어 있을 때 발생합니다.
        """
        if not turn_id:
            raise MonitorWorkflowStateError("claimed delivery requires exact turn id")
        self._session_id = session_id
        self._event_id = event_id
        self._claim_id = claim_id
        self._turn_id = turn_id
        self._now = now

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Matching active claim에만 turn을 bind합니다.

        Args:
            current: CAS retry마다 다시 읽은 latest workflow-local state입니다.

        Returns:
            Matching claim에 turn을 결속한 candidate 또는 불일치 시 original state입니다.

        Raises:
            MonitorWorkflowStateError: Claim에 다른 immutable turn이 이미 결속됐을 때 발생합니다.
        """
        document = MonitorWorkflowDocument(current, self._session_id)
        mailbox = document.mailbox
        claim = mailbox.get("active_claim")
        if not isinstance(claim, Mapping):
            return current
        if claim.get("event_id") != self._event_id or claim.get("claim_id") != self._claim_id:
            return current
        existing = claim.get("turn_id")
        if isinstance(existing, str) and existing != self._turn_id:
            raise MonitorWorkflowStateError("monitor delivery turn identity is immutable")
        bound = dict(claim)
        bound["turn_id"] = self._turn_id
        bound.setdefault("turn_bound_at_epoch", self._now)
        mailbox["active_claim"] = bound
        mailbox["updated_at_epoch"] = self._now
        lifecycle = document.lifecycle
        lifecycle.update({
            "turn_id": self._turn_id,
            "activity": "turn-started",
            "transitioned_at_epoch": self._now,
        })
        document.replace_mailbox(mailbox)
        document.replace_lifecycle(lifecycle)
        return document.payload()


class CompleteMonitorTurnMutation:
    """Terminal read-back과 matching ACK를 claim completion으로 반영합니다."""

    def __init__(self, *, session_id: str, turn_id: str, acknowledged: bool, now: float) -> None:
        """Terminal observation을 retry 전에 고정합니다.

        Args:
            session_id: Active claim owner와 일치해야 하는 exact session ID입니다.
            turn_id: Terminal read-back이 증명한 exact runtime turn identity입니다.
            acknowledged: Matching durable ACK까지 확인됐는지 나타냅니다.
            now: Terminal lifecycle transition에 기록할 timestamp입니다.
        """
        self._session_id = session_id
        self._turn_id = turn_id
        self._acknowledged = acknowledged
        self._now = now

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Matching turn을 recovering 또는 idle completion으로 전이합니다.

        Args:
            current: CAS retry마다 다시 읽은 latest workflow-local state입니다.

        Returns:
            ACK 유무에 따라 recovering 또는 idle로 바꾼 candidate입니다.
        """
        document = MonitorWorkflowDocument(current, self._session_id)
        mailbox = document.mailbox
        claim = mailbox.get("active_claim")
        if not isinstance(claim, Mapping) or claim.get("turn_id") != self._turn_id:
            return current
        saved_claim = dict(claim)
        saved_claim["terminal_observed_at_epoch"] = self._now
        if not self._acknowledged:
            saved_claim["delivery_state"] = "awaiting-ack"
            mailbox["active_claim"] = saved_claim
            lifecycle = {
                "state": "recovering",
                "owner_session_id": self._session_id,
                "source": "monitor-delivery",
                "transitioned_at_epoch": self._now,
                "activity": "terminal-without-ack",
                "claim_id": claim.get("claim_id"),
                "turn_id": self._turn_id,
            }
        else:
            mailbox["active_claim"] = None
            lifecycle = {
                "state": "idle",
                "owner_session_id": self._session_id,
                "source": "monitor-delivery",
                "transitioned_at_epoch": self._now,
                "activity": "turn-completed-and-acknowledged",
            }
        mailbox["updated_at_epoch"] = self._now
        document.replace_mailbox(mailbox)
        document.replace_lifecycle(lifecycle)
        return document.payload()


class ReleaseMonitorClaimMutation:
    """Turn이 없는 exact claim만 FIFO head로 되돌립니다."""

    def __init__(self, *, session_id: str, claim_id: str, now: float) -> None:
        """Release identity와 clock을 고정합니다.

        Args:
            session_id: Active claim owner와 일치해야 하는 exact session ID입니다.
            claim_id: Delivery가 시작되지 않았음을 확인한 exact claim identity입니다.
            now: FIFO 복원과 lifecycle transition에 기록할 timestamp입니다.
        """
        self._session_id = session_id
        self._claim_id = claim_id
        self._now = now

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Matching unbound claim을 안전하게 release합니다.

        Args:
            current: CAS retry마다 다시 읽은 latest workflow-local state입니다.

        Returns:
            Event를 FIFO head로 복원한 candidate 또는 불일치 시 original state입니다.

        Raises:
            MonitorWorkflowStateError: Claim event 또는 pending collection shape가 invalid할 때 발생합니다.
        """
        document = MonitorWorkflowDocument(current, self._session_id)
        mailbox = document.mailbox
        claim = mailbox.get("active_claim")
        if not isinstance(claim, Mapping) or claim.get("claim_id") != self._claim_id:
            return current
        if isinstance(claim.get("turn_id"), str):
            return current
        event = claim.get("event")
        pending = mailbox["pending_events"]
        if not isinstance(event, Mapping) or not isinstance(pending, list):
            raise MonitorWorkflowStateError("monitor claim requires event payload")
        pending.insert(0, dict(event))
        mailbox["pending_events"] = pending
        mailbox["active_claim"] = None
        mailbox["updated_at_epoch"] = self._now
        document.replace_mailbox(mailbox)
        document.replace_lifecycle({
            "state": "idle",
            "owner_session_id": self._session_id,
            "source": "monitor-delivery",
            "transitioned_at_epoch": self._now,
            "activity": "delivery-not-started",
        })
        return document.payload()


class ReleaseNativeOwnerMutation:
    """Runtime inspection이 terminal로 증명한 exact native turn을 idle로 해제합니다."""

    def __init__(
        self,
        *,
        session_id: str,
        turn_id: str,
        turn_status: str,
        now: float,
    ) -> None:
        """Inspection evidence를 retry 전에 고정합니다.

        Args:
            session_id: Native lifecycle owner와 일치해야 하는 exact session ID입니다.
            turn_id: App-server가 terminal로 read-back한 native turn identity입니다.
            turn_status: Native turn의 허용된 terminal status입니다.
            now: Owner release lifecycle에 기록할 timestamp입니다.

        Raises:
            MonitorWorkflowStateError: ``turn_status``가 terminal set 밖일 때 발생합니다.
        """
        if turn_status not in NATIVE_TURN_TERMINAL_STATUSES:
            raise MonitorWorkflowStateError("native owner release requires terminal status")
        self._session_id = session_id
        self._turn_id = turn_id
        self._turn_status = turn_status
        self._now = now

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Current native lifecycle이 inspected turn과 같을 때만 해제합니다.

        Args:
            current: CAS retry마다 다시 읽은 latest workflow-local state입니다.

        Returns:
            Matching native owner를 idle로 해제한 candidate 또는 original state입니다.
        """
        document = MonitorWorkflowDocument(current, self._session_id)
        lifecycle = document.lifecycle
        mailbox = document.mailbox
        if (
            isinstance(mailbox.get("active_claim"), Mapping)
            or lifecycle.get("state") != "active"
            or lifecycle.get("source") != "native-hook"
            or lifecycle.get("turn_id") != self._turn_id
        ):
            return current
        document.replace_lifecycle({
            "state": "idle",
            "owner_session_id": self._session_id,
            "source": "turn-inspection",
            "transitioned_at_epoch": self._now,
            "activity": "native-turn-release",
            "released_turn_id": self._turn_id,
            "released_turn_status": self._turn_status,
        })
        return document.payload()


class MonitorWorkflowState:
    """Exact workflow mailbox를 pure optimistic transactions로 관리합니다."""

    _MAX_RETRIES = 64

    def __init__(self, handle: StateHandle, workflow_id: WorkflowId) -> None:
        """Runtime-bound handle과 exact active workflow에 adapter를 고정합니다.

        Args:
            handle: Vendor runtime identity에 attach된 canonical session handle입니다.
            workflow_id: Mailbox와 owner lifecycle을 소유하는 exact workflow입니다.
        """
        self._handle = handle
        self._workflow_id = workflow_id
        self._session_id = str(handle.session_id)
        self._store = SkillStateStore(handle, workflow_id)

    def runtime(self) -> dict[str, object]:
        """Validated lifecycle과 mailbox snapshot을 반환합니다.

        Returns:
            Current lifecycle, FIFO, seen IDs, active claim을 분리한 runtime view입니다.
        """
        snapshot = self._store.read()
        document = MonitorWorkflowDocument(snapshot.skill_state, self._session_id)
        mailbox = document.mailbox
        return {
            "lifecycle": document.lifecycle,
            "pending_events": mailbox["pending_events"],
            "seen_event_ids": mailbox["seen_event_ids"],
            "active_claim": mailbox["active_claim"],
        }

    def stage(self, event: Mapping[str, object]) -> bool:
        """새 event를 exact-once 저장하고 CAS 승자 여부를 반환합니다.

        Args:
            event: Stable ``event_id``를 포함한 workflow-local occurrence입니다.

        Returns:
            새 occurrence가 committed되면 ``True``, 이미 seen이면 ``False``입니다.
        """
        _, changed = self._commit(
            StageMonitorEventMutation(
                session_id=self._session_id,
                event=event,
                now=time.time(),
            )
        )
        return changed

    def claim(self, *, runtime_id: str, instance_id: str, claimant_pid: int) -> dict[str, object]:
        """Idle FIFO head를 claim하고 committed claim을 반환합니다.

        Args:
            runtime_id: Claimant monitor launch의 고유 runtime identity입니다.
            instance_id: 같은 launch 안에서 process instance를 구분하는 identity입니다.
            claimant_pid: Stale claim recovery에서 process 생존을 검증할 PID입니다.

        Returns:
            Committed active claim이며 claim할 event가 없으면 빈 object입니다.
        """
        snapshot, changed = self._commit(
            ClaimMonitorEventMutation(
                session_id=self._session_id,
                workflow_id=str(self._workflow_id),
                runtime_id=runtime_id,
                instance_id=instance_id,
                claimant_pid=claimant_pid,
                claim_id=uuid.uuid4().hex,
                now=time.time(),
            )
        )
        if not changed:
            return {}
        document = MonitorWorkflowDocument(snapshot.skill_state, self._session_id)
        claim = document.mailbox.get("active_claim")
        return dict(claim) if isinstance(claim, Mapping) else {}

    def bind_turn(self, *, event_id: str, claim_id: str, turn_id: str) -> bool:
        """Matching claim에 exact turn identity를 결속합니다.

        Args:
            event_id: Claim이 참조하는 staged event identity입니다.
            claim_id: Turn을 결속할 exact active claim identity입니다.
            turn_id: Resume adapter가 시작한 immutable runtime turn identity입니다.

        Returns:
            Matching claim이 committed되면 ``True``, 없으면 ``False``입니다.
        """
        _, changed = self._commit(
            BindMonitorTurnMutation(
                session_id=self._session_id,
                event_id=event_id,
                claim_id=claim_id,
                turn_id=turn_id,
                now=time.time(),
            )
        )
        return changed

    def complete_turn(self, *, turn_id: str, acknowledged: bool) -> bool:
        """Terminal observation을 기록하고 ACK가 있으면 claim을 완료합니다.

        Args:
            turn_id: Terminal read-back을 마친 exact runtime turn identity입니다.
            acknowledged: Matching durable monitor ACK를 확인했는지 나타냅니다.

        Returns:
            ACK와 terminal turn이 함께 committed되어 claim이 사라지면 ``True``입니다.
        """
        snapshot, changed = self._commit(
            CompleteMonitorTurnMutation(
                session_id=self._session_id,
                turn_id=turn_id,
                acknowledged=acknowledged,
                now=time.time(),
            )
        )
        if not changed or not acknowledged:
            return False
        document = MonitorWorkflowDocument(snapshot.skill_state, self._session_id)
        return document.mailbox.get("active_claim") is None

    def release_claim(self, claim_id: str) -> bool:
        """Matching unbound claim을 FIFO로 되돌립니다.

        Args:
            claim_id: Resume turn을 시작하지 못한 exact active claim identity입니다.

        Returns:
            Event가 FIFO head로 복원되어 commit되면 ``True``입니다.
        """
        _, changed = self._commit(
            ReleaseMonitorClaimMutation(
                session_id=self._session_id,
                claim_id=claim_id,
                now=time.time(),
            )
        )
        return changed

    def release_native_owner(self, *, turn_id: str, turn_status: str) -> dict[str, object]:
        """Exact terminal native turn을 idle로 해제하고 committed lifecycle을 반환합니다.

        Args:
            turn_id: Runtime inspection이 terminal로 증명한 native turn identity입니다.
            turn_status: Native runtime이 read-back한 terminal status입니다.

        Returns:
            해제가 committed되면 새 lifecycle, route가 달라지면 빈 object입니다.
        """
        snapshot, changed = self._commit(
            ReleaseNativeOwnerMutation(
                session_id=self._session_id,
                turn_id=turn_id,
                turn_status=turn_status,
                now=time.time(),
            )
        )
        if not changed:
            return {}
        return MonitorWorkflowDocument(snapshot.skill_state, self._session_id).lifecycle

    def acknowledgement(self) -> dict[str, object]:
        """Current workflow-local monitor ACK를 반환합니다.

        Returns:
            Exact workflow의 durable ACK이며 기록이 없거나 invalid하면 빈 object입니다.
        """
        value = self._store.read().skill_state.get("monitor_event_ack")
        return dict(value) if isinstance(value, Mapping) else {}

    def _commit(
        self,
        mutation: MonitorWorkflowMutation,
    ) -> tuple[SkillStateSnapshot, bool]:
        for _attempt in range(self._MAX_RETRIES):
            original = self._store.read()
            candidate = mutation(original.skill_state)
            if dict(candidate) == dict(original.skill_state):
                return original, False
            try:
                committed = self._store.compare_and_update(
                    original.workflow_revision,
                    mutation,
                )
            except SkillStateConflict:
                continue
            return committed, True
        raise SkillStateRetryExhausted(
            f"monitor workflow {self._workflow_id} did not converge after "
            f"{self._MAX_RETRIES} retries"
        )


class MonitorDelegationSnapshot:
    """Exact workflow child assignment과 optional result를 immutable하게 결합합니다."""

    __slots__ = ("claim", "result", "status")

    def __init__(
        self,
        *,
        claim: Mapping[str, object],
        result: Mapping[str, object] | None,
        status: DelegationStatus,
    ) -> None:
        """Canonical delegation projection을 고정합니다.

        Args:
            claim: Owner와 target identity를 포함한 normalized child assignment입니다.
            result: Reported child이면 immutable result receipt, pending이면 ``None``입니다.
            status: SessionKernel이 보존한 pending 또는 reported delegation 상태입니다.
        """
        object.__setattr__(self, "claim", dict(claim))
        object.__setattr__(self, "result", None if result is None else dict(result))
        object.__setattr__(self, "status", status)

    claim: dict[str, object]
    """Monitor가 delivery 판단에 사용할 normalized child assignment입니다."""
    result: dict[str, object] | None
    """Reported child의 digest-bound result이며 pending 상태에서는 없습니다."""
    status: DelegationStatus
    """Result delivery 여부를 결정하는 canonical delegation lifecycle 상태입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성 이후 delegation snapshot mutation을 거부합니다.

        Args:
            name: 변경을 시도한 snapshot attribute 이름입니다.
            value: Immutable projection에 새로 지정하려 한 값입니다.

        Raises:
            AttributeError: 생성 이후 snapshot field를 변경하려 할 때 발생합니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class MonitorDelegationReader:
    """SessionKernel delegation map에서 exact owner/workflow child만 선택합니다."""

    def __init__(self, handle: StateHandle, workflow_id: WorkflowId) -> None:
        """Canonical session actor와 workflow identity를 고정합니다.

        Args:
            handle: Exact owner actor와 delegation map을 제공하는 session handle입니다.
            workflow_id: Child assignment를 필터링할 exact workflow identity입니다.
        """
        self._handle = handle
        self._workflow_id = workflow_id

    def active(self) -> tuple[MonitorDelegationSnapshot, ...]:
        """Pending 또는 reported exact child assignment를 stable order로 반환합니다.

        Returns:
            Current owner와 workflow에 속한 active child projection의 stable tuple입니다.

        Raises:
            MonitorWorkflowStateError: Assignment JSON, identity, required field가 invalid할 때 발생합니다.
        """
        snapshots: list[MonitorDelegationSnapshot] = []
        state = self._handle.inspect()
        for delegation_id, delegation in sorted(
            state.delegations.items(),
            key=lambda item: str(item[0]),
        ):
            if delegation.owner_actor_id != self._handle.actor_id:
                continue
            # Terminal history can use another producer's assignment schema.
            if delegation.status not in {DelegationStatus.PENDING, DelegationStatus.REPORTED}:
                continue
            try:
                raw_assignment: object = json.loads(delegation.assignment)
            except json.JSONDecodeError as error:
                raise MonitorWorkflowStateError(
                    f"delegation assignment is invalid: {delegation_id}"
                ) from error
            if not isinstance(raw_assignment, Mapping):
                raise MonitorWorkflowStateError(
                    f"delegation assignment must be an object: {delegation_id}"
                )
            if raw_assignment.get("workflow_id") != str(self._workflow_id):
                continue
            required = ("kind", "scope", "started_at", "target", "workflow_id")
            if any(
                not isinstance(raw_assignment.get(field), str) or not raw_assignment.get(field)
                for field in required
            ):
                raise MonitorWorkflowStateError(
                    f"delegation assignment identity is incomplete: {delegation_id}"
                )
            claim: dict[str, object] = {
                "delegation_id": str(delegation.id),
                "kind": raw_assignment["kind"],
                "owner_actor_id": str(delegation.owner_actor_id),
                "scope": raw_assignment["scope"],
                "started_at": raw_assignment["started_at"],
                "target": raw_assignment["target"],
                "target_agent_id": str(delegation.target_actor_id),
                "workflow_id": raw_assignment["workflow_id"],
            }
            result_payload: dict[str, object] | None = None
            if delegation.status is DelegationStatus.REPORTED:
                result_payload = delegation.result.to_payload()
                result_payload.update({
                    "delegation_id": str(delegation.id),
                    "target_agent_id": str(delegation.target_actor_id),
                    "result_digest": hashlib.sha256(
                        json.dumps(
                            result_payload,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ).encode()
                    ).hexdigest(),
                })
            snapshots.append(
                MonitorDelegationSnapshot(
                    claim=claim,
                    result=result_payload,
                    status=delegation.status,
                )
            )
        return tuple(snapshots)


class LocalPrMonitor:
    """GitHub observation과 workflow-local mailbox delivery를 조정합니다."""

    _PRESERVED_OBSERVATION_FIELDS = frozenset({
        "active_delivery",
        "claim_recovery",
        "delegate_in_progress",
        "delivery_status",
        "last_event",
        "last_observed",
        "last_observed_at_epoch",
        "last_poll_error",
        "last_seen",
        "native_owner_inspection",
        "native_owner_release",
        "pending_snapshot_detected",
        "resume_probe_output",
        "resume_unavailable_reason",
        "runtime_reload",
        "turn_inspection",
    })

    def __init__(
        self,
        *,
        handle: StateHandle,
        workflow_id: WorkflowId,
        worktree: CanonicalWorktreeIdentity,
        runtime_id: str,
        repo: str,
        pr_number: int,
        poll_interval_seconds: int,
        resume_command: str | None,
        launcher: str = "process",
        resume_unavailable_reason: str = "",
        resume_probe_output: str = "",
        resume_adapter: ResumeAdapter | None = None,
    ) -> None:
        """Runtime authority와 canonical local observation path에 monitor를 고정합니다.

        Args:
            handle: Current vendor session에 attach된 canonical state handle입니다.
            workflow_id: Mailbox와 owner lifecycle을 소유하는 exact workflow입니다.
            worktree: Git이 증명한 path와 opaque ID를 제공하는 worktree identity입니다.
            runtime_id: 이번 monitor process launch의 고유 identity입니다.
            repo: Snapshot client가 조회할 exact GitHub repository입니다.
            pr_number: Snapshot client가 추적할 pull request 번호입니다.
            poll_interval_seconds: Continuous mode에서 snapshot 사이에 대기할 주기입니다.
            resume_command: Event delivery에 사용할 command adapter이며 없으면 collector-only입니다.
            launcher: Observation receipt에 기록할 실제 process manager 종류입니다.
            resume_unavailable_reason: Collector-only fallback을 설명하는 typed reason입니다.
            resume_probe_output: Resume capability probe의 제한된 진단 receipt입니다.
            resume_adapter: Authenticated service adapter supplied by the MCP automation boundary.

        Raises:
            ValueError: Monitor runtime identity가 비어 있을 때 발생합니다.
        """
        if not runtime_id.strip():
            raise ValueError("monitor runtime id must not be empty")
        self._handle = handle
        self._workflow_id = workflow_id
        self._session_id = str(handle.session_id)
        self._runtime_id = runtime_id.strip()
        self._repo = repo
        self._pr_number = pr_number
        self._worktree = worktree.path
        self._worktree_id = str(worktree.worktree_id)
        self._state_path = worktree.path / ".monitor-pr" / "monitor-state.json"
        self._poll_interval_seconds = poll_interval_seconds
        self._launcher = launcher
        self._resume_unavailable_reason = resume_unavailable_reason
        self._resume_probe_output = resume_probe_output
        self._state = MonitorObservationStore(self._state_path)
        self._workflow_state = MonitorWorkflowState(handle, workflow_id)
        self._delegations = MonitorDelegationReader(handle, workflow_id)
        self._classifier = EventClassifier()
        self._resume_adapter = resume_adapter if resume_adapter is not None else ResumeAdapter(resume_command)
        self._instance_id = uuid.uuid4().hex
        self._runtime_signature = self._runtime_source_signature()

    def run(self, *, once: bool) -> None:
        """Runtime receipt를 먼저 게시하고 bounded poll loop를 실행합니다.

        Args:
            once: 첫 snapshot 처리 뒤 종료할지 지속 polling할지 결정합니다.
        """
        self._state.write(self._base_state(self._state.read()))
        while True:
            if self._runtime_source_changed():
                self._reexec_runtime()
                return
            try:
                snapshot = GitHubSnapshotClient(self._repo, self._pr_number).load()
            except (json.JSONDecodeError, subprocess.CalledProcessError) as error:
                self._record_poll_error(error)
                if once:
                    return
                time.sleep(self._poll_interval_seconds)
                continue
            event = self.run_once(snapshot)
            if once or self._should_stop_after_event(event):
                return
            time.sleep(self._poll_interval_seconds)

    def run_once(self, snapshot: dict[str, object]) -> MonitorEvent | None:
        """GitHub snapshot 하나를 classify, stage, claim, deliver합니다.

        Args:
            snapshot: 같은 poll에서 read-back한 PR, review, check, comment 상태입니다.

        Returns:
            실제 delivery를 시도한 event이며 새 occurrence가 없으면 ``None``입니다.

        Raises:
            MonitorWorkflowStateError: Committed mailbox claim에 event payload가 없을 때 발생합니다.
        """
        state = self._base_state(self._state.read())
        state.pop("last_poll_error", None)
        self._reconcile_claimed_turn(state)
        previous = self._dict(state.get("last_observed")) or self._dict(state.get("last_seen"))
        classified = self._classifier.classify(snapshot, previous)
        state["last_observed"] = self._classifier.last_seen_from_snapshot(snapshot)
        state["last_observed_at_epoch"] = time.time()
        emitted = classified
        if classified is not None:
            self._stage_classified_event(classified, snapshot, state)

        delegations = self._delegations.active()
        pending_delegations = [
            delegation.claim
            for delegation in delegations
            if delegation.status is DelegationStatus.PENDING
        ]
        if pending_delegations:
            state["delegate_in_progress"] = pending_delegations
            if classified is not None:
                state["pending_snapshot_detected"] = True
            self._state.write(state)
            return None
        state.pop("delegate_in_progress", None)
        for delegation in delegations:
            if delegation.status is not DelegationStatus.REPORTED or delegation.result is None:
                continue
            delegate_event = self._delegate_result_event(
                snapshot,
                delegation.claim,
                delegation.result,
            )
            self._stage_classified_event(delegate_event, snapshot, state)
            if emitted is None:
                emitted = delegate_event

        if not self._resume_adapter.available:
            state["delivery_status"] = "collector-only-resume-unavailable"
            state.pop("active_delivery", None)
            self._state.write(state)
            return emitted

        self._release_dead_native_owner(state)
        claim = self._workflow_state.claim(
            runtime_id=self._runtime_id,
            instance_id=self._instance_id,
            claimant_pid=os.getpid(),
        )
        if not claim:
            self._state.write(state)
            return emitted
        claimed_event = self._dict(claim.get("event"))
        if not claimed_event:
            raise MonitorWorkflowStateError("monitor mailbox claim requires event payload")
        claimed_monitor_event = self._event_from_payload(claimed_event)
        delivery_payload = dict(claimed_event)
        delivery_payload["delivery_status"] = "claimed"
        delivery_payload["claim_id"] = claim["claim_id"]
        state["last_event"] = dict(delivery_payload)
        state["active_delivery"] = dict(delivery_payload)
        self._state.write(state)

        delivery_payload.update(self._resume_adapter.resume(delivery_payload))
        turn_id = self._delivery_turn_id(delivery_payload)
        if turn_id:
            self._workflow_state.bind_turn(
                event_id=self._str(claim.get("event_id")),
                claim_id=self._str(claim.get("claim_id")),
                turn_id=turn_id,
            )
            delivery_payload["delivery_status"] = "turn-started"
            delivery_payload["turn_id"] = turn_id
            if self._delivery_turn_is_terminal(delivery_payload):
                completed = self._workflow_state.complete_turn(
                    turn_id=turn_id,
                    acknowledged=self._delivery_is_consumed(delivery_payload),
                )
                delivery_payload["delivery_status"] = (
                    "completed" if completed else "recovering-awaiting-ack"
                )
                if completed:
                    state.pop("active_delivery", None)
        elif self._delivery_definitively_not_started(delivery_payload):
            self._workflow_state.release_claim(self._str(claim.get("claim_id")))
            delivery_payload["delivery_status"] = "not-started"
            state.pop("active_delivery", None)
        else:
            recovered = self._recover_unbound_claim(claim, state, force=True)
            if recovered:
                delivery_payload["delivery_status"] = "turn-recovered"
                delivery_payload["turn_id"] = recovered
            elif self._workflow_state.runtime().get("active_claim") is None:
                delivery_payload["delivery_status"] = "not-started"
                state.pop("active_delivery", None)
            else:
                delivery_payload["delivery_status"] = "recovering-unbound-claim"
        state["last_event"] = dict(delivery_payload)
        if "active_delivery" in state:
            state["active_delivery"] = dict(delivery_payload)
        self._state.write(state)
        print(json.dumps(delivery_payload, ensure_ascii=False))
        return claimed_monitor_event

    def _runtime_source_signature(self) -> str:
        digest = hashlib.sha256()
        for path in RUNTIME_SOURCE_PATHS:
            digest.update(str(path).encode())
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def _runtime_source_changed(self) -> bool:
        return self._runtime_source_signature() != self._runtime_signature

    def _reexec_runtime(self) -> None:
        current_signature = self._runtime_source_signature()
        state = self._base_state(self._state.read())
        state["runtime_reload"] = {
            "previousSignature": self._runtime_signature,
            "currentSignature": current_signature,
            "detectedAtEpoch": time.time(),
        }
        self._state.write(state)
        os.execv(sys.executable, [sys.executable, *sys.argv])

    def _should_stop_after_event(self, event: MonitorEvent | None) -> bool:
        if event is None:
            return self._persisted_terminal_ack_consumed()
        return (
            event.kind == "terminal"
            and event.reason in {"merged", "closed-without-merge"}
            and self._terminal_delivery_consumed(event)
        )

    def _persisted_terminal_ack_consumed(self) -> bool:
        event = self._persisted_terminal_event()
        return event is not None and self._terminal_delivery_consumed(event)

    def _persisted_terminal_event(self) -> MonitorEvent | None:
        try:
            last_event = self._dict(self._state.read().get("last_event"))
        except json.JSONDecodeError, OSError:
            return None
        if last_event.get("monitor_event") != "terminal" or last_event.get("reason") not in {
            "merged",
            "closed-without-merge",
        }:
            return None
        return self._event_from_payload(last_event)

    def _terminal_delivery_consumed(self, event: MonitorEvent) -> bool:
        try:
            state = self._state.read()
        except json.JSONDecodeError, OSError:
            return False
        if self._workflow_state.runtime().get("active_claim") is not None:
            return False
        last_event = self._dict(state.get("last_event"))
        expected_id = MonitorEventIdentity.create(self._event_payload(event))
        if last_event.get("event_id") != expected_id:
            return False
        return self._has_matching_event_ack(last_event) or (
            last_event.get("delivery_status") == "completed"
            and last_event.get("monitor_event") == "terminal"
            and last_event.get("reason") == event.reason
            and ResumeOutcome.succeeded(last_event)
        )

    def _stage_classified_event(
        self,
        event: MonitorEvent,
        snapshot: dict[str, object],
        state: dict[str, object],
    ) -> bool:
        payload = self._event_payload(event)
        payload["event_id"] = MonitorEventIdentity.create(payload)
        inserted = self._workflow_state.stage(payload)
        state["last_seen"] = (
            self._last_seen_from_work_event(payload)
            if event.kind == "event"
            else self._classifier.last_seen_from_snapshot(snapshot)
        )
        payload["delivery_status"] = "mailboxed"
        state["last_event"] = dict(payload)
        if inserted:
            self._write_event(payload)
        return inserted

    def _release_dead_native_owner(self, state: dict[str, object]) -> None:
        runtime = self._workflow_state.runtime()
        if not runtime.get("pending_events") or isinstance(runtime.get("active_claim"), Mapping):
            return
        lifecycle = self._dict(runtime.get("lifecycle"))
        if lifecycle.get("state") != "active" or lifecycle.get("source") != "native-hook":
            return
        turn_id = self._str(lifecycle.get("turn_id"))
        if not turn_id:
            return
        inspection = self._resume_adapter.inspect_turn(turn_id)
        turn = self._dict(inspection.get("turn"))
        status = self._str(turn.get("status"))
        state["native_owner_inspection"] = {
            "turn_id": turn_id,
            "status": status,
            "inspected_at_epoch": time.time(),
        }
        if status not in NATIVE_TURN_TERMINAL_STATUSES:
            return
        released = self._workflow_state.release_native_owner(
            turn_id=turn_id,
            turn_status=status,
        )
        if released:
            state["native_owner_release"] = released

    def _reconcile_claimed_turn(self, state: dict[str, object]) -> None:
        active_claim = self._workflow_state.runtime().get("active_claim")
        if not isinstance(active_claim, Mapping):
            state.pop("active_delivery", None)
            return
        claim = dict(active_claim)
        turn_id = claim.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id:
            turn_id = self._recover_unbound_claim(claim, state)
            if not turn_id:
                return
        inspection = self._resume_adapter.inspect_turn(turn_id)
        turn = self._dict(inspection.get("turn"))
        state["turn_inspection"] = {
            "turn_id": turn_id,
            "status": turn.get("status"),
            "inspected_at_epoch": time.time(),
        }
        if turn.get("status") not in NATIVE_TURN_TERMINAL_STATUSES:
            return
        event = self._dict(claim.get("event"))
        acknowledged = turn.get("status") == "completed" and self._delivery_is_consumed(event)
        completed = self._workflow_state.complete_turn(
            turn_id=turn_id,
            acknowledged=acknowledged,
        )
        if completed:
            state.pop("active_delivery", None)
        else:
            state["active_delivery"] = {
                **event,
                "delivery_status": "recovering-awaiting-ack",
                "turn_id": turn_id,
            }

    def _recover_unbound_claim(
        self,
        active_claim: dict[str, object],
        state: dict[str, object],
        *,
        force: bool = False,
    ) -> str:
        if not force and self._claimant_process_is_live(active_claim):
            return ""
        claim_id = self._str(active_claim.get("claim_id"))
        event_id = self._str(active_claim.get("event_id"))
        if not claim_id or not event_id:
            return ""
        recovery = self._resume_adapter.find_claimed_turn(claim_id, event_id)
        state["claim_recovery"] = {
            "claim_id": claim_id,
            "event_id": event_id,
            **recovery,
            "inspected_at_epoch": time.time(),
        }
        turn = self._dict(recovery.get("turn"))
        turn_id = self._str(turn.get("id"))
        if (
            recovery.get("recovery_status") == "found"
            and turn_id
            and self._workflow_state.bind_turn(
                event_id=event_id,
                claim_id=claim_id,
                turn_id=turn_id,
            )
        ):
            return turn_id
        if recovery.get("recovery_status") == "absent" and recovery.get("thread_status") == "idle":
            self._workflow_state.release_claim(claim_id)
            state.pop("active_delivery", None)
        return ""

    def _claimant_process_is_live(self, active_claim: dict[str, object]) -> bool:
        if (
            active_claim.get("session_id") != self._session_id
            or active_claim.get("workflow_id") != str(self._workflow_id)
            or active_claim.get("claimant_runtime_id") != self._runtime_id
        ):
            return False
        pid = active_claim.get("claimant_pid")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            return True
        result = subprocess.run(
            ("ps", "-p", str(pid), "-o", "command="),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False
        try:
            command = shlex.split(result.stdout)
        except ValueError:
            return False
        return (
            any(Path(part).name == "local_pr_monitor.py" for part in command)
            and self._option_matches(command, "--repo", self._repo)
            and self._option_matches(command, "--pr-number", str(self._pr_number))
            and self._option_matches(command, "--workflow-id", str(self._workflow_id))
            and self._option_matches(command, "--runtime-id", self._runtime_id)
        )

    def _option_matches(self, command: Sequence[str], option: str, expected: str) -> bool:
        try:
            index = command.index(option)
        except ValueError:
            return False
        return index + 1 < len(command) and command[index + 1] == expected

    def _delivery_is_consumed(self, payload: dict[str, object]) -> bool:
        if payload.get("monitor_event") == "terminal" and payload.get("reason") in {
            "merged",
            "closed-without-merge",
        }:
            return True
        return self._has_matching_event_ack(payload)

    def _delivery_turn_id(self, payload: dict[str, object]) -> str:
        completion = self._dict(payload.get("turn_completion"))
        if (
            payload.get("delivery_method") == "active-turn-deferred"
            or completion.get("status") == "deferred"
        ):
            return ""
        turn_id = self._str(completion.get("turnId"))
        if turn_id:
            return turn_id
        response = self._dict(payload.get("response"))
        turn_id = self._str(response.get("turnId"))
        if turn_id:
            return turn_id
        return self._str(self._dict(response.get("turn")).get("id"))

    def _delivery_definitively_not_started(self, payload: dict[str, object]) -> bool:
        completion = self._dict(payload.get("turn_completion"))
        return (
            payload.get("delivery_method") == "active-turn-deferred"
            and completion.get("status") == "deferred"
        )

    def _delivery_turn_is_terminal(self, payload: dict[str, object]) -> bool:
        completion_turn = self._dict(self._dict(payload.get("turn_completion")).get("turn"))
        if completion_turn.get("status") in NATIVE_TURN_TERMINAL_STATUSES:
            return True
        response_turn = self._dict(self._dict(payload.get("response")).get("turn"))
        return response_turn.get("status") in NATIVE_TURN_TERMINAL_STATUSES

    def _event_from_payload(self, payload: dict[str, object]) -> MonitorEvent:
        stale = payload.get("staleHandledIds")
        return MonitorEvent(
            self._str(payload.get("monitor_event")) or "event",
            self._str(payload.get("reason")) or "review-blocked",
            self._dict(payload.get("snapshot")),
            self._dict(payload.get("fingerprint")) or None,
            tuple(item for item in stale if isinstance(item, str))
            if isinstance(stale, list)
            else (),
            self._dict(payload.get("observation")) or None,
            self._dict(payload.get("detected_change")) or None,
        )

    def _event_payload(self, event: MonitorEvent) -> dict[str, object]:
        return {
            **event.as_payload(),
            "repo": self._repo,
            "pr_number": self._pr_number,
            "session_id": self._session_id,
            "workflow_id": str(self._workflow_id),
            "worktree_id": self._worktree_id,
        }

    def _last_seen_from_work_event(self, payload: dict[str, object]) -> dict[str, object]:
        summary = self._dict(payload.get("snapshot"))
        fingerprint = self._dict(payload.get("fingerprint"))
        return {
            "comments": self._dict(fingerprint.get("comments")),
            "reviewDecision": summary.get("reviewDecision", ""),
            "headRefOid": summary.get("headRefOid", ""),
            "observation": self._dict(payload.get("observation")) or summary,
            "terminal": {},
        }

    def _delegate_result_event(
        self,
        snapshot: dict[str, object],
        delegate: dict[str, object],
        result: dict[str, object],
    ) -> MonitorEvent:
        report = {
            key: result[key]
            for key in (
                "delegation_id",
                "target_agent_id",
                "verdict",
                "summary",
                "blocking_findings",
                "result_digest",
                "outcome_ref",
            )
        }
        return MonitorEvent(
            "event",
            "delegate-result-ready",
            self._classifier.snapshot_summary(snapshot),
            {"delegate_result": report},
            detected_change={
                "delegate_result": {
                    "before": None,
                    "after": result["outcome_ref"],
                }
            },
        )

    def _has_matching_event_ack(self, payload: dict[str, object]) -> bool:
        acknowledgement = self._workflow_state.acknowledgement()
        evidence = acknowledgement.get("evidence")
        return (
            acknowledgement.get("event_id") == payload.get("event_id")
            and isinstance(evidence, list)
            and bool(evidence)
            and self._evidence_matches_reason(payload.get("reason"), evidence)
        )

    def _evidence_matches_reason(self, reason: object, evidence: list[object]) -> bool:
        values = {item for item in evidence if isinstance(item, str)}
        if reason == "ci-failed":
            return "ci_readback:failedChecks=0" in values
        if reason == "merge-dirty":
            return any(item.startswith("merge_readback:mergeState=") for item in values)
        comments_resolved = {
            "collect_comments:TOTAL=0",
            "collect_comments:UNRESOLVED_THREADS_COUNT=0",
        }.issubset(values)
        if reason == "comments-changed":
            return comments_resolved
        if reason == "review-blocked":
            return comments_resolved and "review_readback:reviewDecision=APPROVED" in values
        if reason == "mergeable-clean":
            open_clean = {
                "terminal_readback:state=OPEN",
                "terminal_readback:mergeState=CLEAN",
                "terminal_readback:reviewDecision=APPROVED",
                "terminal_readback:failedChecks=0",
                "terminal_readback:pendingChecks=0",
            }.issubset(values)
            merged_successor = "terminal_readback:state=MERGED" in values
            return (
                comments_resolved
                and (open_clean or merged_successor)
                and any(item.startswith("terminal_readback:headRefOid=") for item in values)
            )
        if reason == "merged":
            return "terminal_readback:state=MERGED" in values and any(
                item.startswith("terminal_readback:headRefOid=") for item in values
            )
        if reason == "closed-without-merge":
            return "terminal_readback:state=CLOSED" in values and any(
                item.startswith("terminal_readback:headRefOid=") for item in values
            )
        return False

    def _record_poll_error(
        self, error: json.JSONDecodeError | subprocess.CalledProcessError
    ) -> None:
        state = self._base_state(self._state.read())
        receipt: dict[str, object] = {
            "kind": error.__class__.__name__,
            "timestamp_ms": int(time.time() * 1000),
        }
        if isinstance(error, subprocess.CalledProcessError):
            receipt.update({
                "returncode": error.returncode,
                "command": " ".join(str(part) for part in error.cmd),
                "stdout": (error.stdout or "")[-2000:],
                "stderr": (error.stderr or "")[-2000:],
            })
        else:
            receipt["message"] = str(error)[-2000:]
        state["last_poll_error"] = receipt
        self._state.write(state)
        print(json.dumps({"poll_error": receipt}, ensure_ascii=False))

    def _base_state(self, current: dict[str, object]) -> dict[str, object]:
        state = {
            **{
                key: value
                for key, value in current.items()
                if key in self._PRESERVED_OBSERVATION_FIELDS
            },
            "schema_version": 4,
            "provider": "local-pr-monitor",
            "repo": self._repo,
            "pr_number": self._pr_number,
            "session_id": self._session_id,
            "workflow_id": str(self._workflow_id),
            "runtime_id": self._runtime_id,
            "worktree_id": self._worktree_id,
            "poll_interval_seconds": self._poll_interval_seconds,
            "resume_adapter": self._resume_adapter_state(),
            "launcher": self._launcher,
            "pid": os.getpid(),
            "heartbeat_at_epoch": time.time(),
        }
        if self._resume_unavailable_reason:
            state["resume_unavailable_reason"] = self._resume_unavailable_reason
        elif self._resume_adapter.available:
            state.pop("resume_unavailable_reason", None)
        if self._resume_probe_output:
            state["resume_probe_output"] = self._resume_probe_output
        elif self._resume_adapter.available:
            state.pop("resume_probe_output", None)
        if not isinstance(state.get("last_observed"), Mapping):
            last_seen = state.get("last_seen")
            state["last_observed"] = dict(last_seen) if isinstance(last_seen, Mapping) else {}
        return state

    def _resume_adapter_state(self) -> str:
        if self._resume_adapter.available:
            return "command" if self._resume_adapter._command else "app-server"
        if self._resume_unavailable_reason:
            return "unavailable"
        return "unconfigured"

    def _write_event(self, payload: dict[str, object]) -> None:
        self._state.append_event(payload)

    def _dict(self, value: object) -> dict[str, object]:
        return dict(value) if isinstance(value, Mapping) else {}

    def _str(self, value: object) -> str:
        return value if isinstance(value, str) else ""


class LocalPrMonitorApplication:
    """Runtime-owned identity와 cwd를 path-free monitor constructor로 연결합니다."""

    def __init__(self) -> None:
        """Runtime과 worktree identity resolver를 application에 귀속시킵니다."""
        self._runtime_resolver = RuntimeEnvironmentResolver()
        self._worktree_resolver = WorktreeIdentityResolver()

    def parser(self) -> argparse.ArgumentParser:
        """Legacy path selector가 없는 public CLI parser를 반환합니다.

        Returns:
            Repo, workflow, runtime, polling과 resume policy만 받는 parser입니다.
        """
        parser = argparse.ArgumentParser(description="Run the Neurath local PR monitor.")
        parser.add_argument("--repo", required=True)
        parser.add_argument("--pr-number", required=True, type=int)
        parser.add_argument("--workflow-id", required=True)
        parser.add_argument("--runtime-id", required=True)
        parser.add_argument("--poll-interval-seconds", type=int, default=30)
        parser.add_argument(
            "--resume-command",
            default=os.environ.get("NEURATH_CODEX_RESUME_COMMAND"),
        )
        parser.add_argument("--launcher", default=os.environ.get("MONITOR_LAUNCHER", "process"))
        parser.add_argument("--resume-unavailable-reason", default="")
        parser.add_argument("--resume-probe-output", default="")
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--mcp-launch-id", default="", help=argparse.SUPPRESS)
        return parser

    def run(
        self,
        arguments: Sequence[str],
        environment: Mapping[str, object],
        cwd: Path,
    ) -> int:
        """Exact existing session workflow에 monitor를 attach하고 실행합니다.

        Args:
            arguments: Repository, workflow, runtime, poll policy를 담은 CLI 인자입니다.
            environment: Current vendor session identity를 소유하는 runtime 환경입니다.
            cwd: Session locator와 canonical worktree를 함께 파생할 현재 Git 경로입니다.

        Returns:
            Monitor가 requested run mode를 정상 종료하면 성공 코드 0입니다.

        Raises:
            MonitorWorkflowStateError: Session locator와 Git control root가 다를 때 발생합니다.
            RuntimeIdentityError: Vendor runtime identity가 없거나 모순될 때 발생합니다.
            SessionKernelError: Exact session 또는 workflow attach가 invalid할 때 발생합니다.
            WorktreeRegistryError: Current cwd가 canonical worktree로 해석되지 않을 때 발생합니다.
        """
        namespace = self.parser().parse_args(tuple(arguments))
        if namespace.mcp_launch_id:
            from neurath.runtime.monitor_runtime import worker
            return worker(cwd, namespace.mcp_launch_id, namespace)
        locator = SessionLocator.from_worktree(cwd)
        worktree = self._worktree_resolver.resolve(cwd)
        if locator.control_root.resolve() != worktree.repository_control_root.resolve():
            raise MonitorWorkflowStateError("session locator and worktree control root mismatch")
        binding = self._runtime_resolver.resolve(environment)
        handle = StateHandle.attach(locator, binding)
        workflow_id = WorkflowId(namespace.workflow_id)
        monitor = LocalPrMonitor(
            handle=handle,
            workflow_id=workflow_id,
            worktree=worktree,
            runtime_id=namespace.runtime_id,
            repo=namespace.repo,
            pr_number=namespace.pr_number,
            poll_interval_seconds=namespace.poll_interval_seconds,
            resume_command=namespace.resume_command,
            launcher=namespace.launcher,
            resume_unavailable_reason=namespace.resume_unavailable_reason,
            resume_probe_output=namespace.resume_probe_output,
        )
        monitor.run(once=namespace.once)
        return 0


class LocalPrMonitorEntrypoint:
    """Process defaults를 application port에 전달합니다."""

    def run(self) -> int:
        """Current argv, environment, cwd로 monitor를 실행합니다.

        Returns:
            Monitor가 정상 종료하면 0, identity나 state route가 invalid하면 2입니다.
        """
        try:
            return LocalPrMonitorApplication().run(
                tuple(sys.argv[1:]),
                os.environ,
                Path.cwd(),
            )
        except (
            MonitorWorkflowStateError,
            RuntimeIdentityError,
            SessionKernelError,
            WorktreeRegistryError,
            subprocess.CalledProcessError,
        ) as error:
            print(str(error), file=sys.stderr)
            return 2


if __name__ == "__main__":
    raise SystemExit(LocalPrMonitorEntrypoint().run())
