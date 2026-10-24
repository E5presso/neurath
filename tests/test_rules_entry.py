"""설치 rules의 선택 정보·원본 경로·기존 CLI 연결을 실제 저장소로 확인한다.

정해 둔 대표 요청을 사용하며 네이티브 모델의 선택 정확도를 측정하지 않는다.
"""

import json
import re
import sqlite3
from pathlib import Path

import pytest

from neurath.domain.enums.provider_kind import ProviderKind
from neurath.infrastructure.services.installation import PosixInstallationService
from neurath.infrastructure.services.skill_catalog import PosixSkillCatalogService
from tests.support.hook_cli import HookCliClient
from tests.test_host_flow import invoke


@pytest.fixture(params=list(ProviderKind))
async def installed_rules(tmp_path, request, monkeypatch):
    provider = request.param
    root = tmp_path / "project with spaces"
    root.mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setenv("NEURATH_PROVIDER", provider.value)
    rules = root / ("AGENTS.md" if provider is ProviderKind.CODEX else "CLAUDE.md")
    rules.write_text("User/project instructions take their existing precedence.\n")
    custom = (
        root
        / (".agents/skills" if provider is ProviderKind.CODEX else ".claude/skills")
        / "project-specialist/SKILL.md"
    )
    custom.parent.mkdir(parents=True)
    custom.write_text(
        "---\nname: project-specialist\ndescription: Use the explicitly selected project procedure\n---\nRead the requested project input and verify its content."
    )
    installed = await PosixInstallationService(PosixSkillCatalogService()).install(
        provider, str(root), str(tmp_path / "data")
    )
    return root, provider, rules, custom, Path(installed.database)


async def test_rules_index_locates_real_skill_sources_and_preserves_instruction_precedence(
    installed_rules,
):
    root, provider, rules, custom, database = installed_rules
    before = database.read_bytes()
    content = rules.read_text()
    assert content.startswith("User/project instructions take their existing precedence.")
    assert content.count("<!-- neurath:begin -->") == content.count("<!-- neurath:end -->") == 1
    assert "user does not need to enable a Neurath mode" in content
    assert "An explicitly named skill takes precedence" in content
    assert "native, project, or user skill" in content
    assert "follow existing host/project instruction precedence" in content
    assert "Reading a skill or mentioning its name is not a started run" in content
    assert "never expands the user's requested scope" in content
    assert "Reuse the task/run already handling the request" in content
    assert "@NEURATH_SKILLS@" not in content and "@NEURATH_COMMAND@" not in content
    paths = re.findall(r"\]\(<([^>]+/SKILL\.md)>\)", content)
    entries = PosixSkillCatalogService().list(str(root))
    assert len(paths) == len(entries) == 14
    for entry in entries:
        path = next(
            Path(value) for value in paths if Path(value).parent.name == entry.workflow.skill
        )
        assert path.is_file()
        assert entry.purpose in content and entry.use_when in content and entry.exclude in content
        body = path.read_text()
        assert entry.workflow.phases[0].purpose in body
        assert f"workflow start --task-id ... --skill {entry.workflow.skill}" in body
    assert "explicitly selected project procedure" in custom.read_text()
    assert database.read_bytes() == before
    again = await PosixInstallationService(PosixSkillCatalogService()).install(
        provider, str(root), str(database.parent.parent)
    )
    assert again.changed_files == () and rules.read_text() == content


