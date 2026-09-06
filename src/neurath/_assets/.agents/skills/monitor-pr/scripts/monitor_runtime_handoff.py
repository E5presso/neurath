"""PR monitor runtime 하나를 exact session workflow에 안전하게 인계합니다."""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import plistlib
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from monitor_runtime_lock import MonitorRuntimeCommitLock, monitor_runtime_claim_path

from scripts.agent_harness.session_kernel import (
    SessionKernelError,
    SessionLocator,
    WorkflowId,
)
from scripts.agent_harness.skill_state_store import SkillStateSnapshot, SkillStateStore
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityError,
    StateHandle,
)
from scripts.agent_harness.worktree_registry import (
    CanonicalWorktreeIdentity,
    WorktreeIdentityResolver,
    WorktreeRegistryError,
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


class MonitorWorkflowSnapshotValidator:
    """Runtime retirement 전에 persisted owner와 monitor route를 fail-closed 검증합니다."""

    _OWNER_STATES = frozenset({"active", "idle", "recovering", "terminal"})

    def __init__(
        self,
        *,
        session_id: str,
        workflow_id: str,
        paths: MonitorRuntimePaths,
    ) -> None:
        """Current runtime authority와 canonical local route를 고정합니다.

        Args:
            session_id: StateHandle이 검증한 exact root session identity입니다.
            workflow_id: Handoff가 속한 exact active workflow identity입니다.
            paths: Git identity에서 파생한 canonical monitor runtime paths입니다.
        """
        self._session_id = session_id
        self._workflow_id = workflow_id
        self._paths = paths

    def validate(self, state: Mapping[str, object]) -> None:
        """Owner fence와 optional monitor runtime receipt의 exact identity를 확인합니다.

        Args:
            state: Exact workflow의 latest skill-state snapshot입니다.

        Raises:
            MonitorRuntimeIdentityMismatch: Owner, session, workflow 또는 local route가
                current authority와 다를 때 발생합니다.
        """
        self._validate_owner_lifecycle(state.get("owner_lifecycle"))
        subscription = state.get("monitor_event_subscription")
        started = state.get("monitor_started")
        if subscription is not None:
            self._validate_runtime_receipt(subscription, "monitor_event_subscription")
        if started is not None:
            self._validate_runtime_receipt(started, "monitor_started")
            if subscription is None:
                raise MonitorRuntimeIdentityMismatch(
                    "detached monitor subscription identity is missing"
                )

    def _validate_owner_lifecycle(self, value: object) -> None:
        if not isinstance(value, Mapping):
            raise MonitorRuntimeIdentityMismatch(
                "workflow-local owner lifecycle identity is missing"
            )
        if value.get("state") not in self._OWNER_STATES:
            raise MonitorRuntimeIdentityMismatch("owner lifecycle state is invalid")
        if value.get("owner_session_id") != self._session_id:
            raise MonitorRuntimeIdentityMismatch("owner session identity mismatch")

    def _validate_runtime_receipt(self, value: object, field: str) -> None:
        if not isinstance(value, Mapping):
            raise MonitorRuntimeIdentityMismatch(f"{field} must be an object")
        if "process_state_path" in value:
            raise MonitorRuntimeIdentityMismatch(
                f"{field} cannot select worktree-local process state"
            )
        expected: dict[str, object] = {
            "provider": "local-pr-monitor",
            "session_id": self._session_id,
            "workflow_id": self._workflow_id,
        }
        if "worktree_id" in value or "observation_resource" in value:
            expected.update({
                "worktree_id": self._paths.worktree_id,
                "observation_resource": self._paths.observation_resource(),
            })
        else:
            expected.update({
                "worktree": str(self._paths.worktree.resolve()),
                "state_path": str(self._paths.state_path.resolve()),
            })
        for key, expected_value in expected.items():
            if value.get(key) != expected_value:
                identity_name = {
                    "session_id": "session",
                    "workflow_id": "workflow",
                }.get(key, key.replace("_", " "))
                raise MonitorRuntimeIdentityMismatch(f"{field} {identity_name} identity mismatch")
        thread_id = value.get("thread_id")
        if thread_id is not None and thread_id != self._session_id:
            raise MonitorRuntimeIdentityMismatch(f"{field} thread identity mismatch")


class MonitorHandoffPreparedMutation:
    """Legacy event migration과 prepared receipt를 pure optimistic transform으로 만듭니다."""

    _OWNER_STATES = frozenset({"active", "idle", "recovering", "terminal"})

    def __init__(
        self,
        *,
        session_id: str,
        workflow_id: str,
        worktree: str,
        prepared_at: str,
        mailbox_updated_at_epoch: float,
        receipt: Mapping[str, object],
        migrated_events: tuple[Mapping[str, object], ...],
    ) -> None:
        """Retry 사이에서 바뀌면 안 되는 identity, time, migration input을 고정합니다.

        Args:
            session_id: Workflow owner와 일치해야 하는 exact session identity입니다.
            workflow_id: Receipt에 결속할 exact workflow identity입니다.
            worktree: Git이 증명한 canonical worktree path입니다.
            prepared_at: I/O 전에 한 번 캡처한 UTC timestamp입니다.
            mailbox_updated_at_epoch: Mailbox mutation에 사용할 한 번 캡처한 epoch입니다.
            receipt: Retirement와 legacy inventory를 담은 immutable input receipt입니다.
            migrated_events: 안전하게 재큐잉할 수 있는 legacy event 후보입니다.
        """
        self._session_id = session_id
        self._workflow_id = workflow_id
        self._worktree = worktree
        self._prepared_at = prepared_at
        self._mailbox_updated_at_epoch = mailbox_updated_at_epoch
        self._receipt = dict(receipt)
        self._migrated_events = tuple(dict(event) for event in migrated_events)

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Latest workflow state에 exact-once mailbox와 prepared lifecycle을 계산합니다.

        Args:
            current: SkillStateStore가 optimistic retry마다 제공하는 latest snapshot입니다.

        Returns:
            Concurrent sibling field와 owner lifecycle을 보존한 새 skill-state object입니다.

        Raises:
            MonitorRuntimeIdentityMismatch: Retry 중 owner identity 또는 mailbox shape가
                invariant를 벗어나면 발생합니다.
        """
        self._validate_owner(current.get("owner_lifecycle"))
        next_state = dict(current)
        mailbox = self._mailbox(current.get("monitor_mailbox"))
        acknowledged_event_id = self._event_id(current.get("monitor_event_ack"))
        pending = mailbox["pending_events"]
        seen = mailbox["seen_event_ids"]
        if not isinstance(pending, list) or not isinstance(seen, list):
            raise MonitorRuntimeIdentityMismatch("monitor mailbox is not normalized")
        migrated_event_ids: list[str] = []
        staged_event_ids: list[str] = []
        inserted = False
        for event in self._migrated_events:
            event_id = self._event_id(event)
            if not event_id or event_id == acknowledged_event_id:
                continue
            migrated_event_ids.append(event_id)
            if event_id in seen:
                continue
            pending.append(dict(event))
            seen.append(event_id)
            staged_event_ids.append(event_id)
            inserted = True
        if inserted or current.get("monitor_mailbox") is not None:
            mailbox["updated_at_epoch"] = self._mailbox_updated_at_epoch
            next_state["monitor_mailbox"] = mailbox
        prepared_receipt = dict(self._receipt)
        prepared_receipt.update({
            "state": "prepared",
            "session_id": self._session_id,
            "workflow_id": self._workflow_id,
            "worktree": self._worktree,
            "prepared_at": self._prepared_at,
            "migrated_event_ids": list(dict.fromkeys(migrated_event_ids)),
            "staged_event_ids": staged_event_ids,
        })
        next_state["monitor_runtime_handoff"] = prepared_receipt
        return next_state

    def _validate_owner(self, value: object) -> None:
        if not isinstance(value, Mapping):
            raise MonitorRuntimeIdentityMismatch("workflow-local owner lifecycle is missing")
        if value.get("state") not in self._OWNER_STATES:
            raise MonitorRuntimeIdentityMismatch("owner lifecycle state is invalid")
        if value.get("owner_session_id") != self._session_id:
            raise MonitorRuntimeIdentityMismatch("owner session identity mismatch")

    def _mailbox(self, value: object) -> dict[str, object]:
        if value is None:
            return {
                "pending_events": [],
                "seen_event_ids": [],
                "active_claim": None,
            }
        if not isinstance(value, Mapping):
            raise MonitorRuntimeIdentityMismatch("monitor mailbox must be an object")
        pending = value.get("pending_events", [])
        seen = value.get("seen_event_ids", [])
        active_claim = value.get("active_claim")
        if not isinstance(pending, list) or any(
            not isinstance(event, Mapping) for event in pending
        ):
            raise MonitorRuntimeIdentityMismatch(
                "monitor mailbox pending events must be object array"
            )
        if not isinstance(seen, list) or any(not isinstance(event_id, str) for event_id in seen):
            raise MonitorRuntimeIdentityMismatch(
                "monitor mailbox seen event identities must be string array"
            )
        if active_claim is not None and not isinstance(active_claim, Mapping):
            raise MonitorRuntimeIdentityMismatch(
                "monitor mailbox active claim must be an object or null"
            )
        return {
            **value,
            "pending_events": [dict(event) for event in pending],
            "seen_event_ids": list(seen),
            "active_claim": dict(active_claim) if isinstance(active_claim, Mapping) else None,
        }

    def _event_id(self, value: object) -> str:
        if not isinstance(value, Mapping):
            return ""
        event_id = value.get("event_id")
        return event_id if isinstance(event_id, str) and event_id else ""


class MonitorHandoffCompletedMutation:
    """Prepared receipt와 exact handoff identity가 같은 경우에만 완료로 전이합니다."""

    def __init__(
        self,
        *,
        handoff_id: str,
        completed_at: str,
        retired_detached_pids: tuple[int, ...],
        retired_labels: tuple[str, ...],
        removed_state_paths: tuple[str, ...],
    ) -> None:
        """Deletion read-back 뒤 한 번 캡처한 completion evidence를 고정합니다.

        Args:
            handoff_id: Prepared transaction과 동일해야 하는 fencing identity입니다.
            completed_at: Retry 밖에서 한 번 캡처한 UTC timestamp입니다.
            retired_detached_pids: Exact plan상 종료가 read-back된 process IDs입니다.
            retired_labels: Exact plan상 unloaded가 read-back된 LaunchAgent labels입니다.
            removed_state_paths: 실제 unlink가 끝난 obsolete state paths입니다.
        """
        self._handoff_id = handoff_id
        self._completed_at = completed_at
        self._retired_detached_pids = retired_detached_pids
        self._retired_labels = retired_labels
        self._removed_state_paths = removed_state_paths

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Exact prepared lifecycle만 completed receipt로 바꿉니다.

        Args:
            current: SkillStateStore가 optimistic retry마다 제공하는 latest snapshot입니다.

        Returns:
            Unrelated workflow state를 보존한 completed handoff snapshot입니다.

        Raises:
            MonitorRuntimeIdentityMismatch: Prepared receipt가 없거나 다른 handoff이면
                발생합니다.
        """
        handoff = current.get("monitor_runtime_handoff")
        if not isinstance(handoff, Mapping):
            raise MonitorRuntimeIdentityMismatch("prepared monitor handoff is missing")
        if handoff.get("handoff_id") != self._handoff_id:
            raise MonitorRuntimeIdentityMismatch("monitor handoff fencing identity mismatch")
        if handoff.get("state") not in {"prepared", "completed"}:
            raise MonitorRuntimeIdentityMismatch("monitor handoff lifecycle is invalid")
        completed = dict(handoff)
        completed.update({
            "state": "completed",
            "completed_at": self._completed_at,
            "retired_detached_pids": list(self._retired_detached_pids),
            "retired_labels": list(self._retired_labels),
            "removed_state_paths": list(self._removed_state_paths),
            "live_rescan_required": bool(self._removed_state_paths),
        })
        return {**current, "monitor_runtime_handoff": completed}


class MonitorRuntimeInventory:
    """Local process manager와 LaunchAgent의 exact obsolete runtime만 퇴역시킵니다."""

    def __init__(
        self,
        *,
        paths: MonitorRuntimePaths,
        session_id: str,
        workflow_id: str,
    ) -> None:
        """Detached process를 식별할 route fragments를 고정합니다.

        Args:
            paths: Git identity에서 파생된 canonical local runtime paths입니다.
            session_id: Process command의 exact root session identity입니다.
            workflow_id: Process command의 exact workflow identity입니다.
        """
        self._paths = paths
        self._session_id = session_id
        self._workflow_id = workflow_id

    def detached_targets(
        self,
        state: Mapping[str, object],
    ) -> tuple[DetachedRuntimeTarget, ...]:
        """Exact subscription이 가리키는 live process를 read-only로 inventory합니다.

        Args:
            state: Runtime route receipt를 가진 validated workflow skill state입니다.

        Returns:
            Durable prepared plan에 넣을 exact PID와 command targets입니다.

        Raises:
            MonitorRuntimeIdentityMismatch: Detached receipt가 subscription 없이 존재하면
                발생합니다.
        """
        subscription = state.get("monitor_event_subscription")
        started = state.get("monitor_started")
        if subscription is None:
            if isinstance(started, Mapping) and started.get("launcher") == "nohup":
                raise MonitorRuntimeIdentityMismatch(
                    "detached monitor subscription identity is missing"
                )
            return ()
        if not isinstance(subscription, Mapping):
            raise MonitorRuntimeIdentityMismatch("monitor event subscription must be an object")
        route = started if isinstance(started, Mapping) else subscription
        if route.get("launcher") != "nohup":
            return ()
        return self._matching_detached_processes(route, subscription)

    def retire_detached(
        self,
        targets: tuple[DetachedRuntimeTarget, ...],
    ) -> tuple[int, ...]:
        """Prepared plan의 exact process가 아직 같을 때만 종료합니다.

        Missing process 또는 다른 command로 재사용된 PID는 prepared target이 이미
        사라진 것으로 판정해 성공 read-back합니다.

        Args:
            targets: Prepared CAS가 승인한 exact process identities입니다.

        Returns:
            Exact target이 모두 사라졌음을 read-back한 process ID 목록입니다.
        """
        for target in targets:
            readback = self._process_command(target.pid)
            if readback is None or readback != target.command:
                continue
            try:
                os.kill(target.pid, signal.SIGTERM)
            except ProcessLookupError:
                continue
            self._wait_for_process_exit(target)
        return tuple(target.pid for target in targets)

    def launch_agent_targets(self, expected_label: str) -> tuple[LaunchAgentTarget, ...]:
        """Expected label 외의 worktree-local plist를 read-only로 inventory합니다.

        Args:
            expected_label: 새 monitor가 이어서 사용할 유일한 LaunchAgent label입니다.
        Returns:
            Durable prepared plan에 넣을 exact label/plist targets입니다.
        """
        if not self._paths.state_dir.is_dir():
            return ()
        targets: list[LaunchAgentTarget] = []
        for plist_path in sorted(self._paths.state_dir.glob("*.plist")):
            file_target = PreparedFileTarget.capture(
                role="launch-agent-plist",
                path=plist_path,
            )
            label = self._plist_label(file_target)
            if not label or label == expected_label:
                continue
            targets.append(LaunchAgentTarget(label=label, file_target=file_target))
        return tuple(targets)

    def retire_launch_agents(
        self,
        targets: tuple[tuple[LaunchAgentTarget, PreparedFileClaim], ...],
        *,
        launchctl_path: str,
        user_id: int,
    ) -> tuple[str, ...]:
        """Prepared plist claim이 증명하는 exact LaunchAgents만 idempotently unload합니다.

        Args:
            targets: Commit lock 아래 확보한 exact LaunchAgent/plist claims입니다.
            launchctl_path: Prepared plan에 고정된 launchctl executable입니다.
            user_id: Prepared plan에 고정된 GUI domain user identity입니다.

        Returns:
            Exact claim으로 unload했거나 launchd 부재를 read-back한 labels입니다.
        """
        retired: list[str] = []
        for target, claim in targets:
            if not claim.present:
                if launchctl_path and self._launch_agent_is_absent(
                    launchctl_path,
                    target.label,
                    user_id,
                ):
                    retired.append(target.label)
                continue
            claim.verify()
            if launchctl_path:
                self._retire_launch_agent(launchctl_path, target.label, user_id)
            retired.append(target.label)
        return tuple(retired)

    def _matching_detached_processes(
        self,
        route: Mapping[str, object],
        subscription: Mapping[str, object],
    ) -> tuple[DetachedRuntimeTarget, ...]:
        runtime_id = route.get("runtime_id")
        if not isinstance(runtime_id, str) or not runtime_id:
            raise MonitorRuntimeIdentityMismatch(
                "detached monitor runtime fencing identity is missing"
            )
        repo = subscription.get("repo")
        pr_number = subscription.get("pr_number")
        if not isinstance(repo, str) or not repo:
            raise MonitorRuntimeIdentityMismatch("detached monitor repo identity is missing")
        if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
            raise MonitorRuntimeIdentityMismatch("detached monitor PR identity is missing")
        matches: list[DetachedRuntimeTarget] = []
        for field in ("pid", "manager_pid"):
            raw_pid = route.get(field)
            if raw_pid is None:
                continue
            if not isinstance(raw_pid, int) or isinstance(raw_pid, bool) or raw_pid <= 0:
                raise MonitorRuntimeIdentityMismatch(f"detached monitor {field} receipt is invalid")
            command = self._process_command(raw_pid)
            if command is None:
                continue
            if not self._matches_command(
                command,
                repo=repo,
                pr_number=pr_number,
                runtime_id=runtime_id,
            ):
                raise MonitorRuntimeIdentityMismatch(
                    f"detached monitor {field} process identity mismatch"
                )
            if all(target.pid != raw_pid for target in matches):
                matches.append(DetachedRuntimeTarget(pid=raw_pid, command=command))
        return tuple(matches)

    def _matches_command(
        self,
        command_text: str,
        *,
        repo: str,
        pr_number: int,
        runtime_id: str,
    ) -> bool:
        try:
            command = shlex.split(command_text)
        except ValueError:
            return False
        return (
            any(Path(part).name == "local_pr_monitor.py" for part in command)
            and self._option_matches(command, "--repo", repo)
            and self._option_matches(command, "--pr-number", str(pr_number))
            and self._option_matches(command, "--workflow-id", self._workflow_id)
            and self._option_matches(command, "--runtime-id", runtime_id)
            and self._option_matches(command, "--launcher", "nohup")
        )

    def _option_matches(
        self,
        command: Sequence[str],
        option: str,
        expected: str,
    ) -> bool:
        try:
            index = command.index(option)
        except ValueError:
            return False
        return index + 1 < len(command) and command[index + 1] == expected

    def _process_command(self, pid: int) -> str | None:
        readback = subprocess.run(
            ("ps", "-p", str(pid), "-o", "command="),
            capture_output=True,
            text=True,
            check=False,
        )
        return readback.stdout if readback.returncode == 0 else None

    def _wait_for_process_exit(self, target: DetachedRuntimeTarget) -> None:
        for _attempt in range(50):
            command = self._process_command(target.pid)
            if command is None or command != target.command:
                return
            time.sleep(0.1)
        raise MonitorRuntimeRetirementFailed(f"detached monitor process did not stop: {target.pid}")

    def _plist_label(self, target: PreparedFileTarget) -> str:
        try:
            content = target.read_if_current()
            if content is None:
                return ""
            payload = plistlib.loads(content)
        except plistlib.InvalidFileException:
            return ""
        if not isinstance(payload, dict):
            return ""
        label = payload.get("Label")
        return label if isinstance(label, str) and label else ""

    def _retire_launch_agent(self, launchctl: str, label: str, user_id: int) -> None:
        domain_target = f"gui/{user_id}/{label}"
        initial = subprocess.run(
            (launchctl, "print", domain_target),
            capture_output=True,
            text=True,
            check=False,
        )
        if initial.returncode != 0:
            return
        subprocess.run(
            (launchctl, "bootout", domain_target),
            capture_output=True,
            text=True,
            check=False,
        )
        subprocess.run(
            (launchctl, "remove", label),
            capture_output=True,
            text=True,
            check=False,
        )
        readback = subprocess.run(
            (launchctl, "print", domain_target),
            capture_output=True,
            text=True,
            check=False,
        )
        if readback.returncode == 0:
            raise MonitorRuntimeRetirementFailed(
                f"obsolete monitor runtime is still loaded: {label}"
            )

    def _launch_agent_is_absent(self, launchctl: str, label: str, user_id: int) -> bool:
        """Prepared plist claim이 이미 없을 때 label 부재만 read-back합니다.

        Args:
            launchctl: Prepared plan에 고정된 exact executable path입니다.
            label: Unload 권한 없이 부재만 확인할 prepared LaunchAgent label입니다.
            user_id: Prepared plan에 고정된 GUI domain user identity입니다.

        Returns:
            Exact GUI domain read-back에서 label이 missing이면 True입니다.

        Raises:
            MonitorRuntimeRetirementFailed: Claim 없는 label이 loaded 상태면 발생합니다.
        """
        domain_target = f"gui/{user_id}/{label}"
        readback = subprocess.run(
            (launchctl, "print", domain_target),
            capture_output=True,
            text=True,
            check=False,
        )
        if readback.returncode == 0:
            raise MonitorRuntimeRetirementFailed(
                f"obsolete monitor runtime is loaded without prepared plist claim: {label}"
            )
        return True


class LegacyMonitorState:
    """한 legacy local monitor snapshot과 migration 정렬 근거를 묶습니다."""

    __slots__ = ("path", "payload", "recency")

    def __init__(self, path: Path, payload: Mapping[str, object], recency: float) -> None:
        """Compatibility reader가 검증한 snapshot을 고정합니다.

        Args:
            path: One-way migration 뒤 제거할 local state path입니다.
            payload: JSON object로 검증된 legacy state입니다.
            recency: Baseline 선택에 사용할 heartbeat 또는 mtime입니다.
        """
        self.path = path
        self.payload = dict(payload)
        self.recency = recency

    path: Path
    """One-way migration input인 obsolete local state path입니다."""

    payload: Mapping[str, object]
    """Legacy monitor가 마지막으로 기록한 JSON object입니다."""

    recency: float
    """가장 최신 observation baseline을 고르는 정렬 값입니다."""


class LegacyMonitorFileStore:
    """Compatibility JSON을 current monitor와 공유하지 않는 atomic file boundary입니다."""

    def read(self, target: PreparedFileTarget) -> Mapping[str, object]:
        """Legacy file에서 JSON object만 읽습니다.

        Args:
            target: One-way migration input의 prepared regular-file fingerprint입니다.

        Returns:
            JSON root가 object임을 검증한 snapshot입니다.

        Raises:
            LegacyMonitorStateInvalid: JSON root가 object가 아닐 때 발생합니다.
            OSError: Input을 읽을 수 없을 때 발생합니다.
            json.JSONDecodeError: Input JSON이 손상됐을 때 발생합니다.
        """
        content = target.read_if_current()
        if content is None:
            raise MonitorExternalFileConflict(
                f"external file fingerprint conflict: missing inventory target: {target.path}"
            )
        payload = json.loads(content.decode("utf-8"))
        if not isinstance(payload, dict):
            raise LegacyMonitorStateInvalid(f"{target.path} must contain a JSON object")
        return payload

    def write_if_absent(self, path: Path, payload: Mapping[str, object]) -> bool:
        """Prepared baseline을 fsync 뒤 atomic no-replace create로 기록합니다.

        Args:
            path: 새 monitor가 이어서 읽을 canonical local runtime state입니다.
            payload: Compatibility reader가 만든 observation baseline입니다.

        Returns:
            Baseline을 생성했으면 True, competing current state가 먼저 있으면 False입니다.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_name = ""
        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                json.dump(dict(payload), temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            try:
                os.link(temporary_name, path)
            except FileExistsError:
                return False
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
            return True
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)


class LegacyMonitorMigration:
    """Worktree-local monitor state를 한 번 읽어 canonical workflow mailbox로 옮깁니다."""

    _MIGRATABLE_REASONS = frozenset({
        "comments-changed",
        "ci-failed",
        "merge-dirty",
        "review-blocked",
        "mergeable-clean",
        "merged",
        "closed-without-merge",
    })

    def __init__(self, paths: MonitorRuntimePaths) -> None:
        """Compatibility input과 current local state의 canonical 경계를 고정합니다.

        Args:
            paths: Current worktree의 local monitor runtime paths입니다.
        """
        self._paths = paths
        self._files = LegacyMonitorFileStore()

    def inventory(
        self,
        targets: tuple[PreparedFileTarget, ...],
    ) -> tuple[LegacyMonitorState, ...]:
        """Canonical current state를 제외한 obsolete `*-state.json`만 읽습니다.

        Args:
            targets: 한 번의 directory inventory에서 capture한 exact legacy files입니다.

        Returns:
            읽을 수 있는 legacy JSON object snapshot 목록입니다.
        """
        states: list[LegacyMonitorState] = []
        for target in targets:
            try:
                payload = self._files.read(target)
            except json.JSONDecodeError, LegacyMonitorStateInvalid, UnicodeDecodeError:
                continue
            states.append(
                LegacyMonitorState(
                    target.path,
                    payload,
                    self._recency(target.path, payload),
                )
            )
        return tuple(states)

    def obsolete_targets(self) -> tuple[PreparedFileTarget, ...]:
        """읽기 성공 여부와 무관하게 obsolete state fingerprints를 capture합니다.

        Returns:
            Canonical current state를 제외한 exact regular-file optimistic keys입니다.
        """
        if not self._paths.state_dir.is_dir():
            return ()
        return tuple(
            PreparedFileTarget.capture(role="legacy-state", path=candidate)
            for candidate in sorted(self._paths.state_dir.glob("*-state.json"))
            if PreparedFileTarget._lexical_path(candidate)
            != PreparedFileTarget._lexical_path(self._paths.state_path)
        )

    def events(
        self,
        states: tuple[LegacyMonitorState, ...],
    ) -> tuple[Mapping[str, object], ...]:
        """Live rescan 없이 재큐잉해도 안전한 event만 중복 없이 반환합니다.

        Args:
            states: 읽을 수 있는 legacy local monitor snapshots입니다.

        Returns:
            Stable event identity와 허용 reason을 가진 event 목록입니다.
        """
        migrated: list[Mapping[str, object]] = []
        seen: set[str] = set()
        for state in states:
            event = state.payload.get("last_event")
            if not isinstance(event, Mapping):
                continue
            event_id = self._event_id(event)
            reason = event.get("reason")
            if (
                not event_id
                or event_id in seen
                or event_id in self._acknowledged_event_ids(state.payload)
                or not isinstance(reason, str)
                or reason not in self._MIGRATABLE_REASONS
            ):
                continue
            seen.add(event_id)
            migrated.append(dict(event))
        return tuple(migrated)

    def suppressed_event_ids(
        self,
        states: tuple[LegacyMonitorState, ...],
    ) -> tuple[str, ...]:
        """Live aggregate 재검증이 필요해 mailbox에 넣지 않은 event identity를 반환합니다.

        Args:
            states: 읽을 수 있는 legacy local monitor snapshots입니다.

        Returns:
            Automatic 또는 delegate-result event처럼 rescan해야 하는 identity입니다.
        """
        suppressed: list[str] = []
        for state in states:
            event = state.payload.get("last_event")
            if not isinstance(event, Mapping):
                continue
            event_id = self._event_id(event)
            reason = event.get("reason")
            if (
                event_id
                and event_id not in self._acknowledged_event_ids(state.payload)
                and reason not in self._MIGRATABLE_REASONS
            ):
                suppressed.append(event_id)
        return tuple(dict.fromkeys(suppressed))

    def baseline_plan(
        self,
        states: tuple[LegacyMonitorState, ...],
        suppressed_event_ids: tuple[str, ...],
    ) -> tuple[str, Mapping[str, object] | None]:
        """Current state가 없을 때 쓸 baseline action을 read-only로 계산합니다.

        Args:
            states: 읽을 수 있는 legacy local monitor snapshots입니다.
            suppressed_event_ids: Mailbox 대신 live rescan으로 넘긴 event identities입니다.

        Returns:
            Baseline source path와 persisted payload이며 action이 없으면 빈 값들입니다.
        """
        if not states or self._paths.state_path.exists():
            return "", None
        source = max(states, key=lambda state: state.recency)
        baseline = self._observation_baseline(source.payload)
        payload: dict[str, object] = {
            "schema_version": 3,
            "provider": "local-pr-monitor",
            "legacy_handoff": {
                "source_state_path": str(source.path),
                "suppressed_legacy_event_ids": list(suppressed_event_ids),
            },
        }
        if baseline:
            payload["last_seen"] = dict(baseline)
            payload["last_observed"] = dict(baseline)
        return str(source.path), payload

    def write_baseline(self, payload: Mapping[str, object] | None) -> None:
        """Prepared plan의 exact baseline을 canonical state가 없을 때만 기록합니다.

        Args:
            payload: Prepared receipt에 durable하게 저장된 complete baseline payload입니다.
        """
        if payload is None or self._paths.state_path.exists():
            return
        self._files.write_if_absent(self._paths.state_path, payload)

    def remove(self, claims: tuple[PreparedFileClaim, ...]) -> tuple[str, ...]:
        """Workflow prepared receipt 뒤 exact obsolete state만 제거합니다.

        Args:
            claims: Commit lock 아래 확보한 one-way migration input claims입니다.

        Returns:
            Exact claim을 unlink했거나 이미 absent로 확인한 original path 목록입니다.
        """
        removed: list[str] = []
        for claim in claims:
            claim.discard()
            removed.append(str(claim.target.path))
        return tuple(removed)

    def _event_id(self, event: Mapping[str, object]) -> str:
        event_id = event.get("event_id")
        return event_id if isinstance(event_id, str) and event_id else ""

    def _acknowledged_event_ids(self, state: Mapping[str, object]) -> frozenset[str]:
        event_ids: set[str] = set()
        last_acknowledged = state.get("last_acknowledged_event_id")
        if isinstance(last_acknowledged, str) and last_acknowledged:
            event_ids.add(last_acknowledged)
        monitor_ack = state.get("monitor_event_ack")
        if isinstance(monitor_ack, Mapping):
            event_id = self._event_id(monitor_ack)
            if event_id:
                event_ids.add(event_id)
        return frozenset(event_ids)

    def _recency(self, path: Path, state: Mapping[str, object]) -> float:
        heartbeat = state.get("heartbeat_at_epoch")
        if isinstance(heartbeat, int | float) and not isinstance(heartbeat, bool):
            return float(heartbeat)
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    def _observation_baseline(self, state: Mapping[str, object]) -> dict[str, object]:
        last_observed = state.get("last_observed")
        last_seen = state.get("last_seen")
        baseline = dict(last_observed) if isinstance(last_observed, Mapping) else {}
        if not baseline and isinstance(last_seen, Mapping):
            baseline = dict(last_seen)
        event = state.get("last_event")
        if not isinstance(event, Mapping):
            return baseline
        observation = event.get("observation")
        if isinstance(observation, Mapping):
            baseline["observation"] = dict(observation)
        fingerprint = event.get("fingerprint")
        if isinstance(fingerprint, Mapping):
            comments = fingerprint.get("comments")
            if isinstance(comments, Mapping):
                baseline["comments"] = dict(comments)
        snapshot = event.get("snapshot")
        if isinstance(snapshot, Mapping):
            for field in ("headRefOid", "reviewDecision"):
                value = snapshot.get(field)
                if isinstance(value, str):
                    baseline[field] = value
        return baseline


class MonitorRuntimeHandoffService:
    """Runtime retirement, compatibility migration, workflow receipt를 순서대로 수행합니다."""

    def __init__(
        self,
        *,
        handle: StateHandle,
        workflow_id: WorkflowId,
        paths: MonitorRuntimePaths,
    ) -> None:
        """Exact session actor, workflow, worktree boundary에 handoff service를 고정합니다.

        Args:
            handle: Runtime identity와 current actor에 결속된 canonical state facade입니다.
            workflow_id: Monitor owner lifecycle을 소유하는 exact workflow입니다.
            paths: Git identity가 증명한 local monitor runtime paths입니다.
        """
        self._handle = handle
        self._workflow_id = workflow_id
        self._paths = paths
        self._store = SkillStateStore(handle, workflow_id)
        self._validator = MonitorWorkflowSnapshotValidator(
            session_id=str(handle.session_id),
            workflow_id=str(workflow_id),
            paths=paths,
        )
        self._inventory = MonitorRuntimeInventory(
            paths=paths,
            session_id=str(handle.session_id),
            workflow_id=str(workflow_id),
        )
        self._migration = LegacyMonitorMigration(paths)
        self._commit_lock = MonitorRuntimeCommitLock(paths.state_dir)

    def prepare(self, *, expected_label: str, user_id: int) -> Mapping[str, object]:
        """Prepared CAS 뒤 exact external plan을 실행하고 completion을 CAS합니다.

        Args:
            expected_label: 새 monitor가 사용할 유일한 LaunchAgent label입니다.
            user_id: LaunchAgent GUI domain의 current macOS user identity입니다.

        Returns:
            Process retirement, legacy migration, live rescan 요구를 담은 receipt입니다.

        Raises:
            MonitorRuntimeHandoffError: Identity, lifecycle, retirement read-back이 실패하면
                side effect 이후 단계로 진행하지 않습니다.
            SessionKernelError: Workflow-local optimistic state commit이 실패할 때 발생합니다.
        """
        original = self._store.read()
        self._validator.validate(original.skill_state)
        existing = original.skill_state.get("monitor_runtime_handoff")
        if isinstance(existing, Mapping) and existing.get("state") in {"prepared", "completed"}:
            plan = MonitorHandoffPlan.from_receipt(
                existing,
                paths=self._paths,
                session_id=str(self._handle.session_id),
                workflow_id=str(self._workflow_id),
                expected_label=expected_label,
                user_id=user_id,
            )
            if existing.get("state") == "completed":
                return dict(existing)
            return self._execute_prepared(original, plan)
        if existing is not None and not isinstance(existing, Mapping):
            raise MonitorRuntimeIdentityMismatch("monitor handoff receipt must be an object")

        plan, migrated_events = self._candidate_plan(
            original,
            expected_label=expected_label,
            user_id=user_id,
        )
        prepared_at = datetime.now(UTC).isoformat()
        mailbox_updated_at_epoch = time.time()
        prepared = self._store.compare_and_update(
            original.workflow_revision,
            MonitorHandoffPreparedMutation(
                session_id=str(self._handle.session_id),
                workflow_id=str(self._workflow_id),
                worktree=str(self._paths.worktree.resolve()),
                prepared_at=prepared_at,
                mailbox_updated_at_epoch=mailbox_updated_at_epoch,
                receipt=plan.to_receipt(self._paths),
                migrated_events=migrated_events,
            ),
        )
        persisted = prepared.skill_state.get("monitor_runtime_handoff")
        persisted_plan = MonitorHandoffPlan.from_receipt(
            persisted,
            paths=self._paths,
            session_id=str(self._handle.session_id),
            workflow_id=str(self._workflow_id),
            expected_label=expected_label,
            user_id=user_id,
        )
        return self._execute_prepared(prepared, persisted_plan)

    def _candidate_plan(
        self,
        original: SkillStateSnapshot,
        *,
        expected_label: str,
        user_id: int,
    ) -> tuple[MonitorHandoffPlan, tuple[Mapping[str, object], ...]]:
        """Exact snapshot에서 side-effect-free external plan과 mailbox input을 계산합니다."""
        detached_targets = self._inventory.detached_targets(original.skill_state)
        launch_agent_targets = self._inventory.launch_agent_targets(expected_label)
        obsolete_targets = self._migration.obsolete_targets()
        legacy_states = self._migration.inventory(obsolete_targets)
        migrated_events = self._migration.events(legacy_states)
        suppressed_event_ids = self._migration.suppressed_event_ids(legacy_states)
        baseline_source, baseline_payload = self._migration.baseline_plan(
            legacy_states,
            suppressed_event_ids,
        )
        return (
            MonitorHandoffPlan(
                handoff_id=uuid.uuid4().hex,
                expected_label=expected_label,
                user_id=user_id,
                launchctl_path=shutil.which("launchctl") or "",
                detached_targets=detached_targets,
                launch_agent_targets=launch_agent_targets,
                state_targets=obsolete_targets,
                baseline_source_path=baseline_source,
                baseline_payload=baseline_payload,
                suppressed_event_ids=suppressed_event_ids,
            ),
            migrated_events,
        )

    def _execute_prepared(
        self,
        prepared: SkillStateSnapshot,
        plan: MonitorHandoffPlan,
    ) -> Mapping[str, object]:
        """Persisted external plan을 idempotently 실행하고 exact prepared revision을 완료합니다."""
        plan.verify_file_targets()
        with self._commit_lock:
            plan.verify_file_targets()
            launch_claims, state_claims = plan.claim_file_targets()
        try:
            retired_detached_pids = self._inventory.retire_detached(plan.detached_targets)
            retired_labels = self._inventory.retire_launch_agents(
                launch_claims,
                launchctl_path=plan.launchctl_path,
                user_id=plan.user_id,
            )
        except MonitorRuntimeHandoffError:
            with self._commit_lock:
                for _target, claim in reversed(launch_claims):
                    claim.restore()
                for claim in reversed(state_claims):
                    claim.restore()
            raise
        with self._commit_lock:
            plan.verify_file_targets()
            self._migration.write_baseline(plan.baseline_payload)
            for _target, claim in launch_claims:
                claim.discard()
            removed = self._migration.remove(state_claims)
        completed_at = datetime.now(UTC).isoformat()
        committed = self._store.compare_and_update(
            prepared.workflow_revision,
            MonitorHandoffCompletedMutation(
                handoff_id=plan.handoff_id,
                completed_at=completed_at,
                retired_detached_pids=retired_detached_pids,
                retired_labels=retired_labels,
                removed_state_paths=removed,
            ),
        )
        receipt = committed.skill_state.get("monitor_runtime_handoff")
        if not isinstance(receipt, Mapping):
            raise MonitorRuntimeIdentityMismatch("completed monitor handoff is missing")
        return dict(receipt)


class MonitorRuntimeHandoffApplication:
    """CLI input을 runtime-owned identity와 exact workflow handoff로 연결합니다."""

    def __init__(self) -> None:
        """Runtime identity와 Git worktree resolver를 application에 귀속시킵니다."""
        self._runtime_resolver = RuntimeEnvironmentResolver()
        self._worktree_resolver = WorktreeIdentityResolver()

    def run(
        self,
        arguments: Sequence[str],
        environment: Mapping[str, object],
        cwd: Path,
    ) -> MonitorRuntimeHandoffResult:
        """Manual state path 없이 current session workflow handoff를 실행합니다.

        Args:
            arguments: Required workflow ID, expected label, user ID만 담은 CLI arguments입니다.
            environment: Vendor runtime이 소유한 exact session/actor identity입니다.
            cwd: SessionLocator와 Git worktree identity를 해석할 current directory입니다.

        Returns:
            성공 receipt 또는 fail-closed diagnostic을 담은 process result입니다.

        Raises:
            SystemExit: Argparse가 지원하지 않는 option 또는 누락된 필수 option을 만나면
                발생합니다.
        """
        try:
            namespace = self._parser().parse_args(tuple(arguments))
            locator = SessionLocator.from_worktree(cwd)
            worktree = self._worktree_resolver.resolve(cwd)
            if locator.control_root.resolve() != worktree.repository_control_root.resolve():
                raise MonitorRuntimeIdentityMismatch(
                    "session locator and worktree control root mismatch"
                )
            binding = self._runtime_resolver.resolve(environment)
            handle = StateHandle.attach(locator, binding)
            workflow_id = WorkflowId(self._text(namespace, "workflow_id"))
            expected_label = self._text(namespace, "expected_label")
            user_id = self._user_id(namespace)
            receipt = MonitorRuntimeHandoffService(
                handle=handle,
                workflow_id=workflow_id,
                paths=MonitorRuntimePaths(worktree),
            ).prepare(expected_label=expected_label, user_id=user_id)
            return MonitorRuntimeHandoffResult(
                exit_code=0,
                stdout=json.dumps(
                    dict(receipt),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                stderr="",
            )
        except (
            json.JSONDecodeError,
            MonitorRuntimeHandoffError,
            OSError,
            RuntimeIdentityError,
            SessionKernelError,
            subprocess.CalledProcessError,
            WorktreeRegistryError,
        ) as error:
            return MonitorRuntimeHandoffResult(
                exit_code=2,
                stdout="",
                stderr=str(error),
            )

    def _parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="Prepare one exact session workflow local PR monitor runtime."
        )
        parser.add_argument("--workflow-id", required=True)
        parser.add_argument("--expected-label", required=True)
        parser.add_argument("--user-id", required=True, type=int)
        return parser

    def _text(self, namespace: argparse.Namespace, name: str) -> str:
        value = getattr(namespace, name, None)
        if not isinstance(value, str) or not value.strip():
            raise MonitorRuntimeIdentityMismatch(f"{name} must be a non-empty string")
        return value.strip()

    def _user_id(self, namespace: argparse.Namespace) -> int:
        value = getattr(namespace, "user_id", None)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise MonitorRuntimeIdentityMismatch("user_id must be a non-negative integer")
        return value


class MonitorRuntimeHandoffEntrypoint:
    """Current process defaults를 path-free handoff application에 전달합니다."""

    def run(self) -> int:
        """Runtime environment와 current cwd에서 CLI를 실행합니다.

        Returns:
            Application이 결정한 process exit code입니다.
        """
        result = MonitorRuntimeHandoffApplication().run(
            tuple(sys.argv[1:]),
            os.environ,
            Path.cwd(),
        )
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return result.exit_code


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(MonitorRuntimeHandoffEntrypoint().run())
