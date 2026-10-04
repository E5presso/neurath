# Codex 이벤트 처리

[English](../../en/contributing/codex-poll-hook.md) · [코어 계약](core-v2-spec.md)

새 어댑터는 네이티브 prompt·tool·child·Stop 이벤트를 처리한다. 별도 진행 원장을 polling하거나 provider-wave 엔진을 유지하지 않는다. 새 이벤트나 구체적인 불확실성이 생겼을 때 상태를 읽는다. 대기와 진행 보고는 미완료 Task를 종결하지 않는다. 훅 설정·신뢰·실제 이벤트 전달·활성화는 각각 확인한다.

구현 참조:

- [core/hooks.py](../../../src/neurath/core/hooks.py)
- [core/hook_adapter.py](../../../src/neurath/core/hook_adapter.py)

[검증](validation.md)에서 소스 테스트·설치 프로토콜 검사·실제 호스트 동작을 구분한다.
