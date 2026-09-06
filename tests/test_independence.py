"""Neurath is a kit with its own authority, not a project-specific projection."""

import json
import subprocess
import sys

from neurath.install.transaction import apply_plan, make_plan
from neurath.install.projection import PROFILES, asset_files
from neurath.resources import PACKAGE


def test_distribution_has_no_source_project_payload_or_namespace():
    forbidden = (b"amber", b"spakky", b"E5presso/")
    violations = []
    for path in PACKAGE.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(PACKAGE).as_posix()
        if path.name in {"upstream.tar.gz", "extraction.json"}:
            violations.append(relative)
            continue
        if any(word.lower() in path.read_bytes().lower() for word in forbidden):
            violations.append(relative)
    assert not violations, "Source-project payload in distribution: " + ", ".join(violations[:30])


def test_installed_assets_are_project_neutral():
    assert PROFILES == ("generic",)
    assets = asset_files("generic", ["codex", "claude-code"])
    forbidden = (
        b"amber",
        b"spakky",
        b"E5presso/",
        b"apps/backend/services/",
        b"apps/local-surface",
        b"scripts.monorepo_cli",
        b"uv run pyrefly",
    )
    forbidden += tuple(text.encode() for text in (
        "기본 한국어", "한국어 metadata audit", "GitHub Issue-only tracking",
        "Neurath monorepo", "Neurath는 SDD",
    ))
    violations = [
        name
        for name, (content, _) in assets.items()
        if name != ".neurath/run" and any(word.lower() in content.lower() for word in forbidden)
    ]
    assert not violations, "Source policy in installed assets: " + ", ".join(violations[:30])


def test_review_personas_do_not_supply_unbound_python_policies():
    assets = asset_files("generic", ["codex"])
    for name in ("type", "naming"):
        text = assets[f".agents/skills/review-code/personas/{name}.md"][0].decode()
        assert "python-code.md" not in text
        assert "대상 프로젝트" in text
        assert "I*` 접두사로 정의해야" not in text
        assert "TypedDict` 사용 (BaseModel로 대체" not in text


