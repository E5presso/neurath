"""Immutable retirement targets and identity-fenced external file effects."""

from __future__ import annotations

import glob
import hashlib
import os
import stat
from collections.abc import Mapping
from pathlib import Path


from monitor_runtime_lock import monitor_runtime_claim_path

from scripts.agent_harness.worktree_registry import (
    CanonicalWorktreeIdentity,
)


class MonitorRuntimeHandoffError(RuntimeError):
    """Monitor handoff가 identity, lifecycle 또는 retirement 계약을 어길 때의 오류입니다."""


class MonitorRuntimeIdentityMismatch(MonitorRuntimeHandoffError):
    """Persisted monitor route가 current session workflow와 다를 때 발생합니다."""


class MonitorRuntimeRetirementFailed(MonitorRuntimeHandoffError):
    """Obsolete runtime이 실제로 종료됐음을 확인하지 못했을 때 발생합니다."""


class LegacyMonitorStateInvalid(MonitorRuntimeHandoffError):
    """Compatibility input의 JSON root가 object가 아닐 때 발생합니다."""


class MonitorExternalFileConflict(MonitorRuntimeHandoffError):
    """Prepared file의 identity 또는 content가 effect 전에 달라졌을 때 발생합니다."""


class MonitorRuntimeHandoffResult:
    """CLI가 stderr 예외 대신 전달할 machine-readable 실행 결과입니다."""

    __slots__ = ("exit_code", "stderr", "stdout")

    def __init__(self, *, exit_code: int, stdout: str, stderr: str) -> None:
        """Process exit code와 출력 channel을 하나의 결과로 고정합니다.

        Args:
            exit_code: 성공은 0, fail-closed handoff는 2인 process code입니다.
            stdout: 성공 receipt의 canonical JSON입니다.
            stderr: 실패 이유이며 성공이면 빈 문자열입니다.
        """
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    exit_code: int
    """Application process가 반환할 exit code입니다."""

    stdout: str
    """성공한 handoff receipt의 JSON output입니다."""

    stderr: str
    """실패한 identity 또는 retirement invariant 설명입니다."""


class MonitorRuntimePaths:
    """Git이 증명한 worktree에 local monitor runtime path를 고정합니다."""

    __slots__ = ("state_dir", "state_path", "worktree", "worktree_id")

    def __init__(self, identity: CanonicalWorktreeIdentity) -> None:
        """Canonical worktree 밖의 caller path override를 제거합니다.

        Args:
            identity: Git common-dir와 top-level로 검증된 worktree identity입니다.
        """
        self.worktree = identity.path
        self.worktree_id = str(identity.worktree_id)
        self.state_dir = identity.path / ".monitor-pr"
        self.state_path = self.state_dir / "monitor-state.json"

    worktree: Path
    """Monitor process가 실행되는 canonical Git worktree top-level입니다."""

    state_dir: Path
    """해당 worktree의 local runtime artifact directory입니다."""

    state_path: Path
    """현재 monitor observation만 담는 canonical local runtime state입니다."""

    worktree_id: str
    """Receipt identity에 사용할 opaque canonical worktree resource ID입니다."""

    def observation_resource(self) -> dict[str, str]:
        """Raw path를 노출하지 않는 process-local observation handle을 반환합니다.

        Returns:
            Cache kind와 opaque worktree ID로만 구성된 local resource handle입니다.
        """
        return {
            "kind": "monitor-observation-cache",
            "worktree_id": self.worktree_id,
        }


