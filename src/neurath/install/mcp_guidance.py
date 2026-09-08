"""Project managed guidance onto available named tasks; inventory explicit gaps.

Only installer-owned strings enter this module. It never rewrites user files or
executes the compatibility text. Runtime schemas remain the input authority.
"""
import re
import json
import shlex

PREFIXES = {
    "engine scripts.skill_harness.phase_runner init": "phase_start",
    "engine scripts.skill_harness.phase_runner current": "phase_current",
    "engine scripts.skill_harness.phase_runner complete": "phase_complete",
    "engine scripts.skill_harness.phase_runner finalize": "phase_finalize",
    "engine scripts.agent_harness.state_cli session inspect": "session_inspect",
    "engine scripts.agent_harness.state_cli turn inspect": "turn_inspect",
    "engine scripts.agent_harness.state_cli worktree claim": "worktree_claim",
    "engine scripts.agent_harness.state_cli worktree release": "worktree_release",
    "engine scripts.agent_harness.state_cli workflow start": "workflow_start",
    "engine scripts.agent_harness.state_cli workflow advance": "workflow_advance",
    "engine scripts.agent_harness.state_cli workflow finalize": "workflow_finalize",
    "engine scripts.agent_harness.state_cli adaptive preflight": "adaptive_preflight",
    "engine scripts.agent_harness.state_cli adaptive read": "adaptive_read",
    "engine scripts.agent_harness.state_cli adaptive replace": "adaptive_replace",
    "engine scripts.agent_harness.state_cli adaptive override-goal": "adaptive_override_goal",
    "engine scripts.agent_harness.state_cli adaptive prepare-evaluation": "evaluation_prepare",
    "engine scripts.agent_harness.state_cli adaptive read-evaluation": "evaluation_read",
    "engine scripts.agent_harness.state_cli adaptive execute-evidence": "evaluation_execute",
    "engine scripts.agent_harness.state_cli action prepare": "material_prepare",
    "engine scripts.agent_harness.state_cli action read": "material_read",
    "engine scripts.agent_harness.state_cli action resolve": "material_resolve",
    "engine scripts.agent_harness.state_cli action abandon": "material_abandon",
    "engine scripts.agent_harness.state_cli delegation assign": "delegation_assign",
    "engine scripts.agent_harness.state_cli delegation report": "evaluation_report",
    "engine scripts.agent_harness.state_cli delegation consume": "evaluation_consume",
    "session-status": "session_status",
    "provider capabilities": "provider_capabilities", "provider route": "provider_route",
    "provider run": "provider_run", "provider status": "provider_status", "provider cancel": "provider_cancel",
    "memory recall": "memory_recall", "memory checkpoint": "memory_checkpoint",
    "learning status": "learning_status", "learning history": "learning_history",
    "learning pending": "learning_pending", "learning defer": "learning_defer",
    "agent register": "collaboration_register", "agent conversation": "collaboration_conversation",
    "agent close": "collaboration_close", "agent subscribe": "collaboration_subscribe",
    "agent unsubscribe": "collaboration_unsubscribe", "agent publish": "collaboration_publish",
    "newsroom revise": "newsroom_revise", "newsroom comment": "newsroom_comment",
    "newsroom peers": "newsroom_peers", "newsroom seen": "newsroom_seen",
    "agent discover": "collaboration_discover", "agent send": "collaboration_send",
    "agent inbox": "collaboration_inbox", "agent message": "collaboration_message",
    "agent ack": "collaboration_ack", "agent reply": "collaboration_reply",
    "agent forward": "collaboration_forward", "agent submitted": "collaboration_submitted",
    "newsroom headlines": "newsroom_headlines", "newsroom read": "newsroom_read",
    "newsroom publish": "newsroom_publish", "verify": "verification_run",
    "delegate prepare": "delegation_prepare",
    "integrity": "diagnostics_integrity", "doctor": "diagnostics_project", "profile-check": "diagnostics_profile",
    "engine scripts.agent_harness.state_cli artifact put": "artifact_put",
    "engine scripts.agent_harness.state_cli artifact read": "artifact_read",
    "engine scripts.agent_harness.state_cli enclave read": "enclave_read",
    "engine scripts.agent_harness.state_cli enclave set": "enclave_set",
    "engine scripts.agent_harness.state_cli enclave delete": "enclave_delete",
    "engine scripts.agent_harness.state_cli turn yield": "turn_yield",
    "engine scripts.agent_harness.verification_runner pytest": "verification_nodes",
    "engine scripts.agent_harness.verification_runner": "verification_builtin",
}
for action in ("record","validate","resolve","escalate","refresh","supersede"):
    PREFIXES["engine scripts.agent_harness.harness_incident "+action] = "incident_"+action
