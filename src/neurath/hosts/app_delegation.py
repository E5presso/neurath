"""Extract sender identity only after verifying native app delivery provenance."""
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import UUID


def current_delivery(root, session, turn_id):
    from neurath.hosts.identity import snapshot, _verified_peer_delivery, _state
    state = _state(root, session)
    turn = state.foreground_turns[state.session.root_actor_id]
    path = snapshot(root, session).get("transcript")
    if turn.vendor_turn_id != turn_id or turn.user_prompt_receipt is not None:
        raise ValueError("app delegation requires the exact current non-user turn")
    value = None if not path else _verified_peer_delivery(root, Path(path), session, turn_id)
    if value is None:
        raise ValueError("app delegation lacks paired native ingress")
    # The identity validator pins the latest ingress/output/completion pair. Read
    # that same first incoming output, never a called tool's response or UI parser.
    if value.get("name") not in {"create_thread", "send_message_to_thread"}:
        raise ValueError("this app ingress is not a task delegation")
    output = value["output"]
    if len(output.encode()) > 65536 or "<!" in output:
        raise ValueError("unsupported app envelope")
    try:
        envelope = ET.fromstring(output)
        children = list(envelope)
        if (envelope.tag != "codex_delegation" or envelope.attrib
                or [child.tag for child in children] != ["source_thread_id", "input"]
                or any(child.attrib or list(child) for child in children)
                or (envelope.text or "").strip()
                or any((child.tail or "").strip() for child in children)):
            raise ValueError("ambiguous app envelope")
        source = children[0].text or ""
        if str(UUID(source)) != source:
            raise ValueError("noncanonical app source ID")
        text = children[1].text or ""
    except (ET.ParseError, ValueError) as error:
        raise ValueError("invalid outer app delegation envelope") from error
    return {"source_session": source, "target_session": session, "turn": turn_id,
            "delivery_id": value["id"], "output_digest": hashlib.sha256(output.encode()).hexdigest(),
            "input": text}
