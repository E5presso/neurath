# Setup execution reference

[한국어](../../ko/contributing/setup-reference.md) · [Core contract](core-v2-spec.md)

Agents use `./setup TARGET` for an authorized target installation and `./setup --self` for this checkout. Setup prepares an immutable tool environment separate from the development virtual environment, validates source identity, installs the projected configuration and runs protocol diagnostics. A repeated identical install is a no-op.

The package CLI retains `setup`, `plan`, `apply`, `install`, `update`, `uninstall`, `restore`, `recover`, `doctor` and `integrity`. Consult its current parser for exact arguments. Project work uses the named core MCP tools and native editing/testing tools; the old generic engine and skill-script gateways are removed. A successful local protocol check does not prove host trust or live activation.
