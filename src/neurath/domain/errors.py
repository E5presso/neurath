"""Failures that leave the ledger transaction unchanged."""


class DomainError(Exception):
    code = "invalid-transition"


class ValidationError(DomainError):
    code = "invalid-input"


class ConflictError(DomainError):
    code = "conflict"


class AuthorizationError(DomainError):
    code = "forbidden"


class NotFoundError(DomainError):
    code = "not-found"
