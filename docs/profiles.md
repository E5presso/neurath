# Project bindings
<!-- date: 2026-09-07; synced_from: source and documentation at 3563609329437641570a5e45d87ceb99064e4c02; English and Korean editions updated together -->

**English** · [한국어](profiles.ko.md)

`generic` is the only profile. The harness does not choose a language, framework, or monorepo
layout. Existing project instructions and `.neurath/project.json` define documents, verification
commands, optional protected resources, and metadata conventions. See the
[installation guide](../ONBOARDING.md) for configuration examples and commands.

The 31 skills operate according to the target repository and current user request. `explain-code`
and `graphify` are helper skills without state-owning phase contracts; the other 29 have phase
and evidence contracts. Both primary intent and input authority must match when selecting a skill.

Missing document bindings are not filled with another project's documents. Verification tools
are not installed arbitrarily, and unconfigured checks are not reported as passing. No particular
connector is protected by default. Protection covers kit state, rules, runtime assets, and the
paths and connectors the user explicitly specifies.

The `test-harness` kit regression matrix runs against the kit's development source. Changes to
an installed target project's code use that project's verification bindings. Product-specific
profile names and product state namespaces are not supported.
