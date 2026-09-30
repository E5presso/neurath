# Worker 정리 후 최종 기록

[English](../../en/contributing/post-cleanup-finalization.md)

병합된 ticket을 정리하면 native 도구 dispatcher가 사용하던 checkout이 삭제될 수 있습니다.
이후 worker가 마지막 phase나 task 결과를 기록하지 못하더라도 실제 정리 결과는 보존됩니다.

원래 provider issuer는 살아 있는 primary checkout에서 원래 provider `run_id`와 정확한
`workflow_id`로 `worktree_finalize_read`를 호출합니다. 도구는 저장된 소유 관계에서 원본 native
session을 파생합니다. 실제 프로세스·연결 종료 기록, 원래 workflow 소유자, 정확한 cleanup
release fence를 요구하며 worker를 재개하지 않고 workflow와 task revision을 반환합니다.

먼저 issuer는 새 native 자식에게 독립적인 task 연결 검토를 위임합니다. 정확한 JSON assignment는
`{"kind":"post-cleanup-task-scope","scope":SCOPE}`이며 `SCOPE`는 `task_scopes`에서 반환한 해당
객체입니다. 검토자는 그 task의 모든 인수 조건이 완료된 workflow와 남은 최종 기록으로
충족되는지 확인합니다. `neurath.post-cleanup-task-scope.v1` schema, 정확한 `scope`, boolean
`task_matches_terminal_workflow`, 구체적인 `reason`을 artifact로 저장하고 판정을 보고합니다.
호스트가 확인한 직접 자식의 결과를 실제로 consume했고, blocking finding 없이 `pass`인 경우만
허용합니다. 같은 prompt나 동일한 goal 문구만으로 task를 workflow에 연결하지 않습니다.

이어서 issuer는 반환한 revision, 유일한 미완료 task, `task_scope_delegation_id`, idempotency key, 실제 관측한 terminal
근거 보고를 `worktree_finalize`에 전달합니다. Cleanup, 병합 상태, adaptive 근거 label은 도구가
검증된 생산자 기록에서 생성합니다. 기존 phase 근거와 adaptive 완료 검사를 유지합니다.
Typed finalization event는 실제 issuer와 원 소유자를 구분해 기록하며, phase·workflow·task
결과·복구 기록을 하나의 트랜잭션으로 저장합니다.

불변 evaluator candidate의 정확한 payload hash가 두 canonical cleanup 전이 전 원본과
일치할 때만 기존 평가 권위를 보존합니다. 정리와 마지막 phase 기록은 지시, adaptive 근거,
이전 phase 결과를 바꾸지 못합니다. 원본 권위가 바뀌면 거부합니다. 복구 도구가 생기기 전에
정리된 worker도 이 검사를 만족하는 기존 기록으로 처리할 수 있습니다.

이 경로는 checkout 재생성, branch 삭제, 정리 반복, native worker 재개, 권한 변경을 하지
않습니다. 새 claim, 재생성된 경로나 branch, 다른 issuer, 오래된 revision, 미확인 종료,
여러 미완료 task, 끝나지 않은 위임 wave를 거부합니다. 같은 key와 동일한 요청을 재전송하면
저장된 결과를 반환하고, 같은 key로 요청을 바꾸면 거부합니다.
