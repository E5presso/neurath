# 구조와 실행 경계
<!-- date: 2026-09-07; synced_from: source and documentation at 2456ae73ffaf818c04ea4419574218df36852805; English and Korean editions updated together -->

[사용 안내](../usage/index.md) · [기여자 안내](index.md)


[English](../../en/contributing/architecture.md) · **한국어**

Neurath는 자체 런타임·계약·배포 목록을 가진 독립 하네스 키트입니다.
대상 프로젝트의 소스, 스택, 문서 구조, 브랜치명과 개발환경을 내장하지 않습니다.

| 위치 | 역할 |
| --- | --- |
| `src/neurath/_assets/scripts/agent_harness` | 상태·호스트 신원·소유권·행위·독립 평가 엔진 |
| `src/neurath/_assets/scripts/skill_harness` | 단계·증거 계약과 실행 보고 |
| `src/neurath/_assets/.agents` | 공통 규칙, 31개 스킬, 29개 실행 계약 |
| `src/neurath/manifest.json` | 전체 실행 코드와 자산의 SHA-256 목록 |
| `src/neurath/install/` | 호스트 배치, 병합, 충돌 검사, 저널·복구 |
| `src/neurath/hosts/` | 실제 호스트 호출과 신원·재개 증명 |
| `src/neurath/memory/` | 프로젝트 공유 기억, 회고, 실행 전략 학습과 철회 |
| `src/neurath/agents/` | 동료 메시지, active Newsroom, 호출에 결속된 통신 MCP |
| `src/neurath/runtime/` | 대상 프로젝트가 지정한 검증 실행 |
| `tests/runtime` | 키트가 소유하는 상태·계약·권위 회귀 테스트 |

공개 명령은 독립 Python 환경에서 `python -I`로 실행합니다. 대상 프로젝트에 같은
이름의 `scripts` 패키지가 있어도 내장 엔진을 가리지 않습니다. 코드·계약은 배포 자산
루트에서, 작업 내용은 대상 Git worktree에서 읽습니다. 상태는 Git 공통 control root의
`.neurath/local/runs`와 `.neurath/local/resources`에 저장합니다. `NEURATH_*` 환경변수와
`neurath.*` 스키마만 사용합니다. 다른 제품의 상태를 암묵적으로 이어받지 않습니다.

## 설치 트랜잭션

설치 계획은 대상 경로, 배포 fingerprint, 호스트, 변경 전후 bytes·mode·link를 결속합니다.
적용 직전에 계획과 현재 파일을 다시 비교하고 Git 디렉터리 잠금 아래 적용합니다.
각 파일은 임시 파일과 fsync/replace로 기록합니다. 실패·프로세스 중단은 저널로 복구하고,
동시에 수정된 사용자 파일은 덮어쓰지 않습니다.

기존 지침, hook group, 권한, 모델 설정을 보존합니다. 제거는 설치 전 원문을 복원합니다.
공유 지침과 `.gitignore`의 관리 블록 밖 편집은 원래 위치에 보존하고 관리 블록 변경은 거부합니다.
빠른 설치는 배포 내용 지문마다 독립 실행 환경을 만들어 기존 프로젝트의 실행 코드를
바꾸지 않습니다. 대상 설치 성공 후 전역 명령만 새 환경에 연결하며, 복원을 위해 이전
환경을 유지합니다. 진단은 현재 실행 중인 배포 지문과 대상 설치 기록도 비교합니다.
사용자가 편집한 `.neurath/project.json`은 사용자 소유로 남습니다. 설치 상태와 원문이
포함된 설치 이력은 비공개 로컬 파일이며 외부로 전송하지 않습니다.

## 검증과 권위

31개 스킬 중 `explain-code`와 `graphify`는 상태를 소유하는 단계 계약이 없는 보조 스킬이며,
나머지 29개에는 단계와 증거 계약이 있습니다. 스킬을 선택할 때는 작업의 주된 목적과 입력의
권한·근거가 맞아야 합니다. `test-harness`의 키트 회귀 검사표는 키트 개발 소스에서 실행하고,
대상 프로젝트 변경에는 해당 프로젝트의 검증 연결을 사용합니다. 제품별 프로필 이름과
상태 이름 공간은 지원하지 않습니다.

