# Phase 2: Dependency DAG

dependency graph와 execution wave를 구성합니다.

## 절차

1. GitHub `blocked-by` 관계를 graph edge로 변환합니다.
2. parent/sub-issue ordering이 실제 dependency를 뜻할 때만 포함합니다.
3. work를 spawn하기 전에 cycle을 탐지합니다.
4. 독립 issue를 wave로 묶습니다.
5. critical path와 parallelizable group을 식별합니다.

## 통과 조건

다음 경우 phase 3을 실행하지 않습니다.

- graph에 cycle이 있습니다.
- ordering을 바꾸는 dependency metadata가 빠졌습니다.
- scope 안의 모든 issue에 대해 product intent가 충분히 확정되지 않았습니다.
