"""The public checkout must contain the files its documentation promises."""

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]


def test_public_document_links_resolve_inside_checkout():
    documents = sorted(ROOT.glob("*.md")) + sorted((ROOT / "docs").rglob("*.md"))
    missing = []
    for document in documents:
        text = re.sub(r"```.*?```", "", document.read_text(), flags=re.DOTALL)
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            target = target.split(maxsplit=1)[0].strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            path = (document.parent / unquote(parsed.path)).resolve()
            if not path.is_relative_to(ROOT) or not path.exists():
                missing.append(f"{document.relative_to(ROOT)} -> {target}")
    assert not missing, "Unresolvable public documentation links: " + ", ".join(missing)


def test_contributing_translations_are_included_in_source_distribution():
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    included = config["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    for name in ("CONTRIBUTING.md", "CONTRIBUTING.ko.md"):
        assert name in included
        assert (ROOT / name).is_file()


def test_fresh_checkout_excludes_machine_local_mcp_settings(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
    (tmp_path / ".codex").mkdir()
    for name in (".mcp.json", ".codex/config.toml"):
        (tmp_path / name).write_text("machine-specific configuration\n")
    result = subprocess.run(
        ["git", "-C", str(tmp_path), "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True, check=True,
    )
    assert ".mcp.json" not in result.stdout.splitlines()
    assert ".codex/config.toml" not in result.stdout.splitlines()
