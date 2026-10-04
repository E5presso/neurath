# 병합과 정리

Task가 요구하는 delivery를 확인한다. 병합까지 요청받았으면 현재 head의 승인과 모든 gate를 확인하고 같은 head에 조건부로 merge한다. 명령 실패 뒤에도 원격 merge가 이미 성공했을 수 있으므로 실제 GitHub 상태를 먼저 읽고 같은 merge를 맹목적으로 반복하지 않는다.

`publication_read(publication_kind="pr-merge")`로 실제 merged/head를 확인한다. 연결 issue와 project status를 읽고, parent issue가 있으면 모든 child 완료 여부를 확인한 뒤에만 parent 완료를 전파한다. 남은 child는 명시한다.

PR 준비만 요청받은 정의된 `pr-ready` 경로는 실제 PR/head와 인계 결과를 확인한다. 원래 Task가 merge를 요구하면 이 경로로 완료할 수 없다.

정리는 surviving checkout에서 native Git로 수행한다. 변경된 기본 branch를 함부로 덮어쓰지 않고 실제 base branch·remote ref·clean 상태를 확인한다. 기본 checkout을 갱신할 때는 실제 checkout을 fast-forward한다. 단지 ref만 이동시켜 파일과 HEAD를 어긋나게 하지 않는다. 삭제할 topic branch는 관측한 expected old OID와 비교하여 바뀐 ref를 보존한다.

사용자 파일, 필요한 ignored 산출물과 미완료 작업을 보존한다. 제거할 worktree의 실제 경로와 소유권을 확인한다. 삭제 뒤에도 `worktree_release`는 반환된 canonical 경로와 generation으로 호출할 수 있다. 정상 반환·보고는 source checkout의 존재나 writer claim에 종속되지 않는다. 성공한 cleanup을 반복하거나 기록을 끝내려고 checkout을 재생성하지 않는다.

Writer는 자기 lease를 반환한 뒤 실제 결과를 보고한다. Owner는 위임 결과를 읽고 수락하며 모든 phase와 사용자 인수 조건이 충족될 때 `task_complete`한다. failed/blocked/cancelled attempt는 원래 사용자 요구의 성공이 아니다.

최종 보고에는 실제 delivery 상태, PR/issue, 검증·독립 리뷰, merge/cleanup 결과와 남은 요구를 적는다. 관련 없는 개선 issue를 만들거나 실패를 숨기지 않는다. 승인된 범위에 필요한 gap은 해결하거나 실제 후속 work item에 연결한다.
