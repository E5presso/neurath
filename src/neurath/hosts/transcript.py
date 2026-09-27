"""Read host-classified Codex lifecycle and prompt evidence without mutating state.

Observation alone grants no authority: callers still reconcile the evidence with
native bindings, session state and the exact current foreground turn.
"""

import json
from pathlib import Path


def _first_record(path):
    with path.open() as stream:
        line = stream.readline(1024 * 1024)
    return json.loads(line)



def _independent_root_source(meta):
    """App-created threads and forks are independent roots, not parent authority."""
    if meta.get("thread_source") in (None, "user", "agent_created_thread"):
        return True
    return (meta.get("thread_source") == "agent_forked_thread"
            and isinstance(meta.get("forked_from_id"), str)
            and bool(meta["forked_from_id"].strip())
            and meta["forked_from_id"] != meta.get("id"))



def _latest_codex_turn(path):
    """Find the current lifecycle beyond recall's tail budget, with bounded memory."""
    ended = set()
    for item in _reverse_native_lifecycle(path):
        turn = item.get("turn_id")
        if not isinstance(turn, str) or not turn:
            continue
        if item["type"] == "task_started":
            return "" if turn in ended else turn
        ended.add(turn)
    return "" if ended else None



def _reverse_native_lifecycle(path):
    kinds = {"task_started", "task_complete", "task_completed", "turn_aborted"}
    for event in _reverse_native_records(path, kinds):
        item = event.get("payload")
        if (event.get("type") == "event_msg" and isinstance(item, dict)
                and item.get("type") in kinds):
            yield item



def _reverse_native_records(path, needles):
    """Scan complete lines backwards; huge message records cannot hide lifecycle.

    Lifecycle envelopes are small. Oversized non-lifecycle lines are skipped as
    whole records, never parsed from a fragment. No transcript tail limit applies.
    """
    needles = tuple(('"' + kind + '"').encode() for kind in needles)

    def parse(line):
        if len(line) > 1024 * 1024:
            return {"type": "oversized_native_record"}
        if not any(word in line for word in needles):
            return None
        try:
            event = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            return None
        return event if isinstance(event, dict) else None

    with Path(path).open("rb") as stream:
        position = stream.seek(0, 2)
        tail, skipping = b"", False
        while position:
            size = min(position, 65536)
            position -= size
            stream.seek(position)
            parts = stream.read(size).split(b"\n")
            if len(parts) == 1:
                if skipping or len(parts[0]) + len(tail) > 1024 * 1024:
                    tail, skipping = b"", True
                else:
                    tail = parts[0] + tail
                continue
            if skipping:
                yield {"type": "oversized_native_record"}
            else:
                item = parse(parts[-1] + tail)
                if item is not None:
                    yield item
            for line in reversed(parts[1:-1]):
                item = parse(line)
                if item is not None:
                    yield item
            tail, skipping = parts[0], False
        if skipping:
            yield {"type": "oversized_native_record"}
        else:
            item = parse(tail)
            if item is not None:
                yield item



def native_root_turn(root, path, session, turn_id):
    """Read-only proof of the exact live Codex root turn."""
    try:
        record = _first_record(path)
        meta = record["payload"]
        if (record["type"] != "session_meta" or meta["id"] != session
                or meta.get("session_id", session) != session
                or meta.get("source") not in ("vscode", "cli", "exec")
                or not _independent_root_source(meta)
                or any(meta.get(k) for k in (
                    "parent_thread_id", "parent_session_id", "agent_id"))
                or meta.get("agent_path") not in (None, "/root")
                or Path(meta["cwd"]).resolve() != Path(root).resolve()
                or _latest_codex_turn(path) != turn_id):
            return False
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False
    return True



def _native_user_prompt(path, turn_id):
    """Read the latest host-classified user text in the current Codex turn."""
    for event in _reverse_native_records(path, {"message", "task_started"}):
        item = event.get("payload")
        if not isinstance(item, dict):
            continue
        if (event.get("type") == "event_msg" and item.get("type") == "task_started"
                and item.get("turn_id") == turn_id):
            break
        if (event.get("type") != "response_item" or item.get("type") != "message"
                or item.get("role") != "user"):
            continue
        metadata = item.get("internal_chat_message_metadata_passthrough")
        if not isinstance(metadata, dict) or metadata.get("turn_id") != turn_id:
            return None
        if metadata.get("content_item_kinds") != ["user.text"]:
            if (metadata.get("content_item_kinds") == ["skills.selected_skill_instructions"]
                    or _native_context_refresh(item, turn_id)):
                continue
            return None
        blocks = item.get("content")
        if (not isinstance(blocks, list) or len(blocks) != 1
                or not isinstance(blocks[0], dict)
                or blocks[0].get("type") != "input_text"
                or not isinstance(blocks[0].get("text"), str)):
            return None
        return blocks[0]["text"]
    return None



def _native_context_refresh(item, turn_id):
    """Only host-classified context is not a human prompt; never inspect its text."""
    metadata = item.get("internal_chat_message_metadata_passthrough")
    if not isinstance(metadata, dict) or metadata.get("turn_id") != turn_id:
        return False
    kinds = metadata.get("content_item_kinds")
    return (isinstance(kinds, list) and bool(kinds)
            and all(isinstance(kind, str) and kind in {
                "agents_md.instructions", "environments.environment_context", "plugins.recommendations",
            } for kind in kinds))
