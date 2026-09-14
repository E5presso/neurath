<!-- date: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# 설치와 진단 실행 참조

[English](../../en/contributing/setup-reference.md) · [첫 설치](installation.md)

대상 Git 루트와 해당 프로젝트 지침을 확인한 뒤 이 문서를 사용합니다. 초기 설치 명령은 네이티브 연동이 아직 없을 때 런타임을 준비합니다. 설치된 세션에서는 그 세션에 노출된 명명 도구와 현재 `.neurath/policy.md`를 따릅니다. 아래 명령 예시는 실행 참조이며 호스트 제한을 우회할 권한은 아닙니다.

## 소스에서 초기 설치하기

```sh
./setup TARGET [--host codex|claude-code] [--profile generic] [--skill-prefix PREFIX] [--dry-run] [--json]
./setup --self [--host codex|claude-code] [--json]
```

`TARGET`은 기존 Git 작업 트리 루트여야 합니다. 새 프로젝트라면 Git 초기화를 별도 프로젝트 작업으로 먼저 수행합니다. 소스 체크아웃 자체에 설치할 때는 `--self`가 필요합니다. 호스트 플래그를 반복할 수 있으며, 새 설치에서 생략하면 두 호스트를 모두 선택합니다. 현재 프로필은 `generic` 하나입니다.

`--skill-prefix`는 빈 접두어나 `[a-z][a-z0-9-]*-`에 맞는 소문자 이름을 받습니다. 생략하면 설치된 접두어를 유지합니다. `--dry-run`은 대상 쓰기를 미리 보는 옵션이며 외부 소스 설치 스크립트는 영구 런타임을 준비할 수 있습니다. `--json`은 구조화된 결과를 반환합니다. 설정은 `--auto-report yes|no`도 받으며, 사용자가 실제로 결정한 보고 동의를 기록할 때 사용합니다. 생략하면 기존 결정을 유지하고 dry run에서는 동의를 저장하지 않습니다.

런타임은 Python `>=3.14,<3.15`가 필요하며 macOS/Linux 초기 설치는 Python 3.14를 준비합니다. Git은 이미 있어야 합니다. `NEURATH_NO_BOOTSTRAP=1`은 `uv` 자동 다운로드를 막습니다. 런타임은 대상의 `.venv`, 잠금 파일, 의존성 명세와 분리됩니다.

## 설치된 작업 트리 관리하기

`installation_plan`으로 정확한 변경을 준비합니다.

```json
{"action": "update", "hosts": ["codex"], "key": "installation-update-preview-1"}
```

선택 필드는 `profile`, `hosts`, `installation_id`, `skill_prefix`입니다. `action`의 기본값은 `install`이며 `update`, `uninstall`, `restore`도 받습니다. 빈 선택은 서비스 기본값이나 설치 기록을 사용합니다. 복원에는 실제 존재하는 설치 ID가 필요합니다. 결과는 `plan_ref`, `plan_id`, `action`, 경로별 쓰기·제거를 담은 `changes` 배열입니다.

반환된 참조를 `installation_apply`에 전달합니다.

```json
{"plan_ref": "RETURNED_PLAN_REF", "key": "installation-update-apply-1"}
```

대문자 값은 실제 참조로 바꿔야 하는 자리 표시자입니다. 같은 논리 작업을 재시도할 때는 동일한 입력과 안정적인 키를 유지합니다. 새 요청에는 새 키를 쓰며, 같은 키로 내용을 바꾸면 실패합니다. 네이티브 바인딩은 호스트 연동이 제공하는 값이므로 만들어 넣거나 다른 세션에서 복사하지 않습니다.

`installation_recover`는 `{"key":"installation-recover-1"}`을 받습니다. 일반 파일 배치 상태가 손상되어도 보수적인 저널 복구 서비스에 접근합니다. `installation-recovery-required` 오류가 이 경로를 안내합니다. 복구 후 `diagnostics_project`를 확인하고 새 계획을 준비합니다. `plan-unavailable`은 현재 주체·작업 트리에서 준비한 참조가 아니며, `plan-changed`는 비공개 계획이 보존된 ID와 일치하지 않음을 뜻합니다.

## 초기 설정과 관리를 위한 네이티브 터미널 명령

네 가지 설치 동작은 같은 계획 엔진을 사용합니다.

```sh
neurath --root TARGET plan --action install --output PRIVATE_NEW_PLAN.json
neurath --root TARGET apply PRIVATE_NEW_PLAN.json
neurath --root TARGET install --host codex
neurath --root TARGET update --host codex
neurath --root TARGET uninstall
neurath --root TARGET restore INSTALLATION_ID
neurath --root TARGET recover
```

