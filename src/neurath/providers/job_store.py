"""Durable provider-job storage shared by supervision and batch scheduling."""

from neurath.agents.store import MessageStore


def open_store(root):
    store = MessageStore(root)
    with store.connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS provider_jobs (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, request TEXT NOT NULL,
            status TEXT NOT NULL, result TEXT, control TEXT NOT NULL,
            cancel_requested INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL)""")
    return store


def owned_job(db, owner, run_id):
    row = db.execute("SELECT * FROM provider_jobs WHERE id=?", (run_id,)).fetchone()
    if row is None or row["owner"] != owner:
        raise ValueError("provider job requires its owner")
    return row
