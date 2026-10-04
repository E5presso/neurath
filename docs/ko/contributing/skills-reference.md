# 스킬 순서 계약

[English](../../en/contributing/skills-reference.md) · [코어 계약](core-v2-spec.md)

`core-skills.json`이 배포 스킬과 순서가 있는 phase를 정의한다. 스킬을 시작하면 정의의 스냅샷을 Task에 저장한다. `phase_complete`는 현재 phase와 필요한 결과만 받는다. 중첩 스킬은 미리 선언해야 하며 완료 후 미완료 부모 phase로 돌아온다. 조건 분기는 정의에 명시하고 복구는 새 시도를 기록해 선언된 재시작 지점을 따른다. 스킬 완료와 사용자 Task 인수 조건은 각각 충족해야 한다.

구현 참조:

- [_assets/.agents/skills/core-skills.json](../../../src/neurath/_assets/.agents/skills/core-skills.json)
- [core/skills.py](../../../src/neurath/core/skills.py)
- [core/domain.py](../../../src/neurath/core/domain.py)

[검증](validation.md)에서 소스 테스트·설치 프로토콜 검사·실제 호스트 동작을 구분한다.
