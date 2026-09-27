"""PR monitor가 GitHub delta를 exact session workflow mailbox에 전달합니다."""

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app_server_resume import monitor_delivery_marker
from monitor_check_summary import CheckSummary as CheckSummary
from monitor_observation_store import MonitorObservationStore

from scripts.agent_harness.session_kernel import (
    DelegationStatus,
    SessionKernelError,
    SessionLocator,
    WorkflowId,
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

RUNTIME_SOURCE_PATHS = (
    Path(__file__),
    Path(__file__).with_name("monitor_check_summary.py"),
    Path(__file__).with_name("monitor_events.py"),
    Path(__file__).with_name("monitor_workflow_state.py"),
    Path(__file__).with_name("monitor_observation_store.py"),
    REPOSITORY_ROOT / "scripts/agent_harness/session_kernel.py",
    REPOSITORY_ROOT / "scripts/agent_harness/session_model.py",
    REPOSITORY_ROOT / "scripts/agent_harness/session_events.py",
    REPOSITORY_ROOT / "scripts/agent_harness/session_reducer.py",
    REPOSITORY_ROOT / "scripts/agent_harness/session_store.py",
    REPOSITORY_ROOT / "scripts/agent_harness/session_paths.py",
    REPOSITORY_ROOT / "scripts/agent_harness/skill_state_store.py",
    REPOSITORY_ROOT / "scripts/agent_harness/state_handle.py",
)


from monitor_events import (
    DEFAULT_REVIEW_BOT_LOGINS as DEFAULT_REVIEW_BOT_LOGINS,
    MonitorEventIdentity as MonitorEventIdentity,
    MonitorEvent as MonitorEvent,
    CommentLedger as CommentLedger,
    EventClassifier as EventClassifier,
)
from monitor_workflow_state import (
    NATIVE_TURN_TERMINAL_STATUSES as NATIVE_TURN_TERMINAL_STATUSES,
    MonitorWorkflowStateError as MonitorWorkflowStateError,
    MonitorWorkflowMutation as MonitorWorkflowMutation,
    MonitorWorkflowDocument as MonitorWorkflowDocument,
    StageMonitorEventMutation as StageMonitorEventMutation,
    ClaimMonitorEventMutation as ClaimMonitorEventMutation,
    BindMonitorTurnMutation as BindMonitorTurnMutation,
    CompleteMonitorTurnMutation as CompleteMonitorTurnMutation,
    ReleaseMonitorClaimMutation as ReleaseMonitorClaimMutation,
    ReleaseNativeOwnerMutation as ReleaseNativeOwnerMutation,
    MonitorWorkflowState as MonitorWorkflowState,
    MonitorDelegationSnapshot as MonitorDelegationSnapshot,
    MonitorDelegationReader as MonitorDelegationReader,
)

class GitHubSnapshotClient:

    def __init__(self, repo: str, pr_number: int) -> None:
        self._repo = repo
        self._pr_number = pr_number

    def load(self) -> dict[str, object]:
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

    def __init__(self, command: str | None) -> None:
        self._command = command

    @property
    def available(self) -> bool:
        """새 owner turn을 시작할 command가 준비됐는지 반환합니다.

        Returns:
            Resume command가 있으면 True입니다.
        """
        return bool(self._command)

    def resume(self, event: dict[str, object]) -> dict[str, object]:
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
