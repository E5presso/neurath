# Commit, 독립 리뷰와 PR

승인된 변경을 현재 저장소의 commit 규칙에 맞춰 커밋한다. 최종 local HEAD와 diff를 실제로 확인한 뒤 구현에 참여하지 않은 fresh reviewer 한 명에게 `/review-code`를 맡긴다. Codex native child는 `fork_turns="none"`을 사용한다. 다른 provider의 fresh session도 필요에 따라 선택할 수 있다. 이 선택은 독립성이나 host 권한을 대신하지 않는다.

검토자는 목표·인수 조건·제약·원문·diff를 받고 14개 기준을 검토한다. 구현자의 결론을 정답으로 주입하지 않는다. 구체적인 재현과 영향을 가진 finding을 해결하고 동일 reviewer에게 변경된 head를 재검증시킨다. 새 코드가 생기면 `phase_restart`로 정해진 재작업 경로를 수행한다.

Owner는 실제 report를 읽고 정확한 subject에 대해 `assignment_accept` 또는 `assignment_reject`한다. 자기 검토, 다른 head의 결과, 일부 조사 결과는 최종 독립 리뷰를 대신하지 못한다.

검사·리뷰·local HEAD가 맞으면 승인된 push와 PR 생성을 수행한다. PR body에는 문제, 결과 동작, 실제 validation과 인수 결과를 담고 repository의 언어·metadata 규칙을 따른다. 의도한 issue 연결, labels/assignee/reviewer와 body를 read-back한다.

`publication_read`로 실제 remote head와 PR head를 확인한다. 게시 명령 접수나 local commit만으로 push/PR 성공을 보고하지 않는다. PR 생성 뒤 제공되는 앱의 PR attachment 도구가 있으면 생성한 PR을 붙인다.
