"""Native question selections, correlated by tool call rather than prompt prose.

Only registered host transcript frames supply results. A prepared option digest
binds the choice instance, target, decision and visible option. Transport JSON and
assistant narration are not user answer bytes and never enter that digest.
"""
import hashlib
import itertools
import json

from neurath.serialization import canonical

SCHEMA = "neurath.user-choice.options.v1"
LABELS = {
    "yes": ("승인 / Approve", "표시된 대상과 변경을 승인합니다. / Approve the displayed action."),
    "no": ("거절 / Decline", "표시된 작업을 승인하지 않습니다. / Decline the displayed action."),
    "later": ("나중에 / Later", "지금 결정하지 않고 보류합니다. / Defer this decision."),
}
ASYNC = {"request_user_input_async", "functions.request_user_input_async"}


def option_digest(reference, subject_digest, option):
    return hashlib.sha256(canonical({"schema": SCHEMA, "user_choice_ref": reference,
        "subject_digest": subject_digest,
        **{k: option[k] for k in ("decision", "label", "description")}}).encode()).hexdigest()


def question_options(record, host):
    options = []
    for decision in record["decisions"]:
        label, description = LABELS[decision]
        option = {"decision": decision, "label": label, "description": description}
        options.append({**option, "digest": option_digest(record["user_choice_ref"], record["subject_digest"], option)})
    visible = [{k: o[k] for k in ("label", "description")} for o in options]
    if host == "claude-code":
        native = {"tool": "AskUserQuestion", "arguments": {"questions": [{
            "question": record["question"], "header": "동의 / Consent", "options": visible, "multiSelect": False}]}}
    elif host == "codex":
        native = {"tool": "request_user_input_async", "arguments": {"questions": [{
            "title": record["question"], "options": [o["label"] for o in options]}]}}
    else:
        raise ValueError("native question selections unsupported on this host")
    return {"selection_schema": SCHEMA, "options": options, "native_question": native}


