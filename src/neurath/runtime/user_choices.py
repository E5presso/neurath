"""Bind maintenance decisions to exact targets and fresh native user input.

Maintenance authority is a selected prepared option on a correlated native question
tool call, not an agent boolean, prompt hash or copied prose.
Unsupported/ambiguous host input formats fail closed without inventing a choice.
"""
import hashlib
import itertools
import json
import secrets

from neurath.serialization import canonical
from neurath.project_paths import control_root
from neurath.runtime.choice_selection import question_options, native_selection, verify_selection

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class ChoiceStore:
    def __init__(self, path=None, *, database=None):
        from neurath.runtime.maintenance_tasks import MaintenanceCalls
        self.calls = MaintenanceCalls(path, database=database)
        with self.calls._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS user_choices(
                id TEXT PRIMARY KEY, owner TEXT, request_key TEXT, request TEXT,
                record TEXT, used_key TEXT, proof TEXT, UNIQUE(owner,request_key))""")

    def prepare(self, owner, key, subject, receipt, *, host="codex"):
        if receipt is None:
            raise ValueError("native user prompt receipt required")
        request = canonical(subject)
        if len(request.encode()) > 131072:
            raise ValueError("choice preview exceeds limit")
        with self.calls._db() as db:
            previous = db.execute("SELECT request,record FROM user_choices WHERE owner=? AND request_key=?",
                                  (owner,key)).fetchone()
            if previous:
                if previous[0] != request:
                    raise ValueError("choice key changed target")
                return json.loads(previous[1])
            identifier = secrets.token_hex(24)
            question = subject["question"] + "\n\nReference / 확인 번호: " + identifier
            record = {"user_choice_ref":identifier, "operation":subject["operation"],
                      "target_id":subject["target_id"], "subject_digest":digest(request),
                      "question":question, "decisions":subject["decisions"],
                      "prepared_prompt":receipt, "status":"awaiting-user"}
            record.update(question_options(record, host))
            db.execute("INSERT INTO user_choices VALUES(?,?,?,?,?,?,?)",
                       (identifier,owner,key,request,canonical(record),None,None))
        return record

    def read(self, owner, reference):
        with self.calls._db() as db:
            row=db.execute("SELECT record,used_key,proof FROM user_choices WHERE id=? AND owner=?",
                           (reference,owner)).fetchone()
            application = None if row is None or row[1] is None else db.execute(
                "SELECT status FROM maintenance_calls WHERE owner=? AND key=?",(owner,row[1])).fetchone()
        if row is None:
            raise ValueError("native choice reference missing or wrong owner")
        return {**json.loads(row[0]), "status":"admitted" if row[1] else "awaiting-user",
                "application_status":application[0] if application else "not-recorded",
                "selection":None if row[2] is None else json.loads(row[2])}

    def admit_selection(self, owner, reference, subject, selected, decision, key):
        with self.calls._db() as db:
            row = db.execute("SELECT request,record,used_key,proof FROM user_choices WHERE id=? AND owner=?",
                             (reference, owner)).fetchone()
            if row is None:
                raise ValueError("native choice reference missing or wrong owner")
            if row[0] != canonical(subject):
                raise ValueError("choice target changed; review the current target")
            proof = verify_selection(json.loads(row[1]), selected)
            if proof["decision"] != decision:
                raise ValueError("requested decision differs from native selected option")
            if row[2] is not None:
                if row[2] != key:
                    raise ValueError("native choice already used by another action")
                if json.loads(row[3]) != proof:
                    raise ValueError("native choice key changed selection")
                return proof
            db.execute("UPDATE user_choices SET used_key=?,proof=? WHERE id=? AND owner=?",
                       (key, canonical(proof), reference, owner))
        return proof


def _visible(content):
    if isinstance(content,str):
        return content
    if not isinstance(content,list) or any(
        isinstance(b,dict) and b.get("type") in {"tool_result","tool_use"} for b in content
    ):
        return None
    text=[b.get("text","") for b in content if isinstance(b,dict)
          and b.get("type") in {"text","input_text","output_text"}]
    return "\n".join(text) if text else None


def _question(name, args):
    if name not in {"request_user_input", "functions.request_user_input",
                    "request_user_input_async", "functions.request_user_input_async"}:
        return None
    if isinstance(args,str):
        try:
            args=json.loads(args)
        except ValueError:
            return None
    questions=args.get("questions") if isinstance(args,dict) else None
    if not isinstance(questions,list) or len(questions)!=1 or not isinstance(questions[0],dict):
        return "unsupported native multi-question input"
    return questions[0].get("question") or questions[0].get("title")


def native_messages(root, identity, *, record_limit=2000):
    from neurath.hosts.identity import snapshot, _reverse_native_records
    path=snapshot(root,identity.session).get("transcript")
    if not path:
        raise ValueError("registered native transcript is unavailable")
    records=list(itertools.islice(_reverse_native_records(path,
        {"response_item","event_msg","assistant","user"}),record_limit))
    messages=[]
    for event in reversed(records):
        role=text=None
        if identity.host=="codex":
            payload=event.get("payload",{})
            if event.get("type")=="response_item":
                if payload.get("type")=="message" and payload.get("role") in {"assistant","user"}:
                    if payload.get("channel") not in (None,"final","commentary"):
                        continue
                    role,text=payload["role"],_visible(payload.get("content"))
                elif payload.get("type") in {"function_call","custom_tool_call"}:
                    text=_question(payload.get("name"),payload.get("arguments",payload.get("input")))
                    role="assistant"
            elif event.get("type")=="event_msg" and payload.get("type") in {"user_message","agent_message"}:
                role="user" if payload["type"]=="user_message" else "assistant"
                text=payload.get("message")
        elif event.get("sessionId")==identity.session and not event.get("isSidechain"):
            message=event.get("message",{})
            if event.get("type") in {"assistant","user"}:
                role=event["type"]
                text=_visible(message.get("content"))
                if text is None and role=="assistant":
                    for block in message.get("content",[]):
                        if isinstance(block,dict) and block.get("type")=="tool_use":
                            text=_question(block.get("name"),block.get("input"))
                            if text:
                                break
        if role and isinstance(text,str) and text.strip():
            item=(role,text)
            if not messages or messages[-1]!=item:
                messages.append(item)
    last = next((i for i in range(len(messages)-1,-1,-1) if messages[i][0]=="user"),None)
    return [] if last is None else messages[:last+1]

def verify_registered_prompt(root, session_id, reference, prompt_digest):
    """Recover a pre-SQLite prompt from only the registered native transcript.

    The kernel hashes exact prompt UTF-8 bytes, so this reader deliberately does
    not strip or normalize visible user text. Codex can record one prompt as both
    event_msg and response_item; a digest set collapses those representations.
    The independent evaluator remains responsible for mapping that authenticated
    content to one exact task or goal effect.
    """
    import re
    from neurath.hosts.identity import snapshot, _reverse_native_records

    if not isinstance(prompt_digest, str) or re.fullmatch(r"[0-9a-f]{64}", prompt_digest) is None:
        raise ValueError("registered native prompt digest must be SHA-256")
    expected_reference = f"registered-native-prompt:{prompt_digest}"
    if reference != expected_reference:
        raise ValueError("registered native prompt reference is not canonical")
    registered = snapshot(root, str(session_id))
    host = registered.get("host")
    path = registered.get("transcript")
    if host not in {"codex", "claude-code"} or not isinstance(path, str) or not path:
        raise ValueError("registered native transcript is unavailable")

    observed: set[str] = set()
    records = itertools.islice(
        _reverse_native_records(path, {"response_item", "event_msg", "user"}),
        2000,
    )
    for event in records:
        text = None
        if host == "codex":
            payload = event.get("payload", {})
            if (
                event.get("type") == "event_msg"
                and payload.get("type") == "user_message"
            ):
                text = payload.get("message")
            elif (
                event.get("type") == "response_item"
                and payload.get("type") == "message"
                and payload.get("role") == "user"
            ):
                text = _visible(payload.get("content"))
        elif (
            event.get("type") == "user"
            and event.get("sessionId") == str(session_id)
            and not event.get("isSidechain")
        ):
            text = _visible(event.get("message", {}).get("content"))
        if isinstance(text, str):
            observed.add(digest(text))
    if prompt_digest not in observed:
        raise ValueError("historical native prompt digest is unobserved")
    return {
        "authority_reference": expected_reference,
        "prompt_digest": prompt_digest,
        "source": "registered-native-transcript",
    }

def target(root, operation, target_id):
    from neurath.reporting import Reporting, QUESTION, UPSTREAM
    from neurath.updates import Updates
    if operation in {"reporting_consent","releases_check"} and target_id:
        raise ValueError("this choice does not accept an alternate target")
    if operation=="reporting_consent":
        return {"operation":operation,"target_id":"","snapshot":{"repository":UPSTREAM,"question":QUESTION},
                "question":QUESTION+"\n\n예 / 아니요", "decisions":["yes","no"]}
    if operation=="reporting_approve":
        draft=Reporting(root).read(target_id)
        if draft["data"]["kind"]!="contribution" or draft["status"]!="draft":
            raise ValueError("choice requires an unsent contribution draft")
        body={k:draft[k] for k in ("id","title","body","repository")}
        return {"operation":operation,"target_id":target_id,"snapshot":body,
                "question":draft["title"]+"\n\n"+draft["body"]+"\n\nRepository: "+draft["repository"]+
                           "\n\n이 기여 내용의 공개 제출을 승인할까요? / Approve publishing this contribution?\n예 / 아니요",
                "decisions":["yes","no"]}
    if operation=="releases_choose":
        service=Updates(root)
        state=service._read()
        offer=service._offer(state,target_id)
        operation_state=state.get("operation")
        prepared=bool(operation_state and operation_state.get("phase")=="prepared"
                      and operation_state.get("offer_id")==target_id)
        preview=None if not prepared else {k:operation_state[k] for k in ("plan_id","distribution","changes")}
        body={"offer":offer,"preview":preview}
        changes="" if not prepared else "\n".join(
            "- "+c["action"]+": "+c["path"] for c in preview["changes"])
        relation=offer.get("relation") or (
            "same-version-origin-unknown" if offer["current"]==offer["version"] else "newer-version")
        relation_text={
            "newer-version":"newer version / 새 버전",
            "same-version-origin-unknown":(
                "same version; installed wheel origin unknown / 같은 버전; 설치 wheel 출처 미확인"),
            "same-version-distinct-asset":(
                "same version; distinct from recorded installed asset / "
                "같은 버전; 기록된 설치 asset과 다름"),
        }.get(relation)
        if relation_text is None:
            raise ValueError("invalid release asset relation")
        question=(f"Neurath {offer['current']} → {offer['version']}\n"
                  f"Wheel SHA-256: {offer['sha256']}\nAsset relation: {relation_text}\n"+changes)
        question+="\n\n이 업데이트를 승인할까요? / Approve this update?" if prepared else (
            "\n\n업데이트를 거절하거나 나중으로 미룰까요? / Decline or defer this update?")
        decisions=["yes","no","later"] if prepared else ["no","later"]
        return {"operation":"releases_choose","target_id":target_id,"snapshot":body,
                "question":question+"\n"+" / ".join(decisions),"decisions":decisions}
    if operation=="releases_check":
        return {"operation":operation,"target_id":"","snapshot":{"repository":UPSTREAM},
                "question":"새 버전을 지금 다시 확인할까요? / Check for updates again now?\nyes / no",
                "decisions":["yes","no"]}
    raise ValueError("unsupported native choice operation")


def _store(root):
    from neurath.runtime.database import RuntimeDatabase

    root = control_root(root)
    return ChoiceStore(database=RuntimeDatabase(root))


def prepare(root, fields, *, identity, expected_turn, context):
    from neurath.runtime.state_tasks import _handle
    handle=_handle(root,identity,expected_turn,context)
    receipt=handle.inspect().foreground_turns[handle.actor_id].user_prompt_receipt
    if receipt is None:
        raise ValueError("native user prompt receipt is missing")
    subject=target(root,fields["operation"],fields.get("target_id",""))
    store = _store(root)
    result=store.prepare(identity.address,fields["key"],subject,receipt.to_payload(), host=identity.host)
    return {**result,"preview":subject["snapshot"],
            "next_action":"Call native_question.tool with its exact arguments to display the prepared options. "
                          "Wait for the actual selection, then apply its decision with user_choice_ref. "
                          "Do not supply answers, infer consent from prose, or repeat an unanswered question. "
                          "If the host question tool is unavailable, preserve this pending choice and report the limitation."}



def validate(root, name, fields, *, identity, expected_turn, context):
    from neurath.runtime.state_tasks import _handle
    _handle(root,identity,expected_turn,context)
    subject=target(root,name,fields.get("draft_id",fields.get("offer_id","")))
    store = _store(root)
    choice=store.read(identity.address,fields["user_choice_ref"])
    if choice["subject_digest"]!=digest(canonical(subject)):
        raise ValueError("choice target changed")
    selected=native_selection(root,identity,choice)
    proof=verify_selection(choice,selected)
    if proof["decision"]!=fields["decision"]:
        raise ValueError("requested decision differs from native selected option")
    return subject,selected


def commit(root, name, fields, validated, *, identity):
    subject,selected=validated
    return _store(root).admit_selection(identity.address,fields["user_choice_ref"],subject,selected,
                                       fields["decision"],fields["key"])


def read(root, fields, *, identity):
    return _store(root).read(identity.address, fields["user_choice_ref"])
