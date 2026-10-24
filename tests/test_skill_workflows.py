"""기본·전문 스킬의 선택 지침·고정 정의·실제 호스트 단계와 설치 형식을 검증한다."""

import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from neurath.domain.enums.provider_kind import ProviderKind
from neurath.infrastructure.services.installation import PosixInstallationService
from neurath.infrastructure.services.skill_catalog import PosixSkillCatalogService
from tests.test_host_flow import create, delegate_review, finish_review, invoke, prepare_review
from tests.test_host_flow import host as host

NAMES = {
    "define-spec",
    "implement-spec",
    "autopilot",
    "review-spec",
    "review-code",
    "qa",
    "debug",
    "design-ui",
    "review-ui",
    "sync-design",
    "sync-docs",
    "pr-feedback",
    "finish-session",
    "update-neurath",
}


@pytest.mark.parametrize("provider", list(ProviderKind))
async def test_installed_skill_contract_matches_runner_and_preserves_user_material(
    tmp_path, provider
):
    folder = tmp_path / (".agents/skills" if provider is ProviderKind.CODEX else ".claude/skills")
    custom = folder / "project-specialist/SKILL.md"
    custom.parent.mkdir(parents=True)
    custom.write_text(
        "---\nname: project-specialist\ndescription: Project-specific operation\n---\nKeep original procedure"
    )
    catalog = PosixSkillCatalogService()
    await PosixInstallationService(catalog).install(provider, str(tmp_path), str(tmp_path / "data"))
    entries = catalog.list(str(tmp_path))
    assert {item.workflow.skill for item in entries} == NAMES
    assert custom.read_text().endswith("Keep original procedure")
    for entry in entries:
        content = (folder / entry.workflow.skill / "SKILL.md").read_text()
        assert content.startswith("---\n")
        metadata = yaml.safe_load(content.split("---\n", 2)[1])
        assert metadata["name"] == entry.workflow.skill
        assert (
            entry.use_when in metadata["description"] and entry.exclude in metadata["description"]
        )
        for text in (*entry.required_inputs, *entry.outcomes, *entry.branches):
            assert text in content
        assert "workflow show" in content and "이미 있는 작업을 선택" in content
        assert "--check done" not in content
        for phase in entry.workflow.phases:
            assert phase.key in content and phase.purpose in content
            assert all(check in content for check in phase.checks)
        if entry.workflow.skill.startswith("review-"):
            assert all(phase.evaluation is None for phase in entry.workflow.phases)
    define = next(item for item in entries if item.workflow.skill == "define-spec")
    assert "실행 순서·의존성·검증 계획" in define.workflow.phases[0].purpose
    implement = next(item for item in entries if item.workflow.skill == "implement-spec")
    assert "UI가 없으면" in implement.branches[0]
    assert "화면·접근·상호작용" in implement.workflow.phases[2].purpose


@pytest.mark.parametrize(
    "header",
    [
        "",
        "---\nname: qa\ndescription: old\n---\n",
        "---\nname: qa\ndescription: |\n  old body\nmetadata:\n  owner: user\n---\n",
    ],
)
async def test_owned_legacy_skill_metadata_updates_without_erasing_user_body(tmp_path, header):
    path = tmp_path / ".agents/skills/qa/SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        header
        + "User introduction\n<!-- neurath:begin -->\nold\n<!-- neurath:end -->\nUser notes\n"
    )
    service = PosixInstallationService(PosixSkillCatalogService())
    installed = await service.install(ProviderKind.CODEX, str(tmp_path), str(tmp_path / "data"))
    content = path.read_text()
    meta = yaml.safe_load(content.split("---\n", 2)[1])
    assert meta["name"] == "qa" and "여러 시나리오" in meta["description"]
    assert "User introduction" in content and "User notes" in content
    if "metadata:" in header:
        assert meta["metadata"] == {"owner": "user"}
    assert any(Path(backup).read_text().endswith("User notes\n") for backup in installed.backups)
    assert (
        await service.install(ProviderKind.CODEX, str(tmp_path), str(tmp_path / "data"))
    ).changed_files == ()


async def test_broken_owned_frontmatter_preserves_everything(tmp_path):
    path = tmp_path / ".agents/skills/qa/SKILL.md"
    path.parent.mkdir(parents=True)
    original = "---\nname: qa\n<!-- neurath:begin -->\nold\n<!-- neurath:end -->"
    path.write_text(original)
    with pytest.raises(ValueError, match="frontmatter"):
        await PosixInstallationService(PosixSkillCatalogService()).install(
            ProviderKind.CODEX, str(tmp_path), str(tmp_path / "data")
        )
    assert path.read_text() == original and not (tmp_path / "data").exists()


