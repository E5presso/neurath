"""실제 SQLite·스캔·CLI로 기사 원문과 개정별 열람·댓글·활성 알림의 경계를 검증한다."""

import asyncio
import io
import json
from uuid import uuid7

import pytest

from neurath.application.ports.repositories.article import IArticleRepository
from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.usecases.receive_hook import ReceiveHookCommand, ReceiveHookUseCase
from neurath.domain.aggregates.article import Article
from neurath.domain.aggregates.peer import Peer
from neurath.domain.enums.hook_event import HookEvent
from neurath.domain.enums.task_status import TaskStatus
from neurath.domain.errors import ContextNotFound, InvalidTaskState, RevisionConflict
from neurath.domain.values.article_notice import ArticleNoticeStatus
from neurath.domain.values.article_revision import ArticleRevision
from tests import test_collaboration
from tests.conftest import storage_scope
from tests.support.requests import run
from tests.support.session_requests import register_session
from tests.test_cli import invoke
from tests.test_task_requests import snapshot

collaboration = test_collaboration.collaboration
call = test_collaboration.call


async def publish(database, peer, title="발견", body="선택해서 읽을 본문"):
    return await call(
        database, "publish_article", "PublishArticle", peer.uid, title, body, ["test:observation"]
    )


async def read(database, peer, article, number=1, task=None):
    result = await call(
        database,
        "read_article",
        "ReadArticle",
        peer.uid,
        article.uid,
        number,
        None if task is None else task.uid,
        query=True,
    )
    await call(
        database,
        "record_article_read",
        "RecordArticleRead",
        peer.uid,
        article.uid,
        number,
        None if task is None else task.uid,
        result.task_definition_number,
    )
    return result


async def stored(database, article):
    async with storage_scope(database, write=False) as scope:
        return await scope.get(IArticleRepository).get(article.uid)


async def revise(database, author, article, number=1):
    return await call(
        database,
        "revise_article",
        "ReviseArticle",
        author.uid,
        article.uid,
        number,
        "정정한 발견",
        "이전 결론을 정정한 전체 본문",
        ["test:correction"],
        "잘못된 가정 정정",
    )


async def hook(database, actor, event=HookEvent.PRE_TOOL_USE, **kwargs):
    return await run(
        ReceiveHookUseCase,
        ReceiveHookCommand(
            provider=actor.session.provider,
            host_session_id=actor.session.host_session_id,
            working_directory=actor.session.working_directory,
            event=event,
            turn_id="newsroom-turn",
            **kwargs,
        ),
        database_path=database,
    )


async def test_headlines_are_active_subscriber_snapshots_and_never_body_or_seen(
    database, collaboration
):
    actor, sender, receiver, recipient, _ = collaboration
    await call(database, "subscribe_peer", "SubscribePeer", recipient.uid, ["newsroom"])
    article = await publish(database, sender)
    assert [(n.peer_id, n.revision_number) for n in article.notices] == [(recipient.uid, 1)]
    response = await hook(database, receiver)
    assert response.inbox == (f"Article {article.uid} revision 1: 발견",)
    assert (await stored(database, article)).notices[0].status is ArticleNoticeStatus.SUBMITTED
    assert article.current.body not in str(response.inbox)
    assert (await stored(database, article)).reads == ()
    assert not (await call(database, "list_articles", "ListArticles", recipient.uid, query=True))[
        0
    ].seen
    assert (await hook(database, receiver)).inbox == ()
    first = await read(database, recipient, article)
    assert first.content.body == article.current.body
    assert first.comments == ()
    await read(database, recipient, article)
    assert len((await stored(database, article)).reads) == 1
    assert (await call(database, "list_articles", "ListArticles", recipient.uid, query=True))[
        0
    ].seen
    assert (await hook(database, actor)).inbox == ()


