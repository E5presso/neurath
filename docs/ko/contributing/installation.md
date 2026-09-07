# 설치 개발과 에이전트 통합

[English](../../en/contributing/installation.md) · **한국어**

<!-- date: 2026-09-07; synced_from: source and documentation at e1487a1718056b37b999d1343a1007b7e25f5c8c; English and Korean editions updated together -->

[사용 안내](../usage/index.md) · [기여자 안내](index.md)


설치기를 수정·검증하거나 에이전트 통합을 관리하고 검증 연결 계약을 시험할 때 읽는 참조 문서입니다. 일반적인 프로젝트 설치에는 [사용자 설치 안내](../usage/installation.md)를 사용하세요. 빌드 명령은 Neurath 소스 저장소에서, 설치 명령은 명시한 임시 대상이나 사용자가 지정한 프로젝트에서 실행합니다.

## 에이전트 실행 참조

코딩 에이전트에게 원하는 변경, 제약과 완료 조건을 전달해 기여할 수 있습니다.
이 문서의 개발 명령과 Neurath 작업은 에이전트가 수행합니다.
명령 예제는 에이전트와 검토자가 실행을 재현하기 위한 참조이며,
사용자에게 수동 설정을 요구하는 절차가 아닙니다. 호스트 인증과 신뢰 결정은 사용자가 담당합니다.

[설치](setup-reference.md) · [협업](agents-reference.md) ·
[기억](memory-reference.md) · [스킬 호환성](skills-reference.md)

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
   없는 문서를 만들어 넣지 않습니다. 필요한 정보만 사용자에게 요청합니다.
7. `setup`이 실행한 진단을 확인합니다. 별도 `apply` 경로라면 `doctor --protocol`을 실행합니다.
   이는 호스트 trust 또는 실제 실행 중인 에이전트·검토자 신원 증명이 아닙니다.
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


## 검증과 저장소 관례

`generic`이 유일한 프로필입니다. 검증 명령은 도구가 발견됐다는 이유로 자동 선택하지 않습니다.
Python의 정확한 테스트 노드 검증이 필요한 경우 `verification.pytest.argv`에
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

키트 자체의 고정 회귀 검사표는 Neurath 개발 소스의 `tools/run_core_regressions.py`에서
실행합니다. 대상 프로젝트의 검증 결과를 키트 자체 수정의 회귀 증거로 대신 사용하지 않습니다.

## 내부 명령 인터페이스 확인

기존 통합 인터페이스를 확인하는 명령입니다. 사용자가 일반 작업을 시작할 때 실행할 필요는 없습니다.

```sh
.neurath/run engine scripts.agent_harness.state_cli --help
.neurath/run engine scripts.skill_harness.phase_runner --help
.neurath/run skill watch-pr monitor_runtime_readback.py --help
```
