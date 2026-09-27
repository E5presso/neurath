"""Value observations shared by host adapters and transactional service admission."""

from typing import TypedDict

from neurath.serialization import canonical


class PromptReceipt(TypedDict):
    turn_revision: int
    prompt_digest: str


def prompt_receipt(state, actor) -> PromptReceipt | None:
    turn = state.foreground_turns.get(actor.id)
    receipt = turn.user_prompt_receipt if turn else None
    return None if receipt is None else {
        "turn_revision": receipt.turn_revision, "prompt_digest": receipt.prompt_digest}



def participation(state, actor):
    turn = state.foreground_turns.get(actor.id)
    active = (state.session.status.value == "active" and actor.status.value == "active"
              and turn is not None and turn.status.value == "active")
    key = canonical([turn.generation, turn.vendor_turn_id]) if turn else "no-native-turn"
    return active, key
