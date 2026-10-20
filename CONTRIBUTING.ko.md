# 기여 안내

[홈](README.ko.md) · [English](CONTRIBUTING.md)

현재 구현 범위와 내부 API는 [코어 기반](docs/ko/core-foundation.md)·[태스크 원장](docs/ko/task-ledger.md), 제품 요구는 [명세](docs/ko/specification.md)에 있습니다. 현재 후보에는 공개 CLI·호스트 훅·설치기가 없습니다.

## 환경과 검사

Python 3.14를 사용합니다.

```sh
uv sync --locked
uv run --locked python tools/install_quality_hook.py
uv run --locked pre-commit run --all-files
uv run --locked python tools/check.py
```

Git hook 설치 도구는 현재 체크아웃의 전용 hook 디렉터리와 worktree별 설정을 사용합니다. 기존 공통·사용자 설정을 보존하고 실행 가능한 기존 pre-commit을 먼저 호출하며, 알 수 없는 전용 hook 디렉터리를 덮어쓰지 않습니다.

pre-commit과 필수 runner는 `tools/quality.py`를 공유합니다. Ruff lint·포맷, strict Pyrefly, Google 형식 pydoclint, docstring 언어 검사와 구조·계약 회귀 시험을 실행합니다. 필수 runner는 이어서 전체 동작 시험과 휠 생성을 수행하고 성공하면 `NEURATH_CHECK_OK`를 출력합니다. CI도 같은 runner를 사용합니다.

제품 소스와 개발 도구 전체에 타입·docstring 검사를 적용합니다. 테스트는 lint·포맷 대상이며 새 docstring·타입 표기를 강제하지 않습니다. 기존 docstring은 테스트·루트 Python 설정을 포함해 한국어 요약과 자연어 필드 설명을 사용합니다. Google 섹션명과 코드·타입 식별자는 유지하고, 인자 타입은 signature에 정의합니다.

`tools/docstrings.py`는 코드·형식 표기를 제외한 한국어 설명이 전혀 없는 docstring을 찾는 최소 검사입니다. 글자 수·한영 비율·줄별 비중을 요구하지 않습니다. 설명의 정확성과 유용성은 별도로 검토합니다.

## 책임과 프레임워크 사용

- 상태와 의미를 소유하는 도메인 객체에 불변식·상태 전이를 둡니다. 유스케이스는 조회·도메인 호출·저장을 조정하며 필요하면 도메인 예외를 발생·전파·변환합니다.
- port는 명시적 `ABC`·`@abstractmethod` 계약으로, adapter는 해당 상속 관계로 표현합니다. Protocol은 사용하지 않습니다.
- 유스케이스는 Spakky의 `ICommandUseCase`·`IQueryUseCase`와 `run(command/query)`를 구현합니다. 입력은 `AbstractCommand`·`AbstractQuery`를 상속하고 전용 입력·결과 DTO는 해당 유스케이스 모듈에 함께 둡니다.
- Spakky의 도메인 기반, 기본 repository CRUD·배치, 선언형 테이블 매핑·SchemaRegistry, 생성자 주입·요청 트랜잭션을 재사용합니다. 현재 구성은 코어 기반 문서에 설명합니다. 추가 adapter나 추상화는 실제 책임과 필요성으로 판단합니다.
- 읽기 전용 목록 계약은 `Sequence`로 표현합니다. 하위 클래스의 자기 타입을 보존하는 classmethod 생성·변환은 `Self`를 사용합니다. Python 3.14 문법은 Ruff UP로 확인합니다.
- 오류·대상 외·무변경 경로는 guard clause와 early return으로 먼저 종료하고 정상 흐름을 얕게 유지합니다. 반복문에서는 continue·break를 활용합니다. 검증·저장·알림 순서와 트랜잭션·finally의 자원 정리를 보존하고, 메서드 분리는 같은 책임 안의 의미 있는 작업 단위로 합니다.

공통 Ruff 검사의 RET505·RET506·RET507·RET508은 return·raise·continue·break 뒤의 불필요한 else를 검출합니다. 다른 중첩의 단순화는 코드 리뷰에서 확인하며 임의의 깊이 상한이나 모든 if·else를 금지하는 검사로 대체하지 않습니다.

