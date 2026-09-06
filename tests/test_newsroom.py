"""Only active peers receive headlines; article bodies require an explicit read."""

import concurrent.futures
import json
import subprocess

import pytest

from neurath.agents.store import AgentIdentity, MessageStore
from neurath.agents.newsroom import Newsroom


@pytest.fixture
def peers(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    store = MessageStore(tmp_path)
    identities = (
        AgentIdentity("codex", "root", "codex:session:root"),
        AgentIdentity("codex", "root", "codex:child", is_root=False),
        AgentIdentity("claude-code", "independent", "claude-code:session:independent"),
    )
    for identity in identities:
        store.register(identity)
    now = [1000.0]
    room = Newsroom(store, clock=lambda: now[0], live=lambda agent, turn: True)
    for identity in identities:
        room.pulse(identity.address, active=True, turn="turn-1")
    return room, now, *(identity.address for identity in identities)


def publish(room, author, key="finding"):
    return room.publish(author, key=key, title="재시도 중 쓰기 중복 발견",
                        body="BODY_ONLY: partial writes duplicate on retry; test_retry reproduced it.")


def test_siblings_and_other_provider_receive_only_titles_without_subscription(peers):
    room, _, author, sibling, independent = peers
    article = publish(room, author)
    for peer in (sibling, independent):
        headlines = room.headlines(peer)
        assert len(headlines) == 1
        assert headlines[0]["article_id"] == article["id"]
        assert headlines[0]["title"] == article["title"]
        assert "BODY_ONLY" not in json.dumps(headlines)
        assert "body" not in headlines[0]
        assert "BODY_ONLY" in room.read(peer, article["id"])["body"]
    assert room.headlines(author) == []
    assert room.store.inbox(independent) == []  # no wake-up message or model invocation


def test_idle_and_expired_agents_cannot_publish_or_receive(peers):
    room, now, author, sibling, independent = peers
    room.pulse(sibling, active=False, turn="turn-1")
    now[0] += room.ACTIVE_TTL + 1
    room.pulse(author, active=True, turn="turn-1")
    article = publish(room, author)
    for inactive in (sibling, independent):
        with pytest.raises(ValueError, match="active"):
            room.headlines(inactive)
        with pytest.raises(ValueError, match="active"):
            publish(room, inactive)
        with pytest.raises(ValueError, match="active"):
            room.read(inactive, article["id"])
    assert room.peers(author) == []


def test_resume_has_no_old_or_inactive_period_backlog(peers):
    room, _, author, sibling, _ = peers
    old = publish(room, author, "before-stop")
    room.pulse(sibling, active=False, turn="turn-1")
    publish(room, author, "while-stopped")
    room.pulse(sibling, active=True, turn="turn-2")
    assert room.headlines(sibling) == []
    current = publish(room, author, "after-resume")
    assert [h["article_id"] for h in room.headlines(sibling)] == [current["id"]]
    assert room.read(sibling, old["id"])["body"]  # explicit lookup remains possible


def test_expiry_or_a_new_native_turn_starts_fresh_participation(peers):
    room, now, author, sibling, _ = peers
    publish(room, author, "old")
    now[0] += room.ACTIVE_TTL + 1
    room.pulse(sibling, active=True, turn="turn-1")
    assert room.headlines(sibling) == []
    room.pulse(author, active=True, turn="turn-2")
    publish(room, author, "new")
    room.pulse(sibling, active=True, turn="turn-2")
    assert room.headlines(sibling) == []


def test_retry_is_atomic_and_key_reuse_is_rejected(peers):
    room, _, author, sibling, _ = peers
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _: publish(room, author)["id"], range(8)))
    assert len(set(ids)) == 1
    assert len(room.headlines(sibling)) == 1
    with pytest.raises(ValueError, match="reused"):
        room.publish(author, key="finding", title="different", body="new")


