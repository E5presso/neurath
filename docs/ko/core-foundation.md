# 프로젝트·세션 기반

[구조](architecture.md) · [구현 계획](implementation-plan.md) · [English](../en/core-foundation.md)

#137은 사용자 단위 SQLite 안에서 프로젝트와 세션을 요청별로 관리합니다.
현재 의존성은 정식 Spakky 8.2.0 배포판을 사용합니다. 커밋 후 이벤트 발행·인프로세스 구성·요청 격리 수정이 포함된 이 버전으로 모든 직접 Spakky 의존성을 통일하며, `uv.lock`으로 배포 패키지를 고정합니다. 임시 Git 커밋이나 로컬 경로에는 의존하지 않습니다.
패키지는 비동기 코어와 업무 CLI·스킬·rules·훅 설치 경로를 제공합니다. 실제 사용자 저장소 전환과 네이티브 활성화는 별도 근거로 확인합니다.

## 프레임워크 사용과 책임

- `Project`, `HostSession`은 `@mutable`과 `AbstractAggregateRoot[UUID]`로 식별자·동일성·변경 추적을 상속합니다. `ProjectLocation`은 Project가 소유하는 `AbstractValueObject`입니다.
- 기존 `id` 참조는 `uid`를 읽는 호환 속성으로 유지합니다. 프로젝트 식별·폴더 승격·위치 충돌과 세션 범위·이동 규칙은 도메인에 있습니다.
- 저장 포트는 `IAsyncGenericRepository`의 기본 Aggregate CRUD 계약을 사용합니다. Command가 위치·네이티브 ID로 작업 대상 Aggregate를 읽는 계약은 저장소가 구현합니다. CommandUseCase에는 SQLAlchemy 세션·쿼리·ORM 모델을 주입하지 않습니다.
- `SQLAlchemyProjectRepository`, `SQLAlchemySessionRepository`는 `AbstractAsyncGenericRepository`를 상속합니다. `get`, `get_or_none`, `contains`, `range`, `save`, `save_all`, `delete`, `delete_all`과 생성자는 재구현하지 않습니다.
- 도메인 테이블은 `@Table(Domain)`과 `AbstractMappableTable[Domain]`으로 양방향 변환을 정의합니다. 위치 자식 테이블은 도메인 매핑이 없는 `AbstractTable`입니다.
- `SchemaRegistry`가 Table 태그를 통해 도메인과 실제 테이블을 연결합니다. 저장소가 매핑을 별도로 추적하지 않습니다.
- `ApplicationContext`가 `@UseCase`, `@Repository`, 관찰 Pod와 프레임워크의 `AsyncConnectionManager`, `AsyncSessionManager`, `AsyncTransaction`, `AggregateCollector`를 구성합니다.
- 호출자는 컨테이너에서 주입된 유스케이스의 `run(command/query)`를 직접 호출합니다. 공식 `@transactional`이 성공 시 commit, 실패 시 rollback과 세션 종료를 담당합니다.
- 모든 유스케이스는 Spakky의 `IAsyncCommandUseCase` 또는 `IAsyncQueryUseCase`를 구현하며 입력은 `AbstractCommand` 또는 `AbstractQuery`를 상속합니다. 전용 Command/Query·Result DTO는 해당 UseCase 모듈에 정의합니다. 기존 도메인 타입을 반환할 때는 별도 DTO를 강제하지 않습니다.
- 프레임워크의 미존재·저장 버전 충돌 오류는 해당 기본 계약으로 전파합니다. 세션이 요청한 프로젝트에 속하는지는 유스케이스가 도메인에 확인합니다.

기본 CRUD의 SQL과 merge·flush·변경 aggregate 수집은 프레임워크 소유입니다.
명령의 Aggregate 조회는 저장소에, 조회 결과용 SQLAlchemy 검색은 QueryUseCase에 있습니다. 도메인은 프레임워크의
순수 도메인 기반과 mutability 선언만 사용하며 SQLAlchemy와 저장 어댑터에 의존하지 않습니다.

## 요청 수명과 SQLite

CLI 프로세스는 `SpakkyApplication.load_plugins().scan(...).start()`로 구성합니다.
설치된 플러그인을 기본 로딩하고, 패키지 스캔으로 Pod·Table·Controller를 발견합니다.
Alembic 실행 파일과 구성 루트는 스캔 대상에서 제외합니다. 상태를 보관하지 않는 유스케이스·저장소·CLI Controller는 기본 스코프를 사용합니다.
DB 세션은 현재 요청 컨텍스트와 `@transactional` 경계로 구분합니다.

