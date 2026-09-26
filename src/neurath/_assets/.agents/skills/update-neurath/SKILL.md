---
name: update-neurath
description: 설치된 프로젝트의 Neurath 릴리스를 한 번의 스킬 호출로 확인, 준비, 사용자 선택, 적용 및 결과 확인까지 진행합니다. 프로젝트 의존성 업데이트에는 사용하지 않습니다.
intent-class: harness.update
input-authority: verified-release-offer
not-for: [dependency.update, source.refactor]
user-invocable: true
---

# Update Neurath

현재 프로젝트에 설치된 Neurath를 업데이트합니다. 호출 한 번으로 확인부터 결과 보고까지
이어가되, 준비된 **정확한 릴리스와 파일 변경**에 대한 사용자의 선택은 중간에 받습니다.
스킬 호출 자체를 아직 보지 못한 변경에 대한 `yes`로 해석하지 않습니다.

1. `session_status`로 설치·호스트 활성화·현재 작업 공간을 확인하고, 쓰기 전에
   현재 actor의 worktree claim을 확인합니다. 다른 세션이 소유했다면
   `worktree_inspect`로 소유자를 읽고 기존 세션에 정상 종료 또는 안전한 인계를
   요청합니다. 실제 해제 전에는 claim을 재시도하거나 강제로 회수하지 않습니다.
2. `releases_status`를 읽고 `releases_check`로 안정 릴리스를 확인합니다.
   사용자가 **지금 다시 확인**하라고 명시했을 때만 `force: true`를 사용합니다.
   후보가 없거나 확인 결과가 `unavailable`이면 그 상태를 구분해 보고합니다.
3. 반환된 `offer_id`로 `releases_prepare`를 실행하고 버전, 배포본, 설치 변경,
   충돌을 검토합니다. 준비가 실패하거나 관리 파일 충돌이 있으면 적용하지 않습니다.
4. `maintenance_choice_prepare(operation="releases_choose", target_id=offer_id)`가
   반환한 **질문 전문**을 사용자에게 보여 주고 답변을 기다립니다. 실제 네이티브
   답변과 `user_choice_ref`가 확인되면 `releases_choose`에 `yes`, `no` 또는
   `later`를 기록합니다. 응답이 없거나 미리보기가 바뀌면 임의로 결정하지 않습니다.
5. `yes`일 때만 같은 `offer_id`로 `releases_apply`를 실행합니다. 반환된 설치 기록,
   선택 버전·배포본, 배치·프로토콜 진단과 `releases_status`를 읽습니다. 결과가
   불확실하면 상태를 조사하고 별도 전송으로 반복 적용하지 않습니다. 중단된
   `applying`은 보존된 상태를 확인한 뒤 필요할 때만 `releases_recover`를 사용합니다.
6. 설치 성공과 실제 호스트 활성화를 구분합니다. 호스트가 새 연결로 후속 이벤트를
   처리한 뒤 `session_status`로 활성화를 확인합니다. 현재 연결에서 관측할 수
   없다면 설치 결과와 남은 활성화 확인을 정확히 보고합니다.

릴리스 설치는 준비된 후보와 네이티브 선택에 묶인 도구 경로를 사용합니다.
`installation_plan/apply`를 따로 호출해 같은 변경을 중복 적용하지 않습니다.
기존 프로젝트 설정, 보고 동의, 수정된 관리 파일의 충돌을 보존합니다.
