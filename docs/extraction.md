# Independent runtime assets
<!-- date: 2026-09-07; synced_from: source and documentation at 3563609329437641570a5e45d87ceb99064e4c02; English and Korean editions updated together -->

**English** · [한국어](extraction.ko.md)

Neurath maintains its own runtime, host adapters, contracts, and installer.
Other repositories are neither build inputs nor runtime dependencies.

`src/neurath/manifest.json` verifies all runtime code and assets in the installation package.
Private development materials, raw validation evidence, and installation records are excluded
from public distributions.

To inspect the standalone assets, run `neurath corpus /path/to/new-directory`.
This command copies assets from the current distribution without reading another repository.
