# deliver — 검증된 문서 전달

같은 소스와 입력에 대한 기존 검증을 확인한다. 이후 변경이 있었거나 대상 저장소가
추가 검사를 요구할 때만 `.neurath/project.json`의 실제 검사 명령을 native 도구로
실행한다. 실패한 검사를 통과로 기록하지 않는다.

사용자가 요청한 범위에 commit 또는 PR이 포함되면 같은 Task에 선언된 `commit`,
`create-pr` 하위 스킬을 필요한 순서로 끝까지 수행한다. 실제 branch·head·remote·PR
결과를 다시 읽고 `delivery_result`로 기록한다. 게시가 요청되지 않았다면 로컬 결과와
그 전달 범위를 정확히 보고한다.

하위 스킬 뒤에는 `phase_read`로 sync-docs의 deliver에 돌아왔음을 확인한다.
이 phase와 원래 사용자 인수 조건이 모두 충족되기 전에 Task를 완료하지 않는다.
