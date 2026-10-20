# 기여 안내

[홈](README.ko.md) · [English](CONTRIBUTING.md)

승인된 명세와 [기반 구조](docs/ko/core-foundation.md)의 책임 경계를 따릅니다.
도메인 엔티티는 불변식과 상태 전이를 담당합니다. repository·관찰 port는 `ABC`와
`@abstractmethod`를 사용하며 해당 adapter가 명시적으로 상속합니다. 유스케이스는 Spakky의 `ICommandUseCase` 또는 `IQueryUseCase`를 구현합니다. 입력은 `AbstractCommand` 또는 `AbstractQuery`를 상속하고 `run()`으로 처리합니다. 유스케이스 전용 입력·결과 DTO를 같은 모듈에 정의합니다. 이름만으로 다른 인터페이스·공유 자료형을 금지하지 않습니다.
도메인은 Spakky의 `AbstractAggregateRoot`·`AbstractValueObject`를 사용합니다. 저장 포트와
adapter는 `IGenericRepository`·`AbstractGenericRepository`의 기본 CRUD와 배치 메서드를
불필요하게 재작성하지 않고 재사용합니다. `@Table`·`AbstractMappableTable`·`SchemaRegistry`로 매핑하고
표준 `ConnectionManager`·`SessionManager`·`Transaction`을 사용합니다. 요청 경계는
엔진 수명을 정리하며 프레임워크 수명을 중복 구현하는 불필요한 래퍼를 추가하지 않습니다.

## 필수 개발 검사

```sh
uv sync --locked
uv run --locked python tools/install_quality_hook.py
uv run --locked pre-commit run --all-files
uv run --locked python tools/check.py
```

설치 도구는 현재 체크아웃의 전용 Git hook 디렉터리를 만들고 worktree별 설정을
활성화합니다. 공통·사용자 hook 설정을 보존하고 기존 실행 가능한 pre-commit을
먼저 호출하며, 알 수 없는 전용 hook 디렉터리는 덮어쓰지 않습니다.
다른 worktree는 기존 hook 동작을 유지합니다.

pre-commit과 필수 runner는 동일한 `tools/quality.py`를 실행합니다. Ruff의
lint·docstring·타입 표기·포맷, strict Pyrefly, Google 형식 pydoclint 계약 문서, 구조 AST 규칙, 정상·실패 fixture를
검사합니다. CI도 필수 runner를 실행하며, runner는 이어서 전체 동작 시험과
휠 생성을 수행합니다. 성공 표시는 `NEURATH_CHECK_OK`입니다. 현재 소스의 모듈
현재 소스 전체의 타입·형식·문서를 검사합니다. Any·cast·일반 무시 주석의 존재만으로 오류라고 판정하는 별도 금지는 두지 않습니다. 실제 오류와 주석의 적절성은 해당 도구 결과와 의미로 검토합니다.
`src` 아래 앞으로 추가되는 Python 파일도 모두 발견합니다. 시험은 lint·포맷을 적용하며 새 문서 문자열·타입 표기 작성은 강제하지 않습니다.
시험과 루트 Python 설정을 포함한 모든 기존 docstring의 요약·자연어 필드 설명은 한국어로 작성합니다. 제품 소스와 개발 도구는
엄격한 타입 표기와 Google 형식 docstring을 적용합니다. Pydoclint는 Args·Returns·Yields·
Raises·Attributes를 signature와 대조하며 짧은 요약으로 검사를 건너뛸 수 없습니다.
인자 타입은 signature를 기준으로 삼으므로 docstring 인자 설명에 타입을 중복하지 않습니다.
`tools/docstrings.py`는 AST의 실제 문서 문자열을 검사합니다. Google 섹션명과 코드·타입
식별자는 표준 문법을 유지합니다. 식별자와 인라인 코드를 제외한 각 서술 줄은 한글이
두 글자 이상이고 영문 글자 수 이상이어야 합니다. 영문에 한글 단어만 붙인 문장은
실패 fixture입니다. 의도적으로 잘못 작성한 fixture 문자열은 테스트 데이터로 구분하며
번역 정확성과 문서 유용성은 사람이 검토합니다.

## 기계 검사와 의미적 검토

[하네스 규칙 전수 감사](docs/ko/harness-rule-audit.md)에 각 규칙의 원래 요구와 정정 근거를 기록했습니다. Protocol 제외와 계층 의존 방향, 실제 등록 Spakky 구성요소의 타입 관계 등 확인 가능한 계약만 AST에서 검사합니다. 일반 Any/cast/Literal, 모듈·클래스·메서드 이름, contextmanager, 예외 사용을 일괄 금지하지 않습니다.

