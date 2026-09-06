---
name: sync-docs
description: documentation synchronization을 developer/user documentation scope로 routing합니다.
intent-class: docs.route
input-authority: repository-source
not-for: [developer-docs.sync, user-docs.sync]
argument-hint: "[dev|user|all] [component]"
user-invocable: true
---

# Sync Docs

## 결정적 phase 실행

계약이 있는 phase 작업은 다음 명령으로 initialize, inspect, complete,
evaluate, finalize합니다.

```bash
uv run python -m scripts.skill_harness.phase_runner
```

phase runner가 evidence를 수락하고 다음 phase 또는 terminal output을 내기 전에는
phase 결과나 다음 phase 진입을 주장하지 않습니다.

## Tool runtime 호환성

`.agents/rules/tool-runtime-map.md`를 사용합니다. phase 파일은 `tool:<key>`로
tool action을 표현할 수 있으며, Claude Code와 Codex에서는 map을 통해 변환합니다.

## Phase 개요

각 phase에 진입할 때 해당 phase 파일을 읽습니다.

| Phase | 목적 | 파일 |
|-------|------|------|
| 0 | 문서화 범위 계획 | `phases/phase-0-plan.md` |
| 1 | 문서 작성 | `phases/phase-1-write.md` |
| 2 | 문서 검증 | `phases/phase-2-verify.md` |
| 3 | finding 조정 | `phases/phase-3-reconcile.md` |
| 4 | sync result 보고 | `phases/phase-4-report.md` |
| 5 | 검증된 변경 전달 | `phases/phase-5-deliver.md` |

문서 format과 per-doc writing rule은 `doc-format.md`에 있습니다.

## Writer/Verifier 분리

문서 변경은 Writer와 Verifier를 분리합니다. Writer는 code, test, manifest,
approved plan, ADR을 읽고 문서를 작성합니다. Verifier는 별도 context에서 같은
source를 다시 읽고 fact-check합니다. Writer가 쓴 문서를 같은 context가 검증하지
않습니다.

Verifier는 다음을 확인합니다.

- 모든 behavior claim에 code, test, plan, ADR evidence가 있습니다.
- import path, command, package name, deployment manifest path가 현재 파일과
  일치합니다.
- DD 용어가 `.neurath/project.json (documents 슬롯)`와 일치합니다.
- 승인되지 않은 product behavior를 implemented처럼 설명하지 않습니다.
- 문서 frontmatter 또는 상단 metadata에 `date`와 `synced_from` 또는 equivalent
  source SHA가 있습니다.

Critical/Warning finding이 남아 있으면 sync 완료로 보고하지 않습니다.

1. scope를 결정합니다.
   - `dev`: `/sync-dev-docs` 실행
   - `user`: `/sync-user-docs` 실행
   - `all`: 둘 다 실행
2. code, test, manifest, approved plan을 source of truth로 사용합니다.
3. 승인되지 않은 product behavior를 실제처럼 문서화하지 않습니다.
4. docs edit 후 `uv run python -m scripts.agent_harness.verification_runner pre-commit` 또는 관련 docs/harness subset을
   실행합니다.

scope가 없으면 요청과 변경 내용을 보고 개발자용·사용자용 문서 중 실제 대상을 판별합니다.
