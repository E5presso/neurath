# meta_detection — 실제 실행 모순 확인

Orchestrator가 현재 Task/Assignment, lease, provider 실행 결과와 GitHub 원문을 대조한다. 작업 시간이나 세션 수만으로 결함을 단정하지 않는다. 아래 상태 모순에 구체적인 근거가 있을 때만 조사한다.

| 신호 | 확인할 모순 |
| --- | --- |
| monitor-stuck | 승인된 병합 조건이 충족됐지만 담당 Task가 후속 처리를 하지 않음 |
| resume-loop | 같은 원인과 상태에서 이어가기만 반복하고 결과가 변하지 않음 |
| write-conflict | 실제 동일 변경 대상에 동시 writer가 허용됨 |
| state-missing-or-regressed | 맡은 작업이 사라지거나 Task revision이 역행함 |
| event-consumer-missing | 정확한 이벤트가 전달됐지만 해당 Task에 처리 결과가 없음 |
| external-review-pattern | 반복된 구체적 결함이 local review에서 계속 누락됨 |
| monitor-entry-idle | 게시된 PR의 필요한 감시·후속 작업에 담당자가 없음 |
| commit-without-push | 게시 완료 보고와 실제 remote/PR head가 다름 |
| merged-without-return | 실제 병합됐지만 Assignment 결과와 Task 인수가 남음 |
| monitor-resume-idle | 후속 작업 전달 성공 주장과 실제 수신·실행이 다름 |

발견마다 원문·Task/Assignment ID·관측한 모순·필요한 복구를 기록한다. 다른 작업에 임의로 attach하거나 상태 파일을 고치지 않는다. 실제 하네스 결함이면 공통 복구 정책에 따라 영향을 격리하고 원래 미완료 요구를 보존한다.

현재 사용자 결과의 완료를 막는 결함은 승인 범위 안에서 별도 Task로 고치고 확인한다. 별도 issue가 필요하면 정확한 원인·재현·기대 결과·인수 조건과 metadata를 갖춰 `create-issue` 절차로 작성한다. 무관한 개선은 현재 완료 조건에 무한히 추가하지 않는다. 비공개 소스나 대화를 공개 이슈에 복사하지 않는다.

수정할 요구가 생기면 `phase_restart`로 수집부터 다시 확인한다. Metadata 변경도 실제 게시 권한이 있는 해당 Task에서 수행하고 다시 읽는다. 해결되지 않은 차단 요인을 보고서만으로 통과시키지 않는다.

완료 조건의 보고들은 하나의 조사에서 얻은 근거를 사용한다: `meta_detection_result`, `matched_signal_inventory`, `metadata_verification_result`, `fixed_point_result`, `weak_or_failed_gaps`, `meta_queue_result`, `main_session_inspection`. 결함이 없으면 실제 대조 범위와 미발견 결과를 명시한다. 이 보고를 위해 별도 상태 원장을 만들지 않는다.
