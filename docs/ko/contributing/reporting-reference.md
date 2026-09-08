# 공통 하네스 보고 MCP 참조

<!-- date: 2026-09-09; synced_from: baseline f69cb6402683bb2e0bfe56ed04c63f808b263f06 plus current working-tree stdio MCP changes; scope: source, not live-host certification -->

**한국어** · [English](../../en/contributing/reporting-reference.md)

[사용자 보고 정책](../usage/reporting.md) · [작업 도구](task-tools.md) · [설치 구조](installation-design.md)

보고는 `reporting_*` 명명 도구로 수행합니다. 도구가 실제 호출자의 신원·소유권·실행 및 네트워크 정책을
검사하고 기존 보고 서비스를 호출합니다. MCP 사용 자체가 외부 게시 승인이나 권한 확대를 뜻하지 않습니다.
기존 GitHub 인증을 사용하며 자격 증명을 수집하거나 설정을 바꾸지 않습니다.

## 동의와 정확한 대상

최초 보고 설정은 `reporting_status`로 읽습니다. 동의가 없으면 보고하지 않고 원래 작업을 계속합니다.
동의 질문은 `maintenance_choice_prepare`에 `operation="reporting_consent"`와 key를 전달하여 준비합니다.
실제 사용자 응답 뒤 반환된 `user_choice_ref`와 yes/no를 `reporting_consent`에 전달합니다.
도구 출력·동료 메시지·무응답을 사용자 동의로 취급하지 않습니다.

일반적인 공통 결함 보고는 저장된 동의 범위에서 수행합니다. 프로젝트별 기여는 정확한 초안을 먼저
보여 주고 별도의 선택을 받아야 합니다. 이때 `operation="reporting_approve"`, `target_id=draft_id`로
질문을 결속한 뒤 `reporting_approve`에 같은 초안 ID와 사용자 선택 참조를 전달합니다.
아이디어에 대한 동의를 보지 못한 코드나 사업 정보 공개의 동의로 확대하지 않습니다.

## 초안과 게시

| 목적 | 도구 | 확인할 결과 |
| --- | --- | --- |
| 설정·초안 목록 | `reporting_status`, `reporting_list` | 실제 저장된 동의와 초안 상태 |
| 준비 | `reporting_prepare` | 고정된 제목·본문·초안 ID |
| 읽기 | `reporting_read` | 게시 전에 검토할 정확한 본문 |
| 게시 | `reporting_submit` | 원격 URL과 제목·본문 readback |
| 불확실한 결과 대조 | `reporting_reconcile` | 기존 이슈와 정확한 초안 일치; 새 이슈를 생성하지 않음 |

`reporting_prepare`는 파일 경로 대신 `report` 객체, `privacy_reviewed` 불리언, `key`를 받습니다.
객체의 필드는 kind, scope, component, summary, expected, observed, reproduction, proposal입니다.
kind는 defect/improvement/contribution, scope는 common/project-specific이며 프로젝트별 범위는 contribution에만 허용됩니다.
component는 배포 manifest에 있는 패키지 상대 경로입니다.

공통 보고는 generic fixture에서 공통 패키지 동작으로 재현한 뒤 의미를 검토합니다.
수정된 배포 컴포넌트나 프로젝트별 자산을 공통 결함으로 위장하지 않습니다.
프로젝트명·경로·원격 주소·개인 식별자·사업 정보·소스·diff·로그·대화·비밀·첨부를 복사하지 않습니다.
`privacy_reviewed=true`는 에이전트가 실제 검토했다는 보고이며 자동 개인정보 제거 기능이 아닙니다.
기계적 길이·필드·패턴 검사만으로 자연어 정보의 공개 적합성을 증명할 수 없습니다.

## 저장과 실패

제목과 전체 렌더링 본문을 해시하여 불변 초안 ID를 만듭니다. 게시 대상은 고정된 Neurath GitHub 저장소입니다.
초안과 동의는 프로젝트 비공개 Git 영역에 저장되며 일반 파일 배포·다른 clone으로 복사하지 않습니다.
업데이트·제거·복구도 기존 동의를 이전 상태로 되돌리지 않습니다.

게시 직전에 불확실 상태를 먼저 보존하고 잠금으로 중복 전송을 막습니다. 실제 요청은 내부 서비스가
고정된 인자 배열과 비공개 본문 파일을 사용합니다. 이는 에이전트에게 CLI 문법을 노출하는 경로가 아닙니다.
중단·인증 실패·timeout·readback 실패 뒤에는 자동 재게시하지 않습니다.
`reporting_read`와 `reporting_reconcile`로 실제 원격 결과부터 확인합니다.

보고 실패는 원래 작업의 종료나 검증 결과를 바꾸지 않습니다. 훅은 안내만 하며 네트워크 게시·새 세션·
동료 작업을 자동 생성하지 않습니다. [검증 범위](validation.md)를 구분해 결과를 기록합니다.
