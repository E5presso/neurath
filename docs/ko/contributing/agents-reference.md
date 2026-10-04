# 에이전트 실행 참조

[English](../../en/contributing/agents-reference.md) · [코어 계약](core-v2-spec.md)

재개 시 `session_status`와 `task_list`를 읽는다. 보존된 입력과 관측 가능한 인수 조건으로 Task를 정의하고 반환된 ID·revision으로 시작한다. 해당 스킬을 시작해 현재 phase를 따르고 native TODO projection을 표시한다. 편집과 검사는 네이티브 도구로 수행한다. 필요한 근거로 각 phase를 완료한 다음 사용자 인수 조건에 따라 Task를 완료한다. 실패한 시도와 경과 시간은 사용자 목표를 완료시키지 않는다.

구현 참조:

- [core/service.py](../../../src/neurath/core/service.py)
- [core/tool_schema.py](../../../src/neurath/core/tool_schema.py)

[검증](validation.md)에서 소스 테스트·설치 프로토콜 검사·실제 호스트 동작을 구분한다.
