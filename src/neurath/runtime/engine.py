"""Run the full extracted engine with explicit target and immutable resource roots."""

import os
import runpy
import sys
from pathlib import Path

from neurath.resources import BUNDLE
from neurath.skill_names import public_name, source_id


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
    from neurath.install.transaction import read_state

    known = skills()
    requested = skill
    skill = source_id(requested)
    state = read_state(root)
    if skill not in known and state and state.get("skill_prefix"):
        aliases = {public_name(name, state["skill_prefix"]): name for name in known}
        entry = f".agents/skills/{requested}/SKILL.md"
        if entry in state["owned"]:
            skill = aliases.get(requested, requested)
    if skill not in known or Path(script).name != script:
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
