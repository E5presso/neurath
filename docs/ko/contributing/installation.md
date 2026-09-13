# 설치 개발과 MCP 통합

<!-- date: 2026-09-09; synced_from: baseline f69cb6402683bb2e0bfe56ed04c63f808b263f06 plus current working-tree stdio MCP changes; scope: source, not live-host certification -->

[English](../../en/contributing/installation.md) · **한국어**

[기여자 안내](index.md) · [최초 설치 참조](setup-reference.md) · [작업 도구](task-tools.md)

이 문서는 설치기를 개발하거나 에이전트 통합을 검증하는 기여자용 참조입니다.
일반 사용자는 [설치 안내](../usage/installation.md)에 따라 원하는 결과를 요청합니다.

## 최초 준비와 설치 후 관리

최초 설치 전에는 대상 프로젝트에 Neurath MCP 서버가 없습니다. 이 부트스트랩은 소스의
`./setup /대상/Git-root`가 별도 도구 환경과 설치기를 준비하는 실행 인프라입니다.
Neurath 개발 저장소 자체에는 `./setup --self`를 사용합니다. 프로젝트 의존성과 개발 환경을 보존합니다.

서버가 설치·활성화된 뒤의 하네스 관리는 명명 MCP로 수행합니다.

| 목적 | 도구 | 확인 |
| --- | --- | --- |
| 준비 상태 | `session_status` | 설치·활성화·실제 모드·소유권을 별도 관측 |
| 계획 | `installation_plan` | action, 필요 시 hosts/profile/skill_prefix, 안정된 key; 요약과 계획 참조 |
| 적용 | `installation_apply` | 반환된 plan_ref와 key; 실제 적용 결과 |
| 중단 복구 | `installation_recover` | 기존 저널과 현재 파일 대조 |
| 무결성·배치 | `diagnostics_integrity`, `diagnostics_project` | 패키지 원문과 설치 위치 구분 |
| 프로토콜 | `diagnostics_project`의 protocol=true | 모의 호스트 이벤트 검사 |

계획의 action은 install/update/uninstall/restore입니다. restore에는 기존 적용의 installation_id를 사용합니다.
등록된 불변 계획만 적용하며, 기존 원문을 도구 응답으로 노출하지 않습니다. 파일 충돌은 보존하고 원인을 확인합니다.
실제 사용자 승인이 이미 해당 작업을 포함하면 같은 승인을 다시 요청하지 않습니다.

```json
{"tool":"installation_plan","arguments":{"action":"update","key":"inspect-current-update"}}
```

설치본의 도구 목록은 네이티브 호스트가 다시 로드해야 반영될 수 있습니다. 소스 변경이나 설치 성공만으로
현재 대화에 새 도구가 노출됐다고 주장하지 않습니다. 호스트 trust·인증·훅 로딩은 실제 결과로 확인합니다.

## 배포본 개발

아래는 Neurath 자체의 개발·빌드 작업입니다. 에이전트 하네스 운용 API와 구분합니다.

```sh
uv sync --locked
uv run --locked python tools/build_manifest.py
uv run --locked python tools/check.py
uv run --locked python -m build
```

실행 자산의 원본은 `src/neurath/_assets`입니다. `.agents/skills`와 `.neurath/rules`는 설치 결과입니다.
manifest 갱신, 패키지 검사, 빌드, 자기 설치를 각각 수행합니다. 대상 프로젝트의 같은 이름 패키지가
내장 엔진을 가리지 않도록 launcher는 격리된 Python 실행을 사용합니다.

## 프로젝트 바인딩과 검사

`generic` 프로필만 제공합니다. `.neurath/project.json`의 documents와 verification은 실제 대상
저장소의 지침에 연결합니다. 없는 문서나 발견만 한 도구를 검증 계약으로 만들지 않습니다.
정확한 pytest 노드를 실행하려면 프로젝트 테스트 환경을 verification.pytest.argv에 연결합니다.
이 내부 설정에는 실행 파일을 배열로 기록하며, 에이전트가 매번 하네스 CLI 옵션을 조립하지 않습니다.

등록된 명령과 작업 디렉터리를 네이티브 호스트 명령 도구로 실행합니다. 특정 pytest 검사에는 프로젝트 테스트 환경과 정확한 노드를 사용합니다. 예:

```sh
uv run --locked pytest tests/test_example.py::test_example
```

메타데이터 언어·제목 규칙·브랜치 관례는 대상 프로젝트에서 선택합니다.
작업 공간 정리는 `worktree_cleanup`의 `base_branch`와 `remote_ref`에 실제 확인한 값을 전달합니다.
자동 생성된 상태 파일을 편집하거나 소유권을 강제로 회수하지 않습니다.

도구 사용법은 [현재 명명 도구와 스키마](task-tools.md)에서 확인합니다.
배포 무결성·설치 배치·프로토콜 fixture·실제 호스트 활성화·모델 실행은 서로 다른 검증 범위입니다.
