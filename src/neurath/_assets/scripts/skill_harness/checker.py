"""Validate kit skill routing and phase/evidence contracts without target policies."""
import json
import re
from pathlib import Path
from scripts._neurath_paths import asset_path
from scripts.harness_frontmatter import parse_markdown_frontmatter
from scripts.skill_harness.violation import Violation

CONTRACTS_PATH = Path(".agents/skills/contracts.json")
REVIEW_CODE_ROWS = (
    ("C01", "architecture-boundary", "critical"),
    ("C02", "type-discipline", "warning"),
    ("C03", "yagni", "warning"),
    ("C04", "domain-boundary", "critical"),
    ("C05", "naming", "warning"),
    ("C06", "test-gate", "critical"),
    ("C07", "readability", "warning"),
    ("C08", "api-contract", "warning"),
    ("C09", "persistence", "warning"),
    ("C10", "transaction-integrity", "critical"),
    ("C11", "pattern-consistency", "warning"),
    ("C12", "defensive-helper", "warning"),
    ("C13", "operations-consistency", "warning"),
    ("C14", "spec-completeness", "critical"),
)

RESOURCE_REFERENCE_PATTERN = re.compile(r"[\w./-]+\.md")
STATEFUL_CONTROL_COMMAND_PATTERN = re.compile(
    r"(?:"
    r"uv run python -m scripts\.skill_harness\.phase_runner(?=\s+\S)|"
    r"(?:uv run python|python3) -m scripts\.agent_harness\.state_cli(?=\s+\S)|"
    r"uv run python -m scripts\.agent_harness\.harness_incident(?=\s+\S)|"
    r"uv run python -m scripts\.agent_harness\.harness_maintenance(?=\s+\S)|"
    r"uv run python -m scripts\.agent_harness\.verification_runner(?=\s+\S)|"
    r"(?:"
    r"\.agents/skills/process-ticket/scripts/(?:delegate_state|process_state_evidence|merge_cleanup)\.py(?=\s+\S)|"
    r"\.agents/skills/process-ticket/scripts/assert_worktree_isolation\.sh(?=\s+\S)|"
    r"\.agents/skills/monitor-pr/scripts/(?:acknowledge_event|local_pr_monitor)\.py(?=\s+\S)|"
    r"\.agents/skills/pr-review/scripts/publish_final_review\.py(?=\s+\S)"
    r")"
    r")"
)

