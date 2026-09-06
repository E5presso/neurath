---
name: implement-ui
description: 사용자가 승인한 exact canvas node를 한 surface·state에 구현하고 검증합니다. 승인 전 탐색에는 사용하지 않습니다.
intent-class: product-ui.approved-design-implement
input-authority: user-approved-canvas-node
not-for: [product-ui.art-direct, product-ui.design-mirror-sync, product-ui.roundtrip-review]
argument-hint: "<exact canvas node URL> <상주형·모바일·웹> <state>"
user-invocable: true
---

# Implement UI

중요 skill phase는 `uv run python -m scripts.skill_harness.phase_runner`로 initialize, evaluate,
advance, finalize합니다.

다음 세 값이 모두 필요합니다.

1. 사용자가 승인한 **exact canvas node** URL 또는 provider file/node identity
2. 구현할 surface: 상주형, 모바일 또는 웹
3. 구현할 실제 screen state와 sample data

하나라도 없거나 native `tool:design_canvas`가 없으면 `blocked`입니다. `visualize`, 자연어 mood,
reference screenshot 재구성 또는 다른 node로 대체하지 않습니다.

도구 선택과 runtime 변환은 `.agents/rules/tool-runtime-map.md`를 사용합니다.

`.agents/design-collaboration-policy.json`과 제품 정본을 읽습니다. Canvas에서는 exact node의 structured
design context, screenshot, variable/style와 component mapping을 가져옵니다. Repository에서는
실제로 존재하는 design source와 component contract를 읽습니다. Design source가
`clean-slate`이면 임의 token 체계를 발명하지 않고 필요한 source proposal을 gap으로 보고합니다.

Runtime-owned visual은 실제 component를 사용합니다. Canvas capture는 배치 근거일 뿐
renderer source가 아닙니다.

## 구현

- 한 번에 승인된 node·surface·state 하나를 구현합니다.
- 실제 component와 semantic token을 재사용하고 hardcoded visual value를 만들지 않습니다.
- Canvas-only proposal과 아직 없는 component가 있으면 조용히 대체하지 않고 gap을 보고합니다.
- Behavior change는 production code보다 먼저 failing 또는 characterizing test를 작성합니다.
- Browser는 `tool:browser`, mobile simulator는 `tool:native_mobile`을 사용합니다.
- Design content reset은 이 skill, collaboration policy, connector 등록과 regression
  oracle을 삭제하는 권한이 아닙니다.

Evidence는 `approved_node`, `surface_and_state`, `design_context`, `implementation_delta`,
`verification_result`입니다. 구현과 deterministic verification이 끝나면 `implemented`, 진입 조건이나
authority가 없으면 `blocked`, 구현 또는 검증이 실패하면 `failed`입니다. Visual acceptance는
이 skill의 terminal authority가 아니며 `/review-ui`로 이어집니다.
