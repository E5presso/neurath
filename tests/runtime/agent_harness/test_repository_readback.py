"""Repository primary-source readback의 path와 current-byte 계약을 검증합니다."""

import hashlib
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.agent_harness.repository_readback import (
    RepositoryReadbackInvalid,
    RepositoryWorktreeReadback,
)


class RepositoryWorktreeReadbackTest(TestCase):
    """Tracked source만 canonical path와 current worktree bytes로 증명합니다."""

    def setUp(self) -> None:
        """Tracked source와 ignored directory가 있는 실제 temporary Git repository를 만듭니다."""
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repository = Path(self.directory.name)
        subprocess.run(("git", "init", "-q"), cwd=self.repository, check=True)
        subprocess.run(
            ("git", "config", "user.email", "fixture@example.invalid"),
            cwd=self.repository,
            check=True,
        )
        subprocess.run(
            ("git", "config", "user.name", "Fixture"),
            cwd=self.repository,
            check=True,
        )
        (self.repository / ".gitignore").write_text(
            ".agents/runs/\nignored/\n",
            encoding="utf-8",
        )
        source = self.repository / "docs/source.txt"
        source.parent.mkdir(parents=True)
        source.write_text("authoritative fact\n", encoding="utf-8")
        subprocess.run(
            ("git", "add", ".gitignore", "docs/source.txt"),
            cwd=self.repository,
            check=True,
        )
        subprocess.run(
            ("git", "commit", "-qm", "fixture"),
            cwd=self.repository,
            check=True,
        )
        self.readback = RepositoryWorktreeReadback(self.repository)

    def test_tracked_file_readback_binds_canonical_path_fingerprint_and_current_bytes(self) -> None:
        """Valid tracked file은 worktree fingerprint와 current content digest를 함께 반환합니다."""
        result = self.readback.read_tracked_file("docs/source.txt")

        self.assertEqual("docs/source.txt", result.relative_path)
        self.assertRegex(result.worktree_fingerprint, r"^[0-9a-f]{64}$")
        self.assertEqual(
            hashlib.sha256(b"authoritative fact\n").hexdigest(),
            result.content_digest,
        )

    def test_absolute_traversal_symlink_escape_missing_ignored_and_untracked_are_denied(
        self,
    ) -> None:
        """Reference가 repository tracked regular file 경계를 한 번도 벗어나지 못합니다."""
        outside = self.repository.parent / f"{self.repository.name}-outside.txt"
        outside.write_text("outside\n", encoding="utf-8")
        self.addCleanup(outside.unlink, missing_ok=True)
        (self.repository / "escape.txt").symlink_to(outside)
        ignored = self.repository / "ignored/cache.txt"
        ignored.parent.mkdir()
        ignored.write_text("ignored\n", encoding="utf-8")
        (self.repository / "untracked.txt").write_text("untracked\n", encoding="utf-8")
        rows = (
            str((self.repository / "docs/source.txt").resolve()),
            "../outside.txt",
            "docs/../docs/source.txt",
            "escape.txt",
            "missing.txt",
            "ignored/cache.txt",
            "untracked.txt",
        )

        for reference in rows:
            with self.subTest(reference=reference), self.assertRaises(RepositoryReadbackInvalid):
                self.readback.read_tracked_file(reference)

    def test_exact_dirty_current_bytes_are_readable_with_new_worktree_and_content_fingerprints(
        self,
    ) -> None:
        """Dirty tracked bytes는 허용하되 old authority digest와 source revision을 폐기합니다."""
        before = self.readback.read_tracked_file("docs/source.txt")
        (self.repository / "docs/source.txt").write_text("dirty fact\n", encoding="utf-8")

        after = self.readback.read_tracked_file("docs/source.txt")

        self.assertNotEqual(before.worktree_fingerprint, after.worktree_fingerprint)
        self.assertNotEqual(before.content_digest, after.content_digest)
