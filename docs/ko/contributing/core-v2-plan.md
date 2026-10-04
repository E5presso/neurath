# 코어 재구축 구현 계획

[English](../../en/contributing/core-v2-plan.md) · [핵심 계약](core-v2-spec.md)

상태: 구현과 어댑터 통합을 진행 중이다. 구현·호스트 검증 완료를 뜻하지 않는다.
부분 라우팅 수정을 새 코어의 기반으로 삼지 않고 기존 main에서 별도 재구축한다.

## 범위와 이행

핵심 계약의 D1–D7와 SC01–SC20가 구현의 기준이다. 패키지 버전은 호환성이 바뀌는
코어 교체를 구분하도록 0.2.0으로 준비한다. 기존 설치본과 데이터는 새 배포본 검증
전까지 그대로 유지한다. 현재 실행 중인 다른 프로젝트에 개발 소스를 임의 설치하지 않는다.

소스의 새 중심은 `src/neurath/core/`다. 기존 `runtime/`, `hosts/`, `agents/`의 제어·상태
구현과 `_assets/scripts/agent_harness`, `_assets/scripts/skill_harness`를 대체한다.
Provider의 native wire transport, installer의 보존·rollback, 공개 release/reporting
서비스는 구현을 검토해 외곽 기능을 유지하되 이전 코어 의존성을 제거한다.

## 안정된 내부 계약

- `Context`: adapter가 관측한 project/session/actor/invocation. 공개 명령 입력에서 받지 않는다.
- `Task`: ID, revision, 사용자 source 참조, goal, acceptance, owner session, 실행 상태,
  skill run, assignment 참조. 목표 산문은 ID가 아니다.
- `SkillDefinition`: ID/version과 순서 있는 phase 정의. 각 phase에는 이름·완료 조건·허용
  효과 종류가 있다. 실행 시작 시 Task에 스냅샷한다.
- `Evidence`: source 종류, source ID, 실제 결과 또는 actor 보고, 대상 revision. actor가
  보낸 문서의 provenance를 native source로 바꿀 수 없다.
- `Assignment`: ID/task ID, 선택한 세 실행 방식, 필요 근거, 범위, 발행자·수신자,
  상태와 보고. reported는 수신자의 반환 의무를 끝내고, Task 완료에 필요한 수락은 owner가 한다.
- `Lease`: canonical checkout, writer, generation. 경로는 lease 대상이고 신원은 아니다.
- `Approval`: action/target/scope와 실제 사용자 source. 권한 설정이나 OS sandbox를 바꾸지 않는다.

Application 명령은 `Context + command -> result`이고 저장소에 한 트랜잭션으로 적용한다.
조회 결과를 만들기 위해 다른 workflow의 admission을 통과시키지 않는다. 실제 외부 효과는
native adapter에서 수행하며 Task/phase가 허용한 효과인지와 호스트 권한을 각각 확인한다.

## 구현 단위와 의존성

| 단위 | 구현 산출물 | 선행 | 인수 시나리오 |
| --- | --- | --- | --- |
| A1 | Source/Actor/Task/Skill/Assignment/Lease/Approval 모델과 순수 전이 | 스펙 cold-read | SC03–SC13, SC16–SC20 |
| A2 | 단일 transactional store, revision, 동일 호출 재전달, 불변 source | A1 | SC07, SC10, SC12, SC13 |
| A3 | Task·phase·Stop·재작업·adoption application 명령과 닫힌 입력 schema | A2 | SC03–SC06, SC13, SC16–SC20 |
| B1 | Codex/Claude native event 관측과 읽기·쓰기·보고 구분 | A3 | SC01, SC07–SC11, SC19 |
| B2 | 세 가지 위임 경로, assignment 보고·수락과 provider 효과 | B1 | SC01, SC02, SC09, SC17, SC20 |
| B3 | Skill 정의/본문, TODO, installer/MCP/CLI의 새 코어 연결 | A3, B1 | SC03–SC05, SC14 |
| C1 | 이전 core를 제외한 후보 배포본과 명시적 데이터 export/adoption | B2, B3 | SC06, SC14, SC15, SC18 |
| C2 | 후보의 실제 호스트 검증 후 이전 소스 삭제, 최종 배포 검증·독립 리뷰 | C1 | SC01–SC20 |

A1의 모델을 대표 구현으로 삼고 후행 단위는 그 계약을 소비한다. A1→A2→A3→B1→B2/B3→C1→C2가
critical path다. B2와 B3은 provider 코드와 skill/설치 코드를 분리하면 일부 병렬화할 수 있지만,
공용 schema와 adapter 접점 변경은 순서대로 통합한다. 전 단위 병렬 실행은 승인된 설계가 아니다.