async def test_unsubscribe_discards_pending_and_inactive_publication_never_replays(
    database, collaboration
):
    _, sender, receiver, recipient, _ = collaboration
    await call(database, "subscribe_peer", "SubscribePeer", recipient.uid, ["newsroom", "other"])
    pending = await publish(database, sender)
    await call(database, "subscribe_peer", "SubscribePeer", recipient.uid, ["other"])
    await call(database, "subscribe_peer", "SubscribePeer", recipient.uid, ["newsroom", "other"])
    assert (await hook(database, receiver)).inbox == ()
    assert (await stored(database, pending)).notices[0].status is ArticleNoticeStatus.DISCARDED
    await hook(database, receiver, HookEvent.SESSION_END)
    asleep = await publish(database, sender, title="잠든 동안 발견")
    assert asleep.notices == ()
    assert (
        await hook(database, receiver, HookEvent.SESSION_START, start_source="resume")
    ).inbox == ()
    assert (await stored(database, asleep)).notices == ()
    await call(database, "subscribe_peer", "SubscribePeer", recipient.uid, [])
    unsubscribed = await publish(database, sender)
    assert unsubscribed.notices == ()


async def test_wait_or_inactive_observation_discards_already_queued_news(database, collaboration):
    _, sender, receiver, recipient, _ = collaboration
    await call(database, "subscribe_peer", "SubscribePeer", recipient.uid, ["newsroom"])
    article = await publish(database, sender)
    async with storage_scope(database) as scope:
        peer = await scope.get(IPeerRepository).get(recipient.uid)
        peer.active = False
        await scope.get(IPeerRepository).save(peer)
    assert (
        await hook(database, receiver, HookEvent.SESSION_START, start_source="resume")
    ).inbox == ()
    assert (await stored(database, article)).notices[0].status is ArticleNoticeStatus.DISCARDED
    second = await publish(database, sender)
    await hook(database, receiver, HookEvent.SESSION_END)
    assert (await stored(database, second)).notices[0].status is ArticleNoticeStatus.DISCARDED
    assert (
        await hook(database, receiver, HookEvent.SESSION_START, start_source="resume")
    ).inbox == ()


async def test_reconnect_discards_headlines_even_when_previous_end_was_unobserved(
    database, collaboration
):
    _, sender, receiver, recipient, _ = collaboration
    await call(database, "subscribe_peer", "SubscribePeer", recipient.uid, ["newsroom"])
    pending = await publish(database, sender)
    # 종료 훅을 받지 못해 기존 active가 참이어도 재접속을 catch-up 발행으로 쓰지 않는다.
    resumed = await hook(database, receiver, HookEvent.SESSION_START, start_source="resume")
    assert resumed.inbox == ()
    assert (await stored(database, pending)).notices[0].status is ArticleNoticeStatus.DISCARDED
    current = await publish(database, sender)
    compacted = await hook(database, receiver, HookEvent.SESSION_START, start_source="compact")
    assert compacted.inbox == (f"Article {current.uid} revision 1: 발견",)


async def test_revisions_preserve_author_history_comment_scope_and_actual_task_impacts(
    database, collaboration
):
    _, sender, _, recipient, task = collaboration
    await call(database, "subscribe_peer", "SubscribePeer", recipient.uid, ["newsroom"])
    article = await publish(database, sender)
    await read(database, recipient, article, task=task)
    await read(database, recipient, article, task=task)
    before = await stored(database, article)
    assert len(before.uses) == 1
    await call(
        database,
        "comment_on_article",
        "CommentOnArticle",
        recipient.uid,
        article.uid,
        1,
        "원문에 동의",
    )
    changed = await revise(database, sender, article)
    assert changed.author_id == sender.uid
    assert [item.body for item in changed.revisions] == [
        article.current.body,
        "이전 결론을 정정한 전체 본문",
    ]
    listing = await call(database, "list_articles", "ListArticles", recipient.uid, query=True)
    assert listing[0].revision_number == 2 and not listing[0].seen
    impact = listing[0].affected_tasks[0]
    assert (impact.task_id, impact.definition_number, impact.revision_number) == (task.uid, 1, 1)
    with pytest.raises(InvalidTaskState):
        await call(
            database,
            "comment_on_article",
            "CommentOnArticle",
            recipient.uid,
            article.uid,
            2,
            "읽기 전 댓글",
        )
    old = await read(database, recipient, article)
    assert old.content.body == article.current.body and old.comments[0].body == "원문에 동의"
    newest = await read(database, recipient, article, number=2)
    assert newest.comments == () and len(newest.affected_tasks) == 1
    await call(
        database,
        "comment_on_article",
        "CommentOnArticle",
        recipient.uid,
        article.uid,
        2,
        "정정 확인",
    )
    await read(database, recipient, article, number=2, task=task)
    await read(database, recipient, article, number=1, task=task)
    summary = (await call(database, "list_articles", "ListArticles", recipient.uid, query=True))[0]
    assert summary.seen and summary.affected_tasks == ()
    async with storage_scope(database, write=False) as scope:
        unchanged = await scope.get(ITaskRepository).get(task.uid)
    assert unchanged.status is TaskStatus.PENDING and unchanged.attempts == ()
    saved = await stored(database, article)
    assert [(c.revision_number, c.body) for c in saved.comments] == [
        (1, "원문에 동의"),
        (2, "정정 확인"),
    ]
    assert len(saved.reads) == 2 and len(saved.revisions) == 2


