<!-- date: 2026-09-13; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[English](../../en/contributing/collaboration-contract.md)

# 출처를 보존하며 작업 전달하기

협업 메시지는 논리적 수신자를 지정한 지속적인 기록입니다. 전달 계약은 재시도 중에도 식별자와 내용을 보존하며, 작업 수락과 실제 작업 효과는 별도로 확인합니다. 저장소가 보존되고 승인된 수신자가 언젠가 사용 가능한 상태가 된다는 조건이 필요합니다. 그전에는 전달 대기나 복구 필요 상태가 정확한 결과입니다.

## 먼저 저장하고 알림 보내기

메시지에는 `message_id`, 발신자, 논리적 수신자, 종류, 대화, 본문과 digest, 생성 시각, 선택적인 작업·응답 연결이 남습니다. 저장을 완료한 뒤 결과를 반환하거나 transport에 알립니다. 바로 전달된 알림이 조회 ID만 담더라도 호출자가 지정한 안정적인 키는 수신자가 확인할 수 있어야 합니다.

`collaboration_register`로 인증된 참여자를 알리고 `collaboration_discover`로 정확한 주소를 찾습니다. 네이티브 UUID·PID·actor·socket을 추측해서 논리적 수신자 대신 쓰면 안 됩니다. 메일함은 Git 공통 프로젝트 런타임 데이터베이스를 사용하며 별도 clone과 자동 공유하지 않습니다.

`collaboration_send`는 단건 필드 `to`, `message`, `key`, `kind` 또는 `messages` 배열 중 하나를 받습니다. 두 형식을 섞지 않습니다. 묶음의 각 항목에는 비어 있지 않은 수신자 배열·본문·키가 필요하며 지정한 대상 전체에 원자적으로 저장합니다. 같은 키와 같은 내용은 중복 처리하고 같은 키의 다른 내용은 충돌합니다. 아래 주소를 실제 탐색 결과로 바꿔 사용합니다.

```json
{
  "messages":[
    {
      "to":["DISCOVERED_PEER_ADDRESS"],
      "message":"문서의 응답 설명이 현재 API 테스트와 일치하는지 읽기 전용으로 확인해 주세요.",
      "key":"response-contract-question-1",
      "kind":"question"
    }
  ]
}
```

단건 본문은 최대 16,000자입니다. 묶음은 최대 32개 항목, 항목별 최대 32개의 중복 없는 수신자, 항목별 최대 32,768자 본문을 받습니다. 형식상 가능한 크기가 공개 대상 확대나 새 작업의 승인을 뜻하지는 않습니다.

## 본문을 읽은 뒤 수신 확인

| 상태 | 확인된 사실 | 아직 확인하지 않은 사실 |
| --- | --- | --- |
| `queued` | 메시지가 저장됨 | transport 수락 |
| `submitted` | 호스트 transport가 입력을 수락함 | 수신자의 읽기·ACK |
| `received` | 의도한 수신자가 ACK함 | 작업 수락·실제 효과 |
| `replied` | 수신자의 응답을 저장함 | 발행자의 작업 결과 수락 |

수신자는 `collaboration_inbox`, `collaboration_message`로 전체 본문을 읽습니다. `collaboration_ack`에는 단일 `message_id` 또는 이미 읽은 본문들의 `message_ids` 배열을 전달할 수 있습니다. ID 알림만 받았거나 본문 조회가 실패했다면 ACK할 수 없습니다. `collaboration_reply`는 `message_id`, `message`, `key`로 ACK와 응답을 원자적으로 기록합니다.

ACK는 실제 수신자임을 인증하고 지속적으로 저장하며 반복 호출해도 같은 의미를 유지합니다. 이미 읽은 중복 메시지는 다시 ACK할 수 있습니다. ACK는 재전송을 멈추는 수신 확인이며 작업 수락이나 외부 효과 인증이 아닙니다. 전달과 ACK의 중복은 허용됩니다. 외부 효과의 정확히 한 번 실행은 보장하지 않으므로 필요한 작업은 자체 중복 방지를 구현해야 합니다.

일반 동료 작업은 `collaboration_assign` → `collaboration_accept` → `collaboration_report`로 연결합니다. 보고 상태는 `started`, `waiting`, `error`, `failed`, `cancelled`, `completed`입니다. 발행자는 결과를 읽고 완료 수락·취소·확인된 인계까지 후속 책임을 유지합니다. 동료 요청은 실제 사용자 권한을 따릅니다. 일반 동료 보고가 명시적 단계 계약의 독립 검토 결과로 바뀌지는 않습니다.

## 같은 메시지로 재시도

소유한 transport는 같은 ID·키·수신자·본문을 재전달합니다. 시도별 제한 시간과 backoff는 빈도를 조절하며 일반 작업의 수명이나 지속적인 재시도 기회를 소진시키지 않습니다. 데이터베이스 변경, 호스트 준비, 재연결, 메시지별 기한이 시도를 유발합니다. 승인·입력 대기는 관련 준비 이벤트를 기다립니다. 연결할 수 없는 대상은 상태를 반복 조회하거나 바쁘게 순환하지 않고 간격을 둡니다.

전송 중·불확실·실패·ACK 없는 제출 상태는 지원되는 재시도 대상입니다. 수신 프로세스 부재나 ACK 유실만으로 dead-letter가 되지 않습니다. 수신 endpoint generation과 ACK가 오래된 시도의 늦은 결과를 차단하고 lease가 식별자 탈취를 막습니다. 새 네이티브 세션 UUID가 기존 메일함을 자동 승계하지 않습니다.

