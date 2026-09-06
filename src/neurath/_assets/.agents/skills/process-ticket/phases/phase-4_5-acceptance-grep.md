# Phase 4.5: Acceptance gate

commit과 PR 생성 전에 mechanical acceptance check를 실행합니다.

## 절차

1. plan 또는 GitHub Issue에 executable acceptance check가 있으면 추출합니다.
2. 각 check를 올바른 package 또는 repository root에서 실행합니다.
3. work item에 executable acceptance check가 없으면 reason과 함께
   `acceptance_missing`을 기록합니다.
4. acceptance check가 실패하는 동안 phase 5로 들어가지 않습니다.

## Evidence

다음을 기록합니다.

- `acceptance_result`
- 해당 시 `acceptance_missing`
- focused test result
- changed files

이 phase는 prose acceptance criteria를 부분 구현한 채 넘어가는 일을 막습니다.