async def test_wrong_author_stale_revision_invalid_input_and_other_project_roll_back(
    database, collaboration, tmp_path
):
    _, sender, _, recipient, task = collaboration
    article = await publish(database, sender)
    before = snapshot(database)
    with pytest.raises(ContextNotFound):
        await revise(database, recipient, article)
    with pytest.raises(RevisionConflict):
        await revise(database, sender, article, number=0)
    with pytest.raises(ValueError):
        await call(
            database,
            "revise_article",
            "ReviseArticle",
            sender.uid,
            article.uid,
            1,
            "",
            "body",
            ["ref"],
            "reason",
        )
    with pytest.raises(ContextNotFound):
        await read(database, recipient, article, number=99)
    with pytest.raises(InvalidTaskState):
        await call(
            database, "comment_on_article", "CommentOnArticle", recipient.uid, article.uid, 1, " "
        )
    assert snapshot(database) == before
    other_dir = tmp_path / "elsewhere"
    other_dir.mkdir()
    other = await register_session(str(other_dir), "codex", "outsider", database_path=database)
    await hook(database, other, HookEvent.SESSION_START)
    outsider = await call(database, "register_peer", "RegisterPeer", other.session.uid)
    before = snapshot(database)
    for module, name, args in [
        ("read_article", "ReadArticle", (outsider.uid, article.uid, 1)),
        ("comment_on_article", "CommentOnArticle", (outsider.uid, article.uid, 1, "cross-scope")),
        (
            "revise_article",
            "ReviseArticle",
            (outsider.uid, article.uid, 1, "title", "body", ["ref"], "reason"),
        ),
        ("record_article_read", "RecordArticleRead", (outsider.uid, article.uid, 1)),
    ]:
        with pytest.raises(ContextNotFound):
            await call(database, module, name, *args, query=module == "read_article")
    assert await call(database, "list_articles", "ListArticles", outsider.uid, query=True) == ()
    with pytest.raises(ContextNotFound):
        await call(
            database,
            "read_article",
            "ReadArticle",
            outsider.uid,
            (await publish(database, outsider)).uid,
            1,
            task.uid,
            query=True,
        )
    assert (await stored(database, article)).reads == ()
    assert snapshot(database) != before  # 외부 프로젝트의 독립 발행만 추가됐다.


async def test_list_search_pagination_invalid_peer_and_selected_query_never_marks_seen(
    database, collaboration
):
    _, sender, _, recipient, _ = collaboration
    first = await publish(database, sender, title="첫째 %_ 발견")
    second = await publish(database, sender, title="둘째 발견")
    page = await call(database, "list_articles", "ListArticles", recipient.uid, limit=1, query=True)
    assert [item.id for item in page] == [first.uid]
    page = await call(
        database, "list_articles", "ListArticles", recipient.uid, after_id=first.uid, query=True
    )
    assert [item.id for item in page] == [second.uid]
    page = await call(
        database, "list_articles", "ListArticles", recipient.uid, text="%_", query=True
    )
    assert [item.id for item in page] == [first.uid]
    assert (
        await call(
            database, "list_articles", "ListArticles", recipient.uid, text="없는 제목", query=True
        )
        == ()
    )
    with pytest.raises(ValueError):
        await call(database, "list_articles", "ListArticles", recipient.uid, limit=0, query=True)
    with pytest.raises(ContextNotFound):
        await call(database, "list_articles", "ListArticles", uuid7(), query=True)
    result = await call(
        database, "read_article", "ReadArticle", recipient.uid, first.uid, 1, query=True
    )
    assert result.content.body == first.current.body
    assert (await stored(database, first)).reads == ()


