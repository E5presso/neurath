<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[English](../../en/contributing/provider-transports.md)

# 독립 작업을 실행하는 연결 소유하기

독립 provider 실행에는 지속적인 실행 식별자와 소유한 네이티브 연결이 필요합니다. 논리적인 provider 인스턴스는 개별 프로세스 generation과 구분되며 수신 주소도 PID·socket·네이티브 세션 UUID와 다릅니다. 발행자는 자기 모델 턴이 끝난 뒤에도 작업이나 ACK되지 않은 의무가 남아 있으면 후속 책임을 유지합니다.

## 실행 기반과 경계

| provider 표면 | 소유하는 구현 | 경계 |
| --- | --- | --- |
| Codex | 공식 app-server worker의 JSON-RPC 생성·읽기·시작·steer·interrupt·기록 세션 복원 | 다른 살아 있는 클라이언트 세션에 붙거나 이를 재개하지 않음 |
| Claude Code | 공식 Claude Agent SDK 비동기 client·스트리밍·직렬 query·interrupt·기록 세션 복원 | query·응답 소비·interrupt가 같은 client에 유지됨 |
| 네이티브·앱 동료 도구 | 탐색으로 확인한 지원 경로 | 반환 경로를 실제 실행해야 전달이 됨 |
| Claude Desktop/Cowork | 외부 생명주기 어댑터 없음 | 이력 읽기가 소유한 전달 bridge를 만들지 않음 |
| 저장된 제한 CLI 실행기 | 과거의 짧은 읽기 전용 상태·취소·계속 호출 호환 | 일반 독립 세션이나 MCP 전환의 대체 transport가 아님 |

협업 계약은 Codex→Codex, Codex→Claude, Claude→Codex, Claude→Claude를 다룹니다. provider가 같아도 같은 소유 인스턴스인 것은 아닙니다. 방향마다 실제 어댑터와 네이티브 동작을 확인해야 합니다. 소스에 경로가 있다는 사실이 새 호스트의 수락 검증을 대신하지 않습니다.

provider 세션 실행에는 사용자의 관찰, 원격 가시성, 저장된 데스크톱 프로젝트 소속이 필수가 아닙니다. 현재 스키마는 지원 경로의 선택적 `project_id`를 받지만 앱 프로젝트 자동 연결이 완료되었다는 의미는 아닙니다. 앱 데이터베이스를 수정하거나 소속을 꾸며내지 않습니다. 지원 어댑터에 프로젝트 ID를 명시했다면 실제 반환 식별자가 정확한 요청과 일치하는지 확인합니다.

## 직전 생성자의 실제 정책 관찰

상속의 출처는 직전 생성자가 현재 네이티브 실행에서 허용받은 정책입니다. 제한된 중간 에이전트가 더 넓은 루트 권한을 되살릴 수 없습니다. 승인 방식, 도구 제한, 파일·네트워크 범위, provider 고유 필드를 출처와 함께 따로 관찰합니다. 설정 파일은 후보 설정이며 실제 로드 값이나 메모리 내 덮어쓰기의 증거가 아닙니다.

같은 provider에서도 관찰된 관련 제한을 보존해야 합니다. 다른 provider 간에는 이름이 비슷한 모드가 아니라 의미를 대응시킵니다. 작업 공간 상대 범위는 자식 대상과 필요한 공통 상태에 맞추며 다른 소유자의 소스에 권한을 주지 않습니다. 넓은 권한 모드에서도 확인된 명시적 deny와 훅은 적용됩니다.

| 차원 | Codex | Claude Code |
| --- | --- | --- |
| 파일·실행 요청 | `mode`: `read-only`, `workspace-write`, `danger-full-access`, 기본 `inherit` | 기본 `inherit`; 명시적인 `native`에는 `permission_mode`와 실제 provider 정책 관찰이 필요함 |
| 승인 방식 | `approval_policy`: `never`, `on-request`, `untrusted` | `permission_mode`: `plan`, `dontAsk`, `default`, `acceptEdits`, `auto`, `bypassPermissions` |
| 승인 검토자 | `approvals_reviewer`: `user`, `auto_review` | Codex 전용 필드를 넣지 않음 |
| 계획 동작 | `collaboration_mode`: `default`, `plan` | 네이티브 `plan`의 의미와 OS 격리는 별개 |

현재 넓은 교차 provider 대응 후보는 Plan 밖의 Codex `danger-full-access`와 `approval_policy=never`, 또는 Claude `bypassPermissions`입니다. 이 경우도 확인된 제한을 보존할 수 있어야 합니다. 다른 차원은 미지원으로 판정할 수 있습니다. `dontAsk`를 `bypassPermissions`로 넓히면 안 됩니다. SDK sandbox가 꺼져 있어도 주변 OS가 무제한이라는 증거는 아니며 알 수 없는 OS 조건은 미관찰로 남깁니다.

