"""Build-independent wheel acceptance in a fresh external Python environment."""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


def validate(wheel, output):
    wheel_digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="neurath-wheel-") as temporary:
        area = Path(temporary).resolve()
        runtime = area / "runtime"

        def run(argv, **kwargs):
            result = subprocess.run(
                [str(x) for x in argv], capture_output=True, text=True, check=False, **kwargs
            )
            if result.returncode:
                raise RuntimeError(
                    f"command failed {argv}: {result.stderr[-3000:]} {result.stdout[-1500:]}"
                )
            return result.stdout

        run(["uv", "venv", "--python", "3.14", runtime])
        python = runtime / "bin/python"
        run(["uv", "pip", "install", "--python", python, wheel])
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("CODEX_", "CLAUDE_", "NEURATH_", "PYTHON"))
        }
        env["PATH"] = str(runtime / "bin") + ":/usr/bin:/bin:/usr/sbin:/sbin"
        observations = {}
        for name in ("empty", "python", "javascript"):
            root = area / (name + " repository's space")
            run(["git", "init", "-q", root])
            if name == "python":
                (root / "pyproject.toml").write_text(
                    '[project]\nname="user-project"\nversion="1"\n'
                )
            elif name == "javascript":
                (root / "package.json").write_text('{"name":"user-project"}')
            (root / "AGENTS.md").write_text("# Original user instruction\n")
            (root / ".claude").mkdir()
            (root / ".claude/settings.json").write_text(
                '{"permissions":{"deny":["Bash(rm *)"]},"env":{"KEEP":"yes"}}'
            )
            command = [python, "-I", "-m", "neurath", "--root", root]
            installed = json.loads(run([*command, "install"], env=env, cwd=area))
            repeated = json.loads(run([*command, "install"], env=env, cwd=area))
            assert repeated["changed"] == 0
            doctor = json.loads(run([*command, "doctor", "--protocol"], env=env, cwd=area))
            assert doctor["protocol"]["codex"]["status"] == "passed"
            assert doctor["protocol"]["claude-code"]["status"] == "passed"
            run([root / ".neurath/run", "integrity"], env=env, cwd=area)
            settings = json.loads((root / ".claude/settings.json").read_text())
            assert settings["permissions"]["deny"] == ["Bash(rm *)"]
            assert settings["env"]["KEEP"] == "yes"
            assert not (root / ".venv").exists()
            observations[name] = {
                "install_changes": installed["changed"],
                "reinstall_changes": repeated["changed"],
                "doctor": doctor,
            }
            run([*command, "update", "--host", "codex"], env=env, cwd=area)
            run([*command, "uninstall"], env=env, cwd=area)
            assert (root / "AGENTS.md").read_text() == "# Original user instruction\n"
            assert not (root / ".codex/hooks.json").exists()
        code = """import importlib, json, sys
from pathlib import Path
import neurath.core
from neurath.core.service import COMMANDS
from neurath.resources import BUNDLE
source_root = Path(sys.argv[1]).resolve()
def guard(event, args):
    if event == "open" and isinstance(args[0], str):
        target = Path(args[0]).resolve()
        if target.is_relative_to(source_root) or "projects" in target.parts:
            raise RuntimeError("source checkout access forbidden")
sys.addaudithook(guard)
imported=[]
for path in sorted(Path(neurath.core.__file__).parent.glob("*.py")):
    if path.name in ("__main__.py", "__init__.py"):
        continue
    module="neurath.core." + path.stem
    importlib.import_module(module)
    imported.append(module)
assert "task_complete" in COMMANDS and "phase_complete" in COMMANDS
print(json.dumps({"modules":len(imported),"bundle":str(BUNDLE)}))"""
        imported = json.loads(run([python, "-I", "-c", code, Path(__file__).resolve().parents[1]], cwd=area, env=env))
        report = {
            "status": "passed",
            "wheel": wheel.name,
            "wheel_sha256": wheel_digest,
            "environment": "fresh external Python 3.14 environment; core dependencies only; source checkout opens denied during import",
            "import": imported,
            "repositories": observations,
            "host_activation": "unverified; protocol simulation only",
        }
        assert hashlib.sha256(wheel.read_bytes()).hexdigest() == wheel_digest
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "status": "passed",
                    "modules": imported["modules"],
                    "repositories": len(observations),
                    "report": str(output),
                }
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    validate(args.wheel.resolve(), args.output.resolve())
