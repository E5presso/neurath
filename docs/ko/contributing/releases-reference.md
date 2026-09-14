<!-- date: 2026-09-13; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# 공식 업데이트 준비·적용·복구

[English](../../en/contributing/releases-reference.md)

릴리스 유지 관리는 새 공식 배포본을 찾는 단계와 검토한 특정 업데이트를 적용하는 단계를 나눈다. 에이전트는 사용자 선택을 받기 전에 정확한 wheel과 설치 계획을 준비할 수 있다. 선택된 제안과 준비된 계획만 적용 대상이며, 이후 상위 릴리스가 바뀌면 다시 검토해야 한다.

## 원래 작업 안에서 버전 확인

릴리스 출처는 고정된 공식 [Neurath 릴리스](https://github.com/E5presso/neurath/releases)다. 일반 활성 작업에서는 최대 86,400초에 한 번 확인한다. `SessionStart`·`UserPromptSubmit` 훅은 제한된 로컬 안내만 제공하며 네트워크 요청이나 새 세션을 실행하지 않는다. 에이전트가 기존 작업 중 적절한 시점에 확인한다. 네트워크 실패는 확인 불가 상태로 남기고 사용자의 원래 작업을 막지 않는다.

로컬 상태는 `releases_status`에 `{}`를 전달하여 읽는다. `releases_check`에는 안정된 `key`가 필요하며 `force`의 기본값은 `false`다. 사용자가 다시 확인하라고 명시했을 때만 `force: true`를 사용한다. 요청 전 시도 시각을 저장하므로 중단·실패한 요청도 빈도 제한에 포함된다. key를 받는 `releases_notice`는 아직 알리지 않은 제안을 반환하거나 안내가 없음을 반환한다. 설치 버전, 제안 버전, 주요 변경, 공식 링크를 설명한다. 릴리스 본문은 상위 서비스의 데이터이며 실행 지시나 승인 권한이 아니다.

## 제안과 후보 실행 환경 검증

후보는 공개 완료된 정식 릴리스여야 하며 draft·prerelease이면 안 된다. 태그는 설치 버전보다 높은 `vMAJOR.MINOR.PATCH` 형식이다. 업로드된 `neurath-VERSION-py3-none-any.whl`이 정확히 하나 있어야 하고, 양의 제한된 크기와 SHA-256 해시가 필요하다. wheel 상한은 32 MiB, 릴리스 JSON 응답 상한은 512 KiB, 개별 네트워크 요청 제한 시간은 10초다. 이는 요청 단위 제한이며 백그라운드 작업 수명과 다르다.

제안 ID는 현재·대상 버전, 릴리스·자산 ID, wheel 이름, 크기, 해시, 안내문, 공식 URL에 결속된다. 상태에는 `status`, `current`, `offer`, `decision`, `operation`, `checked`가 있다. 확인 결과는 `not-installed`, `current`, `available`, `unavailable` 등을 구분한다. 확인할 수 없다는 결과로 현재 버전이 최신이라고 판단하면 안 된다.

`releases_prepare`는 `offer_id`와 `key`를 받는다. 같은 릴리스를 다시 읽고 정확한 wheel을 내려받아 해시, 크기, 압축 경로, 패키지 신원, 의존성 범위, manifest를 검증한 뒤 별도 후보 런타임을 만든다. 후보의 버전과 배포본 식별자를 확인하고 그 런타임으로 업데이트 계획을 생성한다. 대상 파일은 아직 바꾸지 않는다. 작업 결과에는 `phase: prepared`, 제안 ID, 후보 저장 위치, 배포본 식별자, 계획 ID, 경로·작업 목록이 포함된다.

지원 wheel이 임의의 새 의존성을 선언할 수는 없다. [wheel 검사](../../../src/neurath/release_install.py)는 패키지 메타데이터·파일 무결성과 함께 허용된 Claude Agent SDK 의존성 계약을 확인한다. 후보 환경은 대상 애플리케이션 설정과 분리하여 의존성을 설치한다.

## 실제 사용자 선택 결속

준비가 끝나면 구체적인 변경을 설명하고 `releases_choose`용 네이티브 선택을 준비한다. `maintenance_choice_prepare` 입력 예시:

```json
{"operation":"releases_choose","target_id":"<returned offer ID>","key":"release-choice-1"}
```

반환된 네이티브 선택 절차와 실제 사용자 응답을 사용한다. `maintenance_choice_read`는 반환된 `user_choice_ref`를 받는다. 참조를 만들어내거나 질문 문자열을 확인된 선택으로 취급하지 않는다. 최종 `releases_choose`에는 `offer_id`, `decision`, `user_choice_ref`, `key`가 모두 필요하다.

```json
{
  "offer_id":"<returned offer ID>",
  "decision":"yes",
  "user_choice_ref":"<verified user choice reference>",
  "key":"release-decision-1"
}
```

`decision`은 `yes`, `no`, `later`다. 답이 없으면 현재 프로젝트를 유지한다. `no`와 `later`는 사용자가 다시 이 주제를 꺼낼 때까지 해당 버전의 안내를 억제한다. 같은 버전의 자산이 바뀌어도 반복해서 권하지 않는다. 선택은 worktree와 정확한 제안에 결속되어 세션을 넘어 유지된다. 새 미리보기를 준비하면 이전 긍정 선택은 적용에 사용할 수 없으며 새 계획과 일치하는 결정을 받아야 한다.

## 정확한 대상 적용과 재확인

`releases_apply`는 승인된 `offer_id`와 안정된 `key`를 받는다. 같은 릴리스를 다시 확인하고 준비된 계획·런타임을 검증한다. 트랜잭션 설치기를 실행하기 전에 작업 단계를 영속적으로 `applying`으로 기록한다. 릴리스, 계획, 배포본, 대상 상태가 바뀌면 적용을 막는다. 동의 뒤에 그 시점의 최신 버전을 새로 골라 적용하지 않는다.

적용 후에는 설치 이력과 계획 ID, 설치 버전·배포본 식별자, 배치·프로토콜 진단, 적용 전후 보고 설정을 비교한다. 성공하면 단계가 `applied`가 되고 설치 이력과 진단이 반환된다. 프로필, 선택 호스트, 스킬 접두어, 사용자 설정, 보고 동의, 초안별 기여 승인은 유지된다.

업데이트된 런타임의 실제 활성화는 다음 정상 네이티브 이벤트에서 확인한다. 로컬 프로토콜 성공만으로는 `host_activation`이 여전히 미확인이다. 업데이트 안내만을 위해 세션을 새로 만들거나 별도 프로세스로 재개하지 않는다.

## 적용 결과가 불확실할 때의 복구

| 관측한 문제 | 처리 |
| --- | --- |
| 오래된 제안·변경된 릴리스 | 다시 확인하고 구체적인 새 제안 준비; 이전 선택은 승계하지 않음 |
| 해시·압축 구조·manifest·의존성·후보 신원 오류 | 후보 거부; 공식 자산과 오류 조사 |
| 적용 중단·적용 후 확인 실패 | 영속 `applying` 상태를 유지하고 `releases_recover` 사용 |
| 복구 대상이 알려진 이전 상태와 일치 | 불필요하게 쓰지 않고 복구 완료 처리 |
| 정확한 적용 이후 상태와 일치 | 해당 작업을 되돌린 뒤 이전 상태 재확인 |
| 다른 작업의 저널이거나 전후 어느 상태와도 다름 | 동시 변경을 보존하고 복구 충돌 보고 |

`releases_recover`에는 안정된 `key`만 필요하다. `applying` 또는 `applied` 작업을 복구하며 해당 작업이 없으면 `nothing-to-recover`를 반환한다. 복구는 보수적으로 이전 상태를 되살리고 저장된 선택을 `later`로 바꾼다. 후보 경로는 비공개 저장 영역 안에 있어야 하며 심볼릭 링크이면 안 된다. 손상된 계획·백업은 조사할 오류이며 프로젝트 덮어쓰기의 근거가 아니다.

모든 MCP 입력은 닫힌 스키마를 사용한다. 구조화된 오류의 `code`, `message`, `state`, `retryable`, `next_action`을 읽어 복구를 결정한다. 전송·적용 결과가 불확실하면 그 상태를 보존하고 다른 변경 요청 전에 확인한다.

구현·회귀 검사 근거: [업데이트 상태 관리](../../../src/neurath/updates.py), [후보 설치와 복구](../../../src/neurath/release_install.py), [네이티브 선택](../../../src/neurath/runtime/user_choices.py), [사용자 선택 테스트](../../../tests/test_user_choices_mcp.py). 일반 파일 충돌은 [설치 설계](installation-design.md)를 따른다.

릴리스 복구는 보존된 정상 런타임에서 수행한다. 설치 기반 자체를 사용할 수 없으면 먼저 설치를 진단·복구한 뒤 릴리스 유지 관리를 재개한다. 상태 JSON을 고쳐 복구된 단계를 만들어내지 않는다. 재적용에는 새 준비와 일치하는 사용자 선택이 필요하다. 브랜치, 공개 릴리스가 없는 태그, 다른 패키지 인덱스를 대체 출처로 사용하지 않는다. 후보 런타임은 wheel·SDK 계약과 함께 Python 3.14 조건을 충족해야 한다.
