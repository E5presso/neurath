# dependency_dag — 선행 조건과 동시 실행

수집한 미완료 Task 전체를 노드로 두고 실제 blocked-by 관계를 연결한다. Parent/sub-issue 관계는 실제 선행 조건일 때만 edge로 쓴다. 같은 파일을 수정하거나 통합 순서가 필요한 작업도 충돌 근거와 함께 구분한다.

`dependency_dag` 보고에는 Task ID와 issue 번호의 대응, 모든 edge, ready 집합, 가능한 동시 실행 수와 그 관측 근거, 직렬화가 필요한 이유를 담는다. 수집 단계의 대상을 누락하거나 새 요구를 몰래 추가하지 않는다. 순환·누락된 선행 조건·미확정 제품 의미가 있으면 실행을 시작하지 않는다.

순환이 없음을 확인한 뒤 아직 없는 issue Task를 선행 항목부터 `task_define`하고 실제 선행 Task ID를 `dependencies`에 넣는다. Task 시작·재개·완료는 등록된 선행 Task의 실제 completed 상태를 요구한다. worker 종료나 철회를 선행 요구 충족으로 바꾸지 않는다.

독립된 준비 작업은 병렬로 수행한다. 의존 작업은 선행 worker의 종료 신호가 아니라 그 Task의 실제 인수 결과가 충족된 뒤 시작한다. 진행 원장은 Task 하나로 유지하며 별도의 workflow·wave 완료 원장을 만들지 않는다.