for action in ("open","read","round","close"):
    PREFIXES["engine scripts.agent_harness.state_cli evaluation-loop "+action] = "evaluation_loop_"+action
for domain, tool_prefix, actions in (
    ("releases", "releases", ("status","check","notice","prepare","apply","recover","choose")),
    ("report", "reporting", ("status","list","read","prepare","consent","approve","submit","reconcile")),
):
    PREFIXES.update({domain+" "+a: tool_prefix+"_"+a for a in actions})

COMMAND = re.compile(r"`(?P<inline>\.neurath/run[^`]+)`|^[ \t]*(?P<line>\.neurath/run[^\n]*)",
                     re.MULTILINE)
FLAGS = {"decision":"decisions","next-step":"next_steps","lesson":"lessons",
         "idempotency-key":"key"}


def _typed_references(tool, parameters):
    """Keep source-selected values only for fields actually exposed by the tool."""
    from neurath.runtime.task_schema import TASKS
    schema = TASKS.get(tool, (None,None,None,{}))[3]
    try:
        tokens = shlex.split(parameters.replace("\\\n"," "))
    except ValueError:
        return {}
    result, index = {}, 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not token.startswith("--"):
            continue
        flag = token[2:]
        field = FLAGS.get(flag,flag.replace("-","_"))
        field = {"expected_workflow_revision":"expected_revision","node":"nodes"}.get(field,field)
        if field not in schema:
            continue
        kind = schema[field].get("type")
        if kind == "boolean":
            result[field] = True
        elif index < len(tokens) and not tokens[index].startswith("--"):
            value = tokens[index]
            index += 1
            if kind == "integer":
                if value.isdigit():
                    result[field] = int(value)
            elif kind == "array":
                result.setdefault(field,[]).append(value)
            elif kind == "string":
                result[field] = value
    return result


def _classify(command, available):
    body = command.removeprefix(".neurath/run").strip()
    if "<script>" in body or body == "engine <scripts.module>":
        return None, "entrypoint-placeholder", ""
    if body.startswith("engine scripts.agent_harness.state_cli session recover-foreground-turn"):
        return None, "host-lifecycle-callback", ""
    if body.startswith("delegate ") and not body.startswith("delegate prepare"):
        action = body.split()[1]
        tool = {"run":"provider_run","status":"provider_status","cancel":"provider_cancel","resume":"provider_recover"}.get(action)
        return tool, "legacy-bounded-adapter", ""
    if body == "newsroom":
        return "newsroom_headlines / newsroom_read / newsroom_publish", "named-mcp", ""
    script = re.match(r"skill\s+\S+\s+(\S+)(.*)",body,re.DOTALL)
    if script:
        filename, params = script.groups()
        tools = {"assert_worktree_isolation.sh":"worktree_isolation", "check_auto_merge_continuation_contract.sh":"diagnostics_continuation",
            "merge_cleanup.py":"worktree_cleanup", "process_state_evidence.py":"process_evidence_record",
            "publish_final_review.py":"review_publish", "local_pr_monitor.py":"monitor_start",
            "monitor_runtime_readback.py":"monitor_readback", "prepare_monitor_handoff.py":"monitor_handoff",
            "collect_comments.sh":"review_comments", "acknowledge_event.py":"monitor_external_wait" if "--external-wait" in params else "monitor_ack"}
        if filename == "safe_worktree_apply_patch.sh":
            return "worktree_isolation / material_prepare", "native-file-edit", ""
        if filename == "delegate_state.py":
            match = re.search(r"\b(begin|submit|complete|abort)\b",params)
            tool = None if match is None else {"begin":"review_begin","submit":"review_report","complete":"review_consume","abort":"review_abort"}[match[1]]
        else:
            tool = tools.get(filename)
        if tool in available:
            return tool, "named-mcp", params.strip()
    if body == "engine scripts.skill_harness.phase_runner":
        names = ("phase_start", "phase_current", "phase_complete", "phase_finalize")
        if set(names).issubset(available):
            return " / ".join(names), "named-mcp", ""
    for prefix in sorted(PREFIXES, key=len, reverse=True):
        if body == prefix or body.startswith(prefix+" "):
            tool = PREFIXES[prefix]
            if tool in available:
                parameters = body[len(prefix):].strip()
                if "maintenance_choice_prepare" not in available and (
                    tool in {"releases_choose", "reporting_consent", "reporting_approve"}
                ):
                    return tool, "native-user-choice-evidence-required", parameters
                return tool, "named-mcp", parameters
            return tool, "missing-named-operation", body[len(prefix):].strip()
    return None, "missing-named-operation", body


