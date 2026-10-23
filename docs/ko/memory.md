# 현재 맥락·기억·인수

#143은 현재 enclave, 출처 있는 과거 기억, 체크포인트 보고와 실제 세션 인수를 구분합니다. 사용자 단위 SQLite에 저장하며 `core_0006`이 기존 원장에 세 테이블과 세션의 후속 연결을 추가합니다. 원문·태스크·runner를 삭제하거나 과거 보고를 성공 판정으로 승격하지 않습니다.

## 현재 맥락과 과거 자료

Enclave는 프로젝트·세션·선택한 작업 범위의 사실(`fact`), 가정(`assumption`), 판단(`decision`)을 보존합니다. 저장과 삭제에는 예상 개정이 필요합니다. 생성 시에는 0을, 이후에는 조회한 revision을 사용합니다. 저장소가 낙관적 revision을 갱신하며, 한 요청의 여러 변경은 별도의 이력 순번으로 기록됩니다. 요청 중 하나가 실패하면 상세 자료와 변경 목록 전체가 롤백됩니다.

삭제는 `op: remove`이며 빈 값이나 null 저장과 다릅니다. 과거 값과 삭제 표식은 이력에 남지만 압축 후 복원 대상에는 포함되지 않습니다. 값 객체의 필드 재할당과 읽기 전용 Sequence 계약을 사용하며 깊은 불변성을 강제하지 않습니다.

현재 내용은 enclave별 UTF-8 16 KiB 이내입니다. 큰 자료는 `set`의 `details`로 별도 Memory에 보존하고, 짧은 `value`와 `memory:<id>` 참조를 현재 맥락에 남깁니다. 기억 본문은 UTF-8 1 MiB까지 원문 그대로 저장합니다. 초과 내용을 조용히 자르지 않습니다. 참조 문자열이 있다고 외부 자료의 진위를 보증하지는 않습니다.

## CLI

기존 명시적 DB 초기화가 끝난 후보 환경에서 사용합니다. 다음 명령은 spakky-typer의 `memory` 그룹 아래에 있습니다.

- `neurath memory update --project-id ID --session-id ID --expected-revision N --changes JSON`: set/remove 배열을 원자 적용합니다. `--task-id`로 작업 범위를 선택하며 `--changes -`는 표준입력 JSON을 읽습니다. set 항목은 key/value/kind/references와 선택적 details를 받습니다.
- `neurath memory checkpoint --project-id ID --session-id ID --content TEXT --reference REF`: 결과·판단·남은 일·다음 행동을 보고로 저장합니다. reference는 반복 지정하며 `--content -`는 표준입력을 읽습니다. 작업 완료를 변경하지 않습니다.
- `neurath memory search --project-id ID --text TEXT`: 최근 기억 ID를 검색합니다. session-id/task-id와 결과 수 limit으로 범위를 좁힙니다. SQL 와일드카드도 일반 문자로 검색합니다.
- `neurath memory read --project-id ID --memory-id ID`: 선택한 과거 본문과 출처를 읽습니다. memory-id 대신 `--session-id ID`를 주면 원문·현재 태스크·runner·enclave·기억 ID를 인수 미리보기로 읽습니다. 체크포인트가 없어도 동작하며 소유권을 변경하지 않습니다.
- `neurath memory resume --project-id ID --source-session-id ID --target-session-id ID --expected-revision N --turn-id ID`: 현재 관찰한 후속 턴에 원 작업을 연결합니다. 같은 세션이면 명시적 실행 재개입니다.

## 인수와 자동 복원

다른 세션으로 인수할 때 원 실행과 자식의 종료가 확인돼야 하며, 작성 임대가 남아 있거나 실행 중인 phase가 있으면 인수를 거절합니다. 확인되지 않은 생존 상태를 종료로 바꾸지 않습니다. 대상 enclave가 이미 있으면 내용을 덮어쓰지 않고 먼저 읽고 정리하도록 알립니다. 같은 프로젝트의 태스크·runner·enclave 소유만 옮기고 기존 시도·원문·변경 이력을 보존합니다. 원 세션에는 후속 연결을 남겨 이전 훅이나 실행 재개가 중복 작성을 다시 허용하지 못하게 합니다.

[Codex](https://learn.chatgpt.com/docs/hooks)와 [Claude Code](https://code.claude.com/docs/en/hooks#sessionstart)의 `SessionStart` + `source: compact` 경로에서 최신 현재 맥락을 `hookSpecificOutput.additionalContext`로 반환합니다. startup/resume도 같은 경로를 사용합니다. 현재 세션 공통 사실과 미완료 작업의 사실·요구·출처·runner를 포함하고, 다른 세션·완료/무효 작업의 enclave는 포함하지 않습니다. 빈 상태는 `{}`입니다. 전달 내용이 8,000자를 넘거나 조회에 실패하면 복원을 성공으로 기록하지 않고 실패와 보존된 작업을 알립니다. 설치 시 Codex의 additionalContextLimit과 Claude의 출력 한도도 고려해야 합니다.

실제 호스트 검증은 별도 임시 DB와 검증용 세션에서 수행합니다. 기존 작업 세션·사용자 설정·원본 DB에 후보를 설치하는 것과는 별개입니다.

## Graphify 연결

`memory search --graph-directory PATH`는 기존 `graphify query`로 관련 코드·문서 관계를 함께 조회합니다. `memory checkpoint --graph-directory PATH`는 명시적으로 `graphify update`를 실행하고 검증된 그래프 참조를 보고에 추가합니다. DB 트랜잭션을 연 채 외부 도구를 실행하지 않습니다.

갱신 전에 원 graph.json을 보관하며 문서 노드·관계·하이퍼엣지의 의미 속성과 연결 대상이 유지되는지 확인합니다. 커뮤니티 번호 등 재계산되는 통계는 비교에서 제외합니다. 명령 실패, 문서 관계 손실 또는 잘못된 그래프는 성공으로 취급하지 않습니다. 실패 산출물을 보관하고 원 graph.json을 복원합니다. 다른 Graphify 보고서가 갱신됐을 수 있으므로 이 실패 상태의 보고서를 완료 근거로 사용하지 않습니다. 별도 그래프 엔진이나 의미 추출기를 만들지 않습니다.
