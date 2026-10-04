# Project memory

[한국어](../../ko/contributing/memory-reference.md) · [Core contract](core-v2-spec.md)

Project memory retains attributed checkpoints and reusable learning. Recalled text helps recover context; it cannot authorize work, complete a Task or replace current source verification. The retained outer memory service uses the core SQLite store. Private local history and validation logs are excluded from public assets.

Implementation references:

- [memory/store.py](../../../src/neurath/memory/store.py)
- [memory/learning.py](../../../src/neurath/memory/learning.py)

[Validation](validation.md) distinguishes source tests, installed protocol checks and actual host behavior.
