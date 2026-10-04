"""Installer planning and CLI discovery must not bootstrap the retired engine."""

import subprocess
import sys


def test_cli_and_installer_plan_with_retired_modules_unavailable(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    script = """
import importlib.abc
import sys
from pathlib import Path
class NoRetiredCore(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("neurath.runtime", "neurath.hosts", "neurath.agents", "scripts.agent_harness", "scripts.skill_harness")):
            raise ImportError("retired core imported: " + fullname)
sys.meta_path.insert(0, NoRetiredCore())
from neurath.cli import main
try:
    main(["--help"])
except SystemExit as error:
    assert error.code == 0
from neurath.install.transaction import make_plan
plan = make_plan(Path(sys.argv[1]))
assert plan["changes"]
from neurath.doctor import protocol_smoke
assert all(result["status"] == "passed" for result in protocol_smoke().values())
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
