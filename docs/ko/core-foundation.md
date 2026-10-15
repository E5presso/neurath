# 프로젝트·세션 기반

[구조](architecture.md) · [구현 계획](implementation-plan.md) · [English](../en/core-foundation.md)

#137은 요청 단위 프로젝트·세션 영속성을 제공합니다. #154 구현은 리뷰 후 전면
재작성했습니다. Core façade, UoW 컨테이너, 구조적 Protocol 계약, 실행 모델의
imperative table 매핑을 패키지에 남기지 않습니다.

## 책임 분리

- `domain/aggregates/project.py`: 불변 ProjectLocation 값을 소유하는 가변 Project aggregate, 동일성 선택, 폴더 승격, 소유권·충돌 규칙.
- `domain/aggregates/session.py`: 가변 세션 동일성, 네이티브 ID 검증, 호출자가 관찰한 revision에 따른 이동 검증.
- `domain/observations.py`: 동일성 정책이 없는 불변 파일시스템·Git 원시 관찰 값.
- `application/ports`: repository·관찰용 명시적 ABC. 저장소 계약은 조회·저장만 제공합니다.
- `application/usecases`: 불변 command/query를 받는 구체 프로젝트 등록·세션 등록·조회·이동 동작. use case 인터페이스는 없습니다.
- `application/context.py`: 불변 응답 snapshot. 엔티티는 동일성을, snapshot은 상태를 비교합니다.
- `infrastructure/models`와 `repositories`: 선언형 레코드, 명시적 변환, 기본 영속성 구현.
- `infrastructure/database.py`: engine 생성·스키마 확인·명시적 초기화 함수.
- `infrastructure/directory_observer.py`: 정규 경로·Git common directory·primary worktree 사실만 반환하는 제한 시간 있는 I/O.
- `infrastructure/providers.py`: Dishka 생성자 주입과 APP engine·REQUEST Session/repository/use case 수명 관리.
- `transport/session_requests.py`: 요청 조정과 직접적인 `Session.begin()` 트랜잭션 소유권.

domain과 application은 SQLAlchemy·Alembic·Dishka·호스트 adapter를 import하지 않습니다.
호스트 요청마다 새 컨테이너를 만듭니다. APP scope는 자원 수명이며 상주 daemon이 아닙니다.
DB Session을 resolve하기 전에 Git 관찰을 마칩니다. Dishka는 Session 종료·engine 폐기를
담당하며 트랜잭션을 commit하지 않습니다. 자원 정리 후 독립된 불변 snapshot을 반환합니다.

## 내부 요청 API

```python
from pathlib import Path
from neurath.infrastructure.database import initialize_database
from neurath.transport.session_requests import (
    register_session, get_session_context, move_session,
)

path = Path("/explicit/isolated/core.sqlite3")
initialize_database(path)  # 명시적인 준비이며 일반 요청은 초기화하지 않습니다.
opened = register_session("/project", "codex", "native-session", database_path=path)
current = get_session_context(opened.project.id, opened.session.id, database_path=path)
changed = move_session(current.project.id, current.session.id, "/project/subfolder",
                       current.session.revision, database_path=path)
```

경로를 생략하면 모든 요청은 `$XDG_DATA_HOME/neurath/core.sqlite3`를 사용하며
XDG가 없으면 `~/.local/share/neurath/core.sqlite3`를 사용합니다. 상대 XDG 경로는
거절합니다. 네이티브 ID는 `(project_id, provider, host_session_id)`로 구분하며
호스트 권한을 증명하지 않습니다. 재등록은 최신 관찰 경로를 보존합니다.
다른 프로젝트의 세션 조회는 `ContextNotFound`, 오래된 이동 revision은
`RevisionConflict`를 반환합니다.

정규화한 로컬 Git common directory가 저장소를 식별합니다. linked worktree와
하위 폴더는 같은 프로젝트이며 같은 원격 URL의 독립 clone은 서로 다릅니다.
폴더 별칭을 유지하므로 이후 Git을 초기화해도 프로젝트 ID와 종속 외래 키를
보존하며 첫 후속 요청이 linked worktree에서 와도 동일합니다. 충돌한 별칭은
자료를 합치지 않고 실패합니다. Git 오류를 새 폴더 프로젝트로 숨기지 않습니다.

## SQLAlchemy와 이전

