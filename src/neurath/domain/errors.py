"""Failures callers can handle without knowing persistence implementation details."""


class NeurathError(Exception):
    """Base error for project and session requests."""


class ContextNotFound(NeurathError):
    """The requested project or its scoped session does not exist."""


class RevisionConflict(NeurathError):
    """A session changed after the caller observed its revision."""


class ProjectIdentityConflict(NeurathError):
    """Persisted folder and Git aliases refer to incompatible projects."""


class StorageNotReady(NeurathError):
    """The database needs explicit initialization or a compatible migration."""
