# Neurath 개발 지침

Neurath는 원문 출처와 미완료 작업을 보존하는 에이전트 하네스다.
현재 사용자 지시와 `docs/ko/specification.md`를 구현의 기준으로 삼는다.

- 코어는 hook·CLI 요청마다 사용자 단위 단일 SQLite의 상태를 조회해 처리하는 stateless service다. 프로젝트·세션은 DB 안에서 구분한다. 지속 상태를 상주 코어 메모리에 의존시키지 않는다.
- 설치된 rules가 기본 진입점이며 에이전트가 요청에 맞는 스킬을 선택한다. 사용자 지정 스킬은 그 지정을 따르고 단순 대화에는 강제하지 않는다. 선택한 스킬은 CLI로 시작하며 phase는 기존 runner가 관리한다.
- 태스크/TODO의 완료 여부는 종료 훅이 결정론적으로 검사한다. 사용자 의도 충족과 요청된 회고의 내용 평가는 별도 서브에이전트 또는 다른 provider에게 위탁한다. 결과 평가는 작업 묶음을 마무리하는 스킬의 phase로 관리하고 회고 제안·거절은 원래 작업 종료와 구분한다.
- 도메인 규칙은 `src/neurath/domain`, 유스케이스는 `application`, ORM 매핑·저장 구현·Alembic은 `infrastructure`에 둔다. QueryUseCase는 공식 매뉴얼대로 SQLAlchemy 세션과 매핑을 사용해 조회한다. CommandUseCase는 Repository·서비스의 추상 계약을 통해 작업하고 SQLAlchemy 세션·쿼리·ORM 모델에 직접 의존하지 않는다. 유스케이스 전용 Command/Query·Result DTO는 해당 유스케이스 모듈에 함께 정의한다. 모든 반환에 DTO를 강제하거나 공유 자료형·디렉터리 이름을 금지하지 않는다. 어댑터와 공통 구성요소는 실제 책임과 필요성으로 판단한다. 도메인은 외부 계층에 의존하지 않는다.
- 기존 데이터 이전은 `migration`의 명시적 보존 경계에서 수행한다. 원본 DB를 수정하거나 미완료 작업을 임의로 완료·취소하지 않는다.
- 새 설계는 Python + Typer 기반 `neurath` CLI 전용이며 MCP 서버나 어댑터를 제공하지 않는다. 릴리스 시 실제 CLI 정의에서 가이드 프롬프트를 생성하고 설치 시 관리 영역에 반영한다. 네이티브 호스트의 실행 권한과 사용자 승인을 하네스 기록으로 대체하지 않는다.
- `uv sync --locked`로 개발 환경을 준비하고 `uv run --locked python tools/check.py`로 필수 검사를 실행한다.
- 현재 `./setup`은 미완성 후보 설치를 거부한다. 소스 검사, 패키지 생성, 설치, 실제 호스트 호출을 구분해 보고한다.
- 설치는 관련 없는 사용자 설정·훅·지침을 보존하며, 변경 전에 복구 사본을 남긴다.
- 공개 문서는 `docs/en`과 `docs/ko`의 같은 상대 경로에 함께 작성한다. README와 CONTRIBUTING은 영어·한국어 쌍을 유지한다. 개인 경로와 검증 원문은 공개 문서나 패키지에 넣지 않는다.
- 코드·설치 수정은 승인된 로컬 작업이다. 공개 push·PR·배포는 사용자의 별도 요청 없이 수행하지 않는다.
- 도메인 aggregate, 명시적 ABC port, 개별 command/query use case, 구체 repository adapter와 declarative ORM 모델의 책임을 구분한다. Protocol은 사용하지 않고 명시적 상속·추상 계약을 사용한다. 참고 구조의 불필요한 중복 유스케이스 인터페이스나 ORM 수명 구현을 복제하지 않는다. 이름만으로 인터페이스·클래스의 필요성을 단정하지 않는다. 모든 유스케이스는 Spakky의 IAsyncCommandUseCase 또는 IAsyncQueryUseCase와 run 계약을 구현하고 입력은 AbstractCommand 또는 AbstractQuery를 상속한다. Spakky Framework 8.2.0의 AbstractAggregateRoot·AbstractValueObject·IAsyncGenericRepository·AbstractAsyncGenericRepository·AbstractMappableTable·Table·SchemaRegistry와 AsyncConnectionManager·AsyncSessionManager·AsyncTransaction을 사용한다. 현재 저장소의 기본 CRUD·배치는 프레임워크 구현을 재사용한다. Command가 작업 대상 Aggregate와 그 의존 범위를 읽는 계약은 Repository에 둔다. 기본 CRUD·배치는 그대로 재사용하며 추가 계약은 도메인 aggregate를 반환한다. 조회용 검색·목록·투영은 QueryUseCase가 SQLAlchemy로 처리하여 자신의 반환 계약을 구성한다. DB 유스케이스의 run은 공식 @transactional로 경계를 선언한다. 호출자는 컨테이너에서 받은 유스케이스를 직접 호출하며 외부에서 다시 트랜잭션을 감싸지 않는다. 메서드 이름·클래스 이름이나 contextmanager 문법 자체를 금지하지 않는다.
- 전체 현재 src와 tools에 strict Pyrefly·Google 형식 pydoclint·Ruff 검사를 적용한다. pre-commit과 CI는 tools/quality.py를 공유한다. 모듈 의미와 문서의 유용성은 별도 사람 검토 사항이다. 저장소는 조회·저장만 제공하며 위치 식별·승격·충돌 규칙은 Project aggregate가 소유한다. 엔티티는 가변 상태·동일성을 가지며 불변 관찰·명령·응답 값과 구분한다.
- 현재 후보는 #137의 프로젝트·세션 기반, #140의 원문·태스크 원장, #141의 단계 실행 및 #142의 호스트 런타임과 #143의 기억·enclave·재개 및 #144의 협업·provider 및 #145의 Newsroom 라이브러리·기사 CLI다. 이전 MCP runtime은 Git 기록에 있으며 새 패키지에는 포함하지 않는다. 훅 CLI는 spakky-typer로 제공한다. 나머지 업무 CLI·설치·기존 자료 변환은 후속 티켓이며 이 후보를 실설치하지 않는다.

