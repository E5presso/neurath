"""Source edits must not silently replace the runtime of an active coding session."""
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.fast


@pytest.fixture
def checkout(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "tools").mkdir()
    shutil.copy2(Path(__file__).parents[1] / "tools/checkout_host", tmp_path / "tools/checkout_host")
    (tmp_path / "src/neurath").mkdir(parents=True)
    (tmp_path / "src/neurath/manifest.json").write_text("{}\n")
    (tmp_path / "pyproject.toml").write_text("# source fixture\n")
    setup = tmp_path / "setup"
    setup.write_text('''#!/bin/sh
set -eu
printf 'setup\\n' >> setup-calls
mkdir -p .neurath
printf '{}\\n' > .neurath/install.json
printf '#!/bin/sh\\nprintf "installed:%%s\\\\n" "$*"\\n' > .neurath/run
chmod +x .neurath/run
''')
    setup.chmod(0o755)
    return tmp_path


def invoke(root, *arguments):
    return subprocess.run([str(root / "tools/checkout_host"), *arguments],
                          cwd=root, capture_output=True, text=True, timeout=3)


def test_bootstrap_once_then_reuse_installed_runtime_after_source_edits(checkout):
    first = invoke(checkout, "mcp")
    assert first.returncode == 0, first.stderr
    assert first.stdout.strip() == "installed:__mcp"
    (checkout / "src/neurath/manifest.json").write_text('{"source":"unverified edits"}\n')
    second = invoke(checkout, "hook", "--host", "codex")
    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == "installed:hook --host codex"
    assert (checkout / "setup-calls").read_text().splitlines() == ["setup"]


def test_failed_bootstrap_returns_original_error_without_retry_loop(checkout):
    (checkout / "setup").write_text("#!/bin/sh\nprintf 'setup conflict\\n' >&2\nexit 7\n")
    result = invoke(checkout, "mcp")
    assert result.returncode == 7
    assert "setup conflict" in result.stderr
    assert not (checkout / ".neurath/run").exists()
