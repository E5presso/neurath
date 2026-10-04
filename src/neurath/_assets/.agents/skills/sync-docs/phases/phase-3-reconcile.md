# Phase 3: Finding 조정

verification finding을 해결합니다.

## 절차

1. source evidence가 있는 finding을 수용합니다.
2. 관련 source를 다시 읽은 뒤에만 finding을 기각합니다.
3. 문서 수정이 필요하면 `phase_restart`로 write 단계에 돌아가 적용하고 독립 검증을
   다시 받습니다. 검토 이후 바뀐 문서를 이전 검토 결과로 통과시키지 않습니다.
4. 필수 finding을 해소한 뒤 이 phase를 완료합니다. 해소할 수 없으면 원래 요구를
   미완료로 보존하고 구체적인 차단 사유를 보고합니다.

## 한계

이 skill 안에서 docs를 만족시키기 위해 code를 rewrite하지 않습니다. code gap은
`.agents/rules/behavioral.md`의 Gap Triage로 먼저 분류합니다. 현재 docs sync의
accuracy를 깨는 작은 gap이면 현재 작업에서 문서를 고치고, 스펙이 불명확하면
현재 사용자에게 필요한 결정을 확인하며, 독립 work item이고 지금 처리하면 WIP를 망가뜨릴 때만
triage decision을 포함해 follow-up GitHub Issue로 보냅니다.
