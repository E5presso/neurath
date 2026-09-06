# Phase 6: CI와 review monitor

PR의 최종 remote head를 검증하고, local PR monitor가 reactive continuation을
소유하도록 등록합니다.

이 phase의 publication authority는 exact-head `final-local-review` artifact입니다.

## 진입 조건

- Phase 5 publication evidence가 완료되어 있습니다.
- Worktree가 clean합니다.
- Local HEAD, pushed head, PR `headRefOid`가 일치합니다.
- Independent local review가 같은 local head를 통과했습니다.
- Runtime-owned session actor가 shared worktree resource의 current fenced owner입니다.
- Required `workflow_id`가 같은 session에서 active입니다.

## 리뷰 승인

1. 로컬 검토 결과의 exact head와 PR `headRefOid`를 비교합니다.
2. 두 SHA가 일치할 때만 `/pr-review <PR>`를 실행해 검증된 local verdict를
   게시합니다. 이 단계에서 새 reviewer나 새 finding loop를 시작하지 않습니다.
3. `pr-review` result head, 게시된 `ai-review` commit status head,
   PR `headRefOid`를 다시 비교합니다.
4. 실행 결과와 커밋 검증 실패는 local worktree에서 수정·검증·재검토합니다.
5. 변경이 생기면 새로운 final local commit을 만들고, independent local review를
   다시 통과한 뒤 한 번 push합니다.
6. `ai-review=SUCCESS`와 GitHub `reviewDecision=APPROVED`를 모두 read-back합니다.

## Monitor route 등록

Monitor는 current worktree에서 runtime identity와 exact workflow에 attach합니다. Public CLI에
state path나 worktree path를 전달하지 않습니다.

`python3 .agents/skills/monitor-pr/scripts/local_pr_monitor.py --repo OWNER/NAME --pr-number PR_NUMBER --workflow-id WORKFLOW_ID --runtime-id MONITOR_RUNTIME_ID --poll-interval-seconds 30`

Command 기반 continuation을 쓸 때만 `--resume-command "<command>"`를 추가합니다.

Background process manager는 이 exact command와 runtime ID를 소유하고 live PID,
`heartbeat_at_epoch`, repo, PR, session ID, workflow ID를 read-back합니다. Agent는 launcher의
내부 observation 파일을 subscription identity로 전달하지 않습니다. Read-back이 끝나면
manager가 반환한 typed objects를 그대로 결속하고 다음 command로
`monitor_event_subscription`과 `monitor_started` 처리 결과를 기록합니다.

두 JSON 처리 결과는 각각 별도 tool result에서 읽은 뒤 한 physical line의 direct command로 전달합니다:
`python3 .agents/skills/process-ticket/scripts/process_state_evidence.py --workflow-id WORKFLOW_ID --field monitor_event_subscription --value-json MONITOR_SUBSCRIPTION_JSON` 및
`python3 .agents/skills/process-ticket/scripts/process_state_evidence.py --workflow-id WORKFLOW_ID --field monitor_started --value-json MONITOR_STARTED_JSON`.

## Owner lifecycle

Exact workflow의 `SkillStateStore`에 있는 `owner_lifecycle`과 `monitor_mailbox`가 delivery
정본입니다.

- Native owner `SessionStart|PreCompact|PreToolUse`는 exact owner를 active로
  전이합니다.
- 이미 active인 native owner의 두 번째 `SessionStart`는 거부하고, 직전 activity가
  `PreCompact`인 exact context continuation만 허용합니다.
- Exact-owner Stop gate가 통과하면 owner를 idle로 전이합니다.
- Active owner에서는 event를 mailbox에만 저장합니다.
- Idle owner에서 pending event 한 건과 owner activation을 같은 optimistic CAS transaction으로
  claim합니다.
- 새 `turn/start`가 반환한 exact turn ID만 claim에 bind합니다.
- Wait timeout은 active claim을 유지합니다.
- Exact terminal turn과 matching event ACK가 함께 확인된 뒤에만 claim을 해제합니다.
- ACK가 없는 terminal turn은 recovering 상태로 유지하며 prompt를 다시 만들지 않습니다.
- Native owner의 idle 전이는 exact-owner Stop hook만 기록합니다.
- `last_observed`는 wake하지 않은 poll까지 전진시켜 직전 관찰 이후 delta만
  mailbox event로 만듭니다.

