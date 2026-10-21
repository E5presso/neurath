# 프로젝트·세션 기반

[구조](architecture.md) · [구현 계획](implementation-plan.md) · [English](../en/core-foundation.md)

#137은 사용자 단위 SQLite 안에서 프로젝트와 세션을 요청별로 관리합니다.
현재 의존성은 정식 Spakky 8.2.0 배포판을 사용합니다. 커밋 후 이벤트 발행·인프로세스 구성·요청 격리 수정이 포함된 이 버전으로 모든 직접 Spakky 의존성을 통일하며, `uv.lock`으로 배포 패키지를 고정합니다. 임시 Git 커밋이나 로컬 경로에는 의존하지 않습니다.
패키지는 비동기 기반과 훅 CLI를 제공합니다. 업무 CLI·설치 전환은 후속 구현 범위입니다.

## 프레임워크 사용과 책임

- `Project`, `HostSession`은 `@mutable`과 `AbstractAggregateRoot[str]`로 식별자·동일성·변경 추적을 상속합니다. `ProjectLocation`은 Project가 소유하는 `AbstractValueObject`입니다.
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
비동기 엔진의 `sync_engine` 이벤트에 연결합니다. 쓰기는 `BEGIN IMMEDIATE`, 읽기는 URI의
`mode=ro`와 `query_only`를 사용하고 모든 연결에서 외래 키를 강제합니다. 숨은 재시도는 없습니다.
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

명시적 초기화는 배포된 Alembic head까지 적용합니다. 현재 head는 `core_0005`입니다.
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
from spakky.core.pod.interfaces.container import IContainer
from neurath.application.usecases.get_session_context import GetSessionContextQuery, GetSessionContextUseCase


async def read_session(scope: IContainer, project_id: str, session_id: str):
    # scope는 neurath.bootstrap에서 구성한 애플리케이션의 컨테이너다.
    return await scope.get(GetSessionContextUseCase).run(
        GetSessionContextQuery(project_id, session_id)
    )
```

기본 경로는 `$XDG_DATA_HOME/neurath/core.sqlite3`이며 XDG가 없으면
`~/.local/share/neurath/core.sqlite3`입니다. 상대 XDG 경로는 거부합니다.

## 검증과 구현 경계

시험은 프레임워크 메서드 상속, 실제 registry·생성자 주입·aggregate 수집, 기본 CRUD·배치·삭제,
조회 격리, 변경 없는 저장, 오래된 저장·경합, 예외 정리, 소유권 충돌, 독립 프로세스,
Git/worktree/clone 구분과 명시적·동시 초기화를 검증합니다. 이전 스키마의 값·종속 자료 보존,
반복 이전, 이전 도중 실패의 전체 롤백도 확인합니다. 검사 실행 방법은 [기여 안내](../../CONTRIBUTING.ko.md)를 참고하세요.

훅 CLI의 실제 설치 연결, 기억·협업·업무 CLI·사용자 자료 이전은 후속 티켓입니다.
`setup`은 이 기반 후보의 설치를 거부합니다. 실제 사용자 DB와 설치된 배포본은 이번 소스
수정으로 변경하지 않습니다.

[태스크 원장](task-ledger.md)은 #140에서 추가한 원문·정정·시도·TODO의 구현 범위입니다.

`core_0005`는 [호스트 실행과 작성 임대](host-runtime.md)를 추가합니다.