작업 단위를 기계적인 줄 수에 맞춰 원장·DTO·검사만 하는 티켓으로 쪼개지 않는다.
각 단위는 완결된 불변식과 실행 가능한 수용 시나리오를 제공해야 한다. 공용 모델/schema를
동시에 수정하는 writer는 허용하지 않으며 단일 owner가 통합한다.

## 검증 계획

1. SC별로 기대 동작과 금지 동작을 먼저 실행 가능한 테스트로 작성한다.
2. 실제 SQLite transaction과 경쟁 writer, stale revision, duplicate invocation을 검증한다.
3. 두 host adapter의 실제 event 입력 형태에서 prompt/source·child·tool·Stop 흐름을 검증한다.
4. 설치된 배포본에서 하나의 좁은 티켓을 끝까지 실행한다. native child 리뷰는 별도 writer
   claim과 완전한 policy snapshot 없이도 허용된 읽기·보고를 수행해야 한다.
5. 실패한 검사·끊긴 연결·사용자 인터럽트 뒤에도 현재 phase와 사용자 태스크가 보존되는지 확인한다.
6. 마지막에만 패키지·원문 무결성·설치 보존·호스트별 end-to-end·독립 리뷰 결과를 묶는다.

기존 테스트 중 installer·release 검증처럼 유지되는 외곽 기능의 테스트는 보존한다.
삭제되는 내부 구조만 검사하는 테스트는 해당 SC의 행위 테스트로 대체한다. 실패한 기존
테스트를 이유 없이 제거하거나 새 코어가 이전 엔진을 호출하도록 우회하지 않는다.

## 결정과 미확인 사실

사용자는 태스크·phase 강제를 권고로 바꾸는 선택지를 거부했다. 따라서 단계 건너뛰기와
미완료 상태의 정상 종료 거부는 새 엔진의 필수 동작이다. 출처 검증과 실제 host 권한도
유지한다. 읽기 reviewer에게 writer의 준비 상태를 요구하는 동작은 제거한다.

호스트별 event 전달, 독립 세션의 앱 표시, native tool의 대상 경로 지원은 선언으로
확정하지 않는다. B1/B2와 C2에서 실제 관측하며 미지원 기능은 정확한 capability 결과로
반환한다. 이 미확인이 task/phase 상태 조회와 실패 보고까지 막지는 않는다.

진행·설계 이견·실제 검증 결과는 이 문서와 [핵심 계약](core-v2-spec.md)에 기록한다.
새 세션은 이 두 파일과 실제 source/test를 읽어 작업을 재개할 수 있어야 한다.

## Cold-read 보완 기록

첫 독립 검토에서 재작업, Assignment 보고와 수락의 책임, 소유 세션 손실/취소, 실제 효과의
phase admission이 불명확하다는 네 지적을 수용했다. 스펙 5·6·9절에 전이와 책임을 추가하고
SC16–SC20으로 검증한다. Skill이 정한 restart_from에서 같은 Task의 새 attempt를 수행하며,
reported 상태는 child의 반환 의무와 parent의 수락 의무를 구분한다. Adoption은 같은 Task ID와
증가한 소유 generation을 사용한다. Native 효과 종류와 phase 밖 편집·게시 거부를 검증한다.
후보 배포본 제외→실제 호스트 검증→이전 소스 최종 삭제 순서로 제거 시점을 명확히 했다.

## 구현 진행 — 기반 모델과 저장소

`src/neurath/core/domain.py`에 Task 내부 skill run과 phase 순서, 재작업, Assignment 보고/수락,
인용 원문 검증, 종료 판단을 구현했다. `codec.py`와 `store.py`는 단일 SQLite 트랜잭션,
revision, 동일 요청 재전달, 불변 Source, writer lease generation을 담당한다.
`service.py`는 adapter 제공 Context를 받고 공개 입력에서 actor나 native 출처를 만들지 못하게
하며 Task ID 기반 명령을 제공한다. 초기 domain/store/service 행위 테스트가 통과했다.
이는 A1–A3의 기반 구현이며 approval/위임 transport와 실제 host 훅, 설치·기존 코어 제거는 미완료다.

### 네이티브 입력 경로의 기반

`host_events.py`, `hook_adapter.py`, `tool_schema.py`, `mcp.py`에 CWD와 독립적인 세션·에이전트 신원, 사람의 발화라고 단정하지 않는 입력 원문 보존, 정확한 호출에 연결된 MCP 신원과 종료 처리, 현재 phase의 실행 효과 검사와 Stop 응답을 추가했다. 명시된 하위 skill은 부모 phase로 돌아오며 허용 효과를 확장하지 않는다. 실제 stdio 프로세스에서 이전 엔진을 import하지 않는 새 도구 표면을 확인했다. 코어 테스트는 이 기반의 검증이며 설치된 실제 호스트 검증이 아니다. 명시적 검사 종료 결과를 실행 당시 소스에 연결하며 소스 변경 뒤에는 오래된 검사로 완료할 수 없다. 네이티브 수정 대상 확인, Task 인계/철회와 정확한 대상에 대한 승인 해석 기록도 연결했다. 새 정의는 기존 29개 스킬의 phase 순서를 보존한다. Skill 본문·설치 projection·조건부 경로, provider 실행, 유지할 외곽 서비스, 설치 전환과 실제 호스트 검증은 남아 있다. 초기 검사 이후 진행은 아래 통합 기록을 따른다.


