"""현재 호스트의 작업 정의·진행·결과를 같은 원장에 연결한다."""

import json
from dataclasses import asdict
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from spakky.plugins.typer.stereotypes.cli_controller import CliController, command
from typer import Option, echo

from neurath.application.usecases.accept_delegation import (
    AcceptDelegationCommand,
    AcceptDelegationUseCase,
)
from neurath.application.usecases.correct_task import CorrectTaskCommand, CorrectTaskUseCase
from neurath.application.usecases.create_current_task import (
    CreateCurrentTaskCommand,
    CreateCurrentTaskUseCase,
)
from neurath.application.usecases.get_sources import GetSourcesQuery, GetSourcesUseCase
from neurath.application.usecases.get_task import GetTaskQuery, GetTaskUseCase
from neurath.application.usecases.invalidate_task import (
    InvalidateTaskCommand,
    InvalidateTaskUseCase,
)
from neurath.application.usecases.report_delegation import (
    ReportDelegationCommand,
    ReportDelegationUseCase,
)
from neurath.application.usecases.report_result import ReportResultCommand, ReportResultUseCase
from neurath.application.usecases.resolve_session_context import (
    ResolveSessionContextQuery,
    ResolveSessionContextUseCase,
)
from neurath.application.usecases.resume_task import ResumeTaskCommand, ResumeTaskUseCase
from neurath.application.usecases.start_task import StartTaskCommand, StartTaskUseCase
from neurath.application.usecases.wait_task import WaitTaskCommand, WaitTaskUseCase
from neurath.domain.aggregates.request_source import SourceKind
from neurath.domain.aggregates.task import Task
from neurath.domain.values.delegation_report import DelegationReport
from neurath.domain.values.external_wait import ExternalWait
from neurath.domain.values.task_attempt import Outcome, TaskResult
from neurath.domain.values.task_monitor import MonitorKind
from neurath.serialization import encode_uuid


class TaskAction(StrEnum):
    """같은 작업 원장의 수행·대기·정정 전이를 구분한다.

    Attributes:
        START: 현재 요구 수행을 시작한다.
        WAIT: 실제 외부 의존을 기다린다.
        RESUME: 해소된 의존의 같은 작업을 이어간다.
        CORRECT: 실제 사용자 정정을 관련 필드에 반영한다.
        CANCEL: 원 요구를 무효화하되 이력을 보존한다.
        ACCEPT: 수신한 실제 배정을 받아 수행한다.
    """

    START = "start"
    WAIT = "wait"
    RESUME = "resume"
    CORRECT = "correct"
    CANCEL = "cancel"
    ACCEPT = "accept"


