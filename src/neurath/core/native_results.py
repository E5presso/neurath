"""Normalize only explicit native terminal status; output prose is not status."""


def check_result(payload):
    raw = payload.get("tool_response", {})
    if isinstance(raw, str):
        # A program may print JSON. Text never becomes native status metadata.
        raw = {"text": raw}
    if not isinstance(raw, dict):
        raw = {"value": raw}
    for candidate in (payload.get("exit_code"), raw.get("exit_code"), raw.get("exitCode")):
        if type(candidate) is int:
            return {"exit_code": candidate, "native_response": raw}
    return None
