"""Run kit-owned runtime tests in a disposable checkout without provenance assets."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path)
    parser.add_argument("tests", nargs="*")
    args = parser.parse_args()
    if args.target is not None:
        return run_fixture(args.target, args.tests)
    with tempfile.TemporaryDirectory(prefix="neurath-runtime-") as temporary:
        return run_fixture(Path(temporary) / "kit", args.tests)


def run_fixture(target, selected_tests):
    shutil.copytree(
        ROOT / "src/neurath/_assets", target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    for package in ("agent_harness", "skill_harness"):
        shutil.copytree(
            ROOT / "tests/runtime" / package,
            target / "scripts" / package / "tests",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    (target / "conftest.py").write_text(
        "import importlib, pathlib\nfor path in pathlib.Path(__file__).parent.joinpath('scripts').glob('*/*.py'):\n    if path.name not in ('__main__.py', '__init__.py'):\n        importlib.import_module('.'.join(path.relative_to(pathlib.Path(__file__).parent).with_suffix('').parts))\n"
    )
    (target / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\naddopts = "--import-mode=importlib"\n'
    )
    from neurath.install.projection import host_hooks

    for host, file in (("codex", ".codex/hooks.json"), ("claude-code", ".claude/settings.json")):
        path = target / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"hooks": host_hooks(target, host)}))
    (target / ".neurath").mkdir()
    (target / ".neurath/project.json").write_text(
        json.dumps({"verification": {"pytest": {"argv": [sys.executable, "-m", "pytest"]}}})
    )
    (target / ".gitignore").write_text(
        "__pycache__/\n.pytest_cache/\n.agents/runs/\n.agents/resources/\n"
    )
    subprocess.run(["git", "init", "-q", str(target)], check=True)
    subprocess.run(["git", "-C", str(target), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(target),
            "-c",
            "user.name=Neurath Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "Kit test fixture",
        ],
        check=True,
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("NEURATH_", "CODEX_", "CLAUDE_", "PYTHONPATH"))
    }
    env["PYTHONPATH"] = str(target.resolve())
    print(f"Independent runtime fixture: {target}", flush=True)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *selected_tests], cwd=target, env=env, check=False
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
