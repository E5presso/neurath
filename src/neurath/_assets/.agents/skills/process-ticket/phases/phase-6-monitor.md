# CI, 리뷰와 코멘트

Local HEAD, remote branch, PR head, 독립 리뷰 subject를 대조한다. 검증된 local verdict만 `/review-pr`로 같은 PR head에 게시한다. `ai-review=success`와 GitHub `reviewDecision=APPROVED`는 별개로 확인한다.

CI failure, conflict, 사람의 actionable comment와 unresolved review thread를 처리한다. 수정이 필요하면 같은 Task의 `phase_restart`로 구현·검증·리뷰를 다시 수행하고 final head를 push한다. 변경되지 않은 상태를 반복 조회하거나 같은 검사를 근거 없이 반복하지 않는다.

지속 관찰이 필요하면 `/watch-pr`을 사용한다. 모니터가 시작됐다는 것과 실제 이벤트 전달·처리·완료를 구분한다. Peer 알림은 기존 Task를 재개하는 정보이며 새 사용자 승인이나 목표 취소가 아니다.

병합 준비는 다음 모두의 live read-back이다: PR OPEN, merge state CLEAN, required checks 완료·실패 없음, 같은 head의 ai-review와 GitHub approval, actionable human comments 및 unresolved threads 없음. `mergeable-clean`은 `merged`가 아니다.

병합이 이미 승인돼 있으면 다음 단계로 진행한다. 새로운 승인이 실제 필요한 경우에만 정확한 PR/head와 준비 결과를 보여 주고 기다린다. 승인 대기는 Task 완료가 아니다.
