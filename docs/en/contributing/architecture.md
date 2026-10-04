# Core architecture

[한국어](../../ko/contributing/architecture.md) · [Core contract](core-v2-spec.md)

Task is the single progress aggregate. It contains ordered SkillRuns, attempts and assignments. The core owns transitions and evidence validation; the native host owns permissions and tool execution. SQLite stores Tasks, original sources, writer leases and attributed records under `.neurath/local/core.sqlite3` at the Git common root. Goal text is not an identifier.

Implementation references:

- [core/domain.py](../../../src/neurath/core/domain.py)
- [core/store.py](../../../src/neurath/core/store.py)
- [core/service.py](../../../src/neurath/core/service.py)
- [core/hook_adapter.py](../../../src/neurath/core/hook_adapter.py)

[Validation](validation.md) distinguishes source tests, installed protocol checks and actual host behavior.
