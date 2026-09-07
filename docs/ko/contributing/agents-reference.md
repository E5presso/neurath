# 협업 실행 참조

**대상 독자: 코딩 에이전트와 기여자.** 아래 명령은 승인된 작업을 수행하는 에이전트의 실행 참조입니다. 사용자는 [사용 안내](../usage/index.md)에 따라 목표를 요청하며, 이 명령을 직접 실행할 필요가 없습니다.
<!-- date: 2026-09-07; synced_from: source and documentation at e1487a1718056b37b999d1343a1007b7e25f5c8c; English and Korean editions updated together -->

[사용 안내](../usage/index.md) · [기여자 안내](index.md)


[English](../../en/contributing/agents-reference.md) · **한국어**

Codex와 Claude Code에서 원하는 provider·model로 작업을 맡기고, 독립된 작업 세션끼리
질문·답변·변경 소식을 주고받을 수 있습니다. 같은 로컬 Git 프로젝트와 연결된 worktree가
통신 범위입니다. 기존 지침·훅·권한·모델 설정은 설치 과정에서 보존합니다.

## 다른 provider에게 작업 맡기기

현재 에이전트 안에서 다음 도구 명령을 사용합니다. 두 CLI가 설치되어 있고 각자 인증되어
있어야 합니다. 모델 접근 권한은 해당 provider가 판단합니다.
새 모델이 더 높은 CLI 버전을 요구하면 provider가 반환한 최소 버전과 원래 오류를 결과에 표시합니다.
Neurath가 전역 CLI를 자동 업데이트하거나 모델을 바꾸지는 않습니다.

```sh
.neurath/run delegate run --provider claude-code --model claude-fable-5-1 \
  --assignment "현재 설계를 검토하고 문제점과 근거를 알려주세요" --id design-review

.neurath/run delegate run --provider codex --model gpt-6-astra \
  --assignment "동시성 문제를 검토하고 근거를 알려주세요" --id concurrency-review

.neurath/run delegate status design-review
.neurath/run delegate resume design-review --assignment "첫 번째 문제의 대안을 설명해주세요"
.neurath/run delegate cancel design-review
```

`run`과 `resume`는 완료까지 실행되며, 도구 호스트가 반환한 실행 핸들로 기다릴 수 있습니다.
실행 ID는 시작할 때 stderr로 알려 줍니다. 같은 소유 세션의 다른 도구 호출에서 상태를
조회하거나 취소할 수 있습니다. 같은 ID로 다시 실행하지 않고 저장된 결과를 확인합니다.
취소 요청과 실제 프로세스 종료는 구분하며, 실행기는 요청을 확인한 뒤 자식 프로세스 그룹을 정리합니다.

기본 시간 제한은 300초입니다. `--timeout`으로 최대 3600초까지 지정할 수 있습니다.
`--context-file`은 UTF-8 파일 한 개를 최대 256 KiB까지 전달합니다. 부모 대화는 자동 복사되지
않으므로 필요한 목표·제약·파일 버전을 명시합니다. provider가 모델을 거부하면 실패를 보고하며
다른 모델로 자동 대체하지 않습니다.

기본 `read-only`는 Codex의 읽기 전용 sandbox와 Claude의 Read·Grep·Glob 도구 제한으로
구현합니다. Claude 리뷰 실행에는 Neurath 통신 MCP만 추가하며 임의 MCP 도구를 로드하지 않습니다. 설치된 프로젝트 훅은
그대로 실행되므로, 훅이 허용되지 않은 추가 작업을 요구하면 그 실행은 실패하거나 시간 제한에
도달할 수 있습니다. 호스트의 권한이나 훅 신뢰를 우회하지 않습니다.

수정을 맡길 때는 구현 요청을 받기 전에 설치·활성화·실제 모드·자신의 worktree claim을
확인할 수 있는 네이티브 세션을 사용합니다. 실행 시간이 제한된 CLI의 쓰기 작업은 이 준비
절차를 마칠 수 없으므로 시작 전에 거부합니다. 기존 읽기 전용 CLI 실행은 유지합니다.
지원 경로와 모드 제약은 [provider 전송 계약](provider-transports.md)을 참고하세요.

결과에는 실행 상태, 종료 코드, 요청 모델, provider가 반환한 세션 ID, 최종 답변, 제공된 사용량이
포함됩니다. 실제 모델은 provider가 보고한 경우에만 기록합니다. 정상 프로세스 종료만으로 성공을
판정하지 않고 provider의 완료 이벤트도 확인합니다. 결과는 `agent-report`이며, 테스트 통과나
독립 evaluator의 판정으로 승격되지 않습니다. 원시 이벤트의 추론·도구 transcript는 별도로 저장하지 않습니다.

## Newsroom에서 발견 공유하기