- ProjectLocation은 Project.locations에 종속된 불변 값이다. 별도 위치 repository·DI·생명주기를 만들지 않는다. 물리적 자식 테이블은 선언형 ORM 관계로 매핑하고 프로젝트 저장 시 원자적으로 반영한다. 소유자 선택·승격은 도메인에 두고 repository에는 조회·저장 매핑만 둔다.
- repository는 신규·기존 엔티티를 모두 save(entity) -> entity로 저장한다. add/insert/create/update 저장 별칭을 만들지 않는다. 도메인의 create와 SQLAlchemy Session.add는 이 계약 명칭 규칙과 구분한다. 세션의 ORM 버전 검사·동일 값 no-op·분리된 오래된 엔티티 충돌을 보존한다.
- src·tools·tests 및 루트 Python 설정의 실제 docstring은 요약과 자연어 필드 설명까지 한국어로 작성한다. Google 섹션명과 코드·타입 식별자는 유지한다. 영문 오류 fixture는 의도된 테스트 데이터로만 둔다. tools/docstrings.py는 한국어 설명이 전혀 없는 문서 문자열을 찾는 최소 검사다. 한영 글자 비율·줄별 글자 수 기준을 만들지 않는다. 실제 설명 언어·번역 정확성과 aggregate 의미는 별도로 검토한다.
- 객체 선택은 None과 거짓 값의 의미가 드러나게 작성한다. 명시성을 요구한 지적을 or 연산자나 특정 표현식 전체의 금지로 바꾸지 않는다.

- 지원 Python 3.14 문법은 Ruff UP 규칙으로 검사한다. 호출한 하위 클래스 타입을 유지하는 classmethod 생성·변환 메서드는 Self를 사용한다. 구체 도메인 타입으로 변환하는 인스턴스 메서드의 반환 타입은 그대로 명시한다. 애플리케이션은 Spakky의 기본 load_plugins()와 패키지 scan()으로 구성한다. 개별 Pod·Table 수동 등록 목록이나 요청마다 컨테이너를 다시 조립하는 팩토리를 유지하지 않는다. 현재 상태를 보관하지 않는 유스케이스·저장소·CLI Controller는 기본 스코프를 사용한다. 객체 수명과 DB 세션 수명을 혼동해 CONTEXT를 일괄 지정하지 않는다. 비동기 엔진은 실제 명령을 실행한 이벤트 루프에서 정리한다.

