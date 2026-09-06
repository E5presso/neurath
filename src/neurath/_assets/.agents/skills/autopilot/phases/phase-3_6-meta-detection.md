# Phase 3.6: Meta Detection

run 자체의 automation defect를 탐지하고 fixed-point까지 회수합니다. 이 phase는
product scope를 바꾸지 않고, autopilot/process-ticket/monitor-pr/create-ticket
하네스 결함만 다룹니다.

## 원칙

- wall-clock timeout으로 stuck을 판정하지 않습니다. 상태 모순으로만 판정합니다.
- 메인 orchestrator는 exact autopilot workflow의 `StateHandle` projection, identity-keyed
  작업자의 상태 변경·종료 기록, GitHub readback, issue metadata만 단발 조회합니다.
  다른 session state나 persistence path를 탐색하지 않으며 PR 상태 반복 조회를 대신
  수행하지 않습니다.
- 실제 harness defect는 `.agents/rules/behavioral.md`의 Gap Triage를 거칩니다.
  현재 run의 merge safety 또는 automation closure를 깨면 현재 변경으로 고칩니다.
  독립 work item으로 분리할 때만 `/create-ticket`을 사용합니다.

## S1-S10 Detection Taxonomy

| Signal | 상태 모순 |
|--------|-----------|
| S1 `monitor-stuck` | `monitor_started`가 있고 PR은 mergeable/CI green인데 `merged` 또는 `failed`가 없음 |
| S2 `resume-loop` | 같은 issue에 resume worker가 2회 이상 필요함 |
| S3 `write-conflict-open-prs` | 같은 file path를 쓰는 PR 3개 이상이 동시에 open |
| S4 `workflow-state-missing-or-regressed` | registry worktree claim은 있으나 필수 작업 흐름의 실행 기록이 없거나 revision이 역행 |
| S5 `event-consumer-missing` | monitor event 또는 durable delivery가 emit됐는데 state 또는 terminal report 전이가 없음 |
| S6 `external-review-pattern` | 외부 review 또는 CI가 같은 category를 반복 지적해 local harness가 둔감함 |
| S7 `monitor-entry-idle` | PR open 후 `monitor_started` 없이 worker가 idle |
| S8 `commit-without-push` | commit/push phase ping 뒤 upstream 또는 PR readback이 없음 |
| S9 `merged-without-terminal-return` | `merged` state는 있는데 정규 terminal report가 도착하지 않음 |
| S10 `monitor-resume-idle` | `monitor_started` 뒤 router delivery 이후 재기동 없이 idle |

각 signal은 `signal`, `issue`, `evidence`, `readback_source`, `recommended_recovery`를
가진 `matched_signal_inventory`에 기록합니다.

S6 `external-review-pattern`만 반복 임계값을 사용합니다. 기본 threshold는 3이며,
환경 변수 `AUTOPILOT_BOT_VIOLATION_THRESHOLD`가 있으면 그 값을 사용합니다. 이
threshold는 시간 임계값이 아니라 반복 패턴의 증거 수입니다. threshold 미만은
ledger만 갱신하고 fix issue를 만들지 않습니다.

## Recovery

1. 회수 가능한 worker 상태 모순(S1, S7, S8, S9, S10)은 먼저 resume 또는
   terminal-return probe를 보냅니다.
2. S5는 event source ID, delivery ID, PR number, head SHA를 기준으로 exact autopilot route
   entry와 worker가 반환한 원본 작업 흐름의 실행 기록을 대조한 뒤 worker resume 또는
   terminal-return probe를 보냅니다. Main actor가 worker session에 attach하거나 다른
   workflow로 fallback하지 않습니다.
3. probe가 정규형으로 응답하면 `process_ticket_terminal_states`에 흡수합니다.
4. 응답이 없거나 동일 signal이 반복되면 `weak_or_failed_gaps`로 분류하고
   harness fix로 보냅니다.
5. metadata drift(S3, issue label/milestone/blocked-by 누락)는 GitHub readback 후
   1회 보정하고 다시 읽습니다.
6. 보정 실패 또는 반복 signal은 `/create-ticket`으로 하네스 fix child issue를
   생성하되, `task_size_audit`, `priority`, `assignee_policy`, `blocked-by`,
   `source evidence`를 포함합니다.

## Meta Fix Queue

반복 signal 또는 보정 실패로 생성된 harness fix issue는 정상 product wave에 섞지
않습니다. `meta_queue`에 넣고 다음 정상 wave 전에 별도 meta fix wave로 처리합니다.

생성 절차:

1. signal artifact를 `/create-ticket` 또는 승인된 `/plan-issues` artifact에 넘깁니다.
2. issue title은 `[Harness] autopilot self-detected: <signal>` 형식으로 시작합니다.
3. issue body에는 signal 정의, 관찰 evidence, reproduction, expected recovery,
   regression scenario, task size audit, metadata plan을 포함합니다.
4. issue 생성 후 metadata verification을 통과한 issue만 `meta_queue`에 편입합니다.
5. S6로 issue를 생성하면 ledger entry에 `fired_ticket`과 `fired_at`을 기록하여 같은
   category의 중복 생성을 막습니다.

## Metadata Verification

생성하거나 보정한 issue는 즉시 다시 읽습니다.

- milestone
- parent 또는 sub-issue relationship
- labels
- assignee
- blocked-by
- project/status
- issue body의 acceptance와 source evidence

누락되면 자동 처리 wave에 넣지 않고 `metadata_verification_failed`에 남깁니다.

## Fixed Point

`meta_queue`가 비어 있으면 다음 정상 phase로 진행합니다. 비어 있지 않으면 meta fix
wave를 정상 wave와 분리하여 처리하고, 완료 후 이 phase를 다시 실행합니다.

동일 signal이 meta fix wave 이후에도 재매치되면 수렴 실패입니다. 이때는
`blocked`로 멈추고 signal, evidence, 마지막 fix PR/issue를 보고합니다.

## Main Session Responsibility

이 검사는 worker에게 위임하지 않습니다. 메인 autopilot session이 직접 수행합니다.
worker가 종료되거나 idle 상태가 되면서 사라지는 상태를 감지하는 것이 목적이기
때문입니다.

허용되는 직접 조회:

- `StateHandle.attach`로 선택한 exact main session의 autopilot workflow projection
- identity-keyed 작업자의 실행 흐름·종료 기록
- `WorktreeRegistry`의 exact `worktree_id` claim read-back
- durable event route table 또는 delivery ledger 단발 read
- `git worktree list --porcelain`
- GitHub issue/PR 단발 readback
- issue metadata readback

금지되는 직접 처리:

- PR 상태 반복 조회를 메인이 대신 수행
- `monitor-pr`의 event consumer 책임을 메인이 가져오기
- product scope 변경을 meta fix로 몰래 처리

## 완료 evidence

- `meta_detection_result`
- `matched_signal_inventory`
- `metadata_verification_result`
- `fixed_point_result`
- `weak_or_failed_gaps`
- `meta_queue_result`
- `main_session_inspection`
