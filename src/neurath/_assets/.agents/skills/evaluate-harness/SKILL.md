---
name: evaluate-harness
description: Neurath harness에 failure scenario를 simulation하고 선언됐지만 강제되지 않는 rule을 찾습니다.
intent-class: harness.evaluate
input-authority: repository-source
not-for: [harness-prompt.optimize, source.explain]
argument-hint: "[scenario or 'recent session']"
user-invocable: true
---

# Evaluate Harness

harness가 주장하는 behavior를 실제로 막는지 test할 때 사용합니다.

## 목표와 수단의 우선순위

사용자가 요청한 결과와 기존 태스크의 완료 조건을 기준으로 유지합니다. 에이전트가 선택한
검증 시나리오·복구 방식·최적화 실험은 교체 가능한 수단이며 독립적인 완료 의무가 아닙니다.
수단을 성공시키기 위해 사용자 요구에 없던 완료 조건을 원래 태스크에 추가하지 않습니다.
반복을 연장하기 전에는 내부 실험의 진전이 아니라 원래 태스크의 어느 미달 조건이 줄었는지
확인합니다. 내부 실험에서 새 결함을 찾았다는 사실만으로 연장을 정당화하지 않습니다.
같은 수단이 진전을 만들지 못하면 그 수단을 중단하거나 교체하고 원래 태스크를 유지합니다.
검증기를 고치기 위한 변경도 원래 결과를 확인하는 데 필수인지 먼저 판단합니다. 그렇지 않으면
그 실험 변경을 철회하거나 별도로 기록하고 원래 작업으로 돌아갑니다.
사용자 목표를 실패 처리하는 판단과 에이전트가 만든 수단을 폐기하는 판단을 혼동하지 않습니다.

## 작업 목록이 있는 기본 경로

현재 사용자의 완료 조건에 필요한 실패 사례와 관련 파일만 조사합니다. 전수 비교를 명시적으로
요청하지 않았다면 전체 capability inventory, 포화 탐색, 별도 phase·평가 loop를 만들지 않습니다.
현재 요구 → 직접 실패 사례 → 관련 수정 → 종료 조건을 먼저 연결합니다. 상태 질문과 재촉은
목표 취소가 아닙니다. 새 조사를 시작할 근거로 최신 메시지를 자동 사용하지 않습니다.
소스 결함, 검증기 입력 오류, 실행 환경 문제, 외부 제약을 먼저 구분합니다. 테스트를 통과시키기
위해 테스트에 없는 제품 요구사항을 추가하거나 정상 권한 거부를 우회하도록 바꾸지 않습니다.

수정 중에는 해당 실패를 판별하는 최소 검사를 사용하고, 최종 변경을 한 번 독립 검토합니다.
후속 검토는 바뀐 부분만 다룹니다. 필요한 변경이 끝나기 전에 전체 검사를 시작하지 않으며,
전체 검사 중에는 소스를 수정하지 않습니다. 동일 기준의 완료 결과는 재사용하고 새 실행으로
표시하지 않습니다. 사용자 질문, 모델 변경, 새 key 또는 문구 변경만으로 검증을 다시 열지 않습니다.

같은 사례가 같은 제약으로 두 번 실패하면 그 세션의 재요청·복구를 중단합니다. 현재 완료 조건에
필요한 경우에만 최소 재현 또는 깨끗한 기존 격리 환경에서 한 번 확인하고, 남은 외부 제약은
미지원·미검증으로 기록합니다. 성공을 만들려고 조건·권한·작업 수를 늘리지 않습니다.
사용자가 요구하지 않은 일괄 no-retry, 추가 task 생성, 완료 전 무조건 claim 유지 조건을
검증기에 덧붙이지 않습니다. 입력 오류는 스키마대로 고치고 불확실한 효과와 권한 거부는 보존합니다.
완료한 변경과 근거를 task_resolve에 한 번 기록하며, 해결 불가능한 경로는 실패·제약으로
명시합니다. 그 경로 때문에 관련 없는 완료 작업까지 계속 열어 두지 않습니다.
failed·invalidated는 실패 이력이며 원래 목표의 취소가 아닙니다. Stop 거부를 없애려고 결과를
만들지 않습니다. 수행 가능한 나머지 원래 요구는 계속 처리하며, 막힌 조건·관측 근거·다음 행동을
구분합니다. 범위를 줄이는 결정과 사용자의 목표를 포기하는 결정을 혼동하지 않습니다.
개별 시도의 실패와 태스크의 실패를 구분합니다. 동일 세션 재시도 중단은 그 태스크의 포기가
아닙니다. 원래 완료 조건에 필요한 다른 접근과 남은 독립 작업을 계속 처리합니다.

