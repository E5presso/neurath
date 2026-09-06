---
name: optimize-harness
description: AGENTS.md와 .agents/rules·.agents/skills가 모델에 주입하는 prompt token을 capability와 deterministic enforcement를 보존한 채 줄일 때 사용합니다. 개인 memory pattern 승격, 일반 harness behavior 변경, product/domain 결정, workflow typed-state 축소에는 사용하지 않습니다.
intent-class: harness-prompt.optimize
input-authority: repository-prompt-surface
not-for: [personal-memory-pattern.promote, harness.evaluate, source.refactor]
argument-hint: "[target path]"
user-invocable: true
---

# Optimize Harness

Repository prompt surface의 token을 줄이는 것이 주요 의도고, 현재 capability와
enforcement를 동일하게 보존해야 할 때만 사용합니다. Correctness repair나
일반 harness behavior 변경에는 사용하지 않습니다.

중요 skill phase는 `uv run python -m scripts.skill_harness.phase_runner`로
계약을 initialize, evaluate, advance, finalize합니다.

1. `AGENTS.md`, `.agents/rules`, `.agents/skills`의 실제 주입 prompt surface와
   conditional loader pointer를 `prompt_surface_inventory`로 기록하고 token 또는
   대응하는 byte/word `prompt_measurement_baseline`을 잡습니다.
2. 주입 prompt의 duplication, stale platform reference, invalid pointer, 조건부로
   늦게 읽어도 되는 상세 절차를 찾습니다. Workflow state, runtime protocol,
   product/domain decision은 최적화 대상으로 확장하지 않습니다.
3. source harness 또는 원본 repo가 있으면 `source_capability_inventory`와
   `project_mapping`을 만든 뒤 최적화합니다. 축약 과정에서 capability가 사라지면
   optimization 실패입니다.
4. SSOT를 보존합니다.
   - durable rule은 `.agents/rules`
   - workflow는 `.agents/skills`
   - compatibility는 `.claude`
   - executable check는 `scripts/` 또는 `.codex/hooks`
5. behavior를 약화하지 않는 가장 작은 edit로 duplication을 제거합니다.
   늦게 읽어도 되는 내용은 `conditional_load_projection`으로 먼저 모델링하고,
   전후 prompt 사용량은 `prompt_delta`로 기록합니다.
6. 하네스 보강 또는 최적화가 behavior enforcement를 바꾸면 rules/skills 문구만으로
   완료하지 않습니다. 결정론적 executable gate와 regression test를 보존하거나
   추가합니다. rules/skills는 guidance이며 enforcement gate가 아닙니다.
7. 최적화한 scenario에 `/evaluate-harness`를 실행하고, 그 skill이 검증한 바로 아래 자식
   평가자의 저장·소비된 보고서(`consumed direct-child report`)만 정식 evidence로 사용합니다. 평가자 보고서가 아직 없다는
   이유만으로 작업을 종료하지 않고 해당 평가 단계를 다시 이어갈 수 있게 남깁니다.
8. `uv run python -m scripts.agent_harness.verification_runner pre-commit` 또는 관련 root/package harness subset을
   실행합니다.

## 필수 evidence

- `prompt_surface_inventory`
- `prompt_measurement_baseline`
- `source_capability_inventory`
- `project_mapping`
- `conditional_load_projection`
- `prompt_delta`
- `behavior_equivalence_check`
- `deterministic_enforcement_gate`
- `rules_skills_guidance_only`
- `authoritative_pointer_readback`
- `evaluate_harness_result`
- `verification_result`

중복처럼 보인다는 이유만으로 rule을 삭제하지 않습니다. 남는 pointer나 gate가
여전히 enforce한다는 것을 증명합니다.
