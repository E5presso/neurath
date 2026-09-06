---
name: promote-memory
description: private/personal memory에서 여러 session에 걸쳐 반복 확인된 사용자 선호나 작업 pattern을 privacy-safe하게 검토하여 대상 프로젝트의 적절한 durable owner 후보를 제안하거나, 사용자가 repository 반영을 승인하면 해당 owner로 승격할 때 사용합니다. 제안-only 요청에서는 repository를 수정하지 않습니다. prompt token 최적화, 일반 harness cleanup, 제품 memory architecture 설계, workflow typed-state 보존에는 사용하지 않습니다.
intent-class: personal-memory-pattern.promote
input-authority: private-personal-memory
not-for: [harness-prompt.optimize, docs.route, knowledge-graph.project]
argument-hint: "[feedback|project|reference]"
user-invocable: true
---

# Promote Memory

중요 skill phase는 `uv run python -m scripts.skill_harness.phase_runner`로 계약을 initialize, evaluate, advance, finalize합니다.

`private/personal memory만 input authority`로 삼아 반복된 session lesson을 shared
project behavior로 승격해야 할 때 사용합니다. 현재 repository 분석, prompt token
최적화, 일반 docs 동기화는 결과가 비슷해 보여도 이 skill의 입력이 아닙니다.
사용자가 후보 분류와 owner 제안만 요청하면 read-only로 정지하고 contracted
promotion phase를 초기화하지 않습니다. Durable surface 반영을 승인한 범위에서만
아래 evidence와 phase contract를 적용합니다.

1. 개인 식별자나 session 전문을 포함하지 않는 `privacy_safe_memory_source`와
   둘 이상의 독립 관찰을 연결한 `recurrence_evidence`로 memory-derived pattern을
   식별합니다.
2. 어디에 속하는지 결정합니다.
   - `.agents/rules`
   - `.agents/skills`
   - `AGENTS.md`
   - scripts/static 또는 e2e harness
   - docs 또는 ADR
3. 새 prose를 추가하기 전에 `existing_repository_coverage`로 기존 owner와 중복을
   확인합니다.
4. 가능하면 executable gate를 추가합니다.
5. 승격할 owner와 변경 범위를 `promotion_target`, `harness_update_plan`으로
   명시하고, private detail이 durable surface로 새지 않았음을
   `private_detail_removal_check`로 확인합니다.
6. 승격한 behavior에 `/evaluate-harness`를 실행하고
   `evaluate_harness_result`를 남깁니다.

## 필수 evidence

- `privacy_safe_memory_source`
- `recurrence_evidence`
- `existing_repository_coverage`
- `promotion_target`
- `private_detail_removal_check`
- `harness_update_plan`
- `evaluate_harness_result`

private session history를 durable rule에 붙여 넣지 않습니다. 일반 behavior로
증류합니다.
