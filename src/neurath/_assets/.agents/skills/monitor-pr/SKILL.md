---
name: monitor-pr
description: Neurath PR 상태의 실제 변화를 보존하고 idle process-ticket owner를 정확히 한 번 깨웁니다.
intent-class: pull-request.monitor
input-authority: github-pr-state
not-for: [pull-request-comments.triage, pull-request.review]
argument-hint: "<pr-number>"
user-invocable: true
---

# Monitor PR

`monitor-pr`는 GitHub PR 상태를 polling하고 실제 변화만 exact workflow mailbox에
보존하며, 쉬고 있는 `process-ticket` owner를 깨웁니다. 실행 계획, 코드 수정, 리뷰
판단, merge 결정은 owner가 수행합니다.

## 결정적 phase 실행

Monitor skill의 phase workflow와 관찰 대상 process workflow는 서로 다른 identity입니다.
Exact runtime session 안에서 `MONITOR_SKILL_WORKFLOW_ID`를 만들고, 관찰 대상
`PROCESS_WORKFLOW_ID`를 입력으로 고정합니다.

아래 `UPPER_SNAKE_CASE` metavariable는 source workflow와 실행 기록을 먼저 읽은 뒤
actual literal로 치환합니다. 각 command는 canonical ticket worktree를 native `workdir`로
지정한 별도 tool call 한 physical line입니다.

- `uv run python -m scripts.skill_harness.phase_runner init --workflow-id MONITOR_SKILL_WORKFLOW_ID --skill monitor-pr --run-id MONITOR_SKILL_RUN_ID --north-star MONITOR_NORTH_STAR`
- `uv run python -m scripts.skill_harness.phase_runner complete --workflow-id MONITOR_SKILL_WORKFLOW_ID --phase-id PHASE_ID --status completed --summary PHASE_SUMMARY --evidence NAMED_EVIDENCE`

Fresh chain은 init의 `current_phase`와 complete의 `next_phase`를 잇습니다. Resume·compaction·
conflict recovery만 `uv run python -m scripts.skill_harness.phase_runner current --workflow-id MONITOR_SKILL_WORKFLOW_ID`를 사용합니다.

Phase runner와 monitor public CLI는 state path, session path, worktree path를 받지
않습니다. Tool action은 `.agents/rules/tool-runtime-map.md`의 stable key를 사용합니다.

## Local Monitor Contract

Provider와 runtime 명칭은 `local-pr-monitor`입니다. Public identity는 다음 값으로만
구성합니다.

- runtime이 주입한 exact `session_id`와 current actor
- caller가 명시한 source `workflow_id`
- Git이 current cwd에서 계산한 canonical `worktree_id`
- `repo`, positive `pr_number`
- non-empty monitor `runtime_id`
- positive polling interval
- optional resume command 또는 unavailable reason

`StateHandle.attach`는 exact existing session 밖으로 fallback하지 않습니다.
`WorktreeIdentityResolver`는 caller가 전달한 worktree path 대신 current cwd의 Git identity를
사용합니다. Claimed worktree의 product mutation은 shared `WorktreeRegistry`가 current
session actor에게 허용한 경우에만 가능합니다.

Process manager는 background process 생존과 재시작을 담당합니다. Monitor process는 GitHub
관찰, delta 판별, workflow mailbox 저장, idle owner wake만 담당합니다. Launcher 내부의
process-local observation cache와 log는 runtime implementation detail입니다. 이는 canonical session/workflow state,
authority source, resume source, agent input이 아닙니다.

## Owner lifecycle과 mailbox

Canonical delivery state는 exact workflow의 `SkillStateStore`에 있습니다.

```text
owner_lifecycle.state = active | idle | recovering | terminal
monitor_mailbox.pending_events
monitor_mailbox.seen_event_ids
monitor_mailbox.active_claim
```

Workflow owner actor 하나만 lifecycle을 변경합니다.

- `SessionStart`, `PreCompact`, `PreToolUse`는 native owner를 `active`로 유지합니다.
- 검증된 exact-owner `Stop`만 unpublished work와 gate를 확인한 뒤 `idle`로 전이합니다.
- reasoning, tool 실행, context compaction, delivery wait timeout은 `active`를 유지합니다.
- lifecycle에는 시간 기반 만료가 없습니다.

Monitor mailbox mutation은 `SkillStateStore.compare_and_update`를 사용하는 pure transform입니다.

1. `stage`는 stable `event_id`를 FIFO mailbox에 한 번 저장합니다.
2. `claim`은 owner가 idle일 때만 FIFO head와 owner activation을 함께 commit합니다.
3. `bind_turn`은 app-server가 새로 만든 exact turn ID를 matching claim에 결속합니다.
4. `complete_turn`은 exact terminal read-back과 matching ACK가 모두 확인됐을 때 claim을
   해제합니다.
5. Turn이 생성되지 않은 delivery만 `release_claim`으로 FIFO 앞에 되돌립니다.
6. Terminal turn에 ACK가 없으면 같은 claim과 `recovering` lifecycle을 유지합니다.

각 transaction은 먼저 original workflow revision을 읽고 compare-and-swap합니다. 충돌하면
latest state에서 side-effect-free transform을 다시 계산합니다. GitHub 조회, clock, process
launch 같은 effect는 retry 가능한 mutation 밖에서 한 번 준비하고, retry 중 prerequisite가
바뀌면 stale evidence를 적용하지 않습니다.

