# Phase 5: cold-read 실행 시뮬레이션

GitHub을 변경하기 전에 스펙, issue 계층, DAG, FR/SC coverage를 다른 context에서
cold-read합니다. 이 phase는 자기검토가 아니라 외부 게이트입니다.

## Tier

| Tier | 대상 | 목적 |
|------|------|------|
| T1 Spec Probe | implementation child별 1회 | 새 `/process-ticket` agent가 issue body만으로 시작 가능한지 확인 |
| T2 DAG Coherence | parent 또는 milestone 전체 1회 | blocked-by, write conflict, representative task, hidden dependency 모순 확인 |
| T3 Value Drift | milestone 또는 capability parent 1회 | FR/SC trace가 표면 매핑인지, 합쳐서 성공 기준에 도달하는지 확인 |
| T4 Grill-me Interview Replay | 자명 ticket 외 전체 1회 | 질문 순서, 권장 답안 근거, branch closure가 충분했는지 확인 |

자명한 단일 ticket도 chat history에 의존하면 생략하지 않습니다. 생략 가능한 경우는
단일 package, 단일 AC, DD delta 없음, dependency 없음, `clarification_marker=0`,
task size audit 통과가 모두 참일 때뿐입니다. 생략 사유는 `simulation_result`에
남깁니다.

## T1 Spec Probe

각 child draft를 새 `/process-ticket` agent가 실제로 받는 입력으로 시뮬레이션합니다.
세션 대화, 작성자의 의도, 저장되지 않은 설명은 입력에 넣지 않습니다.

입력:

- milestone 또는 parent issue body
- blocker issue body
- 대상 child issue body 전체
- `docs/context/`, `.neurath/project.json (documents 슬롯)`, 관련 ADR path 목록

검사:

1. `AMBIGUITIES`: 구현 전에 사용자 판단이 필요한 domain/spec gap
2. `ASSUMPTIONS`: 본문에 없지만 구현 agent가 결정해야 하는 silent assumption
3. `WHAT_I_WILL_BUILD`: issue body의 단어만 사용한 1-2단락 구현 진술
4. `EXISTING_ASSET_HITS`: 동일 산출물, class, function, DTO, endpoint, event 존재 여부
5. `VERIFICATION_MANDATES`: 결과 명제가 아니라 별도 CI, PR 본문, 수동 리뷰 같은 검증 수단을 강제하는 문구
6. `UNREGISTERED_TERMS`: DD에 없는 새 noun/action verb

출력은 다음 key를 반드시 포함합니다.

```text
AMBIGUITIES: [...]
ASSUMPTIONS: [...]
WHAT_I_WILL_BUILD: "..."
EXISTING_ASSET_HITS: [...]
VERIFICATION_MANDATES: [...]
UNREGISTERED_TERMS: [...]
CONFIDENCE: HIGH|MEDIUM|LOW
```

`AMBIGUITIES`, `ASSUMPTIONS`, `EXISTING_ASSET_HITS`, `VERIFICATION_MANDATES`,
`UNREGISTERED_TERMS` 중 하나라도 비어 있지 않거나 `CONFIDENCE=LOW`이면 검토
후보입니다.

## T2 DAG Coherence

parent/milestone 단위로 전체 child body, dependency graph, write conflict matrix,
critical path, parallel groups, FR coverage를 입력합니다.

검사:

1. 후행 ticket이 선행 ticket이 약속하지 않은 DTO, API, event, table, file을 가정하는가
2. 대표 task가 실제로 후행 task가 의존하는 산출물을 만드는가
3. 본문상 implicit dependency가 있는데 `blocked-by` 또는 critical path에 없는가
4. 모든 child가 병렬 가능하다고 주장한다면 `all_parallel_approval`과 write conflict
   evidence가 충분한가
5. 외부 계약 변경이 scope/ADR/parent body에 승인되어 있는가

출력은 다음 key를 반드시 포함합니다.

```text
DAG_PARADOXES: [...]
REPRESENTATIVE_MISMATCHES: [...]
MISSING_BLOCKERS: [...]
WRITE_CONFLICT_MISMATCHES: [...]
EXTERNAL_CONTRACT_CHANGES: [...]
CONFIDENCE: HIGH|MEDIUM|LOW
```