지원하지 않거나 확인할 수 없는 차원이 있으면 본 작업 전달을 막고 부족한 관찰을 설명합니다. 정책을 조용히 넓히거나 좁힌 뒤 상속 성공이라고 할 수 없습니다. 이는 제한된 정책 대응 계약이며 모든 provider 고유 설정의 전체 복제를 뜻하지 않습니다.

## 수신 제공자의 기존 설정 사용하기

명시적으로 승인된 `target-native` 실행은 계획의 `execution.mode="target-native"`와 실행의 `mode="target-native"`를 사용한다. 배정 내용과 정확한 계획 리비전도 일치해야 한다. 대상의 기존 기본값·훅·도구 규칙을 유지하며 원본의 설정이나 자격 증명을 복사하지 않는다. 상속 실패 뒤 자동으로 선택하는 대안도 아니다.

Codex는 네이티브 `config/read`에서 지원되는 workspace sandbox 항목을 포함한 기본값을 확인한다. Claude는 기존 사용자·프로젝트·로컬 설정을 해석한다. 지원되지 않거나 관측되지 않은 기본값이면 준비를 거부한다. 대상과 충돌하는 명시적 승인·검토자·협업·permission 설정도 덮어쓰지 않고 거부한다. 생성 후 실제 모델·정책·활성화·소유권은 여전히 확인해야 한다. [Target-native 테스트](../../../tests/test_target_native_policy.py)가 지원하는 정책 확인을 다룬다.

## 접수·준비·실행 구분

`provider_capabilities`에 provider 이름을 전달해 기능을 확인합니다. `provider_route`는 `provider`와 작업(`create`, `discover`, `connect`, `status`, `message`, `resume`, `cancel`, `peer`)을 받아 지원 경로를 제안합니다. 제안 자체는 실행이나 소유권의 증거가 아닙니다.

앱 프로젝트 소속이 필요한 새 Codex 작업은 `list_projects`가 반환한 앱 프로젝트 ID로 기존 앱 생성 경로를 확인합니다. 호스트 도구의 명시적 새 작업 요청·모델 선택 조건을 따르고 생성 후 실제 실행 설정을 검증합니다. 앱 프로젝트 ID와 네이티브 app-server 프로젝트 ID는 서로 다르며, 네이티브 메타데이터 갱신 성공만으로 앱 소속을 확인할 수 없습니다. 새 Codex 세션의 `session_status.app_project`는 해당 세션의 로컬 앱 소속 기록을 읽기만 합니다. 실제 로컬 프로젝트가 존재할 때만 `assigned`를 반환하고, 기록이 없거나 불일치하거나 지원하지 않는 형식이면 `unobserved`로 남깁니다. 이 진단은 실행 준비 상태를 바꾸거나 원격 화면 표시를 증명하지 않습니다.

승인된 독립 생성에는 [모델 계획](model-planning-mcp.md)의 관찰 기반 계획을 준비합니다. `provider_run`의 구조적 필수 값은 `worktree`, `assignment`이며 실행 계약은 지속 접수 전에 정확한 `plan_id`, `plan_revision`, 할당 revision, 적용 정책, 안정적인 키도 연결합니다. run ID와 `accepted`는 접수 결과입니다. 준비 완료나 구현 완료로 해석하지 않습니다.

실제 작업을 보내기 전 소유 연결은 설치 배포본·배치, 네이티브 활성화, 적용 정책, 실제 모델, 대상의 자체 worktree 소유권을 확인합니다. 새 worktree에 무시되는 설치 파일이 자동으로 있다고 가정하지 않습니다. 준비 확인은 관찰한 세션·프롬프트 generation에 한정되며 독립 검토 권한을 부여하지 않습니다.

Claude는 별도 할당 query 전에 SDK Result와 응답 iterator를 모두 소비합니다. 같은 소유 제어 경로에서 식별자·프롬프트 generation·정책·설치·소유권을 다시 확인합니다. 준비된 세션의 턴이 닫혀 있다면 소유한 유휴 상태이며 할당을 실행 중이라고 표시하면 안 됩니다.

| 관찰 | 발행자가 판단할 수 있는 사실 |
| --- | --- |
| 지속 실행 접수 | ID로 진단할 수 있는 실행 기록이 있음 |
| 네이티브 세션 생성 | 실제 provider 식별자가 있으며 준비는 아직 실패할 수 있음 |
| 준비 완료 | 관찰된 조건에서 연결된 할당을 시작할 수 있음 |
| 승인·입력 대기 | 해당 승인된 준비 이벤트가 필요함 |
| 네이티브 완료 보고 | 턴 결과가 나왔으며 요청한 효과는 별도 확인 필요 |
| 취소 요청 접수 | 취소를 요청했으며 종료 결과는 추가 관찰 필요 |

