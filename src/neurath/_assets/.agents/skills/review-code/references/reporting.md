## 보고 템플릿

리뷰 에이전트는 14개 카테고리 상태를 모두 보고한다. 탐지 시그널 미매치도 "통과"로 명시하고 Info 섹션은 만들지 않는다.

````markdown
## Review 결과 (Iteration N)

### 카테고리별 상태
| # | 카테고리 | 상태(통과/해소됨/미해소) | 의문점 수 |

### Critical — 해소 필수 (N건)
- **[#카테고리 · 파일:라인]** 의문점
  - 탐지 시그널:
  - 관련 규칙: `rules/<file>.md`
  - 상태: `미해소` / `해소됨 (수용)` / `해소됨 (반박 인정)`

### Warning — 해소/반박 필요 (N건)
- Critical과 동일 포맷

### 수렴 판정
- 미해소 Critical: N
- 루프 종료 가능 여부: 가능/불가능
- 다음 iteration 전달 항목: 미해소 의문점 목록
````

Phase runner에는 사람이 읽는 보고서와 별도로 다음 구조화된 검토 결과를 제출합니다.
이 검토 결과는 판단을 자가증명하지 않습니다. `ConsumedDelegationEvidenceReader`가 exact
workflow에서 읽은 consumed typed delegation, 변경 전에 확정한 14개 검사 항목, content-addressed full
`review_report`, exact outcome digest와 모두 일치하는 read-back locator입니다.

```text
subagent_dispatch: agent_id=<id> delegation_id=<id> outcome=result-applied
diff_marker: head_sha=<40-hex>
persona_readback: policy_id=constructive-skeptic-v1 categories=14
review_categories: verified=14
delegate_transition_receipt: delegation_id=<id> target_agent_id=<id> outcome_ref=sha256:<64-hex>
review_report_readback: outcome_ref=sha256:<64-hex> note_count=<n> blocker_count=0 verdict=pass
turn_harness_audit: checked=true evidence_count=3 violations=0
```

`--review-finding-json`은 `stable_key`, 확정 검사 항목의 `row_id`, `summary`, 실행 가능한
`reproduction_command`, `expected`, `actual`, `impact`, `root_cause_key`의 실제 본문을
요구합니다. `--review-note-json`은 여기에 `severity=warning|resolved`,
`disposition=gap-triage|rebutted|fixed`, `evidence_command`를 함께 기록합니다. Warning은
관찰된 위험과 Gap Triage가, 반박/수정 완료는 기대와 실제 결과의 일치가 있어야 합니다.
같은 `stable_key` 또는 `root_cause_key`를 둘 이상 제출하면 state transition이 거부됩니다.
