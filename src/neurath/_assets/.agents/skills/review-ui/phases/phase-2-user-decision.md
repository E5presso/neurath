# Phase 2: 사용자 시각 결정

사용자에게 approved node와 runtime capture가 나란히 있는 canvas를 보여 줍니다.

- 사용자가 승인하면 exact node·runtime revision과 `user_acceptance`를 기록합니다.
- 수정 요청이면 어느 frame이 어떻게 바뀌어야 하는지 comment/node change를 보존하고
  `revision-requested`로 끝냅니다.
- 사용자가 canvas를 직접 수정하면 새 node/revision을 다음 implementation authority로 사용합니다.
- 답이 없거나 agent가 좋아 보인다고 판단한 것만으로 `accepted`를 만들지 않습니다.

Phase evidence는 `user_acceptance`이며 값은 승인, 수정 요청 또는 미결 중 하나입니다.