현재 저장소의 Sequence 목록 계약·기본 메서드 상속·실제 CRUD, 등록 유스케이스의 입력·프레임워크 계약, 현재 전용 결과 DTO의 같은 모듈 배치, 실제 ORM 매핑·자원 수명·Alembic 이전을 구체적인 시험으로 확인합니다. 모든 결과에 DTO·접미사·frozen을 강제하거나 새 구성요소 수를 고정하지 않습니다.

한국어 docstring 요구는 유지합니다. 최소 자동 검사는 한국어 설명이 전혀 없는 문서를 찾으며 글자 수·한영 비율·줄별 언어 비중을 요구하지 않습니다. 실제 문서 언어와 정확성, 도메인 책임·추상화의 필요성은 의미를 검토합니다. 문법 검사의 통과를 이 의미적 판단의 증명으로 사용하지 않습니다.

## 보존과 구현 범위

DB 시험은 모두 임시 경로를 사용합니다. 이미 적용한 revision을 보존하고 스키마
변경은 새 Alembic revision으로 추가합니다. 이전 스키마 fixture, 롤백, 동시 요청,
프로젝트 범위 격리, 거부한 legacy DB의 바이트 보존을 검사합니다. 소스 시험은
실제 사용자 DB의 설치·전환 권한을 뜻하지 않습니다.

타입 검사를 피하는 병렬 runtime을 남기지 않도록 과거 0.3.1 구현과 그 구현에
의존한 시험은 현재 후보 소스 트리에서 제거했습니다. 원본은 Git 기록에 남습니다.
새 시험은 #137/#154의 행위 계약을 유지하며 과거 전체 하네스 시험이 계속 통과한다고
주장하지 않습니다. 태스크·runner·호스트 훅·기억·자료 이전·공개 CLI·설치는 별도
구현 티켓에 남습니다. `setup`은 이 미완성 후보를 설치할 수 없습니다.

공개 문서는 `docs/en`과 `docs/ko`의 같은 상대 경로에 같은 범위로 유지합니다.
개인 경로와 검증 원문은 공개 문서와 패키지에 넣지 않습니다.

Python 3.14 문법은 Ruff UP로 검사하고 classmethod의 자기 타입 반환은 `Self`를 사용합니다.
실패·정상 구조 fixture와 함께 하위 클래스 생성, 요청 밖 반환 객체 변경의 비영속성, 실패 요청의 전체 상태 보존,
Spakky 요청 격리와 초기화 실패 시 자원 정리를 공통 품질 검사에서 실행합니다.

현재 기본 저장 동작의 상속과 실제 수행은 회귀 시험으로 확인합니다. `core_0002` 이전은 기존
ID·revision·종속 자료를 유지하고 원래 시각이 없는 행에는 epoch 미상 표식을 사용합니다.
이전 실패의 스키마·자료·revision 롤백과 실제 상속 CRUD를 회귀 시험으로 확인합니다.

## 라인·분기 커버리지

필수 `tools/check.py`는 `pytest-cov`로 `src/neurath` 전체를 디렉터리 기준으로 계측합니다.
Alembic의 동적 로드도 포함하며 라인과 분기 모두 100%여야 합니다. `--cov-fail-under=100`과
보고서의 `missing_lines == 0`, `missing_branches == 0` 검사를 함께 실행하여 반올림으로
통과하지 못하게 합니다. JSON/XML 보고서는 `coverage-out/`에 생성하고 CI artifact로 남깁니다.

omit, 커스텀 제외 규칙, `pragma: no cover`·`pragma: no branch`로 수치를 맞추지 않습니다.
설정·주석 우회와 실제 미검증 라인·분기가 게이트를 실패시키는 회귀 시험을 유지합니다.
원본 자료를 보존하는 downgrade, 파괴적 downgrade 거부 시 전체 롤백, 잘못된 연결 거부,
일반 무결성 오류 전달, 미완성 관찰 어댑터 실패를 실제 실행 경로로 검증합니다.

보고서의 `excluded_lines`도 0이어야 합니다. 제외로 100%가 된 실제 보고서도 게이트가 거부합니다.


도메인 규칙은 그 상태와 의미를 소유하는 객체에, 유스케이스의 조회·호출·저장 조정은 유스케이스에 둡니다. 책임 배치는 실제 동작과 호출 흐름으로 검토합니다. 유스케이스에서도 도메인 예외의 발생·전파·변환이 가능하며, 함수·정적 메서드·raise 문 자체를 금지하지 않습니다. 의존 순환·범위·정정 보존·원자성은 기존 도메인·통합 동작 시험으로 확인합니다. 문법 검사만으로 이 책임 배치가 옳다고 주장하지 않습니다.
