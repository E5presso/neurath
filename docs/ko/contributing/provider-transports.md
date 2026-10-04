# Provider 실행

[English](../../en/contributing/provider-transports.md) · [코어 계약](core-v2-spec.md)

`provider_prepare`는 명시적으로 선택한 session 또는 cross-provider 배정을 네이티브 호스트에서 실행할 명령을 반환한다. MCP에서 작업을 시작하거나 앱 프로젝트를 만들지 않는다. Codex는 app-server 전송을, Claude는 Agent SDK를 사용한다. 호스트 설정을 보존하고 실제 모델·네이티브 완료를 관측하며 연결이 끊기면 무작정 재시도하지 않는다. 사람을 대신해 대화형 권한 요청에 답하지 않는다. 네이티브 서브에이전트는 호스트의 생성·재개 도구를 사용한다.

구현 참조:

- [core/provider_commands.py](../../../src/neurath/core/provider_commands.py)
- [core/provider_job.py](../../../src/neurath/core/provider_job.py)
- [providers/stdio.py](../../../src/neurath/providers/stdio.py)
- [providers/environment.py](../../../src/neurath/providers/environment.py)

[검증](validation.md)에서 소스 테스트·설치 프로토콜 검사·실제 호스트 동작을 구분한다.
