# 프로젝트·세션 기반

[구조](architecture.md) · [구현 계획](implementation-plan.md) · [English](../en/core-foundation.md)

#137은 사용자 단위 SQLite 안에서 프로젝트와 세션을 요청별로 관리합니다.
현재 기반은 Spakky Framework 8.1.0의 도메인·영속성 구성요소를 사용합니다.
패키지는 기반 라이브러리이며 공개 CLI·훅·설치 전환은 후속 구현 범위입니다.

## 프레임워크 사용과 책임

- `Project`, `HostSession`은 `@mutable`과 `AbstractAggregateRoot[str]`로 식별자·동일성·변경 추적을 상속합니다. `ProjectLocation`은 Project가 소유하는 `AbstractValueObject`입니다.
- 기존 `id` 참조는 `uid`를 읽는 호환 속성으로 유지합니다. 프로젝트 식별·폴더 승격·위치 충돌과 세션 범위·이동 규칙은 도메인에 있습니다.
- 저장 포트는 `IGenericRepository`를 상속합니다. 프로젝트 위치 조회와 범위가 있는 네이티브 ID 조회만 확장합니다.
- `ProjectRepository`, `SessionRepository`는 `AbstractGenericRepository`를 상속합니다. `get`, `get_or_none`, `contains`, `range`, `save`, `save_all`, `delete`, `delete_all`과 생성자는 재구현하지 않습니다.
- 도메인 테이블은 `@Table(Domain)`과 `AbstractMappableTable[Domain]`으로 양방향 변환을 정의합니다. 위치 자식 테이블은 도메인 매핑이 없는 `AbstractTable`입니다.
- `SchemaRegistry`가 Table 태그를 통해 도메인과 실제 테이블을 연결합니다. 저장소가 매핑을 별도로 추적하지 않습니다.
- `ApplicationContext`가 `@UseCase`, `@Repository`, 관찰 Pod와 프레임워크의 `ConnectionManager`, `SessionManager`, `Transaction`, `AggregateCollector`를 구성합니다.
- `transport/session_requests.py`는 표준 `Transaction`을 사용합니다. 성공 시 commit, 예외 시 rollback, 세션 종료는 프레임워크가 수행합니다. 별도의 UoW나 transaction 구현은 없습니다.
- 요청 경계는 프레임워크의 미존재·버전 충돌 오류를 기존 `ContextNotFound`·`RevisionConflict`로 변환합니다. 세션이 요청한 프로젝트에 속하는지는 유스케이스가 도메인에 확인합니다.

기본 CRUD의 SQL과 merge·flush·변경 aggregate 수집은 프레임워크 소유입니다.
Neurath 저장소의 SQL은 추가한 두 조회 메서드에만 있습니다. 도메인은 프레임워크의
순수 도메인 기반과 mutability 선언만 사용하며 SQLAlchemy와 저장 어댑터에 의존하지 않습니다.

## 요청 수명과 SQLite

각 요청은 독립된 컨테이너·설정·연결 관리자를 만듭니다. 전역 환경변수를 바꾸지 않고
설정 객체를 주입합니다. Spakky의 ConnectionManager가 만든 엔진에 SQLite 연결 정책을
설정하며, 요청 종료나 초기화 실패 시 엔진을 폐기합니다. 상주 daemon은 없습니다.

Git 관찰은 DB 트랜잭션 시작 전에 마칩니다. 쓰기 연결은 첫 조회 전에 `BEGIN IMMEDIATE`를
획득하고 읽기 연결은 SQLite URI의 `mode=ro`와 `query_only`를 사용합니다. 외래 키를
모든 연결에 적용하며 SQLite 잠금 기본 대기는 5초입니다. 숨은 재시도는 없습니다.
중첩된 독립 요청도 각자의 SessionManager와 트랜잭션을 사용합니다.

네이티브 ID는 `(project_id, provider, host_session_id)`로 구분합니다. 재등록은 최신 작업
경로를 덮어쓰지 않습니다. linked worktree와 하위 폴더는 같은 프로젝트이며 같은 원격의
독립 clone은 구분합니다. 일반 폴더가 Git 저장소가 되어도 기존 ID·위치·종속 외래 키를
보존합니다. 서로 다른 프로젝트의 기록을 임의로 합치지 않습니다.