@pytest.mark.parametrize("transport", ["stdin", "file", "inline"])
async def test_selected_project_skill_runs_actual_host_phase_and_keeps_snapshot(
    database, host, transport
):
    directory = host[0]
    source = directory / "SKILL.md"
    original = "---\nname: project-check\ndescription: Verify the project artifact\n---\nRead the input, create output, verify content."
    source.write_text(original)
    spec = {
        "skill": "project-check",
        "version": "custom-1",
        "source": "SKILL.md",
        "inputs": {"input": "request:original"},
        "phases": [
            {"key": "create", "purpose": "Create the requested artifact", "checks": ["content"]},
            {
                "key": "verify",
                "purpose": "Read and verify the artifact",
                "result": "Verified exact content",
                "checks": ["readback"],
            },
        ],
    }
    encoded = json.dumps(spec)
    definition = directory / "workflow.json"
    definition.write_text(encoded)
    value = {"stdin": "-", "file": f"@{definition}", "inline": encoded}[transport]
    task = await create(database, start=False)
    flow = await invoke(
        database,
        [
            "workflow",
            "start",
            "--task-id",
            task["id"],
            "--skill",
            "project-check",
            "--definition",
            value,
        ],
        encoded if transport == "stdin" else "",
    )
    assert flow["attempts"] == [] and flow["current"]["arguments"] == []
    assert dict(flow["definition"]["inputs"])["skill_source_body"] == original
    artifact = directory / "output.txt"
    artifact.write_text("verified result")
    first = await invoke(
        database,
        [
            "workflow",
            "report",
            "--run-id",
            flow["id"],
            "--summary",
            "Created actual output",
            "--reference",
            str(artifact),
            "--check",
            "content",
        ],
    )
    assert first["current"]["key"] == "verify"
    source.write_text("Changed source must not rewrite an ongoing run")
    definition.write_text(json.dumps(dict(spec, version="custom-2")))
    before = database.read_bytes()
    shown = await invoke(database, ["workflow", "show", "--run-id", flow["id"]])
    assert shown["definition"] == flow["definition"] and len(shown["attempts"]) == 1
    await invoke(
        database,
        [
            "workflow",
            "start",
            "--task-id",
            task["id"],
            "--skill",
            "project-check",
            "--definition",
            f"@{definition}",
        ],
        succeeds=False,
    )
    assert before == database.read_bytes()
    assert artifact.read_text() == "verified result"
    final = await invoke(
        database,
        [
            "workflow",
            "report",
            "--run-id",
            flow["id"],
            "--summary",
            "Exact content verified",
            "--reference",
            str(artifact),
            "--check",
            "readback",
        ],
    )
    assert final["steps_complete"] and len(final["attempts"]) == 2
    assert source.read_text() == "Changed source must not rewrite an ongoing run"


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        "{bad",
        "{}",
        '{"phases":[1]}',
        '{"phases":[],"version":"1"}',
        '{"phases":[],"inputs":[]}',
        '{"phases":[],"inputs":{"x":1}}',
        '{"skill":"different"}',
        '{"version":"1","phases":[{"key":"one","purpose":"one","checks":"done"}]}',
        '{"version":"1","phases":[{"key":"one","purpose":"one","checks":[3]}]}',
        '{"version":"1","phases":[{"key":"one","purpose":"one","checks":[]}]}',
    ],
)
async def test_invalid_custom_skill_never_starts_task_or_run(database, host, raw):
    task = await create(database, start=False)
    before = database.read_bytes()
    await invoke(
        database,
        [
            "workflow",
            "start",
            "--task-id",
            task["id"],
            "--skill",
            "project-check",
            "--definition",
            raw,
        ],
        succeeds=False,
    )
    assert before == database.read_bytes()


