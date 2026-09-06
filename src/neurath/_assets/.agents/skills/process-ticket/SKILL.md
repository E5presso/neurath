---
name: process-ticket
description: 승인된 Neurath work item 하나를 분석, test, 구현, PR, monitoring, 선택적 merge까지 실행합니다.
intent-class: ticket.execute
input-authority: github-work-item
not-for: [work-item-set.execute, spec.plan]
argument-hint: "<plan path, issue number, or work item title> [--require-approval] [--auto-merge]"
user-invocable: true
---

# Process Ticket

## 자동 완결 우선

`process-ticket`의 최우선 목표는 승인된 ticket을 분석, TDD 구현, 독립 review 수렴,
commit, PR 생성, `/pr-review`, CI/review/comment 처리, durable monitor 등록까지 자동으로
진행하는 것입니다. manual merge policy에서는 모든 병합 준비를 마친
`mergeable-clean` 상태에서 사용자의 최종 병합 승인만 대기합니다. `--auto-merge` 또는
`autopilot`의 auto policy에서는 같은 gate를 통과한 뒤 Phase 8 merge와 cleanup까지
자동으로 완료합니다.

구현 가능한 review finding, review iteration 횟수, CI 재실행, comment triage,
metadata 보정은 중간 사용자 승인 사유가 아닙니다. 아래 중단 조건에 실제로 해당하지
않으면 agent가 수정, 재검증, publication, monitoring을 계속합니다.

## 결정적 phase 실행

계약이 있는 phase 작업은 하나의 required `workflow_id`에서 단계별 실행 기록으로 실행합니다.
Runtime이 주입한 session/actor identity가 먼저 존재해야 하며, agent가 state path나
session path를 고르지 않습니다.

먼저 issue, north star, phase result를 별도 read/decision step에서 확정하고 아래
`UPPER_SNAKE_CASE` metavariable를 실제 literal로 치환합니다. 각 command는 tool call의
canonical worktree `workdir` metadata와 함께 한 physical line씩 실행합니다.

- `uv run python -m scripts.skill_harness.phase_runner init --workflow-id PROCESS_WORKFLOW_ID --skill process-ticket --run-id PROCESS_RUN_ID --north-star NORTH_STAR`
- `uv run python -m scripts.skill_harness.phase_runner complete --workflow-id PROCESS_WORKFLOW_ID --phase-id PHASE_ID --status completed --summary PHASE_SUMMARY --evidence NAMED_EVIDENCE`
- `uv run python -m scripts.skill_harness.phase_runner finalize --workflow-id PROCESS_WORKFLOW_ID --terminal-state TERMINAL_STATE`

Fresh는 `init.current_phase → complete.next_phase`를 따릅니다. Resume·compaction·
conflict 때만 `uv run python -m scripts.skill_harness.phase_runner current --workflow-id PROCESS_WORKFLOW_ID`를 사용합니다.
Adaptive final은 authority refresh 후 별도 finalize하며 결과 기록 전 완료를 금지합니다.

## Tool runtime 호환성

`.agents/rules/tool-runtime-map.md`를 사용합니다. phase 파일은 `tool:<key>`로
tool action을 표현할 수 있으며, Claude Code와 Codex에서는 map을 통해 변환합니다.
종료된 session을 다시 깨워야 하는 PR monitor는 `tool:local_pr_monitor`를
사용합니다.

## Runtime과 권한 커널

모든 phase는 runtime identity가 고른 exact `session_id`와 required `workflow_id`에
결속합니다. 경로, issue 번호, 최근 시각으로 state나 owner를 추측하지 않습니다.
단독 실행은 `route_owner=process-ticket`, `terminal sink=user`, `merge_policy=manual`이고
`autopilot` worker는 각각 `autopilot`, `autopilot`, `auto`입니다. 상세 publication과
reactive monitor 절차는 Phase 5·6에서만 읽습니다.

Mutation 전 canonical worktree에서
`python3 -m scripts.agent_harness.state_cli worktree claim`을 실행합니다. Read-only
inspection은 claim과 독립적이며, mutation은 current fenced worktree claim의 exact
`(session_id, actor_id)` owner만 수행합니다.

독립 review/evaluator는 runtime이 exact immediate parent를 host-attested `DIRECT_CHILD`로
등록한 경우만 허용합니다. 이 authority가 `UNAVAILABLE`이면 blocked하며
root, serial, `SAME_SESSION` fallback을 금지합니다. 사용자 질문은 단독 owner만 직접 전달하고 worker는
typed delegation으로 route owner에게 보냅니다.

## Phase 개요

각 phase에 진입할 때 해당 phase 파일을 읽습니다.

