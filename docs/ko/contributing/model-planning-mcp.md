# Provider 모델 선택

[English](../../en/contributing/model-planning-mcp.md) · [코어 계약](core-v2-spec.md)

새 코어는 별도 모델 계획 진행 원장을 유지하지 않는다. 배정에 명시적인 override가 필요할 때만 모델을 선택하고 그렇지 않으면 네이티브 기본값을 유지해 실제 설정을 확인한다. 선택 가능한 모델은 실제 호스트 목록에서 확인한다. 지원하지 않는 모델의 실행 실패는 사용자 목표의 완료 근거가 아니다. 기능 제약 때문에 별도 앱 프로젝트를 만들지 않는다.

구현 참조:

- [core/provider_commands.py](../../../src/neurath/core/provider_commands.py)
- [core/provider_job.py](../../../src/neurath/core/provider_job.py)

[검증](validation.md)에서 소스 테스트·설치 프로토콜 검사·실제 호스트 동작을 구분한다.