class DetachedRuntimeTarget:
    """Prepared handoff가 종료할 exact process identity를 고정합니다."""

    __slots__ = ("command", "pid")

    def __init__(self, *, pid: int, command: str) -> None:
        """PID와 prepare 시 read-back한 exact command를 결합합니다.

        Args:
            pid: 종료 후보 process identity입니다.
            command: Exact session/workflow route 검증을 마친 process command입니다.

        Raises:
            MonitorRuntimeIdentityMismatch: Target identity가 유효하지 않으면 발생합니다.
        """
        if pid <= 0 or not command:
            raise MonitorRuntimeIdentityMismatch("detached runtime target is invalid")
        self.pid = pid
        self.command = command

    pid: int
    """Prepared intent가 승인한 exact process ID입니다."""

    command: str
    """PID reuse를 fence할 prepare-time command read-back입니다."""

    def to_payload(self) -> dict[str, object]:
        """Durable prepared receipt에 넣을 JSON payload를 반환합니다.

        Returns:
            Exact PID와 command를 담은 JSON object입니다.
        """
        return {"pid": self.pid, "command": self.command}

    @classmethod
    def from_payload(cls, value: object) -> DetachedRuntimeTarget:
        """Persisted target payload를 validated value object로 복원합니다.

        Args:
            value: Prepared receipt에서 읽은 detached process target입니다.

        Returns:
            Exact PID와 command를 보존한 immutable target입니다.

        Raises:
            MonitorRuntimeIdentityMismatch: Persisted target shape가 invalid하면 발생합니다.
        """
        if not isinstance(value, Mapping):
            raise MonitorRuntimeIdentityMismatch("detached runtime plan must be an object")
        pid = value.get("pid")
        command = value.get("command")
        if not isinstance(pid, int) or isinstance(pid, bool) or not isinstance(command, str):
            raise MonitorRuntimeIdentityMismatch("detached runtime plan identity is invalid")
        return cls(pid=pid, command=command)


