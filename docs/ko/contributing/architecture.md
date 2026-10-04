# 코어 구조

[English](../../en/contributing/architecture.md) · [코어 계약](core-v2-spec.md)

Task가 진행 상태의 단일 기준이다. 순서가 있는 SkillRun, 시도 이력과 배정을 포함한다. 코어는 상태 전이와 근거 검증을 맡고 네이티브 호스트는 권한과 도구 실행을 맡는다. Git 공통 루트의 `.neurath/local/core.sqlite3`에 Task·원문 출처·쓰기 소유권·출처가 표시된 기록을 저장한다. 목표 문장은 식별자가 아니다.

구현 참조:

- [core/domain.py](../../../src/neurath/core/domain.py)
- [core/store.py](../../../src/neurath/core/store.py)
- [core/service.py](../../../src/neurath/core/service.py)
- [core/hook_adapter.py](../../../src/neurath/core/hook_adapter.py)

[검증](validation.md)에서 소스 테스트·설치 프로토콜 검사·실제 호스트 동작을 구분한다.
