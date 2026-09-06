#!/usr/bin/env python3
"""검증된 canonical final-local-review를 exact PR head의 승인 신호로 게시합니다."""

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.agent_harness.artifact_store import ArtifactStoreError
from scripts.agent_harness.delegation_evidence import (
    ConsumedDelegationEvidenceReader,
    ConsumedDelegationEvidenceSnapshot,
    DelegationEvidenceError,
    FinalReviewEvidencePolicy,
    FinalReviewVerification,
)
from scripts.agent_harness.harness_incident import (
    HarnessIncidentValidationError,
    validate_harness_incidents,
)
from scripts.agent_harness.session_kernel import (
    SessionKernelError,
    SessionLocator,
    WorkflowId,
)
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityError,
    StateHandle,
)

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class PublicationError(RuntimeError):
    """승인 신호를 안전하게 게시할 수 없음을 나타냅니다."""


class PublicationReceipt:
    """Exact-head publication에 필요한 검증된 로컬 리뷰 증거입니다."""

    __slots__ = ("head_sha", "matrix_id", "outcome_ref", "pr_url")

    def __init__(
        self,
        *,
        head_sha: str,
        matrix_id: str,
        outcome_ref: str,
        pr_url: str,
    ) -> None:
        """Remote publication이 공유해야 할 immutable identity를 생성합니다.

        Args:
            head_sha: Local review와 remote PR이 공유하는 exact head입니다.
            matrix_id: Frozen canonical review matrix identity입니다.
            outcome_ref: Digest-verified final review artifact reference입니다.
            pr_url: 승인 status가 가리킬 canonical PR URL입니다.
        """
        object.__setattr__(self, "head_sha", head_sha)
        object.__setattr__(self, "matrix_id", matrix_id)
        object.__setattr__(self, "outcome_ref", outcome_ref)
        object.__setattr__(self, "pr_url", pr_url)

    head_sha: str
    """Local review와 remote PR이 공유하는 exact head SHA입니다."""

    matrix_id: str
    """Frozen canonical review matrix 식별자입니다."""

    outcome_ref: str
    """Digest verification을 통과한 final review artifact reference입니다."""

    pr_url: str
    """승인 signal이 가리키는 canonical PR URL입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성된 publication receipt 변경을 거부합니다.

        Args:
            name: 변경하려는 attribute 이름입니다.
            value: 새로 대입하려는 값입니다.

        Raises:
            AttributeError: Receipt는 생성 뒤 immutable입니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class PublicationEvidenceSnapshot:
    """Canonical consumed delegation과 bounded final-review verification을 결합합니다."""

    __slots__ = ("delegation", "review")

    def __init__(
        self,
        *,
        delegation: ConsumedDelegationEvidenceSnapshot,
        review: FinalReviewVerification,
    ) -> None:
        """Shared read model과 final-review policy 결과를 함께 고정합니다.

        Args:
            delegation: Exact process snapshot에서 읽은 consumed delegation evidence입니다.
            review: Canonical 14-row pass matrix를 검증한 bounded receipt입니다.
        """
        object.__setattr__(self, "delegation", delegation)
        object.__setattr__(self, "review", review)

    delegation: ConsumedDelegationEvidenceSnapshot
    """Workflow skill-state, assignment, artifact를 포함한 shared immutable evidence입니다."""

    review: FinalReviewVerification
    """Publication에 필요한 bounded final-review verification입니다."""

    @property
    def skill_state(self) -> Mapping[str, object]:
        """Canonical workflow-local operational state를 반환합니다.

        Returns:
            Shared evidence snapshot이 소유하는 immutable skill-state mapping입니다.
        """
        return self.delegation.skill_state

    def same_evidence(self, other: PublicationEvidenceSnapshot) -> bool:
        """Concurrent read가 publication-relevant canonical evidence를 유지하는지 판정합니다.

        Args:
            other: Remote side effect 직전에 다시 읽은 latest evidence입니다.

        Returns:
            Workflow revision, delegation, review, skill-state가 모두 같으면 `True`입니다.
        """
        return (
            self.delegation.workflow_revision == other.delegation.workflow_revision
            and self.delegation.delegation_id == other.delegation.delegation_id
            and self.delegation.outcome_ref == other.delegation.outcome_ref
            and self.delegation.skill_state == other.delegation.skill_state
            and self.review.head_sha == other.review.head_sha
            and self.review.matrix_id == other.review.matrix_id
            and self.review.verified_rows == other.review.verified_rows
            and self.review.verdict == other.review.verdict
            and self.review.blocking_finding_count == other.review.blocking_finding_count
        )

    def __setattr__(self, name: str, value: object) -> None:
        """생성된 publication evidence 변경을 거부합니다.

        Args:
            name: 변경하려는 attribute 이름입니다.
            value: 새로 대입하려는 값입니다.

        Raises:
            AttributeError: Snapshot은 생성 뒤 immutable입니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class CanonicalPublicationEvidenceReader:
    """Shared consumed-delegation read model을 publication receipt로 좁힙니다."""

    def __init__(self, handle: StateHandle, workflow_id: WorkflowId) -> None:
        """Exact session/workflow reader와 final-review policy를 조립합니다.

        Args:
            handle: Runtime identity로 attach한 exact session facade입니다.
            workflow_id: Process-ticket publication evidence를 소유하는 workflow입니다.
        """
        self._reader = ConsumedDelegationEvidenceReader(handle, workflow_id)
        self._policy = FinalReviewEvidencePolicy()

    def read(self, *, local_head: str) -> PublicationEvidenceSnapshot:
        """Exact head의 unique consumed final review를 canonical state에서 읽습니다.

        Args:
            local_head: Current clean worktree에서 읽은 full commit SHA입니다.

        Returns:
            Shared delegation evidence와 canonical review verification입니다.
        """
        evidence = self._reader.read(
            kind="final-local-review",
            reviewed_head_sha=local_head,
        )
        return PublicationEvidenceSnapshot(
            delegation=evidence,
            review=self._policy.verify(evidence),
        )


