"""Pure GitHub event classification and stable occurrence identity."""

import hashlib
import json
import re
from collections.abc import Mapping


from monitor_check_summary import CheckSummary


DEFAULT_REVIEW_BOT_LOGINS = (
    "claude[bot]",
    "codex[bot]",
    "chatgpt-codex-connector[bot]",
    "github-actions[bot]",
    "review bot",
)


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

    def __init__(self, payload: dict[str, object]) -> None:
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
        if body.startswith(
            (
                "AI review 결과:",
                "## AI review 결과:",
                "AI 리뷰 결과:",
                "## AI 리뷰 결과:",
            )
        ):
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

    def __init__(
        self,
        *,
        review_bot_logins: tuple[str, ...] = DEFAULT_REVIEW_BOT_LOGINS,
        require_review_bot_head_eval: bool = True,
    ) -> None:
        self._review_bot_logins = review_bot_logins
        self._require_review_bot_head_eval = require_review_bot_head_eval

    def classify(
        self,
        snapshot: dict[str, object],
        last_seen: dict[str, object],
    ) -> MonitorEvent | None:
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
        return not body.startswith(
            (
                "AI review 결과:",
                "## AI review 결과:",
                "AI 리뷰 결과:",
                "## AI 리뷰 결과:",
                "ai-review status ",
            )
        )

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
