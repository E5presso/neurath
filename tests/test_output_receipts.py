"""출력과 읽음 사이에 개정이 바뀌거나 같은 receipt가 반복돼도 원 결과를 보존한다."""

import json

from neurath.application.usecases.receive_hook import ReceiveHookCommand, ReceiveHookUseCase
from neurath.domain.enums.hook_event import HookEvent
from tests.support.requests import run
from tests.test_cli import invoke
from tests.test_collaboration import assignment, call
from tests.test_collaboration import collaboration as collaboration
from tests.test_newsroom import publish, revise, stored


async def test_stale_headline_receipt_never_marks_new_revision_submitted(database, collaboration):
    _, author, receiver, recipient, _ = collaboration
    article = await publish(database, author)
    selection = await run(
        ReceiveHookUseCase,
        ReceiveHookCommand(
            provider="claude",
            host_session_id=receiver.session.host_session_id,
            working_directory=receiver.session.working_directory,
            event=HookEvent.PRE_TOOL_USE,
        ),
        database_path=database,
    )
    assert selection.article_ids == ((article.uid, 1),)
    rendered = json.dumps(list(selection.inbox))
    assert str(article.uid) in rendered
    await revise(database, author, article)
    await call(
        database, "record_hook_output", "RecordHookOutput", recipient.uid, (), selection.article_ids
    )
    current = await stored(database, article)
    notice = next(item for item in current.notices if item.revision_number == 2)
    assert notice.status.value == "pending"


async def test_verify_output_and_duplicate_message_receipt_preserve_submission_boundary(
    database, collaboration
):
    _, _, receiver, recipient, _ = collaboration
    delegated = await assignment(database, collaboration)
    payload = {
        "session_id": receiver.session.host_session_id,
        "cwd": receiver.session.working_directory,
        "prompt_id": "receipt-turn",
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_use_id": "read-only",
    }
    response = await invoke(
        database, ["hook", "verify", "--provider", "claude"], json.dumps(payload)
    )
    assert response.exit_code == 1
    assert not json.loads(response.stdout)["verified"]
    before = await call(
        database, "read_message", "ReadMessage", delegated.message_id, recipient.uid
    )
    assert before.status.value == "unknown" and not before.read
    await call(
        database,
        "record_hook_output",
        "RecordHookOutput",
        recipient.uid,
        (delegated.message_id,),
        (),
    )
    after = await call(database, "read_message", "ReadMessage", delegated.message_id, recipient.uid)
    assert after.delivery_attempt == before.delivery_attempt and not after.read
