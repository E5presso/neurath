"""Prepare an immutable runtime, then install it in the selected project."""

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VERIFY = """import json
from neurath.doctor import integrity
from neurath.resources import distribution_id
print(json.dumps({'distribution': distribution_id(), 'integrity': integrity()}))
"""


def snapshot(source):
    package = source / "src/neurath"
    paths = []
    for path in sorted(package.rglob("*")):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise ValueError("source package contains a symlink")
        if path.is_file():
            paths.append(path)
    if not paths:
        raise ValueError("source package is missing")
    distribution = hashlib.sha256()
    key = hashlib.sha256(b"neurath-tool-environment-v1\0python-3.14\0")
    for path in paths:
        data = path.read_bytes()
        distribution.update(path.relative_to(package).as_posix().encode())
        distribution.update(data)
    for path in [source / "pyproject.toml", source / "README.md", *paths]:
        if path.is_symlink():
            raise ValueError("build input contains a symlink")
        name = path.relative_to(source).as_posix().encode()
        data = path.read_bytes()
        key.update(len(name).to_bytes(8, "big") + name)
        key.update((path.stat().st_mode & 0o777).to_bytes(4, "big"))
        key.update(len(data).to_bytes(8, "big") + data)
    return key.hexdigest(), distribution.hexdigest()


def command(argv, *, env=None, capture=False):
    return subprocess.run(
        [str(value) for value in argv], env=env, text=True, check=True,
        stdout=subprocess.PIPE if capture else sys.stderr,
        stderr=subprocess.PIPE if capture else None,
    )


def verify(runtime, expected):
    result = command([runtime / "neurath/bin/python", "-I", "-c", VERIFY], capture=True)
    report = json.loads(result.stdout)
    if report.get("distribution") != expected or report.get("integrity", {}).get("status") != "passed":
        raise ValueError("persistent runtime does not match the validated source")


def managed_link(path, tools, versions):
    if not path.exists() and not path.is_symlink():
        return True
    if not path.is_symlink():
        return False
    target = path.resolve()
    if target == (tools / "neurath/bin/neurath").resolve():
        return True
    try:
        parts = target.relative_to(versions).parts
    except ValueError:
        return False
    return (len(parts) == 4 and re.fullmatch(r"[a-f0-9]{64}", parts[0]) is not None
            and parts[1:] == ("neurath", "bin", "neurath"))


def publish(path, executable):
    if path.is_symlink() and path.resolve() == executable.resolve():
        return
    fd, temporary = tempfile.mkstemp(prefix=".neurath-", dir=path.parent)
    os.close(fd)
    temporary = Path(temporary)
    temporary.unlink()
    try:
        temporary.symlink_to(executable)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def bootstrap(uv, source, target, args):
    tools = Path(command([uv, "--no-config", "tool", "dir"], capture=True).stdout.strip()).resolve()
    binaries = Path(command([uv, "--no-config", "tool", "dir", "--bin"], capture=True).stdout.strip()).resolve()
    versions = tools.with_name(tools.name + "-neurath-versions")
    versions.mkdir(parents=True, exist_ok=True)
    binaries.mkdir(parents=True, exist_ok=True)
    key, expected = snapshot(source)
    runtime = versions / key
    ready = runtime / "ready.json"
    executable = runtime / "neurath/bin/neurath"
    stable = binaries / "neurath"
    # Serialize the shared command publication as well as candidate creation.
    with (versions / ".bootstrap.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not managed_link(stable, tools, versions):
            raise ValueError("existing neurath command is not managed by this installer")
        if snapshot(source) != (key, expected):
            raise ValueError("source changed while preparing runtime")
        record = {"schema": 1, "key": key, "distribution": expected}
        if ready.is_file():
            if json.loads(ready.read_text()) != record:
                raise ValueError("persistent runtime readiness record differs")
            verify(runtime, expected)
        else:
            if runtime.exists():
                raise ValueError("incomplete persistent runtime: inspect " + str(runtime))
            environment = dict(os.environ, UV_TOOL_DIR=str(runtime), UV_TOOL_BIN_DIR=str(runtime / "bin"))
            try:
                command([uv, "--no-config", "--no-cache", "tool", "install", "--python", "3.14", "--from", source, "neurath"], env=environment)
                verify(runtime, expected)
                if snapshot(source) != (key, expected):
                    raise ValueError("source changed while installing runtime")
                ready.write_text(json.dumps(record, sort_keys=True) + "\n")
            except (OSError, ValueError, subprocess.CalledProcessError):
                # This candidate has not been published to any project or global command.
                shutil.rmtree(runtime, ignore_errors=True)
                raise
        if not executable.is_file():
            raise ValueError("persistent runtime executable is missing")
        if snapshot(source) != (key, expected):
            raise ValueError("source changed before project setup")
        result = subprocess.run([str(executable), "setup", str(target), *args], check=False)
        if result.returncode == 0 and "--dry-run" not in args:
            publish(stable, executable)
            print("다음부터 사용할 명령: " + str(stable), file=sys.stderr)
        return result.returncode


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) < 3:
        print("neurath setup: uv, source and target are required", file=sys.stderr)
        return 2
    uv, source, target, *options = arguments
    try:
        return bootstrap(uv, Path(source).resolve(), Path(target).resolve(), options)
    except subprocess.CalledProcessError as error:
        if error.stderr:
            print(error.stderr, file=sys.stderr, end="")
        return error.returncode if error.returncode > 0 else 128 - error.returncode
    except (OSError, ValueError) as error:
        print("neurath setup: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