## Event 처리

Monitor event는 exact workflow mailbox의 stable `event_id`, event payload, active claim에서
read-back합니다. Local runtime observation은 delta 계산용이며 agent-facing resume source가
아닙니다.

| reason | owner 처리 |
|---|---|
| `comments-changed` | `collect_comments.sh` → `/triage-comments` → live zero read-back |
| `ci-failed` | 실패 log 확인 → local fix/test/review → final push |
| `merge-dirty` | 대상 기본 branch 최신화와 conflict 해결 → local review → final push |
| `review-blocked` | 사람의 actionable unresolved thread 처리 |
| `delegate-result-ready` | durable result 적용 → 검증 → exact outcome complete |
| `mergeable-clean` | live terminal read-back → Phase 7 |
| `merged` | merge read-back과 cleanup |
| `closed-without-merge` | closed terminal read-back |

사용자·관리자·maintainer comment는 remote command input입니다. Agent marker,
자동 review, 자동 approval, bot status는 owner wake 대상에서 제외됩니다.

## Event ACK

Work event를 처리한 뒤 exact workflow의 typed ACK application이 GitHub live state를
직접 확인하고 matching `monitor_event_ack`를 기록합니다. Runtime implementation file이나
mailbox payload를 agent가 직접 갱신하지 않습니다.

Feature worktree CWD에서 delivered occurrence의 exact event ID를 지정해 실행합니다.

`python3 .agents/skills/monitor-pr/scripts/acknowledge_event.py --workflow-id WORKFLOW_ID --event-id EVENT_ID`

CLI는 runtime identity로 `StateHandle.attach`하고 `SkillStateStore.compare_and_update`에
선택 당시 workflow revision을 제출합니다. Live read-back 도중 revision이 바뀌면 stale ACK를
적용하지 않고 non-zero로 종료하므로 latest workflow에서 command 전체를 다시 실행합니다.

`comments-changed`와 `review-blocked`:

```text
collect_comments:TOTAL=0
collect_comments:UNRESOLVED_THREADS_COUNT=0
```

`ci-failed`:

```text
ci_readback:failedChecks=0
```

`merge-dirty`:

```text
merge_readback:mergeState=<non-DIRTY>
```

`mergeable-clean`:

```text
terminal_readback:state=OPEN
terminal_readback:mergeState=CLEAN
terminal_readback:reviewDecision=APPROVED
terminal_readback:failedChecks=0
terminal_readback:pendingChecks=0
terminal_readback:headRefOid=<exact remote head>
collect_comments:TOTAL=0
collect_comments:UNRESOLVED_THREADS_COUNT=0
```

Reviewer-owned unresolved thread만 남으면 같은 typed ACK application이 external-wait를
기록합니다. Monitor는 live observation delta가 생길 때 다시 mailbox에 event를 보존합니다.

`python3 .agents/skills/monitor-pr/scripts/acknowledge_event.py --workflow-id WORKFLOW_ID --event-id EVENT_ID --external-wait`

## Terminal read-back

`mergeable-clean`은 다음 값을 모두 포함합니다.

```text
reason=mergeable-clean
state=OPEN
mergeState=CLEAN
reviewDecision=APPROVED
failedChecks=0
pendingChecks=0
headRefOid=<ai-review head>
unresolvedReviewThreads=0
```

`merged`는 `state=MERGED`, `closed-without-merge`는 `state=CLOSED`를
포함합니다.

## Terminal handoff

`monitor_event=terminal reason=mergeable-clean`은 Phase 6만의 terminal이므로
process-ticket 전체를 종료하지 않고 Phase 7로 이동합니다. Auto-merge policy에서는
Phase 8 squash merge와 cleanup까지 계속합니다.

## Evidence

- `pr_review_status`
- `ai_review_head_sha`
- `local_review_head_sha`
- `local_review_matrix_receipt`
  (`harness_audit=true audit_evidence=3` 포함)
- `session_workflow_context`
- `monitor_event_source`
- `monitor_started`
- `monitor_terminal_state`
- `route_resume_contract`
- `owner_lifecycle_readback`
- `monitor_mailbox_readback`
- `monitor_event_readback`
- `live_terminal_readback`
- `delegate_transition_receipt`
- `pending_human_comments`
- `unresolved_review_threads`
