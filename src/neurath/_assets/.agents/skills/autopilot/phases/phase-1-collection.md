# Phase 1: 이슈 수집

target을 normalized GitHub issue set으로 해석합니다.

## 절차

1. target을 parent issue, explicit issue list, milestone, approved local plan 중
   하나로 parse합니다.
2. `gh` 또는 GitHub connector를 source of truth로 사용합니다.
3. 각 item을 다음 형태로 normalize합니다.
   - number
   - title
   - state
   - labels
   - milestone
   - parent
   - blocked-by edge
   - acceptance summary
4. 사용자가 audit을 명시하지 않았다면 이미 closed인 티켓은 구현 wave에서 제외합니다.
   열린 티켓은 acceptance를 현재 소스와 병합된 변경·검증 근거에 대조합니다. 이미 충족된
   티켓은 승인된 범위 안에서 실제로 duplicate로 닫고, 근거와 종료 상태를 다시 확인합니다.
   단순히 구현된 것 같다는 추정이나 중복 후보 표시로 수집을 끝내지 않습니다.
5. `source_of_truth`, `normalized_items`, `total_issue_count`를 기록합니다. 중복 종료는 전체
   처리 티켓 수에 포함하되 새 구현·수정 수와 별도로 집계합니다.
6. 남은 작업과 새로 발견한 필수 수정을 명명 MCP task_define으로 측정 가능한 태스크에
   보존합니다. task_list의 안정된 ID로 추적하고 완료 조건과 출처를 연결합니다. 중복 무효
   처리에는 이미 충족한 결과 참조와 무효 사유를 사용합니다. 별도 태스크 검토는
   선택 사항이며 해당 워크플로의 기존 검토 요건은 유지합니다.

## 통과 조건

target을 모호하지 않게 해석할 수 없으면 `blocked`로 중단합니다.
