"""Project managed guidance onto available named tasks; inventory explicit gaps.

Only installer-owned strings enter this module. It never rewrites user files or
executes the compatibility text. Runtime schemas remain the input authority.
"""
import re

PREFIXES = {
    "engine scripts.skill_harness.phase_runner init": "phase_start",
    "engine scripts.skill_harness.phase_runner current": "phase_current",
    "engine scripts.skill_harness.phase_runner complete": "phase_complete",
    "engine scripts.skill_harness.phase_runner finalize": "phase_finalize",
    "engine scripts.agent_harness.state_cli session inspect": "session_inspect",
    "engine scripts.agent_harness.state_cli session recover-foreground-turn": "session_recover",
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
}
for domain, tool_prefix, actions in (
    ("releases", "releases", ("status","check","notice","prepare","apply","recover","choose")),
    ("report", "reporting", ("status","list","read","prepare","consent","approve","submit","reconcile")),
):
    PREFIXES.update({domain+" "+a: tool_prefix+"_"+a for a in actions})

COMMAND = re.compile(r"`(?P<inline>\.neurath/run[^`]+)`|^[ \t]*(?P<line>\.neurath/run[^\n]*)",
                     re.MULTILINE)
FLAGS = {"decision":"decisions","next-step":"next_steps","lesson":"lessons",
         "idempotency-key":"key"}


def _classify(command, available):
    body = command.removeprefix(".neurath/run").strip()
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
    def replace(match):
        original = match.group("inline") or match.group("line")
        tool, classification, parameters = _classify(original, available)
        if classification != "named-mcp":
            return match.group(0) + f" [MCP migration exception: {classification}; native host policy applies]"
        parameters = re.sub(r"--([\w-]+)", lambda m: FLAGS.get(m[1],m[1].replace("-","_"))+":", parameters)
        reference = " ".join(parameters.replace("\\\n"," ").split())
        value = "MCP " + tool + " (use its current structured input schema"
        if reference:
            value += "; parameter reference: " + reference
        value += ")"
        return "`"+value+"`" if match.group("inline") else value
    result = COMMAND.sub(replace,text)
    # A migrated example is tool guidance, not a shell command block.
    result = re.sub(r"(```)(?:bash|sh|shell)\n(?=MCP )", r"\1text\n", result)
    return result
