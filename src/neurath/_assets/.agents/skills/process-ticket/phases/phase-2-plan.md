# Phase 2: 구현 계획

편집 전에 작은 구현 계획을 작성합니다.

## 절차

1. scope를 file, package, test, docs에 mapping합니다.
2. 먼저 작성할 failing 또는 characterizing test를 지목합니다.
3. 새 class name, public method name, domain term이 DD와 naming rule을 따르는지
   확인합니다.
4. import boundary, service boundary, shared package constraint를 식별합니다.
5. focused test와 pre-commit을 포함한 verification command를 나열합니다.
6. `--require-approval`이 설정됐으면 phase 3 전에 approval을 요청합니다.

## 출력

나중에 PR body에 들어갈 수 있을 만큼 짧게 유지합니다.

- intent
- 변경 예상 file
- test-first path
- domain dictionary lookup과 naming plan
- verification command
- risk와 rollback note

## Blocker

scope를 정의하기 위해 product decision이 필요하면 `/plan-issues`로 돌아갑니다.

실행 요청된 ticket이 parent급이거나 단일 session에서 안전하게 완료할 수 없는
scope이면 임의로 child issue를 생성하지 않습니다. 이 경우 phase를 `blocked`로
닫고, 사용자가 decomposition을 명시적으로 승인할 때까지 `/create-ticket`을 호출하지
않습니다.