일반 검증은 명시된 argv/cwd/성공 조건과 timeout을 사용합니다. 실행 전후 Git 파일
fingerprint가 달라지면 종료 코드 0이어도 실패입니다. typed pytest 검증은 요청한 각
leaf node의 실제 통과를 확인하며 다른 테스트의 통과나 skip으로 대체하지 않습니다.

배포 무결성, 설치 배치, 테스트 실행, 독립 검토자, 실제 호스트 활성화는 별도 증거입니다.
`doctor`와 정적 검사기는 호스트의 신뢰 설정이나 부모·자식 관계를 자체 인증하지 않습니다.
상태 접근, 동시 변경 충돌 방지, 작업 공간 소유권, 변경 작업의 실행 결과, 완료 조건은
런타임에서 검사합니다. 코드 식별자와의 대응은 [용어 안내](../terminology.md)에 정리합니다.

## 사용자 입력과 실행 상태

루트 `UserPromptSubmit`은 사용자 입력을 전달하는 경계입니다. 상태 갱신이나 기억·메시지
저장소가 실패해도 입력을 막지 않고 `bookkeeping deferred` 진단을 에이전트에게 전달합니다.
이 응답은 상태 갱신 성공이나 도구 실행 권한을 뜻하지 않습니다. 다른 세션의 입력은
상태·공유 기억에 기록하지 않으며, 도구 실행과 소유권 검사는 계속 적용합니다.

Codex의 새 `task_started` 기록은 이전 턴의 미종료 상태를 복구하는 근거입니다.
재개 훅 없이 새 턴이 시작되거나 같은 문장을 다시 입력해도 새 네이티브 턴으로 처리합니다.
결과를 관측하지 못한 이전 도구 호출은 `unknown`·`blocked`로 남기며 workflow를 완료하지
않습니다. 같은 턴의 추가 입력은 수락한 revision과 내용 digest로 구분해 기억에 저장합니다.

## 프로젝트 기억

Git 공통 control root의 `.neurath/local/memory/project.sqlite3`에 출처가 있는 기록을 저장합니다.
각 세션의 상태·소유권과 분리하며, SQLite 트랜잭션으로 동시 기록과 재전달을 처리합니다.
기억은 worktree 사이에서 공유하지만 검증 계약은 실제 실행한 worktree에서 읽습니다.
기록 선택과 실행 전략의 수명주기는 [기억과 학습](../usage/memory.md)에 설명합니다.

## Newsroom

기사는 제목·본문·작성자·버전을 저장하고 정정·댓글은 불변 이벤트로 추가합니다.
발행 트랜잭션에서 active 참여자만 선택해 제목 알림을 넣습니다. 참여는 네이티브 턴의
generation과 연결되며 비활성화·새 턴·10분 만료 시 이전 알림을 폐기합니다.
주소록뿐 아니라 SessionKernel의 actor·foreground 상태와 네이티브 프로세스 연결도
대조합니다. SessionEnd는 논리 세션을 재개 가능하게 남기므로 별도 연결 종료 기록이 필요합니다.
호스트 훅이 최대 3,000 bytes의 제목·조회 ID를 주입하며 본문은 명시적 조회로만 제공합니다.
알림 전달 기록은 읽음 확인과 다르고, 에이전트를 깨우는 별도 실행기가 없습니다.

통신 MCP 서버는 임의 Python·shell·파일 작업을 노출하지 않습니다. 네이티브 PreToolUse가
확인한 actor·턴·도구 호출·정확한 요청에 임시 토큰을 결속합니다. 요청 변경·신원 변경·만료·
종료 이후 호출은 거부합니다. PostToolUse는 토큰을 닫으며 동일 호출 내 재시도는 저장된
결과를 반환합니다. Claude의 read-only worker에는 이 통신 도구만 추가로 허용합니다.
Codex에는 새 통신 도구만 `tools.agent.approval_mode = "approve"`로 등록합니다.
네이티브 연결이 종료되면 해당 프로세스의 모든 통신 토큰과 캐시 결과도 폐기합니다.
설치기는 기존 Codex TOML과 Claude MCP 서버·권한을 보존하고 동명 사용자 설정과 충돌하면
중단합니다. 제거하면 설치 전 파일을 그대로 복원합니다.