class PreparedFileTarget:
    """Prepared CAS가 승인한 regular file 원본의 immutable optimistic key입니다."""

    __slots__ = (
        "device",
        "inode",
        "mtime_ns",
        "path",
        "role",
        "sha256",
        "size",
    )

    def __init__(
        self,
        *,
        role: str,
        path: Path,
        sha256: str,
        size: int,
        device: int,
        inode: int,
        mtime_ns: int,
    ) -> None:
        """Regular-file metadata와 content digest를 하나의 exact key로 고정합니다.

        Args:
            role: Plan 안에서 target의 허용 path shape를 정하는 stable role입니다.
            path: Symlink를 따라가지 않은 canonical lexical target path입니다.
            sha256: Prepare 때 읽은 complete file bytes의 SHA-256 digest입니다.
            size: Prepare 때 읽은 exact byte size입니다.
            device: Prepare 때 opened file의 device identity입니다.
            inode: Prepare 때 opened file의 inode identity입니다.
            mtime_ns: Prepare 때 opened file의 nanosecond mtime입니다.

        Raises:
            MonitorRuntimeIdentityMismatch: Persist할 fingerprint가 invalid하면 발생합니다.
        """
        if (
            role not in {"launch-agent-plist", "legacy-state"}
            or len(sha256) != 64
            or any(character not in "0123456789abcdef" for character in sha256)
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in (size, device, inode, mtime_ns)
            )
        ):
            raise MonitorRuntimeIdentityMismatch("prepared file fingerprint is invalid")
        self.role = role
        self.path = self._lexical_path(path)
        self.sha256 = sha256
        self.size = size
        self.device = device
        self.inode = inode
        self.mtime_ns = mtime_ns

    role: str
    """Target path validation과 receipt 해석에 사용하는 stable file role입니다."""

    path: Path
    """Symlink replacement 자체를 관찰할 canonical lexical path입니다."""

    sha256: str
    """Prepare 때 stable read한 complete content의 SHA-256 digest입니다."""

    size: int
    """Prepare 때 stable read한 byte size입니다."""

    device: int
    """동일 content로 교체된 새 object도 구분하는 device identity입니다."""

    inode: int
    """동일 content로 교체된 새 object도 구분하는 inode identity입니다."""

    mtime_ns: int
    """In-place rewrite를 digest read 전에 빠르게 구분하는 nanosecond mtime입니다."""

    @classmethod
    def capture(cls, *, role: str, path: Path) -> PreparedFileTarget:
        """Existing regular file을 stable read해 durable optimistic key로 만듭니다.

        Args:
            role: Target의 stable prepared-plan role입니다.
            path: Prepare inventory가 발견한 exact file path입니다.

        Returns:
            Regular-file metadata와 content digest를 가진 immutable target입니다.

        Raises:
            MonitorExternalFileConflict: Missing, symlink, non-regular 또는 read 중 변경이면
                발생합니다.
        """
        canonical = cls._lexical_path(path)
        content, metadata = cls._stable_read(canonical)
        return cls(
            role=role,
            path=canonical,
            sha256=hashlib.sha256(content).hexdigest(),
            size=metadata.st_size,
            device=metadata.st_dev,
            inode=metadata.st_ino,
            mtime_ns=metadata.st_mtime_ns,
        )

    def to_payload(self) -> dict[str, object]:
        """Prepared receipt에 넣을 complete regular-file fingerprint를 반환합니다.

        Returns:
            Path, role, regular-file marker, digest와 object metadata를 담은 JSON입니다.
        """
        return {
            "role": self.role,
            "path": str(self.path),
            "regular_file": True,
            "sha256": self.sha256,
            "size": self.size,
            "device": self.device,
            "inode": self.inode,
            "mtime_ns": self.mtime_ns,
        }

    @classmethod
    def from_payload(
        cls,
        value: object,
        *,
        state_dir: Path,
        expected_role: str,
        current_state_path: Path,
    ) -> PreparedFileTarget:
        """Persisted fingerprint와 role-specific canonical path를 검증합니다.

        Args:
            value: Prepared receipt의 file target JSON입니다.
            state_dir: 모든 target이 속해야 하는 canonical runtime directory입니다.
            expected_role: Parent plan entry가 요구하는 exact target role입니다.
            current_state_path: Legacy target에서 제외할 canonical current state입니다.

        Returns:
            Durable optimistic key를 보존한 immutable file target입니다.

        Raises:
            MonitorRuntimeIdentityMismatch: Shape, role 또는 path가 invalid하면 발생합니다.
        """
        if not isinstance(value, Mapping):
            raise MonitorRuntimeIdentityMismatch("prepared file target must be an object")
        path = value.get("path")
        role = value.get("role")
        sha256 = value.get("sha256")
        size = value.get("size")
        device = value.get("device")
        inode = value.get("inode")
        mtime_ns = value.get("mtime_ns")
        if (
            role != expected_role
            or value.get("regular_file") is not True
            or not isinstance(path, str)
            or not isinstance(sha256, str)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or not isinstance(device, int)
            or isinstance(device, bool)
            or not isinstance(inode, int)
            or isinstance(inode, bool)
            or not isinstance(mtime_ns, int)
            or isinstance(mtime_ns, bool)
        ):
            raise MonitorRuntimeIdentityMismatch("prepared file target identity is invalid")
        candidate = cls._lexical_path(Path(path))
        canonical_directory = state_dir.resolve()
        if candidate.parent != canonical_directory:
            raise MonitorRuntimeIdentityMismatch("prepared file target path is not canonical")
        if expected_role == "launch-agent-plist" and candidate.suffix != ".plist":
            raise MonitorRuntimeIdentityMismatch("launch agent plan path is not canonical")
        if expected_role == "legacy-state" and (
            not candidate.name.endswith("-state.json")
            or candidate == cls._lexical_path(current_state_path)
        ):
            raise MonitorRuntimeIdentityMismatch("monitor state plan path is not canonical")
        return cls(
            role=expected_role,
            path=candidate,
            sha256=sha256,
            size=size,
            device=device,
            inode=inode,
            mtime_ns=mtime_ns,
        )

    def read_if_current(self) -> bytes | None:
        """Current path가 missing이거나 prepared original과 exact match인지 판정합니다.

        Returns:
            Missing이면 None, exact current file이면 stable-read bytes입니다.

        Raises:
            MonitorExternalFileConflict: Symlink, non-regular 또는 fingerprint mismatch이면
                발생합니다.
        """
        return self._read_path_if_current(self.path)

    def preflight_claim(self, handoff_id: str) -> None:
        """Original과 durable claim이 모순 없이 prepared target 하나를 나타내는지 봅니다.

        Args:
            handoff_id: Claim path를 결정하는 durable prepared plan identity입니다.

        Raises:
            MonitorExternalFileConflict: Original/claim mismatch 또는 duplicate이면 발생합니다.
        """
        claim_path = monitor_runtime_claim_path(
            self.path.parent,
            handoff_id=handoff_id,
            target_name=self.path.name,
        )
        foreign_claims = tuple(
            candidate
            for candidate in self.path.parent.glob(
                f".monitor-handoff.*.{glob.escape(self.path.name)}.claimed"
            )
            if self._lexical_path(candidate) != self._lexical_path(claim_path)
        )
        if foreign_claims:
            raise MonitorExternalFileConflict(
                f"external file fingerprint conflict: foreign handoff claim: {self.path}"
            )
        original = self._read_path_if_current(self.path)
        claim = self._read_path_if_current(claim_path)
        if original is not None and claim is not None:
            raise MonitorExternalFileConflict(
                f"external file fingerprint conflict: duplicate original and claim: {self.path}"
            )

    def claim(self, handoff_id: str) -> PreparedFileClaim:
        """Exact original을 deterministic crash-resumable claim path로 atomic rename합니다.

        Args:
            handoff_id: Claim path를 결정하는 durable prepared plan identity입니다.

        Returns:
            Existing claim, 새 claim 또는 already-missing 상태를 나타내는 value object입니다.

        Raises:
            MonitorExternalFileConflict: Original/claim이 prepared fingerprint와 다르면
                발생합니다.
        """
        claim_path = monitor_runtime_claim_path(
            self.path.parent,
            handoff_id=handoff_id,
            target_name=self.path.name,
        )
        self.preflight_claim(handoff_id)
        if self._read_path_if_current(claim_path) is not None:
            return PreparedFileClaim(target=self, path=claim_path, present=True)
        if self.read_if_current() is None:
            return PreparedFileClaim(target=self, path=claim_path, present=False)
        os.replace(self.path, claim_path)
        if self._read_path_if_current(claim_path) is None:
            raise MonitorExternalFileConflict(
                f"external file fingerprint conflict: atomic claim disappeared: {self.path}"
            )
        return PreparedFileClaim(target=self, path=claim_path, present=True)

    def _read_path_if_current(self, path: Path) -> bytes | None:
        try:
            content, metadata = self._stable_read(path)
        except FileNotFoundError:
            return None
        actual = (
            hashlib.sha256(content).hexdigest(),
            metadata.st_size,
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mtime_ns,
        )
        expected = (self.sha256, self.size, self.device, self.inode, self.mtime_ns)
        if actual != expected:
            raise MonitorExternalFileConflict(
                f"external file fingerprint conflict: {self.role}: {path}"
            )
        return content

    @staticmethod
    def _stable_read(path: Path) -> tuple[bytes, os.stat_result]:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            raise
        except OSError as error:
            raise MonitorExternalFileConflict(
                f"external file fingerprint conflict: non-regular target: {path}"
            ) from error
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise MonitorExternalFileConflict(
                    f"external file fingerprint conflict: non-regular target: {path}"
                )
            content = stream.read()
            after = os.fstat(stream.fileno())
        stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
            raise MonitorExternalFileConflict(
                f"external file fingerprint conflict: target changed while reading: {path}"
            )
        if len(content) != after.st_size:
            raise MonitorExternalFileConflict(
                f"external file fingerprint conflict: target size changed while reading: {path}"
            )
        return content, after

    @staticmethod
    def _lexical_path(path: Path) -> Path:
        return Path(os.path.abspath(os.fspath(path)))


