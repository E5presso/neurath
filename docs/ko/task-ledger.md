# 작업 요구·시도·TODO

#140은 프로젝트·세션 기반에 출처 있는 원문, 현재 요구, 시도 결과와 추가 전용
요구 이력을 구현합니다. 각 작업은 `application/ports/usecases`의 불변 명령 또는
조회, ABC `I…UseCase`, 명시적으로 상속한 `…UseCase.execute`, 개별
`transport/<operation>.py` 요청 함수로 분리됩니다. 원장 façade, 사용자 정의
Unit of Work, 거절된 API의 호환 별칭은 없습니다.

각 transport 함수는 명령/조회와 선택적인 `database_path`를 받습니다. 새 SQLAlchemy
`Session`을 열고 직접 `session.begin()`에 진입해 스키마와 프로젝트·세션을 검증한 뒤
개별 유스케이스에 저장소를 전달합니다. 저장소는 flush만 수행하며 요청 함수가
커밋·롤백·해제를 담당합니다. 조회는 SQLite 읽기 전용 연결을 사용합니다. 쓰기 예약이
읽기부터 갱신까지 보호하고 예상 task revision이 오래된 호출을 거부합니다.

| 작업 / 요청 타입 | 관찰할 동작 |
| --- | --- |
| `record_source(RecordSourceCommand)` | 정확한 원문·작성자·참조·최초 세션을 보존합니다. `SourceKind`는 instruction, correction, status_question, summary를 구분합니다. 정정은 같은 프로젝트의 기존 지시 또는 정정 출처를 가리킵니다. |
| `create_task(CreateTaskCommand)` | instruction에 연결한 pending 요구를 만듭니다. 같은 프로젝트의 기존 출처는 명시적 ID로 다른 세션에서도 재사용하며 원래 귀속을 보존합니다. 귀속 정보는 인간 재승인 게이트가 아닙니다. 의존성과 `follows_task_id`로 관련 작업을 연결합니다. |
| `correct_task(CorrectTaskCommand)` | 현재 출처 계보와 예상 task revision을 요구합니다. 전달한 제목·결과 조건·의존성만 바꾸며 생략한 필드와 다른 태스크는 유지합니다. definition revision을 올리고 원래 출처·이력을 보존한 채 pending으로 돌립니다. |
| `invalidate_task(InvalidateTaskCommand)` | 실제 정정 출처와 이유로 취소를 반영합니다. 미완료 시도를 보존하며 실제 실행이 중단됐다고 주장하지 않습니다. |
| `start_task(StartTaskCommand)` | pending/failed 작업과 성공한 선행 의존성을 확인하고 새 `TaskAttempt`를 반환합니다. 시작 기록은 실제 실행 성공이 아닙니다. 재시도해도 이전 실패 시도를 보존합니다. |
| `report_task_result(ReportTaskResultCommand)` | 해당 시도의 실행자·요약·근거를 요구합니다. `SUBMITTED`는 제출 근거만 보존하고 시도·작업을 완료하지 않습니다. `SUCCEEDED`에는 남은 일이 없어야 합니다. `FAILED`·`PARTIAL`은 남은 일 또는 구체적 장애를 요구하고 태스크를 재시도 가능한 failed로 둡니다. 확정 결과는 덮어쓸 수 없습니다. |
| `wait_task(WaitTaskCommand)` | 미완료 작업에 `ExternalWait(target, condition, continuation, evidence)`를 기록합니다. 모든 필드가 필요하므로 일반적인 대기 사유만으로는 대기할 수 없습니다. 독립 작업은 계속 ready입니다. |
| `resume_task(ResumeTaskCommand)` | 해소 근거와 현재 revision을 요구합니다. 이미 시작한 시도를 유지하며 외부 실행을 자동 재제출하지 않습니다. |
| `get_tasks(GetTasksQuery)` | 현재 세션의 전체 태스크를 `TaskProjection`으로 반환합니다. `ready`도 동일한 목록에서 계산합니다. |
| `get_task_history(GetTaskHistoryQuery)` | 전체 요구 스냅샷과 변경 이유를 task revision 순서로 반환합니다. |
| `get_task_attempts(GetTaskAttemptsQuery)` | 실패·부분 결과·제출·미완료 시도·정정으로 현재 요구에 적용되지 않는 결과까지 모든 시도를 반환합니다. |
| `get_sources(GetSourcesQuery)` | 요청한 세션에서 최초 기록된 정확한 원문을 반환합니다. 재사용은 최초 귀속을 복제하거나 다시 쓰지 않습니다. |

