"""Run the full extracted engine with explicit target and immutable resource roots."""

import os
import runpy
import sys
from pathlib import Path

from neurath.resources import BUNDLE
from neurath.skill_names import source_id


def activate(root=None):
    if str(BUNDLE) not in sys.path:
        sys.path.insert(0, str(BUNDLE))
    if root is not None:
        os.environ["NEURATH_TARGET_ROOT"] = str(Path(root).resolve())


def run_engine(root, module, arguments):
    path = BUNDLE.joinpath(*module.split("."))
    if (
        not module.startswith("scripts.")
        or any(not part.isidentifier() for part in module.split("."))
        or not (path.with_suffix(".py").is_file() or (path / "__main__.py").is_file())
    ):
        raise ValueError("unknown bundled engine module")
    if (
        module == "scripts.agent_harness.verification_runner"
        and len(arguments) == 1
        and arguments[0] != "--help"
    ):
        from neurath.cli import main

        return main(["--root", str(root), "verify", arguments[0]])
    activate(root)
    os.chdir(root)
    sys.argv = [module, *arguments]
    runpy.run_module(module, run_name="__main__")
    return 0


def run_skill(root, skill, script, arguments):
    from neurath.install.projection import skills

    skill = source_id(skill)
    if skill not in skills() or Path(script).name != script:
        raise ValueError("unknown skill/script")
    source = BUNDLE / ".agents/skills" / skill / "scripts" / script
    if not source.is_file():
        raise ValueError("unknown skill script")
    activate(root)
    os.chdir(root)
    sys.path.insert(0, str(source.parent))
    os.environ["PYTHON_BIN"] = sys.executable
    os.environ["PYTHONPATH"] = str(BUNDLE)
    if source.suffix == ".py":
        sys.argv = [str(source), *arguments]
        runpy.run_path(str(source), run_name="__main__")
        return 0
    if source.suffix == ".sh":
        import subprocess

        return subprocess.run(["bash", str(source), *arguments], cwd=root, check=False).returncode
    raise ValueError("only Python/Bash skill scripts are executable")
