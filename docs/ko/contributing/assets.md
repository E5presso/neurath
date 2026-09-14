<!-- date: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Neurath가 설치하는 자산 변경하기

[English](../../en/contributing/assets.md) · [기여자 시작 안내](index.md)

자산 변경은 빌드한 Neurath 배포본을 통해 대상 프로젝트에 전달되어야 합니다. `src/neurath/_assets`의 독립 원본을 수정하고 파생 메타데이터를 다시 만든 뒤, 변경에 맞는 패키지·설치 동작을 확인합니다. 설치된 `.agents/skills`나 `.neurath/rules`를 편집하면 해당 설치만 바뀌고 업데이트 충돌이 생길 수 있습니다.

## 역할에 맞는 원본 찾기

| 역할 | 원본 | 설치 또는 실행 위치 |
| --- | --- | --- |
| 에이전트 절차 | `_assets/.agents/skills` | 공개 스킬 이름으로 `.agents/skills`에 투영합니다. |
| 공통 운영 규칙 | `_assets/.agents/rules` | `.neurath/rules`의 이식 가능한 규칙입니다. |
| 워크플로 계약·라우팅 데이터 | `_assets/.agents/skills/contracts.json`과 관련 JSON | `.neurath/reference`의 참조와 안정적인 내부 계약 ID입니다. |
| 런타임 구현 | `_assets/scripts` | 격리된 설치 런타임에서 import합니다. |
| 정책·호스트 연결·경로 변환 | `install/projection.py` | 정책, 훅, 참조, 실행기, 작업 매핑을 생성합니다. |
| 공개 이름 | `skill_names.py` | 내부 원본 이름을 공개 호출명으로 연결합니다. |

표의 모든 원본 경로는 `src/neurath` 아래에 있습니다. 다른 저장소는 빌드 입력이 아닙니다. 대상 프로젝트의 제품 문서와 검증 명령은 `.neurath/project.json`으로 연결합니다.

현재 공개 스킬은 31개입니다. 29개는 단계 계약이 있고 `explain-code`, `graphify`는 그런 계약 없이 작업을 돕는 스킬입니다. 공개 이름은 독자가 요청할 작업을 나타내고 내부 ID는 저장된 워크플로를 안정적으로 유지합니다. 예를 들어 원본 계약 `investigate`는 `debug`로, `monitor-pr`은 `watch-pr`로 호출합니다. `neurath-` 접두어를 설정하면 `/neurath-debug`가 되지만 내부 계약 이름은 바뀌지 않습니다. 전체 매핑은 [스킬 참조](skills-reference.md)에 있습니다.

## 원본 변경이 설치본에 반영되는 과정

투영 과정은 설치할 프로젝트에 맞춰 번들 경로, 공개 스킬명, 엔진 참조를 바꿉니다. 프로젝트별 문서 참조는 `documents` 연결을 사용하도록 만들고 스킬 본문 앞에 설치 정책의 적용 범위를 추가합니다. Markdown의 명령 참조는 현재 사용할 수 있는 명명 도구로 바꾸며 `.neurath/reference/task-operation-map.json`에 매핑을 남깁니다.

따라서 원본 명령이 실행된다는 확인만으로는 절차 변경을 검증하기에 부족합니다. 생성된 스킬이 설치 환경에 없는 작업을 안내할 수도 있습니다. 원본 절차, 투영 문구, 현재 도구 스키마, 관련 계약을 함께 확인합니다. 현재 소스는 128개 명명 도구를 노출하고 138개 내부 작업을 유지합니다. 호환 작업이 모두 공개 도구가 되는 것은 아닙니다. 일반 편집과 테스트는 중복된 material·verification 기록 없이 네이티브 도구를 사용합니다. 공개 경계는 [태스크 도구](task-tools.md)를 참고하세요.

저장 필터를 조사하는 예시라면 스킬은 사용자의 앱이 새로고침 후 상태를 잃는 이유를 추적하고 그 결과를 계속 확인하도록 도와야 합니다. 제품 동작과 저장소 명령은 대상 프로젝트에서 읽고, 공통 자산은 조사 절차를 제공합니다.

## 의미 있는 워크플로 근거 남기기

