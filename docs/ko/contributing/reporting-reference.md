<!-- date: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# 공개할 수 있는 하네스 보고서 준비하기

[English](../../en/contributing/reporting-reference.md) · [기여자 시작 안내](index.md)

Neurath 공개 보고서는 사용자 프로젝트를 드러내지 않으면서 공통 하네스의 결함이나 개선점을 설명해야 합니다. 사용자 앱의 버그는 원래 태스크에 속합니다. 예를 들어 저장 필터가 새로고침 후 사라지는 현상이 곧 Neurath 결함은 아닙니다. 별도로 관찰한 하네스 문제만 이 보고 경로를 사용합니다.

보고서는 고정된 [E5presso/neurath 이슈 저장소](https://github.com/E5presso/neurath/issues)에 게시합니다. 공통 결함·개선 보고에는 프로젝트에 저장한 명시적 보고 동의가 필요합니다. 프로젝트 전용 변경에서 나온 제안을 포함한 기여 보고는 공개할 정확한 초안을 승인받아야 합니다. 설정과 훅은 결정을 안내할 수 있지만 훅이 보고서를 수집하거나 보내지는 않습니다.

## 보고 동의 확인하기

`reporting_status`에 `{}`를 주어 읽습니다. `auto_report`는 동의 대기 중이면 `null`, 거절하면 `false`, 켜져 있으면 `true`입니다. 동의 대기 중에는 자동 보고를 끄고 사용자의 원래 태스크는 계속합니다. 새 복제본은 이 비공개 결정을 상속하지 않습니다.

네이티브 질문은 `maintenance_choice_prepare`로 준비합니다.

```json
{"operation": "reporting_consent", "key": "reporting-question-1"}
```

정확히 반환된 질문을 보여 주고 실제 사용자 답변을 기다립니다. `user_choice_ref`는 질문과 그 대상을 식별합니다. 네이티브 **receipt**는 사용자가 해당 질문에 답했다는 호스트의 보존 기록입니다. 에이전트가 쓴 “예”나 다른 곳에서 복사한 참조는 이 기록을 대신하지 못합니다. 실제 답변이 있으면 `reporting_consent`를 사용합니다.

```json
{"decision": "yes", "user_choice_ref": "RETURNED_USER_CHOICE_REF", "key": "reporting-consent-1"}
```

반환된 질문만 최종 메시지로 보내고 앞뒤에 설명을 덧붙이지 않습니다. Claude에서는 사용자의 새 텍스트 답변을 사용합니다. `AskUserQuestion` 도구 결과는 필요한 프롬프트 기록을 만들지 않으므로 이 동의 경로에 사용하지 않습니다. `yes`, `네`, `동의합니다`, `ok`, `no`, `아니요` 같은 답변을 인식하며, 오류는 질문이 달라진 경우와 답변을 인식하지 못한 경우를 구분합니다.

거절하거나 철회할 때는 `no`를 사용합니다. 보고 상태는 비공개 `LocalState`/SQLite의 기준 기록에 저장합니다. 옛 보고 JSON은 이전 데이터를 가져오는 입력이며 별도의 현재 기준 상태가 아닙니다.

## 제한된 초안을 작성하고 읽기

`reporting_prepare`는 `report`, `privacy_reviewed:true`, 안정적인 `key`를 받습니다. 보고 객체에는 정확히 여덟 필드가 필요합니다.

```json
{
  "report": {
    "kind": "improvement",
    "scope": "common",
    "component": "reporting.py",
    "summary": "보존된 초안 상태를 쉽게 설명하도록 개선",
    "expected": "에이전트가 공개 보고서의 전달 여부를 설명할 수 있다.",
    "observed": "상태 표현을 설명하려면 추가 안내가 필요할 수 있다.",
    "reproduction": "준비한 초안과 그 상태 응답을 읽는다.",
    "proposal": "보존되는 각 전달 상태의 의미를 설명한다."
  },
  "privacy_reviewed": true,
  "key": "report-draft-1"
}
```

형식을 설명하는 예시이며 실제 결함을 관찰했다는 주장은 아닙니다. 실제 보고를 준비할 때는 확인된 관찰로 바꿉니다. `component`는 템플릿을 제외하고 매니페스트에 존재하는 Neurath 패키지 파일이어야 하며 내용도 패키지와 일치해야 합니다. 수정된 설치 자산은 공통 보고 대신 `contribution`으로 제안합니다.

`kind`는 `defect`, `improvement`, `contribution`이고 `scope`는 `common`, `project-specific`입니다. 프로젝트 전용 범위는 기여 종류를 사용해야 합니다. 본문 필드는 비어 있지 않은 최대 2,400자이고 `summary`는 최대 140자의 한 줄입니다. 서비스의 이 제한은 일반 스키마의 문자열 길이보다 엄격합니다. 로그, 첨부, 추가 필드, 위험한 마크업, 링크, 경로, 자격 증명, 비공개 원격 저장소·프로젝트 이름 패턴은 거부합니다. 자동 검사는 에이전트의 의미상 개인정보 검토를 보완합니다.

준비 결과의 불변 초안 ID는 공개 제목, 본문, 목적지에 연결됩니다. `reporting_read`에 `{"draft_id":"RETURNED_DRAFT_ID"}`를 주어 읽고, `reporting_list`로 보존된 ID·상태·URL을 조회합니다. 내용을 바꾸면 새 초안과 필요한 새 승인을 받아야 합니다.

## 기여 초안을 승인받은 뒤 제출하기

기여 보고에서는 `operation:"reporting_approve"`, 초안 ID를 가리키는 `target_id`로 네이티브 질문을 다시 준비합니다. 질문에 정확한 공개 초안이 포함됩니다. 실제 답변 후 `reporting_approve`에 `draft_id`, `decision`, `user_choice_ref`, `key`를 전달합니다. 공통 보고 동의가 기여 내용을 승인하지는 않습니다.

동의가 있는 공통 보고나 승인된 기여는 `reporting_submit`에 다음 입력을 주어 제출합니다.

```json
{"draft_id": "RETURNED_DRAFT_ID", "key": "report-submit-1"}
```

제출은 연결 작업 트리 사이에서도 직렬화됩니다. 네트워크 요청 전에 `uncertain`을 저장하고 고정된 저장소에 이슈를 만든 뒤, 원격 이슈를 다시 읽어 URL·제목·본문을 비교합니다. 검증된 결과만 `submitted`가 됩니다. 비공개 임시 본문 파일과 명시적인 목적지 덕분에 전송은 대상 프로젝트의 GitHub 원격 설정과 독립적으로 동작합니다.

## 전달 여부가 불확실할 때 중복 없이 확인하기

서버가 이슈를 받은 뒤 연결이나 인증 문제가 생길 수 있습니다. 따라서 초안 상태가 아닌 보고를 다시 submit하면 재전송 대신 보존된 상태를 반환합니다. `uncertain`이라면 고정된 원격 저장소와 인증을 확인합니다. 이슈가 존재하면 `reporting_reconcile`을 사용합니다.

```json
{"draft_id": "RETURNED_DRAFT_ID", "url": "https://github.com/E5presso/neurath/issues/123", "key": "report-reconcile-1"}
```

위 URL은 예시이므로 실제 기존 이슈로 바꿉니다. Reconcile은 고정된 저장소의 이슈만 받고 정확한 내용을 비교합니다. 내용이 다르면 오류로 남습니다. 전달 불확실성은 다른 게시 경로나 자동 재전송의 근거가 아니며, 사용자의 원래 태스크 완료 여부도 바꾸지 않습니다.

## 터미널 형식과 진단

```sh
neurath report status
neurath report consent yes --user-confirmed
neurath report prepare PRIVATE_REPORT.json --privacy-reviewed
neurath report read DRAFT_ID
neurath report approve DRAFT_ID yes --user-confirmed
neurath report submit DRAFT_ID
neurath report reconcile DRAFT_ID EXISTING_ISSUE_URL
neurath report list
```

입력 파일은 최대 20,000바이트입니다. 확인·검토 플래그는 실제로 수행한 검토와 결정을 기록합니다. 설치된 네이티브 세션에서는 현재 정책에 따라 명명 도구를 사용합니다. `invalid reporting state; publication disabled`, `report content changed`, `upstream issue readback differs from approved report`는 구체적인 상태·식별 문제이므로 해당 문제를 해결해야 합니다. 서비스를 우회하라는 뜻이 아닙니다.

소스: [보고 서비스](../../../src/neurath/reporting.py), [CLI](../../../src/neurath/reporting_cli.py), [네이티브 결정](../../../src/neurath/runtime/user_choices.py). 테스트: [개인정보·동시성·전달](../../../tests/test_reporting.py), [네이티브 결정](../../../tests/test_user_choices_mcp.py).
