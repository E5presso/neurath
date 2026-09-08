"""Closed schemas for existing canonical communication operations.

No new state transitions or alternate identity route are introduced here.
"""
def definitions():
    from neurath.runtime.task_schema import count, text_field
    t=text_field
    revision={"type":"integer","minimum":1,"maximum":2**53-1}
    entries = {
        "collaboration_register": ("agent","register",
            "Describe this native session's own name and work scope. Does not change its identity, permissions or ownership.",
            {"name":t(256),"summary":t(4096,default="")},False),
        "collaboration_conversation": ("agent","conversation",
            "Read a conversation as its authenticated participant; read-only diagnostics.",
            {"conversation":t(512)},True),
        "collaboration_close": ("agent","close",
            "Close a participating conversation only when its pending-message contract allows it. Pending is not closed.",
            {"conversation":t(512)},False),
        "collaboration_subscribe": ("agent","subscribe",
            "Subscribe this caller to a discovered peer's authorized updates. Does not wake or grant authority to peers.",
            {"to":t(512)},False),
        "collaboration_unsubscribe": ("agent","unsubscribe",
            "Remove this caller's own peer subscription.",
            {"to":t(512)},False),
        "collaboration_publish": ("agent","publish",
            "Publish an authorized update to existing subscribers. Reuse the same key and content on retry.",
            {"message":t(),"key":t(512)},False),
        "newsroom_revise": ("newsroom","revise",
            "Revise this author's article with its observed revision and stable key. A stale revision must not overwrite a newer article.",
            {"article_id":t(512),"revision":revision,"title":t(30),"body":t(),"key":t(512)},False),
        "newsroom_comment": ("newsroom","comment",
            "Add a relevant comment to an observed article revision with native author identity and a stable key.",
            {"article_id":t(512),"revision":revision,"body":t(),"key":t(512)},False),
        "newsroom_peers": ("newsroom","peers",
            "Read active Newsroom peers; do not wake inactive sessions.",
            {"limit":count(20)},True),
        "newsroom_seen": ("newsroom","seen",
            "Mark this recipient's headline notification as seen. This does not attest reading the article body.",
            {"event_id":t(512)},False),
    }
    return entries
