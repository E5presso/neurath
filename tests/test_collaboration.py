"""실제 SQLite·Spakky로 원 메시지·배정·정정·수신 훅의 경계를 검증한다."""

import importlib
from dataclasses import replace
from uuid import uuid7

import pytest

from neurath.application.ports.repositories.delegation import IDelegationRepository
from neurath.application.ports.repositories.message import IMessageRepository
from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.usecases.receive_hook import ReceiveHookCommand, ReceiveHookUseCase
from neurath.domain.aggregates.conversation import Conversation
from neurath.domain.aggregates.delegation import Delegation
from neurath.domain.aggregates.message import DeliveryStatus, Message
from neurath.domain.aggregates.peer import Peer
from neurath.domain.aggregates.request_source import SourceKind
from neurath.domain.enums.delegation_role import DelegationRole
from neurath.domain.enums.delegation_route import DelegationRoute
from neurath.domain.enums.delegation_status import DelegationStatus
from neurath.domain.enums.hook_action import HookAction
from neurath.domain.enums.hook_event import HookEvent
from neurath.domain.enums.provider_kind import ProviderKind
from neurath.domain.enums.task_status import TaskStatus
from neurath.domain.errors import ContextNotFound, InvalidTaskState
from neurath.domain.values.delegation_report import DelegationReport
from neurath.domain.values.provider_plan import ProviderPlan
from tests.conftest import storage_scope
from tests.support.requests import run
from tests.support.session_requests import register_session
from tests.test_task_requests import create, record


async def call(database, module, name, *args, query=False, **kwargs):
    loaded = importlib.import_module("neurath.application.usecases." + module)
    contract = getattr(loaded, name + ("Query" if query else "Command"))
    from dataclasses import fields

    arguments = dict(zip((field.name for field in fields(contract)), args, strict=False))
    arguments.update(kwargs)
    return await run(
        getattr(loaded, name + "UseCase"),
        contract(**arguments),
        database_path=database,
    )


@pytest.fixture
async def collaboration(database, tmp_path):
    actors = []
    for provider, native in [("codex", "sender"), ("claude", "receiver")]:
        actor = await register_session(str(tmp_path), provider, native, database_path=database)
        await run(
            ReceiveHookUseCase,
            ReceiveHookCommand(
                provider=provider,
                host_session_id=native,
                working_directory=str(tmp_path),
                event=HookEvent.SESSION_START,
                start_source="startup",
            ),
            database_path=database,
        )
        peer = await call(database, "register_peer", "RegisterPeer", actor.session.uid)
        actors.append((actor, peer))
    task = await create(database, actors[0][0])
    return actors[0][0], actors[0][1], actors[1][0], actors[1][1], task


async def prepare(database, context, **kwargs):
    _, sender, _, recipient, task = context
    return await call(
        database,
        "prepare_delegation",
        "PrepareDelegation",
        task.uid,
        sender.uid,
        kwargs.pop("role", DelegationRole.EXECUTOR),
        kwargs.pop("scope", "Implement and test the assigned artifact"),
        kwargs.pop("route", DelegationRoute.PEER),
        kwargs.pop("recipient_id", recipient.uid),
        **kwargs,
    )


async def assignment(database, context):
    delegation = await prepare(database, context)
    return await call(
        database, "dispatch_delegation", "DispatchDelegation", delegation.uid, context[1].uid
    )


