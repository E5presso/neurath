# Neurath 설치

이 문서는 사람과 설치를 수행하는 에이전트가 함께 사용합니다. 지원 실행환경은
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
이미 설치된 프로젝트에서는 `.neurath/run setup`도 사용할 수 있습니다.

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

## 에이전트에게 붙여 넣기

소스 경로를 실제 위치로 바꾸어 대상 프로젝트의 Codex 또는 Claude Code에 전달합니다.

> `/path/to/neurath/ONBOARDING.md`를 읽고 이 프로젝트에 Neurath를 설치해줘.
> 기존 지침과 훅·권한·의존성을 보존하고, 기본 generic 프로필로 설치해줘.
> 설치 후 실제 문서 경로와 검증 명령을 `.neurath/project.json`에 연결해줘.
> 알 수 없는 항목만 내게 물어보고, 로컬 진단 결과와 내가 해야 할 훅 신뢰 절차를 알려줘.

## 에이전트 설치 절차

1. 사용자가 지정한 대상 저장소의 Git root와 기존 `AGENTS.md`, `CLAUDE.md`,
   `.agents/skills`, `.claude/settings.json`, `.codex/config.toml`, `.codex/hooks.json`을 확인합니다.
   설치 요청이 이미 승인되었다면 같은 승인을 반복해서 받지 않습니다.
2. 기본 프로필은 `generic`, 기본 호스트는 Codex와 Claude Code 둘 다입니다.
   제품별 프로필이나 프레임워크 정책은 포함하지 않습니다.
3. 별도 변경 검토가 필요하면 먼저 소스의 `setup /대상/Git-root --dry-run` 또는
   이미 설치된 `neurath setup /대상/Git-root --dry-run`으로 경로 목록을 확인합니다.
   원문 비교가 필요할 때만 아래 `plan`/`apply` 경로를 사용합니다. 계획 JSON에는
   기존 원문이 들어 있으므로 비공개 위치에 저장하고 버전 관리에 추가하지 않습니다.
4. 소스를 받았다면 해당 소스의 `setup /대상/Git-root`를 실행합니다. 도구가 이미 준비되어
   있다면 `neurath setup /대상/Git-root`로 설치·진단을 진행합니다. 대상 프로젝트 `.venv`를
   사용하거나 그 프로젝트에서 `uv sync`를 실행하지 않습니다.
5. `setup`은 같은 `make_plan`/`apply_plan` 엔진으로 적용합니다. 충돌이면 해당 파일을 보존하고
   원인을 설명합니다. 파일 덮어쓰기, `--force`, 권한 우회로 해결하지 않습니다.
6. `.neurath/project.json`에 대상 저장소의 문서 슬롯과 실제 검증 명령을 바인딩합니다.
   문서가 없으면 invent하지 않습니다. 필요한 정보만 사용자에게 요청합니다.
7. `setup`이 실행한 진단을 확인합니다. 별도 `apply` 경로라면 `doctor --protocol`을 실행합니다.
   이는 호스트 trust 또는 live actor/evaluator 증명이 아닙니다.
8. Codex에서는 사용자가 프로젝트를 신뢰하고 `/hooks`에서 정확한 훅을 검토해야 합니다.
   Claude Code에서는 프로젝트 설정 및 `/hooks`의 로딩 상태를 확인합니다.
   설치기가 trust 설정을 수정하거나 trust를 건너뛰어서는 안 됩니다.

## wheel 배포본과 개별 단계 사용

직접 wheel을 만들거나 변경 내용을 별도로 검토할 때 사용하는 고급 경로입니다.
빠른 설치를 사용했다면 다시 수행할 필요가 없습니다.

```sh
# Neurath 소스 저장소에서만 빌드
uv sync --locked
.venv/bin/python tools/build_manifest.py
.venv/bin/python -m build

# 배포본마다 새로운 절대 경로를 지정하고 기존 환경은 재설치하거나 이동하지 않음
uv venv --python 3.14 /absolute/path/to/new-neurath-runtime
uv pip install --python /absolute/path/to/new-neurath-runtime/bin/python /absolute/path/to/neurath/dist/neurath-0.1.0-py3-none-any.whl

# 새 프로젝트라면 사용자가 지정한 폴더에서 먼저 git init을 실행
/absolute/path/to/new-neurath-runtime/bin/neurath --root /absolute/path/to/project plan --output /private/path/neurath-plan.json
/absolute/path/to/new-neurath-runtime/bin/neurath --root /absolute/path/to/project apply /private/path/neurath-plan.json
/absolute/path/to/project/.neurath/run doctor --protocol
```

