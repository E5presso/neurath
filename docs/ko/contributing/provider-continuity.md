# Task 연속성

[English](../../en/contributing/provider-continuity.md) · [코어 계약](core-v2-spec.md)

중단 뒤 계속하기 전에 보존된 Task와 배정 상태를 읽는다. `task_adopt`는 이전 소유자의 종료 관측과 계속하라는 지시의 인용을 확인한 뒤 Task ID를 유지하고 소유 세대를 올린다. 과거 보고를 새 검증으로 바꾸지 않는다. 수신자는 필요한 쓰기 자원을 별도로 요청한다. v1 전환 시 설치기는 원래 목표·의존성·소유권을 보존한다. 미완료 작업은 대기 상태로 들어가며 스킬 문맥을 복구해야 한다.

구현 참조:

- [core/legacy_work.py](../../../src/neurath/core/legacy_work.py)
- [install/transition.py](../../../src/neurath/install/transition.py)
- [core/service.py](../../../src/neurath/core/service.py)

[검증](validation.md)에서 소스 테스트·설치 프로토콜 검사·실제 호스트 동작을 구분한다.
