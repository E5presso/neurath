# Maintaining distributed assets

[한국어](../../ko/contributing/assets.md) · [Core contract](core-v2-spec.md)

Edit originals under `src/neurath/_assets`; installed skills and rules are projections. Skills use one typed core catalog. `tools/build_manifest.py` rebuilds catalog indexes, prepares a required version change and records independent package files. The old bundled Python script engines are removed. Installation, rollback and user-owned changes remain covered by outer-service tests.

Implementation references:

- [install/projection.py](../../../src/neurath/install/projection.py)
- [resources.py](../../../src/neurath/resources.py)

[Validation](validation.md) distinguishes source tests, installed protocol checks and actual host behavior.
