---
name: pr-review
description: 검증된 final-local-review를 exact PR head의 ai-review 승인 신호로 게시합니다.
intent-class: pull-request.review
input-authority: github-pr-state
not-for: [source.review, pull-request-comments.triage]
argument-hint: "[pr-number]"
user-invocable: true
---

# PR Review — 검증된 로컬 판정 게시

이 skill의 실행 workflow와 게시 대상 evidence를 소유한 source workflow는 서로 다른
identity입니다. 먼저 exact runtime session 안에서 새 `PR_REVIEW_WORKFLOW_ID`를 만들고,
source `PROCESS_WORKFLOW_ID`를 입력으로 고정합니다. Session이나 workflow를 파일 경로로
추측하지 않습니다.

아래 `UPPER_SNAKE_CASE` metavariable는 source workflow와 PR identity를 먼저 읽은 뒤 actual
literal로 치환합니다. 각 command는 canonical worktree를 native `workdir`로 지정한 별도
tool call 한 physical line입니다.

- `uv run python -m scripts.skill_harness.phase_runner init --workflow-id PR_REVIEW_WORKFLOW_ID --skill pr-review --run-id PR_REVIEW_RUN_ID --north-star PR_REVIEW_NORTH_STAR`

Fresh run은 init의 `current_phase`를 사용합니다. Resume·compaction·conflict recovery만
`uv run python -m scripts.skill_harness.phase_runner current --workflow-id PR_REVIEW_WORKFLOW_ID`를 호출합니다.
Phase 1 complete 뒤 adaptive authority를 refresh하고 별도 finalize합니다.

`pr-review`는 품질 리뷰를 새로 수행하지 않습니다. `/review-code`와
`final-local-review`에서 수렴한 exact-head 판정을 GitHub branch protection이 소비할
수 있는 PR comment와 `ai-review` status로 게시합니다.

## Publication 계약

- 입력은 열린 same-repo non-draft PR, immutable runtime identity, required
  `PROCESS_WORKFLOW_ID`입니다.
- Publisher는 CWD에서 exact session을 찾고 runtime environment에서 actor identity를
  해석한 뒤 `StateHandle.attach`로 그 session에만 attach합니다.
- `ConsumedDelegationEvidenceReader`는 source workflow에서 exact head에 결속된 unique
  consumed `final-local-review` result와 content-addressed artifact를 읽습니다. 다른
  workflow, 미보고 assignment, 취소된 result, digest가 다른 artifact로 fallback하지
  않습니다.
- `FinalReviewEvidencePolicy`는 artifact에서 변경 전에 확정한 14개 검토 항목,
  C01-C14 14/14,
  blocker 0, verdict pass와 세 종류의 harness audit digest를 검증합니다.
- Local HEAD, `commit_done.sha`, `push_done.local_sha`, `push_done.remote_sha`,
  `pr_opened.head_sha`, consumed review head, review matrix head, PR `headRefOid`가 모두
  같아야 합니다.
- Live PR의 number와 URL은 `pr_opened` 및 `monitor_event_subscription`의 repo/PR과
  같은 canonical PR identity여야 합니다.
- `LOCAL_REVIEW_OUTCOME_REF`는 publisher가 digest까지 검증한 artifact reference이며
  `sha256:<64 hex>` 형식입니다.
- 검증 실패 시 comment와 status를 게시하지 않고 local review/publication 단계로
  돌아갑니다.
- 검증 성공 시 verdict는 `AUTO_APPROVE`, status는 `success`로 결정됩니다.

이 계약은 `verified final local review matrix`를 그대로 게시합니다. PR publication
단계에서 diff를 다시 평가하거나 새로운 finding 기준을 만들지 않습니다.
새 reviewer나 새 finding loop를 시작하지 않습니다.

## 실행

현재 repo를 동적으로 해석하고 PR 번호를 정규화합니다.

```bash
set -euo pipefail
export PATH="/opt/homebrew/bin:$PATH"

REPO=$(gh repo view --json nameWithOwner --jq '.nameWithOwner')
if [ -n "${ARGUMENTS:-}" ]; then
  PR_NUMBER="${ARGUMENTS#\#}"
  case "$PR_NUMBER" in
    ''|*[!0-9]*)
      echo "failed: PR 번호는 정수여야 합니다."
      exit 1
      ;;
  esac
else
  PR_NUMBER=$(gh pr view --json number --jq '.number')
fi
```