- 도메인의 uid와 변경 메타데이터는 프레임워크 기반을 사용한다. 기존 id 참조와 정수 revision은 보존하며 ORM의 version_id_col은 정수 revision에 연결한다. UUID version은 도메인 변경 토큰으로 저장한다. SQLite 시각을 UTC로 왕복하되 변경 없는 저장이 UPDATE를 만들지 않게 매핑한다. core_0001은 수정하지 않고 core_0002로 기존 행과 외래 키를 보존한다. 이전 시각이 없으면 epoch를 미상 표식으로 저장하며 원래 생성 시각으로 해석하지 않는다.

- `tools/check.py`는 `src/neurath` 전체의 라인·분기 커버리지를 각각 100%로 강제한다. Alembic 동적 로드 파일도 소스 경로로 계측한다. 미실행 라인·분기 개수가 하나라도 있으면 실패하며 반올림한 비율로 통과하지 않는다. omit·커스텀 제외·pragma no cover/no branch로 기준을 우회하지 않는다. 커버리지 보고서는 coverage-out에 생성한다.

- 최종 커버리지 보고서의 excluded_lines도 0이어야 한다. 추상 포트의 기본 본문으로 잘못 위임한 어댑터는 명시적으로 실패하며 등록 트랜잭션을 롤백해야 한다.

- #140의 Task가 정의·의존·실행 시도·외부 대기 이력을 소유한다. 이 자식들에 별도 repository를 만들지 않는다. 상태 질문·과거 요약을 새 목표로 승격하지 않고 실제 정정은 지정한 작업·필드만 변경한다. 후보 제출은 성공이 아니며 오래된 개정의 결과는 보존하되 현재 요구를 닫지 않는다. TODO는 현재 전체 원장의 투영이며 별도 완료 권한이 아니다.

- 읽기 전용 목록 계약에는 collections.abc.Sequence를 사용한다. 현재 원문·태스크 조회 결과의 Sequence 계약을 회귀 시험으로 확인한다. 내부 저장·정확한 tuple 형식 등 다른 목적의 타입 표기까지 금지하지 않는다. Sequence 자체가 실행 시 불변성을 보장하지는 않으며 소유 이력의 저장 구현에는 tuple snapshot을 사용할 수 있다. 고정된 이종 쌍의 tuple과 구분한다.
- 스키마 revision은 Alembic migration 파일과 version table만 관리한다. 일반 요청은 MigrationContext의 현재 heads와 ScriptDirectory의 배포 heads로 호환성을 확인하며 별도 최신 revision 상수를 유지하지 않는다. 일반 요청에서 자동 이전하지 않는다.

- 유스케이스 전용 결과 DTO는 입력 DTO와 마찬가지로 해당 유스케이스의 계약이며 같은 모듈에 정의한다. 결과 타입의 이름·접미사를 고정하거나 모든 반환에 별도 DTO를 요구하지 않는다. 반환할 데이터만 담고 상태 전이·의존 판단은 도메인, 조회 결과 구성은 해당 유스케이스가 담당한다. CLI·훅은 실제 호출자로서 출력 형식 변환을 담당한다. DTO 명칭이나 위치 변경만으로 책임 문제가 해결됐다고 판단하지 않는다.
- 리뷰 지적은 해당 줄뿐 아니라 같은 책임 문제가 있는 곳을 함께 조사한다. 반복 가능한 구체 요구는 정상/실패 회귀 시험으로, 의미적 책임 판단은 검토 기준으로 반영한다. 실제 등록된 Spakky 구성요소·현재 저장소와 입력/결과 계약·요청 수명·Alembic 이전 동작을 공통 pre-commit/CI에서 확인한다. 책임 없는 중계 계층을 지적한 것을 특정 경로명 금지로 바꾸지 않는다. 구문 검사가 의미적 책임까지 입증한다고 주장하지 않는다.
- 사용자 응대와 PR 답글은 한국어 존댓말로 작성한다. 자신을 가리킬 때는 저·제가·제 표현을 사용한다. 설명이 잘못됐으면 잘못된 판단을 명확히 정정하고 요청 범위를 바꾸지 않는다.

