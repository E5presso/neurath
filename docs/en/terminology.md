# Harness terminology
<!-- date: 2026-09-07; synced_from: source and documentation at 2456ae73ffaf818c04ea4419574218df36852805; English and Korean editions updated together -->

[Usage](usage/index.md) · [Contributing](contributing/index.md)


**English** · [한국어](../ko/terminology.md)

Neurath documentation uses terms that explain what an operation does. English and Korean
express the same concepts; a single legacy name is not applied indiscriminately to different roles.

| Meaning | English term | Korean term | Names in existing code |
| --- | --- | --- | --- |
| Files changed by installation and previous content needed for recovery | installation record | 설치 이력 | install receipt, `neurath-receipts` |
| A tool's result status, output fingerprint, and observed changes | execution result | 실행 결과 | tool receipt, `ToolReceipt` |
| A record of the verification target, conditions, and actual outcome | verification record | 검증 기록 | verification receipt |
| A reviewer's judgment and findings | review result | 검토 결과 | review receipt |
| A record identifying an input or event that was processed | processing record | 처리 기록 | source receipt, prompt receipt |
| Where information or a request came from | source information | 출처 정보 | provenance |
| Facts confirmed against actual host records | host verification | 호스트 확인 | attestation, `HOST_ATTESTED` |
| The agent performing an evaluation | reviewer | 검토자 | evaluator |
| A request to execute a tool once | tool call | 도구 호출 | invocation |
| Results, decisions, and remaining work needed by the next task | handoff note | 인계 기록 | checkpoint |
| Who may modify a workspace | workspace ownership | 작업 공간 소유권 | worktree claim |
| A key that prevents a previous owner from making changes | ownership key | 소유권 확인 키 | fencing token |
| The user request currently being processed | current turn | 현재 턴 | foreground turn |
| The execution, reviewer, user, or official source that determines the final outcome | decision authority | 판정 주체 | `oracle_owner`, `OracleOwner` |
| Working state required to recover a session | session working state | 세션 작업 상태 | enclave |

A record alone does not establish success or approval. Failed and unverified outcomes are recorded
too. Execution results describe what a tool did; verification records describe the conditions used
to check that outcome. A review result does not automatically grant ownership or publishing authority.

`receipt` does not describe a financial transaction here, so it is not translated as “영수증”.
The old `invoice export` was an example task, not a harness concept. Documentation examples use
**work log export / 작업 기록 내보내기** consistently. Terms such as invoices or shipping documents
in real business domains retain the meanings defined by the target project.

Keep the exact spelling of commands, JSON fields, schemas, classes, and storage paths. Existing
`receipt` fields and the `neurath-receipts` directory remain compatible with stored installation
and session records and tools. Installation plans use `--installation-id`; the existing `--receipt`
option remains an equivalent alias. In explanations, use descriptive terms such as “installation
record ID” or “tool execution result”.

This guide applies to the harness itself. It does not replace the target project's domain glossary.