async def test_original_message_read_ack_reply_and_closed_conversation(database, collaboration):
    _, sender, _, recipient, task = collaboration
    conversation = await call(
        database, "open_conversation", "OpenConversation", [sender.uid, recipient.uid]
    )
    message = await call(
        database,
        "send_message",
        "SendMessage",
        conversation.uid,
        sender.uid,
        recipient.uid,
        "retry-key",
        "title",
        "original full body",
    )
    again = await call(
        database,
        "send_message",
        "SendMessage",
        conversation.uid,
        sender.uid,
        recipient.uid,
        "retry-key",
        "title",
        "original full body",
    )
    assert message.uid == again.uid
    with pytest.raises(InvalidTaskState):
        await call(
            database,
            "send_message",
            "SendMessage",
            conversation.uid,
            sender.uid,
            recipient.uid,
            "retry-key",
            "title",
            "changed body",
        )
    with pytest.raises(InvalidTaskState):
        await call(
            database, "acknowledge_message", "AcknowledgeMessage", message.uid, recipient.uid
        )
    with pytest.raises(ContextNotFound):
        await call(database, "read_message", "ReadMessage", message.uid, sender.uid)
    context = await call(
        database, "get_collaboration_context", "GetCollaborationContext", recipient.uid, query=True
    )
    assert context.inbox[0].id == message.uid and not context.inbox[0].read
    assert not hasattr(context.inbox[0], "body")
    assert {(p.provider, p.host_session_id) for p in context.peers} == {
        ("codex", "sender"),
        ("claude", "receiver"),
    }
    read = await call(database, "read_message", "ReadMessage", message.uid, recipient.uid)
    assert read.body == "original full body" and read.read and not read.acknowledged
    ack = await call(
        database, "acknowledge_message", "AcknowledgeMessage", message.uid, recipient.uid
    )
    assert ack.acknowledged
    reply = await call(
        database,
        "send_message",
        "SendMessage",
        conversation.uid,
        recipient.uid,
        sender.uid,
        "reply",
        "reply",
        "answer",
        message.uid,
    )
    assert reply.conversation_id == message.conversation_id and reply.reply_to == message.uid
    closed = await call(
        database, "close_conversation", "CloseConversation", conversation.uid, recipient.uid
    )
    assert closed.closed
    with pytest.raises(InvalidTaskState):
        await call(
            database,
            "send_message",
            "SendMessage",
            conversation.uid,
            sender.uid,
            recipient.uid,
            "new",
            "new",
            "new",
        )
    assert (
        await call(database, "read_message", "ReadMessage", message.uid, recipient.uid)
    ).body == read.body
    async with storage_scope(database) as scope:
        assert (await scope.get(ITaskRepository).get(task.uid)).status is TaskStatus.PENDING


async def test_delegation_accept_progress_report_preserves_original_scope_and_role(
    database, collaboration
):
    actor, sender, _, recipient, task = collaboration
    delegation = await assignment(database, collaboration)
    assert delegation.status is DelegationStatus.ASSIGNED
    assert (await prepare(database, collaboration)).uid == delegation.uid
    assert (
        await call(
            database, "dispatch_delegation", "DispatchDelegation", delegation.uid, sender.uid
        )
    ).message_id == delegation.message_id
    with pytest.raises(ContextNotFound):
        await call(
            database, "dispatch_delegation", "DispatchDelegation", delegation.uid, recipient.uid
        )
    read = await call(database, "read_message", "ReadMessage", delegation.message_id, recipient.uid)
    assert str(task.definition.source_id) in read.body and "original requirement text" in read.body
    await call(database, "acknowledge_message", "AcknowledgeMessage", read.uid, recipient.uid)
    assert (
        await call(
            database, "get_delegation", "GetDelegation", delegation.uid, sender.uid, query=True
        )
    ).status is DelegationStatus.ASSIGNED
    accepted = await call(
        database, "accept_delegation", "AcceptDelegation", delegation.uid, recipient.uid
    )
    assert accepted.status is DelegationStatus.ACCEPTED
    await call(database, "accept_delegation", "AcceptDelegation", delegation.uid, recipient.uid)
    progressed = await call(
        database,
        "advance_delegation",
        "AdvanceDelegation",
        delegation.uid,
        recipient.uid,
        "tests: passed",
    )
    assert progressed.status is DelegationStatus.RUNNING
    await call(
        database,
        "advance_delegation",
        "AdvanceDelegation",
        delegation.uid,
        recipient.uid,
        "tests: passed",
    )
    report = DelegationReport(
        summary="Implemented and verified", references=["artifact:abc", "test:123"]
    )
    completed = await call(
        database, "report_delegation", "ReportDelegation", delegation.uid, recipient.uid, report
    )
    assert completed.report == report and completed.status is DelegationStatus.COMPLETED
    await call(
        database, "report_delegation", "ReportDelegation", delegation.uid, recipient.uid, report
    )
    async with storage_scope(database) as scope:
        assert (await scope.get(ITaskRepository).get(task.uid)).status is TaskStatus.PENDING
    review = await prepare(
        database, collaboration, role=DelegationRole.REVIEWER, scope="Review artifact:abc"
    )
    assert review.role is DelegationRole.REVIEWER and review.source_id == task.definition.source_id
    with pytest.raises(InvalidTaskState):
        await prepare(database, collaboration, scope="different assignment")
    with pytest.raises(ContextNotFound):
        await call(
            database,
            "get_delegation",
            "GetDelegation",
            delegation.uid,
            "unrelated-peer",
            query=True,
        )