## T3 Value Drift

FR/SC trace와 child issue acceptance를 비교합니다.

검사:

1. 각 SC가 observation point, target, expected value를 갖는가
2. 매핑된 child가 모두 끝나면 SC를 실제로 관찰할 수 있는가
3. `기여 SC`로만 적혀 있고 child acceptance가 SC를 검증하지 않는 표면 매핑이 있는가
4. product intent가 약속한 변화 중 SC가 검증하지 않는 부분이 있는가

출력은 다음 key를 반드시 포함합니다.

```text
UNREACHABLE_SC: [...]
SUPERFICIAL_MAPPINGS: [...]
INTENT_GAPS: [...]
CONFIDENCE: HIGH|MEDIUM|LOW
```

## T4 Grill-me Interview Replay

Phase 0~3의 질문, 답변, 자율판정, Decision Branch Ledger를 다른 context에서 다시
읽힙니다. T1은 issue body 관점이고, T4는 계획 인터뷰 관점입니다.

입력:

- 초기 사용자 요청
- 실제 질문/답변 기록: Q-ID, 권장 답안, 사용자 선택, 근거, 재질문 여부
- 자율판정 기록: 질문하지 않고 판단한 항목과 evidence
- open question queue와 deferred-by-evidence 항목
- Decision Branch Ledger
- Phase 2.5 spec 요약
- Phase 3 work item 분해 요약

검사:

1. 구현 전에 닫혀야 하는 architecture, domain model, API contract, data flow,
   UX/surface, error policy, compatibility, rollout, test/docs branch가 빠졌는가
2. 후행 결정을 먼저 묻고 upstream 결정을 나중에 묻는 등 질문 순서가 dependency를
   거슬렀는가
3. 권장 답안이 code, docs, prior issue, web research 같은 근거 없이 제시됐는가
4. 사용자가 승인하지 않은 권장 답안이 spec에 반영됐는가
5. 코드나 문서로 답할 수 있는 낮은 granularity 질문을 사용자에게 물었는가
6. 답변이 추상적인데 같은 Q-ID로 재질문하지 않고 닫았는가

출력은 다음 key를 반드시 포함합니다.

```text
MISSING_BRANCHES: [...]
BAD_ORDER: [...]
UNSUPPORTED_RECOMMENDATIONS: [...]
OVER_QUESTIONING: [...]
UNDER_QUESTIONING: [...]
VAGUE_CLOSURES: [...]
CONFIDENCE: HIGH|MEDIUM|LOW
```

`MISSING_BRANCHES`, `UNDER_QUESTIONING`, `VAGUE_CLOSURES` 중 하나라도 비어 있지
않으면 hard block입니다. 사용자에게 기각 선택지를 먼저 주지 않고 Phase 0~2 질문
루프로 돌아갑니다. 한 번에는 가장 upstream Q-ID 하나만 묻고, 답변 후 spec과 ledger에
저장한 다음 T4를 다시 실행합니다.

`OVER_QUESTIONING`은 issue 생성 blocker는 아니지만 `plan-issues` 품질 결함으로
기록합니다. 반복되면 하네스 개선 gap으로 triage합니다.

## Soft Block

검토 후보가 하나라도 있으면 Phase 4 issue 생성으로 가지 않습니다. 먼저 후보 목록을
ledger와 spec artifact에 기록한 뒤 다음 중 하나로 분기합니다.

- 후보 수정: Phase 2.5 또는 Phase 3으로 돌아가 수정하고 영향 tier만 재실행
- 후보 기각: 항목별 기각 사유를 ledger에 남긴 뒤 진행
- 재시뮬레이션: 같은 입력으로 해당 tier를 다시 실행

T4 hard block은 이 soft block 분기보다 우선합니다.
항목별 기각 사유 없이 "false positive"로 일괄 통과시키지 않습니다.

## 완료 evidence

- `simulation_result`
- `ambiguity_check`
- `clean_slate_read_result`
- `context_rot_check`
- `task_size_audit`
- `parallelization_check`
- `critical_path_check`
- `all_parallel_approval`
- `t1_spec_probe_result`
- `t2_dag_coherence_result`
- `t3_value_drift_result`
- `t4_grill_replay_result`
- `soft_block_decision`
