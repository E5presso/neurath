# Phase 5: Commit과 PR

검증된 변경을 publication skill로 게시합니다.

## 절차

1. commit이 요청됐거나 PR이 필요하면 `/commit`을 실행합니다.
2. Push 전에 exact local HEAD를 대상으로 independent `final-local-review` delegate를
   실행합니다. HEAD를 먼저 read tool로 읽고, 별도 direct command
   `delegate_state.py --workflow-id WORKFLOW_ID begin --reviewed-head-sha FULL_HEAD_SHA`에
   literal로 전달하며 canonical 14개
   `--verified-review-row`를 모두 제출한 pass artifact를 owner가 exact
   `delegation_id + target_agent_id + outcome_ref`로 consume합니다.
3. Finding이 있으면 local에서 수정·검증·commit하고 새로운 exact HEAD에 대해
   `final-local-review`를 다시 실행합니다.
   이때 티켓의 최초 전수 리뷰가 아니라 **후속 재리뷰**(finding 반영, merge conflict
   해소, comment 반영 커밋)라면 delta 재검증을 사용합니다: reviewer는 직전 검증
   head부터의 증분 diff를 읽고 영향받는 row만 `--verified-review-row`로 백지
   재검증하며, 영향 없는 row는 `--inherited-review-row`와
   `--inherited-from-head <직전 검증 head>`로 상속합니다. 상속은 선언이 아니라
   증명입니다 — gate가 직전 통과 결과의 존재, 그 head가 현재 head의 git 조상임,
   최소 1개 row의 실제 재검증을 모두 검증하며 하나라도 어긋나면 거부합니다.
   어떤 row가 영향권인지 모호하면 재검증 쪽으로 분류합니다.
4. 로컬 검토 결과의 `reviewed_head_sha`, local HEAD, commit SHA가 일치하면
   `/create-pr` 또는 기존 branch push를 실행합니다.
5. 해당 event가 발생하면 아래 helper를 각 field에 실행해 `commit_done`, `push_done`,
   `pr_opened`를 exact workflow의 `SkillStateStore`에 기록합니다.

   `python3 .agents/skills/process-ticket/scripts/process_state_evidence.py --workflow-id WORKFLOW_ID --field FIELD --value-json JSON_VALUE`

   Persistence 파일이나 workflow payload를 직접 변경하지 않습니다.
6. `/create-pr`에는 phase 4.5 acceptance 결과를 전달합니다. executable
   acceptance가 있으면 `acceptance_check: PASS` 근거를, 없으면
   `acceptance_check: missing`과 reason을 PR body에 포함시킵니다.
7. PR 생성 후 PR URL, linked issue, assignee/reviewer/label metadata, body의
   acceptance handoff를 다시 읽습니다. read-back이 실패하면 monitor로 가지
   않습니다.
   PR title, body, publication commit subject는 대상 프로젝트의 metadata 정책을
   따릅니다. `git log -1 --format=%s`를 포함한 실제 read-back으로 `scripts.skill_harness.github_metadata_language`를
   실행하고 `policy_passed=true`를 확인합니다. 특정 언어나 issue prefix를
   요구하는 옵션은 해당 저장소가 명시적으로 설정했을 때만 사용합니다.

8. PR 생성이 missing remote 또는 credential로 blocked되면 정확한 reason과 함께
   `blocked`로 finalize합니다.

## 필수 evidence

- commit했다면 commit SHA
- exact `final-local-review` 검토 결과와 `local_review_head_sha`
- `matrix_id`, exact head, 14/14 verified row, blocker 0, `harness_audit=true`,
  `audit_evidence=3`을 담은 `local_review_matrix_receipt`
- push했다면 `HEAD`와 upstream SHA 일치
- PR을 만들었다면 PR URL과 number
- PR read-back metadata
- GitHub metadata의 대상 프로젝트 정책 검사 결과
- publication commit subject issue prefix와 ticket 번호 일치 결과
- acceptance handoff result
- 이미 실행한 verification command
- 연결된 plan 또는 GitHub Issue