Claude 결과는 명시적 중단을 먼저 취소로 분류합니다. 중단이 없고 실제로 보류된 도구 실행이 있으면, 과거 거부 이력이 함께 있어도 승인 대기로 분류합니다. 보류된 실행이 없을 때 오류나 과거 도구 거부가 남아 있으면 실패입니다. 완료 메타데이터의 `permission_denial_count`와 `approval_pending`은 권한이나 작업 성공을 증명하지 않습니다.

## 긴 작업 중에도 메시지 처리

분리된 worker는 시작·대기·오류·연결 해제·취소·완료 이벤트와 메시지를 생성자에게 연결해 보냅니다. 일반 작업에는 수명 제한 시간이 없으며 개별 연결·쓰기·응답에는 기한이 있습니다. 네이티브 결과를 기다리는 동안에도 이벤트 루프가 메시지와 취소를 처리해야 합니다.

할당한 작업이나 ACK되지 않은 의무가 있으면 발행자 소유 연결을 유지합니다. 유휴 Codex에는 새 턴을, 활성 Codex에는 실제 현재 턴의 steer를 전달합니다. Claude는 현재 Result와 iterator를 소비할 때까지 알림을 지속 대기열에 보존합니다. 스트리밍 중간 입력을 독립적으로 완료된 턴처럼 확인하지 않습니다.

수신 전용 모델 세션, heartbeat, 주기적 완료 검색은 필요하지 않습니다. 관련 이벤트나 오류 후 진단에는 `provider_status`를 사용하지만 완료 확인 반복 루프로 쓰지 않습니다. 연결을 닫아도 늦은 알림을 보존하고 이미 시작한 입력 쓰기는 마칠 수 있게 합니다. 본문 읽기·ACK·재시도는 [전달 계약](collaboration-contract.md)을 따릅니다.

## 기록된 실행 복원

발행자 프로세스 종료만으로 다른 인스턴스의 승인된 작업을 취소하지 않습니다. 메시지 복구와 중단된 계산 복구는 별개이며 호스트 전원 종료나 저장소 유실에서도 실행을 보장할 수는 없습니다.

`provider_recover`는 현재 발행자의 기록된 실행에 대해 `run_id`, `key`를 받습니다. 이전 worker generation·네이티브 식별자를 확인하고 이전 프로세스와 연결이 닫혔는지 요구합니다. OS worker lease는 중복 복구와 취소된 작업 복구를 거절합니다. `recovery-accepted`도 접수에 한정된 결과입니다.

복원한 소유 연결은 같은 기록 세션을 재개하고 정책·준비 상태를 확인한 뒤 대기 전달을 연결합니다. 원래 할당을 다시 실행하지 않습니다. 이전 종료를 증명할 수 없거나 세션을 복원할 수 없으면 진단 식별자와 차단 사유를 보존합니다. 같은 식별자의 대체 세션을 꾸미거나 불확실한 생성을 반복하지 않습니다. 크레딧 고갈로 다른 제공자가 남은 일을 이어받아야 한다면 별도의 [맥락 가져오기와 작업 승계](provider-continuity.md)를 사용합니다. 같은 제공자 실행을 복원하는 대신 저장된 원본 맥락과 미완료 작업을 가져오는 절차입니다.

## 계층별 근거

[provider 작업](../../../src/neurath/providers/jobs.py), [복구](../../../src/neurath/providers/job_recovery.py), [감독](../../../src/neurath/providers/supervision.py), [권한 상속](../../../src/neurath/providers/permission_inheritance.py), [런타임 실행](../../../src/neurath/runtime/provider_execution.py)이 접수와 소유 실행을 구현합니다. [provider 정책](../../../src/neurath/runtime/provider_policy.py)은 지원 검사를 정의합니다.

[provider 작업 테스트](../../../tests/test_provider_jobs.py), [상속 모드 테스트](../../../tests/test_inherited_provider_modes.py)는 결정적인 fixture를 검사합니다. 실제 호스트에서는 네 방향, 제한된 중간 생성자, 설치·소유권 누락, 실제 모델·정책, 유휴 발행자 전달, ACK 전후 종료, 오래된 generation, 복구, 긴 작업의 취소를 관찰해야 합니다. [검증 안내](validation.md)에 따라 소스 테스트·설치 검사와 네이티브 관찰을 구분합니다.
