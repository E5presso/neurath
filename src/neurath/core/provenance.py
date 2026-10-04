"""Retained sources and evidence, with provenance and freshness checked at consumption."""

import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from neurath.core.codec import encode
from neurath.core.domain import (
    Evidence,
    Source,
    quote,
    require,
)


class Provenance:
    def __init__(self, store, sessions):
        self.store = store
        self.sessions = sessions

    def observe_user(self, context, text, event_id):
        """Import an actual native user event, never an agent-provided quotation."""
        with self.store.transaction() as tx:
            self.sessions.actor(tx, context)
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
            self.sessions.actor(tx, context)
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
            self.sessions.actor(tx, context)
            tx.task(task_id)
            event_id = encode([context.session_id, context.actor_id, "tool", event_id])
            source = Source.create(
                "source-" + sha256(event_id.encode()).hexdigest(), "tool", encode(result), event_id
            )
            tx.put_source(source)
            return self.record_evidence(
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
            self.sessions.actor(tx, context)
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

    def instruction(self, tx, source_id):
        source = tx.source(source_id)
        require(source.kind in {"user", "native_input"}, "user-source-required")
        origin = tx.record("source-origin", source_id)
        require(
            origin is None or origin["value"]["origin"] in {"unknown", "human"},
            "non-user-instruction",
        )
        return source

    def record_evidence(
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

    def outcomes(self, tx, task_id, values):
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
                    self.require_reviewer(tx, task, value.actor_id)
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
                    or (value.kind == "approval" and self.instruction(tx, source.id)),
                    "evidence-provenance",
                )
                items.append(value)
            result[condition_id] = tuple(items)
        return result

    def require_reviewer(self, tx, task, actor_id):
        require(
            actor_id != task.owner_actor
            and not any(actor_id in previous.implementation_actors for previous in tx.tasks()),
            "review-not-independent",
        )

    def source_list(self, tx, context, actor, values):
        limit = values.get("limit", 12)
        require(type(limit) is int and 1 <= limit <= 100, "invalid-limit")
        kind = values.get("kind")
        require(kind is None or kind in {"user", "native_input", "tool", "report"}, "source-kind")
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

    def evidence_list(self, tx, context, actor, values):
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

    def approval_record(self, tx, context, actor, values):
        task = tx.task(values["task_id"])
        task.require_owner(context.actor_id, task.ownership_generation)
        source = self.instruction(tx, values["source_id"])
        excerpt = quote(source, values["start"], values["end"], values["digest"])
        require(isinstance(values["action"], str) and bool(values["action"]), "approval-action")
        require(isinstance(values["target"], dict) and bool(values["target"]), "approval-target")
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
        evidence = self.record_evidence(
            tx,
            task.id,
            source,
            context.actor_id,
            "approval",
            encode([values["action"], values["target"]]),
            True,
        )
        return {"approval": approval, "evidence": evidence}

    def source_restore(self, tx, context, actor, values):
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
            "legacy-native-input:" + value["session"] + ":" + value["proof"]["authority_reference"]
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

    def report_record(self, tx, context, actor, values):
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
            "evidence": self.record_evidence(
                tx,
                task.id,
                source,
                context.actor_id,
                "report",
                values.get("subject", ""),
                values["passed"],
            )
        }

    def source_quote(self, tx, context, actor, values):
        source = tx.source(values["source_id"])
        return {
            "source_id": source.id,
            "kind": source.kind,
            "text": quote(source, values["start"], values["end"], values["digest"]),
        }

    def source_read(self, tx, context, actor, values):
        source = tx.source(values["source_id"])
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

    def publication(self, tx, context, task_id, observation):
        """Persist an external observation inside the caller's authenticated transaction."""
        event_id = "publication-read:" + context.actor_id + ":" + context.invocation_id
        source = Source.create(
            "source-" + sha256(event_id.encode()).hexdigest(), "tool", encode(observation), event_id
        )
        tx.put_source(source)
        evidence = self.record_evidence(
            tx,
            task_id,
            source,
            context.actor_id,
            "publication",
            observation["subject"],
            observation["ok"],
            operation=observation["operation"],
        )
        return {"evidence": evidence, "observation": observation}
