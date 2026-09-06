# Phase 4: 구현과 review loop

승인된 scope만 구현하고 tight review loop를 실행합니다.

## 형식화된 위임 권한 (`typed delegation authority`)

Owner helper는 runtime identity로 `StateHandle.attach`하고, 예상한 상태가 그대로일 때만
exact workflow assignment를 한 번 갱신합니다(`CAS`). Target actor는 실행 환경이 바로 위
부모를 확인한 자식이어야 합니다(`HOST_ATTESTED`, `DIRECT_CHILD`).
`hook_agent_id == target_agent_id`가 아니면 report authority가 없습니다. 사용할 수 없으면(`UNAVAILABLE`)
phase를 blocked로 닫고 root, serial, `SAME_SESSION` review로 대체하지 않습니다.

Full review는 내용의 요약값으로 다시 찾을 수 있는 세션 내부 보관물(`session-local content-addressed artifact`)에 저장하고 typed result에는 digest만
남깁니다. Owner는 assignment, actor, digest, workflow를 read-back한 뒤 consume합니다.
Review input의 `execution_trajectory`와 `turn_harness_audit`도 같은 digest에 결속합니다.

## 절차

1. failing 또는 characterizing test를 먼저 작성하거나 갱신합니다.
2. 가능하면 focused test를 실행해 기대한 실패를 확인합니다.
3. test를 만족하는 가장 작은 production change를 구현합니다.
   Harness patch가 command-line 입력이어야 하면
   `.agents/skills/process-ticket/scripts/safe_worktree_apply_patch.sh`로 mutation 전후 owner를
   다시 검증합니다.
4. focused test를 다시 실행합니다.
5. `/review-code`를 실행하고 리뷰용 단일 subagent dispatch evidence를 남깁니다.
   Local self-review는 `/review-code`를 대체할 수 없습니다. 현재 runtime에서
   subagent spawn 도구를 사용할 수 없으면 phase를 blocked로 처리하고 사용자 또는
   orchestrator에게 runtime capability gap을 보고합니다.
   `--target-agent-id`는 display 이름이나 희망 경로가 아니라 runtime에 등록된 실제
   immutable actor identity여야 합니다. Runtime이 spawn 전에 identity를 보장하면 먼저 actor를
   등록하고 assignment를 생성합니다. Identity가 spawn 뒤에만 확정되면 반환된 identity를
   등록한 직후 assignment를 생성하며, 추측 identity를 나중에 교체하지 않습니다.

   Owner command:

   `python3 .agents/skills/process-ticket/scripts/delegate_state.py --workflow-id WORKFLOW_ID begin --kind review-code --target reviewer --scope EXACT_REVIEW_SCOPE --target-agent-id IMMUTABLE_RUNTIME_ACTOR_ID --reviewed-head-sha FULL_HEAD_SHA`

   출력의 unique `delegation_id`를 exact target에게 전달합니다. Assignment는 workflow ID,
   target actor, scope, started time, 변경 전에 확정한 review 검사표를 self-contained JSON으로 보존합니다.
   하나의 shared slot, target name match, owner identity 추측은 사용하지 않습니다.
   Target Stop exemption은 `hook_agent_id == target_agent_id` exact match만 허용합니다.

   Target은 final 응답 전에 같은 workflow/delegation/target identity로 report를 제출합니다.

   `python3 .agents/skills/process-ticket/scripts/delegate_state.py --workflow-id WORKFLOW_ID submit --delegation-id DELEGATION_ID --target-agent-id IMMUTABLE_RUNTIME_ACTOR_ID --verdict pass --summary REVIEW_SUMMARY --verified-review-row C01 --verified-review-row C02 --verified-review-row C03 --verified-review-row C04 --verified-review-row C05 --verified-review-row C06 --verified-review-row C07 --verified-review-row C08 --verified-review-row C09 --verified-review-row C10 --verified-review-row C11 --verified-review-row C12 --verified-review-row C13 --verified-review-row C14 --harness-audit-evidence git_diff:sha256:DIGEST --harness-audit-evidence process_state:sha256:DIGEST --harness-audit-evidence execution_trajectory:sha256:DIGEST`

   Finding과 note는 각각 `--review-finding-json`, `--review-note-json`으로 추가합니다.
   Blocker 또는 실행 실패이면 `--verdict block|failed` 중 해당 값을 선택합니다.
   Helper는 full report를 content-addressed artifact로 저장하고 typed delegation result에
   `outcome_ref`를 결속합니다. Owner는 artifact digest와 result identity를 read-back한 뒤
   current scope에서 finding을 처리하고 다음 command로 exact result를 consume합니다.

   `python3 .agents/skills/process-ticket/scripts/delegate_state.py --workflow-id WORKFLOW_ID complete --delegation-id DELEGATION_ID --target-agent-id IMMUTABLE_RUNTIME_ACTOR_ID --outcome-ref sha256:DIGEST`

   Spawn 실패는 owner의 `abort` typed cancellation으로 닫습니다. Reported/consumed/cancelled
   lifecycle이 남아 있으므로 다른 concurrent delegation을 덮어쓰지 않습니다.
6. Critical이 남아 있고 승인된 scope 안에서 deterministic하게 수정할 수 있으면
   수정과 동일 subagent 재검증을 Critical 0개까지 자동 반복합니다. 고정 iteration
   상한을 두거나 사용자에게 중간 승인 질문을 하지 않습니다.
7. 최초 full review의 category별 invariant와 reproduction command를
   `review_acceptance_matrix`의 항목으로 변경 전에 확정합니다. 이후 신규 Critical은 그 항목과
   stable finding key에 매핑되고 current head에서 재현될 때만 blocker로 수용합니다.
   새로운 blocking criterion을 뒤늦게 추가하거나 같은 root cause를 다른 표현으로
   반복하면 blocker를 늘리지 않습니다. Scope 또는 외부 evidence 변화로 matrix 확장이
   필요하면 다시 확정한 전체 항목을 한 번에 재검증합니다. Delegate submit은 canonical
   14개 `--verified-review-row`를 모두 요구하며, blocker는 변경 전에 확정한 검사표 항목, stable key,
   reproduction tuple을 담은 `--review-finding-json`으로만 제출합니다. Warning, 수용된
   반박, 수정 완료는 처리 경로와 검증 command 본문을 담은 `--review-note-json`으로 제출하고,
   같은 stable key 또는 root cause의 중복은 거부합니다.
8. 직접적인 spec/code 모순, 새 product/domain decision, credential 문제,
   destructive external mutation처럼 skill의 중단 조건일 때만 사용자에게 묻습니다.

## Review focus

- TDD evidence가 있습니다.
- 무관한 refactor가 새어 들어오지 않았습니다.
- 제품 domain을 실수로 invent하지 않았습니다.
- 새 class name과 public method name이 `.agents/rules/domain-dictionary.md`와
  `.agents/rules/python-code.md` naming convention을 따릅니다.
- backend import boundary와 strict Python OO rule이 유지됩니다.
- documentation과 issue metadata가 구현 behavior와 일치합니다.
- review evidence는 구현 agent 본인의 local review가 아니라 독립 subagent의
  14-category verdict여야 합니다.