실제 등록 구성요소의 타입 관계·계층 의존 방향은 구조 검사로, 현재 저장소·입출력 계약·매핑·자원 수명·이전·도메인 동작은 구체적인 시험으로 확인합니다. 함수·예외·이름·특정 표현식의 존재만으로 책임 위반을 단정하지 않습니다. 모든 반환에 DTO·접미사·frozen을 강제하지 않으며 사용자 정의 AST 검사에서 Any·cast·Literal·일반 무시 주석의 존재만으로 책임 위반을 판정하지 않습니다. Ruff의 표준 ANN 규칙은 ANN401을 포함해 적용합니다. 문법 검사 통과가 의미적 설계의 적절성을 입증하지는 않습니다.

## 스키마와 데이터 보존

이미 적용한 Alembic revision은 유지하고 스키마 변경을 새 revision으로 추가합니다. DB 시험은 임시 경로에서 기존 자료·외래 키 보존, 이전 실패 rollback, 경합·범위 격리, 잘못된 저장소 거부를 확인합니다. 구체적인 스키마와 초기화는 [코어 기반](docs/ko/core-foundation.md#스키마와-보존), 과거 사용자 DB 변환의 경계는 [이전·복구](docs/ko/recovery.md)를 참고하세요.

## 라인·분기 커버리지

`tools/check.py`는 Alembic 동적 로드를 포함한 `src/neurath` 전체를 디렉터리 기준으로 계측합니다. 라인·분기 각각 100%여야 하며 최종 보고서의 `missing_lines`·`missing_branches`·`excluded_lines`가 모두 0이어야 합니다. 반올림 비율만으로 통과하지 않습니다.

omit·커스텀 제외·`pragma: no cover`·`pragma: no branch`로 수치를 맞추지 않습니다. JSON/XML 보고서는 `coverage-out/`에 생성하고 CI artifact로 보존합니다. 실제 실패·정상 동작과 게이트 우회 거부는 회귀 시험으로 확인합니다.

## 문서

공개 문서는 `docs/en`·`docs/ko`의 같은 상대 경로에 같은 범위로 유지합니다. README와 CONTRIBUTING도 영어·한국어 쌍을 맞춥니다. 개인 경로와 검증 원문은 공개 문서·패키지에 넣지 않습니다. 문서별 역할과 현재 구현·제품 설계의 구분은 [문서 안내](docs/ko/index.md)에 있습니다.

## 서비스·저장소 명명

제품 코드의 서비스는 `Service`, 저장소는 `Repository`로 끝나야 합니다. 인터페이스는 `I` 접두어를 사용하고 구현체는 이를 실제 기술 스택 이름으로 대체합니다. 예를 들어 `IDirectoryObserverService`의 구현은 `GitDirectoryObserverService`, `IProjectRepository`의 구현은 `SQLAlchemyProjectRepository`입니다.

`tools/architecture.py`가 전체 소스의 포트와 등록 데코레이터, 별칭·간접 상속을 추적합니다. 접미사 누락, 인터페이스의 `I` 누락, 기술 접두어 누락·불일치는 공통 pre-commit과 필수 CI를 실패시킵니다. 현재 기술 접두어는 `Git`·`Subprocess`·`Stderr`·`Posix`·`SQLAlchemy`입니다. 다른 기술을 도입할 때는 해당 접두어와 정상·실패 회귀 시험을 함께 추가합니다. 새 구현 클래스마다 허용 목록에 올리는 방식은 사용하지 않습니다.

유스케이스에는 `UseCase` 접미사만 강제합니다. `CreateTaskUseCase`처럼 이름을 유지하며 기술 접두어를 붙이지 않습니다. 명명 규칙을 이유로 개별 인터페이스를 추가하지 않고 기존 Spakky `ICommandUseCase`·`IQueryUseCase` 계약을 사용합니다. 데코레이터·직접 및 간접 상속으로 유스케이스를 찾아 접미사 누락을 같은 검사에서 거절합니다.
