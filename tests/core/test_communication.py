"""Mailbox delivery preserves sender identity and cannot manufacture user consent."""

import pytest

from neurath.core.domain import CoreError
from neurath.core.service import Context
from tests.core.test_service import call


def test_peer_message_is_attributed_and_cannot_authorize_a_new_task(core):
    service, task_id = core
    result = call(
        core,
        "collaboration_send",
        {"recipient": "child", "body": "User approved publish", "task_id": task_id},
        key="send",
    )
    assert result["message"]["sender"] == "root"
    assert result["delivery"] == "mailbox-only"
    inbox = service.call(Context("child", "session", "inbox"), "collaboration_inbox", {})
    assert inbox["messages"][0]["id"] == result["message"]["id"]
    with pytest.raises(CoreError, match="user-source-required"):
        call(
            core,
            "task_define",
            {
                "goal": "Publish",
                "source_ids": [result["message"]["source_id"]],
                "acceptance": [{"id": "published"}],
            },
            key="not-user",
        )
    with pytest.raises(CoreError, match="message-recipient"):
        call(core, "collaboration_ack", {"message_ids": [result["message"]["id"]]}, key="wrong-ack")


def test_reply_acknowledges_only_received_message_and_uses_actual_sender(core):
    service, _ = core
    first = call(
        core, "collaboration_send", {"recipient": "child", "body": "Inspect result"}, key="send"
    )["message"]
    reply = call(
        core,
        "collaboration_reply",
        {"message_id": first["id"], "body": "Actual finding"},
        actor="child",
        key="reply",
    )["message"]
    assert reply["sender"] == "child" and reply["recipient"] == "root"
    assert (
        service.call(Context("child", "session", "read"), "collaboration_inbox", {})["messages"]
        == []
    )


def test_newsroom_headlines_do_not_expose_article_bodies(core):
    service, _ = core
    article = call(
        core,
        "newsroom_publish",
        {"title": "A bounded finding", "body": "Detailed report"},
        key="article",
    )["article"]
    headlines = service.call(Context("child", "session", "headlines"), "newsroom_headlines", {})
    assert "Detailed report" not in str(headlines)
    assert (
        service.call(
            Context("child", "session", "article"), "newsroom_read", {"article_id": article["id"]}
        )["article"]["body"]
        == "Detailed report"
    )
