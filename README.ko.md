# Neurath

[English](README.md)

Neurath는 로컬 CLI 전용 에이전트 하네스로 전면 재작성 중입니다.
[승인된 명세](docs/ko/specification.md)는 태스크, 순서가 있는 실행 단계,
훅, 기억, 협업, 복구 기능을 유지합니다. 이 체크아웃이 구현한 범위는
#137의 사용자 단위 프로젝트·세션 기반과 #140의 원문·태스크·TODO 원장, #141의 스킬 단계 실행입니다.

현재 후보 패키지는 가변 도메인 엔티티와 불변 요청 값, 명시적인 애플리케이션 port와
use case, Spakky 도메인 기반·기본 SQLAlchemy repository·테이블 매핑과 요청별 트랜잭션을 제공합니다.
과거 MCP 서버, 공개 CLI, 설치기와 나머지 하네스 기능은 포함하지 않습니다.
과거 실행 코드는 Git 기록에서 복구할 수 있습니다. 이 체크아웃을 수정하거나
검증해도 기존 설치 배포본과 사용자 데이터베이스는 바뀌지 않습니다.

이 기반은 실행 중인 하네스의 설치 대체물이 아닙니다. `setup`은 설명과 함께
종료하며 사라진 모듈을 가리키는 console entry point도 배포하지 않습니다.
CLI·자료 이전·설치는 승인된 후속 구현 계획에 남아 있습니다.

- [기반 구조·API·구현 경계](docs/ko/core-foundation.md)
- [개발과 강제 품질 검사](CONTRIBUTING.ko.md)
- [전체 구현 계획](docs/ko/implementation-plan.md)
- [요구사항 검증](docs/ko/acceptance.md)
- [문서 안내](docs/ko/index.md)

소스 검사, 휠 생성, 공개 릴리스, 설치, 실제 호스트 활성화는 서로 다른 결과입니다.
이 기반의 릴리스나 실제 활성화를 주장하지 않습니다.

- [원문·태스크·TODO의 현재 내부 API](docs/ko/task-ledger.md)

- [스킬 절차·단계 실행 API](docs/ko/workflow-runner.md)
