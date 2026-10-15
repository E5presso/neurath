# 기여 안내

[홈](README.ko.md) · [English](CONTRIBUTING.md)

승인된 명세와 [기반 구조](docs/ko/core-foundation.md)의 책임 경계를 따릅니다.
도메인 aggregate는 불변식을 담당합니다. 애플리케이션 port는 `ABC`와
`@abstractmethod`를 사용하며 구체 use case와 repository adapter가 명시적으로
상속합니다. 각 use case는 이름이 있는 불변 command/query를 받아 `execute`합니다.
ORM 모델은 `DeclarativeBase`, `Mapped`, `mapped_column`과 명시적인 도메인 변환을
사용합니다. 요청 adapter는 `Session.begin()`을 직접 사용하며 별도 UoW·트랜잭션
프레임워크를 추가하지 않습니다.

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
lint·docstring·타입 표기·포맷, strict mypy, 구조 AST 규칙, 정상·실패 fixture를
검사합니다. CI도 필수 runner를 실행하며, runner는 이어서 전체 동작 시험과
휠 생성을 수행합니다. 성공 표시는 `NEURATH_CHECK_OK`입니다. 현재 소스의 모듈
허용 목록, 과거 소스 예외 baseline, `Any` 우회, 타입·lint 무시 정책은 없습니다.
`src` 아래 앞으로 추가되는 Python 파일도 모두 발견합니다. 시험은 lint·포맷을
적용하되 문서·타입 표기 스타일 규칙에서 제외하며, 제품 소스와 개발 도구는
엄격한 타입 표기와 docstring을 적용합니다.

## 기계 검사 규칙과 사람 검토의 경계

AST 검사는 import 별칭과 로컬 상속 관계를 해석해 Protocol, Literal, Any/cast,
이름으로 드러나는 커스텀 transaction/UoW API, Core/core 모듈, 계층 위반 import,
ABC/abstractmethod 없는 port, 명시 계약 상속이 없는 repository/use case/locator,
비선언형 ORM 매핑을 거부합니다. ORM 규칙은 실행 모델에 적용하며 불변 Alembic
revision의 DDL에는 SQLAlchemy Column을 의도적으로 사용합니다. 별칭, 간접 상속,
port처럼 가장한 DTO, 새 모듈 등 실패·정상 fixture로 규칙을 검증합니다.

검사는 구체적인 구문과 타입 관계를 확인합니다. 이름이 실제 책임을 나타내는지,
docstring이 유용한지, 일반 클래스가 숨겨진 façade인지, 이름을 바꾼 트랜잭션
추상화가 의미상 적절한지는 증명하지 못합니다. 응집도·불변식·트랜잭션 범위와
추상화의 필요성은 사람이 검토해야 합니다. lint가 이 판단까지 증명한다고
주장하지 않습니다. 동적 코드 생성·리플렉션 우회는 명시적 구현의 대안이 아닙니다.

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