단계 계약은 요청한 절차가 다음 단계로 넘어가기 위해 필요한 내용을 기록합니다. 절차를 읽거나 “통과”라고 쓰는 것만으로 단계가 완료되지는 않습니다. 현재 공개 작업은 `phase_start`, `phase_current`, `phase_evidence_prepare`, `phase_complete`, `phase_finalize`이며 옛 `workflow_*` 호출은 호환 경로입니다.

`phase_evidence_prepare`는 현재 단계와 리비전에 연결한 불변 근거를 보존하고, 소스 관찰과 소유자의 보고를 구분합니다. 적응형 평가는 검증된 독립 역할, 정확한 후보, 인증된 보고의 소비까지 필요합니다. 소스·의도·소유자·워크플로 리비전이 바뀌면 오래된 후보 근거를 재사용할 수 없습니다. 일부 운영 절차의 마지막 단계는 `terminal_state`로 원자적으로 최종화하므로 같은 단계를 다시 최종화하지 않습니다.

네이티브 테스트 결과는 사용자 태스크를 직접 뒷받침할 수 있습니다. 명시적인 단계·리뷰 상태는 선택한 절차가 요구할 때 만듭니다. 자세한 전이는 [런타임 수명주기](runtime-lifecycle.md)와 [스킬 참조](skills-reference.md)에, 독립 평가는 [협업 계약](collaboration-contract.md)에 설명되어 있습니다.

## 파생 메타데이터와 패키지 다시 만들기

실행 자산을 변경했을 때 개발 순서는 다음과 같습니다.

```sh
uv sync --locked
uv run --locked python tools/build_manifest.py
uv run --locked python tools/check.py
uv build
./setup --self --json
```

마지막 명령은 권한이 있을 때 수행하는 별도 설치 작업입니다. 새 설치 동작은 구현 전에 실패하는 테스트로 정의합니다. 매니페스트 생성기는 카탈로그의 규칙·감사 인덱스도 다시 생성한 뒤 독립 패키지 파일을 해시합니다. 바이트코드와 캐시는 제외하고 심볼릭 링크에 의존하는 페이로드는 거부합니다. 변경된 자산을 숨기려고 다이제스트만 손으로 바꾸면 이 검사의 목적을 잃습니다.

`tools/check.py`는 첫 실패에서 멈추며 무결성, 정적 진단, 패키지 테스트, 런타임 회귀 검사가 모두 성공한 뒤에만 `NEURATH_CHECK_OK`를 출력합니다. 패키지 빌드는 소스 검사와 다른 부분을 확인합니다. 자기 설치는 개발 프로젝트에 배치된 파일을 바꾸며, 활성화 확인에는 그 후의 실제 호스트 이벤트가 필요합니다. [검증](validation.md)에 따라 필요한 관찰을 선택하고 각각 보고합니다.

## 배포 내용의 독립성 유지하기

Wheel은 독립 자산과 매니페스트를 포함한 `src/neurath`를 패키징합니다. 소스 배포본에는 두 언어의 문서와 개발 소스가 포함됩니다. 비공개 검증 결과, 환경 상태, Git 데이터, 설치 기록, 출처 이력은 공개 페이로드에 넣지 않습니다. 선언된 런타임 의존성은 Neurath 도구 환경에 설치하며 대상 프로젝트 의존성과 분리합니다.

새로운 wheel 설치 환경에서 import 독립성을 확인하고, 대상 프로젝트가 자체 `scripts` 패키지를 가진 경우도 다룹니다. 투영 변경은 공개 이름, 접두어, 호스트 선택, 사용자 설정 보존을 검사합니다. 문서만 바뀌었다면 공개 문서·구조 검사를 사용하며 변경되지 않은 실행 페이로드를 다시 만들 필요는 없습니다.

소스: [투영](../../../src/neurath/install/projection.py), [공개 이름](../../../src/neurath/skill_names.py), [매니페스트 생성기](../../../tools/build_manifest.py), [패키지 설정](../../../pyproject.toml). 테스트: [패키지 독립성](../../../tests/test_independence.py), [스킬 import 경계](../../../tests/test_skill_import_boundary.py), [접두어](../../../tests/test_skill_prefix.py), [도구 안내](../../../tests/test_mcp_guidance.py).
