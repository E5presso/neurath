# Phase 7: Merge gate

clean PR을 merge할 수 있는지 결정합니다.

## 절차

1. GitHub이 PR을 clean으로 보고하고 review requirement가 충족됐는지 확인합니다.
   `--auto-merge`에서도 `ai-review` status와 GitHub review approval 없이 merge하지
   않습니다.
2. normal mode에서는 merge approval을 요청합니다.
3. `--auto-merge` mode에서는 이전 user invocation을 merge approval로 취급합니다.
   이때 Phase 7은 사용자 승인 게이트가 아니라 Phase 8로 넘어가는 0-hop 라우터다.
4. `.agents/skills/process-ticket/scripts/check_auto_merge_continuation_contract.sh`로 auto
   continuation의 clean terminal prerequisites를 검증합니다.

## Guardrail

이 phase에서는 `merged`를 보고하지 않습니다. `merged`는 phase 8이 GitHub merge
state를 확인한 뒤에만 유효합니다.
