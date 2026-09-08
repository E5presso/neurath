"""Managed agent instructions use named operations while preserving compatibility."""
from neurath.install.mcp_guidance import migrate, inventory


def test_inline_and_multiline_phase_commands_become_structured_guidance():
    text = "반드시 `.neurath/run engine scripts.skill_harness.phase_runner init --workflow-id W --skill plan-issues --run-id R --north-star G` 뒤 소유권을 확인한다."
    result = migrate(text, {"phase_start"})
    assert ".neurath/run" not in result
    assert "phase_start" in result and "workflow_id" in result and "north_star" in result
    assert "소유권을 확인한다" in result


def test_unknown_script_is_explicit_gap_and_never_an_arbitrary_mcp_gateway():
    text = "`.neurath/run skill debug reproduction.py --case X`"
    result = migrate(text, {"phase_start"})
    assert "MCP migration exception" in result
    assert "missing-named-operation" in result
    assert "reproduction.py" in result
    assert "agent(argv)" not in result


def test_only_exposed_tools_are_recommended():
    text="`.neurath/run agent message ID`"
    assert "collaboration_message" in migrate(text, {"collaboration_message"})
    result=migrate(text,set())
    assert "missing-named-operation" in result
    assert ".neurath/run agent message ID" in result


def test_inventory_classifies_every_command_including_fenced_lines():
    text="\n".join(["`.neurath/run memory recall --query X`",
                     "```sh", ".neurath/run learning status", ".neurath/run skill custom x.py", "```"])
    rows=inventory(text,{"memory_recall","learning_status"})
    assert len(rows)==3
    assert [r["classification"] for r in rows]==["named-mcp","named-mcp","missing-named-operation"]


def test_rewrite_does_not_change_non_harness_shell_or_remove_authority_text():
    text="Never bypass deny.\n```sh\ngit diff --check\n```"
    assert migrate(text,set())==text

def test_installed_skill_guidance_and_policy_prefer_named_tools():
    from neurath.install.projection import asset_files
    files=asset_files("generic",["codex"])
    policy=files[".neurath/policy.md"][0].decode()
    assert ".neurath/run memory recall" not in policy
    assert "memory_recall" in policy
    assert ".neurath/reference/task-operation-map.json" in files


def test_installed_operation_map_exposes_every_detected_compatibility_gap():
    import json
    from neurath.install.projection import asset_files
    files=asset_files("generic",["codex"])
    mapping=json.loads(files[".neurath/reference/task-operation-map.json"][0])
    assert mapping["schema"]==1
    assert mapping["commands"]
    assert all(r["classification"] in {"named-mcp","missing-named-operation","native-user-choice-evidence-required"}
               for r in mapping["commands"])
    assert any(r["classification"]=="missing-named-operation" for r in mapping["commands"])

def test_managed_entry_prefers_mcp_and_adopts_only_exact_old_block(tmp_path):
    import subprocess
    from neurath.install.transaction import make_plan, apply_plan
    subprocess.run(["git","init","-q",str(tmp_path)],check=True)
    old=("\n<!-- neurath:managed -->\n## Neurath\n\n"
         "Read `.neurath/policy.md` and `.neurath/project.json` for the generic profile.\n"
         "Use the skills in `.agents/skills`; execute through `.neurath/run`.\n"
         "<!-- /neurath:managed -->\n")
    user="# User rules\nPreserve this sentence.\n"
    (tmp_path/"AGENTS.md").write_text(user+old)
    apply_plan(tmp_path,make_plan(tmp_path))
    result=(tmp_path/"AGENTS.md").read_text()
    assert result.startswith(user)
    assert "execute through" not in result
    assert "named MCP task tools" in result
    assert make_plan(tmp_path)["changes"]==[]


def test_generic_phase_runner_instruction_names_existing_phase_actions():
    text="Use `.neurath/run engine scripts.skill_harness.phase_runner`."
    tools={"phase_start","phase_current","phase_complete","phase_finalize"}
    result=migrate(text,tools)
    assert ".neurath/run" not in result
    assert all(tool in result for tool in tools)
    assert inventory(text,tools)[0]["classification"]=="named-mcp"


def test_exposed_preparation_only_choice_is_not_counted_as_migrated_execution():
    text="`.neurath/run report consent yes --user-confirmed`"
    rows=inventory(text,{"reporting_consent"})
    assert rows[0]["classification"]=="native-user-choice-evidence-required"
    assert "native-user-choice-evidence-required" in migrate(text,{"reporting_consent"})
    assert inventory("`.neurath/run releases check --force`",{"releases_check"})[0]["classification"]=="named-mcp"