def inventory(text, available):
    return [{"command": m.group("inline") or m.group("line"),
             "tool": _classify(m.group("inline") or m.group("line"), available)[0],
             "classification": _classify(m.group("inline") or m.group("line"), available)[1],
             "line": text.count("\n",0,m.start())+1} for m in COMMAND.finditer(text)]


def migrate(text, available):
    """Preserve constraints around commands; keep parameter values as reference.

    Parameter references are explanatory, not a new input language or executable
    command. Agents must obtain the current closed schema before supplying input.
    Unported helper scripts remain visible exceptions, never hidden argv MCP.
    """
    # Join only harness command continuations; keep unrelated shell code intact.
    continuation = re.compile(r"(?m)(\.neurath/run[^\n]*?)\\\n[ \t]*")
    while continuation.search(text):
        text = continuation.sub(r"\1 ",text)
    def replace(match):
        original = match.group("inline") or match.group("line")
        tool, classification, parameters = _classify(original, available)
        if classification == "entrypoint-placeholder":
            return "`현재 노출된 Neurath 명명 MCP 도구`"
        if classification == "host-lifecycle-callback":
            return "`호스트 수명 이벤트가 수행하는 foreground 복구`"
        if classification == "native-file-edit":
            return "`worktree_isolation`과 `material_prepare`로 준비한 뒤 호스트의 파일 편집 도구"
        if classification == "legacy-bounded-adapter":
            return "`"+str(tool)+"` (현재 스키마를 따르는 독립 작업; 과거 제한 실행기는 내부 호환용)"
        if classification != "named-mcp":
            return match.group(0) + f" [MCP migration exception: {classification}; native host policy applies]"
        # Do not invent a second pseudo-CLI vocabulary. Preserve exact public
        # test selectors and fixed check names as typed fields; other inputs are
        # obtained from the named tool's schema and surrounding phase contract.
        example = _typed_references(tool, parameters)
        if tool == "verification_nodes":
            nodes = re.findall(r"--node\s+([^\s]+\.py::[^\s]+)",parameters)
            if nodes:
                example["nodes"] = nodes
        elif tool == "verification_builtin":
            example["check"] = parameters.split()[0] if parameters else "check"
        elif tool == "verification_run" and parameters:
            example["check"] = parameters.split()[0]
        value = "MCP " + tool + " (use its current structured input schema)"
        if example:
            value += " "+json.dumps(example,ensure_ascii=False)
        return "`"+value+"`" if match.group("inline") else value
    result = COMMAND.sub(replace,text)
    # Older policy paragraphs use unprefixed inline spellings. They are still
    # Neurath operation instructions, so route them through the same inventory.
    bare = re.compile(r"`((?:agent|newsroom|memory|learning|releases|report|provider) [^`]+)`")
    def bare_replace(match):
        value = match[1]
        tool, classification, _ = _classify(".neurath/run "+value, available)
        if classification == "named-mcp":
            return "`"+tool+"` (현재 구조화 입력 스키마 사용)"
        if classification == "legacy-bounded-adapter":
            return "`"+tool+"`"
        return match[0]
    result = bare.sub(bare_replace,result)
    # A migrated example is tool guidance, not a shell command block.
    result = re.sub(r"(```)(?:bash|sh|shell)\n(?=MCP )", r"\1text\n", result)
    return result