async def test_correction_propagates_only_related_assignments_and_old_result_cannot_close_task(
    database, collaboration
):
    actor, sender, _, recipient, task = collaboration
    delegation = await assignment(database, collaboration)
    await call(database, "accept_delegation", "AcceptDelegation", delegation.uid, recipient.uid)
    unrelated = await create(database, actor, title="unrelated work")
    other = await prepare(database, (*collaboration[:4], unrelated))
    correction = await record(
        database, actor, SourceKind.CORRECTION, corrects_id=task.definition.source_id
    )
    corrected = await call(
        database,
        "correct_task",
        "CorrectTask",
        task.project_id,
        actor.session.uid,
        task.uid,
        task.revision,
        correction.uid,
        required_result="updated result",
    )
    current = await call(
        database, "get_delegation", "GetDelegation", delegation.uid, sender.uid, query=True
    )
    assert current.status is DelegationStatus.STOP_REQUESTED and current.stop_evidence is None
    assert (
        await call(database, "get_delegation", "GetDelegation", other.uid, sender.uid, query=True)
    ).stop_reason is None
    for module, name, args in [
        ("accept_delegation", "AcceptDelegation", ()),
        ("advance_delegation", "AdvanceDelegation", ("late execution",)),
    ]:
        with pytest.raises(InvalidTaskState):
            await call(database, module, name, delegation.uid, recipient.uid, *args)
    late = await call(
        database,
        "report_delegation",
        "ReportDelegation",
        delegation.uid,
        recipient.uid,
        DelegationReport(summary="old result", references=["old-revision"]),
    )
    assert late.status is DelegationStatus.STOP_REQUESTED and late.definition_number == 1
    assert corrected.task.status is TaskStatus.PENDING
    stopped = await call(
        database,
        "confirm_delegation_stop",
        "ConfirmDelegationStop",
        delegation.uid,
        recipient.uid,
        "host: stopped",
    )
    assert stopped.status is DelegationStatus.STOPPED
    await call(database, "reconcile_delegations", "ReconcileDelegations", task.uid)
    async with storage_scope(database) as scope:
        messages = await scope.get(IMessageRepository).find_by_recipient_id(recipient.uid)
        assert len(messages) == 2
        assert len((await scope.get(IDelegationRepository).get(delegation.uid)).progress) == 0


async def test_hook_delivers_summary_once_without_ack_or_task_acceptance(database, collaboration):
    _, sender, receiver, recipient, _ = collaboration
    delegation = await assignment(database, collaboration)
    command = ReceiveHookCommand(
        provider="claude",
        host_session_id="receiver",
        working_directory=receiver.session.working_directory,
        event=HookEvent.PRE_TOOL_USE,
    )
    first = await run(ReceiveHookUseCase, command, database_path=database)
    assert len(first.inbox) == 1 and str(delegation.message_id) in first.inbox[0]
    assert not (await run(ReceiveHookUseCase, command, database_path=database)).inbox
    async with storage_scope(database) as scope:
        message = await scope.get(IMessageRepository).get(delegation.message_id)
        assert (
            message.status is DeliveryStatus.UNKNOWN
            and not message.read
            and not message.acknowledged
        )
        assert (
            await scope.get(IDelegationRepository).get(delegation.uid)
        ).status is DelegationStatus.ASSIGNED


async def test_delivery_recovery_does_not_regress_ack_or_resend_unknown(database, collaboration):
    _, sender, _, recipient, _ = collaboration
    delegation = await assignment(database, collaboration)
    begun = await call(
        database, "begin_delivery", "BeginDelivery", delegation.message_id, sender.uid
    )
    assert begun.delivery_attempt == 1
    with pytest.raises(InvalidTaskState):
        await call(database, "begin_delivery", "BeginDelivery", begun.uid, sender.uid)
    failed = await call(
        database,
        "record_delivery",
        "RecordDelivery",
        begun.uid,
        1,
        DeliveryStatus.FAILED,
        "host refused before submission",
    )
    assert failed.status is DeliveryStatus.FAILED
    retried = await call(database, "begin_delivery", "BeginDelivery", begun.uid, sender.uid)
    assert retried.uid == begun.uid and retried.delivery_attempt == 2
    await call(
        database,
        "record_delivery",
        "RecordDelivery",
        begun.uid,
        1,
        DeliveryStatus.FAILED,
        "late old failure",
    )
    await call(database, "read_message", "ReadMessage", begun.uid, recipient.uid)
    await call(database, "acknowledge_message", "AcknowledgeMessage", begun.uid, recipient.uid)
    late = await call(
        database,
        "record_delivery",
        "RecordDelivery",
        begun.uid,
        2,
        DeliveryStatus.FAILED,
        "late failure",
    )
    assert late.status is DeliveryStatus.DELIVERED and late.acknowledged
    with pytest.raises(ContextNotFound):
        await call(database, "begin_delivery", "BeginDelivery", begun.uid, recipient.uid)


