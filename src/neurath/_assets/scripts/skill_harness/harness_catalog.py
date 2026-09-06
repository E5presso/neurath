"""Canonical rule/skill metadata에서 Neurath harness index를 생성합니다."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from scripts.harness_frontmatter import (
    MarkdownFrontmatterError,
    parse_markdown_frontmatter,
)


class HarnessCatalogError(ValueError):
    """Canonical metadata가 deterministic catalog로 projection될 수 없을 때 발생합니다."""


@dataclass(frozen=True, slots=True)
class RuleCatalogEntry:
    """Rule source와 선언된 loading scope의 immutable projection입니다."""

    name: str
    """Rule file stem에서 파생한 stable name입니다."""

    title: str
    """Rule Markdown body의 첫 H1 title입니다."""

    injection: str
    """Frontmatter `paths` 유무로 파생한 `always` 또는 `path` scope입니다."""

    paths: tuple[str, ...]
    """Path-scoped rule의 canonical glob tuple입니다."""

    source_bytes: int
    """Frontmatter를 포함한 UTF-8 source 크기이며 host token이 아닙니다."""


@dataclass(frozen=True, slots=True)
class SkillCatalogEntry:
    """Skill routing metadata와 optional execution contract join입니다."""

    name: str
    """Skill frontmatter의 canonical name입니다."""

    description: str
    """Native host discovery에 노출되는 positive와 negative routing 설명입니다."""

    intent_class: str
    """Primary intent의 canonical object-action identity입니다."""

    input_authority: str
    """Skill 선택을 정당화하는 primary input authority입니다."""

    not_for: tuple[str, ...]
    """이 skill이 소유하지 않는 intent class tuple입니다."""

    user_invocable: bool
    """Skill이 direct user command surface에 노출되는지 나타냅니다."""

    contracted: bool
    """Execution contract와 exact name으로 join됐는지 나타냅니다."""

    entry_bytes: int
    """Selected SKILL.md 원문의 UTF-8 byte 수입니다."""

    description_bytes: int
    """Native discovery description의 UTF-8 byte 수입니다."""


@dataclass(frozen=True, slots=True)
class HarnessCatalog:
    """Canonical harness sources에서 파생된 정렬된 catalog입니다."""

    rules: tuple[RuleCatalogEntry, ...]
    """Rule frontmatter에서 파생한 canonical 정렬 projection입니다."""

    skills: tuple[SkillCatalogEntry, ...]
    """Skill frontmatter와 contract join에서 파생한 canonical 정렬 projection입니다."""

    uncontracted_skills: tuple[str, ...]
    """SKILL은 존재하지만 execution contract가 없는 skill name입니다."""

    orphan_contracts: tuple[str, ...]
    """Execution contract는 존재하지만 SKILL source가 없는 contract name입니다."""

    agents_bytes: int
    """AGENTS kernel의 UTF-8 source 크기입니다."""

    @classmethod
    def load(cls, repository_root: Path) -> HarnessCatalog:
        """Repository의 rule frontmatter, SKILL frontmatter, contracts를 읽습니다.

        Args:
            repository_root: Canonical `.agents` source를 포함한 repository root입니다.

        Returns:
            Rule, skill, contract join을 정렬한 immutable catalog입니다.

        Raises:
            HarnessCatalogError: Metadata 또는 contract join이 deterministic catalog를
                만들 수 없으면 발생합니다.
        """
        from scripts._neurath_paths import asset_path
        root = asset_path(repository_root.resolve(), Path(".agents")).parent
        contract_names = cls._contract_names(root / ".agents/skills/contracts.json")
        rules = tuple(
            cls._rule_entry(path) for path in sorted((root / ".agents/rules").glob("*.md"))
        )
        skills = tuple(
            cls._skill_entry(path, contract_names)
            for path in sorted((root / ".agents/skills").glob("*/SKILL.md"))
        )
        skill_names = tuple(item.name for item in skills)
        if len(skill_names) != len(set(skill_names)):
            raise HarnessCatalogError("skill names must be unique")
        skill_name_set = set(skill_names)
        return cls(
            rules=rules,
            skills=skills,
            uncontracted_skills=tuple(sorted(skill_name_set.difference(contract_names))),
            orphan_contracts=tuple(sorted(contract_names.difference(skill_name_set))),
            agents_bytes=len(__import__("neurath.install.projection", fromlist=["POLICY"]).POLICY.encode()),
        )

    @staticmethod
    def _contract_names(path: Path) -> set[str]:
        try:
            payload: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise HarnessCatalogError("contracts.json must be readable valid JSON") from error
        if not isinstance(payload, Mapping):
            raise HarnessCatalogError("contracts.json must be an object")
        raw_skills = payload.get("skills")
        if not isinstance(raw_skills, Mapping) or any(
            not isinstance(name, str) for name in raw_skills
        ):
            raise HarnessCatalogError("contracts.json skills must be a string-keyed object")
        return {str(name) for name in raw_skills}

    @classmethod
    def _rule_entry(cls, path: Path) -> RuleCatalogEntry:
        text = path.read_text(encoding="utf-8")
        try:
            parsed = parse_markdown_frontmatter(text)
            raw_paths = parsed.paths
        except MarkdownFrontmatterError as error:
            raise HarnessCatalogError(f"rule paths must be a string list: {path}") from error
        return RuleCatalogEntry(
            name=path.stem,
            title=cls._title(parsed.body, path),
            injection="path" if raw_paths else "always",
            paths=raw_paths,
            source_bytes=len(text.encode("utf-8")),
        )

    @classmethod
    def _skill_entry(
        cls,
        path: Path,
        contract_names: set[str],
    ) -> SkillCatalogEntry:
        try:
            metadata = parse_markdown_frontmatter(path.read_text(encoding="utf-8")).metadata
        except MarkdownFrontmatterError as error:
            raise HarnessCatalogError(f"invalid skill frontmatter: {path}") from error
        name = cls._required_text(metadata, "name", path)
        description = cls._required_text(metadata, "description", path)
        intent_class = cls._required_text(metadata, "intent-class", path)
        input_authority = cls._required_text(metadata, "input-authority", path)
        not_for = metadata.get("not-for")
        if not isinstance(not_for, tuple) or any(
            not isinstance(item, str) or not item for item in not_for
        ):
            raise HarnessCatalogError(f"not-for must be a string list: {path}")
        user_invocable = metadata.get("user-invocable")
        if not isinstance(user_invocable, bool):
            raise HarnessCatalogError(f"user-invocable must be boolean: {path}")
        return SkillCatalogEntry(
            name=name,
            description=description,
            intent_class=intent_class,
            input_authority=input_authority,
            not_for=not_for,
            user_invocable=user_invocable,
            contracted=name in contract_names,
            entry_bytes=len(path.read_bytes()),
            description_bytes=len(description.encode("utf-8")),
        )

    @staticmethod
    def _required_text(metadata: Mapping[str, object], key: str, path: Path) -> str:
        value = metadata.get(key)
        if not isinstance(value, str) or not value.strip():
            raise HarnessCatalogError(f"{key} must be non-empty text: {path}")
        return value.strip()

    @staticmethod
    def _title(body: str, path: Path) -> str:
        for line in body.splitlines():
            if line.startswith("# ") and line[2:].strip():
                return line[2:].strip()
        raise HarnessCatalogError(f"rule requires an H1 title: {path}")

    @property
    def shared_rule_bytes(self) -> int:
        """Claude native rule 선언과 공유 kernel의 source proxy 합을 계산합니다.

        Returns:
            No-path rules와 AGENTS의 UTF-8 byte 합이며 actual host token이 아닙니다.
        """
        return self.agents_bytes + sum(
            item.source_bytes for item in self.rules if item.injection == "always"
        )

    @property
    def codex_base_bytes(self) -> int:
        """Codex가 명시적으로 읽는 일반 작업 입구의 source 크기를 계산합니다.

        Returns:
            AGENTS와 charter source의 합이며 모든 rule의 자동 주입을 가정하지 않습니다.
        """
        return self.agents_bytes + sum(
            item.source_bytes for item in self.rules if item.name == "charter"
        )

    @property
    def discovery_description_bytes(self) -> int:
        """Skill entry 본문과 분리한 native description source 합을 계산합니다.

        Returns:
            Name, path, host wrapper를 제외한 UTF-8 description byte 합입니다.
        """
        return sum(item.description_bytes for item in self.skills)

    def render_rule_index(self) -> str:
        """Planned-path lookup용 compact rule projection을 렌더링합니다.

        Returns:
            Skill routing 진단을 싣지 않은 canonical rule navigation Markdown입니다.
        """
        lines = [
            "<!-- Generated by scripts.skill_harness.harness_catalog; do not edit. -->",
            "# Neurath Harness Rule Index",
            "",
            "이 문서는 planned-path lookup용 canonical rule metadata projection입니다.",
            "Skill·routing·contract 진단은 `.agents/HARNESS_AUDIT.md`에 있으며 두 문서 모두",
            "`uv run python -m scripts.skill_harness.harness_catalog --check`로 drift를 검사합니다.",
            "",
            f"- Rules: {len(self.rules)}",
            f"- No-path source rules: {sum(item.injection == 'always' for item in self.rules)}",
            f"- Path rules: {sum(item.injection == 'path' for item in self.rules)}",
            "",
            "## Rules",
            "",
            "| Rule | Title | Source scope | Paths |",
            "|---|---|---|---|",
        ]
        for item in self.rules:
            paths = "<br>".join(f"`{self._cell(path)}`" for path in item.paths) or "-"
            lines.append(
                f"| [`{item.name}`](rules/{item.name}.md) | {self._cell(item.title)} | "
                f"`{item.injection}` | {paths} |"
            )
        lines.append("")
        return "\n".join(lines)

    def render_audit_index(self) -> str:
        """Rule·skill·routing·contract join의 full audit projection을 렌더링합니다.

        Returns:
            Canonical metadata capability를 생략하지 않은 audit Markdown입니다.
        """
        lines = [
            "<!-- Generated by scripts.skill_harness.harness_catalog; do not edit. -->",
            "# Neurath Harness Audit",
            "",
            "이 문서는 canonical rule/skill metadata와 contract join의 full audit projection입니다.",
            "권한의 정본이 아니며 ordinary planned-path lookup에는 `.agents/HARNESS_INDEX.md`를",
            "사용합니다. 두 문서 모두",
            "`uv run python -m scripts.skill_harness.harness_catalog --check`로 drift를 검사합니다.",
            "",
            f"- Rules: {len(self.rules)}",
            f"- Skills: {len(self.skills)}",
            f"- Contracted skills: {sum(item.contracted for item in self.skills)}",
            "",
            "## Rules",
            "",
            "| Rule | Title | Source scope | Paths |",
            "|---|---|---|---|",
        ]
        for item in self.rules:
            paths = "<br>".join(f"`{self._cell(path)}`" for path in item.paths) or "-"
            lines.append(
                f"| [`{item.name}`](rules/{item.name}.md) | {self._cell(item.title)} | "
                f"`{item.injection}` | {paths} |"
            )
        lines.extend([
            "",
            "## Skills",
            "",
            "| Skill | User | Intent class | Input authority | Not for | Contract | Description |",
            "|---|---:|---|---|---|---|---|",
        ])
        for item in self.skills:
            contract = "contracted" if item.contracted else "uncontracted"
            not_for = "<br>".join(f"`{self._cell(value)}`" for value in item.not_for)
            lines.append(
                f"| [`{item.name}`](skills/{item.name}/SKILL.md) | "
                f"{'yes' if item.user_invocable else 'no'} | `{item.intent_class}` | "
                f"`{item.input_authority}` | {not_for or '-'} | `{contract}` | "
                f"{self._cell(item.description)} |"
            )
        lines.extend([
            "",
            "## Prompt source measurements",
            "",
            "UTF-8 source bytes이며 actual host loaded tokens는 `UNAVAILABLE`입니다.",
            "Claude native와 Codex explicit은 repository의 loading 선언이며 host 실측이 아닙니다.",
            "Skill entry 외 필수 reference, path rule, hook protocol, name/path wrapper는",
            "선택 경로에 따라 추가되므로 아래 값을 완전한 prompt 비용으로 합산하지 않습니다.",
            "",
            "| Surface | Declared acquisition | Source bytes |",
            "|---|---|---:|",
            f"| Neurath policy + common rules | Claude native source proxy | {self.shared_rule_bytes} |",
            f"| Neurath policy + behavioral | Codex explicit base | {self.codex_base_bytes} |",
            f"| Skill descriptions | Native discovery source | {self.discovery_description_bytes} |",
            "",
            "## Skill entry measurements",
            "",
            "| Skill | Entry bytes | Description bytes | Codex base + entry bytes |",
            "|---|---:|---:|---:|",
        ])
        for item in self.skills:
            lines.append(
                f"| `{item.name}` | {item.entry_bytes} | {item.description_bytes} | "
                f"{self.codex_base_bytes + item.entry_bytes} |"
            )
        lines.extend([
            "",
            "## Join diagnostics",
            "",
            "- Uncontracted skills: " + self._names(self.uncontracted_skills),
            "- Orphan contracts: " + self._names(self.orphan_contracts),
            "",
        ])
        return "\n".join(lines)

    @staticmethod
    def _cell(value: str) -> str:
        return " ".join(value.split()).replace("|", "\\|")

    @staticmethod
    def _names(values: tuple[str, ...]) -> str:
        return ", ".join(f"`{value}`" for value in values) if values else "none"


def main() -> None:
    """Generated navigation/audit projection을 쓰거나 exact 비교합니다.

    Raises:
        SystemExit: Generated artifact가 없거나 canonical render와 다르면 발생합니다.
    """
    parser = argparse.ArgumentParser(description="Render the Neurath harness catalog.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    catalog = HarnessCatalog.load(root)
    artifacts = {
        root / ".agents/HARNESS_INDEX.md": catalog.render_rule_index(),
        root / ".agents/HARNESS_AUDIT.md": catalog.render_audit_index(),
    }
    if args.write:
        for target, rendered in artifacts.items():
            target.write_text(rendered, encoding="utf-8")
        return
    for target, rendered in artifacts.items():
        try:
            current = target.read_text(encoding="utf-8")
        except OSError as error:
            raise SystemExit(f"missing generated harness artifact: {target}") from error
        if current != rendered:
            raise SystemExit(f"generated harness artifact is stale: {target}; run with --write")


if __name__ == "__main__":
    main()