class PublicationPolicy:
    """Canonical workflow evidence와 live PR을 exact-head publication receipt로 검증합니다."""

    def validate(
        self,
        *,
        snapshot: PublicationEvidenceSnapshot,
        pr: Mapping[str, object],
        local_head: str,
    ) -> PublicationReceipt:
        """Workflow evidence, consumed review, local head, live PR identity를 함께 검증합니다.

        Args:
            snapshot: Exact workflow/delegation/artifact에서 읽은 publication evidence입니다.
            pr: GitHub에서 읽은 live PR metadata입니다.
            local_head: 현재 clean worktree의 exact head SHA입니다.

        Returns:
            Remote comment/status publication에 사용할 immutable receipt입니다.

        Raises:
            PublicationError: Publication identity 또는 exact-head invariant가 불완전할 때
                발생합니다.
        """
        head_sha = pr.get("headRefOid")
        pr_url = pr.get("url")
        pr_number = pr.get("number")
        if (
            pr.get("state") != "OPEN"
            or not isinstance(head_sha, str)
            or SHA_PATTERN.fullmatch(head_sha) is None
        ):
            raise PublicationError("열린 PR의 exact head SHA를 확인하지 못했습니다.")
        if pr.get("isDraft") is not False or pr.get("isCrossRepository") is not False:
            raise PublicationError("draft 또는 fork PR에는 자동 승인 신호를 게시할 수 없습니다.")
        if not isinstance(pr_url, str) or not pr_url.startswith("https://github.com/"):
            raise PublicationError("PR URL을 확인하지 못했습니다.")

        state = snapshot.skill_state
        canonical_pr_number = self._nested(state, "pr_opened", "number")
        canonical_pr_url = self._nested(state, "pr_opened", "url")
        subscription_repo = self._nested(state, "monitor_event_subscription", "repo")
        subscription_pr_number = self._nested(
            state,
            "monitor_event_subscription",
            "pr_number",
        )
        expected_pr_url = (
            f"https://github.com/{subscription_repo}/pull/{canonical_pr_number}"
            if isinstance(subscription_repo, str)
            and subscription_repo.strip()
            and isinstance(canonical_pr_number, int)
            and not isinstance(canonical_pr_number, bool)
            else None
        )
        if (
            not isinstance(pr_number, int)
            or isinstance(pr_number, bool)
            or pr_number != canonical_pr_number
            or pr_number != subscription_pr_number
            or pr_url != canonical_pr_url
            or pr_url != expected_pr_url
        ):
            raise PublicationError("canonical PR identity와 live PR identity가 일치하지 않습니다.")

        review = snapshot.review
        required_heads = (
            local_head,
            self._nested(state, "commit_done", "sha"),
            self._nested(state, "push_done", "local_sha"),
            self._nested(state, "push_done", "remote_sha"),
            self._nested(state, "pr_opened", "head_sha"),
            snapshot.delegation.reviewed_head_sha,
            review.head_sha,
        )
        if any(candidate != head_sha for candidate in required_heads):
            raise PublicationError("local review, commit, push, PR head SHA가 일치하지 않습니다.")
        if review.verdict != "pass" or review.blocking_finding_count != 0:
            raise PublicationError(
                "final-local-review blocker 또는 non-pass verdict가 남아 있습니다."
            )
        if review.row_count != 14 or review.verified_rows != tuple(
            f"C{index:02d}" for index in range(1, 15)
        ):
            raise PublicationError("final-local-review C01-C14 검증이 완전하지 않습니다.")
        return PublicationReceipt(
            head_sha=head_sha,
            matrix_id=review.matrix_id,
            outcome_ref=review.outcome_ref,
            pr_url=pr_url,
        )

    def build_comment(self, receipt: PublicationReceipt) -> str:
        """Local verdict provenance를 포함한 결정적 한국어 comment를 만듭니다.

        Args:
            receipt: 검증된 final-local-review publication receipt입니다.

        Returns:
            Exact-head AUTO_APPROVE marker로 끝나는 Markdown입니다.
        """
        return (
            "## AI 리뷰 결과: AUTO_APPROVE\n\n"
            f"Exact remote head `{receipt.head_sha}`가 검증된 최종 로컬 리뷰와 일치합니다.\n\n"
            f"- review matrix: `{receipt.matrix_id}`\n"
            "- verified rows: `C01-C14 (14/14)`\n"
            "- blocking findings: `0`\n"
            f"- local review receipt: `{receipt.outcome_ref}`\n\n"
            f"<!-- ai-review verdict=AUTO_APPROVE head={receipt.head_sha} -->"
        )

    def _nested(self, mapping: Mapping[str, object], *keys: str) -> object | None:
        value: object = mapping
        for key in keys:
            if not isinstance(value, Mapping):
                return None
            value = value.get(key)
        return value


