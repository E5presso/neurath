---
name: audit-spec
description: 구현 전에 GitHub milestone, project, issue, local plan의 모호성, 모순, policy drift를 audit합니다.
intent-class: spec.audit
input-authority: repository-spec
not-for: [spec.plan, change.impact-analyze]
argument-hint: "<milestone, project, issue list, or plan path>"
user-invocable: true
---

# Audit Spec

중요 skill phase는 `uv run python -m scripts.skill_harness.phase_runner`로 계약을 initialize, evaluate, advance, finalize합니다.

plan, milestone, GitHub Issue set에 spec-only review가 필요할 때 사용합니다. 이
skill에서는 production code를 편집하지 않습니다.

1. `AGENTS.md`, `.agents/rules/charter.md`, 참조 artifact를 읽습니다.
2. GitHub Issues, `docs/plans/`, `docs/context/`에서 authoritative spec text를
   수집합니다.
3. 다음을 확인합니다.
   - unresolved product intent
   - conflicting acceptance criteria
   - missing test expectation
   - `.neurath/project.json (documents 슬롯)`와 충돌하는 terminology drift
   - web, mobile, backend, database, required infrastructure를 모두 포함하지 않는
     e2e claim
   - 대상 프로젝트에서 승인된 기술 결정과 실제 구현 사이의 차이
4. finding은 severity 순서로 file 또는 issue reference와 함께 보고합니다.
5. 필요한 correction마다 docs patch 또는 GitHub Issue body update를 제안합니다.
   product intent를 조용히 rewrite하지 않습니다.

진짜 intent gap을 발견하면 `/plan-issues`로 되돌립니다.
