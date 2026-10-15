"""Mutable host-session identity and revision rules within a specific project."""

from dataclasses import dataclass
from uuid import uuid4

from neurath.domain.errors import RevisionConflict


@dataclass(eq=False)
class HostSession:
    """A host observation that changes directory while preserving its identity.

    Attributes:
        id: Stable session identifier.
        project_id: Project containing this session.
        provider: Host provider namespace.
        host_session_id: Native identifier, which is not authentication.
        working_directory: Most recently accepted canonical directory.
        revision: Persisted optimistic version used to reject stale requests.
    """

    id: str
    project_id: str
    provider: str
    host_session_id: str
    working_directory: str
    revision: int

    def __eq__(self, other: object) -> bool:
        """Compare the stable session identifier independently of observation state.

        Args:
            other: Object whose session identity is compared.

        Returns:
            bool: Whether both objects represent the same session.
        """
        if not isinstance(other, HostSession):
            return NotImplemented
        return self.id == other.id

    @classmethod
    def create(
        cls, project_id: str, provider: str, host_session_id: str, working_directory: str
    ) -> "HostSession":
        """Register the first observation with a valid native identity.

        Args:
            project_id: Project containing the host session.
            provider: Nonempty host provider namespace.
            host_session_id: Nonempty identifier supplied by that provider.
            working_directory: Canonical observed directory.

        Returns:
            HostSession: A new session at revision one.

        Raises:
            ValueError: The provider or native identifier is blank.
        """
        if not provider.strip() or not host_session_id.strip():
            raise ValueError("provider and host_session_id must be non-empty")
        return cls(str(uuid4()), project_id, provider, host_session_id, working_directory, 1)

    def move(self, working_directory: str, expected_revision: int) -> None:
        """Accept a new directory only when the caller observed the current revision.

        Args:
            working_directory: Canonical directory in this session's project.
            expected_revision: Revision observed by the caller before requesting a move.

        Raises:
            RevisionConflict: The caller's observation is stale.
        """
        if expected_revision != self.revision:
            raise RevisionConflict("Session changed; read current context before updating")
        self.working_directory = working_directory