async def test_representative_work_requests_can_follow_rules_to_existing_cli_runner(
    installed_rules, monkeypatch
):
    root, provider, rules, _, database = installed_rules
    client = HookCliClient(provider.value, database)
    # 요청/스킬 쌍은 검증 시나리오의 입력이다. 모델 분류기로 선택했다고 주장하지 않는다.
    examples = [
        ("명세와 실행 계획을 정리해 주세요", "define-spec"),
        ("요청한 UI 화면과 오류 상태를 구현해 주세요", "implement-spec"),
        ("여러 티켓을 의존성 순서에 맞춰 자율 처리해 주세요", "autopilot"),
        ("원인이 불명확한 실패를 재현하고 고쳐 주세요", "debug"),
        ("현재 PR의 코드 경로와 회귀를 리뷰해 주세요", "review-code"),
    ]
    for index, (prompt, skill) in enumerate(examples):
        session = f"rules-work-{index}"
        monkeypatch.setenv("NEURATH_SESSION_ID", session)
        await client.handle(
            dict(
                session_id=session, cwd=str(root), hook_event_name="UserPromptSubmit", prompt=prompt
            )
        )
        current = await invoke(database, ["context", "show"])
        assert current["tasks"] == current["workflows"] == []
        path = next(
            Path(value)
            for value in re.findall(r"\]\(<([^>]+/SKILL\.md)>\)", rules.read_text())
            if Path(value).parent.name == skill
        )
        before = database.read_bytes()
        assert skill in path.read_text()
        assert before == database.read_bytes()
        task = await invoke(
            database,
            ["task", "create", "--title", prompt, "--result", "Verified requested outcome"],
        )
        flow = await invoke(
            database, ["workflow", "start", "--task-id", task["id"], "--skill", skill]
        )
        assert flow["skill"] == skill and flow["attempts"] == []
        repeated = await invoke(
            database, ["workflow", "start", "--task-id", task["id"], "--skill", skill]
        )
        assert repeated["id"] == flow["id"] and repeated["attempts"] == []
        evidence = root / f"scope-{index}.txt"
        evidence.write_text(prompt)
        assert evidence.read_text() == prompt
        reported = await invoke(
            database,
            [
                "workflow",
                "report",
                "--run-id",
                flow["id"],
                "--summary",
                "Read the actual request and recorded fixture scope; later work remains",
                "--reference",
                str(evidence),
                "--check",
                flow["current"]["checks"][0],
            ],
        )
        assert len(reported["attempts"]) == 1 and not reported["steps_complete"]
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM core_tasks").fetchone()[0] == len(examples)
        assert db.execute("SELECT count(*) FROM core_workflows").fetchone()[0] == len(examples)


async def test_explicit_project_skill_is_available_without_replacing_it_with_builtin(
    installed_rules, monkeypatch
):
    root, provider, rules, custom, database = installed_rules
    original = custom.read_text()
    session = "rules-explicit-specialist"
    monkeypatch.setenv("NEURATH_SESSION_ID", session)
    await HookCliClient(provider.value, database).handle(
        dict(
            session_id=session,
            cwd=str(root),
            hook_event_name="UserPromptSubmit",
            prompt="Use project-specialist to check this project; do not substitute a generic review.",
        )
    )
    assert "An explicitly named skill takes precedence" in rules.read_text()
    assert "--definition @file.json" in rules.read_text()
    task = await invoke(
        database,
        [
            "task",
            "create",
            "--title",
            "Selected project specialist",
            "--result",
            "Verified project input",
        ],
    )
    definition = {
        "version": "project-1",
        "source": str(custom),
        "phases": [
            {"key": "inspect", "purpose": "Read the requested project input", "checks": ["content"]}
        ],
    }
    flow = await invoke(
        database,
        [
            "workflow",
            "start",
            "--task-id",
            task["id"],
            "--skill",
            "project-specialist",
            "--definition",
            "-",
        ],
        json.dumps(definition),
    )
    assert flow["skill"] == "project-specialist"
    assert dict(flow["definition"]["inputs"])["skill_source_body"] == original
    assert custom.read_text() == original


async def test_question_explanation_status_and_single_host_operations_do_not_create_runs(
    installed_rules, monkeypatch
):
    root, provider, rules, _, database = installed_rules
    content = rules.read_text()
    assert (
        "Simple questions, explanations, and status requests do not require a skill, task, or workflow"
        in content
    )
    assert "Single host operations such as a commit or worktree creation" in content
    assert "Use context queries only when current stored state is needed" in content
    client = HookCliClient(provider.value, database)
    for index, prompt in enumerate(
        [
            "이 용어는 무슨 뜻인가요?",
            "코드 한 줄을 설명해 주세요",
            "현재 상태를 알려 주세요",
            "이 변경만 커밋해 주세요",
            "워크트리를 만들어 주세요",
        ]
    ):
        session = f"rules-simple-{index}"
        monkeypatch.setenv("NEURATH_SESSION_ID", session)
        payload = dict(
            session_id=session, cwd=str(root), hook_event_name="UserPromptSubmit", prompt=prompt
        )
        await client.handle(payload)
        before = database.read_bytes()
        current = await invoke(database, ["context", "show"])
        assert current["tasks"] == current["workflows"] == []
        assert before == database.read_bytes()
        assert await client.handle(dict(payload, hook_event_name="Stop")) == {}
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM core_tasks").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM core_workflows").fetchone()[0] == 0
