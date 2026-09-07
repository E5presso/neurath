# Project bindings
<!-- date: 2026-09-07; synced_from: source and documentation at e1487a1718056b37b999d1343a1007b7e25f5c8c; English and Korean editions updated together -->

[Usage](index.md) · [Contributing](../contributing/index.md)


**English** · [한국어](../../ko/usage/profiles.md)

`generic` is the only profile. The harness does not choose a language, framework, or monorepo
layout. Existing project instructions and `.neurath/project.json` define documents, verification
commands, optional protected resources, and metadata conventions. See the
[installation guide](installation.md) for what to ask the agent to connect.

The 31 skills operate according to the target repository and current user request. The agent chooses a skill
that matches both the task and the evidence or authorization available for it. For example,
an approved issue is the starting point for implementation, while a reproducible symptom is the
starting point for debugging. See the [usage guide](index.md) and [skill catalog](skills.md).

Missing document bindings are not filled with another project's documents. Verification tools
are not installed arbitrarily, and unconfigured checks are not reported as passing. No particular
connector is protected by default. Protection covers kit state, rules, runtime assets, and the
paths and connectors the user explicitly specifies.

Changes to your project's code use your project's verification bindings. The checks used to
develop Neurath itself are described in [contributing](../contributing/index.md). There are no
product-specific profiles, and state from another product is not reused.

The agent inspects existing project conventions and maintains these bindings. You supply missing decisions or constraints; you do not need to edit configuration files.