## 매핑·버전·소유권

프레임워크의 UUID `version`과 `created_at`·`updated_at`을 저장합니다. UUID는 도메인
변경 토큰이며, 기존 요청의 정수 `revision`을 대체하지 않습니다. SQLAlchemy의
`version_id_col`은 정수 revision에 연결하여 오래된 detached 저장과 실제 flush 경합을
거부합니다. 프로젝트에도 저장소용 정수 revision을 추가합니다.

반환된 엔티티는 ORM 수명과 독립적이며 요청 결과는 불변 snapshot입니다. 시각은 UTC로
왕복합니다. SQLite의 시각 저장 형태와 도메인 UTC 시각을 명시적으로 변환하여 같은 값을
재저장할 때 시각 표현 차이로 UPDATE가 발생하지 않게 합니다. 같은 경로 이동과 같은
위치 재연결은 변경 토큰·수정 시각·정수 revision을 증가시키지 않습니다.

Project 저장은 소유한 위치 관계까지 기본 merge로 반영합니다. 삭제한 위치는 orphan으로
정리합니다. 다른 Project의 위치를 generic merge가 재할당하지 못하도록 SQLite trigger가
소유자 변경을 거부합니다. 실패한 요청은 부모·자식 변경을 함께 롤백합니다.

## 스키마와 보존

이미 적용한 `core_0001`은 수정하지 않습니다. 명시적 초기화가 `core_0002`를 적용하여
메타데이터·프로젝트 revision·위치 소유 제약을 추가합니다. 기존 ID, 세션 revision,
프로젝트·위치·세션 데이터와 종속 외래 키는 유지합니다.

기존 행에는 원래 시각이 없으므로 epoch를 **미상 표식**으로 저장합니다. 이 값을 실제
생성 시각으로 해석하지 않습니다. 기존 행의 변경 토큰은 초기 표식인 zero UUID이며,
도메인 변경 후 프레임워크가 새 토큰을 생성합니다. 새 aggregate는 실제 생성 시각과
토큰을 사용합니다. 이전 기록을 새 권한·성공 근거로 만들지 않습니다.

일반 요청은 스키마를 바꾸지 않으며 이전·미래 revision을 거부합니다. `initialize_database`
명령 경계에서만 마이그레이션을 수행합니다. 전체 과정이 실패하면 스키마·행·revision이
함께 롤백됩니다. legacy DB는 별도 자료 이전 없이 초기화하지 않습니다.

## 내부 요청 API

```python
from pathlib import Path
from neurath.infrastructure.database import initialize_database
from neurath.transport.session_requests import (
    register_session, get_session_context, move_session,
)

path = Path("/explicit/isolated/core.sqlite3")
initialize_database(path)
opened = register_session("/project", "codex", "native-session", database_path=path)
current = get_session_context(opened.project.id, opened.session.id, database_path=path)
changed = move_session(current.project.id, current.session.id, "/project/subfolder",
                       current.session.revision, database_path=path)
```

기본 경로는 `$XDG_DATA_HOME/neurath/core.sqlite3`이며 XDG가 없으면
`~/.local/share/neurath/core.sqlite3`입니다. 상대 XDG 경로는 거부합니다.

## 검증과 구현 경계

시험은 프레임워크 메서드 상속, 실제 registry·생성자 주입·aggregate 수집, 기본 CRUD·배치·삭제,
조회 격리, 변경 없는 저장, 오래된 저장·경합, 예외 정리, 소유권 충돌, 독립 프로세스,
Git/worktree/clone 구분과 명시적·동시 초기화를 검증합니다. 이전 스키마의 값·종속 자료 보존,
반복 이전, 이전 도중 실패의 전체 롤백도 확인합니다. 기본 CRUD 재구현은 공통 pre-commit·CI의
`FRAMEWORK_CRUD` 검사로 거부합니다. 의미상 도메인 설계의 적절성은 사람 검토 사항입니다.

태스크·runner·호스트 훅·기억·협업·공개 CLI·실제 사용자 자료 이전·설치는 후속 티켓입니다.
`setup`은 이 기반 후보의 설치를 거부합니다. 실제 사용자 DB와 설치된 배포본은 이번 소스
수정으로 변경하지 않습니다.
