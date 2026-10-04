"""Neurath is a kit with its own authority, not a project-specific projection."""

import json
import subprocess
import sys

from neurath.install.transaction import apply_plan, make_plan
from neurath.install.projection import PROFILES, asset_files
from neurath.resources import PACKAGE


def test_distribution_has_no_source_project_payload_or_namespace():
    forbidden = (b"private_project", b"spakky", b"E5presso/")
    violations = []
    for path in PACKAGE.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(PACKAGE).as_posix()
        if path.name in {"upstream.tar.gz", "extraction.json"}:
            violations.append(relative)
            continue
        content = path.read_bytes()
        # The user-authorized public upstream is the reporting/release destination, not a
        # source-project dependency. Keep every other owner/repository forbidden.
        if relative in {"reporting.py", "updates.py"}:
            content = content.replace(b'E5presso/neurath', b'PUBLIC_NEURATH_UPSTREAM')
        if any(word.lower() in content.lower() for word in forbidden):
            violations.append(relative)
    assert not violations, "Source-project payload in distribution: " + ", ".join(violations[:30])


def test_installed_assets_are_project_neutral():
    assert PROFILES == ("generic",)
    assets = asset_files("generic", ["codex", "claude-code"])
    forbidden = (
        b"private_project",
        b"spakky",
        b"E5presso/",
        b"apps/backend/services/",
        b"apps/local-surface",
        b"scripts.monorepo_cli",
        b"uv run pyrefly",
    )
    forbidden += tuple(text.encode() for text in (
        "기본 한국어", "한국어 metadata audit", "GitHub Issue-only tracking",
        "Neurath monorepo", "Neurath는 SDD",
    ))
    violations = [
        name
        for name, (content, _) in assets.items()
        if name != ".neurath/run" and any(word.lower() in content.lower() for word in forbidden)
    ]
    assert not violations, "Source policy in installed assets: " + ", ".join(violations[:30])


def test_review_personas_do_not_supply_unbound_python_policies():
    assets = asset_files("generic", ["codex"])
    for name in ("type", "naming"):
        text = assets[f".agents/skills/review-code/personas/{name}.md"][0].decode()
        assert "python-code.md" not in text
        assert "대상 프로젝트" in text
        assert "I*` 접두사로 정의해야" not in text
        assert "TypedDict` 사용 (BaseModel로 대체" not in text




def test_integrity_detects_added_and_modified_kit_code(tmp_path):
    import hashlib

    from neurath.doctor import integrity

    module = tmp_path / "runtime.py"
    module.write_text("VALUE = 1\n")
    manifest = {
        "schema": 1,
        "files": {"runtime.py": hashlib.sha256(module.read_bytes()).hexdigest()},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert integrity(tmp_path)["status"] == "passed"
    module.write_text("VALUE = 2\n")
    assert integrity(tmp_path)["status"] == "failed"
    module.write_text("VALUE = 1\n")
    (tmp_path / "unexpected.py").write_text("VALUE = 3\n")
    assert integrity(tmp_path)["status"] == "failed"
    (tmp_path / "unexpected.py").unlink()
    module.unlink()
    assert integrity(tmp_path)["status"] == "failed"


def test_unknown_project_profile_is_rejected_before_changes(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    result = subprocess.run(
        [sys.executable, "-I", "-m", "neurath", "setup", str(tmp_path), "--profile", "private_project"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert not (tmp_path / ".neurath").exists()














def test_installed_catalog_links_resolve_to_managed_assets():
    import re
    import posixpath

    assets = asset_files("generic", ["codex", "claude-code"])
    for name in (".neurath/reference/HARNESS_INDEX.md", ".neurath/reference/HARNESS_AUDIT.md"):
        text = assets[name][0].decode()
        for link in re.findall(r"\]\(([^)]+)\)", text):
            if link.startswith(("http:", "https:", "#")):
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), link))
            assert target in assets, f"{name}: broken catalog link {link}"