async def test_old_builtin_run_remains_usable_after_catalog_update(database, host):
    task = await create(database, start=False)
    old = {
        "version": "1",
        "phases": [{"key": "step-1", "purpose": "Original pending work", "checks": ["done"]}],
    }
    flow = await invoke(
        database,
        [
            "workflow",
            "start",
            "--task-id",
            task["id"],
            "--skill",
            "qa",
            "--definition",
            json.dumps(old),
        ],
    )
    before = database.read_bytes()
    await invoke(
        database, ["workflow", "start", "--task-id", task["id"], "--skill", "qa"], succeeds=False
    )
    shown = await invoke(database, ["workflow", "show", "--run-id", flow["id"]])
    assert (
        shown["definition"]["version"] == "1"
        and shown["current"]["purpose"] == "Original pending work"
    )
    assert before == database.read_bytes()
    assert (
        await invoke(
            database,
            [
                "workflow",
                "report",
                "--run-id",
                flow["id"],
                "--summary",
                "Existing procedure performed",
                "--reference",
                "fixture:old",
                "--check",
                "done",
            ],
        )
    )["steps_complete"]


async def test_finish_steps_preserve_existing_valid_result_review_without_recursion(
    database, host, monkeypatch
):
    task, flow, artifact = await prepare_review(database, host)
    assignment = await delegate_review(database, task, artifact)
    await finish_review(database, assignment, artifact, monkeypatch)
    completed = await invoke(
        database,
        [
            "workflow",
            "report",
            "--run-id",
            flow["id"],
            "--summary",
            "Independent content evaluation accepted",
            "--reference",
            str(artifact),
            "--accepted",
        ],
    )
    assert completed["steps_complete"]
    attempts = completed["attempts"]
    phases = completed["definition"]["phases"] + [
        {"key": "finish-handoff", "purpose": "Preserve result and handoff", "checks": ["handoff"]}
    ]
    revised = await invoke(
        database,
        [
            "workflow",
            "revise",
            "--run-id",
            flow["id"],
            "--reason",
            "Finish the same requested work",
            "--definition",
            json.dumps(phases),
        ],
    )
    assert revised["current"]["key"] == "finish-handoff" and revised["attempts"] == attempts
    final = await invoke(
        database,
        [
            "workflow",
            "report",
            "--run-id",
            flow["id"],
            "--summary",
            "Existing evaluation and handoff verified",
            "--reference",
            str(artifact),
            "--check",
            "handoff",
        ],
    )
    assert final["steps_complete"]
    assert sum(item["phase_key"] == "result-review" for item in final["attempts"]) == 1
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM core_delegations").fetchone()[0] == 1


async def test_implement_spec_exposes_ui_conditions_and_records_actual_host_steps(database, host):
    directory = host[0]
    task = await create(database, start=False)
    flow = await invoke(
        database, ["workflow", "start", "--task-id", task["id"], "--skill", "implement-spec"]
    )
    assert flow["definition"]["version"] == "2" and flow["attempts"] == []
    assert [item["checks"] for item in flow["definition"]["phases"]] == [
        ["scope"],
        ["implementation"],
        ["verification"],
        ["intent"],
    ]
    assert "UI" in flow["definition"]["phases"][1]["purpose"]
    scope = directory / "scope.txt"
    scope.write_text(
        "UI fixture: named action and error state; DOM content only, native UI not verified"
    )
    flow = await invoke(
        database,
        [
            "workflow",
            "report",
            "--run-id",
            flow["id"],
            "--summary",
            "Inspected scope and explicit fixture limits",
            "--reference",
            str(scope),
            "--check",
            "scope",
        ],
    )
    artifact = directory / "index.html"
    artifact.write_text('<button aria-label="Save">Save</button><p role="alert">Error state</p>')
    flow = await invoke(
        database,
        [
            "workflow",
            "report",
            "--run-id",
            flow["id"],
            "--summary",
            "Implemented the requested fixture markup",
            "--reference",
            str(artifact),
            "--check",
            "implementation",
        ],
    )
    assert 'aria-label="Save"' in artifact.read_text() and 'role="alert"' in artifact.read_text()
    flow = await invoke(
        database,
        [
            "workflow",
            "report",
            "--run-id",
            flow["id"],
            "--summary",
            "Verified fixture DOM markers; actual visual interaction remains outside fixture",
            "--reference",
            str(artifact),
            "--check",
            "verification",
        ],
    )
    assert flow["current"]["key"] == "result-review" and not flow["steps_complete"]
    assert len(flow["attempts"]) == 3
    before = database.read_bytes()
    await invoke(
        database,
        [
            "workflow",
            "report",
            "--run-id",
            flow["id"],
            "--summary",
            "Not an independent report",
            "--reference",
            str(artifact),
            "--check",
            "intent",
        ],
        succeeds=False,
    )
    assert database.read_bytes() == before