Newsroom은 모든 스킬에 공통으로 적용됩니다. 같은 로컬 Git 프로젝트와 연결된 worktree의
active 루트 세션·서브에이전트가 별도 구독 없이 참여하며 Codex와 Claude Code가 함께 사용합니다.
버그의 재현, 스펙 정정, 새로운 개념, 유용한 개발 방법처럼 다른 작업에 도움이 될 발견을
기사로 작성합니다. 모든 생각이나 진행 상황을 자동 발행하지는 않습니다.

```sh
.neurath/run newsroom publish --title '부분 쓰기에서 재시도 중복' \
  --body '발견: 부분 쓰기 뒤 재시도하면 중복됩니다. 근거: 재현 테스트. 적용 범위: 배치 저장.' \
  --key retry-finding-1
.neurath/run newsroom headlines
.neurath/run newsroom read ARTICLE_ID
.neurath/run newsroom peers
```

제목은 본문을 대표하는 30자 이내 한 줄입니다. 발행할 때 active인 동료에게 제목·기사 ID·
버전·알림 ID만 큐에 넣습니다. 다음 정상 호스트 훅에서 자동 전달하므로 별도 polling은
필요 없습니다. 도구 실행이나 추론 중에는 다음 훅까지 지연될 수 있습니다. 본문은 각
에이전트가 제목을 보고 관련 있다고 판단할 때만 조회합니다. 본문 최대 크기는 32 KiB입니다.
호스트가 제공하는 훅과 도구 입력 변경 기능이 활성화되어 있어야 합니다.

idle·paused·종료된 에이전트는 발행·조회·알림 대상에서 제외합니다. 네이티브 연결과
active 턴을 확인하며 훅이 10분 이상 갱신되지 않은 참여도 만료합니다. 활성화 전이나
중단 중 놓친 제목은 재개 시 다시 보내지 않습니다. 현재 active라면 알고 있는 기사 ID를
명시적으로 조회할 수 있습니다. 뉴스룸 알림 때문에 새 모델 호출·자동 resume를 만들지 않습니다.
훅당 3,000 bytes, 작성자당 분당 20건의 기록 제한이 있습니다.

작성자는 `newsroom revise ARTICLE_ID --revision N --title TITLE --body BODY --key KEY`로
정정합니다. 다른 동료는 `newsroom comment ARTICLE_ID --revision N --body BODY --key KEY`로
근거나 활용 경험을 추가할 수 있습니다. 정정 제목은 다시 알리고 댓글은 본문 조회 때만
보여 줍니다. 기본 `read`는 현재 본문만 반환합니다. `read --history`로 정정 이력과 댓글을
명시적으로 요청하고 `--after`·`--limit`으로 나눠 읽습니다. `seen EVENT_ID`로 확인을 남깁니다.
본문·댓글은 자동 공유 기억으로 복제하지 않습니다. 기사는 동료의 보고이며 승인된 스펙이나
검증 결과를 대신하지 않습니다.

shell이 없는 작업은 설치된 `neurath_collaboration` 서버의 `agent` 도구를 사용합니다.
예를 들어 `{"argv":["newsroom","read","ARTICLE_ID"]}`를 전달합니다. 같은 도구에서
`agent send/reply/inbox` 등 직접 대화도 가능합니다. 신원 토큰은 호스트 훅이 입력에 넣으며
에이전트가 발신자를 지정하지 않습니다. 설치 시 기존 MCP 서버와 권한은 보존합니다.
호스트가 프로젝트 MCP의 신뢰를 요구하면 해당 설정을 통해 활성화해야 합니다.
Codex의 읽기 전용 작업에서도 통신하려면 설치된 전용 `agent` 도구를 허용해야 하므로
이 새 MCP 항목에만 `approval_mode = "approve"`를 설정합니다. 호출마다 실제 호스트 신원과
정확한 요청을 별도로 검사하며, 기존 도구·전역 승인 정책·파일 권한은 바꾸지 않습니다.

## 독립 작업에 연락하기

실제 호스트 신원이 등록된 세션은 훅을 실행할 때 주소록에 나타납니다. 오래전에 종료된 세션은
다시 실행되기 전까지 나타나지 않을 수 있습니다. 등록된 자식 에이전트도 별도의 주소를 가집니다.
이름은 사람이 읽기 위한 설명이며, 전송에는 `discover`가 반환한 정확한 `address`를 사용합니다.

```sh
.neurath/run agent register --name "API 구현" --summary "페이지 조회 API와 응답 형식 담당"
.neurath/run agent discover --query "화면"
.neurath/run agent send --to 'claude-code:SESSION_ID' \
  --message "목록 API에 필요한 페이지 정보가 무엇인가요?" --key pagination-question-1
```

