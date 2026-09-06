# Phase 3: Finding 조정

verification finding을 해결합니다.

## 절차

1. source evidence가 있는 finding을 수용합니다.
2. 관련 source를 다시 읽은 뒤에만 finding을 기각합니다.
3. correction을 적용합니다.
4. critical finding이 사라지거나 scope가 blocked될 때까지 반복합니다.

## 한계

이 skill 안에서 docs를 만족시키기 위해 code를 rewrite하지 않습니다. code gap은
`.agents/rules/behavioral.md`의 Gap Triage로 먼저 분류합니다. 현재 docs sync의
accuracy를 깨는 작은 gap이면 현재 작업에서 문서를 고치고, 스펙이 불명확하면
`/plan-issues`로 되돌리며, 독립 work item이고 지금 처리하면 WIP를 망가뜨릴 때만
triage decision을 포함해 follow-up GitHub Issue로 보냅니다.
