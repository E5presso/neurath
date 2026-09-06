# Phase 2: Canvas exploration

`tool:design_canvas`에서 reference와 후보를 동시에 보며 탐색합니다.

- 같은 실제 task, state와 sample data를 유지하되 후보 topology를 먼저 고정하지 않습니다.
- Reference를 자연어 style tag로 축약하지 않고 object scale, crop, asymmetry, type silhouette,
  color area, imagery density, spacing과 edge tension을 실제 frame에서 비교합니다.
- 태블릿과 모바일은 각각 독립 frame으로 만들고 한 surface를 다른 surface의 축소판으로 쓰지
  않습니다.
- 후보는 사용자가 canvas에서 직접 이동·삭제·복제·수정할 수 있는 native layer여야 합니다.
- Production code를 쓰거나 component/token을 확정하지 않습니다.

Phase evidence는 `canvas_artifact`, `surface_frames`, `reference_comparison`입니다.
