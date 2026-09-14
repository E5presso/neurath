<!-- date: 2026-09-13; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# 초기 설치와 설정 실행 참조

[English](../../en/contributing/setup-reference.md)

초기 설치는 Neurath 전용 실행 환경을 준비한 뒤 트랜잭션 설치기를 호출한다. 이미 활성화된 설치에서는 일반 관리 작업에 명명된 MCP 도구를 사용한다. 이 문서는 연동이 아직 없을 때의 소스 실행기·CLI, 설치 검증 환경, 명시적 진단·복구 경로를 설명한다.

## 실행 환경과 준비 조건

Neurath 체크아웃에서 대상을 명시하여 실행한다.

```sh
./setup /absolute/path/to/your-project
```

macOS·Linux에서 Git이 필요하며 `uv`가 없으면 공식 설치기로 확보할 수 있다. Python 3.14를 준비하고 배포본을 빌드한 뒤 내용 기반으로 구분되는 영속 도구 환경에 설치한다. 전역 `neurath` 진입점은 대상 설치가 성공한 뒤에만 바뀐다. 같은 배포 내용을 다시 사용하면 기존 도구 환경을 검증하여 재사용한다.

프로젝트 `.venv`, 의존성 선언, 잠금 파일, 셸 시작 파일을 보존한다. Neurath 개발 `.venv`, 설치된 도구 환경, 대상 애플리케이션 환경은 각각 분리된다. 한 프로젝트를 업데이트해도 다른 프로젝트의 설치 실행기가 모두 바뀌지 않는다. 기록된 이전 상태로 되돌릴 수 있도록 이전 도구 환경을 유지한다.

```sh
NEURATH_NO_BOOTSTRAP=1 ./setup /absolute/path/to/your-project
```

이 설정은 대체 `uv` 다운로드를 끈다. 누락된 준비 도구를 대신 제공하지 않는다. Git이 없거나 대상이 Git worktree 루트가 아니라면 해당 조건을 해결한 뒤 실행한다. 새로 요청된 대상은 설치의 일부로 `git init`을 수행할 수 있다.

## 지원하는 설치 형태

| 실행 | 효과 |
| --- | --- |
| `./setup /absolute/path/to/your-project` | 도구 환경 준비와 대상 설치 |
| `./setup --self` | 빌드된 도구 환경으로 현재 소스 체크아웃 설치 |
| `neurath setup` | 사용 가능한 배포본으로 현재 프로젝트 설치·정합성 조정 |
| `neurath setup /absolute/path/to/another-project` | 지정 대상 설치 |
| `neurath setup --dry-run` | 대상 파일을 쓰지 않고 경로·작업 목록 반환 |
| `neurath setup --json` | 구조화된 설치 결과 반환 |
| `./setup /path/to/project --host codex` | Codex 연동 선택 |
| `./setup /path/to/project --host claude-code` | Claude Code 연동 선택 |
| `./setup /path/to/project --skill-prefix neurath-` | 공개 스킬 이름에 접두어 적용 |

최초 기본값은 `generic`과 두 호스트다. `--host`는 반복할 수 있다. 재설치에서 생략한 프로필·호스트·접두어는 기존 값을 유지한다. 프로필은 `generic`만 지원한다. 접두어는 빈 값이거나 `[a-z][a-z0-9-]*-` 형식이어야 한다. `neurath-`라면 `debug`가 `neurath-debug`로 배치된다. setup, plan, install, update, wizard에서 접두어를 선택할 수 있다. 설치된 접두어를 바꾸려면 먼저 제거한다. 기본 이름과 접두어 이름 모두 기존 사용자 소유 스킬과 겹치면 충돌이다.

소스 `./setup --dry-run`은 대상 미리보기를 계산하기 전에 별도 도구 환경을 준비할 수 있다. 설치된 `neurath setup --dry-run`은 대상 파일을 쓰지 않는다. 미리보기에는 경로와 작업이 나오며 기존 파일의 본문은 드러내지 않는다.

`--auto-report yes|no`는 사용자가 명시한 보고 선택을 기록한다. 생략하면 기존 선택을 유지한다. 설치 요청만으로 보고 동의가 성립하지 않으며 적용 범위는 [보고 안내](../usage/reporting.md)에 설명되어 있다.

## 구조화된 결과 해석