class PublicationCommandGateway:
    """Git과 GitHub CLI side effect를 validated JSON/text operations로 캡슐화합니다."""

    def run(self, args: Sequence[str], *, input_text: str | None = None) -> str:
        """Command를 shell 없이 실행하고 성공 stdout을 반환합니다.

        Args:
            args: Executable과 arguments를 분리한 command sequence입니다.
            input_text: Optional standard input payload입니다.

        Returns:
            Exit code 0 command의 stdout입니다.

        Raises:
            PublicationError: Command 실행 또는 exit code가 실패하면 발생합니다.
        """
        result = subprocess.run(
            tuple(args),
            check=False,
            capture_output=True,
            input=input_text,
            text=True,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise PublicationError(f"command failed ({' '.join(args)}): {detail}")
        return result.stdout

    def load_json(self, args: Sequence[str]) -> object:
        """Command stdout을 JSON value로 decode합니다.

        Args:
            args: JSON stdout을 반환해야 하는 command sequence입니다.

        Returns:
            Decoded JSON value입니다.

        Raises:
            PublicationError: Command 또는 JSON decode가 실패하면 발생합니다.
        """
        output = self.run(args)
        try:
            return json.loads(output)
        except json.JSONDecodeError as error:
            raise PublicationError(f"JSON read-back failed ({' '.join(args)}): {error}") from error

    def read_pr(self, repo: str, pr_number: int) -> Mapping[str, object]:
        """Live PR publication identity를 GitHub에서 읽습니다.

        Args:
            repo: GitHub owner/name입니다.
            pr_number: 조회할 positive PR number입니다.

        Returns:
            Exact-head policy가 검증할 live PR object입니다.

        Raises:
            PublicationError: GitHub command 또는 PR object shape가 invalid하면 발생합니다.
        """
        pr = self.load_json((
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            "number,state,isDraft,isCrossRepository,headRefOid,url",
        ))
        if not isinstance(pr, dict):
            raise PublicationError("PR metadata read-back 형식이 올바르지 않습니다.")
        return pr

    def existing_comment_url(self, repo: str, pr_number: int, marker: str) -> str | None:
        """Exact-head marker를 이미 포함하는 idempotent comment URL을 찾습니다.

        Args:
            repo: GitHub owner/name입니다.
            pr_number: 조회할 canonical PR number입니다.
            marker: Exact head와 verdict를 포함한 stable marker입니다.

        Returns:
            Existing comment URL 또는 없으면 `None`입니다.

        Raises:
            PublicationError: GitHub command 또는 comment page shape가 invalid하면 발생합니다.
        """
        pages = self.load_json((
            "gh",
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repo}/issues/{pr_number}/comments?per_page=100",
        ))
        if not isinstance(pages, list):
            raise PublicationError("PR comment read-back 형식이 올바르지 않습니다.")
        for page in pages:
            if not isinstance(page, list):
                continue
            for comment in page:
                if not isinstance(comment, dict):
                    continue
                if marker in str(comment.get("body", "")):
                    url = comment.get("html_url")
                    return url if isinstance(url, str) else None
        return None

    def current_repository(self) -> str:
        """Current worktree의 GitHub owner/name을 읽습니다.

        Returns:
            Non-empty repository identity입니다.

        Raises:
            PublicationError: GitHub command 또는 repository identity가 invalid하면 발생합니다.
        """
        payload = self.load_json(("gh", "repo", "view", "--json", "nameWithOwner"))
        if not isinstance(payload, dict):
            raise PublicationError("repository metadata read-back 형식이 올바르지 않습니다.")
        repo = payload.get("nameWithOwner")
        if not isinstance(repo, str) or not repo.strip():
            raise PublicationError("repository identity를 확인하지 못했습니다.")
        return repo.strip()