SQLite는 `sqlite+aiosqlite`와 `AsyncSessionManager`·`AsyncTransaction`으로 접근합니다.
유스케이스·저장소 호출은 `await`하고, 소유 관계는 `selectin`으로 조회하여 변환 중 암묵적
동기 조회를 발생시키지 않습니다. 마이그레이션은 비동기 연결의 `run_sync`로 Alembic을 실행합니다.
세션·트랜잭션은 Spakky 구현이 정리합니다. CLI는 명령을 실행한 이벤트 루프가 닫히기 전에 비동기 엔진을 dispose합니다.

Git 관찰은 DB 트랜잭션 전에 끝냅니다. SQLite 연결 정책은 구성 루트가
비동기 엔진의 `sync_engine` 이벤트에 연결합니다. 일반 요청은 `BEGIN`으로 지연 시작하고 순수 읽기는 URI의 `mode=ro`와 `query_only`도 사용할 수 있습니다. 명시적 스키마 이전만 `BEGIN IMMEDIATE`로 직렬화하며 일반 연결은 외래 키를 강제합니다. 롤백된 세션 등록·훅 DB 경합만 유한하게 재조회하며 외부 작업을 무조건 재실행하지 않습니다.
프레임워크 저장소의 부재·낙관적 충돌 오류는 그대로 전파하며 CLI 경계에서 호스트 응답으로 표현합니다.

네이티브 ID는 `(project_id, provider, host_session_id)`로 구분합니다. 재등록은 최신 작업
경로를 덮어쓰지 않습니다. linked worktree와 하위 폴더는 같은 프로젝트이며 같은 원격의
독립 clone은 구분합니다. 일반 폴더가 Git 저장소가 되어도 기존 ID·위치·종속 외래 키를
보존합니다. 서로 다른 프로젝트의 기록을 임의로 합치지 않습니다.

## 매핑·버전·소유권

프레임워크의 UUID `version`과 `created_at`·`updated_at`을 저장합니다. UUID는 도메인
변경 토큰이며, 기존 요청의 정수 `revision`을 대체하지 않습니다. SQLAlchemy의
`version_id_col`은 정수 revision에 연결하여 오래된 detached 저장과 실제 flush 경합을
거부합니다. 프로젝트에도 저장소용 정수 revision을 추가합니다.

결과 DTO는 데이터 전달 계약이며 조회 결과 구성은 유스케이스가 담당합니다. DTO 필드의 재대입을 막는 frozen 선언과 내부 도메인 객체의 가변성은 구분합니다. 반환된 도메인 객체는 ORM 수명과 독립적이며 요청 밖에서 객체를 바꿔도 DB에 저장되지 않습니다. 시각은 UTC로
왕복합니다. SQLite의 시각 저장 형태와 도메인 UTC 시각을 명시적으로 변환하여 같은 값을
재저장할 때 시각 표현 차이로 UPDATE가 발생하지 않게 합니다. 같은 경로 이동과 같은
위치 재연결은 변경 토큰·수정 시각·정수 revision을 증가시키지 않습니다.

Project 저장은 소유한 위치 관계까지 기본 merge로 반영합니다. 삭제한 위치는 orphan으로
정리합니다. 다른 Project의 위치를 generic merge가 재할당하지 못하도록 SQLite trigger가
소유자 변경을 거부합니다. 실패한 요청은 부모·자식 변경을 함께 롤백합니다.

## 스키마와 보존

명시적 초기화는 배포된 Alembic head까지 적용합니다. 현재 head는 `core_0014`입니다.
`core_0002`는 메타데이터·프로젝트 revision·위치 소유 제약을, `core_0003`는
[원문·태스크 원장](task-ledger.md)을 추가합니다. `core_0004`는 [단계 실행](workflow-runner.md)의 정의·시도 이력을 추가합니다. 적용된 이전 revision은 수정하지 않으며
기존 ID·세션 revision·프로젝트·위치·세션 데이터와 종속 외래 키를 유지합니다.

기존 행에는 원래 시각이 없으므로 epoch를 **미상 표식**으로 저장합니다. 이 값을 실제
생성 시각으로 해석하지 않습니다. 기존 행의 변경 토큰은 초기 표식인 zero UUID이며,
도메인 변경 후 프레임워크가 새 토큰을 생성합니다. 새 aggregate는 실제 생성 시각과
토큰을 사용합니다. 이전 기록을 새 권한·성공 근거로 만들지 않습니다.

