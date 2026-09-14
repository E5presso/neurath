<!-- date: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# 정확한 Neurath 릴리스를 검토하고 적용하기

[English](../../en/contributing/releases-reference.md) · [설치 설계](installation-design.md)

릴리스 업데이트는 프로젝트 설정과 보고 동의를 보존하면서 프로젝트가 선택한 Neurath 런타임과 관리 파일을 교체합니다. 적용 가능한 릴리스를 찾고, 정확한 파일 변경을 준비하고, 그 미리보기에 대한 사용자 결정을 받은 다음 같은 후보를 적용하는 순서입니다. **Offer**는 해당 후보의 보존된 설명이며, ID를 통해 결정이 특정 릴리스와 wheel에 연결됩니다.

## 프로젝트 작업을 이어가며 후보 확인하기

`releases_status`는 로컬 상태를 읽습니다. `releases_check`는 안정적인 요청 키로 새 버전을 확인합니다.

```json
{"key": "release-check-1"}
```

대상은 고정된 공개 [Neurath 릴리스 저장소](https://github.com/E5presso/neurath/releases)입니다. 일반 확인 간격은 86,400초입니다. 훅은 확인할 때가 되면 짧은 로컬 안내만 남기고, 네트워크 요청이나 새 세션 시작은 하지 않습니다. `force:true`는 사용자가 지금 다시 확인하라고 명시적으로 요청했을 때 사용합니다. `releases_notice`는 키를 받아 해당 버전의 안내를 한 번 기록합니다.

네트워크 요청 전에 시도 시각을 저장하므로 실패하거나 중단된 요청에도 간격 제한이 적용됩니다. `unavailable`은 신뢰할 결과를 얻지 못했다는 뜻이며 설치 버전이 최신이라는 뜻이 아닙니다. 저장 필터 수정 같은 원래 작업을 계속하며 업데이트 확인 결과를 별도로 설명합니다.

후보는 공개된 안정 버전이어야 하며, 현재보다 높은 `vMAJOR.MINOR.PATCH` 태그와 업로드된 `neurath-VERSION-py3-none-any.whl` 하나, 허용 크기, SHA-256 다이제스트가 있어야 합니다. 요청은 인증 없이 고정된 공개 엔드포인트로 보내며 프로젝트 ID나 로컬 버전 데이터를 전송하지 않습니다. Wheel은 최대 32 MiB, JSON은 최대 512 KiB, 요청 제한 시간은 10초입니다. 릴리스 노트는 길이를 제한한 표시 데이터이며 실행 지침으로 사용하지 않습니다.

## 결정을 묻기 전에 정확한 변경 준비하기

반환된 offer ID를 `releases_prepare`에 전달합니다.

```json
{"offer_id": "RETURNED_OFFER_ID", "key": "release-prepare-1"}
```

준비 과정은 같은 릴리스를 다시 읽고 wheel의 크기·다이제스트, 압축 파일 경로, 패키지 ID, 메타데이터, 허용 의존성, 매니페스트를 확인합니다. 현재 허용 의존성은 `claude-agent-sdk>=0.2.152,<0.3`이며 후보 도구 환경에만 설치합니다. 준비된 작업에는 후보 배포본, 대상 설치 `plan_id`, 경로별 변경이 남습니다.

사용자는 이 구체적인 미리보기를 보고 결정해야 합니다. `maintenance_choice_prepare`로 네이티브 질문을 준비합니다.

```json
{"operation": "releases_choose", "target_id": "RETURNED_OFFER_ID", "key": "release-question-1"}
```

반환된 질문을 그대로 보여 줍니다. `user_choice_ref`는 준비한 질문을 식별하며 실제 네이티브 사용자 답변이 있어야 사용할 수 있습니다. 여기서 **receipt**는 실제 호스트 이벤트와 답변을 연결한 보존 기록입니다. 에이전트가 권한을 나타내려고 임의로 넣는 문자열이 아닙니다. 후보를 준비하기 전에는 `no`와 `later`를, 준비한 후에는 `yes`까지 선택할 수 있습니다.

실제 긍정 답변을 받은 다음 `releases_choose`로 정확한 결정을 기록합니다.

```json
{"offer_id": "RETURNED_OFFER_ID", "decision": "yes", "user_choice_ref": "RETURNED_USER_CHOICE_REF", "key": "release-choice-1"}
```

`no`, `later`도 유효한 결정이며 같은 버전의 반복 안내를 막습니다. 응답이 없으면 상태는 바뀌지 않습니다. 새 준비 작업은 이전 긍정 결정을 무효화합니다. 새로 준비한 계획을 사용자가 다시 검토해야 하기 때문입니다.

## 적용하고 결과 읽기

`releases_apply`의 입력은 다음과 같습니다.

```json
{"offer_id": "RETURNED_OFFER_ID", "key": "release-apply-1"}
```

같은 릴리스를 재확인하며, 이전 결정으로 더 새로운 “latest”를 골라 적용하지 않습니다. 트랜잭션 설치기를 호출하기 전에 `applying`을 저장합니다. 성공 시 반환된 설치 기록, 선택한 버전과 배포본, 파일 배치·프로토콜 진단, 보고 동의 보존을 확인합니다.

`applied`는 설치를 확인하는 결과입니다. **활성화**는 선택한 호스트가 새 연동으로 실제 후속 이벤트를 처리하기 전까지 미확인입니다. **런타임**은 프로젝트 실행기가 이제 선택하는 격리된 후보 환경입니다. 이 관찰을 소스 검사나 사용자의 앱 작업 결과와 구분합니다.

## 중단되거나 변경된 후보 복구하기

`release changed; check and review a new offer`는 릴리스 메타데이터나 내용이 더 이상 일치하지 않는다는 뜻입니다. `prepared runtime changed`, `prepared installation plan changed`는 보존한 후보 자체가 달라졌음을 뜻합니다. 근거를 보존하고 다시 준비·검토합니다. 이전 결정이 변경된 후보를 승인하지는 않습니다.

작업이 `applying`에 남았거나 적용한 업데이트를 되돌려야 한다면 안정적인 키로 `releases_recover`를 사용합니다. 보존한 전후 상태를 확인하고 필요한 경우 설치 저널을 사용하여 이전 설치를 보수적으로 복원합니다. 결정은 `later`로 기록합니다. 사용자가 관련 경로를 동시에 편집했다면 지우는 대신 충돌을 반환합니다. 현재 상태를 읽고 충돌을 해결한 뒤 다음 업데이트로 진행합니다. 복구 대상이 없으면 `nothing-to-recover`입니다.

## 터미널 참조와 구현 근거

현재 정책이 허용하는 네이티브 CLI 경로에서도 같은 순서를 제공합니다.

```sh
neurath releases status
neurath releases check
neurath releases notice
neurath releases prepare OFFER_ID
neurath releases choose OFFER_ID yes --user-confirmed
neurath releases apply OFFER_ID
neurath releases recover
```

`check --force`에는 실제 재확인 요청이 필요합니다. `--user-confirmed`는 실제 사용자 결정을 기록하며 결정을 대신 만들지 않습니다. 설치된 에이전트 세션에서는 명명 도구와 네이티브 질문 참조로 결정 대상을 명확히 연결합니다. 보고 동의는 별도 결정입니다. [보고 참조](reporting-reference.md)를 참고하세요.

소스: [릴리스 서비스](../../../src/neurath/updates.py), [후보 설치기](../../../src/neurath/release_install.py), [네이티브 결정](../../../src/neurath/runtime/user_choices.py), [CLI](../../../src/neurath/updates_cli.py). 테스트: [릴리스 검증·복구](../../../tests/test_updates.py), [사용자 결정](../../../tests/test_user_choices.py), [명명 결정 도구](../../../tests/test_user_choices_mcp.py). 새 wheel을 사용한 업데이트 검증은 [검증 안내](validation.md)에 있습니다.