async def test_inbox_pagination_validation_and_subscription(database, collaboration):
    _, sender, _, recipient, _ = collaboration
    conversation = await call(
        database, "open_conversation", "OpenConversation", [sender.uid, recipient.uid]
    )
    for i in range(3):
        await call(
            database,
            "send_message",
            "SendMessage",
            conversation.uid,
            sender.uid,
            recipient.uid,
            str(i),
            "notice",
            "long body",
        )
    first = await call(
        database,
        "get_collaboration_context",
        "GetCollaborationContext",
        recipient.uid,
        limit=2,
        query=True,
    )
    assert len(first.inbox) == 2 and first.next_after_id
    second = await call(
        database,
        "get_collaboration_context",
        "GetCollaborationContext",
        recipient.uid,
        after_id=first.next_after_id,
        limit=2,
        query=True,
    )
    assert len(second.inbox) == 1 and second.next_after_id is None
    assert not {m.id for m in first.inbox} & {m.id for m in second.inbox}
    subscribed = await call(
        database, "subscribe_peer", "SubscribePeer", recipient.uid, ["task-updates"]
    )
    assert subscribed.subscriptions == ["task-updates"]
    with pytest.raises(ValueError):
        await call(
            database,
            "get_collaboration_context",
            "GetCollaborationContext",
            recipient.uid,
            limit=0,
            query=True,
        )
    with pytest.raises(ContextNotFound):
        await call(
            database, "get_collaboration_context", "GetCollaborationContext", uuid7(), query=True
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("key", " "),
        ("topic", " "),
        ("title", " "),
        ("body", " "),
        ("body", "x" * 1048577),
        ("recipient_id", "sender"),
    ],
)
def test_invalid_message_envelope(field, value):
    values = dict(
        uid="m",
        conversation_id="c",
        sender_id="sender",
        recipient_id="receiver",
        key="k",
        title="t",
        body="b",
    )
    values[field] = value
    with pytest.raises(ValueError):
        Message(**values)


@pytest.mark.parametrize("participants", [[], ["one"], ["one", "one"]])
def test_conversation_requires_distinct_peers(participants):
    with pytest.raises(ValueError):
        Conversation(uid="c", participants=participants)


@pytest.mark.parametrize("topics", [[""], ["a", "a"]])
def test_invalid_subscriptions(topics):
    with pytest.raises(ValueError):
        Peer(uid="p", session_id="s").subscribe(topics)


@pytest.mark.parametrize(
    "report",
    [
        dict(summary="", references=["r"]),
        dict(summary="x", references=[]),
        dict(summary="x", references=[""]),
        dict(summary="x", references=["r"], remaining_work=""),
    ],
)
def test_report_requires_evidence(report):
    with pytest.raises(ValueError):
        DelegationReport(**report)


@pytest.mark.parametrize(
    "field,value",
    [
        ("definition_number", 0),
        ("scope", ""),
        ("recipient_id", None),
        ("route", DelegationRoute.PROVIDER),
    ],
)
def test_invalid_assignment(field, value):
    values = dict(
        uid="d",
        task_id="t",
        definition_number=1,
        source_id="s",
        sender_id="a",
        recipient_id="b",
        role=DelegationRole.EXECUTOR,
        scope="work",
        route=DelegationRoute.PEER,
    )
    values[field] = value
    with pytest.raises(ValueError):
        Delegation(**values)


def test_domain_delivery_guards_and_idempotence():
    message = Message(
        uid=Message.next_id(),
        conversation_id="c",
        sender_id="a",
        recipient_id="b",
        key="k",
        title="t",
        body="b",
    )
    with pytest.raises(ValueError):
        message.observe_delivery(0, DeliveryStatus.PENDING, "proof")
    with pytest.raises(ValueError):
        message.observe_delivery(0, DeliveryStatus.FAILED, "")
    message.begin_delivery()
    message.observe_delivery(1, DeliveryStatus.DELIVERED, "delivered")
    message.observe_delivery(1, DeliveryStatus.FAILED, "late")
    assert message.status is DeliveryStatus.DELIVERED
    with pytest.raises(InvalidTaskState):
        message.begin_delivery()
    conversation = Conversation(uid="c", participants=["a", "b"])
    with pytest.raises(ContextNotFound):
        conversation.close("outsider")
    peer = Peer(uid=Peer.next_id(), session_id="s", active=False)
    with pytest.raises(InvalidTaskState):
        peer.require_active()


