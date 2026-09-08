# 설치 실행 참조

**대상 독자: 코딩 에이전트와 기여자.** 아래 명령은 승인된 작업을 수행하는 에이전트의 실행 참조입니다. 사용자는 [사용 안내](../usage/index.md)에 따라 목표를 요청하며, 이 명령을 직접 실행할 필요가 없습니다.
<!-- date: 2026-09-09; synced_from: baseline f69cb6402683bb2e0bfe56ed04c63f808b263f06 plus current working-tree stdio MCP changes; scope: source, not live-host certification -->

[사용 안내](../usage/index.md) · [기여자 안내](index.md)


대상 프로젝트에 Neurath를 설치하고 관리하는 안내입니다. 첫 작업은 [사용 안내](../usage/index.md)에서 시작하세요. 패키지 빌드, 에이전트 통합 절차와 단계별 검증은 [설치 개발 참조](installation.md)에 정리했습니다.

[English](../../en/contributing/setup-reference.md) · **한국어**

이 문서는 설치를 수행하는 에이전트와 기여자를 위한 실행 참조입니다. 지원 실행환경은
macOS/Linux, Git, Python `>=3.14,<3.15`입니다. 대상 프로젝트 언어는 제한하지 않습니다.
빠른 설치는 필요한 Python을 자동으로 준비하므로 직접 설치할 필요가 없습니다.

## 빠른 설치

내려받은 Neurath 소스 폴더에서 **실제로 하네스를 사용할 프로젝트** 경로를 지정합니다.

```sh
./setup /absolute/path/to/your-project
```

