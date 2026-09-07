# Independent runtime assets
<!-- date: 2026-09-07; synced_from: source and documentation at 2456ae73ffaf818c04ea4419574218df36852805; English and Korean editions updated together -->

[Usage](../usage/index.md) · [Contributing](index.md)


**English** · [한국어](../../ko/contributing/assets.md)

Neurath maintains its own runtime, host adapters, contracts, and installer.
Other repositories are neither build inputs nor runtime dependencies.

`src/neurath/manifest.json` verifies all runtime code and assets in the installation package.
Private development materials, raw validation evidence, and installation records are excluded
from public distributions.

To inspect the standalone assets, run `neurath corpus /path/to/new-directory`.
This command copies assets from the current distribution without reading another repository.
