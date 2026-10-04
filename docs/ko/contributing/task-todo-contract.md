# Task와 TODO

[English](../../en/contributing/task-todo-contract.md) · [코어 계약](core-v2-spec.md)

Task가 진행 상태의 기준이며 TODO는 네이티브 화면 표시다. 상태는 open·running·waiting·completed·withdrawn이다. 대기와 실패한 시도는 의무를 보존한다. 철회에는 실제 지시 출처가 필요하며 성공이 아니다. 의존 Task가 완료되어야 작업을 시작하거나 완료할 수 있다. native TODO를 갱신해도 phase나 인수 조건이 완료되지 않는다.

구현 참조:

- [core/domain.py](../../../src/neurath/core/domain.py)
- [core/service.py](../../../src/neurath/core/service.py)

[검증](validation.md)에서 소스 테스트·설치 프로토콜 검사·실제 호스트 동작을 구분한다.
