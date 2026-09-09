"""The short setup path must retain the transactional install guarantees."""

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from neurath.install.transaction import make_plan, read_state

SOURCE = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "project's space"
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "AGENTS.md").write_text("Keep my project rules.\n")
    (root / "package.json").write_text('{"scripts":{"test":"do-not-run"}}\n')
    return root


def run_setup(root, *args):
    return subprocess.run(
        [sys.executable, "-I", "-m", "neurath", "setup", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_setup_installs_checks_and_reports_remaining_host_activation(repo):
    (repo / ".claude").mkdir()
    settings = {"permissions": {"deny": ["Bash(rm *)"]}, "model": "keep-this-model"}
    (repo / ".claude/settings.json").write_text(json.dumps(settings))
    result = run_setup(repo, "--json")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "passed"
    assert report["doctor"]["placement"]["status"] == "passed"
    assert report["doctor"]["distribution"]["status"] == "passed"
    assert report["doctor"]["protocol"]["codex"]["status"] == "passed"
    assert report["doctor"]["protocol"]["claude-code"]["status"] == "passed"
    assert report["doctor"]["host_activation"]["status"] == "unverified"
    assert any("/hooks" in step for step in report["next_steps"])
    assert any("project.json" in step for step in report["next_steps"])
    assert (repo / "AGENTS.md").read_text().startswith("Keep my project rules.\n")
    installed = json.loads((repo / ".claude/settings.json").read_text())
    assert installed["permissions"] == settings["permissions"]
    assert installed["model"] == settings["model"]
    assert (repo / "package.json").read_text() == '{"scripts":{"test":"do-not-run"}}\n'
    assert not (repo / ".venv").exists()
    assert not (repo / "neurath-plan.json").exists()
    repeat = run_setup(repo, "--json")
    assert repeat.returncode == 0, repeat.stderr
    assert json.loads(repeat.stdout)["receipt"]["changed"] == 0


def test_setup_dry_run_has_no_target_writes_or_private_plan_leak(repo):
    before = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    result = run_setup(repo, "--dry-run", "--host", "codex", "--json")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "planned"
    assert report["hosts"] == ["codex"]
    assert report["changes"]
    assert "Keep my project rules" not in result.stdout
    assert "before" not in report["changes"][0]
    after = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert after == before


def test_setup_preserves_host_profile_selection_and_edited_bindings(repo):
    first = run_setup(repo, "--host", "codex", "--profile", "generic", "--json")
    assert first.returncode == 0, first.stderr
    binding = '{"schema":1,"documents":{"intent":"SPEC.md"},"verification":{}}\n'
    (repo / ".neurath/project.json").write_text(binding)
    repeat = run_setup(repo)
    assert repeat.returncode == 0, repeat.stderr
    assert "Codex" in repeat.stdout
    assert "Claude Code" not in repeat.stdout
    assert read_state(repo)["hosts"] == ["codex"]
    assert read_state(repo)["profile"] == "generic"
    assert (repo / ".neurath/project.json").read_text() == binding
    assert not (repo / "CLAUDE.md").exists()


def test_setup_conflict_does_not_partially_install(repo):
    conflict = repo / ".agents/skills/debug/SKILL.md"
    conflict.parent.mkdir(parents=True)
    conflict.write_text("user skill")
    result = run_setup(repo)
    assert result.returncode != 0
    assert "conflict" in result.stderr
    assert read_state(repo) is None
    assert conflict.read_text() == "user skill"
    assert not (repo / ".codex/hooks.json").exists()


def test_setup_failed_diagnostics_do_not_claim_success(repo, monkeypatch, capsys):
    from neurath import cli, doctor

    monkeypatch.setattr(doctor, "protocol_smoke", lambda: {"codex": {"status": "failed"}})
    assert cli.main(["setup", str(repo), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "failed"
    assert report["receipt"]["changed"] > 0
    assert report["doctor"]["protocol"]["codex"]["status"] == "failed"


def test_setup_invalid_distribution_does_not_write(repo, monkeypatch, capsys):
    from neurath import cli, doctor

    monkeypatch.setattr(doctor, "integrity", lambda: {"status": "failed", "errors": ["x"]})
    assert cli.main(["setup", str(repo)]) != 0
    assert read_state(repo) is None
    assert "integrity" in capsys.readouterr().err


def test_setup_matches_existing_install_plan(repo):
    expected = make_plan(repo, hosts=["codex"])
    result = run_setup(repo, "--host", "codex", "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["receipt"]["id"] == expected["id"]


@pytest.fixture
def fake_uv(tmp_path):
    """Observe bootstrap commands without changing the user's actual tool install."""
    bin_dir = tmp_path / "fake bin"
    bin_dir.mkdir()
    tool_bin = tmp_path / "tool bin"
    tool_bin.mkdir()
    log = tmp_path / "calls.jsonl"
    recorder = (
        f"#!{sys.executable}\nimport json, os, sys\n"
        "with open(os.environ['TEST_SETUP_LOG'], 'a') as f:\n"
        "    f.write(json.dumps([os.path.basename(sys.argv[0]), *sys.argv[1:]]) + '\\n')\n"
    )
    entry_code = (
        "import json, os, sys\n"
        "with open(os.environ['TEST_SETUP_LOG'], 'a') as f:\n"
        "    f.write(json.dumps(['neurath', *sys.argv[1:]]) + '\\n')\n"
        "if os.environ.get('TEST_NEURATH_REAL') == '1':\n"
        "    from neurath.cli import main\n"
        "    raise SystemExit(main())\n"
        "raise SystemExit(int(os.environ.get('TEST_NEURATH_EXIT', '0')))\n"
    )
    (bin_dir / "uv").write_text(recorder + f'''
import pathlib, shlex, shutil, venv
arguments = sys.argv[1:]
if arguments[-3:] == ['tool', 'dir', '--bin']:
    print(os.environ['UV_TOOL_BIN_DIR'])
elif arguments[-2:] == ['tool', 'dir']:
    print(os.environ['UV_TOOL_DIR'])
elif 'run' in arguments:
    index = arguments.index('python')
    os.execv(sys.executable, [sys.executable, *arguments[index + 1:]])
elif 'install' in arguments:
    code = int(os.environ.get('TEST_UV_INSTALL_EXIT', '0'))
    if code:
        raise SystemExit(code)
    root = pathlib.Path(os.environ['UV_TOOL_DIR'])
    runtime = root / 'neurath'
    venv.EnvBuilder(with_pip=False, symlinks=True).create(runtime)
    source = pathlib.Path(arguments[arguments.index('--from') + 1])
    site = next((runtime / 'lib').glob('python*/site-packages'))
    shutil.copytree(source / 'src/neurath', site / 'neurath', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    executable = runtime / 'bin/neurath'
    executable.write_text('#!/bin/sh\\nexec ' + shlex.quote(str(runtime / 'bin/python')) + ' -I -c ' + shlex.quote({entry_code!r}) + ' "$@"\\n')
    executable.chmod(0o755)
    scripts = pathlib.Path(os.environ['UV_TOOL_BIN_DIR'])
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / 'neurath').symlink_to(executable)
''')
    (bin_dir / "uv").chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    env.update(
        TEST_SETUP_LOG=str(log),
        UV_TOOL_BIN_DIR=str(tool_bin),
        UV_TOOL_DIR=str(tmp_path / "tool environments"),
    )
    return env, log


def _bootstrap_source(tmp_path):
    source = tmp_path / "independent source's path"
    source.mkdir()
    shutil.copytree(SOURCE / "src", source / "src",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (source / "tools").mkdir()
    shutil.copy2(SOURCE / "tools/setup_runtime.py", source / "tools/setup_runtime.py")
    for name in ("setup", "pyproject.toml", "README.md"):
        shutil.copy2(SOURCE / name, source / name)
    return source


def _next_runtime_source(source):
    module = source / "src/neurath/__init__.py"
    module.write_bytes(module.read_bytes() + b"\n# Independent runtime generation.\n")
    manifest = source / "src/neurath/manifest.json"
    contents = json.loads(manifest.read_text())
    contents["files"]["__init__.py"] = hashlib.sha256(module.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(contents, indent=2, sort_keys=True) + "\n")


def _bootstrap(source, project, environment, *options):
    return subprocess.run(["bash", str(source / "setup"), str(project), *options],
                          env=environment, cwd=project, capture_output=True, text=True)


def _project_runtime(project):
    line = (project / ".neurath/run").read_text().splitlines()[-1]
    python = Path(shlex.split(line)[1])
    result = subprocess.run([str(python), "-I", "-c",
                             "from neurath.resources import distribution_id; print(distribution_id())"],
                            capture_output=True, text=True, check=True)
    return python, result.stdout.strip()


@pytest.mark.parametrize("second_mode", ["success", "conflict", "dry-run"])
def test_bootstrap_other_project_preserves_first_runtime(repo, fake_uv, tmp_path, second_mode):
    env, log = fake_uv
    env["TEST_NEURATH_REAL"] = "1"
    source = _bootstrap_source(tmp_path)
    first = _bootstrap(source, repo, env, "--json")
    assert first.returncode == 0, first.stderr
    before_runtime = _project_runtime(repo)
    before_files = {name: (repo / name).read_bytes()
                    for name in (".neurath/run", ".neurath/install.json", ".mcp.json")}
    stable = Path(env["UV_TOOL_BIN_DIR"]) / "neurath"
    before_command = stable.resolve()
    _next_runtime_source(source)
    second = tmp_path / "second project"
    subprocess.run(["git", "init", "-q", str(second)], check=True)
    conflict = second / ".agents/skills/debug/SKILL.md"
    if second_mode == "conflict":
        conflict.parent.mkdir(parents=True)
        conflict.write_text("User skill\n")
    options = ["--json"] + (["--dry-run"] if second_mode == "dry-run" else [])
    attempted = _bootstrap(source, second, env, *options)
    assert _project_runtime(repo) == before_runtime
    assert all((repo / name).read_bytes() == content for name, content in before_files.items())
    diagnosis = subprocess.run([str(repo / ".neurath/run"), "doctor"], capture_output=True, text=True)
    assert diagnosis.returncode == 0, diagnosis.stderr
    assert json.loads(diagnosis.stdout)["placement"]["status"] == "passed"
    if second_mode == "success":
        assert attempted.returncode == 0, attempted.stderr
        assert _project_runtime(second) != before_runtime
        assert stable.resolve() != before_command
    else:
        assert stable.resolve() == before_command
        assert read_state(second) is None
        if second_mode == "conflict":
            assert attempted.returncode != 0
            assert conflict.read_text() == "User skill\n"
        else:
            assert attempted.returncode == 0, attempted.stderr
            assert json.loads(attempted.stdout)["status"] == "planned"


def test_bootstrap_packaged_readme_change_uses_a_new_environment(repo, fake_uv, tmp_path):
    env, _ = fake_uv
    env["TEST_NEURATH_REAL"] = "1"
    source = _bootstrap_source(tmp_path)
    first = _bootstrap(source, repo, env, "--json")
    assert first.returncode == 0, first.stderr
    original_runtime = _project_runtime(repo)
    readme = source / "README.md"
    readme.write_bytes(readme.read_bytes() + b"\nUpdated package description.\n")
    updated = _bootstrap(source, repo, env, "--json")
    assert updated.returncode == 0, updated.stderr
    assert _project_runtime(repo)[0] != original_runtime[0]
    assert original_runtime[0].is_file()


def test_bootstrap_same_content_never_reinstalls_runtime(repo, fake_uv, tmp_path):
    env, log = fake_uv
    env["TEST_NEURATH_REAL"] = "1"
    source = _bootstrap_source(tmp_path)
    first = _bootstrap(source, repo, env, "--json")
    assert first.returncode == 0, first.stderr
    runtime = _project_runtime(repo)
    stable = Path(env["UV_TOOL_BIN_DIR"]) / "neurath"
    link_identity = stable.lstat().st_ino
    repeated = _bootstrap(source, repo, env, "--json")
    assert repeated.returncode == 0, repeated.stderr
    assert json.loads(repeated.stdout)["receipt"]["changed"] == 0
    assert _project_runtime(repo) == runtime
    assert stable.lstat().st_ino == link_identity
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    installs = [call for call in calls if "install" in call]
    assert len(installs) == 1
    assert "--reinstall" not in installs[0] and "--force" not in installs[0]


def _installed_files(project):
    result = {}
    for path in project.rglob("*"):
        relative = path.relative_to(project)
        if ".git" in relative.parts or path.is_relative_to(project / ".neurath/local"):
            continue
        if path.is_symlink():
            result[str(relative)] = ("link", os.readlink(path))
        elif path.is_file():
            result[str(relative)] = ("file", path.read_bytes(), path.stat().st_mode & 0o777)
    return result


def test_bootstrap_restore_recovers_original_runtime_and_files(repo, fake_uv, tmp_path):
    env, log = fake_uv
    env["TEST_NEURATH_REAL"] = "1"
    source = _bootstrap_source(tmp_path)
    first = _bootstrap(source, repo, env, "--json")
    assert first.returncode == 0, first.stderr
    original_runtime = _project_runtime(repo)
    original_files = _installed_files(repo)
    _next_runtime_source(source)
    updated = _bootstrap(source, repo, env, "--json")
    assert updated.returncode == 0, updated.stderr
    updated_runtime = _project_runtime(repo)
    assert updated_runtime != original_runtime
    installation_id = json.loads(updated.stdout)["receipt"]["id"]
    restored = subprocess.run([str(updated_runtime[0]), "-I", "-m", "neurath", "--root", str(repo),
                               "restore", installation_id], capture_output=True, text=True)
    assert restored.returncode == 0, restored.stderr
    assert _installed_files(repo) == original_files
    assert _project_runtime(repo) == original_runtime
    assert updated_runtime[0].is_file()
    diagnosis = subprocess.run([str(repo / ".neurath/run"), "doctor"], capture_output=True, text=True)
    assert diagnosis.returncode == 0, diagnosis.stderr
    assert json.loads(diagnosis.stdout)["placement"]["status"] == "passed"


def test_doctor_rejects_installation_from_a_different_runtime(repo, monkeypatch):
    from neurath import doctor
    from neurath.install.transaction import apply_plan
    apply_plan(repo, make_plan(repo))
    installed_distribution = read_state(repo)["distribution"]
    different = "0" * 64 if installed_distribution != "0" * 64 else "1" * 64
    monkeypatch.setattr(doctor, "distribution_id", lambda: different)
    report = doctor.doctor(repo)
    assert report["placement"]["status"] == "failed"
    assert not doctor.passed(report)
    assert any("distribution" in problem for problem in report["placement"]["errors"])


def test_bootstrap_uses_persistent_tool_and_absolute_executable(repo, fake_uv):
    env, log = fake_uv
    result = subprocess.run(
        ["bash", str(SOURCE / "setup"), str(repo), "--host", "codex"],
        env=env,
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    install = next(call for call in calls if "install" in call)
    assert "--no-config" in install
    assert install[install.index("--python") + 1] == "3.14"
    assert install[install.index("--from") + 1] == str(SOURCE)
    assert "--editable" not in install
    assert "--reinstall" not in install and "--force" not in install
    assert "neurath" == install[-1]
    assert calls[-1] == ["neurath", "setup", str(repo.resolve()), "--host", "codex"]
    assert not (repo / ".venv").exists()


@pytest.mark.parametrize("target", [None, "missing", "source"])
def test_bootstrap_rejects_bad_target_before_install(repo, fake_uv, target):
    env, log = fake_uv
    args = [] if target is None else [str(SOURCE if target == "source" else repo / "missing")]
    result = subprocess.run(
        ["bash", str(SOURCE / "setup"), *args],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert not log.exists()


def test_bootstrap_stops_when_tool_installation_fails(repo, fake_uv):
    env, log = fake_uv
    env["TEST_UV_INSTALL_EXIT"] = "7"
    result = subprocess.run(
        ["bash", str(SOURCE / "setup"), str(repo)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 7, result.stderr
    assert all(json.loads(line)[0] != "neurath" for line in log.read_text().splitlines())


@pytest.mark.parametrize("mode", ["success", "download-failed", "disabled"])
def test_bootstrap_missing_uv_is_controlled_and_keeps_shell_profiles(repo, fake_uv, mode):
    env, log = fake_uv
    restricted_bin = repo.parent / "bootstrap bin"
    restricted_bin.mkdir()
    for name in ("git", "uname", "dirname", "mktemp", "sh", "rm", "mkdir", "cp", "chmod"):
        (restricted_bin / name).symlink_to(shutil.which(name))
    uv_source = Path(env["PATH"].split(":")[0]) / "uv"
    curl = restricted_bin / "curl"
    curl.write_text(
        f"#!{sys.executable}\nimport os, pathlib, sys\n"
        "if os.environ.get('TEST_DOWNLOAD_FAIL') == '1': sys.exit(22)\n"
        "script = '''set -eu\n"
        'test \\"$UV_NO_MODIFY_PATH\\" = 1\n'
        'mkdir -p \\"$UV_INSTALL_DIR\\"\n'
        'cp \\"$TEST_BOOTSTRAP_UV\\" \\"$UV_INSTALL_DIR/uv\\"\n'
        "chmod +x \\\"$UV_INSTALL_DIR/uv\\\"\n'''\n"
        "pathlib.Path(sys.argv[sys.argv.index('--output') + 1]).write_text(script)\n"
    )
    curl.chmod(0o755)
    uv_destination = repo.parent / "downloaded uv"
    env.update(
        PATH=str(restricted_bin),
        UV_INSTALL_DIR=str(uv_destination),
        TEST_BOOTSTRAP_UV=str(uv_source),
    )
    if mode == "disabled":
        env["NEURATH_NO_BOOTSTRAP"] = "1"
    if mode == "download-failed":
        env["TEST_DOWNLOAD_FAIL"] = "1"
    result = subprocess.run(
        ["/bin/bash", str(SOURCE / "setup"), str(repo)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if mode == "success":
        assert result.returncode == 0, result.stderr
        assert (uv_destination / "uv").is_file()
        assert json.loads(log.read_text().splitlines()[-1])[0] == "neurath"
    else:
        assert result.returncode != 0
        assert not log.exists()
        assert not uv_destination.exists()


def test_explicit_self_install_uses_an_independent_tool_environment(fake_uv):
    env,log=fake_uv
    result=subprocess.run(['bash',str(SOURCE/'setup'),'--self','--host','codex'],env=env,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    calls=[json.loads(line) for line in log.read_text().splitlines()]
    assert calls[-1]==['neurath','setup',str(SOURCE.resolve()),'--host','codex']
    assert '--editable' not in calls[0]