- 도메인 규칙은 그 상태와 의미를 소유하는 aggregate·값 객체에 배치하고 유스케이스는 요청의 조회·호출·저장을 조정한다. Task 의존 규칙과 텍스트 검증의 책임 배치는 구체적인 동작·호출 흐름으로 검토한다. 함수·정적 메서드·raise 문이나 예외 타입의 존재만으로 책임 위반을 판정하지 않는다. 유스케이스도 필요에 따라 도메인 예외를 발생·전파·변환할 수 있다. 의존 순환·범위·정정 보존·원자성 같은 구체적인 요구는 동작 회귀 시험으로 확인한다.
- 리뷰 지적을 하네스에 반영할 때 지적된 책임·동작과 기계 검사가 실제로 확인하는 내용을 구분한다. 사례를 일반화한 새 금지 규칙을 임의로 추가하지 않는다. AST·타입·동작 시험이 증명하지 못하는 의미적 판단은 검토 기준으로 명시한다.
- 유스케이스·서비스와 기존 코드의 조건 분기는 guard clause와 early return을 적극 사용한다. 오류·대상 외·무변경 경로를 먼저 raise·return·continue·break로 끝내고 정상 흐름을 얕게 유지한다. 검증 순서, 저장·알림의 조건, 트랜잭션과 finally의 정리 동작은 보존한다. 메서드를 분리할 때는 같은 책임 안의 의미 있는 작업으로 나누며 중첩을 감추려고 도메인 로직을 밖으로 옮기지 않는다.
- 공통 Ruff 검사에 RET505·RET506·RET507·RET508을 적용하여 종료 분기 뒤의 불필요한 else를 검출한다. 그 밖의 중첩은 실제 제어 흐름을 검토해 단순화하며, 임의의 깊이 상한이나 모든 if·else의 금지로 확대하지 않는다.

- #142의 Execution은 실제 호스트 턴과 중단 상태를, Writer는 공유 작업 폴더의 작성 소유자·세대를 관리한다. 읽기·진단·자식 조회에 작성 임대를 요구하지 않는다. Stop의 최신 TODO·phase 판정과 반복 거절 중지를 함께 검증한다. 새 사용자 턴·연결 재개만으로 취소를 해제하지 않으며 실제 재개 지시는 ResumeExecutionUseCase로 처리한다. 작성 회수는 실제 종료 관찰 뒤 같은 소유자·세대를 재검사하며, 훅 응답 생성과 실제 설치·알림 수신을 구분한다.

- 제품 코드의 서비스 이름은 Service, 저장소 이름은 Repository로 끝낸다. 인터페이스는 I를 접두어로 사용하고 구현체는 그 I를 실제 기술 스택 이름으로 대체한다. 예: IDirectoryObserverService → GitDirectoryObserverService, IPhaseExecutorService → SubprocessPhaseExecutorService, IProjectRepository → SQLAlchemyProjectRepository. import·DI 등록·타입 표기·문서도 같은 이름을 사용하며 이전 이름의 호환 별칭을 남기지 않는다. tools/architecture.py가 전체 소스의 포트·등록·별칭·간접 상속을 추적해 명명 위반을 실패시키고, 이 검사는 공통 pre-commit·필수 CI에서 실행된다. 현재 기술 접두어는 Git·Subprocess·Stderr·Posix·SQLAlchemy이며 새 기술 구현을 도입할 때 그 접두어와 회귀 시험을 함께 반영한다.

- 유스케이스는 UseCase 접미사만 강제한다. 서비스·저장소의 기술 접두어 규칙을 유스케이스에 확대 적용하거나 명명을 위해 유스케이스별 인터페이스를 새로 만들지 않는다. 기존 Spakky IAsyncCommandUseCase·IAsyncQueryUseCase 계약을 유지하며, 공통 구조 검사는 데코레이터·직접 및 간접 상속으로 유스케이스를 찾아 접미사 누락을 거절한다.

