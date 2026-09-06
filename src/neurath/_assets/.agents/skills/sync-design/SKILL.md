---
name: sync-design
description: Repository token과 component mapping을 design canvas로 한 방향 동기화하고 read-back합니다. UI 탐색·구현에는 사용하지 않습니다.
intent-class: product-ui.design-mirror-sync
input-authority: repository-source
not-for: [product-ui.art-direct, product-ui.approved-design-implement, product-ui.roundtrip-review]
argument-hint: "<design file 또는 mirror 범위>"
user-invocable: true
---

# Sync Design

중요 skill phase는 `uv run python -m scripts.skill_harness.phase_runner`로 initialize, evaluate,
advance, finalize합니다.

`.agents/design-collaboration-policy.json`을 먼저 읽고, `.agents/rules/tool-runtime-map.md`의
`tool:design_canvas`를 사용하며 native provider tool이 없으면 `blocked`입니다.

## 경계

- 자동 흐름은 **repository → canvas** 한 방향입니다.
- Token·component source가 repository에 실제로 존재할 때만 읽습니다. 아직 없으면
  `repository_sources=clean-slate`로 기록하고 `no-change`로 끝냅니다.
- Canvas에서 발견한 새 값은 proposal로만 보고합니다. `explicit-user-approved-proposal-only`
  근거 없이 repository를 수정하지 않습니다.
- Existing canvas variable·component mapping을 먼저 읽고 필요한 delta만 적용합니다.
- Provider-native token·component·library mapping을 사용합니다.
- 임의 hex, spacing, type style, component를 mirror에 만들지 않습니다.
- Canvas artifact 삭제는 connector 등록 삭제 권한이 아닙니다. Connector retirement는
  별도의 명시적 사용자 결정을 요구합니다.

## 검증과 종료

동기화 뒤 canvas를 다시 읽어 repository source와 name·type·value·component identity를
대조합니다. Evidence는 `repository_sources`, `canvas_mirror_delta`, `read_back`입니다.
변경이 적용되고 read-back이 맞으면 `synced`, 차이가 없으면 `no-change`, provider나 권한이 없으면
`blocked`, mutation 또는 read-back이 실패하면 `failed`입니다.
