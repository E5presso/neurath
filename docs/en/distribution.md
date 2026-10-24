# Preparing, updating, and recovering distributions

Neurath identifies distributions by wheel SHA-256. Two artifacts or source commits at `0.4.0` can be different candidates; a matching version string does not establish that an installation is current. Candidate preparation, file application, a new CLI invocation, model use of updated instructions, and native host activation are separate results.

## Source and official releases

```sh
neurath distribution check --installed /path/to/.codex/neurath/distribution.json
uv run --locked python tools/generate_cli_guide.py --check
uv run --locked python tools/build_release.py --output release-candidate
neurath distribution prepare --wheel release-candidate/neurath-0.4.0-py3-none-any.whl \
  --store /path/to/data/neurath/distributions --source-commit FULL_COMMIT_SHA
```

`check` distinguishes `no-release`, `lookup-failed`, `release-observed`, and `current-artifact`. Only a matching official asset digest establishes `current-artifact`; it does not establish source-branch currency. An official wheel's `browser_download_url` can also be passed to `prepare --wheel`. Preparation compares the published asset SHA-256 with downloaded bytes and fails on missing or mismatched digests.

The source builder first checks the packaged guide against actual Typer definitions. Stale guides or generation failures fail the build. A staging copy packages source provenance, CLI, guide, and all 14 skills together. A modified development checkout records `source_modified: true` and `source_commit: null` rather than claiming a clean commit. For an exact source request, build from that checkout and compare its packaged commit with `--source-commit`. `.github/workflows/distribution.yml` runs all checks and this build, producing a candidate artifact and SHA256SUMS. Producing a candidate does not publish a public release.

## Applying and checking current execution

```sh
neurath distribution plan --candidate /path/to/distributions/WHEEL_SHA \
  --provider codex --directory /path/to/project --data-home /path/to/data
neurath distribution apply --candidate /path/to/distributions/WHEEL_SHA \
  --provider codex --directory /path/to/project --data-home /path/to/data
/path/to/project/.codex/neurath/neurath distribution verify
/path/to/project/.codex/neurath/neurath distribution guide
```

`prepare` creates a separate environment per wheel and compares its actual CLI and guide. It does not overwrite a prepared runtime; reuse checks the retained wheel, guide, and package content. The installed wrapper uses that environment's Python without changing the caller's working directory. `-I` prevents local modules or `PYTHONPATH` from shadowing the installed package while project and host identity are observed from the original environment.

A private `plan` preview contains the actual file changes and selected distribution. `apply` calls the existing installer from that candidate, updates owned blocks, skills, and hooks, and executes the new wrapper to compare version and package content. An already requested update requires no additional consent token or new task. `./setup --provider ... --directory ...` builds the current checkout into a fixed wheel and uses this path. `maintenance install` is the lower-level file installer for its calling environment; `./setup` or `distribution prepare/apply` prepares a development environment as a fixed distribution.

User instructions, specialist skills, and other extension settings are preserved. Historical MCP registrations are removed only when the requested root's managed launcher marker and exact legacy command establish ownership. For an unmarked historical `.neurath/run`, match the launcher SHA, Python and execution target in `install.json`, the configuration file SHA, and exact hook/MCP arguments. Replace only verified handlers, preserving unrelated handlers and properties in mixed groups. When an exact old hook invocation exists but ownership checks fail, planning and application fail before adding a competing handler. Replace old `neurath:managed` blocks using the manifest ownership entry, clear boundaries, and known MCP body. Preserve outside user edits even when they change the whole-file SHA; unclear boundaries or ownership preserve the original and return an error. An ambiguous entry merely named Neurath remains intact, with guidance to inspect that entry and replace its actual Neurath invocation with the grouped CLI. Do not repeatedly retry cached MCP calls or introduce a replacement MCP server.

Version 0.4.0 distinguishes this distribution from the historical public 0.3.1. Installed rules direct new sessions to first read the matching `.codex/neurath/guide.md` or `.claude/neurath/guide.md`. Shared `AGENTS.md`/`CLAUDE.md` uses project-relative links and preserves the symlink and user text. Each guide points to its own CLI and 14 skills, independently of installation order or reinstallation. Running sessions can reread the actual current guide with `distribution guide`. Its result establishes stdout submission; actual model use and native hook activation require separate observation. A CLI update does not impose a host-app restart. Do not fabricate trust hashes, native identity, or permissions.

## Shared databases and failure recovery

When multiple projects or hosts share one user database, each wrapper and guide points explicitly to its selected distribution. Installation does not automatically upgrade the existing database first. Failed candidate schema/integrity checks stop before file switching, and `plan` provides the continuation through [preserving migration](migration.md). Within the existing update request, the agent:

1. Identifies managed CLIs sharing the database and retains their currently compatible runtimes.
2. Uses the compatible CLI's `migration fence` to preserve and retire the old connection path. SQLite path fencing does not prove host-wide or external-schedule termination.
3. Uses that compatible CLI's `migration recover` to create a new data-home copy, then runs the candidate's `maintenance initialize` on that copy and reads preserved work.
4. Applies the candidate and recovered data home to the selected shared hosts, then replays the original transition queue. On failure, it retains original/new stores and pending events and continues with a compatible runtime.

```sh
neurath distribution recover --receipt /path/to/applications/APPLICATION.json
```

Application privately records the original files and matching candidate. Failures restore the original executable/guide combination. Later recovery never overwrites the database or transition events with an older snapshot. User edits made after application are preserved as conflicts. If the former runtime cannot read current records, recovery retains the current installation and directs compatible recovery. Interrupted applications can recover only files matching their recorded before/after content.

Queued monitor ticks reconcile the existing monitor's current session, task, resource ownership, cancellation, and budget. Observations and technical receipts use existing transactions; replay after a lost queue acknowledgment does not consume the same callback's observation budget again. Ticks never become new user instructions. New monitor events remain `written` until actually submitted to the host. Malformed callbacks or unfinished observations remain pending for precise recovery. Native schedule reception and model delivery remain separate activation checks.