class PreparedFileClaim:
    """Prepared original을 slow effect와 분리한 deterministic durable file claim입니다."""

    __slots__ = ("path", "present", "target")

    def __init__(
        self,
        *,
        target: PreparedFileTarget,
        path: Path,
        present: bool,
    ) -> None:
        """Target fingerprint와 deterministic claim presence를 결합합니다.

        Args:
            target: Prepared CAS가 승인한 exact original fingerprint입니다.
            path: Handoff ID에서 파생한 same-directory durable claim path입니다.
            present: Original 또는 기존 claim을 실제로 확보했는지 나타냅니다.
        """
        self.target = target
        self.path = PreparedFileTarget._lexical_path(path)
        self.present = present

    target: PreparedFileTarget
    """Claim bytes가 계속 일치해야 하는 prepared original fingerprint입니다."""

    path: Path
    """Crash recovery invocation도 다시 찾을 deterministic same-directory path입니다."""

    present: bool
    """False이면 original effect가 이전 invocation에서 이미 완료된 상태입니다."""

    def verify(self) -> None:
        """Present claim이 prepared fingerprint와 여전히 exact match인지 확인합니다.

        Raises:
            MonitorExternalFileConflict: Claim presence 또는 fingerprint가 달라지면
                발생합니다.
        """
        content = self.target._read_path_if_current(self.path)
        if self.present and content is None:
            raise MonitorExternalFileConflict(
                f"external file fingerprint conflict: prepared claim disappeared: {self.path}"
            )
        if not self.present and content is not None:
            raise MonitorExternalFileConflict(
                f"external file fingerprint conflict: unexpected prepared claim: {self.path}"
            )

    def discard(self) -> None:
        """Slow effect 성공 뒤 exact claimed original만 unlink합니다.

        Raises:
            MonitorExternalFileConflict: Present claim이 missing 또는 교체됐으면 발생합니다.
        """
        if not self.present:
            return
        if self.target._read_path_if_current(self.path) is None:
            raise MonitorExternalFileConflict(
                f"external file fingerprint conflict: prepared claim disappeared: {self.path}"
            )
        self.path.unlink()

    def restore(self) -> None:
        """Slow effect 실패 시 replacement를 덮지 않고 exact claim을 original로 복구합니다.

        Raises:
            MonitorExternalFileConflict: Claim이 달라졌거나 original path가 재사용됐으면
                발생합니다.
        """
        if not self.present:
            return
        if self.target._read_path_if_current(self.path) is None:
            raise MonitorExternalFileConflict(
                f"external file fingerprint conflict: prepared claim disappeared: {self.path}"
            )
        if os.path.lexists(self.target.path):
            raise MonitorExternalFileConflict(
                f"external file fingerprint conflict: cannot restore over replacement: "
                f"{self.target.path}"
            )
        os.replace(self.path, self.target.path)


