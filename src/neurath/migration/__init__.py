"""Read-only legacy data capture and explicit, non-authoritative task recovery."""
from .legacy import LegacyImportError, capture_sqlite, import_legacy, prepare_import, verify_archive

__all__ = ["LegacyImportError", "capture_sqlite", "import_legacy", "prepare_import", "verify_archive"]