미리보기에는 `status: planned`, `root`, `profile`, `hosts`, `skill_prefix`, 보고 상태, `path`·`action`을 담은 `changes`가 있다. 적용 후에는 설치 ID·변경 수를 담은 `receipt`, `doctor`, 다음 단계가 추가된다. 최종 `status`는 로컬 진단에 따라 `passed` 또는 `failed`다. 파일 적용 후 진단이 실패할 수 있으므로 조사할 때 설치 ID를 보존한다.

진단은 배포본, 배치, 프로토콜, 실제 활성화를 구분한다. 독립 훅 subprocess가 시작 JSON을 받고 잘못된 입력을 거부한 것은 프로토콜 호환성 확인이다. 실제 호스트 활성화는 호스트에서 관측하기 전까지 미확인이다. 사용자에게 프로젝트 신뢰, provider 인증, 세션 새로고침이 필요할 수 있다. 이는 특정 호스트 조작이며 프로젝트 설정 전체를 사용자에게 넘기는 단계가 아니다.

## 적용하지 않고 계획 저장

대화형 wizard도 동일한 `make_plan`·`apply_plan` 엔진을 사용하며 계획만 저장할 수 있다.

```sh
neurath --root /absolute/path/to/project wizard --output /private/path/neurath-plan.json
```

초기 설치 CLI에서 명시적 계획을 만들고 적용하는 형태도 지원한다.

```sh
neurath --root /absolute/path/to/project plan --action update --output /private/path/neurath-plan.json
neurath --root /absolute/path/to/project apply /private/path/neurath-plan.json
```

출력 경로는 새 파일이어야 하며 심볼릭 링크이면 안 된다. wizard의 기본 저장 위치는 Git 관리 영역 `neurath-plans`이며 파일 모드는 `0600`이다. 계획에는 이전 파일 정보가 있으므로 비공개로 보관한다. 적용 시 대상과 배포본을 다시 확인한다. 충돌을 피하려고 계획 본문을 수정하지 않는다.

되돌리기 계획에는 `--action restore --installation-id INSTALLATION_ID`를 사용한다. `--receipt`는 동일한 ID를 받는 호환용 별칭이다. ID는 반전할 완료 작업을 가리킨다. 중단 작업 복구와의 차이는 [트랜잭션 설계](installation-design.md)를 참고한다.

## 실제 프로젝트 절차 연결

에이전트는 프로젝트의 실제 지침을 근거로 `.neurath/project.json`을 관리한다. 다음 예시는 문서 역할과 검사 명령을 연결하는 구조다. 확인한 경로와 명령으로만 대체한다.

```json
{
  "schema": 1,
  "documents": {
    "intent": "docs/product.md",
    "glossary": "docs/glossary.md",
    "decisions": "docs/decisions/"
  },
  "verification": {
    "check": {
      "argv": ["npm", "test", "--", "--run"],
      "cwd": ".",
      "success_codes": [0],
      "timeout_seconds": 300
    }
  },
  "protected_capabilities": {
    "connectors": [],
    "paths": ["docs/product.md"]
  }
}
```

`argv`는 인자 배열이며 셸 문자열이 아니다. 출력 조건이 필요하면 `stdout_contains`를 추가할 수 있다. 정확한 pytest 선택을 실행할 때는 `verification.pytest.argv`에 `uv run --locked pytest`처럼 실제 환경을 연결하고, `tests/test_example.py::test_example` 같은 요청된 선택자를 유지한다. 없는 검사는 미확인으로 남긴다. 비어 있는 문서 역할에 무관한 파일을 채우지 않는다.

내부 등록 검증 경로는 저장소의 실행 전후 지문을 비교하므로 종료 코드가 허용되어도 파일 변경이 있으면 거부한다. 일반 네이티브 명령 실행이 이 호환용 검증 기록을 자동으로 만드는 것은 아니다. `worktree_cleanup` 연결에는 독립적으로 확인한 `base_branch`와 `remote_ref`가 필요하며 이름 관례로 추정하면 안 된다.

독립 배포 자산을 살펴보려면 `neurath corpus /path/to/new-directory`로 새 디렉터리에 복사한다. 다른 프로젝트 파일을 가져오지 않고 패키지에 포함된 자산을 읽는다.

구현 근거: [초기 실행기](../../../setup), [CLI 구문](../../../src/neurath/cli.py), [설치 서비스](../../../src/neurath/install/setup.py), [트랜잭션 엔진](../../../src/neurath/install/transaction.py), [초기 설치 검증](../../../tools/validate_setup.py).
