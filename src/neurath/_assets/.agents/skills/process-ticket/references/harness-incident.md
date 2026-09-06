# Harness incident 상세 처리

`process-ticket/SKILL.md`가 incident를 감지하거나 검사·복구해야 할 때만 읽는 runbook입니다.
Runtime identity로 `StateHandle.attach`하고 exact session의 session-level typed occurrence를
선택합니다. `SkillStateStore`, path selector, raw state를 직접 수정하지 않습니다.

## Canonical commands

아래 typed application만 사용합니다. `--id`는 stable `rule_id` 또는 명시된
`occurrence_id`이며 command 결과는 다시 read-back합니다.

`uv run python -m scripts.agent_harness.harness_incident record --id STABLE_RULE_ID --symptom OBSERVED_FAILURE`

`uv run python -m scripts.agent_harness.harness_incident escalate --id STABLE_RULE_ID --summary HANDOFF_SUMMARY --reproduction-command REPRODUCTION_COMMAND`

`uv run python -m scripts.agent_harness.harness_incident resolve --id STABLE_RULE_ID --root-cause ROOT_CAUSE --harness-fix HARNESS_FIX_PATH --regression-command REGRESSION_COMMAND`

`uv run python -m scripts.agent_harness.harness_incident refresh --id STABLE_OR_OCCURRENCE_ID`

`uv run python -m scripts.agent_harness.harness_incident refresh --id OCCURRENCE_ID_ONE --id OCCURRENCE_ID_TWO --regression-command REGRESSION_COMMAND`

`uv run python -m scripts.agent_harness.harness_incident supersede --id OCCURRENCE_ID --harness-fix REPLACEMENT_PATH --regression-command REGRESSION_COMMAND`

Stop/finalize의 read-only gate는 다음 command입니다.

`uv run python -m scripts.agent_harness.harness_incident validate`

## 원인과 소유권

Live GitHub/local state로 최초 원인을 확인합니다. Ticket product/metadata 결함은 승인된
범위에서 고치고 rule, skill, hook, gate, harness script 결함은 ticket branch에서 고치지
않고 재현 command와 handoff summary를 loop owner에게 보냅니다. Escalation은 완료가 아니라
ticket owner의 Stop을 허용해 수정 소유권을 넘기는 상태입니다. 보고에는 원인,
fix/escalation, verification, monitoring을 포함합니다.

Follow-up issue는 source의 milestone, label, assignee policy, parent/blocker 관계를 상속합니다.
Metadata read-back 전에는 issue를 `spawned`나 `gaps_dispatched`에 기록하지 않습니다.

## 반복 finding 수렴

반복되는 유효 finding은 review 강도나 iteration 상한으로 숨기지 않습니다.
Role/context/capability/decision 통과·거부 검사표(`acceptance matrix`)와 최초 14개 항목을 변경 전에 확정하고,
current head의 executable reproduction이 있는 Critical만 stable finding key에 매핑합니다.
Scope나 authoritative evidence가 바뀔 때만 검사표를 다시 확정합니다. 같은 root cause의 우회 경로는
stable `rule_id` 하나와 `root_cause_deduplication` evidence로 합칩니다. 검사표 내용의 요약값(`matrix digest`), exact head,
unique finding/rule mapping,
전체 row classification, zero-blocker fixed verification이 phase runner를 통과해야 하며
label-only evidence는 거부합니다.

독립 review에는 `execution_trajectory`, canonical session/workflow snapshot, git diff locator를
전달하고 `turn_harness_audit`와 `review_acceptance_matrix`를 같은 finding identity에 결속합니다.

## Resolve admission

Resolve 전에 다음을 모두 확인합니다.

1. `root_cause`가 실패 메커니즘을 설명하고 `harness_fix`가 current worktree에 존재합니다.
2. Fix가 current branch에 commit되어 worktree/index가 clean합니다.
3. 최소 하나는 executable Python/shell gate, hook, pre-commit entry입니다. 문서나 기존 gate
   pointer만으로는 enforcement fix가 아닙니다.
4. Regression은 allowlist의 test/check entrypoint이며 임의 shell/Python, help/version,
   collect-only, no-op은 거부합니다. `unittest`/`pytest`는 test를 실행하고 pre-commit은
   `run --all-files`를 사용합니다.
5. `regression_evidence`의 `structured command receipt`(명령 실행 검증 기록)는 command, exit code 0, current HEAD,
   timezone-aware timestamp,
   output SHA-256을 보존합니다. Output digest는 audit fingerprint이며 timing 차이만으로
   실패하지 않습니다.

Stop/finalize는 exact head에서 같은 gate의 exit code 0을 재검증합니다. 수동 PASS, raw output 주장,
restart, interrupt, raw state 정리, retry는 fix evidence가 아닙니다.

## Freshness와 refresh

실행 결과에 기록된 커밋이 현재 HEAD의 조상 커밋(ancestor)이고 저장된 수정 파일의 내용이 그대로면, 관련 없는 커밋이 추가돼도
유효합니다. 수정 내용이 바뀌거나 실행 결과의 커밋이 현재 HEAD의 조상이 아니면 state/history를 직접 고치지
않고 single refresh로 stored regression을 실행해 같은 occurrence의
`evidence_refreshed_at`과 검증 결과만 갱신합니다. Open incident의 `root_cause`, `harness_fix`,
`occurrence_id`는 보존되며 resolve되지는 않습니다.

Base에 병합된 clean tracked gate는 후속 작업의 historical fix가 될 수 있지만 current exact
HEAD의 검증 결과는 새로 필요합니다. 최초 resolve는 current branch에서 바꾼 gate를 요구합니다.

## Batch refresh와 supersession

같은 변경이 여러 occurrence에 닿으면 target ID를 모두 명시하고 comprehensive regression을
한 번만 실행하는 batch refresh를 사용합니다. 모든 검증 결과를 한 optimistic commit으로
갱신하며 하나라도 stale하거나 prerequisite가 다르면 전체 batch를 거부합니다.

Resolved gate가 제거·rename됐을 때만 supersession을 사용합니다. Replacement는 current HEAD의
executable gate이고 allowlisted regression을 통과해야 합니다. Open incident와 검증 전 변경은
거부하고 이전 수정 내용과 검증 결과는 `superseded_resolution_evidence`에 보존합니다. Optimistic identity와
occurrence revision도 일치해야 합니다.

## Runtime read-back

Open/incomplete incident는 Claude와 Codex의 Stop 및 finalization을 차단합니다. `resolved` label만
붙이거나 raw state에서 occurrence를 지워 우회할 수 없습니다. `SessionStart`와 `PreCompact`는
recovery/compaction을 위해 계속 허용합니다.