소스 빌드와 wheel 경로 지정은 설치기가 처리합니다. uv가 없으면
[공식 설치기](https://docs.astral.sh/uv/reference/installer/)로 준비하고,
Python 3.14와 Neurath를 영구적인 사용자 도구 환경에 설치합니다.
배포 내용마다 별도 환경을 만들고, 같은 내용을 다시 설치하면 기존 환경을 검증해 재사용합니다.
프로젝트 설치가 성공한 뒤에만 전역 `neurath` 명령을 새 환경에 연결합니다.
대상 프로젝트의 `.venv`, 의존성, 셸 설정 파일을 수정하지 않습니다.
Git이 없는 경우에는 먼저 설치해야 합니다. 새 폴더는 `git init /path/to/project`로 준비하세요.
Neurath 개발 저장소 자체에 설치할 때는 `./setup --self`를 사용합니다.
이 경로도 개발 `.venv` 대신 독립 도구 환경에 설치합니다.

한 번 설치한 뒤에는 다른 프로젝트에서 다음 명령만 실행하면 됩니다.

```sh
neurath setup
# 또는 어느 폴더에서든 대상 지정
neurath setup /absolute/path/to/another-project
```

`neurath`가 PATH에 없다면 설치 출력의 실행 파일 전체 경로를 사용하세요.
이미 설치된 프로젝트에서는 `installation_plan` → `installation_apply`도 사용할 수 있습니다.

처음 설치할 때는 `generic` 프로필과 양쪽 호스트를 사용합니다.
재실행하면 기존 호스트·프로필 선택과 사용자 문서·검증 바인딩을 유지합니다.
선택을 변경할 때만 해당 옵션을 지정하세요.

```sh
./setup /path/to/project --host codex
./setup /path/to/project --host claude-code
neurath setup --dry-run
neurath setup --json
```

`--dry-run`은 대상 파일을 쓰거나 원문을 출력하지 않고 경로별 변경 목록만 보여줍니다.
소스의 `./setup --dry-run` 경로는 도구 환경을 준비하므로, 도구 설치도 원하지 않으면
이미 설치된 `neurath setup --dry-run`을 사용하세요.
자동 uv 다운로드를 끄려면 `NEURATH_NO_BOOTSTRAP=1 ./setup /path/to/project`로 실행합니다.

설치 결과에는 배포본 무결성, 파일 배치, 훅 프로토콜 진단과 다음 단계가 표시됩니다.
실제 호스트 활성화는 별도입니다. 대상 프로젝트의 새 에이전트 세션에서 훅을 확인하고,
아래 문서·검증 바인딩을 연결하세요. 설치기는 프로젝트 trust와 훅 trust를 자동 승인하지 않습니다.

## 스킬 이름 충돌

기존 프로젝트에 같은 이름의 스킬이 있으면 새 설치에 접두어를 지정할 수 있습니다.

```sh
./setup /path/to/project --skill-prefix neurath-
```

이 경우 Neurath 스킬은 `/neurath-debug`, `/neurath-review-code`처럼 호출합니다.
기존 프로젝트 스킬의 이름·내용·권한을 보존하며 내부 workflow 계약 식별자는 그대로입니다.
접두어는 소문자로 시작하고 소문자·숫자·하이픈만 사용하며 하이픈으로 끝나야 합니다.
`setup`, `plan`, `install`, `update`, `wizard`에서 지정할 수 있습니다.
생략하면 기존 설치 기록을 유지하며, 다른 접두어로 바꾸려면 먼저 제거해야 합니다.
접두어를 붙인 경로도 기존 파일과 충돌하면 덮어쓰지 않습니다.

접두어는 스킬 이름의 충돌만 해결합니다. 기존 하네스가 같은 호스트 이벤트로 자체 세션
상태를 관리하거나 모든 스킬 디렉터리를 자체 계약과 대조한다면, 대상 프로젝트에서
런타임 역할과 검사 대상을 먼저 정리해야 합니다. 설치기는 기존 훅을 자동 삭제하지 않습니다.

사용자의 요청 예시는 [설치 안내](../usage/installation.md)에 있습니다.

## 위자드 인터페이스 참조

```sh
neurath --root /absolute/path/to/project wizard --output /private/path/neurath-plan.json
```

프로필과 호스트를 고르고 같은 `make_plan`/`apply_plan` 엔진을 사용합니다.
계획만 저장하고 종료할 수도 있습니다. `--output`을 생략하면 Git 관리 디렉터리의
`neurath-plans`에 저장하므로 커밋 대상이 되지 않습니다. 계획에는 복구용 원본 설정이
포함되며 파일 권한은 `0600`입니다. 직접 경로를 지정할 때도 비공개 위치의 새 파일을
사용하세요. 기존 파일이나 심볼릭 링크는 덮어쓰지 않습니다.

## 대상 저장소 바인딩

`.neurath/project.json`은 편집 후 사용자 소유 파일로 남습니다. 업데이트·제거가 이 파일의
사용자 변경을 덮어쓰거나 삭제하지 않습니다.

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

예제 명령은 프로젝트에 맞게 바꿉니다. `argv`는 shell 문자열이 아닙니다. 명령 실행은
그 프로젝트에서 이미 승인한 검증 범위여야 합니다. `stdout_contains`로 추가 성공 조건을
지정할 수 있으며, 종료 코드가 성공이어도 실행 중 저장소 파일이 바뀌면 receipt는 실패합니다.

```text
명명 MCP 도구 verification_run (현재 입력 스키마 사용) {"check": "check"}
```

## 업데이트와 복구

공개 릴리스는 `releases_prepare` → 정확한 사용자 선택 → `releases_apply`로 업데이트합니다.
설치된 배포의 관리 파일은 `installation_plan`에서 update/uninstall/restore 계획을 준비하고,
반환된 plan_ref로 `installation_apply`를 호출합니다. restore는 기존 installation_id를 사용하며,
중단된 저널은 `installation_recover`로 복구합니다.
개발 소스를 새 배포로 교체하는 부트스트랩은 소스의 `./setup /대상/Git-root`로 수행하고,
설치 후 에이전트 운용에는 명명 MCP 도구를 사용합니다.

`AGENTS.md`, 일반 파일 `CLAUDE.md`, `.gitignore`의 관리 블록 밖 사용자 편집은 내용과 위치를
보존합니다. 관리 블록이나 파일이 수정됐으면 충돌을 보고하고 비공개 설치 기록으로 원문과 현재
내용을 대조합니다. 강제 삭제나 덮어쓰기로 해결하지 않습니다. 이전 런타임은 복구를 위해 보존합니다.

## 스킬 이름과 갱신

스킬은 `/debug`, `/qa`, `/review-code`처럼 접두어 없이 호출합니다. [전체 스킬 목록](../usage/skills.md)에서
이름과 용도를 확인할 수 있습니다. 기존 설치를 갱신하면
Neurath가 관리하던 이전 경로는 새 경로로 옮기고 폐지된 스킬은 제거합니다. 같은 이름의
사용자 스킬이나 직접 수정한 관리 파일이 있으면 설치를 중단하여 내용을 보존합니다.
충돌한 사용자 스킬을 덮어쓰지 말고 이름이나 설치 대상을 먼저 정리한 뒤 다시 실행하세요.
