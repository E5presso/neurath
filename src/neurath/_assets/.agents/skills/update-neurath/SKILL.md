---
name: update-neurath
description: 설치된 프로젝트의 Neurath 릴리스를 한 번의 스킬 호출로 확인, 준비, 사용자 선택, 적용 및 결과 확인까지 진행합니다. 프로젝트 의존성 업데이트에는 사용하지 않습니다.
intent-class: harness.update
input-authority: verified-release-offer
not-for: [dependency.update, source.refactor]
user-invocable: true
---

# Update Neurath

설치된 Neurath의 공개 안정 릴리스를 확인·준비하고 정확한 변경에 대한 사용자 선택을 받아 적용한다. 호출 자체를 아직 보지 못한 변경의 동의로 해석하지 않는다. 같은 Task에 `skill_start(skill="update-neurath")`하고 아래 단계를 순서대로 수행한다.

1. **inspect**: `session_status`, `task_list`, `worktree_read`로 실제 설치·실행 배포본, 미완료 작업과 writer를 확인한다. 다른 actor의 claim을 강제로 회수하지 않는다. CLI 유지보수는 설치된 `.neurath/run`을 native 명령 도구로 호출하며 현재 호스트 권한을 유지한다.
2. **check_release**: 유지보수 CLI의 캐시·설치 상태 쓰기 전에 대상 checkout의 writer lease를 정상 획득한다. `releases status`와 `releases check`로 안정 릴리스와 정확한 asset identity를 읽는다. 사용자가 지금 다시 확인하라고 명시했을 때만 `check --force`를 사용한다. current, no-release, unavailable을 구분한다. 버전 번호만 같다고 같은 배포본이라 판단하지 않는다.
3. **prepare**: offer가 있으면 `releases prepare <offer-id>`로 파일 변경과 충돌을 준비한다. 버전·wheel·배포본·변경 범위를 확인한다. offer가 없으면 실제 조회 결과를 기록하고 다음 단계의 비적용 사유를 연결한다. 실패나 충돌을 통과로 기록하지 않는다.
4. **choose**: 정확히 준비된 변경에 대해 현재 native 질문 도구로 yes/no/later를 받는다. 응답 원문을 `source_read`로 확인하고 `approval_record(action="decision")`에 정확한 quote와 실행할 명령·cwd를 연결한다. 이 기록은 원문의 승인 의미에 대한 에이전트 판단이며 인간 발화의 자동 증명이 아니다. 그 뒤 `releases choose <offer-id> <yes|no|later> --user-confirmed`로 선택을 저장한다. 플래그 자체는 동의 근거가 아니다. 실제 응답이 없거나 미리보기가 바뀌면 선택하지 않는다. offer가 없으면 선택하지 않은 이유를 기록한다.
5. **apply**: yes인 같은 offer만 `releases apply <offer-id>`로 적용한다. no/later/no-offer는 적용하지 않고 실제 이유를 기록한다. 결과가 불확실하면 status와 보존된 작업 기록을 읽고 중단된 applying일 때만 `releases recover`를 사용한다. 같은 변경을 별도 install/apply 경로로 중복 실행하지 않는다.
6. **activation**: 설치 결과, 실제 wheel 배포본, 배치·프로토콜 검사와 현재 native MCP의 실행 배포본을 대조한다. 새 연결의 `session_status`로 활성화를 확인한다. 필요한 재시작은 현재 사용자가 승인한 범위에서 `reconnect-host` 하위 스킬로 수행한다. 실제 활성화가 요청 결과에 필요하지만 확인되지 않으면 Task를 대기로 보존한다.

각 단계는 `phase_read`의 조건을 실제 근거로 완료한다. no/later/no-offer도 모든 단계에서 해당하지 않는 행동과 그 근거를 명확히 기록한다. 적용을 하지 않은 결정은 설치 성공이 아니다. 사용자 설정·기존 보고 동의·수정된 관리 파일과 그 충돌을 보존한다. Task의 원래 인수 조건까지 충족해야 완료한다.
