<!-- date: 2026-09-13; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# 독립 실행 자산의 관리와 배포

[English](../../en/contributing/assets.md)

설치된 하네스는 소스 체크아웃과 대상 애플리케이션에 의존하지 않고 실행되어야 한다. Neurath는 이를 위해 `src/neurath/_assets` 아래의 배포 런타임 자산을 직접 관리한다. 대상 프로젝트에는 별도 도구 환경을 가리키는 실행기와 필요한 배치 결과가 들어간다. 다른 저장소는 빌드 입력이 아니다.

## 원본의 책임 구분

| 영역 | 책임 |
| --- | --- |
| `src/neurath/_assets` | 독립 실행 규칙·스킬 자원·하네스 엔진 |
| `src/neurath/install/projection.py` | 공통 배치와 호스트별 설치 항목 |
| `src/neurath/runtime` | 명명된 작업 계약과 도메인 작업 연결 |
| `src/neurath/hosts` | 실제 호스트 수명주기·신원 연동 |
| `src/neurath/resources.py` | 패키지 자원 위치와 배포본 식별 |
| `src/neurath/manifest.json` | 패키지 파일의 기대 해시 |
| `tests/runtime` | 임시 독립 자산 환경에서 실행하는 런타임 계약 |

패키지 원본을 고친 뒤 manifest를 다시 생성하고 검사한다. 설치된 `.agents/skills`, Claude 스킬 링크, `.neurath/rules`, 실행기는 설치 결과다. 소유된 배치 파일을 직접 수정하면 이력과 달라져 업데이트나 제거가 막힐 수 있다.

`generic` 프로필은 공통 동작을 제공한다. 프로젝트별 문서 역할, 검사 명령, 용어, 메타데이터 관례는 대상 지침과 `.neurath/project.json`에 둔다. 실행을 위해 비공개 애플리케이션의 용어나 소스 경로, 의존성을 패키지에 넣지 않는다.

## 공개 인터페이스의 범위

현재 공개 스킬은 31개다. 이 중 29개에는 단계 계약이 있고 `explain-code`, `graphify`는 단계 계약이 없는 지원 스킬이다. 공개 스킬 이름은 사용·배치 이름이며 내부 계약 식별자와 역할이 다르다. 접두어를 설정하면 공개 배치 이름이 바뀌고 내부 계약 이름은 유지된다.

명명된 stdio MCP API는 내부 작업 137개 중 127개를 공개한다. 닫힌 입력 스키마는 선언하지 않은 필드를 거부하며 구조화된 응답은 결과와 실패를 나눈다. 저장된 호출의 호환 처리와 공개 탐색은 다르다. `workflow_start`, `workflow_advance`, `workflow_finalize`는 기존 저장 호출을 처리하지만 새 명시적 단계 작업은 `phase_start`, `phase_complete`, `phase_finalize`를 쓴다. 예전 임의 인자 경로와 material·verification 기록 작업도 일반 에이전트 인터페이스가 아닌 호환 기반이다.

현재 [작업 스키마](../../../src/neurath/runtime/task_schema.py)와 [MCP 서버](../../../src/neurath/agents/mcp.py)가 공개 범위를 정의한다. 명명된 작업과 실제 반환 revision을 사용한다. 일상적인 작업을 위한 별도의 CLI 문자열·Python 모듈·상태 직접 편집 통로를 추가하지 않는다. 일반 프로젝트 편집과 명령은 호스트의 일반 도구로 실행한다.

## 무결성과 독립 실행 유지

[자원 처리](../../../src/neurath/resources.py)는 설치 패키지 안에서 `_assets`를 찾는다. 배포본 식별자는 Python 캐시 파일을 제외한 패키지 상대 경로와 바이트를 해시한다. [manifest 생성기](../../../tools/build_manifest.py)는 진단에 사용할 파일 무결성 기대값을 기록한다. 실행 자산 변경 후 manifest가 그대로이면 소스와 패키지 계약이 어긋나므로 다시 생성해야 한다.

런타임 변경의 개발 순서는 다음과 같다.

```sh
uv run --locked python tools/build_manifest.py
uv run --locked python tools/check.py
uv build
./setup --self
```

`uv run --locked python -m build`로도 빌드할 수 있다. 빌드한 패키지, 설치된 런타임, 실제 호스트가 로드한 인스턴스는 서로 다른 대상이다. 이 관측들을 연결할 때는 실제 wheel 식별자를 비공개 검증 결과에 남긴다.

설치 실행기는 격리된 Python import 경로를 사용한다. 대상 애플리케이션에 `scripts`라는 패키지가 있어도 번들 엔진을 가리면 안 된다. wheel 검증은 외부 환경에서 소스 체크아웃 접근을 차단한 채 번들 모듈을 가져온다. 초기 설치 검증은 원본 소스를 다른 위치로 옮긴 뒤 설치 실행기를 사용한다. 이는 독립 패키징의 근거이며, 실제 호스트 동작은 [검증](validation.md)의 네이티브 시나리오로 확인한다.

## 가변 상태를 배포 자산과 분리

변경 가능한 런타임 도메인의 정식 저장소는 Git 공통 경로에서 구한 제어 루트 아래 `.neurath/local/runtime.sqlite3`다. 연결 worktree는 같은 루트를 공유하지만 namespace와 도메인 codec이 소유권, revision, 메시지, 작업 원장, 기억, 설치 상태를 구분한다. 다른 clone이나 컴퓨터로 자동 동기화하지 않는다.

공통 데이터베이스가 모든 비공개 파일을 대체하는 것은 아니다. 불변 설치 계획, 보관 원본, 복구 백업, 진단 자산은 각자의 형식과 수명주기를 갖는다. 설치된 설정 표시 파일도 디스크에 남는다. 상태 도메인을 추가하거나 저장소 전환을 설명할 때 이 구분을 유지한다. 기존 쓰기 경로의 명시적 폐쇄는 [설치 설계](installation-design.md)에 설명되어 있다.

세션 상태 접근은 세션 커널과 호출자에 결속된 상태 핸들을 거친다. worktree 임대와 소유권 확인 키는 오래된 쓰기 주체를 배제한다. 호출자가 제공한 세션 ID나 자산 문자열로 네이티브 호스트 신원을 대체할 수 없다. 새 작업을 공개하는 자산도 이 경계를 유지해야 한다.

## 공개 배포 내용 검사

공개 문서는 영어·한국어 경로가 대응하며 소스 배포본에 포함된다. 패키지·공개 문서 검사는 메타데이터, 언어 전환, 경로 규칙, 독립성, 비공개 자료 제외를 확인한다.

```sh
uv run --locked pytest -q tests/test_publication.py
```

호스트 원문, 설치 원본, 각종 실행·설치 기록, 개인 경로, 인증 정보, 비공개 프로젝트 이름, 디버그 환경은 패키지에 포함하지 않는다. `.validation` 같은 무시된 저장 공간에 보관한다. 공개 예제는 Neurath가 소유한 자원만으로 일반 환경에서 재현할 수 있어야 한다. `neurath corpus /path/to/new-directory`는 해당 독립 자산을 새 디렉터리로 복사한다.

구현·검사 근거: [패키지 메타데이터](../../../pyproject.toml), [공개 문서 테스트](../../../tests/test_publication.py), [배포본 검증](../../../tools/validate_distribution.py), [런타임 검사 실행기](../../../tools/run_core_regressions.py).
