# Neurath 개발 지침

Neurath는 원문 출처와 미완료 작업을 보존하는 에이전트 하네스다.
현재 사용자 지시와 `docs/ko/specification.md`를 구현의 기준으로 삼는다.

- 코어는 hook·CLI 요청마다 사용자 단위 단일 SQLite의 상태를 조회해 처리하는 stateless service다. 프로젝트·세션은 DB 안에서 구분한다. 지속 상태를 상주 코어 메모리에 의존시키지 않는다.
- 설치된 rules가 기본 진입점이며 에이전트가 요청에 맞는 스킬을 선택한다. 사용자 지정 스킬은 그 지정을 따르고 단순 대화에는 강제하지 않는다. 선택한 스킬은 CLI로 시작하며 phase는 기존 runner가 관리한다.
- 태스크/TODO의 완료 여부는 종료 훅이 결정론적으로 검사한다. 사용자 의도 충족과 요청된 회고의 내용 평가는 별도 서브에이전트 또는 다른 provider에게 위탁한다. 결과 평가는 작업 묶음을 마무리하는 스킬의 phase로 관리하고 회고 제안·거절은 원래 작업 종료와 구분한다.
- 도메인 규칙은 `src/neurath/domain`, 유스케이스는 `application`, SQLAlchemy·Alembic은 `infrastructure`, 호스트·CLI 어댑터는 `transport`에 둔다. 도메인은 외부 계층에 의존하지 않는다.
- 기존 데이터 이전은 `migration`의 명시적 보존 경계에서 수행한다. 원본 DB를 수정하거나 미완료 작업을 임의로 완료·취소하지 않는다.
- 새 설계는 Python + Typer 기반 `neurath` CLI 전용이며 MCP 서버나 어댑터를 제공하지 않는다. 릴리스 시 실제 CLI 정의에서 가이드 프롬프트를 생성하고 설치 시 관리 영역에 반영한다. 네이티브 호스트의 실행 권한과 사용자 승인을 하네스 기록으로 대체하지 않는다.
- `uv sync --locked`로 개발 환경을 준비하고 `uv run --locked python tools/check.py`로 필수 검사를 실행한다.
- 현재 `./setup`은 미완성 후보 설치를 거부한다. 소스 검사, 패키지 생성, 설치, 실제 호스트 호출을 구분해 보고한다.
- 설치는 관련 없는 사용자 설정·훅·지침을 보존하며, 변경 전에 복구 사본을 남긴다.
- 공개 문서는 `docs/en`과 `docs/ko`의 같은 상대 경로에 함께 작성한다. README와 CONTRIBUTING은 영어·한국어 쌍을 유지한다. 개인 경로와 검증 원문은 공개 문서나 패키지에 넣지 않는다.
- 코드·설치 수정은 승인된 로컬 작업이다. 공개 push·PR·배포는 사용자의 별도 요청 없이 수행하지 않는다.
- 도메인 aggregate, 명시적 ABC port, 개별 command/query use case, 구체 repository adapter와 declarative ORM 모델의 책임을 구분한다. 참고 구조의 과거 Protocol·불필요한 use case 인터페이스·UoW는 복제하지 않는다. Dishka로 실제 생성자 주입과 요청별 자원 수명을 구성하되 트랜잭션은 호출자의 Session.begin()이 소유한다.
- 전체 현재 src와 tools에 strict Pyrefly·Google 형식 pydoclint·Ruff 검사를 적용한다. pre-commit과 CI는 tools/quality.py를 공유한다. 모듈 의미와 문서의 유용성은 별도 사람 검토 사항이다. 저장소는 조회·저장만 제공하며 위치 식별·승격·충돌 규칙은 ProjectLocation/Project가 소유한다. 엔티티는 가변 상태·동일성을 가지며 불변 관찰·명령·응답 값과 구분한다.
- 현재 후보는 #137의 기반 라이브러리다. 이전 MCP runtime은 Git 기록에 있으며 새 패키지에는 포함하지 않는다. 공개 CLI·설치·기존 자료 변환은 후속 티켓이며 이 후보를 실설치하지 않는다.