async def test_assignment_domain_invalid_transitions(database, collaboration):
    _, sender, _, recipient, task = collaboration
    prepared = await prepare(database, collaboration)
    with pytest.raises(InvalidTaskState):
        prepared.accept(recipient.uid, task)
    with pytest.raises(InvalidTaskState):
        prepared.advance(recipient.uid, task, "started")
    with pytest.raises(InvalidTaskState):
        prepared.complete(recipient.uid, DelegationReport(summary="too early", references=["r"]))
    prepared.assign("m")
    prepared.assign("m")
    assert prepared.message_id == "m" and prepared.status is DelegationStatus.ASSIGNED
    with pytest.raises(InvalidTaskState):
        prepared.assign("different")
    with pytest.raises(ContextNotFound):
        prepared.accept(sender.uid, task)
    prepared.accept(recipient.uid, task)
    with pytest.raises(ValueError):
        prepared.advance(recipient.uid, task, "")
    prepared.advance(recipient.uid, task, "actual start")
    prepared.accept(recipient.uid, task)
    report = DelegationReport(summary="done", references=["r"])
    prepared.complete(recipient.uid, report)
    with pytest.raises(InvalidTaskState):
        prepared.complete(recipient.uid, DelegationReport(summary="changed", references=["r"]))
    with pytest.raises(InvalidTaskState):
        prepared.confirm_stop(recipient.uid, "stopped")
    with pytest.raises(InvalidTaskState):
        prepared.request_provider(task, "scope")


@pytest.mark.parametrize("policy", ["", "inherit"])
def test_provider_plan_never_silently_inherits_permissions(policy):
    with pytest.raises(ValueError):
        ProviderPlan(
            provider=ProviderKind.CODEX,
            model="model",
            policy=policy,
            directory="/tmp",
            parent_session_id="s",
        )


async def test_publication_uses_current_subscriptions_but_retry_keeps_original_recipients(
    database, collaboration
):
    _, sender, _, recipient, _ = collaboration
    conversation = await call(
        database, "open_conversation", "OpenConversation", [sender.uid, recipient.uid]
    )
    assert (
        await call(
            database,
            "read_conversation",
            "ReadConversation",
            conversation.uid,
            sender.uid,
            query=True,
        )
    ).participants == [sender.uid, recipient.uid]
    assert (
        await call(
            database,
            "publish_message",
            "PublishMessage",
            conversation.uid,
            sender.uid,
            "topic",
            "batch",
            "title",
            "body",
        )
        == ()
    )
    await call(database, "subscribe_peer", "SubscribePeer", recipient.uid, ["topic"])
    messages = await call(
        database,
        "publish_message",
        "PublishMessage",
        conversation.uid,
        sender.uid,
        "topic",
        "batch",
        "title",
        "body",
    )
    assert len(messages) == 1 and messages[0].topic == "topic"
    with pytest.raises(InvalidTaskState):
        await call(
            database,
            "send_message",
            "SendMessage",
            conversation.uid,
            sender.uid,
            recipient.uid,
            "batch",
            "title",
            "body",
        )
    with pytest.raises(InvalidTaskState):
        await call(
            database,
            "publish_message",
            "PublishMessage",
            conversation.uid,
            sender.uid,
            "changed-topic",
            "batch",
            "title",
            "body",
        )
    await call(database, "subscribe_peer", "SubscribePeer", recipient.uid, [])
    retry = await call(
        database,
        "publish_message",
        "PublishMessage",
        conversation.uid,
        sender.uid,
        "topic",
        "batch",
        "title",
        "body",
    )
    assert [m.uid for m in retry] == [m.uid for m in messages]
    with pytest.raises(InvalidTaskState):
        await call(
            database,
            "publish_message",
            "PublishMessage",
            conversation.uid,
            sender.uid,
            "topic",
            "batch",
            "title",
            "changed",
        )
    with pytest.raises(ValueError):
        await call(
            database,
            "publish_message",
            "PublishMessage",
            conversation.uid,
            sender.uid,
            "",
            "another",
            "title",
            "body",
        )
    async with storage_scope(database) as scope:
        peer = await scope.get(IPeerRepository).get(recipient.uid)
        peer.active = False
        await scope.get(IPeerRepository).save(peer)
        assert len(await scope.get(IPeerRepository).find_by_session_id(peer.session_id)) == 1
    assert (
        await call(
            database,
            "publish_message",
            "PublishMessage",
            conversation.uid,
            sender.uid,
            "topic",
            "new",
            "title",
            "body",
        )
        == ()
    )


