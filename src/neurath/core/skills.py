"""Read the distributed phase definitions directly into immutable Task snapshots."""

import json
from hashlib import sha256
from pathlib import Path

from neurath.core.codec import encode
from neurath.core.domain import Condition, CoreError, Phase, Skill, require
from neurath.resources import BUNDLE


def load_skills(path=None):
    path = Path(path) if path is not None else BUNDLE / ".agents/skills/core-skills.json"
    try:
        catalog = json.loads(path.read_text())
        require(
            set(catalog) == {"schema", "skills"} and catalog["schema"] == 1, "skill-catalog-schema"
        )
        definitions = catalog["skills"]
        require(isinstance(definitions, dict), "skill-catalog-schema")
        result = {}
        for identifier, value in definitions.items():
            require(
                set(value) <= {"source", "phases", "acceptance_restart_from"}, "skill-definition"
            )
            phases = []
            for phase in value["phases"]:
                require(
                    set(phase)
                    <= {
                        "id",
                        "requires",
                        "effects",
                        "subskills",
                        "restart_from",
                        "file",
                        "choices",
                    },
                    "skill-definition",
                )
                conditions = []
                for item in phase["requires"]:
                    require(
                        set(item)
                        <= {"id", "kinds", "subject_key", "expected_pass", "operation", "when"},
                        "condition-definition",
                    )
                    conditions.append(
                        Condition(
                            item["id"],
                            frozenset(item["kinds"]),
                            item.get("subject_key"),
                            item.get("expected_pass", True),
                            item.get("operation"),
                            None if item.get("when") is None else tuple(item["when"]),
                        )
                    )
                children = frozenset(phase.get("subskills", []))
                require(children <= set(definitions), "subskill-missing")
                phases.append(
                    Phase(
                        phase["id"],
                        tuple(conditions),
                        frozenset(phase.get("effects", ())),
                        phase.get("restart_from"),
                        children,
                        tuple((key, tuple(values)) for key, values in phase.get("choices", [])),
                    )
                )
            version = sha256(encode(value).encode()).hexdigest()
            result[identifier] = Skill(
                identifier, version, tuple(phases), value.get("acceptance_restart_from")
            )

        def visit(identifier, ancestors):
            require(identifier not in ancestors, "subskill-cycle")
            for phase in result[identifier].phases:
                for child in phase.subskills:
                    visit(child, ancestors | {identifier})

        for identifier in result:
            visit(identifier, set())
        return result
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise CoreError("skill-catalog-invalid") from error
