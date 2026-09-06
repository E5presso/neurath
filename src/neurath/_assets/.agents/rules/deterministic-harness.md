# Deterministic Harness

순서와 종료를 executable contract로 통제합니다.

## Skill contract와 phase runner

중요 skill은 `.agents/skills/contracts.json`에 ordered fragments, terminal states,
phase `id`/`name`/evidence, composite `phase_file`을 선언합니다. 절차를 바꾸면 prose,
contract, regression을 함께 수정합니다.

Fresh run은 `init.current_phase`와 `complete.next_phase` 단계 실행 결과를 이어 쓰고 직후
`current`를 재호출하지 않습니다. `current`는 resume·compaction·conflict recovery에만
사용합니다. Operational final phase는 `complete --terminal-state` 한 번으로 evidence와
terminal CAS를 닫고, adaptive workflow만 authority refresh 뒤 별도 `finalize`를 유지합니다.

`UPPER_SNAKE_CASE`는 shell variable이 아니라 invocation 전에 실제 literal로 치환하는
문서 metavariable입니다. 각 줄은 canonical worktree를 tool의 `workdir`로 지정한 별도
tool call이며, command substitution, pipeline, chain, backslash continuation을 붙이지 않습니다.

Runner가 JSON 실행 결과를 수락하기 전에 phase result, advance, terminal state를 주장하지
않습니다. Failed/blocked completion에는 reason이 필요합니다. North star는 exact workflow의
최초 지시·완료 기준·비목표를 보존하는 compaction anchor이며 완료 결과가 아닙니다.
Session lifecycle은 workflow를 자동 생성하지 않고 한 session은 여러 workflow를 가질 수
있습니다.

## Universal foreground turn

Runtime과 skill 여부와 무관하게 모든 요청은 같은 outer foreground-turn application을
통과합니다. Fresh `SessionStart`는 session/root actor와 provenance 없는 active provisional
turn을 함께 만들고 세 상태를 read-back한 뒤에만 성공합니다. `UserPromptSubmit`은 그
generation을 유지하며 runtime이 실제로 제공한 turn ID와 prompt digest만 결합합니다.
활성 턴의 추가 prompt는 generation을 보존하고 revision과 최신 digest를 갱신합니다.
동일 재전달은 질문 출처까지 보존하고 서로 다른 명시적 native turn ID는 거부합니다.
Vendor turn ID는 optional provenance이지 권한이 아닙니다. Legacy exact session에 turn만
누락됐으면 `state_cli session recover-foreground-turn` typed command로 복구하며 raw state를
편집하지 않습니다. Skill workflow는 outer turn 안의 독립 inner workflow입니다.

정식 adaptive run은 현재 host-attested 직접 자식 evaluator가 있어야 init합니다.
Config 선언은 가용성 증거가 아닙니다. `state_cli adaptive preflight`는 현재 actor와
기존 평가 delegation을 읽으며, `unavailable`은 영구 미지원 판정이 아닙니다.
기존 workflow의 evaluator 경로가 없을 때 foreground `incomplete`와 reason으로
반환할 수 있으며 workflow는 ACTIVE로 보존합니다. Stop은 현재 가용성을 다시 확인하고
기존 delegation, incident, 열린 material action 의무를 그대로 검사합니다.

Runtime `Stop`은 control-return intent입니다. 에이전트의 완료 결과를 다시 요구하거나 `PreToolUse`를
continuation gate로 쓰지 않습니다. Stop은 incident, delegation, active workflow, monitor
evidence를 검사하고 exact-session fresh readback 뒤 global/turn revision CAS로 닫습니다.
검증 중 state가 바뀌면 active로 남기고 blocker가 없으면 즉시 반환합니다. Codex와 Claude
Code는 같은 application을 호출합니다.

Compaction hook은 exact `session_id`의 bounded Enclave와 허용된 workflow context만
재주입합니다. Invalid session/capability는 다른 session으로 fallback하지 않고 차단합니다.

## Composite resource와 report

Composite skill의 phase/supporting Markdown은 `SKILL.md`에서 도달 가능해야 합니다. Contract는
`phase_files_required`와 각 phase의 `phase_file`을 선언합니다. Harness는 missing phase file,
orphan Markdown, `.agents/rules/tool-runtime-map.md`에 없는 `tool:<key>`를 거부합니다.