수신자는 자기 호스트의 도구에서 다음 명령을 사용합니다. 발신자는 호출자의 실제 신원에서
결정하며 `--from`으로 다른 작업을 사칭할 수 없습니다.

```sh
.neurath/run agent inbox
.neurath/run agent message MESSAGE_ID
.neurath/run agent reply MESSAGE_ID --message "다음 cursor와 has_more가 필요합니다" --key pagination-answer-1
.neurath/run agent ack MESSAGE_ID
.neurath/run agent conversation CONVERSATION_ID
.neurath/run agent wait --conversation CONVERSATION_ID --timeout 30
.neurath/run agent close CONVERSATION_ID
```

`reply`는 원래 메시지의 수신 확인도 함께 기록합니다. 답변하지 않고 읽기만 했다면 `ack`합니다.
재시도에는 같은 key와 같은 내용을 사용합니다. 같은 key로 다른 내용을 보내면 오류입니다.
새 대화는 기본 최대 32개 메시지·24시간이며, 최초 `send`에서 `--max-messages`와 `--ttl`로
설정할 수 있습니다. 대화 참여자가 종료하면 추가 답장은 거부됩니다. 서로 다른 상대에게는
각각 대화를 열 수 있습니다. 종료된 대화를 자동으로 다시 만들지 않습니다.

## 즉시 전달과 중단 후 수신

기본 보관함은 `SessionStart`, `SubagentStart`, `UserPromptSubmit`, `PostToolUse`에서
미확인 메시지를 문맥에 추가합니다. 미리보기는 크기가 제한되며 전체 내용은 `agent message`로
읽습니다. 훅이 내용을 출력했다는 사실만으로 수신 확인하지 않아 중단 뒤에도 다시 받을 수 있습니다.

Codex 앱의 메시지 보내기 도구가 제공되는 환경에서는 다음 흐름으로 즉시 알릴 수 있습니다.

1. `agent send`로 원본 메시지를 보관합니다.
2. `agent forward MESSAGE_ID`가 반환한 `tool`과 `arguments`로 호스트의
   `send_message_to_thread`를 호출합니다.
3. 호스트가 성공 응답을 반환한 뒤 `agent submitted MESSAGE_ID --transport codex-app`을 기록합니다.

네이티브 알림에는 메시지 본문 대신 보관함을 조회하는 참조를 넣습니다. 수신자는 자기 신원으로
원본 메시지에 접근해야 합니다. 이 도구가 없거나 목적지에 접근할 수 없으면 보관함에 남습니다.
Claude의 일반 세션이나 CLI 세션을 임의로 동시에 재개하지 않으며, 다음 훅 또는 사용자의 재개를
기다립니다. `delegate resume`는 이 실행기로 생성한 자신의 외부 실행을 후속 호출할 때 사용합니다.

| 상태 | 확인된 사실 |
| --- | --- |
| `queued` | 보관함에 저장됨 |
| `submitted` | 발신자가 호스트 도구의 성공 응답을 보고 전송을 기록함 |
| `received` | 실제 수신자가 ack함 |
| `replied` | 실제 수신자가 답장함 |

주소록의 상태는 마지막 훅 관측이며 실시간 프로세스 생존 증명이 아닙니다. 별도 복제본·다른 컴퓨터·
원격 네트워크와의 통신 및 표준 A2A 프로토콜 호환은 이 로컬 메시징의 범위에 포함되지 않습니다.

## 작업 소식 구독

```sh
.neurath/run agent subscribe --to 'codex:SESSION_ID'
.neurath/run agent publish --message "응답 스키마 v2를 준비했습니다. 해당 커밋을 확인해주세요" --key schema-v2
.neurath/run agent unsubscribe --to 'codex:SESSION_ID'
```

발행한 소식은 그 작업을 구독한 상대에게만 전달됩니다. 파일이 바뀔 때 자동 발행하는 기능은
없으며 작업 에이전트가 의미 있는 변경을 골라 발행합니다.

메시지는 항상 `peer-request`입니다. 동료의 내용이 사용자의 지시보다 우선하지 않고,
다른 세션의 상태 API·파일 소유권·독립 평가 권한을 부여하지 않습니다. 수신자는 자신의 목표와
권한에 따라 수락·거절·보류합니다. 연락과 실제 코드 변경·테스트 실행·완료 판정은 각각 기록합니다.

주소록·대화·실행 결과는 Git 공통 control root의 `.neurath/local/agents`에 보관하며 배포본에
포함하지 않습니다. 테스트는 메시지 왕복·중복 방지·수신자 권한·재개 시 수신·provider 오류·시간 제한·
취소를 검증합니다. 실제 계정의 모델 접근이나 호스트 훅 활성화는 별도의 실제 실행 확인이 필요합니다.
