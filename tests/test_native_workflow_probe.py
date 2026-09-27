"""Loading a verification driver must not activate a real native session."""
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.fast
PROBE = Path(__file__).parents[1] / "tools/native_workflow_probe.py"


def test_import_and_help_do_not_require_native_identity(tmp_path):
    code = ("import importlib.util; "
            f"spec=importlib.util.spec_from_file_location('probe_import', {str(PROBE)!r}); "
            "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)")
    imported = subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp_path,
                              capture_output=True, text=True)
    assert imported.returncode == 0, imported.stderr
    help_result = subprocess.run([sys.executable, "-I", str(PROBE), "--help"],
                                 cwd=tmp_path, capture_output=True, text=True)
    assert help_result.returncode == 0, help_result.stderr
    assert "role" in help_result.stdout
