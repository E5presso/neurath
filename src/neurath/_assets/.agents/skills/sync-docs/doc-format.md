# Documentation Format

Neurath docs는 간결하고, source-backed이며, 안정적이어야 합니다.

## 필수 style

- implementation diary가 아니라 durable fact를 씁니다.
- 유용할 때 behavior를 plan, ADR, test, code에 연결합니다.
- `/plan-issues`가 제품 목적을 확정하기 전에는 product-purpose-neutral language를
  유지합니다.
- ad hoc synonym보다 glossary term을 선호합니다.
- future work를 shipped behavior처럼 문서화하지 않습니다.

## 검증 문구

검증이 중요하면 정확한 command를 포함합니다.

```bash
uv run python -m scripts.agent_harness.verification_runner pre-commit
.neurath/run verify typecheck
```