class LaunchAgentTarget:
    """Prepared handoff가 제거할 exact LaunchAgent와 plist를 고정합니다."""

    __slots__ = ("file_target", "label")

    def __init__(self, *, label: str, file_target: PreparedFileTarget) -> None:
        """LaunchAgent label과 canonical plist path를 결합합니다.

        Args:
            label: launchctl에서 사용하는 exact LaunchAgent label입니다.
            file_target: Prepare 때 capture한 exact plist regular-file fingerprint입니다.

        Raises:
            MonitorRuntimeIdentityMismatch: Label이 비어 있으면 발생합니다.
        """
        if not label:
            raise MonitorRuntimeIdentityMismatch("launch agent label is missing")
        if file_target.role != "launch-agent-plist":
            raise MonitorRuntimeIdentityMismatch("launch agent file target role is invalid")
        self.label = label
        self.file_target = file_target

    label: str
    """launchctl read-back과 retirement에 사용할 exact label입니다."""

    file_target: PreparedFileTarget
    """Unload 전에 재검증하고 retirement 뒤 제거할 exact plist fingerprint입니다."""

    def to_payload(self) -> dict[str, object]:
        """Durable prepared receipt에 넣을 JSON payload를 반환합니다.

        Returns:
            Exact label과 canonical plist path를 담은 JSON object입니다.
        """
        return {"label": self.label, "plist_target": self.file_target.to_payload()}

    @classmethod
    def from_payload(cls, value: object, state_dir: Path) -> LaunchAgentTarget:
        """Persisted target이 canonical monitor directory 안인지 검증해 복원합니다.

        Args:
            value: Prepared receipt에서 읽은 LaunchAgent target입니다.
            state_dir: Plist가 속해야 하는 canonical monitor runtime directory입니다.

        Returns:
            Exact label과 fenced plist path를 보존한 immutable target입니다.

        Raises:
            MonitorRuntimeIdentityMismatch: Target shape 또는 path가 invalid하면 발생합니다.
        """
        if not isinstance(value, Mapping):
            raise MonitorRuntimeIdentityMismatch("launch agent plan must be an object")
        label = value.get("label")
        plist_target = value.get("plist_target")
        if not isinstance(label, str):
            raise MonitorRuntimeIdentityMismatch("launch agent plan identity is invalid")
        return cls(
            label=label,
            file_target=PreparedFileTarget.from_payload(
                plist_target,
                state_dir=state_dir,
                expected_role="launch-agent-plist",
                current_state_path=state_dir / "monitor-state.json",
            ),
        )


