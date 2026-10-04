# 배포 자산 관리

[English](../../en/contributing/assets.md) · [코어 계약](core-v2-spec.md)

`src/neurath/_assets`의 원본을 수정한다. 설치된 스킬과 규칙은 투영본이다. 스킬에는 하나의 typed 코어 catalog를 사용한다. `tools/build_manifest.py`가 catalog index를 생성하고 필요한 버전 변경과 독립 패키지 파일 목록을 기록한다. 이전 번들 Python 스크립트 엔진은 제거했다. 설치·롤백·사용자 소유 변경 보존은 외부 서비스 테스트로 확인한다.

구현 참조:

- [install/projection.py](../../../src/neurath/install/projection.py)
- [resources.py](../../../src/neurath/resources.py)

[검증](validation.md)에서 소스 테스트·설치 프로토콜 검사·실제 호스트 동작을 구분한다.
