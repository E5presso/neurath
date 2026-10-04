# 협업 계약

[English](../../en/contributing/collaboration-contract.md) · [코어 계약](core-v2-spec.md)

범위·난이도·필요한 호스트에 따라 `subagent`, `session`, `cross-provider`를 고른다. worker·reviewer·executor는 역할이며 실행 방식이 아니다. checkout 때문에 새 세션이나 프로젝트를 만들지 않는다. 범위가 한정된 배정을 준비하고 실제 수신자를 관측한 뒤 결과 보고를 읽어 수락하거나 거절한다. 자식의 보고가 부모 Task를 완료시키지 않는다. reviewer에는 독립 문맥이 필요하며 쓰기 소유권을 얻을 수 없다.

구현 참조:

- [core/native_delegation.py](../../../src/neurath/core/native_delegation.py)
- [core/communication.py](../../../src/neurath/core/communication.py)
- [core/provider_commands.py](../../../src/neurath/core/provider_commands.py)

[검증](validation.md)에서 소스 테스트·설치 프로토콜 검사·실제 호스트 동작을 구분한다.
