# 평가 보고서와 검증 evidence

rule_id: harness-evaluation-verification-v1

독립 평가 보고서 수신, finding 재현, 검증, 마지막 phase에서 해당 형식을 읽습니다.
초기 matrix/head/worktree의 권위와 phase 순서는 SKILL.md 및 phase runner가 소유합니다.

- `independent_evaluator_report`는 self-attested evaluator label이 아니라
  `delegation_id`와 `outcome_ref` pointer를 제출합니다. Runner는 current workflow owner의
  direct-child delegation이 reported artifact와 일치하고 consumed됐는지 read-back합니다.
- `finding_reproduction`: 같은 `matrix_id`, `head_sha`, `worktree_sha`, unique `finding_ids`,
  `reproduced=true`, 실행한 `commands`, `expected_actual_pairs`, 각
  `finding:row:expected:actual:command-sha256`의 `reproduction_specs`를 남깁니다. Expected는
  변경 전에 확정한 검사표의 decision과 같아야 하고 evaluator의 blocker count는 expected/actual mismatch
  수와 같아야 합니다. 각 finding은 `finding@<scripts/**::test_*>` 형식의
  `reproduction_nodes`로 실행 가능한 regression identity에도 결속합니다.
  각 node는 해당 frozen row의 node와 같아야 합니다.
  Runner가 재현 node를 실제 실행하고 JUnit의 testcase 결과를 함께 확인합니다.
  정상 PASS는 expected/actual 일치, 실제 test-call FAILURE는 mismatch이며,
  setup·수집 오류, skip, timeout, 결과 파일 부재는 재현 증거가 아닙니다.
  보고서의 blocker ID는 재현 mismatch finding ID의 exact set과
  같아야 합니다. Finding이 0개면 finding_ids/reproduction_specs/reproduction_nodes와 dedup
  관련 목록은 `none`, `commands=0 expected_actual_pairs=0`, 보고서 blockers는 빈 목록으로
  기록하고 `no_change`를 판정할 수 있습니다.
- `root_cause_deduplication`: 같은 finding 전체를 unique stable `rule_id` 목록에 매핑하고
  `mapped=true`, 각 `finding:stable-rule`의 `dedup_specs`를 남깁니다. Finding/rule 목록과
  mapping 양쪽이 정확히 일치해야 합니다.
- `enforcement_classification`: 변경 전에 확정한 검사표 항목 전체를 중복 없이
  `strong_rows`, `weak_rows`,
  `failed_rows`에 분류합니다. 빈 분류는 `none`입니다.
- `fixed_matrix_verification_result`: 같은 matrix/head와 current `worktree_sha`, row 전체,
  각 `row@<scripts/**::test_*>`의 `row_nodes`를 요구합니다. 전체 매핑은 최초 검사표와 같아야 하며
  Runner가 모든 node를 실행합니다. `result=pass`는 `blocking_findings=0`이어야 하고,
  `result=approach_change_required`는 실제 실패 node 수와 같은 양수 blocker를 요구합니다.
- `verification_result`: runner 실행 결과와 동일한 matrix/head/worktree/result/row/blocker
  read-back이어야 합니다. 임의 shell command 문자열은 실행 evidence가 아닙니다.
- `harness_evolution_result`: 같은 matrix/head/current-worktree/finding 전체와
  `action=promote|no_change|approach_change_required|defer`를 기록합니다. `promote`이면
  repository에 실제로 존재하는 harness path와 `scripts/**::test_*` regression node를
  요구합니다. Promotion node는 최초 `reproduction_nodes`와 같고, 그 finding에 해당하는
  확정 검사표 항목이 검증 결과에서 실행한 node와도 같아야 합니다. 무관한 통과 test로 node identity를
  바꾸는 것은 승격이 아닙니다.

Git repository가 있으면 `head_sha`는 phase 실행 시점의 exact `HEAD`와 일치해야 합니다.