class SkillHarnessChecker:
    def __init__(self, root: Path):
        self._root = root.resolve()

    def _contracts(self, path):
        parsed = json.loads(path.read_text())
        if not isinstance(parsed, dict) or not isinstance(parsed.get("skills"), dict):
            raise ValueError("contracts must define a skills object")
        contracts = parsed["skills"]
        if any(not isinstance(k, str) or not isinstance(v, dict) for k, v in contracts.items()):
            raise ValueError("every skill contract must be a named object")
        return contracts

    def check(self):
        from scripts.agent_harness.checker import AgentHarnessChecker
        violations = [Violation(v.code, v.path, v.message) for v in AgentHarnessChecker(self._root).check()]
        path = asset_path(self._root, CONTRACTS_PATH)
        try:
            contracts = self._contracts(path)
        except (OSError, ValueError, TypeError) as error:
            return [*violations, Violation("NS001", path, str(error))]
        directory = path.parent
        actual = {p.parent.name for p in directory.glob("*/SKILL.md")}
        if set(contracts) != actual - {"explain-code", "graphify"}:
            violations.append(Violation("NS002", path, "skill inventory and contracts differ"))
        for name, contract in contracts.items():
            skill = directory / name / "SKILL.md"
            try:
                self._validate(skill, name, contract)
            except (OSError, ValueError, TypeError, KeyError) as error:
                violations.append(Violation("NS003", skill, str(error)))
        return violations

    def _validate(self, skill, name, contract):
        text = skill.read_text()
        metadata = parse_markdown_frontmatter(text).metadata
        for field in ("name", "description", "intent-class", "input-authority", "not-for", "user-invocable"):
            if field not in metadata:
                raise ValueError(f"missing routing metadata: {field}")
        if metadata["name"] != name:
            raise ValueError("skill identity differs from contract")
        from scripts.agent_harness.adaptive_policy import ADAPTIVE_CONTROL_OPERATIONAL_EXEMPT_WORKFLOW_KINDS
        operational = name in ADAPTIVE_CONTROL_OPERATIONAL_EXEMPT_WORKFLOW_KINDS
        expected_semantics = "operational-projection" if operational else "semantic"
        expected_adaptive = "not-applicable" if operational else "required"
        if contract.get("workflow_semantics") != expected_semantics or contract.get("adaptive_control") != expected_adaptive:
            raise ValueError("workflow semantics and adaptive admission policy differ")
        terminals = contract["terminal_states"]
        if not isinstance(terminals, list) or not terminals or len(set(terminals)) != len(terminals):
            raise ValueError("terminal states must be unique and nonempty")
        phases = contract["phase_contracts"]
        if not isinstance(phases, list) or not phases:
            raise ValueError("phase contracts must be nonempty")
        names = set()
        start = phases[0]["id"]
        if start not in (0, 1):
            raise ValueError("phases must start at zero or one")
        for index, phase in enumerate(phases, start):
            if phase["id"] != index or phase["name"] in names:
                raise ValueError("phases must have sequential ids and unique names")
            names.add(phase["name"])
            evidence = phase.get("required_evidence", [])
            if not isinstance(evidence, list) or len(set(evidence)) != len(evidence):
                raise ValueError("phase evidence must be a unique list")
            count = phase.get("min_evidence_count", 0)
            if type(count) is not int or count < 1 or not evidence or count < len(evidence):
                raise ValueError("phase evidence count is smaller than its requirements")
            if "phase_file" in phase:
                self._resource(skill, phase["phase_file"]).read_text()
        for fragment in contract.get("required_fragments", []):
            if not isinstance(fragment, str) or fragment not in text:
                raise ValueError(f"missing required instruction: {fragment!r}")
        offset = 0
        for fragment in contract.get("ordered_fragments", []):
            index = text.find(fragment, offset)
            if index < 0:
                raise ValueError(f"missing or unordered instruction: {fragment!r}")
            offset = index + len(fragment)
        for relative, fragments in contract.get("required_resource_fragments", {}).items():
            content = self._resource(skill, relative).read_text()
            if any(fragment not in content for fragment in fragments):
                raise ValueError(f"missing required resource instruction: {relative}")

    def _resource(self, skill, relative):
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("resource must stay inside the skill")
        result = skill.parent / path
        if not result.resolve().is_relative_to(skill.parent.resolve()) or result.is_symlink():
            raise ValueError("resource escapes skill directory")
        return result

    def _stateful_markdown_fragments(self, text: str) -> tuple[str, ...]:
        """Markdown code spans/blocks에서 agent-facing stateful command만 추출합니다."""
        fragments: list[str] = []
        fenced_spans: list[tuple[int, int]] = []
        for match in re.finditer(
            r"(?ms)^[ \t]*```(?P<info>[^\n]*)\n(?P<body>.*?)^[ \t]*```[ \t]*$",
            text,
        ):
            fenced_spans.append(match.span())
            if match.group("info").strip().casefold().split(maxsplit=1)[:1] == ["markdown"]:
                continue
            block = match.group("body")
            for line in block.splitlines():
                selected = line.strip()
                if STATEFUL_CONTROL_COMMAND_PATTERN.search(selected) is not None:
                    fragments.append(selected)
            if "\n" in block and STATEFUL_CONTROL_COMMAND_PATTERN.search(block) is not None:
                stateful_lines = [
                    line
                    for line in block.splitlines()
                    if STATEFUL_CONTROL_COMMAND_PATTERN.search(line) is not None
                ]
                if any(line.rstrip().endswith("\\") for line in stateful_lines):
                    fragments.append(block.strip())

        inline_source = text
        for start, end in reversed(fenced_spans):
            inline_source = inline_source[:start] + (" " * (end - start)) + inline_source[end:]
        for match in re.finditer(r"`([^`]+)`", inline_source, re.DOTALL):
            selected = match.group(1).strip()
            if STATEFUL_CONTROL_COMMAND_PATTERN.search(selected) is not None:
                fragments.append(selected)
        return tuple(dict.fromkeys(fragments))

    def _check_prompt_loading_owners(self) -> list[Violation]:
        """조건부 입구가 현재 repository의 canonical 원문에 도달하는지 검사합니다.

        Returns:
            Owner 누락, 끊어진 pointer, 외부 symlink, stable identity 누락의 위반입니다.
        """
        owner_specs = (
            (
                ".agents/rules/behavioral.md",
                ".agents/skills/evaluate-harness/references/convergence.md",
                "rule_id: harness-evaluation-convergence-v1",
            ),
            (
                ".agents/rules/evaluation-loops.md",
                ".agents/skills/evaluate-harness/references/convergence.md",
                "rule_id: harness-evaluation-convergence-v1",
            ),
            (
                ".agents/skills/evaluate-harness/SKILL.md",
                ".agents/skills/evaluate-harness/references/convergence.md",
                "rule_id: harness-evaluation-convergence-v1",
            ),
            (
                ".agents/skills/evaluate-harness/SKILL.md",
                ".agents/skills/evaluate-harness/references/verification-evidence.md",
                "rule_id: harness-evaluation-verification-v1",
            ),
        )
        violations: list[Violation] = []
        root = self._root.resolve()
        for reader_name, owner_name, marker in owner_specs:
            reader = root / reader_name
            if not reader.is_file():
                continue
            owner = (root / owner_name).resolve()
            if not owner.is_relative_to(root) or not owner.is_file():
                violations.append(
                    Violation(
                        code="DH039",
                        path=reader,
                        message=(
                            f"canonical prompt owner is missing or outside repository: {owner_name}"
                        ),
                    )
                )
                continue
            references = RESOURCE_REFERENCE_PATTERN.findall(reader.read_text(encoding="utf-8"))
            reachable = any(
                owner
                in (
                    (root / reference).resolve(),
                    (reader.parent / reference).resolve(),
                )
                for reference in references
            )
            if not reachable or marker not in owner.read_text(encoding="utf-8"):
                violations.append(
                    Violation(
                        code="DH039",
                        path=reader,
                        message=(
                            "canonical prompt owner pointer or stable identity is missing: "
                            f"{owner_name}"
                        ),
                    )
                )
        return violations

    def _reachable_resources(self, skill_file: Path) -> set[Path]:
        skill_root = skill_file.parent
        reachable: set[Path] = set()
        queue = [skill_file]
        seen: set[Path] = set()
        while queue:
            current = queue.pop(0)
            if current in seen or not current.exists():
                continue
            seen.add(current)
            text = current.read_text(encoding="utf-8")
            for raw_reference in RESOURCE_REFERENCE_PATTERN.findall(text):
                resolved = self._resolve_skill_resource(skill_root, current.parent, raw_reference)
                if resolved is None or resolved in seen:
                    continue
                reachable.add(resolved)
                queue.append(resolved)
        return reachable

    def _resolve_skill_resource(
        self,
        skill_root: Path,
        current_parent: Path,
        raw_reference: str,
    ) -> Path | None:
        # `RESOURCE_REFERENCE_PATTERN`은 trailing 문장부호를 포함하지 않습니다. Leading
        # dot은 `.agents/...` repository-relative identity의 일부이므로 절대 제거하지
        # 않습니다.
        normalized = raw_reference.strip("`,;:()[]")
        candidates = [
            skill_root / normalized,
            current_parent / normalized,
            self._root / normalized,
        ]
        for candidate in candidates:
            resolved = candidate.resolve()
            try:
                resolved.relative_to(skill_root.resolve())
            except ValueError:
                continue
            if resolved.exists() and resolved.suffix == ".md":
                return resolved
        return None