def _object(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def _arguments_match(choice, tool, arguments):
    expected = choice.get("native_question")
    if not expected:
        raise ValueError("legacy text choice has no prepared options; prepare a native option question")
    if not isinstance(tool, str) or tool.removeprefix("functions.") != expected["tool"]:
        return False
    args = _object(arguments)
    # Never accept agent-populated answers or a changed preview/multi-select setting.
    if args is None or args.get("answers") or args.get("annotations"):
        return False
    if set(args) - {"questions", "metadata", "answers", "annotations"}:
        return False
    return args.get("questions") == expected["arguments"]["questions"]


def verify_selection(choice, selected):
    if choice.get("selection_schema") != SCHEMA:
        raise ValueError("legacy text choice has no prepared options; prepare a native option question")
    call_id = selected.get("call_id")
    if not isinstance(call_id, str) or not call_id.strip():
        raise ValueError("native question tool call identity is missing")
    tool = selected.get("tool", "")
    if not _arguments_match(choice, tool, selected.get("arguments")):
        raise ValueError("native question options differ from the prepared choice")
    result = _object(selected.get("result"))
    if result is None or result.get("afkTimeoutMs") is not None or any(result.get(k) for k in (
            "is_error", "isError", "error", "cancelled", "canceled", "response", "annotations")):
        raise ValueError("native question was cancelled, automatic, or answered with free text")
    questions = selected["arguments"]["questions"]
    if tool == "AskUserQuestion":
        if result.get("questions") != questions:
            raise ValueError("returned questions differ from the native question call")
        key = questions[0]["question"]
        answers = result.get("answers")
        answer = answers.get(key) if isinstance(answers, dict) and set(answers) == {key} else None
    elif tool in ASYNC:
        # The async host envelope carries the original call ID and question index.
        if result.get("question_item_id") != [tool.removeprefix("functions."), call_id, 0]:
            raise ValueError("native selection belongs to another question call")
        if result.get("question") != questions[0]["title"]:
            raise ValueError("native selection question changed")
        answer = result.get("answer")
    else:
        raise ValueError("unsupported native question tool")
    if not isinstance(answer, str):
        raise ValueError("select exactly one prepared option")
    # Only transport edge whitespace is normalized; prose is never interpreted.
    answer = answer.strip()
    options = [o for o in choice["options"] if o["label"] == answer]
    if len(options) != 1:
        raise ValueError("native answer is not a prepared option")
    option = options[0]
    actual = option_digest(choice["user_choice_ref"], choice["subject_digest"], {**option, "label": answer})
    if actual != option["digest"]:
        raise ValueError("selected option digest differs from the prepared option")
    return {"decision": option["decision"], "user_choice_ref": choice["user_choice_ref"],
            "subject_digest": choice["subject_digest"], "option_digest": actual,
            "tool": tool, "tool_call_id": call_id, "authority": "native-question-selection"}


def _async_replies(text):
    if not isinstance(text, str):
        return []
    text = text.strip()
    start, end = "<send_user_message_question_reply>", "</send_user_message_question_reply>"
    if not text.startswith(start) or not text.endswith(end):
        return []
    try:
        rows = json.loads(text[len(start):-len(end)])
    except ValueError:
        return []
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return []
    row = rows[0]
    try:
        item_id = json.loads(row.get("questionItemId", ""))
    except (ValueError, TypeError):
        return []
    if (not isinstance(item_id, list) or len(item_id) != 3
            or not isinstance(item_id[0], str) or item_id[0] not in ASYNC
            or not isinstance(item_id[1], str) or type(item_id[2]) is not int or item_id[2] != 0):
        return []
    return [{"question_item_id": item_id, "question": row.get("question"), "answer": row.get("answer")}]


def native_selection(root, identity, choice, *, record_limit=2000):
    from neurath.hosts.identity import snapshot, _reverse_native_records
    from neurath.runtime.user_choices import _visible

    path = snapshot(root, identity.session).get("transcript")
    if not path:
        raise ValueError("registered native transcript is unavailable")
    records = list(itertools.islice(_reverse_native_records(path,
        {"response_item", "event_msg", "assistant", "user"}), record_limit))
    calls, results, accepted = {}, {}, set()

    def add_call(call_id, tool, args):
        args = _object(args)
        if not isinstance(call_id, str) or not isinstance(tool, str):
            return
        if not _arguments_match(choice, tool, args):
            return
        call = {"tool": tool, "call_id": call_id, "arguments": args}
        if call_id in calls and calls[call_id] != call:
            raise ValueError("native question call identity was reused")
        calls[call_id] = call

    def add_result(call_id, result):
        if call_id not in calls:
            return
        result = _object(result)
        if result is None:
            return
        if call_id in results and results[call_id] != result:
            raise ValueError("native question has conflicting results")
        results[call_id] = result

    for event in reversed(records):
        if identity.host == "codex":
            payload = event.get("payload", {})
            if event.get("type") == "response_item":
                kind = payload.get("type")
                if kind in {"function_call", "custom_tool_call"}:
                    add_call(payload.get("call_id"), payload.get("name"), payload.get("arguments", payload.get("input")))
                elif kind in {"function_call_output", "custom_tool_call_output"}:
                    call_id = payload.get("call_id")
                    result = _object(payload.get("output"))
                    if call_id in calls and result and result.get("accepted") is True:
                        accepted.add(call_id)
                elif kind == "message" and payload.get("role") == "user":
                    for reply in _async_replies(_visible(payload.get("content"))):
                        call_id = reply["question_item_id"][1]
                        if call_id in accepted:
                            add_result(call_id, reply)
            elif event.get("type") == "event_msg" and payload.get("type") == "user_message":
                for reply in _async_replies(payload.get("message")):
                    call_id = reply["question_item_id"][1]
                    if call_id in accepted:
                        add_result(call_id, reply)
        elif identity.host == "claude-code" and event.get("sessionId") == identity.session and not event.get("isSidechain"):
            content = event.get("message", {}).get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if event.get("type") == "assistant" and block.get("type") == "tool_use":
                    add_call(block.get("id"), block.get("name"), block.get("input"))
                elif event.get("type") == "user" and block.get("type") == "tool_result":
                    call_id = block.get("tool_use_id")
                    if call_id not in calls:
                        continue
                    if block.get("is_error"):
                        add_result(call_id, {"is_error": True})
                        continue
                    # Claude retains the structured output alongside its display prose.
                    result = event.get("toolUseResult")
                    if result is None:
                        result = block.get("content")
                    add_result(call_id, result)
    if len(calls) != 1:
        raise ValueError("one exact native question call is required; missing or duplicate question")
    call_id, call = next(iter(calls.items()))
    if call_id not in results:
        raise ValueError("native question selection is not yet observed; do not infer consent or ask again")
    selected = {**call, "result": results[call_id]}
    verify_selection(choice, selected)
    return selected
