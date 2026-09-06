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
4. 사용자가 audit을 명시하지 않았다면 closed 또는 already merged work는 제외합니다.
5. `source_of_truth`, `normalized_items`, `total_issue_count`를 기록합니다.

## 통과 조건

target을 모호하지 않게 해석할 수 없으면 `blocked`로 중단합니다.