`collaboration_forward`가 지원되는 호스트 도구와 정확한 인자를 반환하면 그 경로로 실행합니다. 실제 도구가 성공한 뒤에만 `collaboration_submitted`를 호출합니다. 경로 제안만으로 제출을 기록하면 안 됩니다. 즉시 연결할 수 있는 지원 bridge가 없으면 다음 지원 훅·재개까지 `queued`를 유지합니다. 공유 기록을 읽는 기능만으로 Desktop 자동 깨우기가 생기지 않습니다.

`collaboration_conversation`은 대화 상태를 읽습니다. 일반 대화의 기본 한도는 24시간 동안 32개 메시지이며, 새 활동을 제한해도 이미 수락한 대기 메시지는 삭제하지 않습니다. `collaboration_close`는 대기 의무를 보존하거나 명시적으로 승인된 취소를 기록합니다. 대화 종료가 소유권을 이전하지는 않습니다. 지속적인 구독은 `collaboration_subscribe`, `collaboration_publish`, `collaboration_unsubscribe`로 관리합니다.

## 전달 보류 원인 복구

`delivery_status`는 `message_id`를 받아 현재 전달 상태, 최근 시도, 복구 보류를 반환합니다. dead-letter 보류에는 본문·실패 이력·복구 요구가 유지됩니다. 현재 분류에는 envelope-version과 recipient-binding 문제가 있습니다.

실제 원인을 고친 뒤 인증된 소유자가 `delivery_redrive`에 원래 `message_id`, 반환된 `expected_revision`, `repair_reference`, 안정적인 `key`를 전달합니다. 참조는 복구를 설명할 뿐 transport가 유효하다는 증거를 대신하지 않습니다. 실제 경로가 원래 수신자·내용을 유지하며 다시 확인합니다. 권한 확대, 취소된 작업 부활, 비공개 DB 행 수정으로 수신자 변경은 허용하지 않습니다.

| 중단 상황 | 보존할 정보 | 복구 시 확인할 결과 |
| --- | --- | --- |
| 전송 전 수신자 종료 | 원래 메시지와 키 | 승인된 복원 수신자에게 전달 재개 |
| 입력 후 ACK 전 종료 | 같은 본문과 시도 이력 | 중복 본문을 읽고 ACK 가능 |
| transport·ACK 응답 유실 | 불확실·ACK 없는 시도 | 수신 사실을 꾸미지 않고 재시도로 진행 |
| endpoint 변경 후 예전 시도 완료 | generation과 현재 ACK | 늦은 결과가 새 상태를 되돌리지 않음 |
| 대기 입력이 있는 대화 만료·종료 | 이미 수락한 의무 | 대기 또는 명시적 취소가 계속 보임 |
| 복구 보류 해제 | revision·복구 참조·원래 메시지 | 실제 transport 확인에 따라 진행 |

## 활성 동료에게 발견 공유

뉴스룸은 전체 대화를 복사하지 않고 짧은 발견을 알립니다. `newsroom_publish`에는 `title`(1–30자), `body`(1–16,000자), `key`가 필요합니다. 일반 호스트 이벤트에서 제목과 조회 ID를 알리고 관련 있는 동료가 `newsroom_read`로 본문을 읽습니다. `newsroom_headlines`, `newsroom_peers`로 탐색하고 `newsroom_seen`으로 확인을 기록합니다.

수정은 `newsroom_revise`에 `article_id`, 현재 `revision`, `title`, `body`, `key`를 전달합니다. 의견은 `newsroom_comment`에 같은 식별자·revision과 본문·키를 전달합니다. 출처와 revision을 보존합니다. 현재 활성 상태가 확인된 세션·자식이 참여하며 활동은 10분 뒤 만료됩니다. 훅 알림은 최대 3,000바이트이고 발행·수정·의견은 작성자별 분당 20회로 제한됩니다.

대기·일시 정지·종료된 동료는 깨우지 않습니다. 비활성 중 놓친 알림은 재생하지 않습니다. 본문을 메모리·부모 대화·공식 보고에 자동 복사하지 않습니다. 기사는 출처 있는 보고이며 승인된 명세나 검증 완료 결과가 아닙니다.

## 구현과 수락 검증

[에이전트 저장소](../../../src/neurath/agents/store.py), [전달](../../../src/neurath/agents/delivery.py), [복구](../../../src/neurath/agents/delivery_recovery.py), [뉴스룸](../../../src/neurath/agents/newsroom.py)이 이 동작을 담당합니다. [통신 테스트](../../../tests/test_communication_mcp.py), [전달 복구 테스트](../../../tests/test_delivery_recovery.py), [뉴스룸 테스트](../../../tests/test_newsroom_mcp.py)는 스키마와 fixture 동작을 검사합니다.

실제 수락 검증에는 Codex·Claude 네 방향, 유휴 발행자의 소유 연결을 통한 수신, 전송 전후 종료, ACK 유실, 오래된 generation, 대기 메시지 보존, 복구 후 재전달, 긴 작업 중 메시지·취소 처리가 필요합니다. 이는 확인할 시나리오이며 현재 모든 호스트 조합을 새로 인증했다는 뜻은 아닙니다. 연결 소유권은 [provider transport](provider-transports.md), 식별은 [에이전트 참조](agents-reference.md)를 참고합니다.
