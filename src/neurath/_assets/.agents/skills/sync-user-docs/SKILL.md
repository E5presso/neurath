---
name: sync-user-docs
description: 승인된 product behavior가 존재한 뒤 user-facing documentation을 동기화합니다.
intent-class: user-docs.sync
input-authority: repository-source
not-for: [docs.route, developer-docs.sync]
argument-hint: "[component or scenario]"
user-invocable: false
---

# Sync User Docs

중요 skill phase는 `uv run python -m scripts.skill_harness.phase_runner`로 계약을 initialize, evaluate, advance, finalize합니다.

user docs를 쓰기 전에 대상 프로젝트의 해당 동작이 승인되고 구현됐는지 확인합니다.

1. 승인된 scenario 또는 feature plan을 읽습니다.
2. 구현된 behavior를 검증합니다.
3. internal harness mechanic을 노출하지 않고 user-facing docs를 갱신합니다.
4. terminology를 `.neurath/project.json (documents 슬롯)`와 맞춥니다.
5. 관련 check를 실행합니다.

product purpose가 아직 unsettled이면 user docs가 blocked됐다고 보고합니다.
