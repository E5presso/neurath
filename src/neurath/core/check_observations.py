"""Direct registered check observations, bound to the original Task attempt."""

from hashlib import sha256
from pathlib import Path

from neurath.core.codec import encode
from neurath.core.domain import require


class CheckObservations:
    def __init__(self, store, provenance, provider):
        self.store = store
        self.provenance = provenance
        self.provider = provider

    def _execution_id(self, context, tool_id):
        require(isinstance(tool_id, str) and bool(tool_id), "native-tool-id-required")
        return sha256(
            encode([self.provider, context.session_id, context.actor_id, tool_id]).encode()
        ).hexdigest()

    def start(self, context, payload, task_id, definitions):
        from neurath.core.workspace import checkout, source_subject

        values = payload["tool_input"]
        directory = values.get("workdir") or values.get("cwd") or payload.get("cwd")
        require(isinstance(directory, str), "check-directory-required")
        directory = Path(directory).resolve()
        target = checkout(self.store.root, directory)
        identifier = self._execution_id(context, payload.get("tool_use_id"))
        value = {
            "task_id": task_id,
            "actor_id": context.actor_id,
            "checkout": target,
            "subject": source_subject(target),
            "tool": payload["tool_name"],
            "input": values,
            "state": "running",
            "definition": next(
                check
                for check in definitions
                if check["command"] == values.get("command", values.get("cmd"))
                and Path(check["cwd"]).resolve() == directory
            ),
        }
        with self.store.transaction() as tx:
            value["execution_scope"] = [list(item) for item in tx.task(task_id).observation_scope()]
            previous = tx.record("check-execution", identifier)
            if previous:
                require(previous["value"] == value, "invocation-mismatch")
            else:
                tx.put_record("check-execution", identifier, value)

    def finish(self, context, payload, event):
        from neurath.core.native_results import check_result

        if not payload.get("tool_use_id"):
            return
        identifier = self._execution_id(context, payload["tool_use_id"])
        with self.store.transaction() as tx:
            record = tx.record("check-execution", identifier)
        if record is None:
            return
        value = record["value"]
        result = check_result(payload) if event == "PostToolUse" else None
        if result is None:
            with self.store.transaction() as tx:
                tx.put_record(
                    "check-execution",
                    identifier,
                    {
                        **value,
                        "state": "outcome-unavailable"
                        if event == "PostToolUse"
                        else "failed-to-execute",
                        "last_response": payload.get("tool_response"),
                        "last_event": event,
                    },
                    record["revision"],
                )
            return
        definition = value["definition"]
        marker = definition.get("stdout_contains")
        output = result["native_response"].get("stdout", result["native_response"].get("output"))
        if marker is not None and not isinstance(output, str):
            with self.store.transaction() as tx:
                tx.put_record(
                    "check-execution",
                    identifier,
                    {
                        **value,
                        "state": "outcome-unavailable",
                        "last_response": result,
                        "reason": "Required check output was not observable",
                    },
                    record["revision"],
                )
            return
        result["passed"] = result["exit_code"] in definition.get("success_codes", [0]) and (
            marker is None or marker in output
        )
        evidence = self.provenance.observe_tool(
            context,
            value["task_id"],
            "check:" + identifier,
            result,
            kind="check",
            subject=value["subject"],
            checkout_path=value["checkout"],
            execution_scope=value["execution_scope"],
        )
        if value["state"] == "completed":
            require(value["evidence_id"] == evidence.id, "native-result-changed")
            return
        with self.store.transaction() as tx:
            tx.put_record(
                "check-execution",
                identifier,
                {**value, "state": "completed", "evidence_id": evidence.id},
                record["revision"],
            )