async def test_native_child_can_accept_inspect_and_report_without_parent_writer(
    database, collaboration
):
    actor, sender, _, _, task = collaboration
    await run(
        ReceiveHookUseCase,
        ReceiveHookCommand(
            provider="codex",
            host_session_id="sender",
            working_directory=actor.session.working_directory,
            event=HookEvent.SUBAGENT_START,
            agent_id="native-child",
        ),
        database_path=database,
    )
    child = await call(database, "register_peer", "RegisterPeer", actor.session.uid, "native-child")
    from neurath.application.usecases.prepare_delegation import PrepareDelegationCommand

    delegation = await call(
        database,
        "delegate_task",
        "DelegateTask",
        PrepareDelegationCommand(
            task_id=task.uid,
            sender_id=sender.uid,
            role=DelegationRole.REVIEWER,
            scope="Review artifact",
            route=DelegationRoute.CHILD,
            recipient_id=child.uid,
        ),
    )
    await call(database, "accept_delegation", "AcceptDelegation", delegation.uid, child.uid)
    await run(
        ReceiveHookUseCase,
        ReceiveHookCommand(
            provider="codex",
            host_session_id="sender",
            working_directory=actor.session.working_directory,
            event=HookEvent.USER_PROMPT_SUBMIT,
            agent_id="native-child",
            turn_id="child-turn",
        ),
        database_path=database,
    )
    read = await run(
        ReceiveHookUseCase,
        ReceiveHookCommand(
            provider="codex",
            host_session_id="sender",
            working_directory=actor.session.working_directory,
            event=HookEvent.PRE_TOOL_USE,
            agent_id="native-child",
            turn_id="child-turn",
            writes=False,
        ),
        database_path=database,
    )
    assert read.action is HookAction.ALLOW
    stop = ReceiveHookCommand(
        provider="codex",
        host_session_id="sender",
        working_directory=actor.session.working_directory,
        event=HookEvent.SUBAGENT_STOP,
        agent_id="native-child",
        turn_id="child-turn",
    )
    assert (
        await run(ReceiveHookUseCase, stop, database_path=database)
    ).action is HookAction.CONTINUE
    await call(
        database,
        "report_delegation",
        "ReportDelegation",
        delegation.uid,
        child.uid,
        DelegationReport(
            summary="Reviewed actual artifact", references=["candidate:123", "tests:passed"]
        ),
    )
    assert (await run(ReceiveHookUseCase, stop, database_path=database)).action is HookAction.ALLOW
    async with storage_scope(database) as scope:
        assert (await scope.get(IPeerRepository).get(child.uid)).current_delegation_id is None


async def test_cancelled_assignment_blocks_only_its_receiver_writes_and_preserves_reads(
    database, collaboration
):
    actor, sender, receiver, recipient, task = collaboration
    assignment = await prepare(database, collaboration)
    await call(database, "dispatch_delegation", "DispatchDelegation", assignment.uid, sender.uid)
    await call(database, "accept_delegation", "AcceptDelegation", assignment.uid, recipient.uid)
    correction = await record(
        database, actor, SourceKind.CORRECTION, corrects_id=task.definition.source_id
    )
    await call(
        database,
        "invalidate_task",
        "InvalidateTask",
        task.project_id,
        actor.session.uid,
        task.uid,
        task.revision,
        correction.uid,
        "cancel",
    )
    command = ReceiveHookCommand(
        provider="claude",
        host_session_id="receiver",
        working_directory=receiver.session.working_directory,
        event=HookEvent.PRE_TOOL_USE,
        turn_id="turn",
        tool_use_id="write",
        writes=True,
    )
    assert (
        await run(ReceiveHookUseCase, command, database_path=database)
    ).action is HookAction.PAUSE
    assert (
        await run(ReceiveHookUseCase, replace(command, writes=False), database_path=database)
    ).action is HookAction.ALLOW
    await call(
        database,
        "confirm_delegation_stop",
        "ConfirmDelegationStop",
        assignment.uid,
        recipient.uid,
        "host actually stopped",
    )
    async with storage_scope(database) as scope:
        assert (await scope.get(IPeerRepository).get(recipient.uid)).current_delegation_id is None


