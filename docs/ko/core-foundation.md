# 요청 단위 코어 기반

[구조](architecture.md) · [구현 계획](implementation-plan.md) · [English](../en/core-foundation.md)

#137에서 새 Python 코어 기반을 구현합니다. 새 CLI, 네이티브 훅, 설치, 기존 자료
이전을 활성화한 상태는 아닙니다. 해당 경로는 후속 구현 티켓에서 연결합니다.
기존 0.3.1 모듈은 호환성을 위해 잠시 유지하며 새 코어에서 사용하지 않습니다.

## 저장소와 요청 경계

`CoreDatabase()`는 `$XDG_DATA_HOME/neurath/core.sqlite3`를 사용하며,
XDG_DATA_HOME이 없으면 `~/.local/share/neurath/core.sqlite3`를 사용합니다.
프로젝트나 세션에 따라 경로를 바꾸지 않습니다. 격리 설치·시험에는 명시적인
`Path`를 전달할 수 있으며, 실제 어댑터는 같은 사용자 DB 설정을 공유합니다.

초기화는 명시적인 `CoreDatabase.initialize()`로 수행합니다. 패키지의
`core_migrations` Alembic 체인을 새 코어 DB에 적용합니다. 이미 존재하는 다른
형식의 DB는 초기화하지 않으며 기존 자료 변환은 #150에서 수행합니다.
일반 요청은 이전을 실행하지 않고, DB가 없거나 스키마가 맞지 않으면
`StorageNotReady`를 반환합니다. 구현 시험은 사용자의 설치 DB를 열지 않습니다.

각 `transaction(write=...)`는 SQLAlchemy 연결을 새로 열고 종료 시 닫습니다.
쓰기는 SQLite `BEGIN IMMEDIATE`를 사용하고 관련 변경을 함께 커밋하거나
실패 시 함께 되돌립니다. 조회는 파일을 읽기 전용으로 열고 조회 트랜잭션을
사용합니다. 모든 연결에서 외래 키를 적용합니다. 메모리 잠금 대신 SQLite가
동시 작성을 조정합니다. 경합한 작성자는 설정된 시간(기본 5초)까지 기다리며,
잠금 실패는 동작을 몰래 재시도하지 않고 호출자에게 반환합니다.
호스트·네트워크 동작은 트랜잭션 밖에서 수행해야 합니다.

## 후속 티켓에서 사용할 내부 API

- `neurath.transport.core_requests.build_core(path=None)`는 CLI·훅 어댑터가 사용할
  같은 코어를 구성합니다. 저장소 초기화나 훅 설치를 수행하지 않습니다.
- `Core.open_session(working_directory, provider, host_session_id)`는 프로젝트를
  판별하고 관찰한 세션을 등록합니다. 반복 등록은 기존 세션과 현재 작업 경로를 유지합니다.
- `Core.get_context(project_id, session_id)`는 지정한 프로젝트·세션만 조회합니다.
  다른 프로젝트의 세션을 지정하면 `ContextNotFound`를 반환합니다.
- `Core.move_session(project_id, session_id, working_directory, expected_revision)`는
  같은 프로젝트 안의 작업 경로를 예상 개정과 비교해 변경합니다. 오래된 개정은
  `RevisionConflict`로 거절합니다. 늦은 세션 등록이 최신 경로 변경을 덮어쓰지 않습니다.

애플리케이션은 `application/core.py`의 `Database`, `UnitOfWork`,
`IdentityRepository`, `ProjectResolver` 프로토콜에 의존합니다. 불변 값과 오류는
`domain/core.py`에 있으며 SQLAlchemy·Git·Alembic은 infrastructure가 담당합니다.
`CoreDatabase.transaction()`이 제공하는 `CoreUnitOfWork.connection`을 후속
저장소 구현이 공유해 관련 변경을 원자적으로 반영할 수 있습니다.
서비스 객체에 요청·세션 상태를 보존하거나 응답 뒤 작업 단위를 유지하지 않습니다.
후속 스키마는 `infrastructure/core_migrations`에 새 개정으로 추가하고
`SCHEMA_REVISION`을 지원하는 최신 개정에 맞춥니다. 적용된 개정은 수정하지 않습니다.

호스트 ID는 범위가 있는 식별 정보이며 인증이나 권한 증명이 아닙니다.
세션은 `(project_id, provider, host_session_id)`로 구분하고 실제 작업 경로는
프로젝트 동일성과 별도로 기록합니다.

Git 프로젝트는 정규화한 공통 Git 디렉터리를 사용합니다. linked worktree와 하위
폴더는 같은 프로젝트이고, 같은 원격 URL의 별도 clone은 다른 프로젝트입니다.
Git이 없으면 정규화한 작업 폴더를 사용합니다. 폴더 별칭을 유지해 이후 `git init`을
하면 동일 프로젝트 ID에 Git 연결을 추가하며 종속 레코드는 변경하지 않습니다.
첫 후속 요청이 linked worktree에서 와도 기존 ID를 유지합니다. 저장된 동일성이
충돌하면 무관한 자료를 합치지 않고 `ProjectIdentityConflict`를 반환합니다.
Git 조회 오류를 새 폴더 프로젝트로 숨기지 않습니다.

## 검증과 범위

`tests/test_core_foundation.py`에서 독립 프로세스 상태 보존, 동시 등록·개정 경합,
실패 롤백, 미커밋 조회 격리, 외래 키, 읽기 전용 동작, 명시적·동시 초기화,
Git/worktree/clone 구분, 일반 폴더의 Git 전환을 검증합니다. 전환 시험의 종속
레코드는 외래 키 보존을 확인하는 fixture이며 태스크·메모리 기능 구현을 뜻하지 않습니다.

태스크(#140), runner(#141), 호스트 수명주기·훅(#142), 기억(#143), 협업(#144),
공개 Typer CLI(#148), 이전(#150), 설치(#151)는 이 기반을 확장합니다.
격리 코어 시험 통과는 실제 호스트 집행·메시지 전달이나 전체 재설계 완료의 근거가 아닙니다.
