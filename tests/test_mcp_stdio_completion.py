"""Regression boundaries for a complete named stdio MCP control surface."""
import io
import json
from pathlib import Path
from types import SimpleNamespace

from neurath.agents import mcp

ROOT = Path(__file__).resolve().parents[1]


def test_tool_discovery_does_not_advertise_argv_adapter():
    result = mcp.response(ROOT,{"jsonrpc":"2.0","id":1,"method":"tools/list"})
    assert "agent" not in {tool["name"] for tool in result["result"]["tools"]}


def test_generated_agent_instructions_have_no_unported_operations():
    from neurath.install.projection import asset_files
    files = asset_files("generic",["codex","claude-code"])
    catalog=json.loads(files[".neurath/reference/task-operation-map.json"][0])
    assert not [row for row in catalog["commands"] if row["classification"] == "missing-named-operation"]


def test_stdio_reserves_stdout_for_protocol_frames(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", ["neurath-mcp", "--root", str(tmp_path)])
    monkeypatch.setattr("neurath.install.transaction.repository", lambda root: root)
    incoming = SimpleNamespace(buffer=io.BytesIO(b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n'))
    output, diagnostic = io.StringIO(), io.StringIO()
    monkeypatch.setattr("sys.stdin", incoming)
    monkeypatch.setattr("sys.stdout", output)
    monkeypatch.setattr("sys.stderr", diagnostic)

    def response(root, request):
        print("backend diagnostic")
        return {"jsonrpc": "2.0", "id": request["id"], "result": {}}

    monkeypatch.setattr(mcp, "response", response)
    assert mcp.main() == 0
    frames = [json.loads(line) for line in output.getvalue().splitlines()]
    assert frames == [{"jsonrpc": "2.0", "id": 1, "result": {}}]
    assert "backend diagnostic" in diagnostic.getvalue()


def test_adaptive_reference_uses_the_real_phase_parser_delimiter(monkeypatch):
    from neurath.runtime import workflow_tasks
    from scripts.skill_harness.phase_runner import PhaseRunner

    receipt = {"kind": "adaptive-control-decision", "workflow_revision": 3}
    snapshot = SimpleNamespace(receipt=lambda: SimpleNamespace(to_evidence=lambda: receipt))
    monkeypatch.setattr("scripts.agent_harness.adaptive_control_store.AdaptiveControlStore",
                        lambda store: SimpleNamespace(read=lambda: snapshot))
    monkeypatch.setattr("scripts.agent_harness.skill_state_store.SkillStateStore", lambda *args: None)
    monkeypatch.setattr(workflow_tasks, "_adaptive_read", lambda *args: {})
    actual = workflow_tasks._evidence_refs(None, None, ["adaptive_control_initialized"])
    observed = []
    readback = SimpleNamespace(contract_goal="scope")
    store = SimpleNamespace(verify_adaptive_control_evidence=lambda value: observed.append(value) or readback)
    assert PhaseRunner(None)._adaptive_control_readback(
        "adaptive_control_initialized", actual, store, "scope"
    ) is readback
    assert observed == [receipt]


def test_workflow_schema_supports_atomic_operational_completion():
    from neurath.runtime.task_schema import arguments

    result = arguments("phase_complete", {
        "workflow_id": "commit", "expected_revision": 2, "phase_id": 3,
        "status": "completed", "summary": "Actual commit readback",
        "evidence_refs": [], "terminal_state": "committed", "key": "complete",
    })
    assert result["terminal_state"] == "committed"


def test_public_harness_operation_examples_use_named_tools():
    import re

    operations = r"(?:agent|delegate|memory|learning|newsroom|report|releases|verify|engine|skill|session-status|doctor|integrity|profile-check)"
    documents = list((ROOT / "docs/en").rglob("*.md")) + list((ROOT / "docs/ko").rglob("*.md"))
    violations = []
    for document in documents:
        for number, line in enumerate(document.read_text().splitlines(), 1):
            if re.search(r"\.neurath/run\s+" + operations + r"\b", line):
                violations.append(f"{document.relative_to(ROOT)}:{number}")
    assert not violations, "Agent-facing CLI operation examples remain: " + ", ".join(violations)


def test_public_mcp_json_examples_match_current_schemas():
    import re
    from neurath.runtime.task_schema import arguments
    for document in (ROOT / "docs").rglob("*.md"):
        for block in re.findall(r"```json\s*\n(.*?)\n```",document.read_text(),re.DOTALL):
            try:
                value=json.loads(block)
            except ValueError:
                continue
            if isinstance(value,dict) and set(value)=={"tool","arguments"}:
                arguments(value["tool"],value["arguments"])


def test_generated_runtime_notifications_do_not_teach_cli_fallback():
    from neurath.providers.codex_delivery import notification
    from neurath.providers.claude_sdk import BOOTSTRAP
    for value in (notification("a"*64),BOOTSTRAP):
        assert ".neurath/run" not in value
        assert "CLI compatibility" not in value


def test_generated_guidance_covers_dynamic_helpers_and_runtime_map():
    from neurath.install.projection import asset_files
    files=asset_files("generic",["codex","claude-code"])
    text="\n".join(data.decode() for p,(data,_) in files.items() if p.endswith(".md"))
    assert "REPO=example/project PR_NUMBER=" not in text
    assert "delegate resume <" not in text
    assert "report list/read" not in text
    assert "에이전트의 CLI 대체 경로" not in text
    assert ".neurath/run engine scripts.skill_harness.harness_catalog" not in text
