# Harness 수렴 계약

rule_id: harness-evaluation-convergence-v1

Source inventory는 initial full pass 뒤 delta-only pass를 반복하며
마지막 delta pass의 신규 capability가 0일 때만 닫습니다.
source inventory pass 횟수 상한은 두지 않습니다. generation 수는 고정하지 않습니다.
Pass count, 신규 capability 수, saturated는 조사 기록이며 의미적 포화의 실행 증거가 아닙니다.

다음 회차는 current candidate, consumed direct-child report와 같은 목표의
verified goal delta, authoritative resource delta 또는 material blocker로 정당화합니다.
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