- SQLite 접근은 aiosqlite와 Spakky IAsyncGenericRepository·AbstractAsyncGenericRepository·AsyncSessionManager·AsyncTransaction을 사용한다. DB 유스케이스와 Typer 훅 명령은 async def로 선언하고 호출을 await한다. Alembic은 async connection.run_sync로 실행한다. 관계 매핑은 비동기 조회 안에서 selectin으로 적재하여 암묵적 lazy SQL을 만들지 않는다. CLI 입출력은 transport, 외부 기술 구현은 infrastructure, 의존성 조립은 구성 루트가 담당한다. 실제 컨테이너에서 직접 호출한 유스케이스의 커밋·롤백, 동일 앱의 반복 CLI와 요청 격리, 실행·정리 이벤트 루프, scan 발견과 await 누락을 회귀 시험으로 확인한다.

- Spakky 사용법은 https://framework.spakky.com/ 의 해당 매뉴얼을 직접 읽고 설치한 버전의 실제 API와 함께 확인한다. Domain Event는 aggregate.add_event → Repository.save → @transactional 커밋 → @EventHandler/@on_event 경로로 후속 작업을 연결한다. 후속 유스케이스는 새 트랜잭션으로 실행하며 중첩 트랜잭션이나 자체 이벤트 디스패처를 도입하지 않는다. 원자적으로 끝나야 하는 한 작업은 하나의 유스케이스가 담당한다. 이벤트 핸들러 실패가 로그로 격리되는 동작을 고려하여 예약 응답을 후속 작업 완료로 해석하지 않고 DB의 실제 결과를 확인한다.
- @immutable은 값 객체의 필드 재할당을 막고 Sequence는 읽기 전용 목록 계약을 표현한다. 깊은 불변성을 별도 요구로 확대하지 않으며, 모든 입력의 tuple 변환이나 object.__setattr__를 이용한 강제 할당을 추가하지 않는다. 기존에 저장·정렬을 위해 필요한 tuple 사용과는 구분한다.

- EventHandler는 transport의 인바운드 어댑터다. 이벤트를 Command/Query로 변환해 주입받은 유스케이스를 호출한다. 실행·관찰·복구·예외 처리·알림 로직과 그 서비스 의존성은 담당 유스케이스에 둔다. 외부 작업만 수행하는 유스케이스에는 DB 트랜잭션을 열지 않으며, 관찰 결과는 표준 이벤트 발행자로 후속 저장 유스케이스에 전달한다. DB 결과 저장이 실패하면 그 결과에 대한 알림 사건도 발행하지 않는다.
- 공통 구조 검사는 CommandUseCase의 ORM 직접 참조와 이벤트 어댑터의 작업 서비스 주입을 실제 계약·별칭·상속으로 검사한다. QueryUseCase의 SQLAlchemy 조회는 허용한다. 임의의 클래스 이름이나 모든 함수·예외 문법의 금지로 책임 규칙을 확장하지 않는다.

- 저장소의 추가 조회 계약은 find_by_project_id·find_by_resource처럼 조회 조건을 드러내는 find_by_<조건> 이름을 사용한다. 복합 조건은 _and_로 연결하며 포트·구현·호출자가 같은 이름을 쓴다. 프레임워크에서 상속하는 CRUD 메서드는 그대로 재사용한다.
- 지원 훅 사건은 HookEvent로 표현하고 네이티브 문자열은 transport에서 Enum으로 변환한다. 외부 입력의 임의 문자열까지 모두 Enum으로 만들지 않는다.
- Typer 실행 진입점은 공식 가이드처럼 스캔·시작한 애플리케이션에서 가져온 모듈 전역 cli 객체를 노출한다. 설치된 console script는 해당 객체를 호출하며 비동기 연결 정리는 명령의 이벤트 루프에서 수행한다.