class FinalReviewPublisher:
    """Canonical review evidence를 idempotent GitHub comment/status로 게시합니다."""

    def __init__(
        self,
        *,
        handle: StateHandle,
        workflow_id: WorkflowId,
        worktree: Path,
        gateway: PublicationCommandGateway,
    ) -> None:
        """Exact state reader, Git worktree, external gateway를 publisher에 고정합니다.

        Args:
            handle: Runtime-owned identity로 exact existing session에 attach한 facade입니다.
            workflow_id: Publication evidence를 소유하는 exact workflow입니다.
            worktree: Git identity와 incident evidence를 검증할 current CWD입니다.
            gateway: Shell-free Git/GitHub command boundary입니다.
        """
        self._reader = CanonicalPublicationEvidenceReader(handle, workflow_id)
        self._worktree = worktree.resolve()
        self._gateway = gateway
        self._policy = PublicationPolicy()

    def publish(self, *, repo: str, pr_number: int) -> dict[str, object]:
        """Canonical receipt를 검증하고 comment/status를 게시해 read-back합니다.

        Args:
            repo: Canonical workflow route와 대조할 GitHub owner/name입니다.
            pr_number: Canonical workflow route와 대조할 positive PR number입니다.

        Returns:
            Exact head, comment URL, status 게시 여부를 담은 result object입니다.

        Raises:
            PublicationError: 검증, 게시 또는 read-back이 실패할 때 발생합니다.
            DelegationEvidenceError: Canonical delegation evidence가 불완전할 때 발생합니다.
        """
        if not repo.strip() or pr_number <= 0:
            raise PublicationError("repository와 positive PR number가 필요합니다.")
        local_head = self._gateway.run((
            "git",
            "-C",
            str(self._worktree),
            "rev-parse",
            "HEAD",
        )).strip()
        if self._gateway.run(("git", "-C", str(self._worktree), "status", "--porcelain")).strip():
            raise PublicationError("worktree가 clean하지 않습니다.")
        snapshot = self._reader.read(local_head=local_head)
        validate_harness_incidents(
            None,
            self._worktree,
            state=snapshot.delegation.skill_state_payload(),
        )
        receipt = self._policy.validate(
            snapshot=snapshot,
            pr=self._gateway.read_pr(repo, pr_number),
            local_head=local_head,
        )
        comment_body = self._policy.build_comment(receipt)
        marker = f"<!-- ai-review verdict=AUTO_APPROVE head={receipt.head_sha} -->"
        comment_url = self._gateway.existing_comment_url(repo, pr_number, marker)
        comment_posted = comment_url is None
        if comment_posted:
            self._require_stable_evidence(snapshot, local_head)
            self._policy.validate(
                snapshot=snapshot,
                pr=self._gateway.read_pr(repo, pr_number),
                local_head=local_head,
            )
            response_text = self._gateway.run(
                (
                    "gh",
                    "api",
                    "-X",
                    "POST",
                    f"repos/{repo}/issues/{pr_number}/comments",
                    "--input",
                    "-",
                ),
                input_text=json.dumps({"body": comment_body}, ensure_ascii=False),
            )
            try:
                response: object = json.loads(response_text)
            except json.JSONDecodeError as error:
                raise PublicationError("게시된 PR comment 응답이 JSON이 아닙니다.") from error
            comment_url = response.get("html_url") if isinstance(response, dict) else None
            if not isinstance(comment_url, str):
                raise PublicationError("게시된 PR comment URL을 확인하지 못했습니다.")

        status = self._gateway.load_json((
            "gh",
            "api",
            f"repos/{repo}/commits/{receipt.head_sha}/status",
        ))
        statuses = status.get("statuses") if isinstance(status, dict) else None
        already_success = isinstance(statuses, list) and any(
            isinstance(item, dict)
            and item.get("context") == "ai-review"
            and item.get("state") == "success"
            for item in statuses
        )
        if not already_success:
            self._require_stable_evidence(snapshot, local_head)
            self._policy.validate(
                snapshot=snapshot,
                pr=self._gateway.read_pr(repo, pr_number),
                local_head=local_head,
            )
            self._gateway.run((
                "gh",
                "api",
                "-X",
                "POST",
                f"repos/{repo}/statuses/{receipt.head_sha}",
                "-f",
                "state=success",
                "-f",
                "context=ai-review",
                "-f",
                "description=AI review verdict: AUTO_APPROVE",
                "-f",
                f"target_url={receipt.pr_url}",
            ))
        read_back = self._gateway.load_json((
            "gh",
            "api",
            f"repos/{repo}/commits/{receipt.head_sha}/status",
        ))
        read_back_statuses = read_back.get("statuses") if isinstance(read_back, dict) else None
        if not isinstance(read_back_statuses, list) or not any(
            isinstance(item, dict)
            and item.get("context") == "ai-review"
            and item.get("state") == "success"
            for item in read_back_statuses
        ):
            raise PublicationError("exact head의 ai-review=success read-back에 실패했습니다.")
        return {
            "pr": pr_number,
            "head": receipt.head_sha,
            "verdict": "AUTO_APPROVE",
            "status": "success",
            "comment": comment_url,
            "comment_posted": comment_posted,
            "status_posted": not already_success,
            "local_review_outcome_ref": receipt.outcome_ref,
        }

    def _require_stable_evidence(
        self,
        expected: PublicationEvidenceSnapshot,
        local_head: str,
    ) -> None:
        current = self._reader.read(local_head=local_head)
        if not expected.same_evidence(current):
            raise PublicationError("canonical publication evidence changed during read-back")


