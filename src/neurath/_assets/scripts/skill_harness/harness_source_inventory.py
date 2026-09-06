"""Harness discovery의 파일·참조 사실을 검증하며 의미적 포화는 판정하지 않습니다."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath


class HarnessSourceInventory:
    """현재 harness 파일 목록을 manifest와 비교하는 read-only boundary입니다."""

    _SCHEMA = "neurath.harness-source-inventory.v1"
    _PREFIXES = (".neurath/", ".agents/", ".claude/", ".codex/", ".github/", "scripts/")
    _EXCLUDED_PREFIXES = (".neurath/local/", ".neurath/install.json", ".agents/runs/", ".agents/worktrees/")
    _ROOT_FILES = frozenset({
        "AGENTS.md",
        "CLAUDE.md",
        ".pre-commit-config.yaml",
        "mise.toml",
        "pyproject.toml",
    })
    _MANIFEST_KEYS = frozenset({"schema", "head_sha", "files", "capabilities"})
    _CAPABILITY_KEYS = frozenset({"id", "source_paths", "gate_paths", "regression_nodes"})

    def __init__(self, root: Path) -> None:
        """검사가 읽을 repository root를 고정합니다.

        Args:
            root: Source inventory가 읽을 Git worktree의 root입니다.
        """
        self._root = root.resolve()

    def build(self, capabilities: Sequence[Mapping[str, object]]) -> dict[str, object]:
        """현재 HEAD·파일 사실과 caller의 capability mapping을 한 manifest로 반환합니다.

        Capability의 의미나 포화 여부는 생성하지 않습니다. 결과를 ignored runtime
        artifact에 저장하고 해당 bytes의 SHA-256을 phase evidence에 제출합니다.

        Args:
            capabilities: 조사자가 source·gate·test 참조에 연결한 capability 목록입니다.

        Returns:
            현재 HEAD와 실제 파일 목록을 포함하는 JSON-compatible manifest입니다.
        """
        return {
            "schema": self._SCHEMA,
            "head_sha": self._head(),
            "files": self._files(),
            "capabilities": [dict(item) for item in capabilities],
        }

    def verify(
        self,
        *,
        reference: str,
        digest: str,
        source_sha: str,
        capability_ids: Sequence[str],
        source_files: int,
        regression_node_exists: Callable[[str], bool],
    ) -> bool:
        """Digest·current source·capability references를 실제 파일과 다시 비교합니다.

        의미적 coverage와 discovery saturation은 이 반환값의 authority가 아닙니다.

        Args:
            reference: Ignored runtime directory의 canonical manifest 상대 경로입니다.
            digest: 제출한 manifest bytes의 SHA-256입니다.
            source_sha: Source inventory가 지목한 commit SHA입니다.
            capability_ids: Manifest와 정확히 일치해야 하는 capability identity 목록입니다.
            source_files: Manifest에 요구되는 실제 source file 개수입니다.
            regression_node_exists: Repository의 exact pytest node 존재를 검사합니다.

        Returns:
            제출한 파일 사실과 참조가 current read-back과 모두 일치하면 True입니다.
        """
        try:
            path = self._manifest_path(reference)
            content = path.read_bytes()
            if len(content) > 1_048_576 or hashlib.sha256(content).hexdigest() != digest:
                return False
            manifest = json.loads(content, object_pairs_hook=self._unique_object)
            if not isinstance(manifest, dict) or set(manifest) != self._MANIFEST_KEYS:
                return False
            before = self.build(())
            if (
                manifest.get("schema") != self._SCHEMA
                or manifest.get("head_sha") != before["head_sha"]
                or (before["head_sha"] is not None and source_sha != before["head_sha"])
                or manifest.get("files") != before["files"]
            ):
                return False
            files = self._files()
            if source_files != len(files):
                return False
            regular_paths = {str(item["path"]) for item in files if item["kind"] == "file"}
            if not self._valid_capabilities(
                manifest.get("capabilities"),
                capability_ids,
                regular_paths,
                regression_node_exists,
            ):
                return False
            return before == self.build(()) and path.read_bytes() == content
        except OSError, ValueError, UnicodeError:
            return False

    def _valid_capabilities(
        self,
        value: object,
        expected_ids: Sequence[str],
        regular_paths: set[str],
        regression_node_exists: Callable[[str], bool],
    ) -> bool:
        if not isinstance(value, list) or len(value) != len(expected_ids):
            return False
        found_ids: list[str] = []
        for item in value:
            if not isinstance(item, dict) or set(item) != self._CAPABILITY_KEYS:
                return False
            capability_id = item.get("id")
            if not isinstance(capability_id, str) or capability_id in found_ids:
                return False
            found_ids.append(capability_id)
            sources = self._string_list(item.get("source_paths"))
            gates = self._string_list(item.get("gate_paths"))
            nodes = self._string_list(item.get("regression_nodes"))
            if sources is None or not sources or gates is None or nodes is None:
                return False
            if not {*sources, *gates}.issubset(regular_paths):
                return False
            if bool(gates) != bool(nodes):
                return False
            if any(
                node.partition("::")[0] not in regular_paths or not regression_node_exists(node)
                for node in nodes
            ):
                return False
        return set(found_ids) == set(expected_ids)

    def _string_list(self, value: object) -> list[str] | None:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            return None
        values = [str(item) for item in value]
        return values if len(values) == len(set(values)) else None

    def _manifest_path(self, reference: str) -> Path:
        parsed = PurePosixPath(reference)
        if (
            not reference.startswith((".neurath/local/runs/", ".agents/runs/"))
            or parsed.is_absolute()
            or str(parsed) != reference
            or any(part in {".", ".."} for part in parsed.parts)
        ):
            raise ValueError("inventory manifest must be a canonical runtime artifact")
        path = self._root
        for part in parsed.parts:
            path /= part
            if path.is_symlink():
                raise ValueError("inventory manifest cannot traverse symlinks")
        return path

    def _files(self) -> list[dict[str, object]]:
        listed = self._git(("ls-files", "-z", "--cached", "--others", "--exclude-standard"))
        records: list[dict[str, object]] = []
        for raw_path in sorted(set(listed.split(b"\0"))):
            if not raw_path:
                continue
            relative_path = os.fsdecode(raw_path)
            if not self._in_scope(relative_path):
                continue
            path = self._root / relative_path
            if path.is_symlink():
                kind, content, executable = "symlink", os.fsencode(path.readlink()), False
            elif path.is_file():
                kind, content, executable = (
                    "file",
                    path.read_bytes(),
                    bool(path.stat().st_mode & 0o111),
                )
            elif not path.exists():
                kind, content, executable = "missing", b"", False
            else:
                raise ValueError("inventory cannot read a non-file Git entry")
            records.append({
                "path": relative_path,
                "kind": kind,
                "sha256": hashlib.sha256(content).hexdigest(),
                "executable": executable,
            })
        return records

    def _in_scope(self, relative_path: str) -> bool:
        return not relative_path.startswith(self._EXCLUDED_PREFIXES) and (
            relative_path.startswith(self._PREFIXES) or relative_path in self._ROOT_FILES
        )

    def _head(self) -> str | None:
        result = subprocess.run(
            ("git", "-C", str(self._root), "rev-parse", "--verify", "HEAD"),
            check=False,
            capture_output=True,
        )
        return result.stdout.decode().strip() if result.returncode == 0 else None

    def _git(self, arguments: tuple[str, ...]) -> bytes:
        result = subprocess.run(
            ("git", "-C", str(self._root), *arguments),
            check=False,
            capture_output=True,
        )
        if result.returncode:
            raise ValueError("cannot read Git source inventory")
        return result.stdout

    def _unique_object(self, pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("inventory manifest contains duplicate keys")
            result[key] = value
        return result
