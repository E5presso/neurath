# Neurath 개발 지침

Neurath는 원문 출처와 미완료 작업을 보존하는 에이전트 하네스다.
현재 사용자 지시와 `docs/ko/specification.md`를 구현의 기준으로 삼는다.

- 코어는 hook·CLI 요청마다 사용자 단위 단일 SQLite의 상태를 조회해 처리하는 stateless service다. 프로젝트·세션은 DB 안에서 구분한다. 지속 상태를 상주 코어 메모리에 의존시키지 않는다.
- 설치된 rules가 기본 진입점이며 에이전트가 요청에 맞는 스킬을 선택한다. 사용자 지정 스킬은 그 지정을 따르고 단순 대화에는 강제하지 않는다. 선택한 스킬은 CLI로 시작하며 phase는 기존 runner가 관리한다.
- 태스크/TODO의 완료 여부는 종료 훅이 결정론적으로 검사한다. 사용자 의도 충족과 요청된 회고의 내용 평가는 별도 서브에이전트 또는 다른 provider에게 위탁한다. 결과 평가는 작업 묶음을 마무리하는 스킬의 phase로 관리하고 회고 제안·거절은 원래 작업 종료와 구분한다.
- 도메인 규칙은 `src/neurath/domain`, 유스케이스는 `application`, SQLAlchemy·Alembic과 요청별 구성은 `infrastructure`에 둔다. 유스케이스의 Command/Query·Result DTO·UseCase는 같은 `application/usecases/<동작>.py` 모듈에 정의한다. 별도 `application/dto` 패키지나 공통 응답 기반을 만들지 않는다. 실제 CLI·호스트 프로토콜을 처리하지 않는 호출 중계 계층도 만들지 않는다. 도메인은 외부 계층에 의존하지 않는다.
- 기존 데이터 이전은 `migration`의 명시적 보존 경계에서 수행한다. 원본 DB를 수정하거나 미완료 작업을 임의로 완료·취소하지 않는다.
- 새 설계는 Python + Typer 기반 `neurath` CLI 전용이며 MCP 서버나 어댑터를 제공하지 않는다. 릴리스 시 실제 CLI 정의에서 가이드 프롬프트를 생성하고 설치 시 관리 영역에 반영한다. 네이티브 호스트의 실행 권한과 사용자 승인을 하네스 기록으로 대체하지 않는다.
- `uv sync --locked`로 개발 환경을 준비하고 `uv run --locked python tools/check.py`로 필수 검사를 실행한다.
- 현재 `./setup`은 미완성 후보 설치를 거부한다. 소스 검사, 패키지 생성, 설치, 실제 호스트 호출을 구분해 보고한다.
- 설치는 관련 없는 사용자 설정·훅·지침을 보존하며, 변경 전에 복구 사본을 남긴다.
- 공개 문서는 `docs/en`과 `docs/ko`의 같은 상대 경로에 함께 작성한다. README와 CONTRIBUTING은 영어·한국어 쌍을 유지한다. 개인 경로와 검증 원문은 공개 문서나 패키지에 넣지 않는다.
- 코드·설치 수정은 승인된 로컬 작업이다. 공개 push·PR·배포는 사용자의 별도 요청 없이 수행하지 않는다.
- 도메인 aggregate, 명시적 ABC port, 개별 command/query use case, 구체 repository adapter와 declarative ORM 모델의 책임을 구분한다. 참고 구조의 과거 Protocol·커스텀 use case 인터페이스·UoW는 복제하지 않는다. 모든 유스케이스는 Spakky의 ICommandUseCase 또는 IQueryUseCase와 run 계약을 구현하고 입력은 AbstractCommand 또는 AbstractQuery를 상속한다. Spakky Framework 8.1.0의 AbstractAggregateRoot·AbstractValueObject·IGenericRepository·AbstractGenericRepository·AbstractMappableTable·Table·SchemaRegistry와 ConnectionManager·SessionManager·Transaction을 사용한다. 기본 CRUD·배치 메서드를 포트나 어댑터에 다시 정의하지 않는다. 트랜잭션은 표준 Transaction이 소유하며 Neurath용 UoW나 트랜잭션 구현을 추가하지 않는다.
- 전체 현재 src와 tools에 strict Pyrefly·Google 형식 pydoclint·Ruff 검사를 적용한다. pre-commit과 CI는 tools/quality.py를 공유한다. 모듈 의미와 문서의 유용성은 별도 사람 검토 사항이다. 저장소는 조회·저장만 제공하며 위치 식별·승격·충돌 규칙은 Project aggregate가 소유한다. 엔티티는 가변 상태·동일성을 가지며 불변 관찰·명령·응답 값과 구분한다.
- 현재 후보는 #137의 프로젝트·세션 기반과 #140의 원문·태스크 원장 라이브러리다. 이전 MCP runtime은 Git 기록에 있으며 새 패키지에는 포함하지 않는다. 공개 CLI·설치·기존 자료 변환은 후속 티켓이며 이 후보를 실설치하지 않는다.

