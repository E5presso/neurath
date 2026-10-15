# 프로젝트·세션 기반

[구조](architecture.md) · [구현 계획](implementation-plan.md) · [English](../en/core-foundation.md)

#137은 요청 단위 프로젝트·세션 영속성을 제공합니다. #154 구현은 리뷰 후 전면
재작성했습니다. Core façade, UoW 컨테이너, 구조적 Protocol 계약, 실행 모델의
imperative table 매핑을 패키지에 남기지 않습니다.

## 책임 분리

- `domain/aggregates/project.py`: 프로젝트 동일성과 `ProjectKind` enum.
- `domain/aggregates/session.py`: 호스트 세션 aggregate, revision 전이, 분리된 응답 값.
- `application/ports`: repository/service/use case ABC와 불변 command/query 입력.
- `application/usecases`: 등록·맥락 조회·이동을 각각 `execute`하는 명시 구현.
- `infrastructure/models`: 선언형 ORM 레코드와 명시적 `from_domain`/`to_domain` 변환.
- `infrastructure/repositories`: application repository port를 명시적으로 상속한 구현.
- `infrastructure/database.py`: SQLite engine 설정, 스키마 확인, 명시적 초기화.
- `infrastructure/project_locator.py`: 트랜잭션 이전에 수행하는 제한 시간이 있는 Git 관찰.
- `transport/session_requests.py`: 실제 Session 트랜잭션 수명주기와 의존성 조립.

domain과 application은 SQLAlchemy·Alembic·호스트 adapter를 import하지 않습니다.
의존성은 명시적인 생성자 인자이며 일반 registry나 암묵 DI를 사용하지 않습니다.
요청 계층은 불변 도메인 값을 반환하고 외부 호스트 동작 전에 연결을 닫습니다.
서비스 객체는 영속 요청 상태를 메모리에 보관하지 않습니다.

## 내부 요청 API

```python
from pathlib import Path
from neurath.infrastructure.database import SqliteDatabase
from neurath.transport.session_requests import (
    register_session, get_session_context, move_session,
)

path = Path("/explicit/isolated/core.sqlite3")
SqliteDatabase(path).initialize()  # 명시적인 준비이며 일반 요청은 초기화하지 않습니다.
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

각 요청은 pool 없는 engine과 실제 ORM `Session`을 열고
`with Session(engine) as session, session.begin():`을 사용합니다. 쓰기는 가변
상태를 읽기 전에 `BEGIN IMMEDIATE`를 획득하고 조회는 SQLite 읽기 전용 모드를
사용합니다. 모든 연결은 외래 키를 적용합니다. SQLite가 동시 작성을 조정하며
기본 잠금 대기는 5초입니다. 실패를 몰래 재시도하지 않습니다. repository는
전달받은 트랜잭션 안에서 flush하고 독립 commit하지 않습니다.

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

[필수 품질 검사](../../CONTRIBUTING.ko.md)는 현재 패키지 전체에 구체적 리뷰 규칙을
적용하고 실패 fixture로 검증합니다. 모듈 응집도와 문서의 의미는 사람 검토가
필요합니다.

과거 0.3.1 runtime과 구현 의존 시험은 Git에서 복구할 수 있으며 병렬 runtime이나
lint 예외로 포함하지 않습니다. 이 후보는 태스크(#140), runner(#141), 훅(#142),
기억(#143), 협업(#144), CLI(#148), legacy 변환(#150), 설치(#151)를 구현하지
않습니다. 이는 남은 구현 작업이며 기능 보존 완료가 아닙니다. 휠에는 과거 CLI
진입점이 없으며 `setup`은 설치를 거부합니다. 실제 사용자 DB·설치 배포본·호스트
활성화는 여기서 변경하거나 검증하지 않았습니다.
