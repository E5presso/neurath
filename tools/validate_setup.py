"""Exercise the documented setup from a fresh, isolated user tool environment."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def validate(source, output):
    with tempfile.TemporaryDirectory(prefix="neurath-setup-") as temporary:
        area = Path(temporary).resolve()
        copied = area / "Neurath source's space"
        def source_ignore(directory, names):
            excluded = {".git", ".venv", ".validation", "__pycache__", ".pytest_cache", ".ruff_cache", "dist", "build"}
            if Path(directory) == source:
                excluded.update({".agents", ".claude", ".codex", ".neurath", ".mcp.json", "CLAUDE.md"})
            return set(names) & excluded

        shutil.copytree(
            source,
            copied,
            symlinks=True,
            ignore=source_ignore,
        )
        if (source / ".neurath/project.json").is_file():
            (copied / ".neurath").mkdir()
            shutil.copy2(source / ".neurath/project.json", copied / ".neurath/project.json")

        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("CODEX_", "CLAUDE_", "NEURATH_", "PYTHON", "UV_"))
        }
        env.update(
            PATH="/usr/bin:/bin:/usr/sbin:/sbin",
            UV_INSTALL_DIR=str(area / "uv bin"),
            UV_TOOL_DIR=str(area / "tool environments"),
            UV_TOOL_BIN_DIR=str(area / "tool bin"),
            UV_PYTHON_INSTALL_DIR=str(area / "python runtimes"),
        )
        # A distro's external git/curl binaries may live outside the minimal PATH.
        for name in ("git", "curl"):
            if not shutil.which(name, path=env["PATH"]):
                raise RuntimeError(f"{name} must be available on the minimal system PATH")

        def run(argv, cwd=area):
            result = subprocess.run(
                [str(x) for x in argv],
                env=env,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
            if result.returncode:
                raise RuntimeError(
                    f"command failed {argv}: {result.stderr[-4000:]} {result.stdout[-2000:]}"
                )
            return result.stdout

        observations = {}
        for name in ("empty", "python", "javascript"):
            root = area / (name + " project's 한글")
            run(["git", "init", "-q", root])
            (root / "AGENTS.md").write_text("Keep this project rule.\n")
            (root / ".claude").mkdir()
            original_settings = {
                "permissions": {"deny": ["Bash(rm *)"]},
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo keep"}]}]},
                "model": "user-model",
            }
            (root / ".claude/settings.json").write_text(json.dumps(original_settings))
            manifest_name = None
            if name == "python":
                manifest_name = "pyproject.toml"
                (root / manifest_name).write_text('[project]\nname="user-project"\nversion="1"\n')
            elif name == "javascript":
                manifest_name = "package.json"
                (root / manifest_name).write_text('{"scripts":{"test":"do-not-run"}}\n')
            original_manifest = (root / manifest_name).read_bytes() if manifest_name else None
            first = json.loads(run([copied / "setup", root, "--json"], cwd=root))
            assert first["status"] == "passed"
            assert first["doctor"]["host_activation"]["status"] == "unverified"
            cli = Path(env["UV_TOOL_BIN_DIR"]) / "neurath"
            repeated = json.loads(run([cli, "setup", root, "--json"]))
            assert repeated["receipt"]["changed"] == 0
            current = json.loads((root / ".claude/settings.json").read_text())
            assert current["permissions"] == original_settings["permissions"]
            assert current["model"] == original_settings["model"]
            assert current["hooks"]["Stop"][0] == original_settings["hooks"]["Stop"][0]
            assert not (root / ".venv").exists()
            assert not (root / "uv.lock").exists()
            if manifest_name:
                assert (root / manifest_name).read_bytes() == original_manifest
            bindings = '{"schema":1,"documents":{"intent":"SPEC.md"},"verification":{}}\n'
            (root / ".neurath/project.json").write_text(bindings)
            updated = json.loads(run([copied / "setup", root, "--json"]))
            assert updated["status"] == "passed"
            assert (root / ".neurath/project.json").read_text() == bindings
            # Remove the install source from its recorded path before running the launcher.
            moved = copied.with_name("source moved away")
            copied.rename(moved)
            try:
                doctor = json.loads(run([root / ".neurath/run", "doctor", "--protocol"]))
                assert doctor["placement"]["status"] == "passed"
                assert doctor["protocol"]["codex"]["status"] == "passed"
                run([root / ".neurath/run", "engine", "scripts.agent_harness.state_cli", "--help"])
                run([root / ".neurath/run", "uninstall"])
            finally:
                moved.rename(copied)
            assert (root / "AGENTS.md").read_text() == "Keep this project rule.\n"
            assert json.loads((root / ".claude/settings.json").read_text()) == original_settings
            assert (root / ".neurath/project.json").read_text() == bindings
            observations[name] = {
                "status": "passed",
                "first_changes": first["receipt"]["changed"],
                "repeat_changes": repeated["receipt"]["changed"],
                "source_moved_launcher": "passed",
                "user_files_preserved": True,
                "protocol": first["doctor"]["protocol"],
                "uninstall": "passed",
            }
        report = {
            "status": "passed",
            "repositories": observations,
            "bootstrap": "real official uv download and isolated Python/tool directories",
            "uv_downloaded": (Path(env["UV_INSTALL_DIR"]) / "uv").is_file(),
            "python_downloaded": any(Path(env["UV_PYTHON_INSTALL_DIR"]).glob("cpython-3.14*")),
            "setup_sha256": hashlib.sha256((source / "setup").read_bytes()).hexdigest(),
            "host_activation": "unverified; local protocol checks only",
        }
        assert report["uv_downloaded"] and report["python_downloaded"]
        run(["git", "init", "-q", copied])
        public_instructions = (copied / "AGENTS.md").read_bytes()
        own = json.loads(run([copied / "setup", "--self", "--json"], cwd=copied))
        assert own["status"] == "passed"
        repeat = json.loads(run([cli, "setup", copied, "--json"]))
        assert repeat["receipt"]["changed"] == 0
        assert (copied / "AGENTS.md").read_bytes().startswith(public_instructions)
        assert not (copied / ".venv").exists()
        observations["self_checkout"] = {"status": "passed", "repeat_changes": 0, "public_instructions_preserved": True}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    validate(args.source.resolve(), args.output.resolve())