- ProjectLocation은 Project.locations에 종속된 불변 값이다. 별도 위치 repository·DI·생명주기를 만들지 않는다. 물리적 자식 테이블은 선언형 ORM 관계로 매핑하고 프로젝트 저장 시 원자적으로 반영한다. 소유자 선택·승격은 도메인에 두고 repository에는 조회·저장 매핑만 둔다.
- repository는 신규·기존 엔티티를 모두 save(entity) -> entity로 저장한다. add/insert/create/update 저장 별칭을 만들지 않는다. 도메인의 create와 SQLAlchemy Session.add는 이 계약 명칭 규칙과 구분한다. 세션의 ORM 버전 검사·동일 값 no-op·분리된 오래된 엔티티 충돌을 보존한다.
- src·tools·tests 및 루트 Python 설정의 실제 docstring은 요약과 자연어 필드 설명까지 한국어로 작성한다. Google 섹션명과 코드·타입 식별자는 유지한다. 영문 오류 fixture는 의도된 테스트 데이터로만 둔다. tools/docstrings.py가 실제 문서 문자열의 한국어 서술을 검사하며 영문에 한글 한 단어만 붙이는 방식은 허용하지 않는다. 번역 정확성과 aggregate 의미는 별도 사람 검토 사항이다.
- 저장소의 객체 선택은 이름 있는 변수와 명시적인 `is None` 분기로 작성한다. `mapping.get(...) or 새객체`처럼 진리값으로 객체를 선택하는 축약은 사용하지 않는다. 일반적인 boolean 조건은 이 규칙과 구분한다.

- 지원 Python 3.14 문법은 Ruff UP 규칙으로 검사한다. 호출한 하위 클래스 타입을 유지하는 classmethod 생성·변환 메서드는 Self를 사용한다. 구체 도메인 타입으로 변환하는 인스턴스 메서드의 반환 타입은 그대로 명시한다. Spakky 컨테이너는 요청마다 새로 구성하고 엔진·세션은 요청 경계에서 항상 정리한다.

- 도메인의 uid와 변경 메타데이터는 프레임워크 기반을 사용한다. 기존 id 참조와 정수 revision은 보존하며 ORM의 version_id_col은 정수 revision에 연결한다. UUID version은 도메인 변경 토큰으로 저장한다. SQLite 시각을 UTC로 왕복하되 변경 없는 저장이 UPDATE를 만들지 않게 매핑한다. core_0001은 수정하지 않고 core_0002로 기존 행과 외래 키를 보존한다. 이전 시각이 없으면 epoch를 미상 표식으로 저장하며 원래 생성 시각으로 해석하지 않는다.

