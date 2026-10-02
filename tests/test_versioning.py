"""Changed runtime payloads need a new, consistent package version before delivery."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "neurath_versioning", Path(__file__).parents[1] / "tools/versioning.py")
versioning = importlib.util.module_from_spec(spec)
spec.loader.exec_module(versioning)

pytestmark = pytest.mark.fast


@pytest.fixture
def source(tmp_path):
    (tmp_path / "src/neurath").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "neurath"\nversion = "0.1.0"\n')
    (tmp_path / "src/neurath/__init__.py").write_text('__version__ = "0.1.0"\n')
    (tmp_path / "src/neurath/runtime.py").write_text('VALUE = 1\n')
    (tmp_path / "uv.lock").write_text(
        'version = 1\n[[package]]\nname = "neurath"\nversion = "0.1.0"\n'
        '[[package]]\nname = "other"\nversion = "0.1.0"\n')
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "-qm", "baseline"],
                   check=True)
    return tmp_path


def test_changed_runtime_requires_and_prepares_one_patch_bump(source):
    (source / "src/neurath/runtime.py").write_text('VALUE = 2\n')
    with pytest.raises(ValueError, match="version"):
        versioning.check_version(source)
    assert versioning.prepare_version(source) == "0.1.1"
    assert versioning.prepare_version(source) == "0.1.1"
    assert versioning.check_version(source) == "0.1.1"
    assert '__version__ = "0.1.1"' in (source / "src/neurath/__init__.py").read_text()
    assert 'name = "other"\nversion = "0.1.0"' in (source / "uv.lock").read_text()


def test_new_runtime_file_also_requires_a_bump(source):
    (source / "src/neurath/new.py").write_text('NEW = True\n')
    assert versioning.prepare_version(source) == "0.1.1"


def test_docs_and_manifest_refresh_do_not_increment_version(source):
    (source / "README.md").write_text('Docs only.\n')
    (source / "src/neurath/manifest.json").write_text('{}\n')
    assert versioning.prepare_version(source) == "0.1.0"


def test_explicit_higher_version_is_preserved(source):
    for path in [source / "pyproject.toml", source / "src/neurath/__init__.py", source / "uv.lock"]:
        path.write_text(path.read_text().replace('"0.1.0"', '"0.2.0"'))
    (source / "src/neurath/runtime.py").write_text('VALUE = 2\n')
    assert versioning.prepare_version(source) == "0.2.0"


def test_inconsistent_metadata_fails_without_rewriting(source):
    path = source / "src/neurath/__init__.py"
    path.write_text('__version__ = "0.2.0"\n')
    with pytest.raises(ValueError, match="inconsistent"):
        versioning.prepare_version(source)
    assert path.read_text() == '__version__ = "0.2.0"\n'


def test_archive_keeps_declared_version_without_git_history(source):
    import shutil
    shutil.rmtree(source / ".git")
    (source / "src/neurath/runtime.py").write_text('VALUE = 2\n')
    assert versioning.prepare_version(source) == "0.1.0"
