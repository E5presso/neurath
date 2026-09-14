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


def test_installed_policy_uses_one_task_completion_and_reversible_bypass():
    from neurath.install.projection import asset_files

    policy = asset_files("generic", ["codex"])[".neurath/policy.md"][0].decode()
    assert "harness_bypass(enabled=true)" in policy
    assert "enabled=false" in policy
    assert "별도 phase·workflow 완료나 acceptance JSON을 요구하지 않는다" in policy
    assert "SessionStart에서만" in policy
    assert "종료 훅은 인계가 이미 있어도" not in policy


def test_installed_skills_do_not_reintroduce_retired_edit_and_phase_gates():
    from neurath.install.projection import asset_files

    files = asset_files("generic", ["codex"])
    for path, (data, _) in files.items():
        if path.endswith("/SKILL.md"):
            text = data.decode()
            assert "중요 skill phase는" not in text, path
    text = files[".agents/skills/test-harness/SKILL.md"][0].decode()
    assert "Harness mutation 자체도 current actor-turn material action" not in text
    assert "파일 편집에 material 배치를 만들지 않는다" in text


def test_projected_incident_review_does_not_require_exhaustive_work_or_allow_abandonment():
    from neurath.install.projection import asset_files

    files = asset_files("generic", ["codex", "claude-code"])
    skill = files[".agents/skills/test-harness/SKILL.md"][0].decode()
    basic, formal = skill.split("## 정식 평가 또는 기존 workflow 복구", 1)
    assert "전수 비교를 명시적으로" in basic
    assert "상태 질문과 재촉은" in basic
    assert "Stop 거부를 없애려고" in basic
    assert "독립적인 완료 의무가 아닙니다" in basic
    assert "원래 태스크를 유지합니다" in basic
    assert "명시적으로 승인된 전수 비교" in formal
    policy = files[".neurath/policy.md"][0].decode()
    assert "all_terminal은 실행 기록의 종결이며 목표 달성이 아니다" in policy
    assert "prompt receipt는 출처의 존재만 증명" in policy
    assert "수단의 성공을 새 완료 조건으로 추가하지 않는다" in policy


def test_installed_operation_map_exposes_every_detected_compatibility_gap():
    import json
    from neurath.install.projection import asset_files
    files=asset_files("generic",["codex"])
    mapping=json.loads(files[".neurath/reference/task-operation-map.json"][0])
    assert mapping["schema"]==1
    assert mapping["commands"]
    assert all(r["classification"] in {"named-mcp","entrypoint-placeholder","host-lifecycle-callback","legacy-bounded-adapter","native-file-edit","native-project-check"}
               for r in mapping["commands"])
    assert not any(r["classification"]=="missing-named-operation" for r in mapping["commands"])

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
