"""Host별 source 비용과 조건부 문서의 canonical owner를 검증합니다."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.skill_harness.checker import SkillHarnessChecker
from scripts.skill_harness.harness_catalog import HarnessCatalog

ROOT = Path(__file__).resolve().parents[3]
CONVERGENCE_OWNER = ".agents/skills/evaluate-harness/references/convergence.md"
BACKEND_OWNER = ".agents/rules/backend-structure.md"
VERIFICATION_OWNER = ".agents/skills/evaluate-harness/references/verification-evidence.md"


class PromptLoadingProjectionTest(TestCase):
    """Source 비용과 실제 host token을 구분하고 조건부 경로를 보존합니다."""

    def test_late_skill_details_have_reachable_owners_and_smaller_entries(self) -> None:
        """큰 스킬의 후반 실행 형식은 접근 가능한 원문을 보존하며 초기 읽기를 줄입니다."""
        for skill, reference, heading, limit in (
            ("review-code", "reporting.md", "## 보고 템플릿", 18_000),
            ("triage-comments", "reply-and-follow-up.md", "## 실행", 11_000),
            ("monitor-pr", "event-delivery.md", "## Delivery protocol", 10_200),
        ):
            with self.subTest(skill=skill):
                entry = ROOT / ".agents/skills" / skill / "SKILL.md"
                owner = entry.parent / "references" / reference
                self.assertTrue(owner.is_file())
                self.assertIn(f"references/{reference}", entry.read_text())
                self.assertIn(
                    owner.resolve(), SkillHarnessChecker(ROOT)._reachable_resources(entry)
                )
                self.assertIn(heading, owner.read_text())
                self.assertNotIn(heading + "\n", entry.read_text())
                self.assertLess(len(entry.read_bytes()), limit)
                if skill == "monitor-pr":
                    positions = [
                        owner.read_text().index(section)
                        for section in (
                            "## Delivery protocol",
                            "## Hook enforcement",
                            "## Review와 push",
                            "## Monitor Event Block",
                        )
                    ]
                    self.assertEqual(sorted(positions), positions)


    def test_skill_growth_changes_only_the_matching_source_measurement(self) -> None:
        """Entry나 description 증가는 base rule 비용으로 잘못 집계하지 않습니다."""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            skill_path = self._catalog_fixture(root)
            before = HarnessCatalog.load(root)
            entry = skill_path.read_text(encoding="utf-8")
            skill_path.write_text(entry + "\n추가 설명\n", encoding="utf-8")
            after_entry = HarnessCatalog.load(root)
            self.assertEqual(before.codex_base_bytes, after_entry.codex_base_bytes)
            self.assertEqual(before.shared_rule_bytes, after_entry.shared_rule_bytes)
            self.assertEqual(
                before.discovery_description_bytes,
                after_entry.discovery_description_bytes,
            )
            self.assertEqual(
                len("\n추가 설명\n".encode()),
                after_entry.skills[0].entry_bytes - before.skills[0].entry_bytes,
            )
            skill_path.write_text(
                entry.replace("original", "longer description"),
                encoding="utf-8",
            )
            after_description = HarnessCatalog.load(root)
            self.assertEqual(before.codex_base_bytes, after_description.codex_base_bytes)
            self.assertEqual(
                len("longer description") - len("original"),
                after_description.discovery_description_bytes - before.discovery_description_bytes,
            )




    def _catalog_fixture(self, root: Path) -> Path:
        """Source 성분 변화만 격리할 최소 valid catalog를 준비합니다.

        Args:
            root: 독립 임시 repository 경로입니다.

        Returns:
            Entry와 description을 변경할 skill source 경로입니다.
        """
        (root / ".agents/rules").mkdir(parents=True)
        (root / ".agents/skills/probe").mkdir(parents=True)
        (root / "AGENTS.md").write_text("# Kernel\n", encoding="utf-8")
        (root / ".agents/rules/behavioral.md").write_text("# Charter\n", encoding="utf-8")
        (root / ".agents/skills/contracts.json").write_text(
            json.dumps({"skills": {}}), encoding="utf-8"
        )
        path = root / ".agents/skills/probe/SKILL.md"
        path.write_text(
            "---\nname: probe\ndescription: original\nintent-class: source.inspect\n"
            "input-authority: repository-source\nnot-for: [source.mutate]\n"
            "user-invocable: true\n---\n# Probe\n",
            encoding="utf-8",
        )
        return path


class PromptOwnerBoundaryTest(TestCase):
    """문구 중복 대신 repository 안의 canonical owner 도달성을 검사합니다."""

    def test_reachable_owner_allows_code_and_markdown_pointer(self) -> None:
        """동일 owner를 가리키는 정상 Markdown 표현을 불필요하게 제한하지 않습니다."""
        for pointer in (
            f"`{CONVERGENCE_OWNER}`",
            f"[평가 수렴 계약]({CONVERGENCE_OWNER})",
        ):
            with self.subTest(pointer=pointer):
                self.assertEqual([], self._probe(pointer, "present"))

    def test_missing_canonical_owner_is_denied(self) -> None:
        """Pointer만 남기고 실제 계약을 지우면 검사를 통과하지 못합니다."""
        self.assertEqual(
            ["DH039"],
            self._probe(f"`{CONVERGENCE_OWNER}`", "missing"),
        )

    def test_unrelated_pointer_cannot_stand_in_for_the_owner(self) -> None:
        """다른 실제 문서를 읽는 것으로 수렴 계약 읽기를 대신하지 못합니다."""
        self.assertEqual(
            ["DH039"],
            self._probe("`.agents/rules/other.md`", "present"),
        )

    def test_symlink_outside_repository_is_not_a_canonical_owner(self) -> None:
        """동일 문자열이 repository 밖으로 나가는 symlink이면 거부합니다."""
        self.assertEqual(
            ["DH039"],
            self._probe(f"`{CONVERGENCE_OWNER}`", "external"),
        )

    def test_owner_without_stable_rule_identity_is_denied(self) -> None:
        """경로만 맞고 다른 문서로 교체된 owner를 marker로 구분합니다."""
        self.assertEqual(
            ["DH039"],
            self._probe(f"`{CONVERGENCE_OWNER}`", "unmarked"),
        )


    def _probe(self, pointer: str, owner_mode: str) -> list[str]:
        """독립 fixture에서 pointer와 owner 상태의 allow/deny 결과를 읽습니다.

        Args:
            pointer: Reader에 기록할 정상 또는 잘못된 reference입니다.
            owner_mode: 누락, identity 누락, 외부 symlink 반례의 종류입니다.

        Returns:
            Repository owner 검사에서 나온 실제 violation code 목록입니다.
        """
        with TemporaryDirectory() as directory, TemporaryDirectory() as external:
            root = Path(directory)
            (root / ".agents/rules").mkdir(parents=True)
            (root / ".agents/rules/behavioral.md").write_text(
                f"# Charter\n평가 전에 {pointer}를 읽습니다.\n",
                encoding="utf-8",
            )
            (root / ".agents/rules/other.md").write_text("# Other\n", encoding="utf-8")
            owner = root / CONVERGENCE_OWNER
            owner.parent.mkdir(parents=True)
            if owner_mode != "missing":
                owner.write_text(
                    "# 평가 수렴\n\nrule_id: harness-evaluation-convergence-v1\n",
                    encoding="utf-8",
                )
            if owner_mode == "unmarked":
                owner.write_text("# Other contract\n", encoding="utf-8")
            if owner_mode == "external":
                outside = Path(external) / "owner.md"
                outside.write_text(owner.read_text(encoding="utf-8"), encoding="utf-8")
                owner.unlink()
                owner.symlink_to(outside)
            return [item.code for item in SkillHarnessChecker(root)._check_prompt_loading_owners()]