### 재작업·스킬 통합·설치 진입점

재작업 전에 bounded Assignment의 결과·취소를 정리하도록 했다. Native 검사는 실행을 시작한 run과 모든 상위 attempt를 보존한다. 결과가 재시작 뒤 늦게 도착해도 입력이 변경되었거나 불명확하면 과거 결과를 소비하지 않는다. 명시적으로 입력이 같을 때는 같은 소스 관측을 재사용한다. 독립 재현과 재검증에서 두 경로 및 저장소 재개·상위 run 재작업을 확인했다. 이는 해당 수정의 검토이며 최종 릴리스 리뷰가 아니다.

계약을 가진 29개 스킬 진입점, implement-issue/autopilot 단계 문서와 공통 실행 규칙을 단일 Task 계약으로 전환했다. Autopilot은 issue별 Task, 세 실행 선택, 명시된 하위 검토·문서화 스킬과 재작업 지점을 유지한다. Catalog는 상위 phase에서 필요한 효과를 실행할 수 없는 하위 스킬을 거부한다. 나머지 유지보수 스킬과 supporting script 통합은 남아 있다.

설치 MCP 설정은 도구별 승인 override를 만들지 않고 provider별 새 코어 adapter를 사용한다. Hook은 현재 checkout과 독립적으로 설치된 interpreter와 공통 프로젝트를 기준으로 실행한다. 옛 코어 import를 금지한 프로세스에서 CLI 조회·설치 계획 생성·양 호스트 훅 프로토콜 실행을 확인했다. 이전의 일반 engine/skill 명령 게이트웨이는 제거했다. 설치 rollback과 이력은 유지할 외곽 서비스에 남는다. 데이터 전환·이전 bootstrap 호환·후보 패키지·실제 호스트 활성화는 미완료다.

최근 집중 코어 전체 검사는 150개가 통과했고, 이후 설치·CLI 변경에는 별도 집중 검사를 추가했다. 전체 저장소 검사와 최종 독립 리뷰가 필요하다. 이 결과는 설치·병합·공개 릴리스 완료를 뜻하지 않는다.

## 소스 교체 상태

개발 소스에서 기존 `runtime`, `hosts`, `agents`, 번들 스크립트 엔진, 이전 provider 조정 계층과 스킬 helper 구현을 제거했다. 이 소스 변경은 이미 설치된 불변 런타임을 전환하지 않는다. 후보 패키지 검증을 이유로 기존 구현을 소스에 계속 남기지 않는다. 최종 활성화와 공개 릴리스에는 각각의 실제 근거가 필요하다.

삭제된 구현의 내부 구조에 결속된 테스트는 구현과 함께 폐기한다. 유지할 계약은 `tests/core`로 옮긴다. Task·phase·Stop과 재작업은 `test_domain`, `test_service`, `test_hook_adapter`, 동시 상태 변경과 쓰기 소유권은 `test_store`, `test_workspace`, 배정·보고·수락과 세 위임 선택은 `test_collaboration`, `test_native_delegation`, `test_provider_commands`, 입력·인용 출처는 `test_service`, `test_host_events`, 실제 검사·게시 결과는 `test_checks`, `test_native_results`, `test_publications`, 기존 상태·설치 보존은 `test_legacy_work`, `test_install_storage`, `test_install_entrypoints`에서 검사한다. 외부 서비스의 설치·릴리스·보고·전송·학습 동작 테스트는 유지한다. 테스트 교체가 모든 실제 호스트 시나리오의 검증 완료를 뜻하지 않는다.

실제 Claude 세션에서 phase 순서 위반 거부, 미완료 Stop 거부 뒤 같은 Task의 계속 실행, 성공 문자열을 출력해도 실제 종료 코드 7인 검사의 실패 처리를 확인했다. Codex 검증 호스트에서는 후보 훅 정의가 아직 신뢰되지 않아 해당 실제 Codex 결과는 미검증이다. 이 호스트 경계 때문에 소스 개발·데이터 전환 구현·패키지 검사·독립 리뷰를 중단하지 않는다.

현재 source replacement와 독립 리뷰의 재현 결함 수정은 진행했다. 최종 후보 패키지 검증과 실제 호스트 활성화는 별도로 확인하며, 앞선 기초 구현 단락의 미완료 목록은 이후 통합 상태로 대체한다.
