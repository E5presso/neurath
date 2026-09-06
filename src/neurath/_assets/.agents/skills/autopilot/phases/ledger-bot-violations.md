# Bot Violation Ledger

bot review나 automation behavior가 merge state에 영향을 줄 때 이 reference를
사용합니다.

## 기록 항목

- PR number
- bot 또는 automation actor
- 정확한 comment 또는 check signal
- 수행한 action
- PR이 여전히 blocked인지 여부
- Gap Triage decision
- harness follow-up issue가 필요한 경우 priority, acceptance, owner/agent route,
  재개 조건, source evidence

GitHub review state가 repository requirement를 만족한다고 확인하기 전에는 bot
signal을 human approval로 취급하지 않습니다.
