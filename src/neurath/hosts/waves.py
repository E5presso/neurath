"""Native root wave preparation and pre-wait enforcement; no extra goal ledger."""
import hashlib
import json

from neurath.hosts.identity import _foreground, _state, journal, snapshot
from neurath.hosts.task_scope import instruction_scope
from scripts.agent_harness.delegation_wave import projection, require_dispatch_before_wait, validate_plan

WAIT_TOOLS = {'wait_agent', 'collaborationwait_agent', 'collaboration.wait_agent',
              'TaskOutput', 'functions.wait', 'clock.sleep', 'sleep',
              'write_stdin', 'functions.write_stdin'}
EXEC_TOOLS = {'functions.exec', 'exec'}


def _dispatch_prepare_code(wave, entry):
    """One exact nested MCP call allowed while ready wave slots remain."""
    arguments = {'delegation_id': entry['delegation_id'],
        'assignment': entry['assignment'], 'task_id': wave['task_id'],
        'expected_task_revision': wave['task_revision'],
        'key': _dispatch_prepare_key(wave, entry['delegation_id'])}
    literal = json.dumps(arguments, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    return ('const r=await tools.mcp__neurath_collaboration__delegation_prepare('
            + literal + ');text(r.structuredContent??r)')


def _dispatch_prepare_key(wave, delegation_id):
    identity = json.dumps([wave['wave_id'], delegation_id],
                          ensure_ascii=True, separators=(',', ':')).encode()
    return 'wave-prepare:' + hashlib.sha256(identity).hexdigest()


def _with_dispatch_codes(wave, result):
    if not wave.get('strict_wrapper_fence'):
        return {**result, 'dispatch_prepare_keys': {identifier: _dispatch_prepare_key(
            wave, identifier) for identifier in (entry['delegation_id'] for entry in wave['entries'])},
            'dispatch_read_code': _dispatch_read_code(wave['wave_id'])}
    entries = {entry['delegation_id']: entry for entry in wave['entries']}
    return {**result, 'dispatch_prepare_code': {identifier: _dispatch_prepare_code(
        wave, entry) for identifier, entry in entries.items()},
        'dispatch_read_code': _dispatch_read_code(wave['wave_id'])}


def _dispatch_read_code(wave_id):
    literal = json.dumps({'wave_id': wave_id}, ensure_ascii=True,
                         sort_keys=True, separators=(',', ':'))
    return ('const r=await tools.mcp__neurath_collaboration__delegation_wave_read('
            + literal + ');text(r.structuredContent??r)')


def _legacy_prepare_code_is_exact(code, wave, ready_ids):
    """Accept one canonical prepare call, never interpret arbitrary wrapper code."""
    prefix = 'const r=await tools.mcp__neurath_collaboration__delegation_prepare('
    suffix = ');text(r.structuredContent??r)'
    if not isinstance(code, str) or not code.startswith(prefix) or not code.endswith(suffix):
        return False
    try:
        arguments = json.loads(code[len(prefix):-len(suffix)])
    except (TypeError, ValueError):
        return False
    if (not isinstance(arguments, dict) or
            set(arguments) != {'assignment', 'delegation_id', 'expected_task_revision',
                               'key', 'task_id'} or
            arguments.get('delegation_id') not in ready_ids or
            not isinstance(arguments.get('assignment'), str) or
            not arguments['assignment'].strip() or
            len(arguments['assignment'].encode()) > 8192):
        return False
    entry = {'delegation_id': arguments['delegation_id'],
             'assignment': arguments['assignment']}
    return code == _dispatch_prepare_code(wave, entry)


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
    plan['strict_wrapper_fence'] = all('assignment' in entry for entry in entries)
    plan.update(task_id=task_id, task_revision=expected_task_revision, workflow_id=workflow_id,
                wave_id=wave_id, owner=str(handle.actor_id),
                foreground={**_foreground(state, root, task_scope=scope), 'task_scope': scope})
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
    return {'wave_id': wave_id, **_with_dispatch_codes(plan, result)}


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
    tool = payload.get('tool_name')
    if payload.get('agent_id') or tool not in WAIT_TOOLS | EXEC_TOOLS:
        return
    state = _state(root, payload['session_id'])
    data = snapshot(root, payload['session_id'])
    from neurath.hosts.identity import _locator
    from scripts.agent_harness.runtime_database import RuntimeDatabase
    from scripts.agent_harness.task_service import read_ledger
    with RuntimeDatabase(_locator(root).control_root).transaction() as tx:
        _, ledger = read_ledger(tx, state)
    active_tasks = {task.id for task in ledger.tasks if task.status.value == 'in_progress'}
    ready = []
    for wave_id, recorded in data.get('waves', {}).items():
        wave = {**recorded, 'wave_id': wave_id}
        if wave['task_id'] not in active_tasks:
            continue
        result = projection(wave, state, data['spawns'])
        if not result['all_succeeded']:
            instruction_scope(root, state, wave['task_id'], wave['task_revision'])
            if result['dispatch_required']:
                ready.append((wave, result))
    if tool in EXEC_TOOLS:
        if not ready:
            return
        code = (payload.get('tool_input') or {}).get('code')
        if any(code == _dispatch_read_code(wave['wave_id']) for wave, _ in ready):
            return
        if any((code == _dispatch_prepare_code(wave, entry)
                if wave.get('strict_wrapper_fence') else
                _legacy_prepare_code_is_exact(code, wave, result['dispatch_required']))
               for wave, result in ready for entry in wave['entries']
               if entry['delegation_id'] in result['dispatch_required']):
            return
        raise ValueError('dispatch ready wave work before using the host tool wrapper')
    for wave, _ in ready:
        require_dispatch_before_wait(wave, state, data['spawns'])


def read(root, handle, *, wave_id):
    state = handle.inspect()
    data = snapshot(root, str(handle.session_id))
    wave = data.get('waves', {}).get(wave_id)
    if wave is None or wave['owner'] != str(handle.actor_id):
        raise ValueError('wave requires its exact root owner')
    return {'wave_id': wave_id, **_with_dispatch_codes({**wave, 'wave_id': wave_id},
            projection(wave, state, data['spawns'])),
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
    return {'wave_id': wave_id, **_with_dispatch_codes({**wave, 'wave_id': wave_id}, result)}