async def test_stdout_failure_and_stdin_failure_leave_no_false_receipt_or_publication(
    database, collaboration, monkeypatch
):
    _, sender, _, recipient, _ = collaboration
    article = await publish(database, sender)
    before = snapshot(database)
    from neurath.transport.cli import newsroom

    def broken_output(*args, **kwargs):
        raise BrokenPipeError("host output closed")

    monkeypatch.setattr(newsroom, "echo", broken_output)
    response = await invoke(
        database,
        [
            "newsroom",
            "read",
            "--peer-id",
            str(recipient.uid),
            "--article-id",
            str(article.uid),
            "--revision-number",
            "1",
        ],
    )
    assert isinstance(response.exception, BrokenPipeError)
    assert snapshot(database) == before
    monkeypatch.undo()

    class BrokenInput(io.StringIO):
        def read(self, *args):
            raise OSError("host input failed")

    from neurath.infrastructure.database import sqlite_url
    from neurath.transport.cli.newsroom import NewsroomCliController
    from tests.support.application import scanned_application

    async with scanned_application(sqlite_url(database, "rw")) as app:
        monkeypatch.setattr(newsroom.sys, "stdin", BrokenInput())
        with pytest.raises(OSError):
            await app.container.get(NewsroomCliController).publish_article(
                sender.uid, "title", "-", ["ref"]
            )
    assert snapshot(database) == before


async def test_cli_five_commands_print_whole_body_then_record_exact_revision(
    database, collaboration
):
    _, sender, _, recipient, task = collaboration
    pub = await invoke(
        database,
        [
            "newsroom",
            "publish",
            "--peer-id",
            str(sender.uid),
            "--title",
            "제목",
            "--body",
            "-",
            "--reference",
            "fixture:source",
        ],
        "본문 첫째 줄\n둘째 줄",
    )
    assert pub.exit_code == 0, pub.exception
    article_id = json.loads(pub.stdout)["id"]
    common = ["--peer-id", str(recipient.uid), "--article-id", article_id, "--revision-number", "1"]
    read_response = await invoke(
        database, ["newsroom", "read", *common, "--task-id", str(task.uid)]
    )
    assert read_response.exit_code == 0, read_response.exception
    assert json.loads(read_response.stdout)["content"]["body"] == "본문 첫째 줄\n둘째 줄"
    comment = await invoke(database, ["newsroom", "comment", *common, "--body", "-"], "댓글 전체")
    assert comment.exit_code == 0 and json.loads(comment.stdout)["body"] == "댓글 전체"
    rev = await invoke(
        database,
        [
            "newsroom",
            "revise",
            "--peer-id",
            str(sender.uid),
            "--article-id",
            article_id,
            "--expected-revision",
            "1",
            "--title",
            "정정",
            "--body",
            "-",
            "--reference",
            "fixture:new",
            "--reason",
            "사실 정정",
        ],
        "정정 본문",
    )
    assert rev.exit_code == 0 and json.loads(rev.stdout)["revision_number"] == 2
    listing = await invoke(database, ["newsroom", "list", "--peer-id", str(recipient.uid)])
    assert listing.exit_code == 0
    summary = json.loads(listing.stdout)[0]
    assert summary["seen"] is False and "body" not in summary
    assert summary["revision_number"] == 2
    read_again = await invoke(database, ["newsroom", "read", *common])
    assert read_again.exit_code == 0 and len(json.loads(read_again.stdout)["comments"]) == 1


async def test_receipt_task_change_rolls_back_and_read_use_scope_is_not_task_success(
    database, collaboration
):
    _, sender, _, recipient, task = collaboration
    article = await publish(database, sender)
    before = snapshot(database)
    with pytest.raises(RevisionConflict):
        await call(
            database,
            "record_article_read",
            "RecordArticleRead",
            recipient.uid,
            article.uid,
            1,
            task.uid,
            99,
        )
    assert snapshot(database) == before
    result = await call(
        database, "read_article", "ReadArticle", recipient.uid, article.uid, 1, task.uid, query=True
    )
    assert result.task_definition_number == 1
    assert (await stored(database, article)).reads == ()