아래 정식 평가 절차와 구조화 근거는 기존 phase workflow 복구 또는 명시적인 전수 비교에만
적용합니다. 위 기본 경로에 중복 완료 조건으로 덧붙이지 않습니다.

## 정식 평가 또는 기존 workflow 복구

정식 run을 열기 전에 `python3 -m scripts.agent_harness.state_cli adaptive preflight`로
현재 직접 자식 evaluator를 확인합니다. 미확보 상태의 init은 `EVALUATOR_UNAVAILABLE`을
반환하며 workflow를 만들지 않습니다. 이때는 state-free 검토를 보존하고 host 등록 뒤 재시도합니다.

task 목록 없이 기존 phase workflow를 실행·복구할 때만 `uv run python -m scripts.skill_harness.phase_runner`로
계약을 initialize, evaluate, advance, finalize합니다.

1. failure scenario를 정의합니다. 사용자가 "recent session"이라고 하면 current
   diff와 conversation context에서 도출합니다.
2. `AGENTS.md`, `.agents/rules/charter.md`, 직접 관련 rule 또는 skill file을
   읽습니다.
3. 명시적으로 승인된 전수 비교에서 원본 harness 또는 비교 대상의 source skill/rule/script를 inventory한 뒤
   initial full pass 뒤 delta-only pass를 반복해 `source_capability_inventory`를 만듭니다.
   마지막 delta pass의 신규 capability가 0일 때만 다음 단계로 갑니다.
   유사 문구가 있다는 이유로 covered 처리하지 않습니다.
4. 독립 평가 전에 identity/role, execution context, tool capability, expected decision의
   통과·거부 검사표(`acceptance matrix`)를 작성합니다. Failure scenario와 직접 관련된 허용·거부 조합을
   모두 항목으로 만들고 검사표를 확정한 뒤 구현과 평가를 시작합니다.
   TDD는 이 mechanical boundary를 Red → Green으로 구현하지만 semantic goal oracle은
   아닙니다. Property/integration, 독립 outcome/trajectory, source/user evidence를 해당
   criterion의 declared authority에 따라 별도로 평가합니다.
5. 독립 평가자 sub-agent를 최소 1명 세워 self-confirmation bias를 차단합니다.
   평가자에게는 "완료 판정"을 유도하지 말고 missing capability, weak gate,
   prose-only rule, checker gap만 찾게 합니다. 평가자를 먼저 dispatch하고 report를 기다립니다.
   평가자 보고서가 아직 없다는 이유만으로 작업을 종료하지 않습니다. 현재 단계를 유지하고
   `blocked|failed`로 바꿔 닫지 않습니다. 정식 완료 근거는 runtime host가 부모-자식 관계를
   확인한 바로 아래 자식(`HOST_ATTESTED`, `DIRECT_CHILD`) → fresh candidate 작성 → exact
   assignment → child read/report → owner consume 순서로만 만듭니다. 관계를 확인할 수
   없으면 상태에 권한을 기록하지 않는 검토(`state-free review`)로만 참고하고 정식 완료 근거로
   쓰지 않습니다.
6. 기대 agent behavior를 file reference와 함께 trace합니다.
7. enforcement를 분류합니다.
   - strong: external gate 또는 explicit workflow가 failure를 막음
   - weak: rule은 있으나 self-judgment에 의존
   - failed: 현실적으로 failure를 막는 경로가 없음
8. weak 또는 failed case에는 gap을 닫는 가장 작은 external gate, skill change,
   rule pointer를 제안합니다.
9. 정적 harness 보강은 rules/skills 문구만으로 완료하지 않습니다. 결정론적
   executable gate(`scripts/`, `.codex/hooks`, `.pre-commit-config.yaml`)와 그 gate의
   regression test를 먼저 제시합니다. rules/skills는 토큰 낭비를 줄이는 guidance일
   뿐 enforcement가 아닙니다.
10. edit했다면 `uv run python -m scripts.agent_harness.verification_runner pre-commit` 또는
   `pytest --node <exact-public-node>`/관련 closed harness profile을 실행합니다.

## 자기개선 회차