@CliController("task")
class TaskCliController:
    """내부 프로젝트·세션 ID 대신 현재 호스트 맥락으로 작업을 호출한다."""

    def __init__(
        self,
        context: ResolveSessionContextUseCase,
        create: CreateCurrentTaskUseCase,
        read: GetTaskUseCase,
        sources: GetSourcesUseCase,
        start: StartTaskUseCase,
        wait: WaitTaskUseCase,
        resume: ResumeTaskUseCase,
        correct: CorrectTaskUseCase,
        cancel: InvalidateTaskUseCase,
        report: ReportResultUseCase,
        accept: AcceptDelegationUseCase,
        report_delegation: ReportDelegationUseCase,
        connection: AsyncConnectionManager,
    ) -> None:
        """실제 작업 단위와 현재 호스트 조회 계약을 받는다.

        Args:
            context: 현재 호스트 범위 조회.
            create: 원문에 작업을 연결한다.
            read: 현재 개정 조회.
            sources: 실제 사용자 원문 조회.
            start: 작업 수행 시작.
            wait: 외부 대기 기록.
            resume: 같은 작업의 대기 해소.
            correct: 실제 정정 반영.
            cancel: 원 요구 무효화와 이력 보존.
            report: 실제 관찰 결과 저장.
            accept: 받은 배정 수락.
            report_delegation: 원 담당자에게 결과 반환.
            connection: 명령 이벤트 루프의 정리.
        """
        self.context = context
        self.create = create
        self.read = read
        self.sources = sources
        self.start = start
        self.wait = wait
        self.resume = resume
        self.correct = correct
        self.cancel = cancel
        self.report = report
        self.accept = accept
        self.report_delegation = report_delegation
        self.connection = connection

    @staticmethod
    def _output(task: Task) -> None:
        """현재 요구와 남은 상태를 성공으로 부풀리지 않고 출력한다.

        Args:
            task: 실제 저장한 작업.
        """
        echo(
            json.dumps(
                {
                    "id": task.uid,
                    "status": task.status,
                    "title": task.definition.title,
                    "required_result": task.definition.required_result,
                    "source_id": task.definition.source_id,
                    "attempt": task.current_attempt_number,
                    "monitors": [
                        {
                            "number": item.number,
                            "active": item.active,
                            "callback": f"NEURATH_MONITOR_TICK {task.uid} {item.number}",
                            "remaining_polls": item.remaining_polls,
                            "events": [asdict(event) for event in item.events],
                        }
                        for item in task.monitors
                    ],
                },
                default=encode_uuid,
                ensure_ascii=False,
            )
        )

    @command("create")
    async def create_task(
        self,
        title: Annotated[str, Option("--title")],
        result: Annotated[str, Option("--result")],
        source_id: UUID | None = None,
        dependency: list[UUID] | None = None,
        start: bool = False,
    ) -> None:
        """현재 원문에서 수행할 결과를 등록한다. 외부 코드는 실행하지 않는다.

        Args:
            title: 수행할 일의 제목.
            result: 사용자에게 필요한 결과.
            source_id: 이전 원문을 선택할 때만 지정한다.
            dependency: 선행 작업 ID 목록.
            start: 지금 수행하는 작업의 시작도 기록한다.
        """
        try:
            task = await self.create.run(
                CreateCurrentTaskCommand(
                    title=title,
                    required_result=result,
                    source_id=source_id,
                    dependencies=() if dependency is None else dependency,
                    start=start,
                )
            )
            self._output(task)
        finally:
            await self.connection.dispose()

    @command("update")
    async def update_task(
        self,
        action: Annotated[TaskAction, Option("--action")],
        task_id: UUID | None = None,
        delegation_id: UUID | None = None,
        reason: str = "",
        target: str = "",
        condition: str = "",
        resume_scope: str = "",
        title: str | None = None,
        result: str | None = None,
        source_id: UUID | None = None,
        monitor: MonitorKind | None = None,
        poll_budget: int = 100,
        monitor_event: int | None = None,
    ) -> None:
        """현재 조회한 개정으로 실제 수행·외부 대기·사용자 정정을 기록한다.

        Args:
            action: 같은 작업의 전이 목적.
            task_id: 선택한 기존 작업.
            delegation_id: 수락할 원 배정.
            reason: 실제 관찰 또는 정정 이유.
            target: 대기하는 외부 대상.
            condition: 대기의 실제 해소 조건.
            resume_scope: 기존 지시에서 이어갈 범위.
            title: 정정한 작업 제목.
            result: 정정한 필요 결과.
            source_id: 정정 원문이며 미지정이면 최신 실제 원문.
            monitor: 요청된 감시에만 지정하는 실제 관찰 종류.
            poll_budget: 요청한 감시의 유한 관찰 횟수.
            monitor_event: 재개 근거로 삼은 현재 감시의 실제 사건 순번.

        Raises:
            ValueError: 해당 동작에 필요한 대상이 없거나 실제 원문이 없는 경우.
        """
        try:
            scope = await self.context.run(ResolveSessionContextQuery())
            if action is TaskAction.ACCEPT:
                if delegation_id is None or scope.peer is None:
                    raise ValueError("An observed recipient and delegation ID are required")
                assignment = await self.accept.run(
                    AcceptDelegationCommand(delegation_id=delegation_id, peer_id=scope.peer.uid)
                )
                echo(
                    json.dumps(
                        {"delegation_id": assignment.uid, "status": assignment.status},
                        default=encode_uuid,
                    )
                )
                return
            if task_id is None:
                raise ValueError("Select a task from context show")
            task = (
                await self.read.run(
                    GetTaskQuery(
                        project_id=scope.session.project_id,
                        session_id=scope.session.uid,
                        task_id=task_id,
                    )
                )
            ).task
            if action is TaskAction.START:
                task = (
                    await self.start.run(
                        StartTaskCommand(
                            project_id=task.project_id,
                            session_id=task.owner_session_id,
                            task_id=task.uid,
                            expected_revision=task.revision,
                        )
                    )
                ).task
                self._output(task)
                return
            if action is TaskAction.WAIT:
                task = (
                    await self.wait.run(
                        WaitTaskCommand(
                            project_id=task.project_id,
                            session_id=task.owner_session_id,
                            task_id=task.uid,
                            expected_revision=task.revision,
                            monitor=monitor,
                            poll_budget=poll_budget,
                            condition=ExternalWait(
                                target=target,
                                condition=condition,
                                resume_scope=resume_scope,
                                observation=reason,
                            ),
                        )
                    )
                ).task
                self._output(task)
                return
            if action is TaskAction.RESUME:
                task = (
                    await self.resume.run(
                        ResumeTaskCommand(
                            project_id=task.project_id,
                            session_id=task.owner_session_id,
                            task_id=task.uid,
                            expected_revision=task.revision,
                            resolution=reason,
                            monitor_event=monitor_event,
                        )
                    )
                ).task
                self._output(task)
                return
            if source_id is None:
                records = await self.sources.run(
                    GetSourcesQuery(project_id=task.project_id, session_id=task.owner_session_id)
                )
                source = next(
                    (
                        item
                        for item in reversed(records.sources)
                        if item.session_id == task.owner_session_id
                        and item.kind not in (SourceKind.STATUS, SourceKind.SUMMARY)
                    ),
                    None,
                )
                if source is None:
                    raise ValueError("A real source is required for a correction")
                source_id = source.uid
            if action is TaskAction.CANCEL:
                task = (
                    await self.cancel.run(
                        InvalidateTaskCommand(
                            project_id=task.project_id,
                            session_id=task.owner_session_id,
                            task_id=task.uid,
                            expected_revision=task.revision,
                            source_id=source_id,
                            reason=reason,
                        )
                    )
                ).task
                self._output(task)
                return
            task = (
                await self.correct.run(
                    CorrectTaskCommand(
                        project_id=task.project_id,
                        session_id=task.owner_session_id,
                        task_id=task.uid,
                        expected_revision=task.revision,
                        source_id=source_id,
                        title=title,
                        required_result=result,
                    )
                )
            ).task
            self._output(task)
        finally:
            await self.connection.dispose()

    @command("report")
    async def report_task(
        self,
        summary: Annotated[str, Option("--summary")],
        reference: Annotated[list[str], Option("--reference")],
        task_id: UUID | None = None,
        delegation_id: UUID | None = None,
        outcome: Outcome = Outcome.SUCCEEDED,
        remaining: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        """실제 수행 결과를 원 작업 또는 수신한 배정에 연결한다.

        Args:
            summary: 실제 산출물과 수행 결과.
            reference: 관찰한 근거 참조.
            task_id: 소유 작업 결과를 보고할 때의 ID.
            delegation_id: 수신자로서 원 배정에 보고할 때의 ID.
            outcome: 성공·실패·부분 수행.
            remaining: 실패·부분 수행에 남은 일.
            exit_code: 실제 명령을 관찰한 경우의 종료 코드.

        Raises:
            ValueError: 대상이 모호하거나 현재 수행 시도가 없는 경우.
        """
        try:
            if (task_id is None) == (delegation_id is None):
                raise ValueError("Select exactly one task or received delegation")
            scope = await self.context.run(ResolveSessionContextQuery())
            if delegation_id is not None:
                if scope.peer is None:
                    raise ValueError("The current native recipient has not been observed")
                result = await self.report_delegation.run(
                    ReportDelegationCommand(
                        delegation_id=delegation_id,
                        peer_id=scope.peer.uid,
                        report=DelegationReport(
                            summary=summary, references=reference, remaining_work=remaining
                        ),
                    )
                )
                echo(json.dumps({"id": result.uid, "status": result.status}, default=encode_uuid))
                return
            assert task_id is not None
            task = (
                await self.read.run(
                    GetTaskQuery(
                        project_id=scope.session.project_id,
                        session_id=scope.session.uid,
                        task_id=task_id,
                    )
                )
            ).task
            if task.current_attempt_number is None:
                raise ValueError(
                    "The task has no observed attempt; start the selected work before reporting"
                )
            task = (
                await self.report.run(
                    ReportResultCommand(
                        project_id=task.project_id,
                        session_id=task.owner_session_id,
                        task_id=task.uid,
                        expected_revision=task.revision,
                        attempt_number=task.current_attempt_number,
                        result=TaskResult(
                            outcome=outcome,
                            summary=summary,
                            observations=reference,
                            remaining_work=remaining,
                            exit_code=exit_code,
                        ),
                    )
                )
            ).task
            self._output(task)
        finally:
            await self.connection.dispose()