async def test_current_headline_replaces_old_revision_and_hook_batches_titles(
    database, collaboration
):
    _, sender, receiver, recipient, _ = collaboration
    await call(database, "subscribe_peer", "SubscribePeer", recipient.uid, ["newsroom"])
    first = await publish(database, sender)
    await revise(database, sender, first)
    for number in range(10):
        await publish(database, sender, title=f"발견 {number}")
    # 본문을 반환하지 않는 종료 도구 사건에서는 알림을 소비하지 않는다.
    no_delivery = await hook(database, receiver, HookEvent.POST_TOOL_USE)
    assert no_delivery.inbox == ()
    titles = await hook(database, receiver)
    assert len(titles.inbox) == 10 and "revision 2" in titles.inbox[0]
    assert len((await hook(database, receiver)).inbox) == 1
    assert (await hook(database, receiver)).inbox == ()


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", " "),
        ("body", ""),
        ("reason", ""),
        ("references", []),
        ("references", [" "]),
        ("title", "가" * 201),
        ("body", "가" * 350000),
    ],
)
def test_article_content_rejects_empty_evidence_and_host_size_overflow(field, value):
    args = dict(number=1, title="제목", body="본문", references=["ref"], reason="발행")
    args[field] = value
    with pytest.raises(ValueError):
        ArticleRevision(**args)


def test_domain_scope_history_ownership_and_unread_use_rules():
    author, reader, task = uuid7(), uuid7(), uuid7()
    article = Article.publish(uuid7(), author, "제목", "본문", ["ref"])
    assert article.uid.version == 7
    with pytest.raises(ValueError):
        Article(uid=uuid7(), project_id=uuid7(), author_id=author, revisions=())
    with pytest.raises(InvalidTaskState):
        article.use(reader, 1, task, 1)
    with pytest.raises(InvalidTaskState):
        article.comment(reader, 1, "아직 읽지 않음")
    article.read(reader, 1)
    for body in (" ", "x" * 1048577):
        with pytest.raises(ValueError):
            article.comment(reader, 1, body)
    before = article.revisions
    with pytest.raises(ValueError):
        article.revise(author, 1, "", "body", ["ref"], "reason")
    assert article.revisions is before
    article.use(reader, 1, task, 1)
    article.read(author, 1)
    article.use(author, 1, task, 2)
    assert article.affected_tasks(author) == ()
    peer = Peer(uid=reader, session_id=uuid7(), subscriptions=["newsroom"])
    article.queue_notices([peer])
    article.revise(author, 1, "정정", "새 본문", ["ref:new"], "정정 이유")
    assert article.consume_notices(peer, continuous=True) is False
    assert article.affected_tasks(reader)[0].task_id == task
    new_task = uuid7()
    article.read(reader, 2)
    article.use(reader, 2, new_task, 1)
    article.use(reader, 1, new_task, 1)
    assert [item.task_id for item in article.affected_tasks(reader)] == [task]
    other = Peer(uid=uuid7(), session_id=uuid7(), subscriptions=["newsroom"])
    article.queue_notices([peer, other])
    assert article.consume_notices(peer, continuous=True)
    assert article.consume_notices(peer, continuous=True) is False
    assert article.consume_notices(other, continuous=True)
    assert [item.status for item in article.notices] == [
        ArticleNoticeStatus.DISCARDED,
        ArticleNoticeStatus.SUBMITTED,
        ArticleNoticeStatus.SUBMITTED,
    ]


async def test_newsroom_migration_empty_roundtrip_and_history_preservation(database, collaboration):
    from alembic import command

    from neurath.infrastructure.database import create_database_engine
    from tests.test_task_migrations import migration_config

    engine = create_database_engine(database, write=True, migration=True)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda c: command.downgrade(migration_config(c), "core_0009"))
        async with engine.begin() as connection:
            await connection.run_sync(lambda c: command.upgrade(migration_config(c), "head"))
    finally:
        await engine.dispose()
    _, sender, _, _, _ = collaboration
    article = await publish(database, sender)
    before = snapshot(database)
    engine = create_database_engine(database, write=True, migration=True)
    try:
        with pytest.raises(RuntimeError, match="Article history"):
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda c: command.downgrade(migration_config(c), "core_0009")
                )
    finally:
        await engine.dispose()
    assert snapshot(database) == before
    assert (await stored(database, article)).current.body == article.current.body


