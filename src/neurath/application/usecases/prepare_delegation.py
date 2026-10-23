"""기존 요구의 범위·수신자·경로를 검증해 배정 계획을 저장하며 아직 실행하지 않는다."""

import asyncio
from dataclasses import dataclass, replace
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.delegation import IDelegationRepository
from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.services.directory_observer import IDirectoryObserverService
from neurath.domain.aggregates.delegation import Delegation
from neurath.domain.aggregates.project import Project
from neurath.domain.delegation_records import (
    DelegationRole,
    DelegationRoute,
    DelegationStatus,
    ProviderPlan,
)
from neurath.domain.errors import InvalidTaskState
from neurath.domain.task_records import TaskStatus


@dataclass(frozen=True)
class PrepareDelegationCommand(AbstractCommand):
    """기존 요구의 범위·수신자·경로를 검증해 배정 계획을 저장하며 아직 실행하지 않는다.

    Attributes:
        task_id: 기존 요청에 연결된 작업.
        sender_id: 배정 책임이 있는 발신 피어.
        role: 수행 또는 검토 책임.
        scope: 맡길 명시적 작업 범위.
        route: 실제 피어·자식·독립 실행 경로.
        recipient_id: 실제 등록된 수신 피어.
        plan: 독립 실행의 검증된 모델·정책 계획.
        parent_id: 재위임이면 수신자가 수락한 기존 배정. 원 지시를 바꾸지 않는다.
    """

    task_id: str
    sender_id: str
    role: DelegationRole
    scope: str
    route: DelegationRoute
    recipient_id: str | None = None
    plan: ProviderPlan | None = None
    parent_id: str | None = None


@UseCase()
class PrepareDelegationUseCase(IAsyncCommandUseCase[PrepareDelegationCommand, Delegation]):
    """기존 요구의 범위·수신자·경로를 검증해 배정 계획을 저장하며 아직 실행하지 않는다."""

    def __init__(
        self,
        peers: IPeerRepository,
        sessions: ISessionRepository,
        tasks: ITaskRepository,
        delegations: IDelegationRepository,
        directories: IDirectoryObserverService,
        projects: IProjectRepository,
    ) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            peers: Peer aggregate의 범위 조회와 저장.
            sessions: Session aggregate의 범위 조회와 저장.
            tasks: Task aggregate의 범위 조회와 저장.
            delegations: Delegation aggregate의 범위 조회와 저장.
            directories: 독립 실행 폴더의 실제 프로젝트 위치를 관찰한다.
            projects: 관찰한 작업 폴더가 같은 프로젝트인지 대조한다.
        """
        self.peers = peers
        self.sessions = sessions
        self.tasks = tasks
        self.delegations = delegations
        self.directories = directories
        self.projects = projects

    @transactional
    @override
    async def run(self, command: PrepareDelegationCommand) -> Delegation:
        """기존 요구의 범위·수신자·경로를 검증해 배정 계획을 저장하며 아직 실행하지 않는다.

        Args:
            command: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Delegation: 요청한 범위에서 저장 또는 조회한 결과.

        Raises:
            InvalidTaskState: 최신 배정·수신 경로·원문과 충돌하는 요청인 경우.
        """
        observation = None
        if command.plan is not None:
            observation = await asyncio.to_thread(self.directories.observe, command.plan.directory)
        plan = command.plan
        if plan is not None and observation is not None:
            plan = replace(plan, directory=observation.working_directory)
        sender = await self.peers.get(command.sender_id)
        sender.require_active()
        session = await self.sessions.get(sender.session_id)
        session.require_current_owner()
        if observation is not None:
            owners = []
            for location in Project.identify(observation):
                owner = await self.projects.find_by_location(location)
                if owner is not None:
                    owners.append(owner)
            project = Project.owner_of(owners)
            if project is None or project.uid != session.project_id:
                raise InvalidTaskState("Provider working directory belongs to another project")
        task = await self.tasks.get(command.task_id)
        if command.parent_id is None:
            task.require_scope(session.project_id, session.uid)
        else:
            parent = await self.delegations.get(command.parent_id)
            parent.require_recipient(sender.uid)
            parent.require_current(task)
            if parent.status not in (DelegationStatus.ACCEPTED, DelegationStatus.RUNNING):
                raise InvalidTaskState("Redelegation requires an accepted current assignment")
        if task.status in (TaskStatus.INVALIDATED, TaskStatus.SUCCEEDED):
            raise InvalidTaskState("Only unfinished current work can be delegated")
        if command.recipient_id is not None:
            recipient = await self.peers.get(command.recipient_id)
            (await self.sessions.get(recipient.session_id)).require_current_owner()
            if recipient.uid == sender.uid:
                raise InvalidTaskState("Delegate to a distinct peer")
            if command.route is DelegationRoute.CHILD and (
                recipient.session_id != sender.session_id or not recipient.agent_id
            ):
                raise InvalidTaskState(
                    "Native child route requires an observed child of this host session"
                )
        if plan is not None and plan.parent_session_id != session.uid:
            raise InvalidTaskState("Provider plan belongs to a different parent session")
        for existing in await self.delegations.find_by_task_id(task.uid):
            if (
                existing.definition_number == task.definition.number
                and existing.role is command.role
                and existing.parent_id is None
                and command.parent_id is None
                and existing.sender_id != sender.uid
            ):
                raise InvalidTaskState(
                    "This task revision already has a root assignment; recover it instead of duplicating execution"
                )
            if (
                existing.definition_number == task.definition.number
                and existing.role is command.role
                and existing.sender_id == sender.uid
            ):
                if (
                    existing.sender_id,
                    None if existing.plan is not None else existing.recipient_id,
                    existing.scope,
                    existing.route,
                    existing.plan,
                ) != (
                    command.sender_id,
                    command.recipient_id,
                    command.scope,
                    command.route,
                    plan,
                ):
                    raise InvalidTaskState("This definition and role already have an assignment")
                return existing
        delegation = Delegation(
            uid=Delegation.next_id(),
            task_id=task.uid,
            definition_number=task.definition.number,
            source_id=task.definition.source_id,
            sender_id=sender.uid,
            recipient_id=command.recipient_id,
            role=command.role,
            scope=command.scope,
            route=command.route,
            plan=plan,
            parent_id=command.parent_id,
        )
        return await self.delegations.save(delegation)
