"""Record the complete independent runtime payload before building a distribution."""

import hashlib
import json
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src/neurath"


def main():
    # The catalog measures projected policy bytes. Refresh it before hashing so
    # a policy change cannot ship with stale generated audit measurements.
    sys.path.insert(0, str(PACKAGE.parent))
    sys.path.insert(0, str(PACKAGE / "_assets"))
    from scripts.skill_harness.harness_catalog import HarnessCatalog

    catalog = HarnessCatalog.load(PACKAGE / "_assets")
    for name, rendered in (
        ("HARNESS_INDEX.md", catalog.render_rule_index()),
        ("HARNESS_AUDIT.md", catalog.render_audit_index()),
    ):
        (PACKAGE / "_assets/.agents" / name).write_text(rendered, encoding="utf-8")
    files = {}
    for path in sorted(PACKAGE.rglob("*")):
        if "__pycache__" in path.parts or path.suffix == ".pyc" or path.name == "manifest.json":
            continue
        if path.is_symlink():
            raise RuntimeError(f"runtime payload must not depend on symlinks: {path}")
        if path.is_file():
            files[path.relative_to(PACKAGE).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    (PACKAGE / "manifest.json").write_text(
        json.dumps({"schema": 1, "files": files}, indent=2) + "\n"
    )
    print(f"Recorded {len(files)} independent runtime files")


if __name__ == "__main__":
    main()
