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
            if not key.startswith(("CODEX_", "CLAUDE_", "AMBER_", "NEURATH_", "PYTHON"))
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
            for module in ("scripts.agent_harness", "scripts.skill_harness"):
                run([*command, "engine", module], env=env, cwd=area)
            run(
                [root / ".neurath/run", "engine", "scripts.agent_harness.state_cli", "--help"],
                env=env,
                cwd=area,
            )
            run(
                [root / ".neurath/run", "engine", "scripts.skill_harness.phase_runner", "--help"],
                env=env,
                cwd=area,
            )
            run(
                [
                    root / ".neurath/run",
                    "skill",
                    "monitor-pr",
                    "monitor_runtime_readback.py",
                    "--help",
                ],
                env=env,
                cwd=area,
            )
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
from neurath.runtime.engine import activate
from neurath.resources import BUNDLE
def guard(event, args):
    if event == "open" and isinstance(args[0], str) and ("/projects/amber/" in args[0] or "/projects/neurath/" in args[0]):
        raise RuntimeError("source checkout access forbidden")
sys.addaudithook(guard)
activate()
imported=[]
for path in sorted((BUNDLE / "scripts").rglob("*.py")):
    if "tests" in path.parts or path.name in ("__main__.py", "__init__.py"):
        continue
    module=".".join(path.relative_to(BUNDLE).with_suffix("").parts)
    importlib.import_module(module)
    imported.append(module)
print(json.dumps({"modules":len(imported),"bundle":str(BUNDLE)}))"""
        imported = json.loads(run([python, "-I", "-c", code], cwd=area, env=env))
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
