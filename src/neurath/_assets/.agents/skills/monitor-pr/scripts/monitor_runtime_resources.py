"""Monitor helper의 runtime-owned identity와 Git-derived local resource 계약입니다."""

import re
import sys
from collections.abc import Mapping
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.agent_harness.session_kernel import SessionLocator
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityBinding,
)
from scripts.agent_harness.worktree_registry import (
    CanonicalWorktreeIdentity,
    WorktreeIdentityResolver,
)


class MonitorRuntimeResources:
    """Caller-selected path 없이 exact session worktree의 local resources를 파생합니다."""

    _LABEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")

    def __init__(
        self,
        *,
        binding: RuntimeIdentityBinding,
        worktree: CanonicalWorktreeIdentity,
    ) -> None:
        """Validated runtime binding과 Git worktree identity를 결합합니다.

        Args:
            binding: Vendor 환경에서 검증된 exact session identity binding입니다.
            worktree: Git control root에서 파생한 canonical worktree identity입니다.
        """
        self._binding = binding
        self._worktree = worktree

    @classmethod
    def resolve(
        cls,
        *,
        cwd: Path,
        environment: Mapping[str, object],
    ) -> MonitorRuntimeResources:
        """Current runtime env와 cwd만으로 exact local resource handle을 만듭니다.

        Args:
            cwd: Active Git worktree 안의 current directory입니다.
            environment: Vendor runtime이 소유한 session identity environment입니다.

        Returns:
            Session, worktree, process-local observation resource가 결속된 handle입니다.

        Raises:
            ValueError: Session locator와 Git worktree control root가 다를 때 발생합니다.
        """
        locator = SessionLocator.from_worktree(cwd)
        worktree = WorktreeIdentityResolver().resolve(cwd)
        if locator.control_root.resolve() != worktree.repository_control_root.resolve():
            raise ValueError("session locator and worktree control root mismatch")
        binding = RuntimeEnvironmentResolver().resolve(environment)
        return cls(binding=binding, worktree=worktree)

    @property
    def session_id(self) -> str:
        """Vendor runtime이 소유한 exact root session ID를 반환합니다.

        Returns:
            Canonical workflow attach에 사용할 root session ID입니다.
        """
        return str(self._binding.session_id)

    @property
    def worktree(self) -> Path:
        """Git이 증명한 canonical worktree top-level을 반환합니다.

        Returns:
            Runtime-local resources의 유일한 filesystem anchor입니다.
        """
        return self._worktree.path

    @property
    def worktree_id(self) -> str:
        """Raw path 대신 receipt에 사용할 opaque worktree resource ID를 반환합니다.

        Returns:
            External receipt가 filesystem path 없이 worktree를 비교할 ID입니다.
        """
        return str(self._worktree.worktree_id)

    @property
    def state_directory(self) -> Path:
        """Monitor process-local artifact directory를 반환합니다.

        Returns:
            Canonical state와 분리된 monitor runtime artifact directory입니다.
        """
        return self.worktree / ".monitor-pr"

    @property
    def observation_path(self) -> Path:
        """Canonical state가 아닌 local observation cache path를 반환합니다.

        Returns:
            Runtime read-back에만 쓰이는 process-local observation 경로입니다.
        """
        return self.state_directory / "monitor-state.json"

    @property
    def stdout_path(self) -> Path:
        """Monitor stdout log resource를 반환합니다.

        Returns:
            Current worktree에 고정된 monitor 표준 출력 로그 경로입니다.
        """
        return self.state_directory / "monitor.log"

    @property
    def stderr_path(self) -> Path:
        """Monitor stderr log resource를 반환합니다.

        Returns:
            Current worktree에 고정된 monitor 표준 오류 로그 경로입니다.
        """
        return self.state_directory / "monitor.err.log"

    @property
    def app_server_socket_path(self) -> Path:
        """Worktree-local managed app-server socket resource를 반환합니다.

        Returns:
            다른 worktree와 resume route가 섞이지 않는 Unix socket 경로입니다.
        """
        return self.state_directory / "app-server.sock"

    @property
    def launch_lock_path(self) -> Path:
        """Exact worktree monitor launch critical-section resource를 반환합니다.

        Returns:
            같은 worktree의 중복 monitor launch를 직렬화할 lock 경로입니다.
        """
        return self.state_directory / "monitor-launch.lock"

    def launch_plist_path(self, label: str) -> Path:
        """Validated launch label의 worktree-local plist resource를 반환합니다.

        Args:
            label: Traversal 없이 plist filename에 포함할 LaunchAgent identity입니다.

        Returns:
            Current worktree artifact directory 아래의 exact plist 경로입니다.

        Raises:
            ValueError: Label이 허용된 identifier 형태를 벗어날 때 발생합니다.
        """
        if self._LABEL_PATTERN.fullmatch(label) is None:
            raise ValueError("monitor launch label is invalid")
        return self.state_directory / f"{label}.plist"

    def observation_resource(self) -> dict[str, str]:
        """Raw path를 노출하지 않는 process-local observation handle을 반환합니다.

        Returns:
            Resource kind와 opaque worktree ID만 포함하는 receipt-safe handle입니다.
        """
        return {
            "kind": "monitor-observation-cache",
            "worktree_id": self.worktree_id,
        }