## Monitor 시작

실제 polling entrypoint는
`.agents/skills/monitor-pr/scripts/local_pr_monitor.py`입니다. Current ticket worktree에서
다음 public CLI를 실행합니다.

`python3 .agents/skills/monitor-pr/scripts/local_pr_monitor.py --repo OWNER/NAME --pr-number PR_NUMBER --workflow-id PROCESS_WORKFLOW_ID --runtime-id MONITOR_RUNTIME_ID --poll-interval-seconds 30`

Resume capability가 있으면 같은 command에 `--resume-command "<command>"`를 추가합니다.
없으면 `--resume-unavailable-reason resume-capability-missing`을 추가해 collector-only로
실행합니다. `--once`는 한 번의 bounded poll 검증에만 사용합니다.

Background process manager는 위 exact command를 등록하고 live PID,
`heartbeat_at_epoch`, repo, PR, session ID, workflow ID, monitor runtime ID를 read-back합니다.
macOS process manager는 generated LaunchAgent와 `launchctl bootstrap`을 사용할 수 있으며
`KeepAlive.SuccessfulExit=false`로 runtime failure만 재시작합니다. Read-back이 실패하면
성공 evidence를 기록하지 않습니다.

Source owner는 manager가 반환한 typed subscription과 시작 결과를 변형하지 않고 exact
process workflow에 결속합니다.

각 JSON 처리 결과를 먼저 읽고 다음 direct command를 별도 tool call로 실행합니다:
`python3 .agents/skills/process-ticket/scripts/process_state_evidence.py --workflow-id PROCESS_WORKFLOW_ID --field monitor_event_subscription --value-json MONITOR_SUBSCRIPTION_JSON` 및
`python3 .agents/skills/process-ticket/scripts/process_state_evidence.py --workflow-id PROCESS_WORKFLOW_ID --field monitor_started --value-json MONITOR_STARTED_JSON`.

여러 launcher가 동시에 시작돼도 exact workflow의 monitor runtime claim은 한 actor/runtime만
승리합니다. 다른 claimant는 canonical claim을 덮어쓰지 않습니다. 기존 runtime 교체는
current claim을 읽고 old process의 terminal read-back을 확인한 뒤 expected claim을 제출하는
handoff로 수행합니다.

## 실제 변화 분류

`last_seen`은 마지막으로 mailbox에 보존한 GitHub observation이고, `last_observed`는 wake
여부와 관계없이 성공한 매 poll의 observation입니다. Event에는 바로 직전
`last_observed`와 달라진 field만 `detected_change`로 포함합니다. 자동 review 중간 상태도
baseline을 전진시키므로 sticky 상태가 해소된 뒤 다시 나타나면 새 occurrence입니다.

Owner wake 대상은 다음과 같습니다.

| reason | 조건 |
|---|---|
| `comments-changed` | 사람의 새 comment 또는 수정된 comment |
| `ci-failed` | current head의 actionable check가 실패 상태로 전이 |
| `merge-dirty` | merge state가 `DIRTY`로 전이 |
| `review-blocked` | 사람의 submitted unresolved review thread identity가 변경 |
| `mergeable-clean` | OPEN, CLEAN, APPROVED, checks 0/0, unresolved thread 0 |
| `merged` | PR state가 MERGED로 전이 |
| `closed-without-merge` | PR state가 CLOSED로 전이 |
| `delegate-result-ready` | matching identity-keyed delegation이 reported로 전이 |

Comment와 review thread 분류는 author login, agent marker, review marker를 함께 검사합니다.
사용자·관리자·maintainer 입력을 보존하고 agent 진행 comment, 자동 review 출력, 자동
approval, bot status는 observation에만 반영합니다. 동일 snapshot polling은 새 event를
만들지 않습니다.

## Event 처리 전 읽기

Phase 3에서 owner wake, 전달된 event 처리 또는 ACK를 수행하기 전에
`references/event-delivery.md`를 읽습니다. Collector 시작·구독 단계에서는
이 후반 절차를 미리 읽지 않습니다.

## 종료 조건

`mergeable-clean`은 `monitor_event_readback` 뒤 Phase 7로 이어지는 상태입니다. Exact head의
review bot 신호는 GitHub `reviewDecision=APPROVED`를 대체하지 않으며 두 조건을 모두
확인합니다. Auto-merge policy에서는 Phase 8 merge와 cleanup까지 같은 owner가 계속
수행합니다.

`merged` 또는 `closed-without-merge` terminal이 exact turn에서 소비되면 monitor가 정상
종료합니다. Merge completion은 GitHub merge read-back, issue close, remote branch 삭제,
worktree 정리, 확인한 기본 branch sync로 증명합니다. 그 밖의 fatal runtime 오류는 `failed`,
missing authority/capability는 `blocked`로 보고합니다.

Phase 4는 위 command를 `complete --terminal-state MONITOR_TERMINAL_STATE` 형식으로 실행해 한 CAS에서
닫습니다. `failed`/`blocked`는 phase status도 같은 값이며, 별도 finalize는 recovery 전용입니다.

## Evidence

- `monitor_started`
- `monitor_event_source`
- `route_resume_contract`
- `owner_lifecycle_readback`
- `monitor_mailbox_readback`
- `monitor_event_readback`
- `live_terminal_readback`
- `pending_human_comments: TOTAL=0`
- `unresolved_review_threads: UNRESOLVED_THREADS_COUNT=0`
