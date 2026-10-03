---
name: autopilot
description: GitHub milestone, parent issue, issue set을 구현 wave, PR review, merge, audit, docs sync까지 orchestration합니다.
intent-class: work-item-set.execute
input-authority: github-work-item
not-for: [ticket.execute, spec.plan]
argument-hint: "<milestone-name | #N | #101,#102,...>"
user-invocable: true
---

# Autopilot

Autopilot은 Neurath의 high-autonomy SDLC orchestrator입니다. bounded GitHub
milestone, parent issue, issue set을 끝까지 처리하기 위해 존재하며 약속 목록만
남기지 않습니다.

실행 전체에서 `mergeable-clean`과 `merged`를 구분합니다.

각 assignment의 성격·난이도·필요한 능력과 수명에 따라 native subagent, 독립 세션,
Claude ↔ Codex 위탁을 먼저 선택합니다. Native child가 기본이며 worktree나 병렬 실행
필요만으로 독립 세션을 선택하지 않습니다. 독립 세션 또는 교차 provider가 필요한
항목만 `provider_wave_run`으로 접수하고 런타임이 ready 슬롯을 실행합니다.
커스텀 Codex 빌드나 launcher를 요구하지 않습니다.
각 worker는 독립 provider peer이며 native 직접 자식·독립 evaluator 권한을 갖지 않습니다.
Root는 정확한 결과를 `provider_wave_consume`으로 수락하고, fresh native child에
독립 리뷰를 별도로 맡깁니다. 실제 hook 지원이 검증된 호스트의 native wave도 유지합니다.
배치 scheduling, 소스 테스트와 실제 스톡 호스트 검증을 구분하며 임의 대기의 전면 차단을
주장하지 않습니다. Phase 3의 절차와 backend별 근거를 따릅니다.

## 작업 중 인사이트 공유

모든 worker는 프로젝트 공통 Newsroom에 active 동안 참여합니다. 작업 배정에는
`.neurath/policy.md`의 Newsroom 규약을 포함합니다. 다른 worker와 독립 세션의 제목 알림을
보고 현재 작업에 관련 있는 기사만 본문을 조회합니다. 유용한 발견은 제목과 본문으로
발행하고 필요한 의견은 기사 댓글이나 직접 메시지로 교환합니다.
이 대화는 부모에 대한 필수 보고·검토와 worktree 단일 소유권을 대체하지 않습니다.
종료·대기 중인 worker를 뉴스 수신 때문에 깨우거나 자동 재개하지 않습니다.

## 결정적 phase 실행

Autopilot을 호출하면 `task_define`으로 사용자의 정확한 목표를 등록한 뒤
구현이나 `task_start` 전에 명명 MCP `phase_start`로 워크플로를 시작합니다.
각 단계에서 `phase_current`를 읽고
`phase_evidence_prepare`와 `phase_complete`로 해당 단계의 근거를 확정합니다.
마지막 단계 뒤 `phase_finalize`를 사용합니다. task 목록이 있어도 이 순서는
생략되지 않습니다. Autopilot의 모든 phase는 `completed`가 필요합니다.
실행할 항목이 없는 단계도 확인한 결과를 근거로 `completed`로 기록하며
`skipped`로 우회하지 않습니다.

phase runner가 evidence를 수락하고 다음 phase 또는 terminal output을 내기 전에는
phase 결과나 다음 phase 진입을 주장하지 않습니다.

## Tool runtime 호환성

`.agents/rules/tool-runtime-map.md`를 사용합니다. phase 파일은 `tool:<key>`로
tool action을 표현할 수 있으며, Claude Code와 Codex에서는 map을 통해 변환합니다.

## 강한 전제조건

시작 전에 다음을 확인합니다.

- 대상이 GitHub milestone, GitHub parent issue, issue list, 승인된 local plan 중
  하나입니다.
- scope 안의 모든 issue에 대해 product intent가 충분히 확정되어 있습니다.
- PR 생성 또는 merge가 예상되면 remote repository가 있습니다.
- `/process-ticket`, `/monitor-pr`, `/triage-comments`, `/sync-docs`,
  `/audit-spec`를 사용할 수 있습니다.

전제조건이 빠졌으면 정확한 missing prerequisite와 함께 중단합니다.

## 대상 해석

- `#N` 또는 `N`: parent GitHub Issue.
- comma-separated issue number: explicit issue set.
- 그 외: GitHub milestone name.

`gh` 또는 GitHub connector를 source of truth로 사용합니다. 다른 issue tracker를
사용하지 않습니다.

## Phase 개요

각 phase에 진입할 때 해당 phase 파일을 읽습니다.

| Phase | 목적 | 파일 |
|-------|------|------|
| 1 | 이슈 수집 | `phases/phase-1-collection.md` |
| 2 | dependency DAG 구성 | `phases/phase-2-dag.md` |
| 3 | 각 wave 실행 | `phases/phase-3-wave-loop.md` |
| 3.5 | spawned follow-up issue 복구 | `phases/phase-3_5-recovery.md` |
| 3.6 | automation defect 탐지 | `phases/phase-3_6-meta-detection.md` |
| 4 | `/audit-spec` 실행 | `phases/phase-4-intent-audit.md` |
| 5 | `/sync-docs all` 실행 | `phases/phase-5-sync-docs.md` |
| 6 | 병합된 PR 보고 | `phases/phase-6-final-report.md` |

조건부 reference:

- `phases/new-ticket-intake.md`
- `phases/ledger-bot-violations.md`

## 중단 조건

다음 경우에만 중단하고 사용자에게 묻습니다.

- spec과 code가 직접 모순됩니다.
- `.neurath/project.json (documents 슬롯)`에 없는 새 domain term이 필요합니다.
- destructive external mutation입니다.
- issue decomposition이 product intent를 바꿉니다.
- GitHub permission 또는 필수 tooling이 없습니다.

승인된 spec이 명백히 요구하는 follow-up implementation issue를 만들지 말지
묻지 않습니다.

## 진행 보고 형식

실행 중 progress update는 모두 다음 형식을 사용합니다.

```text
[autopilot N/M (P%) ETA Xh Ym] message
```

`N`은 terminal issue 수, `M`은 spawned blocking follow-up을 포함한 scope 전체
수입니다. ETA는 terminal issue당 경과 시간으로 계산합니다.
