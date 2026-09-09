"""One package facade for the installed runtime database implementation.

Import the bundled module under its executable scripts name. Importing it again
through neurath._assets would create a second ContextVar transaction registry
and break nested atomicity.
"""
from neurath.runtime.engine import activate

activate()

from scripts.agent_harness.runtime_database import (  # noqa: E402,F401
    CorruptRecord,
    LegacyStateChanged,
    LegacyTableCollision,
    RecordConflict,
    RuntimeConnection,
    RuntimeDatabase,
    RuntimeTransaction,
    StoredRecord,
)