게시 도구가 검토 대상 커밋의 검증 기록, 열린 문제 기록, 변경 사항이 없는 작업 공간, PR 정보를
확인하고 같은 댓글·상태를 중복 게시하지 않도록 처리합니다. `--workflow-id`는 pr-review
runner의 workflow가 아니라 publication evidence를 소유한 source workflow입니다.

`python3 .agents/skills/pr-review/scripts/publish_final_review.py --workflow-id PROCESS_WORKFLOW_ID --repo OWNER/NAME --pr-number PR_NUMBER`

이 command는 한 physical line의 별도 tool call로 실행합니다. 반환 JSON의
`local_review_outcome_ref`를 다음 read/decision step에서 검증하며 shell command substitution,
pipeline 또는 environment variable로 같은 tool call에 합치지 않습니다.

Publisher는 동일한
`<!-- ai-review verdict=AUTO_APPROVE head=<HEAD_SHA> -->` comment가 있으면 다시
만들지 않습니다. Exact head에 `ai-review=success`가 이미 있으면 status도 중복
게시하지 않습니다.

## Read-back과 evidence

출력의 `head`, `local_review_outcome_ref`, `comment`, `status=success`를 확인합니다.
그 뒤 GitHub에서 다음 값을 다시 읽습니다.

```bash
HEAD_SHA=$(gh pr view "$PR_NUMBER" --repo "$REPO" --json headRefOid --jq '.headRefOid')
POSTED_STATE=$(gh api "repos/$REPO/commits/$HEAD_SHA/status" \
  --jq '[.statuses[] | select(.context == "ai-review")][0].state')
test "$POSTED_STATE" = "success"
```

Process-ticket owner는 publisher JSON과 GitHub read-back에서 다음 evidence를 만들고,
source workflow의 해당 phase를 exact process workflow ID로 완료할 때 함께 제출합니다.

- `pr_review_status`: `AUTO_APPROVE was posted from verified final-local-review`
- `ai_review_head_sha`: exact PR head
- `local_review_head_sha`: 같은 exact head
- `local_review_matrix_receipt`: matrix ID, 14/14, blocker 0, pass
- `local_review_outcome_ref`: publisher가 검증한 기록의 내용 지문

`.github/workflows/ai-review.yml`이 same-repo exact head, stale SHA 없음, status
creator 권한을 검증한 뒤 GitHub approval을 남깁니다. `ai-review=success`와
`reviewDecision=APPROVED`는 각각 read-back합니다.

Remote comment/status 전후의 source workflow evidence 일관성은 publisher가 다시 읽어
비교합니다. 이 read-check-publish 경계는 optimistic compare semantics이며, evidence가
바뀌면 side effect를 계속하거나 과거 snapshot을 덮어쓰지 않고 publication을 실패시켜
최신 source workflow에서 재실행하게 합니다. Workflow state mutation이 필요할 때도
`SkillStateStore`의 pure transform과 bounded CAS retry를 사용하고 외부 side effect를
mutation callback 안에서 실행하지 않습니다.

Publisher와 live read-back이 모두 성공하면 pr-review 실행 workflow를 닫습니다.

- `uv run python -m scripts.skill_harness.phase_runner complete --workflow-id PR_REVIEW_WORKFLOW_ID --phase-id 1 --status completed --summary PR_REVIEW_SUMMARY --evidence PR_METADATA_EVIDENCE --evidence LOCAL_REVIEW_RECEIPT_EVIDENCE --evidence STATUS_POSTED_EVIDENCE`
- `uv run python -m scripts.skill_harness.phase_runner finalize --workflow-id PR_REVIEW_WORKFLOW_ID --terminal-state completed`

## 완료 보고

```text
pr-review: posted
pr: #<PR_NUMBER> (<PR_URL>)
head: <HEAD_SHA>
verdict: AUTO_APPROVE
status: success
comment: <COMMENT_URL>
local-review: <LOCAL_REVIEW_OUTCOME_REF>
```

## 규칙

- PR comment는 대상 프로젝트의 문서 언어로 게시합니다.
- Comment marker는 정보용이고 승인 트리거는 exact head의 `ai-review` commit
  status입니다.
- Fork, draft, stale head, incomplete matrix, unresolved blocker, dirty worktree,
  open harness incident에서는 아무 신호도 게시하지 않습니다.
- 로컬 login, 프로젝트 ID, repo 경로를 하드코딩하지 않습니다.

$ARGUMENTS
