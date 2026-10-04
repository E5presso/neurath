# 네이티브 호스트 통합

[English](../../en/contributing/hosts.md) · [코어 계약](core-v2-spec.md)

설치 훅은 `neurath.core.hooks`, MCP는 `neurath.core.mcp`를 명시적인 provider·공통 프로젝트 루트로 실행한다. 새로운 `_call_id`는 정확한 네이티브 호출과 MCP 요청을 연결하며 권한을 전달하지 않는다. PreToolUse가 실제 실행자·요청을 기록하고 PostToolUse가 결속을 닫는다. 읽기에는 Task나 쓰기 소유권이 필요 없다. 신뢰·권한·sandbox·사람과의 상호작용은 호스트가 관리한다.

구현 참조:

- [core/hooks.py](../../../src/neurath/core/hooks.py)
- [core/mcp.py](../../../src/neurath/core/mcp.py)
- [install/projection.py](../../../src/neurath/install/projection.py)

[검증](validation.md)에서 소스 테스트·설치 프로토콜 검사·실제 호스트 동작을 구분한다.
