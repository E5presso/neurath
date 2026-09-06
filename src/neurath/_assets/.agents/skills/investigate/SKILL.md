---
name: investigate
description: bug 또는 failing check를 fix 제안 전에 재현, 격리, 설명합니다.
intent-class: defect.investigate
input-authority: repository-source
not-for: [source.explain, source.refactor]
argument-hint: "<symptom, failing command, issue number, or log excerpt>"
user-invocable: true
---

# Investigate

## 적용 경계

이 skill은 code, runtime, failing check의 기술적 원인을 조사할 때만 사용합니다. Agent의
행동, 대화 방식, 자기 비판, process 성찰을 요구하는 질문에는 적용하지 않습니다. 그런
요청은 도구나 phase를 시작하기 전에 직접 답합니다. 사용자가 이 skill 또는 skill 사용
자체를 거부하면 keyword가 겹쳐도 초기화하지 않습니다.

중요 skill phase는 `uv run python -m scripts.skill_harness.phase_runner`로 계약을 initialize, evaluate, advance, finalize합니다.

1. 정확한 symptom과 source of truth를 포착합니다.
2. 가장 작은 command 또는 runtime setup으로 재현합니다.
3. 최근 diff와 owning component를 검사합니다.
4. evidence에서 hypothesis를 세우고 cheap하게 반증합니다.
5. root cause, blast radius, candidate fix를 식별합니다.
   이미 해결됐다고 주장한 동일 symptom이 사용자 evidence에서 재현되면 직전 hypothesis를
   falsified로 기록하고 그 실험 변경의 rollback 경계를 먼저 식별합니다. 그 위에 새 fix를
   제안하지 않습니다.
6. investigation이 bug 또는 follow-up work item을 확인하면
   `.agents/rules/behavioral.md`의 Gap Triage를 먼저 적용합니다.
   - 현재 승인된 `/process-ticket` scope의 acceptance, Definition of Done, merge
     safety를 깨면 새 ticket으로 미루지 말고 현재 fix path에 포함합니다.
   - 스펙이나 제품 의도가 불명확하면 새 구현 ticket을 만들지 말고
     `/plan-issues`로 되돌립니다.
   - 현재 scope 밖의 독립 work item이고 지금 처리하면 WIP를 망가뜨릴 때만
     `/create-ticket`을 호출합니다.
   - 가치가 낮거나 중복이면 ticket을 만들지 않고 닫습니다.
   `/create-ticket` 호출 시에는 reproduction, expected behavior, observed
   behavior, root cause, labels, assignee policy, milestone, dependency metadata와
   triage decision을 포함합니다. 이 skill에서 issue를 직접 만들지 않습니다.
7. 다음을 보고합니다.
   - reproduction command
   - root cause
   - affected file/component
   - recommended fix
   - 필요한 test
   - Gap Triage decision
   - `/create-ticket` 호출 시 created 또는 blocked ticket result

사용자가 이어서 fix하라고 하거나 이미 승인된 `/process-ticket` scope 안이 아니면
이 skill에서 fix하지 않습니다.
