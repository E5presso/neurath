"""기존 요구의 범위·수신자·경로를 검증해 배정 계획을 저장하며 아직 실행하지 않는다."""

import asyncio
from dataclasses import replace
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
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
from neurath.domain.aggregates.peer import Peer
from neurath.domain.aggregates.project import Project
from neurath.domain.aggregates.session import HostSession
from neurath.domain.aggregates.task import Task
from neurath.domain.delegation_records import (
    DelegationRole,
    DelegationRoute,
    ProviderPlan,
)
from neurath.domain.errors import InvalidTaskState
from neurath.domain.observations import DirectoryObservation


@immutable
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

    task_id: UUID
    sender_id: UUID
    role: DelegationRole
    scope: str
    route: DelegationRoute
    recipient_id: UUID | None = None
    plan: ProviderPlan | None = None
    parent_id: UUID | None = None


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

        """
        observation = await self._observe_provider_directory(command.plan)
        sender = await self.peers.get(command.sender_id)
        sender.require_active()
        session = await self.sessions.get(sender.session_id)
        session.require_current_owner()
        plan = await self._resolve_provider_plan(command.plan, observation, session.project_id)

        task = await self.tasks.get(command.task_id)
        await self._load_assignment_scope(task, session, sender, command.parent_id)
        await self._load_recipient(command.recipient_id, sender, command.route)
        if plan is not None:
            plan.require_parent(session.uid)

        candidate = Delegation(
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
        existing = candidate.find_reusable(await self.delegations.find_by_task_id(task.uid))
        if existing is not None:
            return existing
        return await self.delegations.save(candidate)

    async def _observe_provider_directory(
        self, plan: ProviderPlan | None
    ) -> DirectoryObservation | None:
        """첫 DB 접근 전에 독립 실행의 실제 작업 폴더를 관찰한다.

        Args:
            plan: 독립 실행 계획이며 피어 배정이면 None.

        Returns:
            DirectoryObservation | None: 정규 위치 관찰 또는 None.
        """
        if plan is None:
            return None
        return await asyncio.to_thread(self.directories.observe, plan.directory)

    async def _resolve_provider_plan(
        self, plan: ProviderPlan | None, observation: DirectoryObservation | None, project_id: UUID
    ) -> ProviderPlan | None:
        """관찰한 위치의 프로젝트를 확인하고 계획에 정규 경로를 반영한다.

        Args:
            plan: 원래 모델·정책을 담은 계획.
            observation: DB 조회 전에 얻은 실제 위치.
            project_id: 배정 세션이 속한 프로젝트.

        Returns:
            ProviderPlan | None: 같은 프로젝트의 정규 경로를 사용하는 계획.

        Raises:
            InvalidTaskState: 실행 폴더가 등록된 같은 프로젝트에 속하지 않는 경우.
        """
        if plan is None or observation is None:
            return None
        owners = []
        for location in Project.identify(observation):
            owner = await self.projects.find_by_location(location)
            if owner is not None:
                owners.append(owner)
        project = Project.owner_of(owners)
        if project is None or project.uid != project_id:
            raise InvalidTaskState("Provider working directory belongs to another project")
        return replace(plan, directory=observation.working_directory)

    async def _load_assignment_scope(
        self, task: Task, session: HostSession, sender: Peer, parent_id: UUID | None
    ) -> None:
        """직접 배정의 소유 범위 또는 재위임의 현재 부모 배정을 읽어 검증한다.

        Args:
            task: 배정할 원 태스크.
            session: 실제 발신 세션.
            sender: 발신 피어.
            parent_id: 수락한 부모 배정이며 직접 배정이면 None.
        """
        if parent_id is None:
            task.require_scope(session.project_id, session.uid)
        else:
            parent = await self.delegations.get(parent_id)
            parent.require_redelegation(task, sender.uid)
        task.require_delegatable()

    async def _load_recipient(
        self, recipient_id: UUID | None, sender: Peer, route: DelegationRoute
    ) -> None:
        """수신자와 실제 세션을 읽고 도메인에 경로 검증을 맡긴다.

        Args:
            recipient_id: 대상 피어이며 독립 실행 준비 단계면 None.
            sender: 배정하는 피어.
            route: 명시한 수신 경로.
        """
        if recipient_id is None:
            return
        recipient = await self.peers.get(recipient_id)
        (await self.sessions.get(recipient.session_id)).require_current_owner()
        recipient.require_recipient_route(sender, route)
