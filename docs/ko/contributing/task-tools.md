# 공통 작업 실행

[English](../../en/contributing/task-tools.md) · **한국어**

[기여 안내](index.md) · [아키텍처](architecture.md)

CLI 파서와 MCP 통신 처리는 `runtime/tasks.py`를 호출하는 어댑터입니다. 명명된 도구는
CLI 파서 없이 구조화 입력을 검사합니다. 기존 저장소와 커널 권한은 함께 사용하며,
작업 성공만으로 독립 검토나 작업 흐름 완료를 인정하지 않습니다.

| 작업 도구 | 입력 | 호환 CLI |
|---|---|---|
| `session_status` | 없음; 현재 네이티브 호출자만 사용 | `session-status` |
| `provider_capabilities`, `provider_route` | provider; operation, 선택적인 대상 ID·모델·요청 설정 | `provider capabilities/route` |
| `provider_run` | worktree/assignment, 선택적인 model/mode/approval_policy/approvals_reviewer/collaboration_mode/timeout | `provider run` |
| `memory_recall`, `memory_checkpoint` | query/limit; summary/key와 선택적 decisions/next_steps/lessons/status | `memory recall/checkpoint` |
| `verification_run` | 프로젝트에 등록된 check | `verify NAME` |
| `collaboration_discover`, `collaboration_inbox` | query/limit; conversation/limit/include_read | `agent discover/inbox` |
| `collaboration_send`, `collaboration_reply` | to 또는 message_id, message, key | `agent send/reply` |
| `newsroom_headlines`, `newsroom_read`, `newsroom_publish` | limit; article_id/history/after/limit; title/body/key | `newsroom headlines/read/publish` |

각 도구는 입력·출력 스키마를 제공합니다. 응답은 `ok`, `operation`과 CLI와 같은
`result`, 또는 code/message/state/retryable/next_action을 담은 `error`입니다.
검증 실패도 실제 결과를 보존하고 `isError`를 설정합니다. 인계는 에이전트 보고입니다.

세션 진단은 설치·활성화·관찰된 정책·소유권을 구분하고, 작업별 실행 가능 여부와 복구
방향을 제공합니다. 현재 호출에 네이티브 생성 요청 근거가 없으면 요청 모드는 미관찰로
표시하며 실제 모드에서 추정하지 않습니다. 진단은 세션을 시작하거나 권한·소유권을 바꾸지 않습니다.

호스트 경로 안내는 다음 네이티브 도구·인자와 전제 조건, 지원하지 않는 설정을 반환하며
직접 실행하지 않습니다. 현재 호스트 도구 목록을 확인하고 승인된 작업을 실행한 뒤 새 세션
자신의 준비 상태를 확인합니다. 생성 경로는 준비 확인까지만 요청하고 구현 지시는 그 뒤
별도로 전달합니다. 대상 ID와 요청 설정은 경로 입력이며 호출자 신원이나 실제 정책 근거가 아닙니다.

`provider_run`은 adapter가 소유한 Codex app-server를 통해 실행하며 검증과 같은 호출자 정책·
소유권 조건을 적용합니다. 독립 터미널 자동화는 읽기 전용으로 제한합니다. 쓰기 지시는 별도로
설치된 worktree와 새 세션의 실제 활성화·소유권 확인 뒤 전달합니다. 부분 실패에도 생성된
세션 ID와 진단을 보존하며, 호출자가 바뀌면 결과를 현재 작업의 권한 근거로 쓸 수 없습니다.

서버 이름과 기존 `agent(argv)` 도구는 저장된 작업과 호환되며, 기존 도구는 동료 대화와
뉴스룸만 지원합니다. 업데이트는 다른 서버와 권한을 보존합니다. 예전 스킬 본문의 CLI
예제보다 명명된 도구를 우선합니다. 설치·훅·자동화와 적합한 도구가 없는 작업은 CLI를 유지합니다.

네이티브 PreToolUse는 도구 이름·정규화 입력·worktree·actor·턴·호출을 결속합니다.
입력으로 신원을 지정할 수 없습니다. PostToolUse와 세션 종료는 결속을 닫습니다.
변경·만료·종료된 결속은 재사용할 수 없습니다. 성공한 호출은 저장 결과를 반환하고,
새 호출로 쓰기를 재시도할 때는 같은 key와 내용을 씁니다. 실패는 오류를 보존하며,
중단된 호출은 결과가 불확실한 상태로 남겨 자동 재실행하지 않습니다.

검증은 프로젝트 설정을 고정하고 현재 네이티브 root의 활성 소유권을 요구합니다.
MCP 프로세스가 호출자의 샌드박스를 자동 상속하지는 않습니다. 직접 실행하려면
설치·활성화·모드·소유권의 최신 근거와 제한 없는 실제 네이티브 샌드박스를 확인해야 합니다.
승인 정책은 `never`여야 하며 외부 승인 검토자가 없어야 합니다. 훅에서 승인을 요청한
사실은 승인 완료 근거가 아닙니다. 승인이 필요한 실행은 네이티브 호스트 경로를 사용합니다.
검사 프로세스에는 서버 신원 환경 변수를 전달하지 않습니다. 그 외에는 에이전트가 같은
검사를 호스트 셸에서 실행해 정책과 승인을 적용하며, 상태·소유권 조건을 완화하지 않습니다.
네이티브 신원 실패를 독립 자동화로 바꿔 우회할 수 없고 독립 자동화에는 네이티브 학습 권한이 없습니다.

테스트 환경에서는 CLI/MCP 상태·결과, 잘못된 입력, 변경된 결속, 중복·실패·중단을
검증합니다. 실제 Codex/Claude의 선택 행동은 같은 자연어 작업으로 별도 검증합니다.
도구 목록·선택·완료·오호출·복구·소요 시간은 비공개 기록으로 보존합니다.
설치나 API 호출 성공만으로 모델의 행동을 증명하지 않습니다.

[MCP 도구 명세](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)는
통신 스키마와 오류를 정의합니다. [도구 설계 지침](https://www.anthropic.com/engineering/writing-tools-for-agents)은
작업 경계의 참고 자료이며 실행 권한은 현재 소스와 네이티브 근거로 판단합니다.
