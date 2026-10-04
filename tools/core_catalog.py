"""Render the skill/rule index from the single replacement-core catalog."""

from pathlib import Path


def render(bundle: Path):
    from neurath.core.skills import load_skills

    skills = load_skills(bundle / ".agents/skills/core-skills.json")
    rules = sorted((bundle / ".agents/rules").glob("*"))
    index = [
        "# Harness Index",
        "",
        "The task owns skill progress. Read the current project policy before acting.",
        "",
        "## Rules",
        "",
    ]
    index += [f"- [{path.stem}](rules/{path.name})" for path in rules if path.is_file()]
    index += ["", "## Skills", ""]
    import json

    source = json.loads((bundle / ".agents/skills/core-skills.json").read_text())["skills"]
    for identifier, skill in sorted(skills.items()):
        directory = source[identifier]["source"]
        index.append(
            f"- [{identifier}](skills/{directory}/SKILL.md): "
            + " → ".join(p.id for p in skill.phases)
        )
    audit = [
        "# Harness Contract Audit",
        "",
        "This index describes declared contracts; it is not evidence of host activation or task completion.",
        "",
        "| Skill | Ordered phases | Required outcomes |",
        "| --- | --- | --- |",
    ]
    for identifier, skill in sorted(skills.items()):
        directory = source[identifier]["source"]
        audit.append(
            f"| [{identifier}](skills/{directory}/SKILL.md) | {len(skill.phases)} | {sum(len(p.requires) for p in skill.phases)} |"
        )
    audit += [
        "",
        "Nested skills must be declared and remain within their parent phase effects. Normal task completion requires all attached phases and user acceptance.",
        "",
    ]
    return {"HARNESS_INDEX.md": "\n".join(index) + "\n", "HARNESS_AUDIT.md": "\n".join(audit)}