class MonitorHandoffPlan:
    """Prepared CAS가 승인한 모든 external retirement effect의 immutable plan입니다."""

    __slots__ = (
        "baseline_payload",
        "baseline_source_path",
        "detached_targets",
        "expected_label",
        "handoff_id",
        "launch_agent_targets",
        "launchctl_path",
        "state_targets",
        "suppressed_event_ids",
        "user_id",
    )

    def __init__(
        self,
        *,
        handoff_id: str,
        expected_label: str,
        user_id: int,
        launchctl_path: str,
        detached_targets: tuple[DetachedRuntimeTarget, ...],
        launch_agent_targets: tuple[LaunchAgentTarget, ...],
        state_targets: tuple[PreparedFileTarget, ...],
        baseline_source_path: str,
        baseline_payload: Mapping[str, object] | None,
        suppressed_event_ids: tuple[str, ...],
    ) -> None:
        """Stable handoff identity와 prepared external plan을 구성합니다.

        Args:
            handoff_id: Prepared/completed lifecycle을 fence하는 stable identity입니다.
            expected_label: 새 monitor가 유지할 유일한 LaunchAgent label입니다.
            user_id: LaunchAgent GUI domain user identity입니다.
            launchctl_path: Prepare 시 선택한 exact launchctl executable path입니다.
            detached_targets: 종료할 exact process identities입니다.
            launch_agent_targets: 제거할 exact LaunchAgent/plist identities입니다.
            state_targets: 제거할 exact legacy state regular-file fingerprints입니다.
            baseline_source_path: Baseline payload를 만든 exact legacy source입니다.
            baseline_payload: Prepared 뒤 canonical local state에 기록할 payload입니다.
            suppressed_event_ids: Live rescan으로 넘길 legacy event identities입니다.

        Raises:
            MonitorRuntimeIdentityMismatch: Plan identity가 invalid하면 발생합니다.
        """
        if (
            len(handoff_id) != 32
            or any(character not in "0123456789abcdef" for character in handoff_id)
            or not expected_label
            or user_id < 0
        ):
            raise MonitorRuntimeIdentityMismatch("monitor handoff plan identity is invalid")
        self.handoff_id = handoff_id
        self.expected_label = expected_label
        self.user_id = user_id
        self.launchctl_path = launchctl_path
        self.detached_targets = detached_targets
        self.launch_agent_targets = launch_agent_targets
        if any(target.role != "legacy-state" for target in state_targets):
            raise MonitorRuntimeIdentityMismatch("monitor state target role is invalid")
        self.state_targets = state_targets
        self.baseline_source_path = baseline_source_path
        self.baseline_payload = dict(baseline_payload) if baseline_payload is not None else None
        self.suppressed_event_ids = suppressed_event_ids

    @property
    def state_paths(self) -> tuple[Path, ...]:
        """Receipt readability와 completion evidence용 legacy state paths를 반환합니다.

        Returns:
            Prepared state fingerprints와 같은 순서의 canonical original paths입니다.
        """
        return tuple(target.path for target in self.state_targets)

    def verify_file_targets(self) -> None:
        """Plan의 모든 plist/state fingerprint를 effect 순서와 무관하게 preflight합니다."""
        for target in self.launch_agent_targets:
            target.file_target.preflight_claim(self.handoff_id)
        for target in self.state_targets:
            target.preflight_claim(self.handoff_id)

    def claim_file_targets(
        self,
    ) -> tuple[
        tuple[tuple[LaunchAgentTarget, PreparedFileClaim], ...],
        tuple[PreparedFileClaim, ...],
    ]:
        """All-target preflight 뒤 exact files를 crash-resumable claim paths로 옮깁니다.

        Returns:
            LaunchAgent metadata와 plist claims, 그리고 legacy state claims입니다.

        Raises:
            MonitorExternalFileConflict: Claim 중 fingerprint가 달라지면 확보한 claims를
                original path로 되돌린 뒤 발생합니다.
        """
        self.verify_file_targets()
        launch_claims: list[tuple[LaunchAgentTarget, PreparedFileClaim]] = []
        state_claims: list[PreparedFileClaim] = []
        claimed: list[PreparedFileClaim] = []
        try:
            for target in self.launch_agent_targets:
                claim = target.file_target.claim(self.handoff_id)
                launch_claims.append((target, claim))
                claimed.append(claim)
            for target in self.state_targets:
                claim = target.claim(self.handoff_id)
                state_claims.append(claim)
                claimed.append(claim)
        except MonitorExternalFileConflict:
            for claim in reversed(claimed):
                claim.restore()
            raise
        return tuple(launch_claims), tuple(state_claims)

    def to_receipt(self, paths: MonitorRuntimePaths) -> dict[str, object]:
        """Prepared mutation에 넣을 complete external plan을 반환합니다.

        Args:
            paths: Expected local state와 worktree identity를 소유하는 runtime paths입니다.

        Returns:
            재시작 뒤에도 그대로 실행할 수 있는 complete JSON plan입니다.
        """
        return {
            "provider": "local-pr-monitor",
            "handoff_id": self.handoff_id,
            "expected_label": self.expected_label,
            "user_id": self.user_id,
            "expected_state_path": str(paths.state_path.resolve()),
            "planned_detached_targets": [target.to_payload() for target in self.detached_targets],
            "planned_launch_agents": [target.to_payload() for target in self.launch_agent_targets],
            "planned_state_paths": [str(path) for path in self.state_paths],
            "planned_state_targets": [target.to_payload() for target in self.state_targets],
            "launchctl_path": self.launchctl_path,
            "baseline_source_path": self.baseline_source_path,
            "baseline_payload": (
                dict(self.baseline_payload) if self.baseline_payload is not None else None
            ),
            "suppressed_legacy_event_ids": list(self.suppressed_event_ids),
        }

    @classmethod
    def from_receipt(
        cls,
        value: object,
        *,
        paths: MonitorRuntimePaths,
        session_id: str,
        workflow_id: str,
        expected_label: str,
        user_id: int,
    ) -> MonitorHandoffPlan:
        """Prepared/completed receipt를 current command identity에 결속해 복원합니다.

        Args:
            value: Exact workflow snapshot에서 읽은 handoff receipt입니다.
            paths: Current worktree가 소유하는 canonical monitor runtime paths입니다.
            session_id: Current StateHandle의 exact root session identity입니다.
            workflow_id: Handoff를 소유하는 exact workflow identity입니다.
            expected_label: Current command가 요청한 retained LaunchAgent label입니다.
            user_id: Current command가 요청한 LaunchAgent GUI user identity입니다.

        Returns:
            Identity와 path fencing을 통과한 immutable external plan입니다.

        Raises:
            MonitorRuntimeIdentityMismatch: Receipt identity, shape 또는 path가 다르면
                발생합니다.
        """
        if not isinstance(value, Mapping):
            raise MonitorRuntimeIdentityMismatch("prepared monitor handoff is missing")
        expected_identity: dict[str, object] = {
            "provider": "local-pr-monitor",
            "session_id": session_id,
            "workflow_id": workflow_id,
            "worktree": str(paths.worktree.resolve()),
            "expected_state_path": str(paths.state_path.resolve()),
            "expected_label": expected_label,
            "user_id": user_id,
        }
        for field, expected in expected_identity.items():
            if value.get(field) != expected:
                raise MonitorRuntimeIdentityMismatch(
                    f"prepared monitor handoff {field.replace('_', ' ')} mismatch"
                )
        if value.get("state") not in {"prepared", "completed"}:
            raise MonitorRuntimeIdentityMismatch("monitor handoff lifecycle is invalid")
        handoff_id = value.get("handoff_id")
        launchctl_path = value.get("launchctl_path")
        detached_payloads = value.get("planned_detached_targets")
        launch_payloads = value.get("planned_launch_agents")
        state_path_values = value.get("planned_state_paths")
        state_target_values = value.get("planned_state_targets")
        baseline_source_path = value.get("baseline_source_path")
        baseline_payload = value.get("baseline_payload")
        suppressed_event_ids = value.get("suppressed_legacy_event_ids")
        if (
            not isinstance(handoff_id, str)
            or not isinstance(launchctl_path, str)
            or not isinstance(detached_payloads, list)
            or not isinstance(launch_payloads, list)
            or not isinstance(state_path_values, list)
            or not isinstance(state_target_values, list)
            or not isinstance(baseline_source_path, str)
            or (baseline_payload is not None and not isinstance(baseline_payload, Mapping))
            or not isinstance(suppressed_event_ids, list)
            or any(not isinstance(event_id, str) for event_id in suppressed_event_ids)
        ):
            raise MonitorRuntimeIdentityMismatch("monitor handoff external plan is invalid")
        state_targets = tuple(
            PreparedFileTarget.from_payload(
                payload,
                state_dir=paths.state_dir,
                expected_role="legacy-state",
                current_state_path=paths.state_path,
            )
            for payload in state_target_values
        )
        state_paths = cls._state_paths(state_path_values, paths)
        if state_paths != tuple(target.path for target in state_targets):
            raise MonitorRuntimeIdentityMismatch("monitor state path and fingerprint plans differ")
        if baseline_source_path and baseline_source_path not in {str(path) for path in state_paths}:
            raise MonitorRuntimeIdentityMismatch("monitor baseline source is outside the plan")
        return cls(
            handoff_id=handoff_id,
            expected_label=expected_label,
            user_id=user_id,
            launchctl_path=launchctl_path,
            detached_targets=tuple(
                DetachedRuntimeTarget.from_payload(payload) for payload in detached_payloads
            ),
            launch_agent_targets=tuple(
                LaunchAgentTarget.from_payload(payload, paths.state_dir)
                for payload in launch_payloads
            ),
            state_targets=state_targets,
            baseline_source_path=baseline_source_path,
            baseline_payload=(
                dict(baseline_payload) if isinstance(baseline_payload, Mapping) else None
            ),
            suppressed_event_ids=tuple(suppressed_event_ids),
        )

    @classmethod
    def _state_paths(
        cls,
        values: list[object],
        paths: MonitorRuntimePaths,
    ) -> tuple[Path, ...]:
        """Persisted obsolete paths를 canonical monitor directory로 fence합니다."""
        canonical: list[Path] = []
        for value in values:
            if not isinstance(value, str):
                raise MonitorRuntimeIdentityMismatch("monitor state plan path is invalid")
            candidate = PreparedFileTarget._lexical_path(Path(value))
            if (
                candidate.parent != paths.state_dir.resolve()
                or not candidate.name.endswith("-state.json")
                or candidate == PreparedFileTarget._lexical_path(paths.state_path)
            ):
                raise MonitorRuntimeIdentityMismatch("monitor state plan path is not canonical")
            canonical.append(candidate)
        return tuple(canonical)
