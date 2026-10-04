# 네이티브 수명과 소유권

[English](../../en/contributing/runtime-lifecycle.md) · [코어 계약](core-v2-spec.md)

네이티브 session·agent 이벤트로 실행자를 식별한다. CWD는 자원의 위치이며 사람이나 세션의 신원이 아니다. 쓰기 전에 대상 checkout의 소유권을 얻는다. 읽기와 보고에는 쓰기 소유권이 필요 없다. 세션 중단은 미완료 Task를 보존한다. 정상 Stop은 소유한 미완료 Task와 아직 반환하지 않은 배정을 확인한다. SessionEnd는 호출 결속을 닫으며 작업을 완료시키지 않는다.

구현 참조:

- [core/host_events.py](../../../src/neurath/core/host_events.py)
- [core/hook_adapter.py](../../../src/neurath/core/hook_adapter.py)
- [core/workspace.py](../../../src/neurath/core/workspace.py)

[검증](validation.md)에서 소스 테스트·설치 프로토콜 검사·실제 호스트 동작을 구분한다.
