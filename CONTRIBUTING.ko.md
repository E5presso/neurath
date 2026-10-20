# 기여 안내

[홈](README.ko.md) · [English](CONTRIBUTING.md)

승인된 명세와 [기반 구조](docs/ko/core-foundation.md)의 책임 경계를 따릅니다.
도메인 엔티티는 불변식과 상태 전이를 담당합니다. repository·관찰 port는 `ABC`와
`@abstractmethod`를 사용하며 해당 adapter가 명시적으로 상속합니다. 유스케이스는 Spakky의 `ICommandUseCase` 또는 `IQueryUseCase`를 구현합니다. 입력은 `AbstractCommand` 또는 `AbstractQuery`를 상속하고 `run()`으로 처리합니다. Command/Query·Result DTO·UseCase를 같은 모듈에 정의하며 자체 인터페이스나 공통 DTO 패키지를 추가하지 않습니다.
도메인은 Spakky의 `AbstractAggregateRoot`·`AbstractValueObject`를 사용합니다. 저장 포트와
adapter는 `IGenericRepository`·`AbstractGenericRepository`의 기본 CRUD와 배치 메서드를
다시 정의하지 않습니다. `@Table`·`AbstractMappableTable`·`SchemaRegistry`로 매핑하고
표준 `ConnectionManager`·`SessionManager`·`Transaction`을 사용합니다. 요청 경계는
엔진 수명을 정리하며 별도 UoW나 트랜잭션 구현을 추가하지 않습니다.

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
허용 목록, 과거 소스 예외 baseline, `Any` 우회, 타입·lint 무시 정책은 없습니다.
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

## 기계 검사 규칙과 사람 검토의 경계

AST 검사는 import 별칭과 로컬 상속 관계를 해석해 Protocol, Literal, Any/cast,
이름으로 드러나는 커스텀 transaction/UoW API, Core/core 모듈, 계층 위반 import,
ABC/abstractmethod 없는 port, 명시 계약 상속이 없는 repository/observer,
비선언형 ORM 매핑을 거부합니다. 직접 만든 use case 인터페이스, frozen 또는 기본 값 동등성을 쓰는
엔티티 dataclass, 조회·저장을 넘어서는 repository 계약, 엔티티를 노출하는 관찰 port,
실제 호스트 어댑터에서의 직접 의존성 생성도 거부합니다. 모든 유스케이스는 Spakky command/query 계약과 run 메서드를 구현하고 입력도 프레임워크 기반을 상속해야 합니다. 동종 가변 길이 컬렉션 계약은 Sequence를 사용하며 고정 이종 tuple과 구분합니다. 결과 DTO는 해당 유스케이스의 입력·처리와 같은 모듈에 두고 프로토콜이 없는 transport 중계 패키지는 두지 않습니다. Project는 불변 ProjectLocation 값을 소유하며
위치 전용 repository·DI·생명주기를 만들지 않습니다. 자식 테이블은 ORM 관계로 매핑하여
프로젝트와 원자적으로 저장합니다. 루트 선택·승격은 도메인 규칙입니다. 모든 저장소의
삽입·갱신은 `save(entity) -> entity`로 통일하고 add·insert·create·update 저장 별칭은
거부합니다. 도메인의 create와 SQLAlchemy Session.add는 허용합니다. 소유된 자식 값과
선언형 관계는 정상 fixture로 검증하며 aggregate 의미 자체는 사람 검토에 남깁니다. 자원을 yield·정리하는 provider는 허용하며
트랜잭션까지 소유하는 generator wrapper는 거부합니다. 공통 품질 hook은 순수 도메인과
실제 DI/ORM 수명 회귀 시험도 구문·checker 실패 fixture와 함께 실행합니다. ORM 규칙은 실행 모델에 적용하며 불변 Alembic
revision의 DDL에는 SQLAlchemy Column을 의도적으로 사용합니다. 별칭, 간접 상속,
port처럼 가장한 DTO, 새 모듈 등 실패·정상 fixture로 규칙을 검증합니다.

검사는 구체적인 구문과 타입 관계를 확인합니다. 이름이 실제 책임을 나타내는지,
docstring이 유용한지, 일반 클래스가 숨겨진 façade인지, 이름을 바꾼 트랜잭션
추상화가 의미상 적절한지는 증명하지 못합니다. 응집도·불변식·트랜잭션 범위와
추상화의 필요성은 사람이 검토해야 합니다. lint가 이 판단까지 증명한다고
주장하지 않습니다. 동적 코드 생성·리플렉션 우회는 명시적 구현의 대안이 아닙니다.

저장소 매핑의 객체 선택은 이름 있는 변수와 명시적 `is None` 분기를 사용합니다.
좁은 AST 규칙은 대입·반환·comprehension 요소에서 `mapping.get(...) or 대체객체`를
거부하며 일반적인 boolean 조건은 허용합니다.

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

기본 저장 동작은 `FRAMEWORK_CRUD` 검사로 재구현을 거부합니다. `core_0002` 이전은 기존
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

유스케이스별 Result가 별도 패키지로 이동하거나 다른 모듈의 응답으로 대체되면 `RESULT_LOCATION` 검사가 실패합니다. 고정 revision 상수의 재도입은 `ALEMBIC_REVISION`, 제거한 프로토콜 없는 중계 모듈의 재도입은 `TRANSPORT_PASSTHROUGH`로 검사합니다. 모든 실제 유스케이스·입력의 프레임워크 상속과 결과 배치도 순회 검증합니다. 이 검사는 업무 책임의 의미적 적절성을 대신하지 않습니다.

도메인 검증과 업무 동작은 상태를 소유하는 aggregate·값 객체 또는 유스케이스의 메서드에 둡니다. domain/application의 독립 함수와 이를 이름만 바꾼 정적 유틸리티 클래스는 `BEHAVIOR_OWNERSHIP`으로 거부합니다. 텍스트 검증도 해당 객체의 validate/행동 메서드가 수행합니다. 의존 검증은 Task 인스턴스가 self.uid와 자신의 현재/제안 의존을 사용하며 별도 task_id를 받지 않습니다. 인프라 자원 구성 함수와 Alembic 진입점은 이 규칙과 구분합니다.
