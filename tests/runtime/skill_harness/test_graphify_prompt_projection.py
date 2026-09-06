"""Graphify entrypoint가 호출 경로별 prompt를 lazy-load하는지 검증합니다."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GRAPHIFY_SKILL = ROOT / ".agents/skills/graphify/SKILL.md"
FULL_BUILD = ROOT / ".agents/skills/graphify/references/full-build.md"


class GraphifyPromptProjectionTest(unittest.TestCase):
    """Read-only query가 full-build runbook을 선주입하지 않는 계약을 고정합니다."""

    def test_entrypoint_is_bounded_dispatcher_and_full_build_remains_reachable(self) -> None:
        """Entrypoint는 bounded하고 default build의 canonical reference를 가리킵니다."""
        entrypoint = GRAPHIFY_SKILL.read_text(encoding="utf-8")
        full_build = FULL_BUILD.read_text(encoding="utf-8")

        self.assertLess(len(entrypoint.encode("utf-8")), 12_000)
        self.assertIn("references/full-build.md", entrypoint)
        self.assertIn("### Step 1 - Ensure graphify is installed", full_build)
        self.assertIn("### Step 9 - Save manifest", full_build)
        self.assertIn("Graph health check", full_build)
        self.assertIn("save_manifest(", full_build)

    def test_query_route_does_not_require_full_build_reference(self) -> None:
        """Existing-graph query는 query reference만 읽도록 dispatcher가 분리합니다."""
        entrypoint = GRAPHIFY_SKILL.read_text(encoding="utf-8")
        query_start = entrypoint.index("\n## For /graphify query\n")
        query_end = entrypoint.index("\n## For /graphify add and --watch\n")
        query_route = entrypoint[query_start:query_end]

        self.assertIn("references/query.md", query_route)
        self.assertNotIn("references/full-build.md", query_route)

    def test_full_build_uses_sibling_relative_references(self) -> None:
        """Moved runbook은 자신이 위치한 references directory에서 sibling을 찾습니다."""
        full_build = FULL_BUILD.read_text(encoding="utf-8")

        self.assertNotIn("`references/", full_build)
        for name in (
            "github-and-merge.md",
            "transcribe.md",
            "extraction-spec.md",
            "exports.md",
        ):
            self.assertIn(f"`{name}`", full_build)
            self.assertTrue((FULL_BUILD.parent / name).is_file())


if __name__ == "__main__":
    unittest.main()