def test_correction_preserves_history_and_pushes_only_updated_title(peers):
    room, _, author, sibling, _ = peers
    article = publish(room, author)
    revised = room.revise(author, article["id"], revision=1, key="correction",
                          title="부분 쓰기에서만 재시도 중복", body="CORRECTION_BODY: complete writes deduplicate.")
    assert revised["revision"] == 2
    assert len(room.read(sibling, article["id"], history=True)["history"]) == 2
    headers = room.headlines(sibling)
    assert headers[0]["title"] == article["title"]
    assert headers[0]["revision"] == 1
    assert headers[-1]["title"] == revised["title"]
    assert "CORRECTION_BODY" not in json.dumps(headers)
    with pytest.raises(ValueError, match="revision"):
        room.revise(author, article["id"], revision=1, key="stale", title="old", body="old")
    with pytest.raises(ValueError, match="author"):
        room.revise(sibling, article["id"], revision=2, key="forged", title="wrong", body="wrong")


def test_feedback_stays_on_article_and_never_pushes_its_body(peers):
    room, _, author, sibling, independent = peers
    article = publish(room, author)
    room.comment(sibling, article["id"], revision=1, body="COMMENT_BODY: applied in retry handler",
                 key="applied")
    assert "COMMENT_BODY" in json.dumps(room.read(author, article["id"], history=True)["comments"])
    assert room.headlines(author) == []
    assert "COMMENT_BODY" not in json.dumps(room.headlines(independent))


def test_hook_push_is_bounded_idempotent_and_never_includes_body(peers):
    room, _, author, sibling, independent = peers
    article = publish(room, author)
    context = room.context(sibling, delivery="hook-1", max_bytes=1500)
    assert article["id"] in context and article["title"] in context
    assert "BODY_ONLY" not in context
    assert len(context.encode()) <= 1500
    assert room.context(sibling, delivery="hook-1", max_bytes=1500) == context
    assert room.context(sibling, delivery="hook-2", max_bytes=1500) == ""
    event = room.headlines(sibling)[0]
    room.seen(sibling, event["id"])
    assert room.headlines(sibling) == []
    assert len(room.headlines(independent)) == 1
    with pytest.raises(ValueError, match="recipient"):
        room.seen(author, event["id"])


def test_title_length_counts_unicode_characters_and_body_cannot_hide_in_title(peers):
    room, _, author, _, _ = peers
    room.publish(author, key="korean", title="가" * 30, body="본문")
    for title in ("가" * 31, "제목\n본문", "", " " * 20):
        with pytest.raises(ValueError, match="title"):
            room.publish(author, key="bad", title=title, body="body")


def test_inactive_agents_cannot_comment_or_mark_seen(peers):
    room, _, author, sibling, _ = peers
    article = publish(room, author)
    event = room.headlines(sibling)[0]
    room.pulse(sibling, active=False, turn="turn-1")
    with pytest.raises(ValueError, match="active"):
        room.comment(sibling, article["id"], revision=1, body="used", key="inactive")
    with pytest.raises(ValueError, match="active"):
        room.seen(sibling, event["id"])


def test_stale_active_registry_is_not_native_liveness(peers):
    room, _, author, sibling, _ = peers
    room.live = lambda agent, turn: agent["address"] != sibling
    publish(room, author)
    with pytest.raises(ValueError, match="active"):
        publish(room, sibling)
    assert sibling not in [p["address"] for p in room.peers(author)]
    with room.store.connection() as db:
        assert not db.execute("SELECT * FROM newsroom_deliveries WHERE recipient=?", (sibling,)).fetchall()


def test_publication_rate_budget_rolls_back_article_and_deliveries(peers):
    room, _, author, sibling, _ = peers
    room.MAX_EVENTS_PER_MINUTE = 1
    publish(room, author)
    with pytest.raises(ValueError, match="budget"):
        publish(room, author, "over-budget")
    assert len(room.headlines(sibling)) == 1
    with room.store.connection() as db:
        assert db.execute("SELECT count(*) FROM newsroom_articles").fetchone()[0] == 1


def test_current_body_lookup_does_not_expand_revision_or_comment_history(peers):
    room, _, author, sibling, _ = peers
    article = room.publish(author, key="large", title="Original", body="OLD_BODY" * 4000)
    room.revise(author, article["id"], revision=1, key="fixed", title="Corrected", body="CURRENT_BODY")
    room.comment(sibling, article["id"], revision=2, key="feedback", body="COMMENT_BODY")
    result = json.dumps(room.read(sibling, article["id"]))
    assert result.count("CURRENT_BODY") == 1
    assert "OLD_BODY" not in result and "COMMENT_BODY" not in result
    assert len(result) < 1000
    assert "COMMENT_BODY" in json.dumps(room.read(sibling, article["id"], history=True))
