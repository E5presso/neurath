# Phase 3: 사용자 선택

Reference와 후보 frame을 같은 crop과 surface 조건으로 보여 주고 사용자의 결정을 기다립니다.

- 사용자가 직접 고치면 변경된 node를 다시 읽고 screenshot으로 확인합니다.
- 선택, 부분 채택, 기각을 그대로 기록합니다.
- 선택하지 않은 상태를 score, agent preference 또는 다수결로 닫지 않습니다.
- 더 탐색하라는 답은 이전 frame을 덮어쓰지 않고 새 exploration revision으로 이어갑니다.

Phase evidence는 `user_decision`과 `approved_node_or_iteration`입니다. Exact node가 없는 승인 표현은
handoff authority가 아닙니다.