Alembic migration 파일과 version table이 revision의 유일한 기준입니다. 별도 최신 revision 상수 없이 `MigrationContext.get_current_heads()`와 `ScriptDirectory.get_heads()`로 호환성을 검사합니다. 일반 요청의 첫 DB 트랜잭션에서 검사하며 스키마를 바꾸지 않고 이전·미래 revision을 거부합니다. `initialize_database`
명령 경계에서만 마이그레이션을 수행합니다. 전체 과정이 실패하면 스키마·행·revision이
함께 롤백됩니다. legacy DB는 별도 자료 이전 없이 초기화하지 않습니다.

## 내부 요청 API

```python
from uuid import UUID
from spakky.core.pod.interfaces.container import IContainer
from neurath.application.usecases.get_session_context import GetSessionContextQuery, GetSessionContextUseCase


async def read_session(scope: IContainer, project_id: UUID, session_id: UUID):
    # scope는 neurath.bootstrap에서 구성한 애플리케이션의 컨테이너다.
    return await scope.get(GetSessionContextUseCase).run(
        GetSessionContextQuery(project_id=project_id, session_id=session_id)
    )
```

기본 경로는 `$XDG_DATA_HOME/neurath/core.sqlite3`이며 XDG가 없으면
`~/.local/share/neurath/core.sqlite3`입니다. 상대 XDG 경로는 거부합니다.

## 검증과 구현 경계

시험은 프레임워크 메서드 상속, 실제 registry·생성자 주입·aggregate 수집, 기본 CRUD·배치·삭제,
조회 격리, 변경 없는 저장, 오래된 저장·경합, 예외 정리, 소유권 충돌, 독립 프로세스,
Git/worktree/clone 구분과 명시적·동시 초기화를 검증합니다. 이전 스키마의 값·종속 자료 보존,
반복 이전, 이전 도중 실패의 전체 롤백도 확인합니다. 검사 실행 방법은 [기여 안내](../../CONTRIBUTING.ko.md)를 참고하세요.

기억·인수·업무 CLI·스킬·rules·설치는 같은 요청 흐름으로 연결합니다. `maintenance install`은 현재 저장소와 소유 설정을 보존하며 설치합니다. 과거 하네스의 다른 DB 형식 변환은 별도 이전 범위이며 원본을 수정하지 않습니다. 소스 수정이나 설치 파일 생성만으로 실제 호스트 활성화를 주장하지 않습니다.

[태스크 원장](task-ledger.md)은 #140에서 추가한 원문·정정·시도·TODO의 구현 범위입니다.

`core_0005`는 [호스트 실행과 작성 임대](host-runtime.md)를 추가합니다.

추가 Aggregate 조회명은 `find_by_<조건>`으로 조건을 드러냅니다. 프로젝트 소유 위치의 `lazy="selectin"`은 지연 로딩이 아닌 select-in eager loading입니다. 현재 회귀 시험은 프로젝트 3개와 위치를 부모 SELECT 1회·자식 IN SELECT 1회로 적재하고 추가 접근 시 SQL이 발생하지 않음을 확인합니다. 컬렉션 joined loading에는 `Result.unique()`가 필요하지만 Spakky 8.2.0 기본 저장소의 get/range는 이를 적용하지 않습니다. 기본 CRUD를 재구현하지 않고 select-in 방식을 유지합니다.

## 식별자와 불변 입력 계약

내부 aggregate ID와 관련 Command·Query·저장소 참조는 `UUID`로 전달하고 새 ID는 시간 순서로 정렬되는 `uuid7()`로 생성합니다. ORM은 SQLAlchemy의 `Uuid()`를 사용합니다. `core_0009`는 기존 UUID4·UUID7 값과 참조를 재발급하지 않고 SQLite의 키 저장 표현을 32자리 hex로 이전합니다. 관계형 참조·복합 제약·인덱스·트리거와 미완료 이력을 보존하며, 이전 전후 외래 키 검사에 실패하면 자료·스키마·revision을 함께 롤백합니다. 외부 호스트 ID와 JSON·원문·산출물 참조는 원래 문자열을 유지하며, JSON·CLI 경계에서 내부 UUID를 정규 문자열로 표현합니다.

불변 입력·결과·관찰 계약은 Spakky `@immutable`과 키워드 인자를 사용합니다. 필드 재할당을 막는 계약이며 내부 목록까지 깊게 동결하는 계약은 아닙니다. 도메인 값 객체의 동등성은 해당 프레임워크 계약을 유지합니다.