- `tools/check.py`는 `src/neurath` 전체의 라인·분기 커버리지를 각각 100%로 강제한다. Alembic 동적 로드 파일도 소스 경로로 계측한다. 미실행 라인·분기 개수가 하나라도 있으면 실패하며 반올림한 비율로 통과하지 않는다. omit·커스텀 제외·pragma no cover/no branch로 기준을 우회하지 않는다. 커버리지 보고서는 coverage-out에 생성한다.

- 최종 커버리지 보고서의 excluded_lines도 0이어야 한다. 추상 포트의 기본 본문으로 잘못 위임한 어댑터는 명시적으로 실패하며 등록 트랜잭션을 롤백해야 한다.

- #140의 Task가 정의·의존·실행 시도·외부 대기 이력을 소유한다. 이 자식들에 별도 repository를 만들지 않는다. 상태 질문·과거 요약을 새 목표로 승격하지 않고 실제 정정은 지정한 작업·필드만 변경한다. 후보 제출은 성공이 아니며 오래된 개정의 결과는 보존하되 현재 요구를 닫지 않는다. TODO는 현재 전체 원장의 투영이며 별도 완료 권한이 아니다.

- 동종 컬렉션의 포트·DTO·도메인 계약은 collections.abc.Sequence로 선언한다. Sequence 자체가 실행 시 불변성을 보장하지는 않으며 소유 이력의 저장 구현에는 tuple snapshot을 사용할 수 있다. 고정된 이종 쌍의 tuple과 구분한다.
- 스키마 revision은 Alembic migration 파일과 version table만 관리한다. 일반 요청은 MigrationContext의 현재 heads와 ScriptDirectory의 배포 heads로 호환성을 확인하며 별도 최신 revision 상수를 유지하지 않는다. 일반 요청에서 자동 이전하지 않는다.

- 결과 DTO는 입력 DTO와 마찬가지로 해당 유스케이스의 계약이다. `<동작>Result`를 같은 모듈에 정의하고 프레임워크 제네릭의 결과 타입과 run 반환 타입으로 사용한다. 반환할 데이터만 담고 상태 전이·의존 판단은 도메인, 조회 결과 구성은 해당 유스케이스가 담당한다. CLI·훅은 실제 호출자로서 출력 형식 변환을 담당한다. DTO 명칭이나 위치 변경만으로 책임 문제가 해결됐다고 판단하지 않는다.
- 리뷰 지적은 해당 줄뿐 아니라 같은 패턴 전체를 조사하고, 수정·지침·정상/실패 회귀 fixture를 함께 반영한다. Sequence 계약, Spakky command/query·입력 기반 상속과 run, 유스케이스별 결과 배치, Alembic revision 단일 관리, 프로토콜 없는 transport 중계 제거를 공통 pre-commit/CI에서 확인한다. 구문 검사가 의미적 책임까지 입증한다고 주장하지 않는다.
- 사용자 응대와 PR 답글은 한국어 존댓말로 작성한다. 자신을 가리킬 때는 저·제가·제 표현을 사용한다. 설명이 잘못됐으면 잘못된 판단을 명확히 정정하고 요청 범위를 바꾸지 않는다.

- 도메인 불변식·의존·텍스트 검증은 해당 상태를 소유하는 aggregate·값 객체의 인스턴스 검증/행동 메서드에 둔다. validate_dependencies·require_text 같은 독립 업무 함수를 domain/application에 만들거나 정적 유틸리티 클래스로 감싸지 않는다. Task 의존 검증은 self.uid와 현재 정의/제안한 의존을 사용한다. 호출자가 별도 task_id로 검증 주체를 바꾸지 않는다. infrastructure의 자원 구성 함수와 Alembic upgrade/downgrade 진입점은 이 업무 규칙과 구분하며 이를 없애려고 DB/UoW 래퍼를 만들지 않는다. BEHAVIOR_OWNERSHIP 검사와 정상·실패 fixture를 공통 품질 검사에서 실행한다.
