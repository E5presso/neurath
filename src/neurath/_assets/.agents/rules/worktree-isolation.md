# Worktree 소유권

Worktree는 공유 파일을 수정하는 자원이다. 신원은 호스트가 관측한 session/agent이며,
CWD나 파일 경로로 소유 actor를 추측하지 않는다. 같은 Git common directory의 checkout은
공통 코어 저장소에서 writer lease를 관리한다.

한 checkout에는 한 writer만 허용한다. `worktree_claim`은 실제 canonical checkout에
원자적으로 적용한다. 반환된 generation으로 release와 후속 작업을 확인하며 오래된
소유권을 재사용하지 않는다. `worktree_read`로 다른 owner를 읽을 수 있고, 읽기·리뷰·
실패 보고에는 writer lease를 요구하지 않는다.

실제 native 편집 대상과 명령의 workdir를 확인한다. 다른 linked checkout에서 일하려면
현재 actor가 그 대상을 claim하고 native 도구에 실제 경로를 지정한다. Worktree가 필요하다는
이유로 새 세션·앱 프로젝트·부모 자식 계보를 만들지 않는다.

새 worktree는 `worktree_claim(create=true)`로 없는 경로를 예약한 후 native Git 도구로
생성한다. 예약은 파일 접근 권한이 아니다. 다른 writer의 lease를 강제로 빼앗지 않는다.
담당 세션의 실제 상태를 확인하고 승인된 정상 반환·인계를 수행한다. 시간 경과만으로
살아 있는 writer를 중단시키거나 소유권을 지우지 않는다.

정리 전에 필요한 결과를 보존한다. Worktree 제거 뒤에는 보존된 canonical 경로와 generation으로
lease를 반환한다. 종료 기록을 남기려고 삭제된 checkout을 다시 만들거나 정리를 반복하지 않는다.

Lease는 호스트 권한과 별개다. 게시 승인, OS sandbox, 사용자 설정을 변경하거나 우회할 수 없다.
원장은 공개 명령과 native adapter로만 변경하며 상태 파일·SQLite를 직접 편집하지 않는다.
