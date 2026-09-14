<!-- date: 2026-09-13; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# 프로젝트 연동 설치와 유지 관리

[English](../../en/contributing/installation.md)

설치는 프로젝트 지침, 스킬, 훅, 명명된 MCP 서버를 독립된 Neurath 런타임에 연결한다. 설치기는 프로젝트 소유 설정을 보존하고 자신이 바꾼 내용을 기록한다. 이 기록을 통해 업데이트, 제거, 되돌리기에서 정확한 이전 상태를 판단한다. 사용자 관점의 흐름은 [설치 사용 안내](../usage/installation.md)에 있으며, 아래 명령은 에이전트 실행 참조다.

## 설치 상태에 맞는 진입점

아직 Neurath가 없는 대상은 Neurath MCP 서버로 초기 설치를 수행할 수 없다. 에이전트가 정상적인 Neurath 소스 체크아웃에서 다음을 실행한다.

```sh
./setup /absolute/path/to/your-project
```

대상은 Git worktree의 루트여야 한다. 사용자가 새 디렉터리를 대상으로 요청했다면 승인된 설치의 일부로 Git 저장소를 초기화한다. Git은 미리 사용할 수 있어야 한다. 소스 실행기는 `uv` 확보, Python 3.14 준비, Neurath wheel 빌드, 영속 도구 환경 설치를 수행할 수 있다. 자세한 조건은 [설치 실행 참조](setup-reference.md)에 있다.

최초 설치의 기본값은 `generic` 프로필과 두 호스트다. 이후에는 명시적으로 바꾸지 않은 프로필, 호스트, 스킬 접두어, 사용자가 수정한 연결 설정을 유지한다. 한 호스트만 선택하려면 다음처럼 실행한다.

```sh
./setup /absolute/path/to/your-project --host codex
```

Claude Code는 `--host claude-code`를 사용한다. 기존 프로젝트 스킬 이름과 겹친다면 접두어를 지정할 수 있다.

```sh
./setup /absolute/path/to/your-project --skill-prefix neurath-
```

예를 들어 공개 `debug` 스킬은 `neurath-debug`로 배치된다. 기존 사용자 스킬 이름은 유지한다. 접두어는 디렉터리 이름 충돌을 해결한다. 다른 하네스와 훅·상태 관리 책임이 겹치는지는 별도로 확인해야 한다. 이미 설치된 접두어를 바꾸려면 기존 연동을 먼저 제거한다.

## 활성 설치에서 계획과 적용

호출자가 확인되고 필요한 worktree 소유권을 가진 에이전트는 `installation_plan`으로 계획을 만든 뒤 반환된 참조를 `installation_apply`에 전달한다. 초기 설치와 같은 트랜잭션 엔진을 사용한다. 계획은 해당 호출자, worktree, 배포본, 관측한 파일 상태에 결속된다. 준비 결과에는 경로와 작업이 나오며 기존 파일 본문은 노출하지 않는다.

`installation_plan` 입력 예시:

```json
{"action":"update","key":"project-update-plan-1"}
```

반환된 `result.plan_ref`, `result.plan_id`, `result.action`, `result.changes`를 확인한다. 승인된 정확한 계획을 적용할 때는 그 참조를 사용한다.

```json
{"plan_ref":"<returned plan_ref>","key":"project-update-apply-1"}
```

꺾쇠 안의 값은 치환 위치다. 실제로 반환되지 않은 참조를 만들어 넣으면 안 된다. 호스트 신원은 네이티브 연동에서 제공하며 다른 호출의 신원 필드를 복사한다고 현재 호출이 인증되지는 않는다. 같은 요청에는 안정된 key를 유지하고, 하려는 작업이 달라지면 새 key를 사용한다.

계획의 `action`은 `install`, `update`, `uninstall`, `restore` 중 하나다. `profile`은 `generic`, `hosts`는 `codex`·`claude-code`를 지원한다. 옵션을 생략하면 기존 설치 선택을 유지한다. 되돌리기에는 반전할 실제 작업의 `installation_id`가 추가로 필요하다. 적용 결과는 설치 이력 ID와 변경 경로 수를 반환한다. 변경이 없는 재설치는 `changed: 0`일 수 있다.