반복 평가와 source discovery 전에 `references/convergence.md`의 수렴 계약을 읽습니다.

각 회차의 자원 판정은 같은 goal/evidence basis에서 정본을 연속해 다시 읽은 결과
(`consecutive authoritative readback`)로 계산한 goal delta와 runtime이 사용 가능하다고
확인한 자원 묶음(`runtime-admitted resource vector`)을 분리해
보존합니다. Evidence settlement/blocker resolution은 namespaced exact set으로 비교하고
새 blocker는 regression으로 보며 두 종류를 scalar로 환산하지 않습니다. Missing
telemetry는 0이 아니라 측정값을 사용할 수 없음(`UNAVAILABLE`)이고, 일부 현재 항목만
확인됐으면 부분 확인 상태(`PARTIALLY_PROVEN`)로 보존합니다. 같은 goal/evidence/resource
basis와 사용할 수 있는 항목이 정확히 같은 표시값(`exact availability mask`)을 공유할 때만
임의 가중합 대신 어느 한쪽도 더 나쁘지 않은지 비교합니다(`Pareto dominance`).
자원 효율 검사표는 실행 기록의 형식과 버전 연속성을 검사합니다.
그 검사만으로 실행 기록이 실제 호스트에서 나왔다는 사실을 증명하지는 않습니다.

하네스 파일은 현재 소유권과 사용자 승인 범위에서 네이티브 도구로 편집하고 검사한다.
파일 편집에 material 배치를 만들지 않는다. 검사 결과와 변경 차이를 확인한 뒤
task_resolve에 결과와 근거를 한 번 기록한다. 기존 phase workflow를 복구할 때만
아래 구조화 근거 형식을 사용하며, task 목록에 별도 phase 완료를 덧붙이지 않는다.

- `accept`: stable `rule_id` 하나에 결속한 executable gate와 regression node로 승격합니다.
- `reject` 또는 `defer`: 현재 검사표를 바꾸지 않는 근거를 남깁니다.
- 같은 접근이 동일 invariant에서 다시 실패하면 보정 patch를 더하지 않고
  `approach_change_required`로 전환합니다.
- 승격 뒤에는 최초 검사표의 모든 항목을 runner가 직접 다시 실행합니다. 새 회차가
  기존 allow row를 깨뜨리면 개선이 아니라 regression입니다. Agent가 적은 `command`와
  `exit_code` 문자열은 실행 결과로 인정하지 않습니다.

마지막 phase는 `harness_evolution_result`를 요구합니다. `action=promote`는 exact finding
전체와 실제 harness path, 실행 가능한 regression test node를 함께 제시해야 하며, prose
제안이나 존재하지 않는 경로로는 완료할 수 없습니다. `no_change`, `defer`,
`approach_change_required`는 변경 경로를 가장하지 않습니다.

## 반복 finding 수렴 계약

탐지는 넓게, 현재 작업의 조치는 좁게 유지합니다. 독립 평가자는 예상 밖 문제를 폭넓게
찾지만, current goal을 깨는 재현 가능한 blocker만 현재 검사표와 수정 loop에 포함합니다.
그 밖의 유효 finding은 분류하되 현재 구현을 확장하지 않습니다. 검사표 항목(`acceptance matrix row`)은
사용자 목표, 승인된 acceptance 또는 실제 실패한 검증에 직접 매핑되어야 하며, 추측성
우회 경로만으로 새 row를 만들지 않습니다.

`반복되는 유효 finding`은 독립 평가자의 엄격도를 낮출 근거가 아닙니다. 현재 검사표 밖 finding이
current goal의 criterion이나 authority를 실제로 깨면 재현 node를 추가해 검사표를 다시 확정하고,
무관한 finding만 defer합니다. 같은 invariant가 같은 root와 접근에서 다시 실패하면 point fix를
중단하고 `approach_change_required`로 전환합니다. 다른 접근이 material verified goal delta를
만들 수 있으면 다음 generation을 열 수 있습니다.

- 모든 blocking finding은 current head에서 실행 가능한 test 또는 command와 기대/실제
  decision을 `finding_reproduction`으로 남깁니다. 추상적 가설만으로 실패 판정을 늘리지 않습니다.
- 같은 root cause의 여러 우회 경로는 새 독립 incident로 부풀리지 않고 하나의 stable
  `rule_id` 아래 scenario row로 합치며, 그 매핑을 `root_cause_deduplication`으로 남깁니다.
