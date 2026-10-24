"""선택한 과거 미완료 작업을 현재 관찰 세션으로 연결하고 원래 상태를 보존한다."""

import json
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.historical_archive import IHistoricalArchiveRepository
from neurath.application.ports.repositories.memory import IMemoryRepository
from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.application.ports.services.historical_store import HistoricalRecord
from neurath.domain.aggregates.memory import Memory, MemoryKind
from neurath.domain.aggregates.request_source import RequestSource, SourceKind
from neurath.domain.aggregates.task import Task
from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.domain.values.workflow_definition import PhaseDefinition, WorkflowDefinition


@immutable
class AdoptHistoricalWorkCommand(AbstractCommand):
    """현재 관찰 범위와 실제로 읽은 과거 작업을 지정한다.

    Attributes:
        archive_id: 보존 자료.
        project_id: 현재 관찰 프로젝트.
        session_id: 실제 작업을 이어갈 현재 세션.
        record: 사본에서 읽은 원 작업.
    """

    archive_id: UUID
    project_id: UUID
    session_id: UUID
    record: HistoricalRecord


@UseCase()
class AdoptHistoricalWorkUseCase(IAsyncCommandUseCase[AdoptHistoricalWorkCommand, Task]):
    """과거 성공·신원·임대를 만들지 않고 실제 선택한 미완료 결과만 이어간다."""

    def __init__(
        self,
        archives: IHistoricalArchiveRepository,
        projects: IProjectRepository,
        sessions: ISessionRepository,
        sources: IRequestSourceRepository,
        tasks: ITaskRepository,
        workflows: IWorkflowRepository,
        memories: IMemoryRepository,
    ) -> None:
        """현재 작업과 원본 참조를 같은 트랜잭션에 저장할 계약을 받는다.

        Args:
            archives: 원 작업의 중복 재개 조회.
            projects: 실제 프로젝트 범위.
            sessions: 현재 관찰된 세션.
            sources: 과거 원문과 요구 정의 보존.
            tasks: 실제 현재 작업.
            workflows: 존재하는 과거 미완료 단계의 연결.
            memories: 원래 상태·소유자·증거 보존.
        """
        self.archives = archives
        self.projects = projects
        self.sessions = sessions
        self.sources = sources
        self.tasks = tasks
        self.workflows = workflows
        self.memories = memories

    @transactional
    @override
    async def run(self, command: AdoptHistoricalWorkCommand) -> Task:
        """원본을 수정하지 않고 실제 선택 재개와 현재 작업 연결을 저장한다.

        Args:
            command: 현재 세션과 선택한 원 작업.

        Returns:
            Task: 새로 이어갈 작업 또는 이미 연결된 같은 작업.

        Raises:
            ValueError: 범위·미완료 상태·의존 관계를 안전하게 연결할 수 없는 경우.
        """
        archive = await self.archives.get(command.archive_id)
        project = await self.projects.get(command.project_id)
        session = await self.sessions.get(command.session_id)
        session.require_project(project.uid)
        session.require_current_owner()
        if archive.directory != project.root_path:
            raise ValueError("Historical archive belongs to another selected project")
        prior = await self.archives.find_by_directory_and_origin(
            archive.directory, command.record.origin
        )
        if prior is not None:
            adopted = next(item for item in prior.adoptions if item.origin == command.record.origin)
            return await self.tasks.get(adopted.task_id)
        record = command.record
        if record.category != "tasks" or record.status not in {
            "pending",
            "waiting",
            "active",
            "in_progress",
            "failed",
        }:
            raise ValueError(
                "Select an unfinished historical task; terminal or unknown state was preserved"
            )
        dependencies = []
        prerequisite_phases = []
        for prerequisite in record.data.get("prerequisites", []):
            related = await self.archives.find_by_directory_and_origin(
                archive.directory, prerequisite["origin"]
            )
            if related is not None:
                dependencies.append(
                    next(
                        item.task_id
                        for item in related.adoptions
                        if item.origin == prerequisite["origin"]
                    )
                )
            elif prerequisite["status"] in {"completed", "succeeded"}:
                prerequisite_phases.append(
                    PhaseDefinition(
                        key=f"historical-prerequisite-{len(prerequisite_phases) + 1}",
                        purpose=f"Verify preserved prerequisite {prerequisite['key']} and its original evidence against the current result; historical success is not current verification.",
                        arguments=(),
                        directory=session.working_directory,
                        target_revision="current",
                        checks=("prerequisite-valid",),
                    )
                )
            else:
                raise ValueError(
                    "Resume the unfinished historical prerequisite first; no dependency was marked successful"
                )
        goal = record.data.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError(
                "Historical task has no interpretable goal; original data remains available"
            )
        reference = f"historical:{archive.uid}:task:{record.key}"
        original = record.data.get("source")
        body = original.get("text") if isinstance(original, dict) else None
        if not isinstance(body, str) or not body.strip():
            body = json.dumps(
                {"historical_task_definition": record.data, "original_user_source": "unknown"},
                ensure_ascii=False,
            )
        source = RequestSource.create(
            project.uid,
            session.uid,
            SourceKind.TICKET,
            body,
            "historical source; not a new native user event",
            reference,
        )
        criteria = record.data.get("criteria", [])
        descriptions = [
            str(item.get("description", json.dumps(item, ensure_ascii=False)))
            if isinstance(item, dict)
            else str(item)
            for item in criteria
        ]
        task = Task.create(
            project.uid,
            session.uid,
            source,
            goal,
            "\n".join([goal, *descriptions, *(phase.purpose for phase in prerequisite_phases)]),
            dependencies,
        )
        memory = Memory.create(
            project.uid,
            session.uid,
            task.uid,
            MemoryKind.HANDOFF,
            json.dumps(
                {
                    "historical_status": record.status,
                    "historical_record": record.data,
                    "current_action": "selected resumption; no historical authority or success inferred",
                },
                ensure_ascii=False,
            ),
            (reference, *record.references),
        )
        phases = tuple(prerequisite_phases) + tuple(
            PhaseDefinition(
                key=f"legacy-{item['id']}",
                purpose=f"Reconcile and continue preserved phase: {item['name']}; previous status: {item['status']}",
                arguments=(),
                directory=session.working_directory,
                target_revision="current",
                checks=("observed-result",),
            )
            for item in record.data.get("phases", [])
            if item["status"] not in {"completed", "succeeded", "skipped"}
        )
        await self.sources.save(source)
        task = await self.tasks.save(task)
        current_tasks = await self.tasks.find_by_project_id(project.uid)
        task.validate_dependencies(current_tasks)
        if task.ready(current_tasks):
            task.start(current_tasks)
            task = await self.tasks.save(task)
        if phases:
            await self.workflows.save(
                WorkflowRun.create(
                    project.uid,
                    session.uid,
                    task.uid,
                    task.definition.number,
                    WorkflowDefinition(
                        skill="historical-continuation",
                        version="preserved",
                        phases=phases,
                        inputs=(("original", reference),),
                    ),
                )
            )
        await self.memories.save(memory)
        archive.adopt(record.origin, task.uid)
        await self.archives.save(archive)
        return task