def test_article_repository_port_fails_loudly():
    with pytest.raises(NotImplementedError):
        asyncio.run(IArticleRepository.find_by_recipient_id(object(), uuid7()))


async def test_task_detail_exposes_only_real_article_use_and_preserves_requirements(
    database, collaboration
):
    from tests.test_task_requests import create

    actor, sender, _, recipient, task = collaboration
    unrelated = await create(database, actor, title="다른 작업")
    article = await publish(database, sender)
    await read(database, recipient, article, task=task)
    await read(database, recipient, article, task=unrelated)
    await read(database, sender, article, task=task)
    await revise(database, sender, article)
    result = await call(
        database, "get_task", "GetTask", task.project_id, actor.session.uid, task.uid, query=True
    )
    assert len(result.article_impacts) == 2
    assert {item.peer_id for item in result.article_impacts} == {sender.uid, recipient.uid}
    for item in result.article_impacts:
        assert (
            item.article_id,
            item.definition_number,
            item.used_revision,
            item.current_revision,
        ) == (article.uid, 1, 1, 2)
    assert result.task.definition.required_result == task.definition.required_result
    assert result.task.status is task.status
    await read(database, recipient, article, number=2, task=task)
    result = await call(
        database, "get_task", "GetTask", task.project_id, actor.session.uid, task.uid, query=True
    )
    assert [item.peer_id for item in result.article_impacts] == [sender.uid]


async def test_article_save_conflict_and_commit_failure_preserve_complete_history(
    database, collaboration, monkeypatch
):
    from spakky.data.persistency.repository import VersionConflictError
    from spakky.plugins.sqlalchemy.persistency.transaction import AsyncTransaction

    _, sender, _, recipient, _ = collaboration
    article = await publish(database, sender)
    first = await stored(database, article)
    stale = await stored(database, article)
    first.read(recipient.uid, 1)
    async with storage_scope(database) as scope:
        await scope.get(IArticleRepository).save(first)
    stale.read(sender.uid, 1)
    before = snapshot(database)
    with pytest.raises(VersionConflictError):
        async with storage_scope(database) as scope:
            await scope.get(IArticleRepository).save(stale)
    assert snapshot(database) == before

    async def failed_commit(self):
        raise RuntimeError("article commit failed")

    monkeypatch.setattr(AsyncTransaction, "commit", failed_commit)
    with pytest.raises(RuntimeError, match="article commit failed"):
        await revise(database, sender, article)
    assert snapshot(database) == before


async def test_scanned_newsroom_commands_belong_to_explicit_group_without_manual_seen(
    database, tmp_path
):
    from spakky.plugins.typer.stereotypes.cli_controller import CliController
    from typer import Typer
    from typer.main import get_command

    from neurath.infrastructure.database import sqlite_url
    from neurath.transport.cli.newsroom import NewsroomCliController
    from tests.support.application import scanned_application

    names = {"list", "read", "publish", "revise", "comment"}
    async with scanned_application(sqlite_url(database, "rw")) as app:
        root = get_command(app.container.get(Typer))
        assert CliController.get(NewsroomCliController).group_name == "newsroom"
        assert names == root.commands["newsroom"].commands.keys()
        assert names.isdisjoint(root.commands)
        assert {"newsroom-cli-controller", "seen", "record-article-read"}.isdisjoint(root.commands)
        controller = app.container.get(NewsroomCliController)
        from neurath.application.usecases.read_article import ReadArticleUseCase

        assert controller.read is app.container.get(ReadArticleUseCase)
    missing = tmp_path / "missing.sqlite3"
    for name in names:
        assert (await invoke(missing, ["newsroom", name, "--help"])).exit_code == 0
        assert (await invoke(missing, [name, "--help"])).exit_code == 2
    for old_name in (
        "list-articles",
        "read-article",
        "publish-article",
        "revise-article",
        "comment-on-article",
    ):
        assert (await invoke(missing, [old_name, "--help"])).exit_code == 2
    assert not missing.exists()