class PublicationApplication:
    """CWD와 runtime environment를 exact publication service에 연결합니다."""

    def run(
        self,
        arguments: Sequence[str],
        environment: Mapping[str, object],
        cwd: Path,
    ) -> int:
        """CLI selector를 검증하고 exact session/workflow publication을 실행합니다.

        Args:
            arguments: Required workflow와 PR route를 담은 CLI arguments입니다.
            environment: Vendor runtime이 소유하는 exact session/actor identity입니다.
            cwd: Session locator와 Git validation의 current worktree입니다.

        Returns:
            성공은 0, identity/state/publication failure는 1입니다.
        """
        args = self._parser().parse_args(tuple(arguments))
        try:
            locator = SessionLocator.from_worktree(cwd)
            binding = RuntimeEnvironmentResolver().resolve(environment)
            handle = StateHandle.attach(locator, binding)
            gateway = PublicationCommandGateway()
            repo = args.repo or gateway.current_repository()
            publisher = FinalReviewPublisher(
                handle=handle,
                workflow_id=WorkflowId(args.workflow_id),
                worktree=cwd,
                gateway=gateway,
            )
            result = publisher.publish(repo=repo, pr_number=args.pr_number)
        except (
            ArtifactStoreError,
            DelegationEvidenceError,
            HarnessIncidentValidationError,
            OSError,
            PublicationError,
            RuntimeIdentityError,
            SessionKernelError,
            subprocess.CalledProcessError,
            ValueError,
        ) as error:
            print(f"failed: {error}")
            return 1
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    def _parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser()
        parser.add_argument("--workflow-id", required=True)
        parser.add_argument("--pr-number", type=int, required=True)
        parser.add_argument("--repo")
        return parser


if __name__ == "__main__":
    raise SystemExit(PublicationApplication().run(tuple(sys.argv[1:]), os.environ, Path.cwd()))
