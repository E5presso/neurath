"""Copy retained installer metadata without executing or mutating the former core."""

import json
from hashlib import sha256

from neurath.core.archive import import_tables
from neurath.core.codec import encode
from neurath.core.domain import require

TABLES = {
    "installation_states": ("root", "digest", "payload", "updated"),
    "installation_journals": ("root", "plan_id", "payload"),
    "installation_receipts": ("root", "id", "digest", "payload"),
    "installation_legacy_files": ("root", "path", "digest", "status"),
    "installation_json_cutovers": ("root", "version"),
}


def import_installation_metadata(store):
    def validate(rows):
        for table in ("installation_states", "installation_receipts"):
            columns = TABLES[table]
            for row in rows.get(table, ()):
                value = dict(zip(columns, row, strict=True))
                canonical = encode(json.loads(value["payload"]))
                require(
                    sha256(canonical.encode()).hexdigest() == value["digest"],
                    "installation-source-corrupt",
                )

    import_tables(store, "installation-metadata", TABLES, validate=validate)
