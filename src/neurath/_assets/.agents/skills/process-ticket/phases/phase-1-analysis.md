# Phase 1: 분석

code를 건드리기 전에 authoritative work item을 읽습니다.

## 필수 입력

- `AGENTS.md`
- `.neurath/project.json (documents 슬롯)` 스펙 지도와 티켓이 인용한 FR/SC의 정의처
- `.agents/rules/charter.md`
- `.agents/rules/domain-dictionary.md`
- `.neurath/project.json (documents 슬롯)`
- 참조된 `docs/plans/` artifact, GitHub Issue, 또는 명시적 user work item
- 관련 glossary와 ADR entry

## 절차

1. 사용자 또는 운영 의도를 두 줄로 간결하게 재진술합니다.
2. 승인된 scope와 explicit non-goal을 식별합니다.
3. work item이 지목한 code, test, docs, harness rule을 검사합니다.
4. 요청 언어, class name, public method name 후보가 `.neurath/project.json (documents 슬롯)` Domain
   Dictionary와 충돌하는지 확인합니다.
5. 새 domain noun 또는 action verb가 필요하면 DD delta가 승인됐는지 확인합니다.
6. 구현 가능한지, 아니면 `/plan-issues`로 돌아가야 하는지 결정합니다.

## Evidence

phase runner state에 `agents_rules_read`, `work_item_source`,
`intent_restatement`, `domain_dictionary_lookup`을 기록합니다.

worker로 실행 중이면 `tool:send_message`로 phase 진입과 blocker를 orchestrator에
보고합니다.

## Blocker

unresolved product purpose, 승인되지 않은 새 domain vocabulary, 모순된 spec/code, missing
credential, destructive external mutation에서는 block합니다.
