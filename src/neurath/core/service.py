"""Closed work commands under adapter-supplied identity; all progress stays in Task."""

import json
import subprocess
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from neurath.core.checks import COMMANDS as CHECK_COMMANDS
from neurath.core.checks import call as check_command
from neurath.core.codec import encode
from neurath.core.communication import COMMANDS as COMMUNICATION_COMMANDS
from neurath.core.communication import call as communicate
from neurath.core.domain import (
    Assignment,
    Condition,
    CoreError,
    Evidence,
    Source,
    Task,
    quote,
    require,
    select_execution,
    stop_reasons,
)
from neurath.core.memory_commands import COMMANDS as MEMORY_COMMANDS
from neurath.core.memory_commands import MemoryCommands
from neurath.core.provider_commands import COMMANDS as PROVIDER_COMMANDS
from neurath.core.provider_commands import call as provider_command
from neurath.core.store import Store
from neurath.project_paths import control_root


@dataclass(frozen=True, slots=True)
class Context:
    actor_id: str
    session_id: str
    invocation_id: str


# Identity, source provenance and native observations have no public write command.
COMMANDS = {
    **CHECK_COMMANDS,
    **PROVIDER_COMMANDS,
    **COMMUNICATION_COMMANDS,
    **MEMORY_COMMANDS,
    "session_status": (set(), set(), True),
    "collaboration_discover": (set(), set(), True),
    "task_list": (set(), {"all_project"}, True),
    "task_read": ({"task_id"}, set(), True),
    "evidence_list": ({"task_id"}, set(), True),
    "publication_read": (
        {"task_id", "checkout", "publication_kind", "reference"},
        {"head", "asset_sha256"},
        True,
    ),
    "approval_record": (
        {"task_id", "source_id", "start", "end", "digest", "action", "target", "reason"},
        set(),
        False,
    ),
    "source_read": ({"source_id"}, {"start", "limit"}, True),
    "source_list": (set(), {"kind", "limit"}, True),
    "source_quote": ({"source_id", "start", "end", "digest"}, set(), True),
    "source_restore": ({"task_id", "source_id", "body"}, set(), False),
    "phase_read": ({"task_id"}, set(), True),
    "task_define": ({"goal", "source_ids", "acceptance"}, {"dependencies"}, False),
    "task_start": ({"task_id", "expected_revision"}, set(), False),
    "skill_start": ({"task_id", "expected_revision", "skill"}, set(), False),
    "task_wait": ({"task_id", "expected_revision", "reason", "source_id"}, set(), False),
    "task_resume": ({"task_id", "expected_revision"}, set(), False),
    "task_withdraw": (
        {"task_id", "expected_revision", "source_id", "start", "end", "digest", "reason"},
        set(),
        False,
    ),
    "task_adopt": (
        {"task_id", "expected_revision", "source_id", "start", "end", "digest", "reason"},
        set(),
        False,
    ),
    "task_complete": ({"task_id", "expected_revision", "outcomes"}, set(), False),
    "phase_complete": (
        {"task_id", "expected_revision", "phase_id", "outcomes", "inputs"},
        set(),
        False,
    ),
    "phase_restart": ({"task_id", "expected_revision", "source_id"}, {"changed_inputs"}, False),
    "report_record": ({"task_id", "body", "passed"}, {"subject"}, False),
    "assignment_prepare": (
        {"task_id", "expected_revision", "execution", "reason", "scope", "subject", "role"},
        {"recipient", "provider", "checkout"},
        False,
    ),
    "assignment_start": ({"task_id", "assignment_id"}, set(), False),
    "assignment_read": ({"task_id", "assignment_id"}, set(), True),
    "assignment_report": ({"task_id", "assignment_id", "verdict", "body", "subject"}, set(), False),
    "assignment_accept": ({"task_id", "assignment_id", "source_id", "subject"}, set(), False),
    "assignment_reject": ({"task_id", "assignment_id", "source_id"}, set(), False),
    "assignment_cancel": ({"task_id", "assignment_id", "reason"}, set(), False),
    "worktree_read": ({"checkout"}, set(), True),
    "worktree_claim": ({"task_id", "checkout"}, {"create"}, False),
    "worktree_release": ({"checkout", "generation"}, set(), False),
    "task_focus": ({"task_id"}, set(), False),
}


def validated(name, values):
    require(name in COMMANDS, "unknown-command", command=name)
    required, optional, readonly = COMMANDS[name]
    require(isinstance(values, dict), "invalid-input")
    require(
        set(values) <= required | optional | (set() if readonly else {"key"}), "unexpected-fields"
    )
    require(required <= set(values), "missing-fields", fields=sorted(required - set(values)))
    if not readonly:
        require(isinstance(values.get("key"), str) and bool(values["key"]), "command-key")
    for key in (
        "task_id",
        "source_id",
        "goal",
        "skill",
        "phase_id",
        "digest",
        "reason",
        "body",
        "assignment_id",
        "checkout",
        "scope",
        "execution",
        "role",
    ):
        if key in values:
            require(
                isinstance(values[key], str) and bool(values[key].strip()),
                "invalid-input",
                field=key,
            )
    if "expected_revision" in values:
        require(
            type(values["expected_revision"]) is int and values["expected_revision"] > 0,
            "invalid-revision",
        )
    require(len(encode(values).encode()) <= 65536, "input-too-large")
    return readonly