async def test_invalid_routes_and_unobserved_peer_do_not_assign(database, collaboration, tmp_path):
    actor, sender, receiver, recipient, task = collaboration
    with pytest.raises(InvalidTaskState):
        await prepare(database, collaboration, route=DelegationRoute.CHILD)
    with pytest.raises(InvalidTaskState):
        await prepare(database, collaboration, recipient_id=sender.uid)
    plan = ProviderPlan(
        provider=ProviderKind.CODEX,
        model="model",
        policy="read-only",
        directory=str(tmp_path),
        parent_session_id="different",
    )
    with pytest.raises(InvalidTaskState):
        await prepare(
            database, collaboration, route=DelegationRoute.PROVIDER, recipient_id=None, plan=plan
        )
    unobserved = await register_session(
        str(tmp_path), "codex", "unobserved", database_path=database
    )
    with pytest.raises(ContextNotFound):
        await call(database, "register_peer", "RegisterPeer", unobserved.session.uid)
    from neurath.application.ports.repositories.execution import IExecutionRepository
    from neurath.domain.aggregates.execution import Execution

    async with storage_scope(database) as scope:
        await scope.get(IExecutionRepository).save(Execution.create(unobserved.session.uid, ""))
    fresh = await call(database, "register_peer", "RegisterPeer", unobserved.session.uid)
    assert fresh.session_id == unobserved.session.uid
    pending = await prepare(
        database,
        collaboration,
        route=DelegationRoute.PROVIDER,
        recipient_id=None,
        plan=replace(plan, parent_session_id=actor.session.uid),
    )
    with pytest.raises(InvalidTaskState):
        await call(database, "dispatch_delegation", "DispatchDelegation", pending.uid, sender.uid)
    with pytest.raises(InvalidTaskState):
        await call(database, "recover_provider", "RecoverProvider", pending.uid, sender.uid)
    with pytest.raises(ContextNotFound):
        await call(database, "start_provider", "StartProvider", pending.uid, recipient.uid)


async def test_redelegation_keeps_parent_scope_and_cancellation_fence(database, collaboration):
    actor, sender, _, recipient, task = collaboration
    parent = await assignment(database, collaboration)
    from neurath.application.usecases.prepare_delegation import PrepareDelegationCommand

    command = PrepareDelegationCommand(
        task_id=task.uid,
        sender_id=recipient.uid,
        role=DelegationRole.REVIEWER,
        scope="Review assigned artifact",
        route=DelegationRoute.PEER,
        recipient_id=sender.uid,
        parent_id=parent.uid,
    )
    with pytest.raises(InvalidTaskState):
        await call(database, "prepare_delegation", "PrepareDelegation", **vars(command))
    await call(database, "accept_delegation", "AcceptDelegation", parent.uid, recipient.uid)
    child = await call(database, "prepare_delegation", "PrepareDelegation", **vars(command))
    assert child.parent_id == parent.uid and child.source_id == parent.source_id
    correction = await record(
        database, actor, SourceKind.CORRECTION, corrects_id=task.definition.source_id
    )
    await call(
        database,
        "invalidate_task",
        "InvalidateTask",
        task.project_id,
        actor.session.uid,
        task.uid,
        task.revision,
        correction.uid,
        "cancel",
    )
    with pytest.raises(InvalidTaskState):
        await call(database, "prepare_delegation", "PrepareDelegation", **vars(command))
    with pytest.raises(InvalidTaskState):
        await prepare(database, collaboration, role=DelegationRole.REVIEWER)


async def test_reply_cannot_move_to_another_conversation(database, collaboration):
    _, sender, _, recipient, _ = collaboration
    delegation = await assignment(database, collaboration)
    other = await call(
        database, "open_conversation", "OpenConversation", [sender.uid, recipient.uid]
    )
    with pytest.raises(ContextNotFound):
        await call(
            database,
            "send_message",
            "SendMessage",
            other.uid,
            recipient.uid,
            sender.uid,
            "reply",
            "title",
            "body",
            delegation.message_id,
        )


async def test_collaboration_migration_preserves_history_and_rejects_loss(database, collaboration):
    from alembic import command

    from neurath.infrastructure.database import create_database_engine
    from tests.test_task_migrations import migration_config
    from tests.test_task_requests import snapshot

    before = snapshot(database)
    engine = create_database_engine(database, write=True, migration=True)
    try:
        with pytest.raises(RuntimeError, match="Collaboration history"):
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda c: command.downgrade(migration_config(c), "core_0007")
                )
    finally:
        await engine.dispose()
    assert snapshot(database) == before


def test_peer_assignment_lifecycle_does_not_overwrite_another_running_scope():
    peer = Peer(uid="p", session_id="s")
    peer.accept_assignment("one")
    with pytest.raises(InvalidTaskState):
        peer.accept_assignment("two")
    peer.finish_assignment("two")
    assert peer.current_delegation_id == "one"
    peer.finish_assignment("one")
    assert peer.current_delegation_id is None


def test_nominal_ports_fail_loudly_instead_of_reporting_fake_results():
    import asyncio
    import inspect

    from neurath.application.ports.services.provider import IProviderService

    for cls in (IDelegationRepository, IMessageRepository, IPeerRepository, IProviderService):
        for name, member in vars(cls).items():
            if not inspect.isfunction(member):
                continue
            args = [object()] * len(inspect.signature(member).parameters)
            with pytest.raises(NotImplementedError):
                result = member(*args)
                if inspect.isawaitable(result):
                    asyncio.run(result)