- #143의 enclave는 현재 맥락이며 Memory의 과거 기록·체크포인트와 구분한다. 기대 개정은 저장소의 낙관적 revision으로, 여러 변경의 이력은 aggregate 안의 순번으로 관리한다. 삭제 기록과 원문은 남기되 복원은 최신 현재 항목만 사용한다. 미리보기는 소유권을 바꾸지 않으며 실제 인수는 원 실행 종료·작성 해제·후속 턴을 확인한다. 인수된 원 세션은 다시 쓰기를 시작하지 못한다.
- 압축 후 복원은 실제 SessionStart/compact 입력과 additionalContext 계약을 사용한다. CLI stdout 생성, 호스트 훅 호출, 다음 모델 입력·응답에서의 실제 전달을 구분해 검증한다. 호스트 한도를 넘는 맥락을 조용히 잘라 성공으로 보고하지 않는다. Graphify는 기존 CLI를 사용하고 문서 의미 관계가 유실된 갱신을 거절하여 원 그래프를 복원한다.

- CLI 컨트롤러는 실제 작업 책임에 따라 나눈다. 기억 조회·검색·보고 저장·현재 맥락 갱신은 MemoryCliController의 `memory read/search/checkpoint/update`, 세션 인수 미리보기·실행 재개는 SessionCliController의 `session preview/resume`에 둔다. 기억에 연결된 정보라는 이유로 세션 작업까지 memory 컨트롤러에 넣거나 옵션으로 우회 노출하지 않는다. 기존 다른 컨트롤러의 역할까지 일괄 금지 규칙으로 확대하지 않는다.
- `tests/test_cli.py`에서 실제 스캔·DI로 등록된 memory/session 명령의 소속과 해당 유스케이스 주입 경계를 함께 검사한다. 루트에 펼쳐진 명령이나 memory의 세션 작업 노출은 실패해야 한다. 이 시험은 공통 tools/quality.py를 통해 pre-commit·CI에서 실행하며, 새로운 명령의 의미적 책임은 코드 리뷰에서도 확인한다.

- 외부 변경을 포함하는 요청은 입력·범위 검증을 먼저 수행한다. 그 요청에 필요한 선행 저장이 있으면 커밋이 끝난 뒤 외부 작업을 시작하며, 필요 없는 사전 기록을 새로 만들도록 강제하지 않는다. 체크포인트는 SaveCheckpointUseCase에서 검증·저장하고, 커밋 후 표준 도메인 이벤트로 Graphify 갱신 및 결과 기록을 이어간다. 외부 작업 중 DB 트랜잭션을 유지하거나 컨트롤러가 갱신·저장 순서를 조율하지 않는다. 독립적인 조회·응답 구성을 포함한 모든 유스케이스 복수 호출을 일괄 금지하지 않는다.
- tests/test_checkpoint_graph.py를 공통 pre-commit·CI에 포함한다. 무효 입력·다른 소유 범위·stdin 실패·커밋 실패에서 외부 호출과 파일 변경이 없는지, 정상 경로가 커밋 이후 잠금 없이 실행되는지 확인한다. 외부 실패는 failed, 결과 미기록은 pending으로 보존하며 CLI는 비성공 종료 코드와 보고 ID·상태를 반환한다. 기록되지 않은 결과를 성공으로 추정하거나 자동 재실행하지 않는다.


- #144의 피어는 관찰한 호스트 세션·네이티브 자식 주소로 연결한다. 전달·본문 읽음·ACK·배정 수락·실제 수행·원 태스크의 성공을 구분한다. 기존 지시 범위의 수신·검토에는 새 인간 입력이나 부모 작업 폴더 작성 임대를 요구하지 않는다. 배정의 원 출처·정정 이력·역할·근거를 보존하며 조회는 재전송이나 새 실행을 만들지 않는다.
- 정정·취소는 해당 태스크의 배정에만 전파한다. 수락한 배정은 수신자의 현재 실행 범위로 연결하고, 늦은 옛 결과로 현재 요구를 완료하지 않는다. 미확인 전달·중단은 미확인으로 보고한다. 새로운 모델 실행은 명시한 경로·실제 지원 모델·정책으로 시작하며 워크트리나 연결 재개를 이유로 새 세션을 만들지 않는다.
- provider 모델 조회는 추론 프롬프트를 보내지 않으며 사용자 훅을 실행하지 않는 조회 경로를 사용한다. 외부 실행은 검증·선행 저장 커밋 후 시작하고 DB 쓰기 잠금을 유지하지 않는다. 중복 배정·실행 전 취소·실행 중 취소·PID 재사용·유실 결과를 같은 실행 ID로 검증한다. tests/test_collaboration.py와 tests/test_provider.py를 공통 품질 검사에 포함하며 fixture와 실제 설치된 공급자의 관찰 근거를 구분한다.