class Core:
    def __init__(self, project_root, *, skills=None):
        self.worktree = Path(project_root).resolve()
        try:
            shared = control_root(self.worktree)
        except subprocess.CalledProcessError:
            # Work-state reads also serve explicitly supplied non-Git fixtures;
            # writer admission separately requires a verified Git checkout.
            shared = self.worktree
        self.store = Store(shared)
        self.skills = dict(skills or {})
        self._load_installed_skills = skills is None
        self._memory_commands = None
        self.runtime_info = None  # Supplied by the actual long-lived MCP entrypoint.

    def observe_actor(
        self, actor_id, session_id, provider, *, parent=None, is_subagent=None, activate=True
    ):
        """Adapter entrypoint; deliberately absent from the public command map."""
        require(
            provider in {"codex", "claude-code"} and bool(actor_id and session_id), "native-actor"
        )
        value = {
            "id": actor_id,
            "session_id": session_id,
            "provider": provider,
            "parent": parent,
            "is_subagent": bool(parent) if is_subagent is None else is_subagent,
            "status": "active" if activate else "observed",
        }
        with self.store.transaction() as tx:
            previous = tx.record("actor", actor_id)
            if previous:
                require(
                    all(
                        previous["value"][key] == value[key]
                        for key in ("id", "session_id", "provider", "parent", "is_subagent")
                    ),
                    "actor-rebinding",
                )
                if not activate:
                    value["status"] = previous["value"]["status"]
            tx.put_record("actor", actor_id, value, 0 if previous is None else previous["revision"])

    def observe_user(self, context, text, event_id):
        """Import an actual native user event, never an agent-provided quotation."""
        with self.store.transaction() as tx:
            self._actor(tx, context)
            event_id = encode([context.session_id, context.actor_id, "user", event_id])
            source = Source.create(
                "source-" + sha256(event_id.encode()).hexdigest(), "user", text, event_id
            )
            tx.put_source(source)
            return source

    def observe_input(self, context, text, event_id, *, origin="unknown"):
        """Retain hook input without asserting that a human authored it.

        Native prompt hooks also deliver continuations and peer messages. This
        record proves only what arrived; consent interpretation is separate.
        """
        require(origin in {"unknown", "peer", "scheduled", "continuation", "human"}, "input-origin")
        require(origin != "human", "human-attestation-required")
        with self.store.transaction() as tx:
            self._actor(tx, context)
            identifier = encode([context.session_id, context.actor_id, "input", event_id])
            source = Source.create(
                "source-" + sha256(identifier.encode()).hexdigest(),
                "native_input",
                text,
                identifier,
            )
            tx.put_source(source)
            previous = tx.record("source-origin", source.id)
            value = {"origin": origin, "actor_id": context.actor_id}
            if previous:
                require(previous["value"] == value, "source-conflict")
            else:
                tx.put_record("source-origin", source.id, value)
                current = tx.record("current-input", context.actor_id)
                tx.put_record(
                    "current-input",
                    context.actor_id,
                    {"source_id": source.id},
                    0 if current is None else current["revision"],
                )
            return source

    def observe_tool(
        self,
        context,
        task_id,
        event_id,
        result,
        *,
        kind,
        subject="",
        checkout_path=None,
        execution_scope=None,
    ):
        """Adapter-owned observation; public reports cannot choose this provenance."""
        require(kind in {"check", "publication", "observation"}, "native-evidence-kind")
        require(isinstance(result, dict), "native-result-required")
        if kind == "check":
            require(
                type(result.get("exit_code")) is int and not result.get("running"),
                "check-not-terminal",
            )
            require(
                "passed" not in result or type(result["passed"]) is bool, "native-result-required"
            )
        else:
            require(type(result.get("ok")) is bool, "result-not-terminal")
        with self.store.transaction() as tx:
            self._actor(tx, context)
            tx.task(task_id)
            event_id = encode([context.session_id, context.actor_id, "tool", event_id])
            source = Source.create(
                "source-" + sha256(event_id.encode()).hexdigest(), "tool", encode(result), event_id
            )
            tx.put_source(source)
            return self._evidence(
                tx,
                task_id,
                source,
                context.actor_id,
                kind,
                subject,
                result.get("passed", result.get("exit_code") == 0)
                if kind == "check"
                else result.get("ok") is True,
                checkout_path=checkout_path,
                execution_scope=execution_scope,
            )

    def observe_output(self, context, payload, *, interaction=False):
        """Retain native output as source text without inventing a success result."""
        raw = payload.get("tool_response")
        text = raw if isinstance(raw, str) else encode(raw)
        event_id = encode([context.session_id, context.actor_id, "output", context.invocation_id])
        source = Source.create(
            "source-" + sha256(event_id.encode()).hexdigest(),
            "native_input" if interaction else "tool",
            text,
            event_id,
        )
        with self.store.transaction() as tx:
            self._actor(tx, context)
            tx.put_source(source)
            if interaction and tx.record("source-origin", source.id) is None:
                tx.put_record(
                    "source-origin",
                    source.id,
                    {"origin": "unknown", "actor_id": context.actor_id, "channel": "input-tool"},
                )
            if tx.record("source-observation", source.id) is None:
                tx.put_record(
                    "source-observation",
                    source.id,
                    {
                        "actor_id": context.actor_id,
                        "tool": payload.get("tool_name"),
                        "tool_use_id": payload.get("tool_use_id"),
                        "input": payload.get("tool_input"),
                        "interaction": interaction,
                    },
                )
        return source

    def _actor(self, tx, context):
        actor = tx.record("actor", context.actor_id)
        require(
            actor is not None and actor["value"]["session_id"] == context.session_id,
            "native-actor-required",
        )
        return actor["value"]

    def _instruction(self, tx, source_id):
        source = tx.source(source_id)
        require(source.kind in {"user", "native_input"}, "user-source-required")
        origin = tx.record("source-origin", source_id)
        require(
            origin is None or origin["value"]["origin"] in {"unknown", "human"},
            "non-user-instruction",
        )
        return source

    def _evidence(
        self,
        tx,
        task_id,
        source,
        actor,
        kind,
        subject,
        passed,
        *,
        checkout_path=None,
        checkout_subject=None,
        operation=None,
        execution_scope=None,
    ):
        require(type(passed) is bool and isinstance(subject, str), "evidence-value")
        identifier = (
            "evidence-"
            + sha256(
                encode([source.id, task_id, kind, subject, passed, operation]).encode()
            ).hexdigest()
        )
        value = Evidence(identifier, kind, source.id, actor, subject, passed, operation)
        saved = {
            "task_id": task_id,
            "evidence": asdict(value),
            "checkout": None if checkout_path is None else str(checkout_path),
            "checkout_subject": checkout_subject,
            "execution_scope": None
            if execution_scope is None
            else [list(item) for item in execution_scope],
        }
        existing = tx.record("evidence", identifier)
        if existing:
            require(existing["value"] == saved, "evidence-conflict")
        else:
            tx.put_record("evidence", identifier, saved)
        return value

    def call(self, context, name, values, *, guard=None):
        readonly = validated(name, values)
        if name in MEMORY_COMMANDS and self._memory_commands is None:
            self._memory_commands = MemoryCommands(self.worktree, self.store)

        def authenticate(tx):
            self._actor(tx, context)
            if guard is not None:
                guard(tx)

        observation = None
        installation = None
        if name == "session_status":
            with self.store.transaction() as tx:
                authenticate(tx)
            from neurath.core.diagnostics import installation_status

            installation = installation_status(self.worktree, self.runtime_info)
        if name == "publication_read":
            with self.store.transaction() as tx:
                authenticate(tx)
                tx.task(values["task_id"])
            from neurath.core.publications import observe

            observation = observe(self.store.root, values)

        def execute(tx):
            actor = self._actor(tx, context)
            if observation is not None:
                event_id = "publication-read:" + context.actor_id + ":" + context.invocation_id
                source = Source.create(
                    "source-" + sha256(event_id.encode()).hexdigest(),
                    "tool",
                    encode(observation),
                    event_id,
                )
                tx.put_source(source)
                evidence = self._evidence(
                    tx,
                    values["task_id"],
                    source,
                    context.actor_id,
                    "publication",
                    observation["subject"],
                    observation["ok"],
                    operation=observation["operation"],
                )
                return {"evidence": evidence, "observation": observation}
            result = self._execute(tx, context, actor, name, values)
            if installation is not None:
                result["runtime"] = self.runtime_info
                result["installation"] = installation
            if (
                name == "task_list"
                or not readonly
                and (name.startswith(("task_", "phase_", "skill_", "assignment_")))
            ):
                result["native_todo"] = self._todo(tx, context, actor)
            return result

        if readonly:
            with self.store.transaction() as tx:
                authenticate(tx)
                return json.loads(encode(execute(tx)))
        return self.store.command(
            context.actor_id,
            values["key"],
            name,
            {key: value for key, value in values.items() if key != "key"},
            execute,
            authenticate=authenticate,
        )

    def _owned(self, tx, context, values, *, control=False):
        task = tx.task(values["task_id"])
        controllers = [a for a in task.assignments if a.role == "executor" and a.state == "active"]
        if control and controllers:
            require(
                any(a.recipient == context.actor_id for a in controllers), "executor-controls-phase"
            )
        else:
            task.require_owner(context.actor_id, task.ownership_generation)
        require(
            task.revision == values["expected_revision"],
            "revision-conflict",
            expected=values["expected_revision"],
            actual=task.revision,
        )
        return task

    def _outcomes(self, tx, task_id, values):
        require(isinstance(values, dict), "invalid-outcomes")
        result = {}
        subjects = {}
        for condition_id, references in values.items():
            require(
                isinstance(condition_id, str) and isinstance(references, list), "invalid-outcomes"
            )
            items = []
            for reference in references:
                require(isinstance(reference, str), "invalid-evidence-reference")
                record = tx.record("evidence", reference)
                require(record is not None, "evidence-missing", evidence_id=reference)
                require(record["value"]["task_id"] == task_id, "evidence-task-mismatch")
                scope = record["value"].get("execution_scope")
                if scope is not None:
                    tx.task(task_id).validate_observation_scope(scope)
                value = Evidence(**record["value"]["evidence"])
                target = record["value"].get("checkout")
                if target is not None:
                    from neurath.core.workspace import source_subject

                    if target not in subjects:
                        if Path(target).exists():
                            subjects[target] = source_subject(target)
                        else:
                            retired = tx.record("retired-checkout", target)
                            require(
                                retired is not None and retired["value"]["task_id"] == task_id,
                                "evidence-subject-unavailable",
                            )
                            subjects[target] = retired["value"]["subject"]
                    require(
                        (record["value"].get("checkout_subject") or value.subject)
                        == subjects[target],
                        "evidence-subject-changed",
                    )
                source = tx.source(value.source_id)
                if value.kind == "review":
                    task = tx.task(task_id)
                    self._reviewer(tx, task, value.actor_id)
                    require(
                        any(
                            a.result_source == source.id
                            and a.state == "accepted"
                            and a.role == "reviewer"
                            and a.result_subject == value.subject
                            for a in task.assignments
                        ),
                        "review-not-accepted",
                    )
                require(
                    (value.kind == "report" and source.kind == "report")
                    or (
                        value.kind in {"check", "publication", "observation"}
                        and source.kind == "tool"
                    )
                    or (value.kind == "review" and source.kind == "report")
                    or (value.kind == "approval" and self._instruction(tx, source.id)),
                    "evidence-provenance",
                )
                items.append(value)
            result[condition_id] = tuple(items)
        return result

    def _execute(self, tx, context, actor, name, values):
        if name in PROVIDER_COMMANDS:
            return provider_command(tx, self, context, name, values)
        if name in CHECK_COMMANDS:
            return check_command(tx, self, context, name, values)
        if name in COMMUNICATION_COMMANDS:
            return communicate(tx, context, name, values)
        if name in MEMORY_COMMANDS:
            return self._memory_commands.call(tx, context, actor, name, values)
        if name == "collaboration_discover":
            return {
                "actors": [
                    {**record["value"], "native_handle": tx.record("native-handle", record["id"])}
                    for record in tx.records("actor")
                ]
            }
        if name == "session_status":
            return {
                "actor": actor,
                "pending": stop_reasons(context.session_id, context.actor_id, tx.tasks()),
            }
        if name == "task_list":
            current = tx.record("current-input", context.actor_id)
            all_project = values.get("all_project", False)
            require(type(all_project) is bool, "invalid-input")
            return {
                "tasks": tuple(
                    task
                    for task in tx.tasks()
                    if all_project
                    or task.owner_actor == context.actor_id
                    or any(a.recipient == context.actor_id for a in task.assignments)
                ),
                "current_input": None if current is None else current["value"],
            }
        if name == "task_read":
            return {"task": tx.task(values["task_id"])}
        if name == "source_list":
            limit = values.get("limit", 12)
            require(type(limit) is int and 1 <= limit <= 100, "invalid-limit")
            kind = values.get("kind")
            require(
                kind is None or kind in {"user", "native_input", "tool", "report"}, "source-kind"
            )
            result = []
            for row in tx.db.execute("SELECT document FROM sources ORDER BY rowid DESC"):
                source = json.loads(row["document"])
                if kind is not None and source["kind"] != kind:
                    continue
                result.append(
                    {
                        "source_id": source["id"],
                        "kind": source["kind"],
                        "digest": source["digest"],
                        "length": len(source["text"]),
                        "preview": source["text"][:240],
                    }
                )
                if len(result) >= limit:
                    break
            return {"sources": result}
        if name == "evidence_list":
            tx.task(values["task_id"])
            return {
                "evidence": [
                    record["value"]
                    for record in tx.records("evidence")
                    if record["value"]["task_id"] == values["task_id"]
                ],
                "checks": [
                    record["value"]
                    for record in tx.records("check-execution")
                    if record["value"]["task_id"] == values["task_id"]
                ],
            }
        if name == "approval_record":
            task = tx.task(values["task_id"])
            task.require_owner(context.actor_id, task.ownership_generation)
            source = self._instruction(tx, values["source_id"])
            excerpt = quote(source, values["start"], values["end"], values["digest"])
            require(isinstance(values["action"], str) and bool(values["action"]), "approval-action")
            require(
                isinstance(values["target"], dict) and bool(values["target"]), "approval-target"
            )
            approval = {
                "id": "approval-" + uuid4().hex,
                "task_id": task.id,
                "assurance": "agent-interpretation",
                "assessor": context.actor_id,
                "source_id": source.id,
                "quote": excerpt,
                "action": values["action"],
                "target": values["target"],
                "reason": values["reason"],
            }
            tx.put_record("approval", approval["id"], approval)
            evidence = self._evidence(
                tx,
                task.id,
                source,
                context.actor_id,
                "approval",
                encode([values["action"], values["target"]]),
                True,
            )
            return {"approval": approval, "evidence": evidence}
        if name == "source_restore":
            task = tx.task(values["task_id"])
            task.require_owner(context.actor_id, task.ownership_generation)
            archived = tx.record("legacy-prompt", values["source_id"])
            require(archived is not None, "legacy-prompt-missing")
            value = archived["value"]
            ledgers = [
                tx.source(identifier)
                for identifier in task.instruction_sources
                if tx.source(identifier).event_id == "legacy-v1:task-ledger:" + value["session"]
            ]
            require(bool(ledgers), "legacy-prompt-task-mismatch")
            from neurath.core.legacy_work import owner_id

            original_owner = json.loads(ledgers[0].text)["payload"]["owner"]
            require(
                owner_id(value["proof"]["actor_id"], value["session"])
                == owner_id(original_owner, value["session"]),
                "legacy-prompt-actor-mismatch",
            )
            body = values["body"]
            require(
                sha256(body.encode()).hexdigest() == value["proof"].get("prompt_digest"),
                "source-changed",
            )
            event = (
                "legacy-native-input:"
                + value["session"]
                + ":"
                + value["proof"]["authority_reference"]
            )
            source = Source.create(
                "source-" + sha256(event.encode()).hexdigest(), "native_input", body, event
            )
            tx.put_source(source)
            if tx.record("source-origin", source.id) is None:
                tx.put_record(
                    "source-origin",
                    source.id,
                    {
                        "origin": "unknown",
                        "restored_from": values["source_id"],
                        "assurance": "retained-native-prompt-digest; not human attestation",
                    },
                )
            return {"source": source}
        if name in {"source_read", "source_quote"}:
            source = tx.source(values["source_id"])
            if name == "source_quote":
                return {
                    "source_id": source.id,
                    "kind": source.kind,
                    "text": quote(source, values["start"], values["end"], values["digest"]),
                }
            start, limit = values.get("start", 0), values.get("limit", 6000)
            require(
                type(start) is int
                and type(limit) is int
                and 0 <= start <= len(source.text)
                and 1 <= limit <= 16000,
                "source-range",
            )
            return {
                "source_id": source.id,
                "kind": source.kind,
                "digest": source.digest,
                "text": source.text[start : start + limit],
                "length": len(source.text),
                "origin": tx.record("source-origin", source.id),
                "observation": tx.record("source-observation", source.id),
            }
        if name == "phase_read":
            task = tx.task(values["task_id"])
            return {
                "task_id": task.id,
                "revision": task.revision,
                "phase": task.current_phase,
                "run": task.skill_run,
            }
        if name.startswith("worktree_"):
            from neurath.core.workspace import checkout

            path = Path(values["checkout"])
            require(path.is_absolute(), "absolute-checkout-required")
            literal = str(path)
            if name == "worktree_release":
                require(type(values["generation"]) is int, "invalid-generation")
                # A resource can be returned after its worktree was removed.
                # Releasing ownership grants no filesystem access.
                target = literal if tx.lease(literal) is not None else str(path.resolve())
                tx.release(target, context.actor_id, values["generation"])
                return {"released": True, "checkout": target}
            if name == "worktree_read" and tx.lease(literal) is not None:
                return {"checkout": literal, "lease": tx.lease(literal), "exists": path.exists()}
            if name == "worktree_claim" and values.get("create", False):
                require(values["create"] is True, "invalid-input")
                require(not path.exists() and not path.is_symlink(), "worktree-target-exists")
                target = str(path.resolve())
            else:
                target = checkout(self.store.root, literal)
            if name == "worktree_read":
                return {"checkout": target, "lease": tx.lease(target), "exists": True}
            task = tx.task(values["task_id"])
            require(task.state in {"open", "running", "waiting"}, "task-state")
            self._participant(task, context.actor_id)
            require(
                not any(
                    a.recipient == context.actor_id and a.role == "reviewer" and a.state == "active"
                    for a in task.assignments
                ),
                "reviewer-read-only",
            )
            current = tx.lease(target)
            if current and current["writer"] != context.actor_id:
                previous = tx.record("actor", current["writer"])
                stopped = (previous is not None and previous["value"]["status"] == "stopped") or (
                    previous is None and tx.record("retired-owner", current["writer"]) is not None
                )
                adopted = any(
                    r["value"].get("operation") == "task_adopt"
                    and r["value"].get("task_id") == task.id
                    and r["value"].get("prior_owner") == current["writer"]
                    and r["value"].get("assessor") == context.actor_id
                    for r in tx.records("task-decision")
                )
                require(stopped and adopted, "lease-conflict", writer=current["writer"])
                tx.release(target, current["writer"], current["generation"])
            return {"lease": tx.claim(target, context.actor_id)}
        if name == "task_focus":
            task = tx.task(values["task_id"])
            self._participant(task, context.actor_id)
            self._focus(tx, context.actor_id, task.id)
            return {"task_id": task.id, "revision": task.revision}
        if name in {"task_withdraw", "task_adopt"}:
            require(not actor["is_subagent"], "task-owner-required")
            task = tx.task(values["task_id"])
            require(
                task.revision == values["expected_revision"],
                "revision-conflict",
                actual=task.revision,
            )
            source = self._instruction(tx, values["source_id"])
            excerpt = quote(source, values["start"], values["end"], values["digest"])
            if name == "task_withdraw":
                task.require_owner(context.actor_id, task.ownership_generation)
                updated = task.withdraw(source)
                assignments = []
                for assignment in updated.assignments:
                    dispatch = tx.record("dispatch", assignment.id)
                    if (
                        assignment.state == "cancel-requested"
                        and not assignment.recipient
                        and dispatch["value"]["state"] == "prepared"
                    ):
                        assignment = replace(
                            assignment,
                            state="rejected",
                            verdict="cancelled",
                            result_source=source.id,
                        )
                    assignments.append(assignment)
                updated = replace(updated, assignments=tuple(assignments))
            else:
                previous = tx.record("actor", task.owner_actor)
                stopped = (previous is not None and previous["value"]["status"] == "stopped") or (
                    previous is None and tx.record("retired-owner", task.owner_actor) is not None
                )
                updated = task.adopt(
                    context.session_id, context.actor_id, source, previous_owner_stopped=stopped
                )
                self._focus(tx, context.actor_id, task.id)
            tx.save_task(updated, expected_revision=task.revision)
            tx.put_record(
                "task-decision",
                f"{task.id}:{updated.revision}",
                {
                    "operation": name,
                    "prior_owner": task.owner_actor,
                    "task_id": task.id,
                    "source_id": source.id,
                    "quote": excerpt,
                    "reason": values["reason"],
                    "assessor": context.actor_id,
                    "assurance": "agent-interpretation",
                },
            )
            return {"task": updated}
        if name == "task_define":
            require(not actor["is_subagent"], "task-owner-required")
            require(
                isinstance(values["source_ids"], list) and bool(values["source_ids"]),
                "instruction-source-required",
            )
            for reference in values["source_ids"]:
                self._instruction(tx, reference)
            require(isinstance(values["acceptance"], list), "acceptance-required")
            conditions = []
            dependencies = values.get("dependencies", [])
            require(isinstance(dependencies, list), "task-dependencies")
            for identifier in dependencies:
                require(isinstance(identifier, str), "task-dependencies")
                tx.task(identifier)
            for value in values["acceptance"]:
                require(
                    isinstance(value, dict)
                    and {"id"} <= set(value)
                    and set(value) <= {"id", "kinds", "subject_key", "expected_pass", "operation"},
                    "invalid-condition",
                )
                conditions.append(
                    Condition(
                        value["id"],
                        frozenset(value.get("kinds", ["report"])),
                        value.get("subject_key"),
                        value.get("expected_pass", True),
                        value.get("operation"),
                    )
                )
            task = Task(
                "task-" + uuid4().hex,
                context.session_id,
                context.actor_id,
                values["goal"],
                tuple(values["source_ids"]),
                tuple(conditions),
                dependencies=tuple(dependencies),
            )
            tx.create_task(task)
            return {"task": task}
        if name == "report_record":
            task = tx.task(values["task_id"])
            require(
                context.actor_id == task.owner_actor
                or any(a.recipient == context.actor_id for a in task.assignments),
                "assignment-required",
            )
            source = Source.create(
                "source-" + uuid4().hex,
                "report",
                values["body"],
                "report:" + context.actor_id + ":" + context.invocation_id,
            )
            tx.put_source(source)
            return {
                "evidence": self._evidence(
                    tx,
                    task.id,
                    source,
                    context.actor_id,
                    "report",
                    values.get("subject", ""),
                    values["passed"],
                )
            }
        if name.startswith("assignment_"):
            return self._assignment(tx, context, actor, name, values)
        task = self._owned(tx, context, values, control=name != "task_complete")
        if name in {"task_start", "task_resume", "task_complete"}:
            require(
                all(tx.task(identifier).state == "completed" for identifier in task.dependencies),
                "dependencies-unfinished",
            )
        if name == "task_start":
            updated = task.start()
        elif name == "skill_start":
            if self._load_installed_skills:
                from neurath.core.skills import load_skills

                self.skills = load_skills()
                self._load_installed_skills = False
            require(values["skill"] in self.skills, "skill-missing")
            updated = task.attach_skill(self.skills[values["skill"]])
        elif name == "task_wait":
            tx.source(values["source_id"])
            updated = task.wait(values["reason"], values["source_id"])
        elif name == "task_resume":
            updated = task.resume()
        elif name == "phase_restart":
            tx.source(values["source_id"])
            changed = values.get("changed_inputs")
            require(
                changed is None
                or isinstance(changed, list)
                and all(isinstance(v, str) for v in changed),
                "invalid-inputs",
            )
            updated = task.restart(values["source_id"], changed)
        elif name == "phase_complete":
            require(
                isinstance(values["inputs"], dict)
                and all(
                    isinstance(k, str) and isinstance(v, str) for k, v in values["inputs"].items()
                ),
                "invalid-inputs",
            )
            updated = task.complete_phase(
                values["phase_id"],
                self._outcomes(tx, task.id, values["outcomes"]),
                values["inputs"],
            )
        elif name == "task_complete":
            updated = task.complete(self._outcomes(tx, task.id, values["outcomes"]))
        else:
            raise CoreError("unknown-command")
        tx.save_task(updated, expected_revision=task.revision)
        self._focus(tx, context.actor_id, task.id)
        return {"task": updated}

    def _participant(self, task, actor_id):
        assignment = next(
            (a for a in task.assignments if a.recipient == actor_id and a.state == "active"), None
        )
        require(actor_id == task.owner_actor or assignment is not None, "assignment-required")
        return assignment

    def _reviewer(self, tx, task, actor_id):
        require(
            actor_id != task.owner_actor
            and not any(actor_id in previous.implementation_actors for previous in tx.tasks()),
            "review-not-independent",
        )

    def _role_compatible(self, task, recipient, role):
        if not recipient:
            return
        require(
            not any(
                a.recipient == recipient
                and (a.role == "reviewer") != (role == "reviewer")
                for a in task.assignments
            ),
            "review-role-conflict",
        )

    def _acceptors(self, task):
        return {
            task.owner_actor,
            *(
                a.recipient
                for a in task.assignments
                if a.role == "executor" and a.state == "active"
            ),
        }

    def _focus(self, tx, actor_id, task_id):
        previous = tx.record("focus", actor_id)
        tx.put_record(
            "focus", actor_id, {"task_id": task_id}, 0 if previous is None else previous["revision"]
        )

    def _todo(self, tx, context, actor):
        rows = []
        focused = tx.record("focus", context.actor_id)
        focus = None if focused is None else focused["value"]["task_id"]
        for task in tx.tasks():
            if task.owner_actor == context.actor_id:
                rows.append(
                    (task.id, task.goal, task.state, task.state in {"completed", "withdrawn"})
                )
            else:
                for assignment in task.assignments:
                    if assignment.recipient == context.actor_id:
                        rows.append(
                            (
                                task.id,
                                assignment.scope,
                                assignment.state,
                                assignment.state in {"reported", "accepted", "rejected"},
                            )
                        )
        active = next((i for i, row in enumerate(rows) if row[0] == focus and not row[3]), None)
        if active is None:
            active = next((i for i, row in enumerate(rows) if not row[3]), None)
        if actor["provider"] == "codex":
            arguments = {
                "plan": [
                    {
                        "step": f"[Neurath] {goal} ({state}; {identifier})",
                        "status": "completed"
                        if done
                        else "in_progress"
                        if i == active
                        else "pending",
                    }
                    for i, (identifier, goal, state, done) in enumerate(rows)
                ]
            }
            tool = "update_plan"
        else:
            arguments = {
                "todos": [
                    {
                        "content": f"{goal} ({state}; {identifier})",
                        "activeForm": goal,
                        "status": "completed"
                        if done
                        else "in_progress"
                        if i == active
                        else "pending",
                    }
                    for i, (identifier, goal, state, done) in enumerate(rows)
                ]
            }
            tool = "TodoWrite"
        return {
            "tool": tool,
            "arguments": arguments,
            "instruction": "Display this projection through the native tool; it does not replace task or phase completion.",
        }

    def _assignment(self, tx, context, actor, name, values):
        task = tx.task(values["task_id"])
        if name == "assignment_prepare":
            self._owned(tx, context, values, control=True)
            require(values["role"] in {"worker", "reviewer", "executor"}, "assignment-role")
            if values["role"] == "executor":
                require(
                    not any(
                        a.role == "executor" and a.state in {"issued", "active", "cancel-requested"}
                        for a in task.assignments
                    ),
                    "executor-conflict",
                )
            recipient = values.get("recipient", "")
            target = tx.record("actor", recipient) if recipient else None
            require(not recipient or target is not None, "recipient-unobserved")
            provider = (
                target["value"]["provider"] if target else values.get("provider", actor["provider"])
            )
            select_execution(values["execution"], actor["provider"], provider, values["reason"])
            if target:
                require(
                    (values["execution"] == "subagent") == target["value"]["is_subagent"],
                    "execution-target-mismatch",
                )
                require(recipient != context.actor_id, "assignment-self")
            if values["role"] == "reviewer" and recipient:
                self._reviewer(tx, task, recipient)
            self._role_compatible(task, recipient, values["role"])
            review_target = None
            if values["role"] == "reviewer":
                from neurath.core.workspace import checkout, source_subject

                require(isinstance(values.get("checkout"), str), "review-checkout-required")
                target = checkout(self.store.root, values["checkout"])
                review_target = {
                    "checkout": target,
                    "subject": source_subject(target),
                    "execution_scope": [list(item) for item in task.observation_scope()],
                }
            identifier = "assignment-" + uuid4().hex
            assignment = Assignment(
                identifier,
                values["execution"],
                values["scope"],
                context.actor_id,
                recipient,
                values["subject"],
                role=values["role"],
                run_index=task.skill_index,
                phase_id=None if task.current_phase is None else task.current_phase.id,
                attempt=None if task.skill_run is None else task.skill_run.attempt,
            )
            tx.put_record(
                "dispatch",
                identifier,
                {
                    "provider": provider,
                    "reason": values["reason"],
                    "task_id": task.id,
                    "issuer": context.actor_id,
                    "state": "prepared",
                    "review_target": review_target,
                },
            )
        else:
            assignment = next(
                (a for a in task.assignments if a.id == values["assignment_id"]), None
            )
            require(assignment is not None, "assignment-missing")
            if name == "assignment_read":
                return {
                    "assignment": assignment,
                    "task_revision": task.revision,
                    "review_target": tx.record("dispatch", assignment.id)["value"].get(
                        "review_target"
                    ),
                }
            if name == "assignment_start":
                assignment = assignment.start(context.actor_id)
                self._focus(tx, context.actor_id, task.id)
            elif name == "assignment_report":
                # Validate recipient and state before saving any reported bytes.
                require(assignment.recipient == context.actor_id, "actor-mismatch")
                if assignment.role == "executor" and values["verdict"] == "pass":
                    require(
                        task.state == "running" and all(run.complete for run in task.skill_runs),
                        "phases-unfinished",
                    )
                if assignment.role == "reviewer" and values["verdict"] == "pass":
                    self._reviewer(tx, task, context.actor_id)
                source = Source.create(
                    "source-" + uuid4().hex,
                    "report",
                    values["body"],
                    "assignment-report:" + context.actor_id + ":" + context.invocation_id,
                )
                assignment = assignment.report(
                    context.actor_id, source.id, values["verdict"], values["subject"]
                )
                tx.put_source(source)
                kind = "review" if assignment.role == "reviewer" else "report"
                review_target = tx.record("dispatch", assignment.id)["value"].get("review_target")
                evidence = self._evidence(
                    tx,
                    task.id,
                    source,
                    context.actor_id,
                    kind,
                    values["subject"],
                    values["verdict"] == "pass",
                    checkout_path=None if review_target is None else review_target["checkout"],
                    checkout_subject=None if review_target is None else review_target["subject"],
                    execution_scope=None
                    if review_target is None
                    else review_target["execution_scope"],
                )
                tx.save_task(task.with_assignment(assignment), expected_revision=task.revision)
                return {"assignment": assignment, "evidence": evidence}
            elif name == "assignment_accept":
                tx.source(values["source_id"])
                if assignment.role == "reviewer":
                    self._reviewer(tx, task, assignment.recipient)
                assignment = assignment.accept(
                    context.actor_id,
                    values["source_id"],
                    values["subject"],
                    acceptors=self._acceptors(task),
                )
            elif name == "assignment_reject":
                tx.source(values["source_id"])
                assignment = assignment.reject(
                    context.actor_id, values["source_id"], acceptors=self._acceptors(task)
                )
            elif name == "assignment_cancel":
                require(
                    context.actor_id
                    in {task.owner_actor, assignment.acceptance_owner or assignment.issuer},
                    "actor-mismatch",
                )
                if assignment.state == "issued" and not assignment.recipient:
                    dispatch = tx.record("dispatch", assignment.id)
                    run = tx.record("provider-run", dispatch["value"].get("run_id", ""))
                    if run and run["value"]["state"] != "prepared":
                        assignment = assignment.cancel()
                        updated = task.with_assignment(assignment)
                        tx.save_task(updated, expected_revision=task.revision)
                        return {"assignment": assignment, "task_revision": updated.revision}
                    require(
                        dispatch["value"]["state"] in {"prepared", "launch-prepared"},
                        "dispatch-uncertain",
                    )
                    if run:
                        tx.put_record(
                            "provider-run",
                            run["value"]["id"],
                            {**run["value"], "state": "cancelled"},
                            run["revision"],
                        )
                    source = Source.create(
                        "source-" + uuid4().hex,
                        "report",
                        values["reason"],
                        "cancel-unstarted:" + context.actor_id + ":" + values["key"],
                    )
                    tx.put_source(source)
                    assignment = replace(
                        assignment, state="rejected", result_source=source.id, verdict="cancelled"
                    )
                else:
                    assignment = assignment.cancel()
            else:
                raise CoreError("unknown-command")
        updated = task.with_assignment(assignment)
        tx.save_task(updated, expected_revision=task.revision)
        self._focus(tx, context.actor_id, task.id)
        return {
            "assignment": assignment,
            "task_revision": updated.revision,
            "dispatch_marker": f"[neurath-assignment:{assignment.id}]",
            "review_target": tx.record("dispatch", assignment.id)["value"].get("review_target"),
        }

    def bind_recipient(self, task_id, assignment_id, recipient):
        """An observed native spawn fills the reserved recipient exactly once."""
        with self.store.transaction() as tx:
            target = tx.record("actor", recipient)
            require(target is not None, "recipient-unobserved")
            task = tx.task(task_id)
            assignment = next((a for a in task.assignments if a.id == assignment_id), None)
            if assignment is not None and assignment.recipient == recipient:
                return
            require(assignment is not None and assignment.state == "issued", "assignment-state")
            require(
                not assignment.recipient or assignment.recipient == recipient, "recipient-rebinding"
            )
            if assignment.role == "reviewer":
                self._reviewer(tx, task, recipient)
            self._role_compatible(task, recipient, assignment.role)
            dispatch = tx.record("dispatch", assignment.id)
            require(dispatch["value"]["provider"] == target["value"]["provider"], "provider-choice")
            require(
                (assignment.execution == "subagent") == target["value"]["is_subagent"],
                "execution-target-mismatch",
            )
            require(recipient != assignment.issuer, "assignment-self")
            updated = task.with_assignment(replace(assignment, recipient=recipient))
            tx.save_task(updated, expected_revision=task.revision)
            tx.put_record(
                "dispatch",
                assignment.id,
                {**dispatch["value"], "state": "bound"},
                dispatch["revision"],
            )

    def admit_write(self, context, *, checkout_path, generation):
        """Coordinate an explicit editor write, without interpreting host commands."""
        from neurath.core.workspace import checkout

        with self.store.transaction() as tx:
            self._actor(tx, context)
            focus = tx.record("focus", context.actor_id)
            require(focus is not None, "task-focus-required")
            task = tx.task(focus["value"]["task_id"])
            require(task.state == "running", "task-state")
            self._participant(task, context.actor_id)
            require(
                not any(
                    a.recipient == context.actor_id and a.role == "reviewer" and a.state == "active"
                    for a in task.assignments
                ),
                "reviewer-read-only",
            )
            target = checkout(self.store.root, checkout_path)
            lease = tx.lease(target)
            require(
                lease is not None and lease["writer"] == context.actor_id, "writer-lease-required"
            )
            require(type(generation) is int and generation == lease["generation"], "stale-lease")
            if context.actor_id not in task.implementation_actors:
                updated = task.changed(
                    implementation_actors=(*task.implementation_actors, context.actor_id)
                )
                tx.save_task(updated, expected_revision=task.revision)
                task = updated
            return {"allowed": True, "task_id": task.id, "task_revision": task.revision}

    def stop(self, context):
        with self.store.transaction() as tx:
            self._actor(tx, context)
            reasons = stop_reasons(context.session_id, context.actor_id, tx.tasks())
            return {"allowed": not reasons, "pending": reasons}
