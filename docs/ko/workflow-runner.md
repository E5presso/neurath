# 스킬 절차와 단계 실행

[문서 안내](index.md) · [실행 구조](architecture.md) · [English](../en/workflow-runner.md)

선택한 스킬은 `workflow start`로 태스크 원장에 연결합니다. 에이전트는 호스트에서 실제 작업하고 `workflow report`로 현재 단계 결과를 보고합니다. 명시적인 프로그램 단계만 기존 프로세스 어댑터를 사용합니다.

## 정의와 결과

`WorkflowRun`은 태스크 하나에 연결되며 선택한 `WorkflowDefinition`의 개정과 `PhaseAttempt` 이력을 소유합니다. 각 단계는 목적, 최종 실행 인자, 작업 디렉터리, 대상 개정, 필요한 검사, 선택적 생략 조건과 실행 한도를 가집니다. inputs는 정의 선택의 입력 기록입니다. `arguments=()`인 조사·설계·리뷰 단계는 호스트 에이전트가 수행하며 subprocess를 만들지 않습니다. 프로그램 단계의 arguments만 실제 실행에 사용합니다.

다음 단계는 현재 정의와 일치하는 마지막 시도의 결과로 결정합니다. 대상·조건이 바뀐 단계는 다시 수행하며, 동일한 단계의 유효 결과와 대기 중 시도는 재사용합니다. 옛 정의의 결과는 보존하지만 새 단계를 완료시키지 않습니다. 방법 변경은 원 사용자 목표의 정정을 요구하지 않습니다. 바뀐 절차와 이유를 보존하고 실제 요구 변경만 태스크 원문에 연결합니다. 선택 단계 생략에는 정의한 조건과 근거를 기록합니다.

같은 대상·태스크 요구의 실제 실행 횟수는 단계의 max_attempts로 제한합니다. 한도에 도달하면 미해결 상태와 이력을 유지하고 추가 실행을 거부합니다. 수정한 대상에 대한 실행은 새 대상의 한도를 적용합니다.

## 내부 유스케이스

입력 Command/Query와 Result는 각각의 유스케이스 모듈에 있습니다.

| 유스케이스 | 동작 |
| --- | --- |
| StartWorkflow | 태스크의 현재 시도에 선택 절차를 연결. 미시작 태스크는 선행 조건을 검사해 시작. 동일 정의의 재요청은 기존 run 반환 |
| GetWorkflow | 현재 정의·단계와 전체 시도 조회. 외부 실행 없음 |
| PreparePhase | 새 running 시도를 저장. 커밋 후 외부 실행을 연결할 수 있도록 예약 |
| ExecutePhase | 예약 커밋 → 잠금 밖 실행/조회 → 별도 트랜잭션의 결과 반영 |
| ReportPhase | 관찰한 대상·검사·근거를 대조하고 결과와 태스크 대기·해소를 함께 저장 |
| ReviseWorkflow | 현재 태스크 요구에 수정한 정의 연결. 이전 정의·실패·영향 없는 결과 보존 |
| SkipPhase | 현재 선택 단계의 조건부 생략 기록 |

DB 작업은 `@transactional`을 사용합니다. ExecutePhase가 시도와 `PhaseExecutionRequested`를 커밋하면 이벤트 어댑터가 RunPhase를 호출합니다. RunPhase가 외부 실행·복구를 수행하고 `PhaseExecutionObserved`를 발행하면, 어댑터가 ReportPhase를 호출해 결과를 저장합니다. 새 외부 대기는 저장 커밋 후 `PhaseWaitingRecorded`를 통해 NotifyPhaseWait가 안내합니다. 어댑터는 이벤트 변환과 유스케이스 호출만 수행하며 실행·저장·알림 서비스를 직접 호출하지 않습니다. ExecutePhase의 반환값은 예약 스냅샷이며 실제 결과는 GetWorkflow로 확인합니다.