Run report는 phase runner를 대체하지 않는 compatibility evidence입니다.
`scripts.skill_harness.run_report`는 contract 순서와 evidence를,
`scripts.skill_harness`는 static contract를 검사합니다.

## Self-detected harness incident

반복 가능한 workflow failure를 인지하면 수동 우회로 완료하지 않고
`scripts/agent_harness/harness_incident.py`로 exact session에 기록합니다. Stable `rule_id`와
재발별 `occurrence_id`를 분리합니다.

- `escalated`: ticket agent가 이관 요약과 재현 command로 loop owner에게 넘깁니다. Ticket
  branch에서 harness를 고치지 않습니다.
- `resolved`: harness owner가 root cause, durable fix path, 회귀 검사 결과를 모두
  확인한 뒤 닫습니다.

Stop과 finalize는 open/incomplete incident를 거부합니다. 해결 검증 결과는 incident
CLI가 실행한 command, exit code, current head, output digest에 결속합니다. 임의 PASS,
no-op, help/collect-only 호출은 evidence가 아닙니다. Fix path가 바뀌면 refresh합니다.

반복 independent finding이 같은 invariant를 깨면 reviewer 강도를 낮추거나 상한으로 성공
처리하지 않습니다. Point fix를 중단하고 역할·상황·사용 가능 기능·판정별 통과·거부 검사표 전체를
재검증합니다. 같은 root cause의 우회 경로는 stable `rule_id` 하나로 합칩니다.

## Bounded harness evolution

Blocking finding은 최초 검사표/finding/worktree와 같은 executable regression으로 승격하고
runner가 변경 전에 확정한 검사표 전체를 재실행합니다. `promote`는 zero blocker만, 반복 실패는 실제
blocker를 보존한 `approach_change_required`만 허용합니다. 미채택은 `no_change` 또는
`defer`입니다. 기존 incident/evaluation/phase runner를 재사용하고 새 Agent OS나 EventStore를
만들지 않습니다.

## 목표 진행 판단 기록

장기 loop는 `.agents/rules/evaluation-loops.md`의 typed state를 사용합니다. 현재 21개 semantic
skill은 `required`이고 `checkpoint`, `commit`, `create-pr`, `create-ticket`, `create-worktree`,
`finish-session`, `monitor-pr`, `update-project-status` 8개 exact operational
projection만 `not-applicable`입니다. Unknown kind는 required입니다. Required run은 first-phase initialization,
모든 phase의 current readback, last-phase 완료 결과를 요구합니다. Marker 없는 실행 중
run만 legacy이며 `await-user/change-approach/blocked/exhausted`는 success가 아닙니다.

`skill_state.adaptive_control`은 `AdaptiveControlStore`만 바꿀 수 있는 reserved namespace입니다.
Schema v5는 v4 `UserDecision`의 raw-free question/prompt provenance, typed effect,
direct-child interpretation에 store-admitted efficiency readback을 더합니다. V4/V3 non-USER
state는 읽지만 legacy USER claim은 pending입니다.

Phase/Stop/finalize는 같은 workflow revision의 decision, authority, goal, criterion을 read-back합니다.
Non-final `AWAIT_USER`는 USER acceptance만 남은 scope, Stop return은 canonical
`ASK_USER/AWAIT_USER`와 foreground `AWAITING_INPUT`, success는 externally verified `COMPLETE`만
허용합니다. 다른 adaptive action은 advance/success 권한이 아닙니다.

Evaluator는 live state가 아니라 source/target workflow revision과 payload digest를 고정한
content-addressed candidate만 읽습니다. Executable evidence는 current dirty worktree의 exact
tracked pytest node를 실행·재실행한 검증 결과이며, execution `COMPLETED`도 independent
`execution-completion` claim을 요구합니다.

변경 전에 확정한 adaptive 통과·거부 검사표는 56개 항목/189개 실행 검사, digest
`d9791e46ffa2e1c180b943adcafced9979b63327a74f40a57a30c074cc4974a7`입니다. Checker는 source에서
이를 재구성합니다. TDD와 검사표는 evidence이며 goal completion oracle이 아닙니다. 상세 결정은
`.neurath/project.json (documents 슬롯)`가 소유합니다.
