## Delivery protocol

Monitor는 exact workflow owner와 worktree resource claim이 확인된 경우에만 delivery를
시도합니다. Owner route가 없으면 `collector-only-owner-unavailable` 상태로 event만
보존합니다.

1. Exact workflow에서 current lifecycle과 claim을 읽습니다.
2. Claimed turn이 있으면 inspector로 그 exact turn만 확인합니다.
3. Active owner 또는 active claim이 있으면 event를 mailbox에만 stage합니다.
4. Idle owner만 atomic claim을 얻습니다.
5. App-server continuation이 idle인 경우 `turn/start`를 한 번 호출합니다.
6. Active turn이면 `active-turn-deferred`로 응답하고 unbound claim만 release합니다.
7. `turn/start`가 반환한 exact turn ID만 claim에 bind합니다.
8. Wait timeout은 bound claim과 active lifecycle을 유지합니다.
9. Exact terminal turn과 matching ACK가 확인될 때만 다음 event를 처리합니다.

Event prompt에는 session ID, workflow ID, event ID, reason, exact PR/head와 처리 branch만
포함합니다. `same event prompt`를 ACK 확인 용도로 다시 생성하지 않습니다.

## Hook enforcement

Codex/Claude hooks는 다음 lifecycle을 강제합니다.

- `SessionStart`: exact owner active 전이와 monitor runtime 확인
- `PreCompact`: owner active 유지와 monitor runtime 확인
- `PreToolUse`: worktree registry의 exact owner/fencing claim 확인
- `Stop`: dirty worktree, unpublished commit, active delegation, incident, claim ACK,
  monitor 생존을 확인한 뒤 idle 전이

Managed app-server delivery는 `NEURATH_MANAGED_APP_SERVER=1`과 exact runtime identity로 native
owner와 구분합니다. Native owner와 managed delivery가 같은 claimed worktree에서 동시에
mutation을 수행할 수 없습니다.

## Review와 push

독립 review는 local worktree에서 수렴시킵니다. Focused test, 전체 harness, independent
review를 통과한 exact local head만 push합니다. 독립 review는 identity-keyed
`final-local-review` delegation과 digest-verified artifact로 기록합니다.

Publication evidence는 independent review head, local commit, pushed remote head, PR
`headRefOid`, `pr-review`의 `ai-review` status head를 같은 SHA에 결속합니다.
`pr-review`는 이 검증된 판정을 게시할 뿐 새 reviewer나 finding loop를 시작하지 않습니다.

```bash
/pr-review <PR>
```

## Monitor Event Block

Work event consumer는 reason별 live read-back 뒤 exact workflow의 matching `event_id`를 typed
ACK application으로 완료합니다. Active owner가 event를 직접 처리해도 같은 mailbox row와
ACK를 하나의 optimistic transaction으로 소비합니다.

Feature worktree CWD에서 exact occurrence를 ACK합니다.

`python3 .agents/skills/monitor-pr/scripts/acknowledge_event.py --workflow-id PROCESS_WORKFLOW_ID --event-id EVENT_ID`

Event ID를 생략하면 current workflow의 latest occurrence를 선택하지만, routed delivery를
처리할 때는 stale occurrence 혼동을 막기 위해 exact `--event-id`를 사용합니다. CLI는 live
read-back 전에 읽은 workflow revision으로 optimistic compare를 수행하며 conflict면 command
전체를 최신 workflow에서 재실행합니다.

- comments/review: `TOTAL=0`, `UNRESOLVED_THREADS_COUNT=0`
- CI: `failedChecks=0`
- dirty merge: live non-DIRTY merge state
- mergeable terminal: OPEN, CLEAN, APPROVED, checks 0/0, exact head, threads 0

Reviewer 소유 unresolved thread만 남으면 typed external wait를 기록하고 monitor를
유지합니다. GitHub observation이 바뀌면 새 delta를 mailbox에 보존합니다.

`python3 .agents/skills/monitor-pr/scripts/acknowledge_event.py --workflow-id PROCESS_WORKFLOW_ID --event-id EVENT_ID --external-wait`
