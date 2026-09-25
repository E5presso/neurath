"""Explicit simulated native review witnesses for isolated domain tests, not live proof."""
import json
from scripts.agent_harness.runtime_database import RuntimeDatabase


def record_review_spawn(handle, target):
    host = handle.runtime.value
    session = str(handle.session_id)
    with RuntimeDatabase(handle._repository_control_root()).transaction() as tx:
        old = tx.get('host-journal', session)
        data = json.loads(old.payload) if old else {'session': session, 'spawns': {}}
        data['spawns']['fixture:' + str(target)] = {'host': host,
            'parent': str(handle.inspect().session.root_actor_id),
            'child': str(target).removeprefix(host + ':'), 'role': 'review',
            'context': {'mode': 'fresh', 'fork_turns': 'none'}}
        tx.put('host-journal', session, json.dumps(data).encode(),
               expected_revision=old.revision if old else None)


def context_provenance(owner, target):
    return {'authority': 'native-spawn', 'mode': 'fresh', 'role': 'review',
            'owner': str(owner), 'target': str(target), 'call_id': 'fixture:' + str(target)}