`--root`는 하위 명령 앞에 둡니다. 실행 파일이 준비되어 있다면 `neurath setup TARGET --json`으로 설치와 진단을 함께 실행할 수 있습니다. `neurath wizard --output PRIVATE_NEW_PLAN.json`은 대화형으로 계획만 준비하며 적용하지 않습니다. 복원 계획에서는 `--installation-id INSTALLATION_ID`를 사용하고, `--receipt`는 호환 별칭으로 남아 있습니다. 출력은 새 비공개 경로여야 하며 기존 파일과 심볼릭 링크를 거부합니다.

설치 **receipt**는 무엇을 바꿨는지 보관하는 기록이며 복원에 사용합니다. 코딩 호스트가 변경을 불러왔다는 근거는 아닙니다. 설치된 환경의 관리에서는 비공개 계획 경로를 대화에 노출하는 대신 앞의 명명 도구 참조를 우선합니다.

## 진단 결과의 범위 읽기

| 명명 도구 | 입력 | 확인하는 내용 |
| --- | --- | --- |
| `diagnostics_integrity` | `{}` | 패키지 파일이 매니페스트와 일치하는지 확인합니다. |
| `diagnostics_project` | `{"protocol":true}` | 배포본, 관리 파일 배치, 로컬 훅 프로토콜을 관찰합니다. |
| `diagnostics_profile` | `{}` | 설치된 프로필의 검사 정보를 읽습니다. |
| `diagnostics_continuation` | `{}` | 현재 작업 지속 관련 진단을 읽습니다. |

터미널에서는 `neurath integrity`, `neurath doctor --protocol`, `neurath profile-check`, `neurath session-status` 등을 사용합니다. Doctor는 로컬 프로토콜이 통과해도 `host_activation.status: "unverified"`를 반환합니다. 실제 활성화는 호스트 이벤트로 확인해야 합니다.

명명 도구 응답에는 `ok`와 `operation`이 있습니다. 전송 성공과 `result`의 실제 결과는 구분합니다. 실패 시 `code`, `message`, `state`, `retryable`, `next_action`을 읽습니다. 예를 들어 진단 응답을 정상 수신했더라도 그 안의 파일 배치 결과는 실패일 수 있습니다.

## 프로젝트 검증 명령 설정하기

검증기는 프로젝트 작업을 확인하기 위해 저장소가 선택한 명령입니다. 아래 예시는 저장 필터 앱에 해당 테스트 스크립트가 이미 있다고 가정합니다.

```json
{
  "schema": 1,
  "documents": {"intent": "SPEC.md"},
  "verification": {
    "project-check": {
      "argv": ["npm", "test"],
      "cwd": ".",
      "success_codes": [0],
      "timeout_seconds": 300
    }
  }
}
```

`argv`는 null 바이트가 없는, 비어 있지 않은 문자열의 비어 있지 않은 배열입니다. 셸 표현식으로 실행하지 않습니다. `cwd`는 저장소 상대 경로이며 저장소 안에 존재하는 디렉터리로 해석되어야 합니다. `success_codes`는 0부터 123까지 정수의 비어 있지 않은 목록이고 기본값은 `[0]`입니다. 타입이 지정된 회귀 검사는 특히 `[0]`을 요구합니다. `timeout_seconds`는 기본 300이며 유한한 양수, 최대 3600입니다. 선택 필드 `stdout_contains`는 비어 있지 않은 문자열이며 표준 출력에 포함되어야 합니다.

검증 보존 기록에는 명령, 설정 다이제스트, 실행 전후 작업 트리 지문, 종료 상태, 제한 시간 정보가 들어갑니다. 프로세스가 성공했어도 작업 트리가 바뀌면 검증 receipt는 실패합니다. `unbound verifier`는 요청한 이름의 연결이 없다는 뜻입니다. 실제 명령을 연결한 다음 실행 여부를 보고해야 합니다. 일반 네이티브 테스트 결과와 함께 사용하는 방법은 [검증](validation.md)을 참고하세요.

## 소스 체크아웃 없이 번들 자원 살펴보기

```sh
neurath corpus NEW_DESTINATION
neurath --root TARGET engine scripts.agent_harness.state_cli --help
neurath --root TARGET skill watch-pr monitor_runtime_readback.py --help
```

`corpus`는 독립 번들 자원 트리를 복사하며 기존 대상 디렉터리를 거부합니다. Engine과 skill 명령은 설치된 격리 인터프리터를 사용합니다. 개발·초기 설정용 실행 참조이므로 현재 정책을 따라야 합니다. 설치된 스킬은 일반 작업을 명명 도구로 수행하도록 안내합니다.

소스: [CLI](../../../src/neurath/cli.py), [설치 입력 스키마](../../../src/neurath/runtime/installation_tasks.py), [검증 실행기](../../../src/neurath/runtime/verification.py), [타입 지정 명령](../../../src/neurath/runtime/commands.py). 테스트: [설정](../../../tests/test_setup.py), [설치 도구](../../../tests/test_installation_tasks.py), [검증](../../../tests/test_verification.py).