def test_runtime_emits_only_kit_namespace(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    apply_plan(tmp_path, make_plan(tmp_path))
    result = subprocess.run(
        [sys.executable, "-I", "-m", "neurath", "--root", str(tmp_path), "hook", "--host", "codex"],
        input=json.dumps(
            {
                "session_id": "independent-test",
                "hook_event_name": "SessionStart",
                "source": "startup",
                "cwd": str(tmp_path),
            }
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "amber" not in (result.stdout + result.stderr).lower()
    assert "neurath" in result.stdout.lower()


def test_integrity_detects_added_and_modified_kit_code(tmp_path):
    import hashlib

    from neurath.doctor import integrity

    module = tmp_path / "runtime.py"
    module.write_text("VALUE = 1\n")
    manifest = {
        "schema": 1,
        "files": {"runtime.py": hashlib.sha256(module.read_bytes()).hexdigest()},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert integrity(tmp_path)["status"] == "passed"
    module.write_text("VALUE = 2\n")
    assert integrity(tmp_path)["status"] == "failed"
    module.write_text("VALUE = 1\n")
    (tmp_path / "unexpected.py").write_text("VALUE = 3\n")
    assert integrity(tmp_path)["status"] == "failed"
    (tmp_path / "unexpected.py").unlink()
    module.unlink()
    assert integrity(tmp_path)["status"] == "failed"


def test_old_project_profile_is_rejected_before_changes(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    result = subprocess.run(
        [sys.executable, "-I", "-m", "neurath", "setup", str(tmp_path), "--profile", "amber"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert not (tmp_path / ".neurath").exists()


def test_configured_verifier_uses_target_command_and_checks_real_execution(tmp_path):
    from neurath.runtime.engine import activate

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "check.py").write_text("print('check actually ran')\n")
    (tmp_path / ".neurath").mkdir()
    (tmp_path / ".neurath/project.json").write_text(
        json.dumps({"verification": {"check": {"argv": [sys.executable, "check.py"]}}})
    )
    activate(tmp_path)
    from scripts.agent_harness.harness_incident import _execute_regression_command
    from scripts.agent_harness.verification_runner import VerificationKind, VerificationRequest

    request = VerificationRequest(VerificationKind.CHECK)
    assert request.commands == (".neurath/run verify check",)
    process, _ = _execute_regression_command(tmp_path, request.commands[0])
    assert process.stdout.strip() == b"check actually ran"


def test_metadata_conventions_are_opt_in():
    from neurath.runtime.engine import activate

    activate()
    from scripts.skill_harness.github_metadata_language import GitHubMetadataLanguageAuditor

    auditor = GitHubMetadataLanguageAuditor()
    english = auditor.audit("Fix the installer", "## Summary\nPreserve settings.")
    assert english.passes(
        require_title_issue_prefix=False, require_commit_subject_issue_prefix=False
    )
    assert "policy_passed=true" in english.evidence()
    korean_policy = auditor.audit("Fix the installer", "English body", language_policy="ko")
    assert not korean_policy.passes(
        require_title_issue_prefix=False, require_commit_subject_issue_prefix=False
    )
    assert "policy_passed=false" in korean_policy.evidence()


def test_portable_static_checks_accept_installed_target_and_detect_drift(tmp_path):
    from neurath.runtime.engine import activate

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "AGENTS.md").write_text("Use the project's own conventions.\n")
    apply_plan(tmp_path, make_plan(tmp_path))
    activate(tmp_path)
    from scripts.agent_harness.checker import AgentHarnessChecker
    from scripts.skill_harness.checker import SkillHarnessChecker

    assert not AgentHarnessChecker(tmp_path).check()
    assert not SkillHarnessChecker(tmp_path).check()
    asset = tmp_path / ".neurath/policy.md"
    asset.write_text("corrupt policy\n")
    assert AgentHarnessChecker(tmp_path).check()
    assert SkillHarnessChecker(tmp_path).check()


def test_typed_pytest_binding_cannot_substitute_unrelated_pass_or_skip(tmp_path):
    import pytest

    from neurath.runtime.engine import activate

    activate(tmp_path)
    from scripts.agent_harness.harness_incident import (
        HarnessIncidentValidationError,
        _execute_regression_command,
    )

    (tmp_path / ".neurath").mkdir()
    source = tmp_path / "test_bound.py"
    source.write_text(
        'import pytest\ndef test_required(): pytest.skip("not executed")\ndef test_other(): pass\n'
    )
    config = tmp_path / ".neurath/project.json"

    def bind(extra=()):
        config.write_text(
            json.dumps(
                {"verification": {"pytest": {"argv": [sys.executable, "-m", "pytest", *extra]}}}
            )
        )

    bind(["-k", "test_other", "test_bound.py"])
    with pytest.raises(HarnessIncidentValidationError):
        _execute_regression_command(
            tmp_path, ".neurath/run verify pytest --node test_bound.py::test_required"
        )
    bind()
    with pytest.raises(HarnessIncidentValidationError):
        _execute_regression_command(
            tmp_path,
            ".neurath/run verify pytest --node test_bound.py::test_required --node test_bound.py::test_other",
        )
    source.write_text("def test_required(): pass\ndef test_other(): pass\n")
    result, _ = _execute_regression_command(
        tmp_path, ".neurath/run verify pytest --node test_bound.py::test_required"
    )
    assert result.returncode == 0


def test_typed_binding_honors_output_requirement_and_timeout(tmp_path):
    import pytest

    from neurath.runtime.engine import activate

    activate(tmp_path)
    from scripts.agent_harness.harness_incident import (
        HarnessIncidentValidationError,
        _execute_regression_command,
    )

    (tmp_path / ".neurath").mkdir()
    config = tmp_path / ".neurath/project.json"
    config.write_text(
        json.dumps(
            {
                "verification": {
                    "check": {
                        "argv": [sys.executable, "-c", 'print("wrong")'],
                        "stdout_contains": "required",
                    }
                }
            }
        )
    )
    with pytest.raises(HarnessIncidentValidationError):
        _execute_regression_command(tmp_path, ".neurath/run verify check")
    config.write_text(
        json.dumps(
            {
                "verification": {
                    "check": {
                        "argv": [sys.executable, "-c", "import time; time.sleep(5)"],
                        "timeout_seconds": 0.05,
                    }
                }
            }
        )
    )
    with pytest.raises(HarnessIncidentValidationError):
        _execute_regression_command(tmp_path, ".neurath/run verify check")


def test_harness_inventory_tracks_kit_configuration_and_uses_local_artifacts(tmp_path):
    from neurath.runtime.engine import activate

    activate(tmp_path)
    from scripts.skill_harness.harness_source_inventory import HarnessSourceInventory

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".neurath/local/runs/test").mkdir(parents=True)
    (tmp_path / ".neurath/project.json").write_text("{}")
    artifact = tmp_path / ".neurath/local/runs/test/inventory.json"
    artifact.write_text("{}")
    inventory = HarnessSourceInventory(tmp_path)
    files = {item["path"] for item in inventory.build(())["files"]}
    assert ".neurath/project.json" in files
    assert ".neurath/local/runs/test/inventory.json" not in files
    assert inventory._manifest_path(".neurath/local/runs/test/inventory.json") == artifact


def test_installed_catalog_links_resolve_to_managed_assets():
    import re
    import posixpath

    assets = asset_files("generic", ["codex", "claude-code"])
    for name in (".neurath/reference/HARNESS_INDEX.md", ".neurath/reference/HARNESS_AUDIT.md"):
        text = assets[name][0].decode()
        for link in re.findall(r"\]\(([^)]+)\)", text):
            if link.startswith(("http:", "https:", "#")):
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), link))
            assert target in assets, f"{name}: broken catalog link {link}"


def test_direct_capability_entrypoint_has_no_product_defaults(tmp_path):
    from neurath.runtime.engine import activate
    activate(tmp_path)
    from scripts.agent_harness.capability_retirement_hook import CapabilityRetirementHookApplication
    policy = CapabilityRetirementHookApplication()
    assert not policy._PROTECTED_CONNECTORS
    assert policy._PROTECTED_PATHS == ('.neurath',)
