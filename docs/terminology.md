# 하네스 용어 안내

Neurath의 문서와 사용자 설명은 어떤 작업을 하는지 드러나는 표현을 사용합니다.
영어도 한국어도 같은 의미를 유지하며, 하나의 옛 이름을 여러 개념에 일괄 적용하지 않습니다.

| 의미 | 영어 표현 | 한국어 표현 | 기존 코드에서 찾을 이름 |
| --- | --- | --- | --- |
| 설치가 바꾼 파일과 복구에 필요한 이전 내용 | installation record | 설치 이력 | install receipt, `neurath-receipts` |
| 호출한 도구의 결과 상태·출력 지문·변경 관측값 | execution result | 실행 결과 | tool receipt, `ToolReceipt` |
| 검사 대상·조건·실제 결과를 함께 보관한 기록 | verification record | 검증 기록 | verification receipt |
| 검토자의 판단과 발견한 문제 | review result | 검토 결과 | review receipt |
| 어떤 입력이나 사건을 처리했는지 나타내는 기록 | processing record | 처리 기록 | source receipt, prompt receipt |
| 정보나 요청이 어디서 왔는지 | source information | 출처 정보 | provenance |
| 실제 호스트 기록을 대조해 확인한 사실 | host verification | 호스트 확인 | attestation, `HOST_ATTESTED` |
| 평가를 수행하는 에이전트 | reviewer | 검토자 | evaluator |
| 도구를 한 번 실행하도록 요청한 것 | tool call | 도구 호출 | invocation |
| 다음 작업에 필요한 결과·결정·남은 일 | handoff note | 인계 기록 | checkpoint |
| 누가 작업 공간을 수정할 수 있는지 | workspace ownership | 작업 공간 소유권 | worktree claim |
| 이전 소유자의 변경을 막기 위한 키 | ownership key | 소유권 확인 키 | fencing token |
| 현재 처리 중인 사용자 요청 | current turn | 현재 턴 | foreground turn |
| 결과를 최종 판정하는 실행·검토자·사용자·공식 자료 | decision authority | 판정 주체 | `oracle_owner`, `OracleOwner` |
| 세션 복구에 필요한 작업 상태 | session working state | 세션 작업 상태 | enclave |

기록이 있다는 것만으로 성공하거나 승인됐다는 뜻은 아닙니다. 실패·미확인 결과도 기록합니다.
실행 결과는 도구가 무엇을 했는지, 검증 기록은 어떤 조건으로 그 결과를 확인했는지 설명합니다.
검토 결과가 자동으로 소유권이나 게시 권한을 부여하지는 않습니다.

`receipt`는 금전 거래가 아니므로 “영수증”으로 옮기지 않습니다. 기존 `invoice export`는
하네스 개념이 아닌 예제 업무명이었습니다. 문서 예제는 **work log export / 작업 기록 내보내기**로
통일합니다. 실제 업무에서 쓰는 청구서·운송장 등의 용어는 대상 프로젝트가 정한 의미를 따릅니다.

명령·JSON 필드·스키마·클래스·저장 경로를 인용할 때는 정확한 철자를 유지합니다.
기존 `receipt` 필드와 `neurath-receipts` 디렉터리는 저장된 설치·세션 기록과 도구의 호환을 위해
유지합니다. 설치 계획에서는 `--installation-id`를 사용하며, 기존 `--receipt`도 같은 의미로 받습니다.
사람에게는 “설치 이력 ID”, “도구 실행 결과”처럼 풀어 설명합니다.

이 안내는 하네스 자체 용어에 적용합니다. 설치 대상 프로젝트의 업무 용어집을 대체하지 않습니다.
