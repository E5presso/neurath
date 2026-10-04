# Release discovery and application

[한국어](../../ko/contributing/releases-reference.md) · [Core contract](core-v2-spec.md)

Agents run native `releases check`, inspect `releases notice`, prepare the exact offer, obtain the user’s yes/no/later choice, record that exact choice and apply the approved candidate. Read the current parser in `updates_cli.py` for arguments. No answer is not consent. A changed immutable offer cannot reuse an earlier choice.

Candidate installation validates version, distribution and wheel digest while preserving user files and reporting choices. Interrupted application uses recovery, not blind reapplication. Source changes, installation, live activation and a public release are separate observations. Publishing requires the verified wheel and a tag resolving to the reviewed commit; `publication_read` checks observed GitHub release state.
