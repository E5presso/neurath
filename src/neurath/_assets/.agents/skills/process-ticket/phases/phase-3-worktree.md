# Checkout 선택

기존 적절한 worktree가 있으면 재사용한다. 동시 작업이 같은 파일에 쓰거나 별도 branch/PR 격리가 필요한 경우 새 worktree를 만든다. 이미 승인된 현재 checkout에서 안전하게 작업할 수 있으면 그 이유를 기록한다.

새 경로를 native Git로 만들 때는 `worktree_claim(create=true)`로 없는 대상 경로를 먼저 예약하고 실제 생성 결과를 확인한다. Native app이 자체적으로 고유한 worktree를 만들면 반환된 실제 경로를 확인한 뒤 수정 전에 claim한다. 다른 writer의 경로를 강제로 회수하지 않는다.

현재 actor가 다른 linked checkout을 claim할 수 있다. 모든 수정·검사는 native 도구의 실제 workdir/파일 경로를 사용한다. 세션 신원, 환경 변수, 프로젝트 소속을 꾸미지 않는다. Workspace 선택과 에이전트 실행 선택은 별개다.

`worktree_decision`, `worktree_absolute_path`에는 선택 이유와 실제 canonical 경로를 기록한다. 작업 기록은 공통 저장소에 있으므로 checkout 제거 뒤에도 원래 Task를 읽고 보고할 수 있어야 한다.
