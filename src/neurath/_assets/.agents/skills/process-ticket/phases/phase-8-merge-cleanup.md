# Phase 8: Merge와 cleanup

merge하고 state를 갱신한 뒤 execution artifact를 정리합니다.

## 절차

1. approval 후 `gh pr merge --squash --delete-branch`로 merge합니다.
   normal mode(`merge_policy=manual`)에서는 Phase 7에서 받은 명시적 사용자 승인
   evidence(`merge_approval: explicit_user_approval=true approved_by=user`) 없이는
   이 phase를 완료할 수 없습니다. `--auto-merge` mode는
   `merge_approval: auto_merge_invocation=true` evidence를 남깁니다.
   GitHub PR comment로 승인받은 경우에는 PR 작성자와 같은 login의 사용자가 현재
   head SHA에 대해 명시적으로 병합을 요청했다는 read-back evidence를 남깁니다:
   `source=github_pr_comment comment_id=<id> author=<login> pr_author=<login>
   head_sha=<sha> approved_at=<timestamp> merge_intent=true`.
2. `gh pr merge`가 non-zero로 끝나도 로컬 cleanup 실패와 원격 merge 성공이 함께
   발생할 수 있으므로, 즉시 PR을 다시 읽고 GitHub state를 source of truth로 삼습니다.
3. PR을 다시 읽고 GitHub이 merged로 보고하는지 확인합니다.
4. 연결된 issue 또는 project status가 `Done`임을 read-back으로 확인합니다.
5. child issue에 parent가 있으면 parent의 sub-issue 목록을 읽습니다. 모든 child가
   `Done`이면 parent issue 또는 project status도 `Done`으로 갱신하고 read-back합니다.
   아직 Done이 아닌 child가 있으면 parent를 Done으로 만들지 않고 남은 child 번호를
   read-back evidence에 남깁니다. parent가 없으면 `parent_issue=none`을 남깁니다.
6. 다음 command로 exact workflow에 `merged`를 optimistic commit합니다.

   `python3 .agents/skills/process-ticket/scripts/process_state_evidence.py --workflow-id WORKFLOW_ID --field merged --value-json '{}'`

   Persistence 파일을 직접 편집하지 않습니다. 이 명령은 등록된 subscription PR의
   GitHub read-back으로 검증된 병합 결과를 저장하며, phase evidence
   `workflow_state_merged`에는 그 병합 결과의
   `state=MERGED pr_number=<n> merge_commit_oid=<sha>`를 그대로 남깁니다.
7. Canonical feature worktree를 current CWD로 유지한 채 raw state/path/session/issue/branch
   selector 없이 required workflow identity로 cleanup application을 실행합니다.

   `uv run python .agents/skills/process-ticket/scripts/merge_cleanup.py --workflow-id WORKFLOW_ID --base-branch BASE_BRANCH --remote-ref REMOTE_REF`

   대상 저장소에서 확인한 base branch와 remote ref를 반드시 명시합니다. Application은
   runtime environment의 exact actor로 `StateHandle.attach`하고 `workflow_id`의
   `SkillStateStore`에 `merge_cleanup_intent`를 explicit CAS한 뒤 CWD의
   `WorktreeIdentityResolver`와 current `WorktreeRegistry` claim을 선택합니다. Root 재시도는
   같은 intent의 exact worktree identity를 직접 사용하며 registry를 scan하지 않습니다.
   Intent는 ticket branch의 exact HEAD와 다음 cleanup reservation에 사용할 stable fencing
   token까지 고정합니다. Reservation 직전 branch/HEAD/clean status가 달라지면 아무 Git
   effect 없이 typed conflict를 반환하며, original active claim이 그대로인 다음 명령에서만
   fresh snapshot으로 intent를 explicit CAS replan합니다. Reservation은 계획된 token을
   그대로 commit하므로 같은 owner/epoch로 재생성된 foreign reservation을 adopt하지 않습니다.
   Root가 확인한 non-bare 기본 branch checkout이고 clean한지 확인하고 선택한 remote ref로 실제
   checkout을 fast-forward한 뒤 worktree를 제거합니다. Local ticket branch는 persisted
   ticket HEAD를 expected old OID로 제출하는 `git update-ref -d` CAS로만 삭제하며, 그 사이
   ref가 바뀌면 새 ref를 보존합니다. Root actual branch는 reservation 직후, merge 직전과
   직후, 최종 결과 기록 직전에 다시 확인합니다. Claim release 뒤 recovery도 remote를 다시
   fetch/sync/read-back합니다. `git update-ref`로 기본 branch ref만 이동하는 cleanup은 금지합니다.
8. 명령이 남긴 `root_checkout_cleanup_receipt`에서 root HEAD와 remote HEAD 일치, clean
   status, worktree/branch 제거, `worktree_claim_released=true`,
   `released_lease_epoch=<claimed epoch>`, `ticket_head_oid=<planned oid>`,
   `cleanup_reservation_fencing_token_sha256=<planned token digest>`를 read-back합니다.
9. terminal report는 이 파일의 `Canonical terminal report` 정규형으로만 emit합니다.
10. `gaps_detected`, `gaps_dispatched`, `spawned`의 일치성을 확인합니다.
11. terminal state, PR URL, verification, residual risk를 보고합니다.

## Parent issue 완료 전파

Parent가 없으면 `parent_issue_completion_readback: parent_issue=none`을 남깁니다. 모든 child가
Done이면 parent issue 또는 project status도 `Done`으로 바꾸고
`all_child_issues_done=true parent_completion_action=updated|already_done`을 read-back합니다.
남은 child가 있으면 parent를 바꾸지 않고
`all_child_issues_done=false parent_completion_action=not_ready remaining_child_issues=#N,...`을
기록합니다.

## Terminal state

이 phase만 `merged`를 보고할 수 있습니다.

## Canonical terminal report

다음 terminal report만 emit합니다.

```text
status: merged|mergeable-clean|failed|skipped|blocked
pr: #N (URL) | none
issue: #N
acceptance_check: PASS|partial|missing
issue_status: Done|InReview|InProgress|Backlog|Cancelled|Unknown
spawned: ISSUE-NUMBER,...|none
gaps_detected: <gap 1줄 enumeration ';'-separated>|none
gaps_dispatched: <index->ISSUE-NUMBER 또는 in-pr 매핑 ';'-separated>|none
review_done: PASS|skipped
failed_reason: 1줄
notes: 1줄
```

`review_done: PASS`는 독립 review가 Critical 0개로 수렴한 경우만 허용합니다.
Review를 실행하지 못했으면 `review_done: skipped`와 사유를 `notes`에 기록합니다.
`failed_reason`은 `status: failed`에서만 필수입니다.
`acceptance_check: partial`의 모든 gap은 `gaps_detected`와 `gaps_dispatched`에서 일대일
대응해야 하며 follow-up issue는 `spawned`에도 있어야 합니다. Notes는 gap dispatch나
failed reason을 대체하지 않습니다.

## Evidence

- `merge_command`
- `merge_approval`
- `github_merge_readback`
- `issue_status_readback`
- `parent_issue_completion_readback`
- `branch_cleanup_readback`
- `worktree_cleanup_readback`
- `root_checkout_cleanup_receipt`
- `workflow_state_merged`
- `terminal_report`
- `gap_dispatch_check`
