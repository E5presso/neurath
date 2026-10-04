"""One explicit representation of core work; no legacy model or executable payload."""

import json
from dataclasses import asdict

from neurath.core.domain import (
    Assignment,
    Attempt,
    Condition,
    CoreError,
    Phase,
    PhaseCompletion,
    Skill,
    SkillRun,
    Task,
)


def encode(value):
    def default(item):
        if isinstance(item, (set, frozenset)):
            return sorted(item)
        return asdict(item)

    return json.dumps(
        value,
        default=default,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def condition(value):
    return Condition(
        value["id"],
        frozenset(value["kinds"]),
        value.get("subject_key"),
        value.get("expected_pass", True),
        value.get("operation"),
        None if value.get("when") is None else tuple(value["when"]),
    )


def skill(value):
    return Skill(
        value["id"],
        value["version"],
        tuple(
            Phase(
                p["id"],
                tuple(condition(c) for c in p["requires"]),
                frozenset(p["effects"]),
                p.get("restart_from"),
                frozenset(p.get("subskills", [])),
                tuple((key, tuple(values)) for key, values in p.get("choices", [])),
            )
            for p in value["phases"]
        ),
        value.get("acceptance_restart_from"),
    )


def completion(value):
    return PhaseCompletion(
        value["phase_id"],
        tuple((key, tuple(ids)) for key, ids in value["outcomes"]),
        tuple(tuple(pair) for pair in value["inputs"]),
    )


def decode_task(document):
    try:
        value = json.loads(document)
        value["instruction_sources"] = tuple(value["instruction_sources"])
        value["acceptance"] = tuple(condition(c) for c in value["acceptance"])
        value["skill_runs"] = tuple(
            SkillRun(
                skill(run["skill"]),
                tuple(completion(c) for c in run["completions"]),
                run["attempt"],
                tuple(
                    Attempt(
                        a["number"],
                        tuple(completion(c) for c in a["completions"]),
                        a["failure_source"],
                        None if a.get("changed_inputs") is None else tuple(a["changed_inputs"]),
                    )
                    for a in run["history"]
                ),
                run.get("parent_index"),
            )
            for run in value["skill_runs"]
        )
        value["assignments"] = tuple(Assignment(**a) for a in value["assignments"])
        value["attempts"] = tuple(tuple(item) for item in value["attempts"])
        value["completion_evidence"] = tuple(value["completion_evidence"])
        value["implementation_actors"] = tuple(value["implementation_actors"])
        value["dependencies"] = tuple(value.get("dependencies", ()))
        return Task(**value)
    except (KeyError, TypeError, ValueError) as error:
        raise CoreError("invalid-task-record") from error
