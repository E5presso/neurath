# Neurath 개발

[English](../../en/contributing/index.md) · [코어 계약](core-v2-spec.md)

현재 사용자 요청·`AGENTS.md`·설치 정책·프로젝트 바인딩을 읽고 편집 전에 작업 트리를 확인한다. `session_status`와 `task_list`로 기존 작업을 복구하고 쓰기에만 checkout 소유권을 얻는다. Task의 스킬 phase 순서를 따른다. 설치 투영본 대신 `src/neurath/_assets` 원본을 수정한다.

`uv sync --locked`로 준비한다. 실행 변경 뒤 `uv run --locked python tools/build_manifest.py`, `uv run --locked python tools/check.py`를 실행한다. 전체 성공 표시는 모든 검사를 통과해야 나온다. 정확한 배포본의 빌드·검증은 별도로 수행한다. `./setup --self`는 설치를 바꾸며 이미 실행 중인 호스트를 전환하지 않는다. 호스트가 지원하는 경로로 재연결하고 활성화를 관측한다. 공개 릴리스에는 사용자 승인과 정확한 자산 검증이 필요하다.