아래 예제는 이미 저장된 태스크에서 실행합니다. 요청을 처음부터 다시 만들지 않으며, 반환된 run의 완료는 태스크 목표의 성공 보고와 별개입니다.

```python
from pathlib import Path
import sys

from neurath.application.usecases.get_task import GetTaskQuery, GetTaskUseCase
from neurath.application.usecases.start_workflow import StartWorkflowCommand, StartWorkflowUseCase
from neurath.application.usecases.execute_phase import ExecutePhaseCommand, ExecutePhaseResult, ExecutePhaseUseCase
from neurath.domain.values.workflow_definition import PhaseDefinition, WorkflowDefinition
from spakky.core.pod.interfaces.container import IContainer


async def execute_check(scope: IContainer, project_id: str, session_id: str,
                  task_id: str, directory: Path, target_revision: str) -> ExecutePhaseResult:
    phase = PhaseDefinition(
        key="check", purpose="프로그램 정상 종료 확인",
        arguments=(sys.executable, "-c", "print('ok')"),
        directory=str(directory), target_revision=target_revision,
    )
    definition = WorkflowDefinition(
        skill="qa", version="example-1", phases=(phase,), inputs=(),
    )
    task = (await scope.get(GetTaskUseCase).run(
        GetTaskQuery(project_id, session_id, task_id)
    )).task
    flow = (await scope.get(StartWorkflowUseCase).run(
        StartWorkflowCommand(project_id, session_id, task_id, task.revision, definition)
    )).run
    return await scope.get(ExecutePhaseUseCase).run(
        ExecutePhaseCommand(project_id, session_id, flow.uid, flow.revision)
    )
```

## 실행·복구와 태스크 상태

기본 `SubprocessPhaseExecutorService`는 POSIX 프로세스 그룹을 실행합니다. 실패 종료 코드, 시간 초과, interrupt 신호를 관찰하며 그룹을 종료·회수합니다. 파이프를 계속 비우면서 출력은 지정 바이트 한도만 메모리에 보존합니다. 자동으로 충족시키는 검사는 exit:0뿐입니다. 추가 검사가 있으면 프로세스가 성공해도 결과를 waiting으로 두고 별도 관찰·검토 보고를 기다립니다.

외부 실행은 run ID와 시도 번호로 식별합니다. 재개는 lookup을 먼저 사용하고, 실행기가 같은 ID의 중복 제거를 보장할 때만 재제출합니다. 로컬 프로세스 어댑터는 재시작 후 조회·중복 제거를 보장하지 않습니다. 이때 같은 시도를 waiting으로 보존하고 stderr에 원인을 알립니다. 동일한 미확인 상태로 실행·알림을 반복하지 않으며 네이티브 UI의 수신을 주장하지 않습니다.

현재 단계의 결과 불명은 연결 태스크에도 실제 외부 대기로 기록합니다. 같은 결과가 확인되면 그 대기만 해소하며 다른 외부 대기·사용자 정정·취소는 덮어쓰지 않습니다. 다른 독립 태스크는 계속 수행할 수 있습니다. 선택 절차가 현재 요구를 완료하기 전에는 태스크의 새 성공 보고를 거부합니다. 모든 단계가 끝난 후에도 태스크 결과는 별도로 보고합니다.

## 저장과 검증 범위

`core_0004`는 run·정의 개정·단계·시도 테이블을 추가합니다. 기존 프로젝트·세션·원문·태스크는 유지하고 run 이력이 있으면 파괴적 downgrade를 거부합니다. 기본 repository CRUD와 선언형 소유 관계를 재사용하며 단계·시도별 저장소는 두지 않습니다.

시험은 실제 프로세스 실행, DB 잠금 밖의 외부 효과, 동시 예약, 별도 프로세스의 재개 조회, 대상 변경·늦은 결과·필수 검사, 외부 대기·재시도 한도와 이전·rollback을 확인합니다. Codex/Claude 훅 집행, provider 어댑터, 제3자 평가 연결과 실제 사용자 설치는 각각의 후속 티켓에서 구현합니다.
