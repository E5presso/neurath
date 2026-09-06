"""Canonical harness sources에서 생성되는 catalog projection을 검증합니다."""

from pathlib import Path
from unittest import TestCase

from scripts.skill_harness.harness_catalog import HarnessCatalog


class HarnessCatalogTest(TestCase):
    """수동 목록이 아니라 rule/skill metadata가 index를 결정합니다."""

    def setUp(self) -> None:
        """현재 checkout의 canonical harness root를 준비합니다."""
        self.root = Path(__file__).resolve().parents[3]

    def test_catalog_derives_rule_scope_and_all_skill_contract_coverage(self) -> None:
        """Frontmatter scope와 optional contract join을 누락 없이 projection합니다."""
        catalog = HarnessCatalog.load(self.root)
        rules = {item.name: item for item in catalog.rules}
        skills = {item.name: item for item in catalog.skills}

        self.assertEqual(8, len(rules))
        self.assertEqual(31, len(skills))
        self.assertEqual("path", rules["worktree-isolation"].injection)
        self.assertIn(".agents/worktrees/**", rules["worktree-isolation"].paths)
        self.assertEqual("always", rules["behavioral"].injection)
        self.assertTrue(skills["optimize-harness"].contracted)
        self.assertEqual("harness-prompt.optimize", skills["optimize-harness"].intent_class)
        self.assertEqual(
            "repository-prompt-surface",
            skills["optimize-harness"].input_authority,
        )
        self.assertIn(
            "personal-memory-pattern.promote",
            skills["optimize-harness"].not_for,
        )
        self.assertTrue(skills["optimize-harness"].user_invocable)
        self.assertTrue(skills["explore-ui"].contracted)
        self.assertEqual("product-ui.art-direct", skills["explore-ui"].intent_class)
        self.assertEqual("user-product-intent", skills["explore-ui"].input_authority)
        self.assertTrue(skills["sync-design"].contracted)
        self.assertEqual("product-ui.design-mirror-sync", skills["sync-design"].intent_class)
        self.assertTrue(skills["implement-ui"].contracted)
        self.assertEqual(
            "product-ui.approved-design-implement",
            skills["implement-ui"].intent_class,
        )
        self.assertTrue(skills["review-ui"].contracted)
        self.assertEqual("product-ui.roundtrip-review", skills["review-ui"].intent_class)
        self.assertFalse(skills["explain-code"].contracted)
        self.assertFalse(skills["graphify"].contracted)
        self.assertEqual(("explain-code", "graphify"), catalog.uncontracted_skills)
        self.assertEqual((), catalog.orphan_contracts)

    def test_committed_navigation_and_audit_indexes_are_exact_projections(self) -> None:
        """Compact rule lookup과 full audit artifact는 각 canonical render와 일치합니다."""
        catalog = HarnessCatalog.load(self.root)
        navigation = (self.root / ".agents/HARNESS_INDEX.md").read_text(encoding="utf-8")
        audit = (self.root / ".agents/HARNESS_AUDIT.md").read_text(encoding="utf-8")

        self.assertEqual(catalog.render_rule_index(), navigation)
        self.assertEqual(catalog.render_audit_index(), audit)
        self.assertIn("## Rules", navigation)
        self.assertNotIn("## Skills", navigation)
        self.assertNotIn("Join diagnostics", navigation)
        self.assertIn("## Skills", audit)
        self.assertIn("Join diagnostics", audit)
        self.assertNotIn("/onboarding", audit)
        self.assertNotIn("/review`", audit)
        self.assertNotIn("/update-ticket-status", audit)
        self.assertIn("uncontracted", audit)

    def test_rule_lookup_is_materially_smaller_without_losing_full_audit_diagnostics(self) -> None:
        """Ordinary lookup은 skill description을 싣지 않고 audit은 routing·join을 보존합니다."""
        catalog = HarnessCatalog.load(self.root)
        navigation = catalog.render_rule_index()
        audit = catalog.render_audit_index()
        optimize = next(item for item in catalog.skills if item.name == "optimize-harness")

        self.assertLess(len(navigation.encode("utf-8")), len(audit.encode("utf-8")))
        self.assertNotIn(optimize.description, navigation)
        self.assertIn(optimize.description, audit)
        self.assertIn("`harness-prompt.optimize`", audit)
        self.assertIn("`repository-prompt-surface`", audit)
        self.assertIn("Uncontracted skills: `explain-code`, `graphify`", audit)
        self.assertIn("Orphan contracts: none", audit)
