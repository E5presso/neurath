"""Independent installed-wheel acceptance; only the public release transport is simulated."""

import argparse
import base64
import hashlib
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path


def future_wheel(source, destination):
    with zipfile.ZipFile(source) as archive:
        files = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
    version = next(name.split("/")[0][8:-10] for name in files if name.endswith(".dist-info/METADATA"))
    parts = list(map(int, version.split(".")))
    parts[2] += 1
    target = ".".join(map(str, parts))
    old_dist, new_dist = f"neurath-{version}.dist-info/", f"neurath-{target}.dist-info/"
    files = {name.replace(old_dist, new_dist): data for name, data in files.items()}
    files["neurath/__init__.py"] = files["neurath/__init__.py"].replace(
        f'"{version}"'.encode(), f'"{target}"'.encode())
    files[new_dist + "METADATA"] = files[new_dist + "METADATA"].replace(
        f"Version: {version}\n".encode(), f"Version: {target}\n".encode())
    files["neurath/manifest.json"] = json.dumps(dict(schema=1, files={
        name.removeprefix("neurath/"): hashlib.sha256(data).hexdigest()
        for name, data in files.items() if name.startswith("neurath/")
        and name != "neurath/manifest.json"})).encode()
    record = new_dist + "RECORD"
    files[record] = ("\n".join(
        f"{name},sha256={base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')},{len(data)}"
        for name, data in files.items() if name != record) + f"\n{record},,\n").encode()
    output = destination / f"neurath-{target}-py3-none-any.whl"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return version, target, output


DRIVER = '''import json, sys
from pathlib import Path
from neurath import updates, release_install
from neurath.cli import main
root, remote, wheel, source, mode, *args = sys.argv[1:]
source = Path(source).resolve()
def guard(event, values):
    if event == "open" and isinstance(values[0], str) and Path(values[0]).resolve().is_relative_to(source):
        raise RuntimeError("source checkout access forbidden")
sys.addaudithook(guard)
def fetch(*unused):
    if mode == "offline":
        raise TimeoutError("fixture network unavailable")
    return json.loads(Path(remote).read_text())
updates.fetch_release = fetch
release_install.download_asset = lambda asset_id: Path(wheel).read_bytes()
raise SystemExit(main(["--root", root, *args]))
'''


def validate(wheel, output):
    source = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="neurath-release-acceptance-") as tmp:
        area = Path(tmp).resolve()
        current, target, future = future_wheel(wheel, area)
        runtime = area / "original-runtime"
        root = area / "private target's project"
        env = {k: v for k, v in os.environ.items() if not k.startswith(
            ("CODEX_", "CLAUDE_", "NEURATH_", "PYTHON"))}
        def run(argv, *, expected=0):
            result = subprocess.run([str(x) for x in argv], cwd=area, env=env,
                                    capture_output=True, text=True, timeout=120)
            if result.returncode != expected:
                raise RuntimeError(f"unexpected exit {result.returncode}: {result.stderr[-2000:]}")
            return result.stdout
        run(["uv", "venv", "--python", "3.14", runtime])
        python = runtime / "bin/python"
        run(["uv", "--no-config", "pip", "install", "--python", python, wheel])
        run(["git", "init", "-q", root])
        original = b"# Keep user instructions\r\n"
        (root / "AGENTS.md").write_bytes(original)
        (root / ".claude").mkdir()
        settings = {"permissions": {"deny": ["Bash(rm *)"]}, "model": "user-selection"}
        (root / ".claude/settings.json").write_text(json.dumps(settings))
        (root / "package.json").write_text('{"name":"keep-user-dependencies"}')
        installed = json.loads(run([python, "-I", "-m", "neurath", "--root", root, "install"]))
        remote = area / "public-release.json"
        remote.write_text(json.dumps(dict(id=1, tag_name="v" + target, draft=False, prerelease=False,
            published_at="2026-09-07T00:00:00Z", body="Test recovery and preserve choices.",
            assets=[dict(id=2, name=future.name, state="uploaded", size=future.stat().st_size,
                         digest="sha256:" + hashlib.sha256(future.read_bytes()).hexdigest())])))
        def cli(*args, mode="online", expected=0):
            value = run([python, "-I", "-c", DRIVER, root, remote, future, source, mode, *args],
                        expected=expected)
            return json.loads(value) if value.strip() else None
        cli("report", "consent", "yes", "--user-confirmed")
        proposal = area / "proposal.json"
        proposal.write_text(json.dumps(dict(kind="contribution", scope="project-specific",
            component="cli.py", summary="Improve generic setup", expected="Preserve choices",
            observed="Inspect choices", reproduction="Use a disposable fixture",
            proposal="Preserve user settings")))
        draft = cli("report", "prepare", str(proposal), "--privacy-reviewed")
        cli("report", "approve", draft["id"], "yes", "--user-confirmed")
        reporting = root / ".git/neurath-reporting/state.json"
        reporting_before = reporting.read_bytes()
        checked = cli("releases", "check")
        offer = checked["offer"]["id"]
        assert checked["current"] == current and checked["offer"]["version"] == target
        assert cli("releases", "notice")["id"] == offer
        assert cli("releases", "notice") is None
        for decision in ("no", "later"):
            cli("releases", "choose", offer, decision, "--user-confirmed")
            assert cli("releases", "status")["decision"] == decision
            cli("releases", "check", "--force")
            assert cli("releases", "notice") is None
            cli("releases", "apply", offer, expected=2)
        prepared = cli("releases", "prepare", offer)
        assert prepared["operation"]["phase"] == "prepared"
        assert cli("releases", "status")["current"] == current
        cli("releases", "choose", offer, "yes", expected=2)
        cli("releases", "choose", offer, "yes", "--user-confirmed")
        applied = cli("releases", "apply", offer)
        assert applied["operation"]["phase"] == "applied"
        assert cli("releases", "status")["current"] == target
        assert reporting.read_bytes() == reporting_before
        assert cli("report", "read", draft["id"])["approved"] is True
        assert (root / "AGENTS.md").read_bytes().startswith(original)
        assert json.loads((root / ".claude/settings.json").read_text())["permissions"] == settings["permissions"]
        assert 'keep-user-dependencies' in (root / "package.json").read_text()
        launcher_version = run([root / ".neurath/run", "--version"]).strip()
        assert launcher_version == target
        recovered = cli("releases", "recover")
        assert recovered["operation"]["phase"] == "recovered"
        assert run([root / ".neurath/run", "--version"]).strip() == current
        assert reporting.read_bytes() == reporting_before
        assert cli("releases", "notice") is None
        assert cli("releases", "check", "--force", mode="offline")["status"] == "unavailable"
        assert cli("releases", "check")["status"] == "unavailable"
        assert cli("releases", "notice") is None
        report = dict(status="passed", wheel=wheel.name,
            wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
            source_access="denied in installed CLI driver", transport="simulated public release responses only",
            fixture_version=target, installation_record=installed["id"],
            checks=["CLI consent flag", "no consent refusal", "decline", "defer", "restart persistence",
                    "one-time notice", "separate wheel runtime", "exact installed version",
                    "user settings and dependencies", "upstream reporting consent",
                    "per-draft contribution approval", "record restore", "launcher rollback",
                    "offline nonblocking cache"],
            host_activation="unverified; protocol simulation is not native host observation")
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(dict(status="passed", checks=len(report["checks"]), report=str(output))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    validate(args.wheel.resolve(), args.output.resolve())
