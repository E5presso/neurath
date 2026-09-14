# Harness 수렴 계약

rule_id: harness-evaluation-convergence-v1

아래 goal은 사용자의 요구를 담은 기존 태스크와 그 완료 조건입니다. 에이전트가 만든 평가·복구·
최적화 실험의 목표로 바꿔 해석하지 않습니다. 내부 실험의 성공, 새 finding, 새 candidate 또는
검사표 확장 자체는 사용자 목표의 진전이 아닙니다. 방법을 교체해도 기준 태스크는 유지하며,
스스로 추가한 조건을 해결해야만 사용자에게 결과를 전달할 수 있다는 새 의무를 만들지 않습니다.

작업 목록의 기본 경로는 현재 완료 조건과 관련된 범위만 한 번 조사하고 변경된 부분만 재검토합니다.
전수 비교가 명시적으로 승인된 정식 평가에서만 initial full pass 뒤 delta-only pass로
source inventory를 완성합니다. 범위·종료 조건을 먼저 고정하며 포화 탐색을 일반 수정의
완료 조건으로 사용하지 않습니다. 같은 제약의 반복 실패는 재요청 횟수로 해결하지 않습니다.
Pass count, 신규 capability 수, saturated는 조사 기록이며 의미적 포화의 실행 증거가 아닙니다.

다음 회차는 current candidate와 consumed direct-child report를 원래 태스크의 미달 조건에
대조해 정당화합니다. 새 내부 목표나 내부 실험의 blocker만으로 다음 회차를 열지 않습니다.
evaluate-harness의 각 회차는 current candidate 하나와 owner가 소비한 direct-child evaluator
report 하나만 가지며, 다음 회차는 같은 goal의 목표·자원 변화가 material criterion settlement
또는 blocker 감소를 보일 때만 엽니다. 저비용이어도 zero-progress는 성공이 아니며 같은 root와
접근이면 `approach_change_required`입니다. Current goal을 깨는 finding은 검사표를 다시 확정해
검증하고 무관한 finding만 defer합니다.

evaluate-harness의 90분 wall-clock budget은 사용자 대기를 포함한 emergency watchdog이며
초과하면 `blocked`로 control을 반환합니다.
watchdog은 success, convergence, efficiency authority가 아닙니다.
Neurath에서는 새 EventStore나 agent runtime을 만들지 않고 기존 incident ledger,
evaluation loop, 변경 전에 확정한 검사표를 재사용합니다.
