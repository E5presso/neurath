"""The public checkout must contain the files its documentation promises."""

import json
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def public_document_pairs():
    pairs = [(ROOT / name, ROOT / name.replace('.md', '.ko.md'))
             for name in ('README.md', 'CONTRIBUTING.md')]
    en = ROOT / 'docs/en'
    ko = ROOT / 'docs/ko'
    assert en.is_dir() and ko.is_dir(), 'Documentation must have both locale directories'
    assert {p.relative_to(en) for p in en.rglob('*.md')} == {
        p.relative_to(ko) for p in ko.rglob('*.md')
    }, 'English and Korean document inventories differ'
    return pairs + [(p, ko / p.relative_to(en)) for p in sorted(en.rglob('*.md'))]


def test_public_documents_have_separate_english_and_korean_editions():
    for original, translated in public_document_pairs():
        assert translated.is_file(), f"Missing Korean edition: {translated.relative_to(ROOT)}"
        for document, counterpart in ((original, translated), (translated, original)):
            text = document.read_text()
            targets = re.findall(r"\[[^\]]*\]\(([^)]+)\)|href=\"([^\"]+)\"", text)
            relative = os.path.relpath(counterpart, document.parent)
            assert any((left or right) == relative for left, right in targets), (
                f"Missing language switch: {document.relative_to(ROOT)}"
            )


def test_document_links_keep_the_selected_language():
    pairs = public_document_pairs()
    languages = {p.resolve(): locale for pair in pairs for locale, p in zip(('en', 'ko'), pair)}
    counterparts = {p: q for en, ko in pairs for p, q in ((en, ko), (ko, en))}
    for document, counterpart in counterparts.items():
        text = re.sub(r"```.*?```", "", document.read_text(), flags=re.DOTALL)
        for markdown, html in re.findall(r"\[[^\]]*\]\(([^)]+)\)|href=\"([^\"]+)\"", text):
            parsed = urlsplit(markdown or html)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target = (document.parent / unquote(parsed.path)).resolve()
            if target in languages and target != counterpart.resolve():
                assert languages[target] == languages[document.resolve()], (
                    f"Language changes unexpectedly: {document.relative_to(ROOT)} -> {parsed.path}"
                )


def test_public_document_links_resolve_inside_checkout():
    documents = sorted(ROOT.glob("*.md")) + sorted((ROOT / "docs").rglob("*.md"))
    missing = []
    for document in documents:
        text = re.sub(r"```.*?```", "", document.read_text(), flags=re.DOTALL)
        targets = re.findall(r'\[[^\]]*\]\(([^)]+)\)|(?:href|src)="([^"]+)"', text)
        for markdown, html in targets:
            target = markdown or html
            target = target.split(maxsplit=1)[0].strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            path = (document.parent / unquote(parsed.path)).resolve()
            if not path.is_relative_to(ROOT) or not path.exists():
                missing.append(f"{document.relative_to(ROOT)} -> {target}")
    assert not missing, "Unresolvable public documentation links: " + ", ".join(missing)


def test_documentation_layout_and_source_distribution_includes():
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    included = config["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    for name in ('README.md', 'README.ko.md', 'CONTRIBUTING.md', 'CONTRIBUTING.ko.md', 'docs'):
        assert name in included
        assert (ROOT / name).exists()
    assert not list((ROOT / 'docs').glob('*.md')), 'Reader documents belong in locale folders'
    for locale in ('en', 'ko'):
        for entry in ('usage/index.md', 'usage/installation.md', 'contributing/index.md'):
            assert (ROOT / 'docs' / locale / entry).is_file()
        readme = ROOT / ('README.ko.md' if locale == 'ko' else 'README.md')
        for audience in ('usage', 'contributing'):
            assert f'docs/{locale}/{audience}/index.md' in readme.read_text()
    bindings = json.loads((ROOT / '.neurath/project.json').read_text())['documents']
    assert (ROOT / bindings['decisions']).is_file()


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
