<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# Neurath 개발과 검증

[English](../../en/contributing/index.md)

Neurath는 기존 Git 프로젝트에 공통 하네스를 설치한다. Neurath 자체를 개발할 때는 설치기, 독립 배포 런타임, Claude Code·Codex와 프로젝트 작업을 연결하는 계약을 바꾼다. Neurath를 사용하는 애플리케이션의 변경은 해당 프로젝트의 소스와 연결 설정에서 수행한다. 애플리케이션 작업을 시작하려면 [사용 안내](../usage/index.md)를 참고한다.

이 절은 Neurath를 개발하고 운영하는 에이전트의 실행 참조다. 변경할 원본, 검사로 확인할 수 있는 범위, 승인된 설치를 대상 프로젝트에 적용하는 절차를 설명한다.

## 변경할 책임 영역 찾기

| 바꾸려는 동작 | 확인할 원본 | 상세 참조 |
| --- | --- | --- |
| 프로젝트 파일 보존·배치 | `src/neurath/install/`과 설치기 테스트 | [설치 트랜잭션 설계](installation-design.md) |
| 초기 설치·옵션·실행 환경 선택 | `setup`, `src/neurath/cli.py`, `src/neurath/install/setup.py` | [설치 실행 참조](setup-reference.md) |
| 배포 규칙·스킬·엔진 | `src/neurath/_assets`와 해당 런타임 테스트 | [실행 자산 관리](assets.md) |
| 호출자 확인을 거치는 작업 API | `src/neurath/runtime/task_schema.py`, 도메인별 작업 모듈, `src/neurath/agents/mcp.py` | [작업 도구](task-tools.md) |
| 호스트 활성화·호출자 신원 | `src/neurath/hosts/identity.py`, `src/neurath/hosts/hooks.py` | [검증](validation.md) |
| 공식 업데이트 준비·복구 | `src/neurath/updates.py`, `src/neurath/release_install.py` | [릴리스 업데이트](releases-reference.md) |

지원 환경은 macOS와 Linux이며 Python 범위는 `>=3.14,<3.15`다. POSIX 프로세스 그룹, `fcntl`, Bash를 사용하므로 Windows는 지원 대상에 포함하지 않는다. 런타임 의존성은 `claude-agent-sdk>=0.2.152,<0.3`다. 대상 프로젝트는 다른 언어를 사용할 수 있으며 자체 의존성 환경을 유지한다. 패키지 조건은 [pyproject.toml](../../../pyproject.toml)에 정의되어 있다.

주기적 목표 환기의 전략은 [설계 원칙](design-principles.md), 실제 전달은 [런타임 수명주기](runtime-lifecycle.md)에서 설명한다. [제공자 간 작업 승계](provider-continuity.md)는 대상 고유 설정 유지와 중단된 작업 승계를 다루며, 맥락 조회·태스크 이전·원본 재개 차단을 구분한다.

## 재현 가능한 개발 환경 준비

Neurath 소스 체크아웃에서 실행한다.

```sh
uv sync --locked
```

커밋된 잠금 파일에 따라 개발 환경을 준비하는 명령이다. 대상 프로젝트에 하네스를 설치하는 작업은 별도다. 새로운 설치 동작은 의도한 전후 차이를 드러내는 실패 테스트로 먼저 정의한다. 개발 중에는 관련 검사를 실행하고, 구현이 정리되면 필수 검사를 수행한다.

```sh
uv run --locked python tools/check.py
```

검사는 배포 자산 무결성, Python 진단, 패키지·설치 테스트, 임시 Git 환경의 런타임 계약을 순서대로 확인한다. 결과는 검사한 소스에 적용된다. 배포본 독립 실행, 초기 설치, 실제 호스트의 동작을 확인하는 추가 검사는 [검증 안내](validation.md)에 정리되어 있다.

런타임이나 실행 자산을 바꾸었다면 무결성 목록을 다시 만든 뒤 검사·빌드·자기 설치를 진행한다.

```sh
uv run --locked python tools/build_manifest.py
uv run --locked python tools/check.py
uv build
./setup --self
```

자기 설치는 일반 설치기를 통해 이 체크아웃의 하네스를 갱신한다. 영속 도구 환경은 개발 `.venv`와 분리된다. 빌드한 결과와 실제 설치된 런타임을 각각 기록한다. 문서만 바꾼 경우에는 새 설명을 전달하기 위해 자기 설치할 필요가 없다.

## 제품 계약 유지

관리 대상 런타임의 원본은 `src/neurath/_assets`다. 설치된 `.agents/skills`와 `.neurath/rules`는 배치 결과이며 설치 이력과 비교된다. 배치 결과를 직접 수정하면 재사용할 소스 변경이 생기는 대신 설치 충돌이 발생할 수 있다.

공개 상세 문서는 `docs/en`과 `docs/ko` 아래에 같은 상대 경로로 유지한다. 각 언어의 `usage`에는 자연어 요청과 사용자에게 보이는 결과를, `contributing`에는 실행 명령과 설정 예제를 둔다. 기능 범위, 지원 동작, 오류와 한계를 두 언어에 함께 반영한다. 언어 전환 링크를 제외한 탐색 링크는 같은 언어를 가리킨다. 루트 README와 CONTRIBUTING 진입점만 `.md`·`.ko.md` 쌍을 쓴다.

공개 문서 규칙을 확인하는 집중 검사는 다음과 같다.

```sh
uv run --locked pytest -q tests/test_publication.py
```

공개 문서와 배포본에는 비공개 원문, 설치 계획, 진단 로그, 설치·실행 기록, 인증 정보, 개인 경로, 다른 저장소의 출처 정보를 넣지 않는다. 검증 근거는 `.validation` 같은 무시된 비공개 저장소에 보관한다. 배포 자산의 소유권과 포함 범위는 [실행 자산 관리](assets.md)를 참고한다.

## 검토자가 판단할 수 있는 결과 설명

어떤 입력에서 동작이 달라지는지, 호환성이나 설치에 어떤 영향이 있는지, 실제로 무슨 검사를 실행했는지 설명한다. 관련 소스와 테스트를 연결하고, 근거가 소스 무결성·빌드된 패키지 실행·대상 파일 배치·프로토콜 모의 검사·실제 네이티브 세션 중 어디에 해당하는지 밝힌다. 소유자가 인증된 작업 결과는 소유자의 보고이며, 명시적 검토 절차는 별도의 독립 검토 계약을 따른다.

명명된 MCP 작업에서는 직전 결과가 반환한 상태와 revision을 사용한다. 일반 편집과 명령 실행에 별도 material 배치나 기준별 acceptance 문서를 만들 필요는 없다. 작업 목록이 있는 세션에서는 작업 원장이 완료 판정의 기준이며, 화면의 TODO는 그 표시 결과다. 자세한 내용은 [작업·TODO 계약](task-todo-contract.md)을 참고한다.

검사와 빌드는 GitHub 생성, push, 공개 배포의 권한을 부여하지 않는다. 현재 사용자 요청에 포함된 배포 작업을 수행하고, 실제 원격 결과를 로컬 작업과 구분하여 보고한다.
