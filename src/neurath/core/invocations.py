"""Exact native invocation correlation and authenticated command execution."""

from hashlib import sha256

from neurath.core.codec import encode
from neurath.core.commands import Context
from neurath.core.domain import require


class NativeInvocations:
    def __init__(self, store, provider, execute):
        self.store = store
        self.provider = provider
        self.execute = execute

    def bind(self, context, command, values, native_tool_id):
        require(isinstance(native_tool_id, str) and bool(native_tool_id), "native-tool-id-required")
        call_id = values.get("_call_id")
        require(isinstance(call_id, str) and 1 <= len(call_id) <= 128, "native-call-id-required")
        identity = encode([self.provider, context.session_id, context.actor_id, native_tool_id])
        identifier = sha256(call_id.encode()).hexdigest()
        arguments = {key: value for key, value in values.items() if key != "_call_id"}
        value = {
            "provider": self.provider,
            "actor_id": context.actor_id,
            "session_id": context.session_id,
            "invocation_id": identity,
            "request": sha256(encode([command, arguments]).encode()).hexdigest(),
            "active": True,
        }
        native_id = sha256(identity.encode()).hexdigest()
        with self.store.transaction() as tx:
            previous = tx.record("native-invocation", identifier)
            if previous:
                require(previous["value"] == value, "native-call-id-reused")
            else:
                require(tx.record("native-call", native_id) is None, "native-invocation-rebound")
                tx.put_record("native-invocation", identifier, value)
                tx.put_record("native-call", native_id, {"id": identifier})
        # Correlation is already in the original input. Host permission handling
        # is unchanged: never issue an allow override to transport identity.
        return {}

    def call(self, command, values):
        require(isinstance(values, dict), "invalid-input")
        call_id = values.get("_call_id")
        require(isinstance(call_id, str) and bool(call_id), "native-invocation-required")
        identifier = sha256(call_id.encode()).hexdigest()
        arguments = {key: value for key, value in values.items() if key != "_call_id"}
        request = sha256(encode([command, arguments]).encode()).hexdigest()

        def authenticate(tx):
            record = tx.record("native-invocation", identifier)
            require(record is not None, "native-invocation-required")
            binding = record["value"]
            require(binding["active"], "native-invocation-closed")
            require(binding["provider"] == self.provider, "provider-binding-mismatch")
            actor = tx.record("actor", binding["actor_id"])
            require(
                actor is not None and actor["value"]["status"] == "active", "native-session-stopped"
            )
            require(binding["request"] == request, "invocation-mismatch")
            return Context(binding["actor_id"], binding["session_id"], binding["invocation_id"])

        with self.store.transaction() as tx:
            context = authenticate(tx)
        return self.execute(context, command, arguments, guard=authenticate)

    def close(self, context, native_tool_id):
        if not isinstance(native_tool_id, str):
            return
        identity = encode([self.provider, context.session_id, context.actor_id, native_tool_id])
        with self.store.transaction() as tx:
            link = tx.record("native-call", sha256(identity.encode()).hexdigest())
            if link:
                identifier = link["value"]["id"]
                record = tx.record("native-invocation", identifier)
                if record["value"]["active"]:
                    tx.put_record(
                        "native-invocation",
                        identifier,
                        {**record["value"], "active": False},
                        record["revision"],
                    )

    @staticmethod
    def close_session(tx, provider, context, *, child):
        for record in tx.records("native-invocation"):
            value = record["value"]
            if (
                value["provider"] == provider
                and value["session_id"] == context.session_id
                and value["active"]
                and (not child or value["actor_id"] == context.actor_id)
            ):
                tx.put_record(
                    "native-invocation",
                    record["id"],
                    {**value, "active": False},
                    record["revision"],
                )
