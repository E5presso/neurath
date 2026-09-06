# Neurath 개발 지침

Neurath는 기술 스택과 독립적인 Claude Code/Codex 하네스 설치 패키지다.
현재 사용자 지시와 현재 소스를 기준으로 구현한다.

- `src/neurath/_assets`은 Neurath가 직접 관리하는 독립 실행 자산이다.
- 출처 이력은 `NOTICE.md`에 기록한다. 다른 저장소는 빌드 입력이 아니다.
- 새 설치 동작은 먼저 실패하는 테스트로 정의한다.
- 설치는 기존 지침, 훅, 권한, 프로젝트 의존성을 보존한다.
- 검증은 원문 무결성, 패키지 실행, 설치 동작, 실제 호스트 활성화를 구분한다.
- GitHub 생성, push, 공개 배포는 별도 요청 없이는 하지 않는다.

## 개발과 자기 설치

- 개발 환경은 `uv sync --locked`로 준비하고 `uv run --locked python tools/check.py`로 검사한다.
- 자기 설치는 `./setup --self`를 사용한다. 개발 `.venv`와 설치된 하네스의 도구 환경은 분리한다.
- 실행 자산을 바꾸면 `uv run --locked python tools/build_manifest.py`를 실행한 뒤 검사·빌드·자기 설치 업데이트를 수행한다.
- `.agents/skills`와 `.neurath/rules`는 설치 결과다. 원본 `src/neurath/_assets`를 수정한다.
- 검증 원문·로컬 상태·설치 receipt·개인 경로를 공개 문서나 배포본에 넣지 않는다.

<!-- neurath:managed -->
## Neurath

Read `.neurath/policy.md` and `.neurath/project.json` for the generic profile.
Use the skills in `.agents/skills`; execute through `.neurath/run`.
<!-- /neurath:managed -->
