# Neurath 개발 지침

Neurath는 원문 출처와 미완료 작업을 보존하는 에이전트 하네스다.
현재 사용자 지시와 `docs/ko/specification.md`를 구현의 기준으로 삼는다.

- 도메인 규칙은 `src/neurath/domain`, 유스케이스는 `application`, SQLAlchemy·Alembic은 `infrastructure`, 호스트·MCP 어댑터는 `transport`에 둔다. 도메인은 외부 계층에 의존하지 않는다.
- 기존 데이터 이전은 `migration`의 명시적 보존 경계에서 수행한다. 원본 DB를 수정하거나 미완료 작업을 임의로 완료·취소하지 않는다.
- MCP 서버 이름은 `neurath`다. 네이티브 호스트의 실행 권한과 사용자 승인을 하네스 기록으로 대체하지 않는다.
- `uv sync --locked`로 개발 환경을 준비하고 `uv run --locked python tools/check.py`로 필수 검사를 실행한다.
- `./setup --self`는 로컬 자기 설치다. 설치 환경은 개발 환경과 분리한다. 소스 검사, 패키지 설치, 프로토콜 시험, 실제 호스트 호출을 구분해 보고한다.
- 설치는 관련 없는 사용자 설정·훅·지침을 보존하며, 변경 전에 복구 사본을 남긴다.
- 공개 문서는 `docs/en`과 `docs/ko`의 같은 상대 경로에 함께 작성한다. README와 CONTRIBUTING은 영어·한국어 쌍을 유지한다. 개인 경로와 검증 원문은 공개 문서나 패키지에 넣지 않는다.
- 코드·설치 수정은 승인된 로컬 작업이다. 공개 push·PR·배포는 사용자의 별도 요청 없이 수행하지 않는다.
- 기존 구현·보관 코드·다른 코드베이스를 재작성의 본보기로 사용하지 않는다. 개념과 명시적 스펙에서 설계한다.


<!-- neurath:managed -->
## Neurath

Use MCP server `neurath`. Read `.neurath/policy.md`.
Inspect `session.get` and `task.list`; preserve unfinished user requirements.
Register the requested outcome with `task.create`, then start it with `task.activate`.
Use ordered phases and criterion-specific evidence; delegation reports need owner acceptance.
Use `lease.acquire` and `lease.release` for writer ownership, native tools for actual execution.
Recover with `harness_bypass(enabled=true)` when the harness malfunctions, then restore it after verification.
<!-- /neurath:managed -->