- 불변 Command·Query·Result·관찰 DTO는 Spakky `@immutable`을 사용하고 키워드 인자로 생성한다. `@dataclass(frozen=True)` 관습을 새 계약에 남기지 않는다. 필드 재할당 금지와 깊은 불변성·값 동등성은 다른 요구다. 기존 도메인 값 객체의 비교 의미는 유지하고, DTO 비교가 필요한 시험은 확인할 필드 값을 명시한다.
- Neurath가 생성하는 내부 aggregate 기본 키와 그 참조는 Python `UUID`로 전달하고 `next_id()`는 `uuid7()`을 반환한다. ORM은 SQLAlchemy의 `Uuid()`를 사용하며 기존 문자열 스키마는 별도 Alembic revision에서 식별자·외래 키·이력·트리거를 보존해 이전한다. 내장 타입을 피하기 위한 자체 UUID TypeDecorator를 만들지 않는다. 외부 호스트 세션·턴·도구 호출 ID, 원문 위치·관찰 참조는 원래 계약을 유지한다. 기존 UUID4 키를 재발급하지 않는다. JSON·CLI·프로세스 인자는 명시적인 문자열 경계다. 프레임워크 version 토큰·파일 백업명까지 UUID4 금지로 확대하지 않는다.
- 긴 실행 흐름은 진입 메서드에서 주요 단계와 오류·무변경 경로가 읽히도록 정리한다. 배정 상태·범위·중복 판단은 도메인이 소유하고 유스케이스는 조회·호출·저장을 조정한다. 호스트 프로토콜의 프레이밍·응답 해석과 프로세스 수명·결과 관찰은 구분한다. 메서드 길이·개수나 모든 조건문에 임의의 금지 규칙을 만들지 않는다.
- 지원 provider 선택에는 공통 `ProviderKind`, 실행 관찰에는 `ProviderStatus`를 사용한다. 공급자별 CLI 인자·초기화·응답 처리는 `match`의 명시적인 분기로 표현하며 미지원 값을 Claude 경로 등으로 암묵 대체하지 않는다. 자유 형식의 외부 식별자까지 일괄 Enum으로 바꾸지 않는다.
- `tools/architecture.py`는 별칭을 포함한 frozen dataclass 선언을 검사하며 `tests/test_review_contracts.py`는 전체 내부 키의 UUID7 생성, 불변 계약의 키워드 생성, 기존 UUID4·외래 키 보존, 미지원 provider 거절을 확인한다. 가독성과 책임 분리 자체를 구문 검사로 증명했다고 주장하지 않는다.
- 생성자·함수 인자로 한 번 전달하는 단순 값은 인라인으로 작성한다. 위임 메시지·실행 프롬프트처럼 여러 줄의 고정 서식은 triple quote로 줄 구조를 드러내며 반복되는 `\n` 이스케이프의 긴 문자열로 작성하지 않는다. 여러 항목을 합치는 `"\n".join(...)`, 재사용·검증·부작용 순서·복잡한 계산을 설명하는 변수까지 기계적으로 금지하지 않는다. 본문 원문·정정 순서와 실제 전달 내용은 회귀 시험으로 확인한다.

- #145의 Article은 원문 개정·댓글·열람·실제 작업 사용·발행 당시 알림을 소유한다. 목록과 제목 알림은 seen이 아니며 CLI는 전체 stdout 출력이 반환된 뒤 내부 receipt 유스케이스로 선택 개정만 기록한다. 정정 영향은 실제 사용한 작업·요구 개정에 연결해 기사와 태스크 상세 조회에 표시하며 동의·댓글을 작업 성공으로 쓰지 않는다. 구독 해제와 비활성 관찰은 미제출 기사 알림을 폐기하고 재접속·재구독으로 옛 뉴스를 재생하지 않는다. tests/test_newsroom.py는 공통 pre-commit·CI에서 출력·입력·커밋 실패, 개정 충돌, 실제 사용 작업 영향, 선택 개정 열람과 보존형 migration을 검사한다. CLI stdout·훅 응답과 실제 호스트 수신·모델 전달은 구분한다.
