"""Read-only imports of explicitly retained outer-service tables from v1 storage."""

import sqlite3
from hashlib import sha256

from neurath.core.codec import encode
from neurath.core.domain import require


def import_tables(store, key, tables, *, validate=None):
    source = store.root / ".neurath/local/runtime.sqlite3"
    with store.transaction() as tx:
        if tx.record("migration", key) is not None:
            return
    require(not source.is_symlink(), "unsafe-archive-source")
    rows = {}
    if source.is_file():
        old = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        try:
            old.execute("BEGIN")
            require(
                old.execute("PRAGMA quick_check").fetchone()[0] == "ok", "archive-source-corrupt"
            )
            for table, columns in tables.items():
                require(
                    table.isidentifier() and all(column.isidentifier() for column in columns),
                    "archive-table-name",
                )
                if (
                    old.execute(
                        "SELECT 1 FROM sqlite_schema WHERE type=? AND name=?", ("table", table)
                    ).fetchone()
                    is None
                ):
                    continue
                actual = tuple(row[1] for row in old.execute("PRAGMA table_info(" + table + ")"))
                require(actual == columns, "archive-source-schema", table=table)
                rows[table] = list(
                    old.execute(
                        "SELECT "
                        + ",".join(columns)
                        + " FROM "
                        + table
                        + " ORDER BY "
                        + ",".join(columns)
                    )
                )
        finally:
            old.close()
    if validate is not None:
        validate(rows)
    with store.transaction() as tx:
        if tx.record("migration", key) is not None:
            return
        for table, values in rows.items():
            columns = tables[table]
            placeholders = ",".join("?" for _ in columns)
            tx.db.executemany(
                "INSERT INTO "
                + table
                + " ("
                + ",".join(columns)
                + ") VALUES ("
                + placeholders
                + ")",
                values,
            )
        tx.put_record(
            "migration",
            key,
            {
                "source": str(source),
                "source_present": source.is_file(),
                "digest": sha256(encode(rows).encode()).hexdigest(),
                "rows": {table: len(values) for table, values in rows.items()},
            },
        )
