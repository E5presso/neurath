# terminal_report — 인수 결과 보고

요청 범위, Task ID별 결과, 실제 merged PR, 아직 병합 전인 PR, failed/blocked 시도와 남은 요구, follow-up, intent audit, 문서 동기화와 잔여 위험을 근거와 함께 보고한다. GitHub에서 확인하지 않은 병합·issue 종료를 주장하지 않는다.

모든 단계의 완료와 사용자 인수 조건을 별도로 확인한다. 실패한 시도의 종료·worker 반환·테스트 통과·보고서 작성만으로 사용자 Task를 완료하지 않는다. 미완료 요구가 있으면 정상 종료를 시도하지 말고 해당 Task를 계속 수행하거나 구체적인 차단 상태로 보존한다.

`terminal_report`의 근거를 기록하고 이 phase를 완료한 뒤, 원래 인수 조건이 모두 충족됐을 때만 `task_complete`한다. 사용자가 명시적으로 철회한 요구는 그 원문을 보존하며 성공으로 집계하지 않는다.
