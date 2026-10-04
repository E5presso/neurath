# 프로젝트 기억

[English](../../en/contributing/memory-reference.md) · [코어 계약](core-v2-spec.md)

프로젝트 기억은 출처가 표시된 체크포인트와 재사용할 학습을 보존한다. 회상한 문장은 문맥 복구를 돕지만 작업을 승인하거나 Task를 완료하거나 현재 소스 검증을 대체하지 않는다. 유지된 외부 memory 서비스는 코어 SQLite 저장소를 사용한다. 비공개 로컬 이력과 검증 로그는 공개 자산에서 제외한다.

구현 참조:

- [memory/store.py](../../../src/neurath/memory/store.py)
- [memory/learning.py](../../../src/neurath/memory/learning.py)

[검증](validation.md)에서 소스 테스트·설치 프로토콜 검사·실제 호스트 동작을 구분한다.
