"""DAG dispatch accounting over existing native delegation and spawn evidence."""
import json


def validate_plan(value):
    entries = value['entries']
    capacity = value['max_parallel']
    if (not entries or len(entries) > 128 or type(capacity) is not int or not 1 <= capacity <= 64
            or not value.get('capacity_basis', '').strip()):
        raise ValueError('wave requires bounded entries and an explicit capacity basis')
    ids = [entry['delegation_id'] for entry in entries]
    if len(set(ids)) != len(ids) or any(not isinstance(i, str) or not i.strip() for i in ids):
        raise ValueError('wave delegation identities must be unique')
    for entry in entries:
        deps = entry['depends_on']
        if len(set(deps)) != len(deps) or set(deps) - set(ids):
            raise ValueError('wave dependencies must name distinct entries')
    remaining, completed = list(entries), set()
    parallel = False
    while remaining:
        ready = [entry for entry in remaining if set(entry['depends_on']) <= completed]
        if not ready:
            raise ValueError('wave dependency cycle')
        parallel |= len(ready) > 1
        completed.update(entry['delegation_id'] for entry in ready)
        remaining = [entry for entry in remaining if entry not in ready]
    if parallel and capacity == 1 and not value.get('serialization_reason', '').strip():
        raise ValueError('parallel work requires an explicit serialization reason at capacity one')
    return json.loads(json.dumps(value))


def projection(wave, process, spawns):
    states = {}
    for entry in wave['entries']:
        identifier = entry['delegation_id']
        delegation = process.delegations.get(identifier)
        records = [s for s in spawns.values() if s.get('delegation', {}).get('id') == identifier]
        if delegation is not None:
            if delegation.status.value == 'consumed':
                result = delegation.result
                states[identifier] = ('succeeded' if result is not None
                    and result.verdict in {'pass', 'succeeded', 'completed'}
                    and not result.blocking_findings else 'failed')
            elif delegation.status.value == 'cancelled':
                states[identifier] = 'failed'
            elif delegation.status.value == 'reported':
                states[identifier] = 'reported'
            else:
                states[identifier] = 'active'
        elif any(s.get('spawn_error') for s in records):
            states[identifier] = 'failed'
        elif records:
            states[identifier] = 'active'  # Includes pre-spawn reservations.
        else:
            states[identifier] = 'pending'
    done = {key for key, status in states.items() if status == 'succeeded'}
    active = [key for key, status in states.items() if status == 'active']
    ready = [entry['delegation_id'] for entry in wave['entries']
             if states[entry['delegation_id']] == 'pending' and set(entry['depends_on']) <= done]
    slots = max(0, wave['max_parallel'] - len(active))
    return {'states': states, 'active': active, 'dispatch_required': ready[:slots],
            'reported': [key for key, status in states.items() if status == 'reported'],
            'failed': [key for key, status in states.items() if status == 'failed'],
            'all_succeeded': len(done) == len(states), 'capacity': wave['max_parallel'],
            'capacity_authority': 'owner-observation', 'capacity_basis': wave['capacity_basis']}


def require_dispatch_before_wait(wave, process, spawns):
    result = projection(wave, process, spawns)
    if result['dispatch_required']:
        raise ValueError('dispatch ready wave work before waiting: ' + ', '.join(result['dispatch_required']))
    return result


def require_complete(data, process, task_id):
    for wave in data.get('waves', {}).values():
        if wave['task_id'] == task_id and not projection(wave, process, data['spawns'])['all_succeeded']:
            raise ValueError('task still has unfinished or unsuccessful native wave work')


def validate_mutation(tx, process, wave):
    """Fence both prompted and peer-turn waves in the journal write transaction."""
    from scripts.agent_harness.task_service import validate_task_scope
    owner = process.session.root_actor_id
    turn = process.foreground_turns.get(owner)
    foreground = wave.get('foreground', {})
    scope = foreground.get('task_scope')
    if (wave.get('owner') != str(owner) or process.session.status.value != 'active'
            or process.actors[owner].status.value != 'active'
            or turn is None or turn.status.value != 'active' or not isinstance(scope, dict)):
        raise ValueError('wave requires its active root task scope')
    expected = {'generation': turn.generation, 'turn': turn.vendor_turn_id,
                'prompt': None if turn.user_prompt_receipt is None else turn.user_prompt_receipt.prompt_digest,
                'task_scope': scope}
    if (foreground != expected or wave.get('task_id') != scope.get('task_id')
            or wave.get('task_revision') != scope.get('task_revision')):
        raise ValueError('wave task scope or native turn changed before commit')
    validate_task_scope(tx, process, scope)
    if wave.get('workflow_id'):
        workflow = process.workflows.get(wave['workflow_id'])
        if workflow is None or workflow.owner_actor_id != owner or workflow.status.value != 'active':
            raise ValueError('wave workflow changed before commit')