| Phase | 목적 | 파일 |
|-------|------|------|
| 1 | work item과 의도 분석 | `phases/phase-1-analysis.md` |
| 2 | 구현 계획 작성 | `phases/phase-2-plan.md` |
| 3 | worktree 생성 또는 확인 | `phases/phase-3-worktree.md` |
| 4 | test-first 구현과 review | `phases/phase-4-review.md` |
| 4.5 | mechanical acceptance gate | `phases/phase-4_5-acceptance-grep.md` |
| 5 | commit과 PR | `phases/phase-5-commit.md` |
| 6 | CI와 review monitor | `phases/phase-6-monitor.md` |
| 7 | merge gate | `phases/phase-7-merge-gate.md` |
| 8 | merge와 cleanup | `phases/phase-8-merge-cleanup.md` |

## 실행과 publication 커널

Agent는 승인된 ticket을 end-to-end로 소유하고 test-first 구현, 검증, metadata·docs
동기화, publication을 계속합니다. 사용자에게는 blocking product decision, scope 변경,
credential, destructive external mutation, final acceptance만 요청합니다. Issue와 연결된
docs·ADR·glossary로 scope와 비목표가 닫히지 않으면 추측하지 말고 blocked로 route합니다.

PR 뒤 Phase 5·6에서 `/pr-review <PR>`, exact-head `ai-review` status, GitHub approval,
CI/review/comment live read-back을 모두 요구합니다. `--auto-merge`는 사용자 merge 승인만
대체합니다. Phase 8은 GitHub merge read-back 뒤에만 cleanup하며, 자세한 CAS·lease·parent
전파·terminal report 계약은 해당 phase 파일이 소유합니다.

## Ticket 분해 금지

실행 요청된 ticket은 임의로 child issue로 분해하지 않습니다. 사용자가
`/process-ticket #N` 또는 동등한 실행 요청을 했으면 agent의 기본 책임은 #N 자체를
승인된 scope 안에서 test-first로 완료하는 것입니다.

Issue가 parent급 또는 단일 session에서 안전하게 실행할 수 없는 scope로 보이면
그 자리에서 child issue를 만들지 말고 `blocked`로 멈춥니다. 이때 terminal
report의 `failed_reason` 또는 `notes`에는 parent급 scope, missing approval,
분해가 필요한 이유를 적고 사용자에게 다음 행동 승인을 요청합니다. `/process-ticket`
중 인접 gap dispatch로 새 issue를 만들 수 있는 경우는 현재 ticket의 acceptance와
merge safety를 깨지 않는 독립 gap에 한정합니다.
요약하면 parent급 scope는 blocked로 멈춥니다.

## 중단 조건

직접적인 spec/code 모순, 새 domain language, destructive external mutation, 사용
불가능한 credential, scope를 바꾸는 product decision이 있을 때만 중단하고
사용자에게 묻습니다.

## Typed state와 지연 로딩

Resume source는 exact runtime identity와 `workflow_id`입니다. Phase projection, operational
`SkillStateStore` evidence, delegation, incident는 각각의 typed application이 소유하며 raw
state/path selector를 사용하지 않습니다. External read-back을 CAS mutation 안에서 실행하거나
stale prepared evidence를 재적용하지 않습니다.

Phase 4는 identity-keyed delegation, content-addressed review artifact,
`execution_trajectory`, `turn_harness_audit`를 소유합니다. Phase 6은
`owner_lifecycle`, `monitor_mailbox`, `delegate-result-ready`, `final-local-review`,
`route_resume_contract`, `monitor_event_readback`, `pending_human_comments`를 소유합니다.
Worktree/root guard와 publication/monitor commands도 해당 phase 파일에서만 읽습니다.

## Gap dispatch 계약

실행 중 spec gap, code gap, harness gap, 인접 domain gap을 인지하면 `notes`나 PR
본문에만 적고 끝내지 않습니다. 각 gap은 현재 PR에서 해결했으면 `in-pr`, 독립 work
item이면 `/create-ticket`으로 생성하고 metadata read-back을 통과한 GitHub Issue
번호로 매핑합니다.

## 감지된 incident와 하네스 보강

사용자 직접 지적 또는 agent가 스스로 인지한 workflow failure는 숨기지 않고
하네스 gap으로 승격합니다. `UserPromptSubmit`의 `user-reported-harness-defect`는 같은 turn에
기록하며, self-detected case도 우회 전에 typed application으로 기록합니다. Occurrence는
stable `rule_id`와 재발별 `occurrence_id`로 구분합니다.

미해결 incident는 Stop과 finalize를 차단합니다. Product 범위 결함은 현재 ticket에서,
harness 결함은 ticket branch 밖의 loop owner가 수정합니다. Incident가 생겨
incident를 처리해야 할 때만 `references/harness-incident.md`를 읽고 그 canonical command와
admission을 따릅니다. Raw state 수정과 산문 PASS는 금지합니다.

## Terminal

Phase 8만 parent completion, cleanup, 정규 terminal report를 소유합니다. Terminal state는
`merged|mergeable-clean|failed|skipped|blocked` 중 하나이며 gap은 `gaps_detected`와
`gaps_dispatched`, review는 `review_done`, acceptance는 `acceptance_check`로 read-back합니다.
GitHub이 merge를 확인하기 전에는 `merged`를 보고하지 않습니다.
