# Phase 3: 스펙 artifact 고정

문서화나 Issue 생성 전에 승인된 스펙을 고정합니다.

## 필수 섹션

- product intent
- assumptions
- scenarios
- functional requirements (`FR-001` 형식 stable ID)
- domain 또는 system contracts
- non-goals
- success criteria (`SC-001` 형식 stable ID, 관찰 지점/대상/기대값 포함)
- Domain Dictionary lookup
- Domain Dictionary delta
- ADR candidates
- decision log
- compaction resume sources
- self-review

`templates.md`를 사용합니다.

## 통과 조건

`[NEEDS CLARIFICATION]` marker가 남아 있으면 안 됩니다. 남아 있으면
phase 2로 돌아갑니다.

모든 FR과 SC는 이후 work item에 양방향 trace될 수 있어야 합니다. FR 또는 SC가
ID 없이 prose로만 존재하면 phase 4로 넘어가지 않습니다.

## 완료 evidence

- `spec_artifact`
- `no_clarification_markers`
- `fr_index`
- `sc_index`
- `approval_source`