## 패키지와 모듈 책임

[Ports and Adapters 원문](https://alistair.cockburn.us/hexagonal-architecture/)은 외부 기술과 애플리케이션 내부의 경계를 정의하며 고정된 디렉터리 이름을 요구하지 않습니다. Neurath는 이 경계를 다음 패키지 규칙으로 구체화합니다.

| 패키지 | 소유 책임 |
| --- | --- |
| `domain/aggregates`, `values`, `enums`, `events` | 식별자와 상태 전이, 값과 검증, 상태 구분, 커밋된 도메인 사건 |
| `application/usecases` | 모듈당 한 작업과 그 작업의 전용 Command/Query·Result |
| `application/ports/repositories`, `services` | 저장·외부 실행·공통 업무 서비스의 추상 계약. 응답 자료형은 해당 포트와 같은 모듈 |
| `infrastructure/models`, `repositories`, `services`, `migrations` | ORM, 저장소 구현, 외부 기술 어댑터, Alembic revision |
| `transport/cli`, `events` | CLI와 커밋 후 사건을 유스케이스 입력으로 바꾸는 인바운드 어댑터 |

구성 루트·SQLite 설정·외부 프로토콜·JSON 직렬화는 그 기술 경계의 모듈로 유지합니다. 도메인 값은 소유 aggregate와 함께 둘 수도 있습니다. 여러 역할을 가진 records 묶음을 `application` 바로 아래에 두지 않습니다.

`tools/architecture.py`는 새 파일까지 탐색해 프레임워크 구성요소의 소속, 모듈당 한 유스케이스와 선언 참조 그래프의 연결성을 검사합니다. 연결된 입출력·유스케이스, aggregate·소유 값, 부모·자식 매핑은 함께 둡니다. 공통 import·외부 기반 타입·데코레이터나 docstring의 문자열 언급은 연결로 인정하지 않으며, 지역 변수의 같은 이름도 전역 참조로 오인하지 않습니다. Alembic의 upgrade/downgrade는 한 revision의 콜백 계약입니다. 정상·실패 fixture와 실제 패키지 스캔 시험을 pre-commit·CI에 공유합니다. 그래프 연결은 기계적으로 확인할 수 있는 최소 조건이며 실제 책임의 타당성은 코드 검토로 확인합니다.

## 서비스 계약과 도메인 상속

공통 업무 서비스는 `application/ports/services`의 ABC 인터페이스와 이를 상속하는 `infrastructure/services` 어댑터로 구성합니다. 어댑터는 [공식 DI 가이드](https://framework.spakky.com/guides/dependency-injection/)의 `@Pod`와 패키지 스캔으로 등록하고 유스케이스에 인터페이스를 생성자 주입합니다. 자유 함수를 서비스 폴더에 옮기는 것은 이 구조를 충족하지 않습니다. 순수 변환·프로토콜·구성 함수의 형태 자체를 금지하지는 않습니다.

감시 컨텍스트의 공통 대조는 `IMonitorContextService.load` 계약과 `SQLAlchemyMonitorContextService` 구현으로 제공합니다. 구현체는 기존 SQLAlchemy 저장소의 `get`을 재사용하고 소유권·실행 상태 판단을 도메인에 요청합니다. 호출 유스케이스의 트랜잭션 안에서 동작하며, 별도 트랜잭션·커밋·외부 관찰을 만들지 않습니다. 대조 결과를 반영한 Task의 최종 저장도 유스케이스가 담당합니다.

[공식 도메인 모델링 가이드](https://framework.spakky.com/guides/domain-modeling/)에 따라 도메인 값은 `AbstractValueObject`, aggregate는 `AbstractAggregateRoot`, 도메인 사건은 `AbstractDomainEvent`를 상속합니다. `@immutable`은 필드 재대입을 막는 선언이며 값 객체 기반 클래스의 동등성·hash·clone·생성 시 validate 호출을 대신하지 않습니다. Enum·예외·애플리케이션 DTO·포트 응답은 각자의 역할을 유지합니다.

공통 검사는 값 객체·aggregate·사건의 상속 누락, 서비스 어댑터의 인터페이스 누락, 저장소·서비스 의존 공통 함수를 유스케이스가 직접 호출하는 우회를 검출합니다. 실제 도메인 선언 전체의 기반 클래스와 모든 서비스 포트·구현체의 스캔 등록·DI 연결도 시험합니다. 상속한 클래스만 미리 골라 누락된 선언을 검사에서 제외하지 않습니다.
