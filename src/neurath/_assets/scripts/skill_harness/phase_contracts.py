"""Load executable skill contracts from the installed asset catalog."""

from pathlib import Path
import json
from scripts._neurath_paths import asset_path
from scripts.skill_harness.phase_models import PhaseContract, SkillContract, PhaseRunnerError

CONTRACTS_PATH = Path(".agents/skills/contracts.json")


def read_skill_contracts(path: Path) -> dict[str, dict[str, object]]:
    """Decode the shared catalog shape before validation or phase execution."""
    parsed = json.loads(path.read_text())
    if not isinstance(parsed, dict) or not isinstance(parsed.get("skills"), dict):
        raise ValueError("contracts must define a skills object")
    contracts = parsed["skills"]
    if any(not isinstance(k, str) or not isinstance(v, dict) for k, v in contracts.items()):
        raise ValueError("every skill contract must be a named object")
    return contracts


class SkillContractRepository:

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    @property
    def root(self) -> Path:
        """Contract와 process state가 속한 repository root를 반환합니다.

        Returns:
            정규화된 repository root입니다.
        """
        return self._root

    def get(self, skill_name: str) -> SkillContract:
        raw_contracts = read_skill_contracts(asset_path(self._root, CONTRACTS_PATH))
        raw_contract = raw_contracts.get(skill_name)
        if raw_contract is None:
            raise PhaseRunnerError("UNKNOWN_SKILL", f"{skill_name} is not a contracted skill")
        return self._parse_skill_contract(skill_name, raw_contract)

    def _parse_skill_contract(
        self,
        skill_name: str,
        raw_contract: dict[str, object],
    ) -> SkillContract:
        terminal_states = tuple(self._string_list(raw_contract.get("terminal_states")))
        if not terminal_states:
            raise PhaseRunnerError("CONTRACT_INVALID", f"{skill_name} has no terminal states")

        raw_phases = raw_contract.get("phase_contracts")
        if not isinstance(raw_phases, list):
            raise PhaseRunnerError("CONTRACT_INVALID", f"{skill_name} has no phase contracts")
        phases = tuple(self._parse_phase_contract(item) for item in raw_phases)
        adaptive_control = raw_contract.get("adaptive_control")
        if adaptive_control not in {None, "not-applicable", "required"}:
            raise PhaseRunnerError(
                "CONTRACT_INVALID",
                (f"{skill_name} adaptive_control must be required or not-applicable when present"),
            )
        return SkillContract(
            skill_name,
            terminal_states,
            phases,
            adaptive_control_required=adaptive_control == "required",
        )

    def _parse_phase_contract(self, raw_phase: object) -> PhaseContract:
        if not isinstance(raw_phase, dict):
            raise PhaseRunnerError("CONTRACT_INVALID", "phase contract must be an object")
        phase_id = raw_phase.get("id")
        name = raw_phase.get("name")
        min_evidence_count = raw_phase.get("min_evidence_count")
        if not isinstance(phase_id, int):
            raise PhaseRunnerError("CONTRACT_INVALID", "phase id must be an integer")
        if not isinstance(name, str) or not name:
            raise PhaseRunnerError("CONTRACT_INVALID", "phase name must be a non-empty string")
        if not isinstance(min_evidence_count, int):
            raise PhaseRunnerError(
                "CONTRACT_INVALID",
                "phase min_evidence_count must be an integer",
            )
        return PhaseContract(
            id=phase_id,
            name=name,
            min_evidence_count=min_evidence_count,
            required_evidence=tuple(self._string_list(raw_phase.get("required_evidence"))),
            phase_file=self._optional_string(raw_phase.get("phase_file")),
            evidence_patterns=self._string_dict(raw_phase.get("evidence_patterns")),
        )

    def _string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]

    def _string_dict(self, value: object) -> dict[str, str] | None:
        if not isinstance(value, dict):
            return None
        parsed = {
            key: item
            for key, item in value.items()
            if isinstance(key, str) and isinstance(item, str)
        }
        return parsed or None

    def _optional_string(self, value: object) -> str | None:
        if isinstance(value, str) and value:
            return value
        return None
