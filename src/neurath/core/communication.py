"""Project peer messages carry attributed reports, never user instructions."""

from uuid import uuid4

from neurath.core.domain import Source, require

COMMANDS = {
    "collaboration_send": ({"recipient", "body"}, {"task_id"}, False),
    "collaboration_inbox": (set(), {"include_read", "limit"}, True),
    "collaboration_ack": ({"message_ids"}, set(), False),
    "collaboration_reply": ({"message_id", "body"}, set(), False),
    "newsroom_publish": ({"title", "body"}, set(), False),
    "newsroom_headlines": (set(), {"limit"}, True),
    "newsroom_read": ({"article_id"}, set(), True),
}


def _message(tx, context, recipient, body, task_id=None):
    require(isinstance(body, str) and bool(body.strip()), "message-body")
    require(tx.record("actor", recipient) is not None, "recipient-unobserved")
    if task_id is not None:
        tx.task(task_id)
    identifier = "message-" + uuid4().hex
    source = Source.create("source-" + uuid4().hex, "report", body, "message:" + identifier)
    tx.put_source(source)
    value = {
        "id": identifier,
        "sender": context.actor_id,
        "recipient": recipient,
        "body": body,
        "source_id": source.id,
        "task_id": task_id,
        "read": False,
        "authority": "peer-report",
    }
    tx.put_record("message", identifier, value)
    return {
        "message": value,
        "delivery": "mailbox-only",
        "next_action": "The mailbox does not wake an idle peer. Use the observed native handle when an authorized wake is needed.",
    }


def call(tx, context, name, values):
    if name == "collaboration_send":
        return _message(tx, context, values["recipient"], values["body"], values.get("task_id"))
    if name == "collaboration_inbox":
        limit = values.get("limit", 20)
        require(type(limit) is int and 1 <= limit <= 100, "invalid-limit")
        require(type(values.get("include_read", False)) is bool, "invalid-input")
        messages = [
            r["value"]
            for r in tx.records("message", chronological=True)
            if r["value"]["recipient"] == context.actor_id
            and (values.get("include_read", False) or not r["value"]["read"])
        ]
        return {"messages": messages[:limit], "authority": "peer-report"}
    if name in {"collaboration_ack", "collaboration_reply"}:
        identifiers = values.get("message_ids", [values.get("message_id")])
        require(
            isinstance(identifiers, list) and all(isinstance(i, str) for i in identifiers),
            "message-ids",
        )
        messages = []
        for identifier in identifiers:
            record = tx.record("message", identifier)
            require(
                record is not None and record["value"]["recipient"] == context.actor_id,
                "message-recipient",
            )
            messages.append(record["value"])
            if not record["value"]["read"]:
                tx.put_record(
                    "message", identifier, {**record["value"], "read": True}, record["revision"]
                )
        if name == "collaboration_reply":
            return _message(
                tx, context, messages[0]["sender"], values["body"], messages[0]["task_id"]
            )
        return {"acknowledged": identifiers}
    if name == "newsroom_publish":
        require(
            all(isinstance(values[k], str) and bool(values[k].strip()) for k in ("title", "body")),
            "article-content",
        )
        identifier = "article-" + uuid4().hex
        source = Source.create(
            "source-" + uuid4().hex, "report", values["body"], "article:" + identifier
        )
        tx.put_source(source)
        article = {
            "id": identifier,
            "sender": context.actor_id,
            "title": values["title"],
            "body": values["body"],
            "source_id": source.id,
            "authority": "peer-report",
        }
        tx.put_record("article", identifier, article)
        return {"article": article}
    if name == "newsroom_read":
        record = tx.record("article", values["article_id"])
        require(record is not None, "article-missing")
        return {"article": record["value"]}
    limit = values.get("limit", 20)
    require(type(limit) is int and 1 <= limit <= 100, "invalid-limit")
    return {
        "articles": [
            {k: r["value"][k] for k in ("id", "sender", "title", "authority")}
            for r in tx.records("article", chronological=True)
        ][-limit:]
    }