상태는 `pending`, `active`, `waiting`, `succeeded`, `failed`, `invalidated`입니다.
`TaskProjection.all_terminal`에는 실패·무효가 포함되지만 `all_succeeded`는 모든 현재
태스크의 실제 성공만 인정합니다. 빈 목록에서는 둘 다 false입니다. 작업이 없다는
사실만으로 요구 완료를 확정하지 않습니다. TODO는 이 조회 결과이며 별도 쓰기 원장이
아닙니다. 표시 실패나 호스트 상태 축약은 저장된 결과를 바꿀 수 없습니다.

태스크 `revision`은 모든 상태 변경을 보호합니다. `definition_revision`은 요구의
정정·무효화 때만 바뀝니다. 시도는 원래 definition revision과 실행자를 유지합니다.
늦게 온 결과는 해당 시도에 저장하지만 새 요구나 취소된 작업을 완료하지 않습니다.
실패한 태스크를 재시도하거나 같은 출처의 후속 작업을 연결해도 원래 실패는 보입니다.
의존성은 세션 범위이며 순환을 거부하고 실제 성공만 인정합니다.

## 저장과 마이그레이션

`RequestSource`, `Task`, `TaskAttempt`, `TaskChange`마다 ABC 저장소 port와 명시적
SQLAlchemy 구현이 있습니다. 선언형 모델은 `Mapped`/`mapped_column`과 명시적인
`from_domain`·`to_domain` 변환을 사용합니다. 어떤 요청을 import해도 전체 모델
metadata가 등록됩니다.

명시적 `SqliteDatabase.initialize()`가 변경하지 않은 `core_0001` 뒤에 `core_0002`를
적용합니다. `task_sources`, `tasks`, `task_attempts`, `task_changes`를 추가하고 기존
프로젝트·세션 행과 외래키를 보존합니다. 신규 초기화와 기존 0001 업그레이드는 동등한
스키마를 만듭니다. 일반 요청은 암묵적으로 이전하지 않습니다. 출처와 작업 이력을
보존하기 위해 파괴적 downgrade는 거부합니다. 거절된 PR 구현의 미설치 초안 스키마를
대체하며, 기존 0.3.1 사용자 DB의 이전은 별도 작업입니다.

## 검증과 경계

A01·A04·A05·A06·A44·B04를 출처 재사용, 제한된 정정, 전체 TODO 상태,
실패·부분·제출 시도, 오래된 결과, 외부 대기, 독립 작업, 의존 순환, 범위 혼합 거부,
동시 시작, 트랜잭션 롤백, 새 프로세스 조회, 0001 보존·스키마 동등성으로 검증합니다.
기반 품질 훅의 strict typing·format·docstring·architecture 검사를 전체 소스에
적용하며 태스크 전용 예외를 두지 않습니다.

근거 문자열은 호출자가 관찰한 내용을 기록하며 원격 실행·인간 인증·산출물 의미를
독립적으로 입증하지 않습니다. 호스트 어댑터가 실제 관찰을 공급하고 후속 phase runner가
필수 평가를 마친 뒤 완료를 보고해야 합니다. 공개 CLI 연결, 감시, Stop 훅, 평가,
설치·실제 활성화는 이 변경의 범위 밖입니다. 임시 DB 검사는 현재 사용자 DB와 설치
배포본을 바꾸지 않습니다.
