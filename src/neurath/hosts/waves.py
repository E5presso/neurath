"""Native root wave preparation and pre-wait enforcement; no extra goal ledger."""
from neurath.hosts.identity import _foreground, _state, journal, snapshot
from neurath.hosts.task_scope import instruction_scope
from scripts.agent_harness.delegation_wave import projection, require_dispatch_before_wait, validate_plan

WAIT_TOOLS = {'wait_agent', 'collaborationwait_agent', 'collaboration.wait_agent',
              'TaskOutput', 'functions.wait', 'clock.sleep', 'sleep'}


def prepare(root, handle, *, wave_id, task_id, expected_task_revision, entries,
            max_parallel, capacity_basis, serialization_reason='', workflow_id='', key=None):
    state = handle.inspect()
    if handle.actor_id != state.session.root_actor_id:
        raise ValueError('only the root orchestrator can prepare a wave')
    scope = instruction_scope(root, state, task_id, expected_task_revision)
    if workflow_id:
        workflow = state.workflows.get(workflow_id)
        if workflow is None or workflow.owner_actor_id != handle.actor_id or workflow.status.value != 'active':
            raise ValueError('wave requires an active owned workflow')
    plan = validate_plan({'entries': entries, 'max_parallel': max_parallel,
        'capacity_basis': capacity_basis, 'serialization_reason': serialization_reason})
    plan.update(task_id=task_id, task_revision=expected_task_revision, workflow_id=workflow_id,
                owner=str(handle.actor_id), foreground={**_foreground(state, root, task_scope=scope), 'task_scope': scope})
    plan['initial_foreground'] = plan['foreground']
    with journal(root, str(handle.session_id)) as data:
        waves = data.setdefault('waves', {})
        previous = waves.get(wave_id)
        if previous is not None and previous != plan:
            raise ValueError('wave identity cannot be reused with changed content')
        ids = {e['delegation_id'] for e in entries}
        if previous is None:
            used = {e['delegation_id'] for wave in waves.values() for e in wave['entries']}
            if ids & (used | set(state.delegations) | set(data.get('intents', {}))):
                raise ValueError('wave must use previously unassigned delegation identities')
        waves[wave_id] = plan
        result = projection(plan, state, data['spawns'])
    return {'wave_id': wave_id, **result}


def admit(root, state, data, delegation_id, *, host=None, inputs=None):
    matches = [wave for wave in data.get('waves', {}).values()
               if delegation_id in {entry['delegation_id'] for entry in wave['entries']}]
    if not matches:
        return
    wave = matches[0]
    instruction_scope(root, state, wave['task_id'], wave['task_revision'])
    result = projection(wave, state, data['spawns'])
    if delegation_id not in result['dispatch_required']:
        raise ValueError('wave entry is not dependency-ready or has no free slot')
    if host == 'claude-code' and wave['max_parallel'] > 1 and not (inputs or {}).get('run_in_background'):
        raise ValueError('parallel Claude wave requires background Agent dispatch')


def before_wait(root, payload):
    if payload.get('agent_id') or payload.get('tool_name') not in WAIT_TOOLS:
        return
    state = _state(root, payload['session_id'])
    data = snapshot(root, payload['session_id'])
    from neurath.hosts.identity import _locator
    from scripts.agent_harness.runtime_database import RuntimeDatabase
    from scripts.agent_harness.task_service import read_ledger
    with RuntimeDatabase(_locator(root).control_root).transaction() as tx:
        _, ledger = read_ledger(tx, state)
    active_tasks = {task.id for task in ledger.tasks if task.status.value == 'in_progress'}
    for wave in data.get('waves', {}).values():
        if wave['task_id'] not in active_tasks:
            continue
        result = projection(wave, state, data['spawns'])
        if not result['all_succeeded']:
            instruction_scope(root, state, wave['task_id'], wave['task_revision'])
            require_dispatch_before_wait(wave, state, data['spawns'])


def read(root, handle, *, wave_id):
    state = handle.inspect()
    data = snapshot(root, str(handle.session_id))
    wave = data.get('waves', {}).get(wave_id)
    if wave is None or wave['owner'] != str(handle.actor_id):
        raise ValueError('wave requires its exact root owner')
    return {'wave_id': wave_id, **projection(wave, state, data['spawns']),
            'attempts': wave.get('attempts', [])}


def retry(root, handle, *, wave_id, delegation_id, replacement_id, key=None):
    state = handle.inspect()
    with journal(root, str(handle.session_id)) as data:
        wave = data.get('waves', {}).get(wave_id)
        if wave is None or wave['owner'] != str(handle.actor_id):
            raise ValueError('wave requires its exact root owner')
        scope = instruction_scope(root, state, wave['task_id'], wave['task_revision'])
        if delegation_id not in projection(wave, state, data['spawns'])['failed']:
            raise ValueError('only an observed failed wave attempt can be replaced')
        used = {e['delegation_id'] for w in data['waves'].values() for e in w['entries']}
        if replacement_id in used | set(state.delegations) | set(data.get('intents', {})):
            raise ValueError('replacement must use a new delegation identity')
        wave.setdefault('initial_foreground', wave['foreground'])
        wave['foreground'] = {**_foreground(state, root, task_scope=scope), 'task_scope': scope}
        for entry in wave['entries']:
            if entry['delegation_id'] == delegation_id:
                entry['delegation_id'] = replacement_id
            entry['depends_on'] = [replacement_id if dep == delegation_id else dep
                                   for dep in entry['depends_on']]
        wave.setdefault('attempts', []).append({'failed': delegation_id, 'replacement': replacement_id})
        result = projection(wave, state, data['spawns'])
    return {'wave_id': wave_id, **result}