CLI에서 `--root`는 하위 명령 앞에 둡니다. launcher는 독립 도구 환경의 Python 경로를 사용하고,
훅은 현재 Git worktree의 launcher를 찾습니다. 도구 환경을 옮긴 경우 update 계획을 검토합니다.
`neurath install`은 계획 생성과 적용을 한 번에 실행하는 명시적인 설치 명령입니다.

## 사람이 선택하는 위자드

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

```sh
.neurath/run verify check
.neurath/run engine scripts.agent_harness.state_cli --help
.neurath/run engine scripts.skill_harness.phase_runner --help
.neurath/run skill watch-pr monitor_runtime_readback.py --help
```

## 업데이트와 복구

새 소스를 받았다면 `./setup /path/to/project`를 다시 실행합니다.
새 배포 내용에 맞는 별도 도구 환경을 준비하고 해당 프로젝트를 적용·진단합니다.
다른 프로젝트의 launcher와 실행 환경은 그대로 유지합니다. 다른 프로젝트도 갱신하려면
`neurath setup /path/to/other-project`를 명시적으로 실행하세요.
`restore`가 이전 실행 환경까지 되돌릴 수 있도록 기존 환경을 보관합니다.
준비가 강제로 중단되어 불완전한 환경이 남으면 설치기가 그 경로를 알려주고 멈춥니다.
사용 중인 환경을 자동 삭제하거나 재설치하지 않습니다.

```sh
# 새 배포 환경의 neurath 명령으로 갱신 계획 생성
neurath --root /project plan --action update --output /private/update-plan.json
neurath --root /project apply /private/update-plan.json

# 관리한 파일만 원래 내용으로 복구
neurath --root /project plan --action uninstall --output /private/remove-plan.json
neurath --root /project apply /private/remove-plan.json

# 직전 적용 결과의 id로 그 트랜잭션을 되돌림
neurath --root /project restore <installation-id>

# 프로세스 중단으로 남은 저널 복구
neurath --root /project recover
```

`AGENTS.md`, 일반 파일인 `CLAUDE.md`, `.gitignore`는 Neurath 관리 블록 밖의 사용자
편집을 위치와 원문 그대로 보존합니다. 관리 블록 자체나 다른 관리 파일을 수정했다면
update/uninstall은 충돌로 멈춥니다.
Git 디렉터리의 `neurath-receipts/<id>.json`에서 before/after를 확인하고 변경을 먼저 조정합니다.
원문을 손실시키는 강제 제거 기능은 제공하지 않습니다. 빈 디렉터리와 변경 이력은 남을 수 있습니다.

## 검증과 저장소 관례

`generic`이 유일한 프로필입니다. 검증 명령은 도구가 발견됐다는 이유로 자동 선택하지 않습니다.
Python의 exact-node 검증이 필요한 경우 `verification.pytest.argv`에
`["python", "-m", "pytest"]`처럼 프로젝트 테스트 환경의 실행 파일을 지정하세요.
선택자(`-k`, `-m`), 다른 테스트 경로와 설정 재정의는 이 바인딩에 넣지 않습니다.
일반 검증은 `verify <name>`, 단계별 typed 검증은 아래 명령을 사용합니다.

```sh
.neurath/run engine scripts.agent_harness.verification_runner pytest --node tests/test_example.py::test_example
```

GitHub metadata는 기본적으로 특정 언어·prefix를 요구하지 않습니다. 필요한 프로젝트만
`metadata.language`를 `"ko"`로 설정하거나 `metadata.require_title_issue_prefix`,
`metadata.require_commit_subject_issue_prefix`를 `true`로 설정합니다.
브랜치와 worktree 경로는 해당 프로젝트의 지침을 따르며 cleanup에는 확인한
`--base-branch`와 `--remote-ref`를 명시합니다.

키트 자체의 고정 회귀 matrix는 Neurath 개발 소스의 `tools/run_core_regressions.py`에서
실행합니다. 대상 프로젝트의 검증 결과를 키트 자체 수정의 회귀 증거로 대신 사용하지 않습니다.

## 스킬 이름과 갱신

스킬은 `/debug`, `/qa`, `/review-code`처럼 접두어 없이 호출합니다. [전체 스킬 목록](docs/skills.md)에서
이름과 용도를 확인할 수 있습니다. 기존 설치를 갱신하면
Neurath가 관리하던 이전 경로는 새 경로로 옮기고 폐지된 스킬은 제거합니다. 같은 이름의
사용자 스킬이나 직접 수정한 관리 파일이 있으면 설치를 중단하여 내용을 보존합니다.
충돌한 사용자 스킬을 덮어쓰지 말고 이름이나 설치 대상을 먼저 정리한 뒤 다시 실행하세요.