각 요청은 Dishka로 pool 없는 engine과 실제 ORM `Session`을 resolve하고 요청
adapter가 직접 `with session.begin():`을 사용합니다. 쓰기는 가변
상태를 읽기 전에 `BEGIN IMMEDIATE`를 획득하고 조회는 SQLite 읽기 전용 모드를
사용합니다. 모든 연결은 외래 키를 적용합니다. SQLite가 동시 작성을 조정하며
기본 잠금 대기는 5초입니다. 실패를 몰래 재시도하지 않습니다. repository는
전달받은 트랜잭션 안에서 flush하고 독립 commit하지 않습니다.
Project가 aggregate root이며 위치에는 독립 저장소나 생명주기가 없습니다.
`get`·`find_by_location`은 소유 위치를 포함한 전체 프로젝트를 읽습니다.
`save(project)`는 부모 필드와 소유 ORM 관계를 함께 반영합니다. 기존 자식은 유지하고
새 값은 삽입하며 제거한 값은 orphan으로 삭제합니다. 다른 프로젝트의 위치 키는
재할당하지 않고 삽입 충돌을 일으켜 호출자 트랜잭션이 부모와 자식을 함께 롤백합니다.
스키마는 바꾸지 않습니다. 프로젝트·세션의 삽입과 갱신은 모두 `save(entity) -> entity`입니다.
`HostSession.move`는 관찰한 버전을 검증하고 경로를 바꿉니다. 기본 저장 동작인
`save(entity)`는 SQLAlchemy `merge`와 `version_id_col`을 사용해 저장한 엔티티를
반환합니다. ORM이 저장 버전을 증가시키고 오래된 detached 엔티티를 거부합니다.
동일한 경로 저장은 ORM의 일반 dirty checking에 따라 UPDATE 없이 버전을 유지합니다. repository 자체의
엔티티 캐시나 save 이전 load 강제 조건은 없습니다.

원래 `core_0001` DDL과 저장된 테이블 이름은 호환됩니다. revision은 현재
`infrastructure/migrations`에 있으며 타입 표기와 docstring만 바뀌었습니다.
명시적 초기화는 legacy 테이블을 거부하고 알려진 Alembic revision을 적용합니다.
일반 요청은 스키마 부재·불일치를 거절합니다. 후속 변경은 새 revision을 추가하고
`SCHEMA_REVISION`을 올리며 이미 적용한 스키마 정의를 수정하지 않습니다.
`tests/fixtures/core_0001.sql`은 기존 스키마를 나타내며 원래 ID·revision을
새 ORM으로 읽고 갱신할 수 있음을 검증합니다.

## 검증과 한계

동작 시험은 독립 프로세스, 등록·revision 경쟁, 롤백, 미커밋 조회 격리, 외래 키,
읽기 전용 연결, 명시적·동시 초기화, 이전 스키마 호환, 거부한 legacy DB 바이트
보존, Git/worktree/clone 구분, 폴더 전환을 확인합니다. 종속 레코드 fixture는
외래 키 보존 시험이며 태스크·메모리 구현을 뜻하지 않습니다.

순수 도메인 시험은 Git·SQL 없이 루트 선택, worktree 동일성, 승격, 소유권 충돌,
엔티티 동일성, 오래된 이동 요청을 검증합니다. DI 시험은 실제 생성자 주입, scope 격리,
detached stale 저장, 연속 저장, 예외 시 롤백·연결 종료를 검증합니다.

[필수 품질 검사](../../CONTRIBUTING.ko.md)는 현재 패키지 전체에 구체적 리뷰 규칙을
적용하고 실패 fixture로 검증합니다. 모듈 응집도와 문서의 의미는 사람 검토가
필요합니다.

과거 0.3.1 runtime과 구현 의존 시험은 Git에서 복구할 수 있으며 병렬 runtime이나
lint 예외로 포함하지 않습니다. 이 후보는 태스크(#140), runner(#141), 훅(#142),
기억(#143), 협업(#144), CLI(#148), legacy 변환(#150), 설치(#151)를 구현하지
않습니다. 이는 남은 구현 작업이며 기능 보존 완료가 아닙니다. 휠에는 과거 CLI
진입점이 없으며 `setup`은 설치를 거부합니다. 실제 사용자 DB·설치 배포본·호스트
활성화는 여기서 변경하거나 검증하지 않았습니다.
