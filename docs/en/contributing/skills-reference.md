# Ordered skill contracts

[한국어](../../ko/contributing/skills-reference.md) · [Core contract](core-v2-spec.md)

`core-skills.json` defines the distributed skills and ordered phases. Starting a skill snapshots its definition into the Task. `phase_complete` only accepts the current phase and its required outcomes. Nested skills must be declared and return to the unfinished parent phase. Conditional branches are explicit definitions; recovery records another attempt and uses the declared restart point. Skill completion and user Task acceptance are separate requirements.

Implementation references:

- [_assets/.agents/skills/core-skills.json](../../../src/neurath/_assets/.agents/skills/core-skills.json)
- [core/skills.py](../../../src/neurath/core/skills.py)
- [core/domain.py](../../../src/neurath/core/domain.py)

[Validation](validation.md) distinguishes source tests, installed protocol checks and actual host behavior.
