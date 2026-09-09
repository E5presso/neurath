"""Read completed native tool records; never infer exit status from stdout text."""

import json
import shlex
from pathlib import Path
from urllib.parse import unquote, urlparse


def _same_cwd(value, root):
    if not isinstance(value, str):
        return False
    if value.startswith("file://"):
        value = unquote(urlparse(value).path)
    return Path(value).resolve() == Path(root).resolve()


def records(path):
    with Path(path).open("rb") as stream:
        size = stream.seek(0, 2)
        stream.seek(max(0, size - 2 * 1024 * 1024))
        if size > 2 * 1024 * 1024:
            stream.readline()
        for line in stream:
            try:
                value = json.loads(line)
            except ValueError, UnicodeDecodeError:
                continue
            if isinstance(value, dict):
                yield value


def command_records(path, host, session, root):
    calls = {}
    for event in records(path):
        if host == "codex":
            payload = event.get("payload", {})
            if (
                event.get("type") != "event_msg"
                or payload.get("type") != "item_completed"
                or payload.get("thread_id") != session
            ):
                continue
            item = payload.get("item", {})
            code = item.get("exit_code")
            if (
                item.get("type") != "CommandExecution"
                or item.get("status") not in ("completed", "failed")
                or type(code) is not int
                or not _same_cwd(item.get("cwd"), root)
            ):
                continue
            argv = item.get("command")
            if not isinstance(argv, list) or not argv or any(not isinstance(v, str) for v in argv):
                continue
            command = argv[2] if len(argv) == 3 and argv[1] in ("-c", "-lc") else shlex.join(argv)
            if isinstance(item.get("id"), str):
                yield item["id"], command, code
        elif host == "claude-code":
            if event.get("sessionId") != session or event.get("isSidechain"):
                continue
            content = event.get("message", {}).get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if (
                    event.get("type") == "assistant"
                    and block.get("type") == "tool_use"
                    and block.get("name") == "Bash"
                ):
                    command = block.get("input", {}).get("command")
                    if isinstance(command, str) and isinstance(block.get("id"), str):
                        calls[block["id"]] = command
                if (
                    event.get("type") != "user"
                    or block.get("type") != "tool_result"
                    or block.get("tool_use_id") not in calls
                    or not _same_cwd(event.get("cwd"), root)
                ):
                    continue
                result = event.get("toolUseResult")
                # Claude emits a string envelope on failed Bash calls. The
                # native is_error flag supplies failure, not the text in it.
                if isinstance(result, str) and block.get("is_error") is True:
                    yield block["tool_use_id"], calls[block["tool_use_id"]], 1
                    continue
                if (
                    not isinstance(result, dict)
                    or any(
                        result.get(key)
                        for key in ("backgroundTaskId", "background_task_id", "interrupted")
                    )
                    or type(block.get("is_error")) is not bool
                ):
                    continue
                yield block["tool_use_id"], calls[block["tool_use_id"]], int(block["is_error"])


def synchronize(memory, root, host, session, registered):
    path = registered.get("transcript")
    if registered.get("host") != host or not path or not Path(path).is_file():
        return
    from neurath.memory.learning import Learning

    learning = Learning(memory)
    # Read the bounded native tail before taking the database write lock. Recheck
    # every source on replay; caching IDs alone would hide changed native evidence.
    completed = list(command_records(path, host, session, root))
    worktree = str(Path(root).resolve())
    with memory.connection() as db:
        for identity, command, code in completed:
            original = registered.get("tools", {}).get(identity)
            if original:
                command = original.get("command", command)
            if len(command.encode()) > 60000:
                continue
            event_id = memory.record(
                host, session, "native-command:" + identity, "tool", command,
                {"exit_code": code, "worktree": worktree,
                 "authority": "native-process-result"},
                _db=db,
            )
            # Persist the event and its ordered observation together. A conflict
            # rolls back the batch; a later hook may safely replay the same tail.
            learning.observe(event_id, _db=db)