- 재평가 중 검사표 밖 finding이 current goal criterion 또는 authority를 실제로 깨면 재현
  node를 추가하고 검사표를 다시 확정합니다. Current goal과 무관한 finding만 `defer`하며,
  승인된 threat model 밖의 새 trust infrastructure나 별도 product decision이 필요하면
  현재 run에 몰래 흡수하지 않고 사용자 authority로 반환합니다.
- `promote` 완료는 확정한 검사표의 모든 항목이 같은 worktree에서 통과한
  `fixed_matrix_verification_result`로만 판정합니다. `approach_change_required`는 같은 row를
  다시 실행해 남은 blocker 수를 숨기지 않고 기록한 뒤 terminalize합니다.

### Structured evidence format

Phase runner는 identity와 phase 간 검사표/head/worktree 일치를 검증합니다.

- `acceptance_matrix`: 변경 전에 확정했다는 표시인 `frozen=true`를 포함해
  `matrix_id=<sha256> frozen=true head_sha=<40-hex>
  worktree_sha=<64-hex>
  rows=<row-id|...> row_specs=<row:identity-role:execution-context:tool-capability|...>
  row_count=<n> decisions=<row:decision|...> row_nodes=<row@scripts/**::test_*|...>` 형식입니다. Opaque row label은 허용하지 않고
  각 row의 identity/role, execution context, tool capability를 non-empty semantic token으로
  고정합니다. `matrix_id`는 UTF-8
  `head_sha|worktree_sha|rows|row_specs|decisions|row_nodes`의 SHA-256이어야 합니다.
  각 row는 정확히 하나의
  `allow|deny|defer|fail_closed|preserve|refreeze_and_verify|terminate_then_allow` decision을
  가집니다. 모든 행의 실행 테스트를 변경 전에 고정하며, 테스트 교체는 검사표 재확정 대상입니다.
- `source_capability_inventory`: `source_sha=<40-hex>
  pass_count=<integer >= 2>
  new_capability_counts=<n|...|0> capability_ids=<id|...> capability_count=<n>
  source_files=<n> complete=true saturated=true
  manifest=<.agents/runs/<run-id>/source-inventory.json> manifest_sha=<64-hex>` 형식입니다. 첫 pass와 마지막 전 pass는 새
  capability가 하나 이상이어야 하고 마지막 pass는 0이어야 하며, capability 수는 pass별 신규
  수의 합과 정확히 같아야 합니다. Pass 수는 고정하지 않습니다.
  Manifest v1은 exact current HEAD, harness 파일별 path/kind/sha256/executable, capability별
  `{id, source_paths, gate_paths, regression_nodes}`를 보존합니다. Gate 없는 guidance는
  gate_paths/regression_nodes 빈 목록을 허용합니다. Runner는 파일 bytes와 source/gate 참조,
  pytest node 존재를 검사합니다. Pass count, new capability count, saturated는 조사 기록이며
  실제 의미적 포화나 capability completeness의 증거가 아닙니다.
- `worktree_sha`는 ignored runtime state를 제외한 tracked/untracked current file byte와 HEAD의
  SHA-256입니다. 검사표와 검토자의 평가 결과는 검사표 확정 시점 worktree를 공유하고, 수정 후의 검증 결과와 개선 평가 결과는 검증 시점 current worktree를 공유합니다. 같은 HEAD에서도
  source 또는 test byte가 바뀌면 기존 검증 결과는 무효입니다.
보고·재현 준비에는 `references/verification-evidence.md`를 읽습니다.
검증과 마지막 phase를 시작하기 전에 같은 원문의 fixed/evolution 형식을 확인합니다.

## 필수 evidence

- `failure_scenario`
- `source_capability_inventory`
- `acceptance_matrix`
- `project_mapping`
- `independent_evaluator_report`
- `finding_reproduction`
- `root_cause_deduplication`
- `enforcement_classification`
- `weak_or_failed_gaps`
- `patch_recommendation`
- `deterministic_enforcement_gate`
- `rules_skills_guidance_only`
- `verification_result`
- `fixed_matrix_verification_result`
- `harness_evolution_result`

대상 프로젝트가 실제로 채택한 검증·명명·작업 추적·격리·프레임워크 정책과
현재 실행이 일치하는지 확인합니다. 채택하지 않은 정책을 기본값으로 강제하지 않습니다.
