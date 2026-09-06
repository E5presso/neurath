## 실행

### 수용하는 경우

1. 코드를 수정한다.
2. PR 스레드에 수용 근거를 남긴다.
   - "수용합니다. [한 줄 이유]"
   - CH1 인라인 리뷰 코멘트는 반드시
     `gh api -X POST repos/$REPO/pulls/$PR/comments/$ID/replies`로 원본
     discussion에 reply한다. CH1은 일반 PR 코멘트로 우회하지 않습니다.
   - GitHub API 경로상 reply가 pending review draft로 남은 경우 즉시 제출한다.
     `gh api -X POST repos/$REPO/pulls/$PR/reviews/$REVIEW_ID/events -f event=COMMENT`
     형태의 `repos/$REPO/pulls/$PR/reviews/$REVIEW_ID/events` 호출로 제출하고,
     `gh api repos/$REPO/pulls/$PR/reviews` read-back에서 해당 head의
     `PENDING=0`을 확인한다. pending review draft만 남긴 채 처리 완료로 보고하지
     않습니다.
3. 커밋 & push한다.

### 반론하는 경우

1. 코드를 수정하지 **않는다**.
2. PR 스레드에 반론 근거를 남긴다.
   - 판단 루프에서 No가 된 질문과 구체적 근거를 포함한다.
   - 대안이 있으면 제시한다 (예: "소비자가 확정되면 그때 시그니처를 결정")
   - CH1 인라인 리뷰 코멘트는 반드시
     `gh api -X POST repos/$REPO/pulls/$PR/comments/$ID/replies`로 원본
     discussion에 reply한다. CH1은 일반 PR 코멘트로 우회하지 않습니다.
   - GitHub API 경로상 reply가 pending review draft로 남은 경우 즉시 제출한다.
     `gh api -X POST repos/$REPO/pulls/$PR/reviews/$REVIEW_ID/events -f event=COMMENT`
     형태의 `repos/$REPO/pulls/$PR/reviews/$REVIEW_ID/events` 호출로 제출하고,
     `gh api repos/$REPO/pulls/$PR/reviews` read-back에서 해당 head의
     `PENDING=0`을 확인한다. pending review draft만 남긴 채 처리 완료로 보고하지
     않습니다.
3. 사용자에게 반론 내용을 보고한다.

### 후속 이슈 생성이 필요한 경우 (스코프 초과 / 제거 약속 / 이관 약속)

스코프를 벗어난 작업을 후속 이슈으로 분리한다고 답했다면, 응답 전에 **반드시**
Gap Triage decision, 이슈 생성, 의존 설정, **처리 약속**까지 완료한다. 스레드에
"후속 이슈를 만들겠다"·"후속 이슈 #N을 만들었습니다"로만 응답하면 그 이슈는
유기된다 — `behavioral.md` Gap Triage 정합 강제.

1. `/plan-issues` 또는 `gh issue edit 또는 GitHub connector 갱신`로 이슈 생성.
2. **의존 관계(`blockedBy`) 필수 설정** — 규칙 전체는 `.agents/rules/behavioral.md` "후속 이슈 생성 시 의존 관계(`blockedBy`) 필수 설정" SSOT.
3. 생성 후 `gh issue view 또는 GitHub connector 조회`로 `relations.blockedBy`를 재확인.
4. **처리 자동 개시 (필수)** — 이슈를 만들기만 하고 끝내지 않는다. 사용자 confirm 질의 자체가 또 다른 유기 경로이므로 묻지 않는다. 본 세션 컨텍스트에서 자동 실행:
   - **기본 동작**: 본 세션 내 서브에이전트로 `/process-ticket {신규-ISSUE-NUMBER}`를 백그라운드로 즉시 실행. PR 머지를 차단하지 않으며 별도 워크트리에서 병행. 이게 default — `behavioral.md` "감지된 스펙 이슈는 후속 이슈 + 같은 세션의 서브에이전트로 즉시 분해 개시" 정합.
   - **즉시 분해가 컨텍스트상 무의미한 경우만**(예: blocker가 진행 중이거나 새 이슈가 현재 PR과 동일 파일을 수정하여 머지 충돌이 예상될 때) PR 스레드에 `blocked` 근거와 재개 조건을 명시하고, GitHub metadata에 blocker를 남긴다. Neurath에는 durable scheduling skill이 없으므로 휘발성 스케줄러를 사용하지 않는다.
   - 어느 경로든 PR 스레드 응답에 "처리 경로: {즉시 분해 / blocked metadata}"를 명시한다.
5. PR 스레드에 (a) Gap Triage decision, (b) 이슈 URL, (c) 설정된 blocker 목록,
   (d) 처리 경로 네 가지를 함께 보고한다. 하나라도 누락되면 reply 금지.
