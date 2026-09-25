"""Review context comes from the native spawn journal, never a review report."""
import json
from collections.abc import Mapping

from scripts.agent_harness.runtime_database import RuntimeDatabase

REVIEW_KINDS = frozenset({'review-code', 'final-local-review'})


def validate_context(value, owner, target):
    if (not isinstance(value, Mapping) or value.get('authority') != 'native-spawn'
            or value.get('mode') != 'fresh' or value.get('role') != 'review'
            or value.get('owner') != str(owner) or value.get('target') != str(target)
            or not isinstance(value.get('call_id'), str) or not value['call_id']):
        raise ValueError('independent review requires native fresh context provenance')
    return dict(value)


def read_context(handle, target, *, state=None):
    state = state or handle.inspect()
    actor = state.actors.get(target)
    owner = state.session.root_actor_id
    if actor is None or actor.parent_actor_id != owner:
        raise ValueError('review context requires an exact native child')
    with RuntimeDatabase(handle._repository_control_root()).transaction() as tx:
        record = tx.get('host-journal', str(handle.session_id))
    data = {} if record is None else json.loads(record.payload)
    host = state.session.runtime.value
    child = str(target).removeprefix(host + ':')
    matches = [(call, spawn) for call, spawn in data.get('spawns', {}).items()
               if spawn.get('child') == child and spawn.get('parent') == str(owner)
               and spawn.get('host') == host]
    if len(matches) != 1:
        raise ValueError('review context lacks a unique native spawn witness')
    call, spawn = matches[0]
    value = validate_context({'authority': 'native-spawn', 'mode': spawn.get('context', {}).get('mode'),
        'role': spawn.get('role'), 'owner': str(owner), 'target': str(target), 'call_id': call}, owner, target)
    bootstrap = spawn.get('delegation', {}).get('id')
    for delegation in state.delegations.values():
        if delegation.target_actor_id != target or str(delegation.id) == bootstrap:
            continue
        try:
            assignment = json.loads(delegation.assignment)
        except (ValueError, TypeError):
            assignment = {}
        if not isinstance(assignment, dict) or assignment.get('kind') not in REVIEW_KINDS:
            raise ValueError('review context was used for non-review work')
    return value