async def test_direct_inactive_recipient_is_queued_without_wakeup_and_receives_on_reconnect(
    database, collaboration
):
    _, sender, receiver, recipient, _ = collaboration
    async with storage_scope(database) as scope:
        stored = await scope.get(IPeerRepository).get(recipient.uid)
        stored.active = False
        await scope.get(IPeerRepository).save(stored)
    conversation = await call(
        database, "open_conversation", "OpenConversation", [sender.uid, recipient.uid]
    )
    direct = await call(
        database,
        "send_message",
        "SendMessage",
        conversation.uid,
        sender.uid,
        recipient.uid,
        "direct",
        "queued notice",
        "original body",
    )
    delegated = await assignment(database, collaboration)
    assert direct.status is DeliveryStatus.PENDING and delegated.status is DelegationStatus.ASSIGNED
    async with storage_scope(database) as scope:
        assert not (await scope.get(IPeerRepository).get(recipient.uid)).active
    connected = await run(
        ReceiveHookUseCase,
        ReceiveHookCommand(
            provider="claude",
            host_session_id="receiver",
            working_directory=receiver.session.working_directory,
            event=HookEvent.SESSION_START,
            start_source="resume",
        ),
        database_path=database,
    )
    assert len(connected.inbox) == 2
    assert any(str(direct.uid) in message for message in connected.inbox)
    assert any(str(delegated.message_id) in message for message in connected.inbox)


@pytest.mark.parametrize("provider_route", [False, True])
async def test_assignment_text_preserves_source_order_and_literal_newlines(
    database, collaboration, monkeypatch, provider_route
):
    from neurath.application.ports.services.provider import (
        ProviderCapabilities,
        ProviderObservation,
    )
    from neurath.domain.enums.provider_status import ProviderStatus
    from neurath.infrastructure.services.provider import SubprocessProviderService

    actor, sender, _, recipient, task = collaboration
    correction = await call(
        database,
        "record_source",
        "RecordSource",
        task.project_id,
        actor.session.uid,
        SourceKind.CORRECTION,
        "정정 첫째 줄\n정정 둘째 줄",
        corrects_id=task.definition.source_id,
    )
    corrected = await call(
        database,
        "correct_task",
        "CorrectTask",
        task.project_id,
        actor.session.uid,
        task.uid,
        task.revision,
        correction.source.uid,
        required_result="수정된 결과",
    )
    context = (*collaboration[:4], corrected.task)
    original_line = f"Source {task.definition.source_id}: original requirement text"
    correction_lines = f"Source {correction.source.uid}: 정정 첫째 줄\n정정 둘째 줄"
    prompts = []

    def start(self, uid, plan, prompt):
        prompts.append(prompt)
        return ProviderObservation(reference="fixture:run", status=ProviderStatus.RUNNING)

    if provider_route:
        monkeypatch.setattr(
            SubprocessProviderService,
            "discover",
            lambda self, provider: ProviderCapabilities(
                provider=provider,
                models=["fixture-model"],
                policies=["read-only"],
            ),
        )
        monkeypatch.setattr(SubprocessProviderService, "start", start)
        delegation = await prepare(
            database,
            context,
            route=DelegationRoute.PROVIDER,
            recipient_id=None,
            plan=ProviderPlan(
                provider=ProviderKind.CODEX,
                model="fixture-model",
                policy="read-only",
                directory=actor.session.working_directory,
                parent_session_id=actor.session.uid,
            ),
        )
        await call(database, "start_provider", "StartProvider", delegation.uid, sender.uid)
        assert prompts == [
            f"Delegation {delegation.uid}; role {delegation.role}; task {task.uid}; definition 2\n"
            f"Original source {correction.source.uid}:\n{original_line}\n{correction_lines}\n"
            "Required result: 수정된 결과\nAssigned scope: Implement and test the assigned artifact\n"
            "Work only within this assignment. Report concrete evidence and remaining work."
        ]
        return
    delegation = await assignment(database, context)
    message = await call(
        database, "read_message", "ReadMessage", delegation.message_id, recipient.uid
    )
    assert message.body == (
        f"Delegation: {delegation.uid}\nTask: {task.uid} / definition 2\nRole: {delegation.role}\n"
        f"Source: {correction.source.uid}\n{original_line}\n{correction_lines}\n"
        "Required result: 수정된 결과\nAssigned scope: Implement and test the assigned artifact\n"
        "Accept the current assignment before execution; report evidence and remaining work to this assignment."
    )
