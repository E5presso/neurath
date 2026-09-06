# Canvas와 review

## Canvas 구성

Provider는 `.agents/design-collaboration-policy.json`이 정합니다. Canvas에는 reference,
exploration, approved node, design-system mirror와 runtime capture를 구분합니다.

- Reference: 원본과 source
- Exploration: 버릴 수 있는 editable 후보
- Approved: 사용자 선택 exact node
- Design System Mirror: repository에서 투영한 token/component
- Runtime Captures: 실제 catalog와 제품 화면

## 방향 선택

사용자는 frame을 직접 수정·복제·삭제할 수 있어야 합니다. Agent는 screenshot을 설명해 선택을
유도할 수 있지만 최종 미감, reference 충실도와 방향 승인을 대신 판정하지 않습니다.

## Runtime roundtrip

선택 뒤 구현은 `/implement-ui`, runtime 비교는 `/review-ui`가 소유합니다.

## Runtime-owned visual

Canvas에는 runtime capture·static export 또는 slot만 둡니다. 대체 renderer를 만들지 않습니다.