입력 객체는 닫힌 스키마이므로 선언하지 않은 필드를 거부한다. 필수 `key`는 1–512자, 적용 참조는 1–71자다. `installation_id`는 최대 64자, `skill_prefix`는 최대 128자이며 접두어 형식도 검사한다. `hosts`는 최대 두 항목이다. 도구 응답에는 `ok`·`operation`과 구조화된 `result` 또는 `error`가 있다. 오류는 `code`, `message`, `state`, `retryable`, `next_action`을 포함한다. 잘못된 호출자·대상의 계획은 `plan-unavailable`, 안전하지 않은 저장 경로는 `invalid-plan-reference`, 달라진 비공개 계획은 `plan-changed`로 보고할 수 있다. 재시도 전에 반환된 복구 행동을 읽는다.

## 결과가 확인한 범위 읽기

배포본은 `diagnostics_integrity`, 대상 프로젝트는 `diagnostics_project`의 `{"protocol":true}` 입력으로 진단한다. 확인 범위는 다음과 같이 나뉜다.

| 관측 | 확인한 내용 |
| --- | --- |
| 배포본 무결성 | 패키지 파일이 manifest와 일치 |
| 파일 배치 | 설치된 바이트와 링크가 설치 이력과 일치 |
| 프로토콜 | 독립 subprocess 검사에서 시작 입력 수용과 잘못된 입력 거부 |
| 실제 호스트 활성화 | 실제 세션에서 호스트가 연동을 로드하고 실행 |
| 대상 프로젝트 검사 | 실제 프로젝트 검사 명령의 실행과 결과 |

파일 배치와 프로토콜의 성공만으로 실제 활성화를 판정하지 않는다. 파일 적용은 끝났지만 그 뒤의 진단이 실패하여 setup 결과가 실패일 수 있다. 설치 이력과 진단을 읽고 현재 상태를 판단한다. 호스트의 새 세션이나 도구 목록 새로고침이 필요할 수 있다. 프로젝트 설정은 에이전트가 처리하고, 사용자 신뢰·인증처럼 직접 조작해야 하는 단계만 구체적으로 안내한다.

## 변경 내용을 보존하며 유지 관리

업데이트와 제거는 정상적인 관리 블록 밖의 사용자 지침을 보존한다. Neurath 항목을 안전하게 분리할 수 있는 공유 훅·MCP 설정에도 같은 원칙을 적용한다. 관리 블록이나 소유 스킬 내부가 바뀌었다면 충돌로 멈춘다. 현재 내용을 덮어써서 충돌을 해소하지 않는다.

사용자가 `.neurath/project.json`을 수정하면 해당 연결 설정은 업데이트와 제거 후에도 프로젝트 소유로 남는다. 제거 후 빈 디렉터리나 이력이 남을 수 있다. 제거 대상은 관리 연동이며 임의의 프로젝트 상태 전체가 아니다. 한 프로젝트를 업데이트해도 다른 프로젝트는 자신에게 기록된 런타임을 계속 사용한다. 지원되는 되돌리기를 위해 이전 런타임도 유지한다.

중단된 설치 저널이 있으면 안정된 key로 `installation_recover`를 호출하고, 프로젝트 진단 후 새 계획을 만든다. 현재 경로가 저널의 알려진 상태와 일치할 때만 기록된 이전 상태로 복구한다. 다른 작업이 수정한 경로는 복구 충돌로 남기고 보존한다. 완료된 작업을 되돌리려면 그 설치 ID로 `restore` 계획을 만든다. 이 동작은 기록된 작업을 반전하며 임의 버전을 선택하는 기능이 아니다.

오래된 계획, 관리 파일 수정, 알 수 없는 링크, 부분 적용은 원인별로 진단한다. 정확한 오류·복구 경계는 [트랜잭션 설계](installation-design.md)에 있다. 공식 신규 버전 업데이트에는 [릴리스 업데이트](releases-reference.md)의 정확한 제안별 사용자 선택 계약이 추가로 적용된다.

구현 근거: [트랜잭션 엔진](../../../src/neurath/install/transaction.py), [MCP 설치 작업](../../../src/neurath/runtime/installation_tasks.py), [설치기 테스트](../../../tests/test_installer.py).
