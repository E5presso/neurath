"""Stage verified wheels and use the existing transactional installer unchanged."""

import hashlib
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

from neurath.install.transaction import (
    STATE, canonical, git_dir, installation_state_matches, read_state, snapshot,
)
from neurath.reporting import Reporting
from neurath.updates import MAX_WHEEL, download_asset


def command(argv):
    result = subprocess.run([str(arg) for arg in argv], capture_output=True, text=True,
                            timeout=120, check=False)
    if result.returncode:
        raise ValueError("release command failed: " + (result.stderr + result.stdout)[-1500:])
    return result.stdout


def runtime_command(python, root, *args):
    return json.loads(command([python, "-I", "-m", "neurath", "--root", root, *args]))


def wheel_check(data, offer):
    if hashlib.sha256(data).hexdigest() != offer["sha256"] or len(data) != offer["size"]:
        raise ValueError("release wheel digest or size mismatch")
    with zipfile.ZipFile(io.BytesIO(data)) as wheel:
        names = wheel.namelist()
        if (len(names) != len(set(names)) or sum(x.file_size for x in wheel.infolist()) > MAX_WHEEL * 4
                or any(PurePosixPath(n).is_absolute() or ".." in PurePosixPath(n).parts for n in names)
                or any(not n.startswith(("neurath/", f"neurath-{offer['version']}.dist-info/")) for n in names)):
            raise ValueError("unsupported wheel layout")
        metadata = BytesParser().parsebytes(wheel.read(f"neurath-{offer['version']}.dist-info/METADATA"))
        # Keep the known runtime dependency boundary explicit. Resolve these only
        # into the candidate tool environment, never the user's project.
        dependencies = metadata.get_all("Requires-Dist") or []
        if (metadata["Name"] != "neurath" or metadata["Version"] != offer["version"]
                or any(value.replace(" ", "") != "claude-agent-sdk<0.3,>=0.2.152"
                       for value in dependencies)):
            raise ValueError("wheel identity or dependency contract changed")
        spec = json.loads(wheel.read("neurath/manifest.json"))
        actual = {n.removeprefix("neurath/"): hashlib.sha256(wheel.read(n)).hexdigest()
                  for n in names if n.startswith("neurath/") and not n.endswith("/")
                  and n != "neurath/manifest.json"}
        if spec.get("schema") != 1 or spec.get("files") != actual:
            raise ValueError("wheel manifest integrity mismatch")


def verify(python, root, offer, expected=None):
    if command([python, "-I", "-m", "neurath", "--version"]).strip() != offer["version"]:
        raise ValueError("runtime version differs from selected release")
    result = runtime_command(python, root, "integrity")
    if result["status"] != "passed":
        raise ValueError("candidate runtime integrity failed")
    distribution = command([python, "-I", "-c",
                            "from neurath.resources import distribution_id; print(distribution_id())"]).strip()
    if expected is not None and distribution != expected:
        raise ValueError("prepared runtime changed")
    return distribution


def prepare(root, directory, offer):
    Reporting(root).status()  # Existing consent must remain readable and untouched.
    data = download_asset(offer["asset_id"])
    wheel_check(data, offer)
    stage = Path(tempfile.mkdtemp(prefix="candidate-", dir=directory))
    wheel = stage / offer["name"]
    wheel.write_bytes(data)
    python = stage / "runtime/bin/python"
    # Project dependencies/settings and the currently running tool environment are untouched.
    command([sys.executable, "-I", "-m", "venv", "--without-pip", stage / "runtime"])
    command(["uv", "--no-config", "--no-cache", "pip", "install", "--python", python, wheel])
    distribution = verify(python, root, offer)
    plan_path = stage / "plan.json"
    runtime_command(python, root, "plan", "--action", "update", "--output", plan_path)
    plan = json.loads(plan_path.read_text())
    if plan["distribution"] != distribution:
        raise ValueError("plan differs from candidate runtime")
    return dict(phase="prepared", offer_id=offer["id"], stage=stage.name,
                distribution=distribution, plan_id=plan["id"],
                changes=[dict(path=x["path"], action="remove" if x["after"] is None else "write")
                         for x in plan["changes"]])


def paths(directory, operation):
    name = operation["stage"]
    if not isinstance(name, str) or not name.startswith("candidate-") or Path(name).name != name:
        raise ValueError("invalid candidate path")
    stage = directory / name
    if stage.is_symlink() or not stage.resolve().is_relative_to(directory.resolve()):
        raise ValueError("candidate path escape")
    return stage / "runtime/bin/python", stage / "plan.json"


def plan_read(path, operation, root):
    plan = json.loads(path.read_text())
    digest = hashlib.sha256(canonical({k: v for k, v in plan.items() if k != "id"}).encode()).hexdigest()
    if (digest != operation["plan_id"] or plan["id"] != digest or plan["root"] != str(root)
            or plan["distribution"] != operation["distribution"] or plan["action"] != "update"):
        raise ValueError("prepared installation plan changed")
    return plan


def apply(root, directory, offer, operation):
    python, plan_path = paths(directory, operation)
    plan_read(plan_path, operation, root)
    verify(python, root, offer, operation["distribution"])
    reporting = Reporting(root)
    before_reporting = reporting._read()
    receipt = runtime_command(python, root, "apply", plan_path)
    if receipt["id"] != operation["plan_id"]:
        raise ValueError("installation record differs from prepared plan")
    installed = read_state(root)
    if installed["version"] != offer["version"] or installed["distribution"] != operation["distribution"]:
        raise ValueError("installed version differs from approved release")
    report = runtime_command(python, root, "doctor", "--protocol")
    from neurath.doctor import passed
    if not passed(report):
        raise ValueError("updated installation diagnostics failed; recover the prior installation")
    if reporting._read() != before_reporting:
        raise ValueError("reporting preferences changed during update; inspect and recover")
    return dict(phase="applied", receipt=receipt["id"], doctor=report,
                host_activation="unverified; observe the next normal native host event")


def _matches_plan_files(root, plan, side):
    """Keep product/config bytes exact; validate installation state cutover."""
    for item in plan["changes"]:
        if item["path"] == STATE:
            semantic = side + "_state"
            if not installation_state_matches(root, item[side],
                    **({"expected_state": plan[semantic]} if semantic in plan else {})):
                return False
        elif snapshot(root, item["path"]) != item[side]:
            return False
    return True


def recover(root, directory, operation):
    """Conservative rollback, including a process killed before recording apply's result."""
    python, plan_path = paths(directory, operation)
    plan = plan_read(plan_path, operation, root)
    from neurath.install.state_store import InstallStateStore
    journal = InstallStateStore(root).journal()
    legacy = git_dir(root) / "neurath-journal.json"
    if journal is None and legacy.is_file():
        journal = json.loads(legacy.read_text())
    if journal is not None:
        if journal != plan:
            raise ValueError("recovery conflict: journal belongs to another installation")
        runtime_command(python, root, "recover")
    if _matches_plan_files(root, plan, "before"):
        return dict(phase="recovered")
    if not _matches_plan_files(root, plan, "after"):
        raise ValueError("recovery conflict: preserve concurrent edits and inspect installation state")
    runtime_command(python, root, "restore", operation["plan_id"])
    if not _matches_plan_files(root, plan, "before"):
        raise ValueError("rollback readback differs from previous installation")
    return dict(phase="recovered")
