# Phase 1: Runtime capture와 병치

1. Approved exact node의 provider, file, revision, surface, viewport, state와 sample data를 읽습니다.
2. 실제 runtime catalog 또는 제품 surface가 있으면 같은 조건으로 실행합니다.
3. `tool:browser` 또는 `tool:native_mobile`로 capture하고, motion이 의미를 가지면 video·key frame을
   함께 보존합니다.
4. `tool:design_canvas`로 runtime capture를 approved node 옆에 native editable frame으로 둡니다.
5. Content, hierarchy, geometry, token/component mapping, clipping과 interaction-state 차이를
   annotation합니다. 어느 쪽이 맞는지는 자동 결정하지 않습니다.

Evidence는 `approved_node`, `runtime_capture`, `side_by_side_artifact`, `difference_record`입니다.
