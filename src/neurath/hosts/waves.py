"""Native root wave preparation and pre-wait enforcement; no extra goal ledger."""
import hashlib
import itertools
import json
import re
from pathlib import Path

from neurath.hosts.identity import _foreground, _state, journal, snapshot
from neurath.hosts.task_scope import instruction_scope
from scripts.agent_harness.delegation_wave import projection, require_dispatch_before_wait, validate_plan

WAIT_TOOLS = {'wait_agent', 'collaborationwait_agent', 'collaboration.wait_agent',
              'TaskOutput', 'functions.wait', 'clock.sleep', 'sleep',
              'write_stdin', 'functions.write_stdin'}


def _dispatch_prepare_code(wave, entry):
    """One exact nested MCP call allowed while ready wave slots remain."""
    arguments = {'delegation_id': entry['delegation_id'],
        'assignment': entry['assignment'], 'task_id': wave['task_id'],
        'expected_task_revision': wave['task_revision'],
        'key': _dispatch_prepare_key(wave, entry['delegation_id'])}
    if 'role' in entry:
        arguments['role'] = entry['role']
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


def admit(root, state, data, delegation_id, *, host=None, inputs=None,
          assignment=None, role=None):
    matches = [wave for wave in data.get('waves', {}).values()
               if delegation_id in {entry['delegation_id'] for entry in wave['entries']}]
    if not matches:
        return
    wave = matches[0]
    entry = next(entry for entry in wave['entries'] if entry['delegation_id'] == delegation_id)
    intent = data.get('intents', {}).get(delegation_id, {})
    observed_assignment = assignment if assignment is not None else intent.get('assignment')
    observed_role = role if role is not None else intent.get('role', 'worker')
    if ('assignment' in entry and observed_assignment != entry['assignment']):
        raise ValueError('wave delegation assignment differs from the prepared entry')
    if wave.get('strict_wrapper_fence') and observed_role != entry.get('role', 'worker'):
        raise ValueError('wave delegation role differs from the prepared entry')
    instruction_scope(root, state, wave['task_id'], wave['task_revision'])
    result = projection(wave, state, data['spawns'])
    if delegation_id not in result['dispatch_required']:
        raise ValueError('wave entry is not dependency-ready or has no free slot')
    if host == 'claude-code' and wave['max_parallel'] > 1 and not (inputs or {}).get('run_in_background'):
        raise ValueError('parallel Claude wave requires background Agent dispatch')


def before_wait(root, payload):
    from neurath.hosts.hooks import SHELL_TOOLS
    tool = payload.get('tool_name')
    # A wrapper's source text does not prove which nested tool it will invoke.
    # Gate only tool calls that the host exposes as their own events.
    if payload.get('agent_id') or tool not in WAIT_TOOLS | SHELL_TOOLS:
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
    if tool in SHELL_TOOLS and ready:
        raise ValueError('dispatch ready wave work before a blocking-capable shell command')
    if ready and tool in WAIT_TOOLS and payload.get('tool_use_id'):
        inputs = payload.get('tool_input') or {}
        # One bounded observation per existing wave; this is diagnostic evidence,
        # never task completion or authority supplied by the agent.
        with journal(root, payload['session_id']) as current:
            observations = current.setdefault('wave_wait_denials', {})
            for wave, result in ready:
                observations[wave['wave_id']] = {
                    'authority': 'native-pre-tool-use', 'tool': tool,
                    'invocation_id': payload['tool_use_id'], 'native_turn': payload.get('turn_id'),
                    'process_id': inputs.get('session_id') if type(inputs.get('session_id')) is int else None,
                    'empty_input': inputs.get('chars', '') == '',
                    'dispatch_required': result['dispatch_required'],
                }
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
            'attempts': wave.get('attempts', []),
            'last_wait_denial': data.get('wave_wait_denials', {}).get(wave_id)}


def retry(root, handle, *, wave_id, delegation_id, replacement_id, key=None):
    state = handle.inspect()
    with journal(root, str(handle.session_id)) as data:
        wave = data.get('waves', {}).get(wave_id)
        if wave is None or wave['owner'] != str(handle.actor_id):
            raise ValueError('wave requires its exact root owner')
        scope = instruction_scope(root, state, wave['task_id'], wave['task_revision'])
        if delegation_id not in projection(wave, state, data['spawns'])['failed']:
            _recover_rejected_name(root, state, data, delegation_id)
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


def _recover_rejected_name(root, state, data, delegation_id):
    """Recover a legacy reservation only from its exact native validation failure."""
    from neurath.hosts.identity import _reverse_native_records, native_root_turn

    matches = [(call, record) for call, record in data['spawns'].items()
               if record.get('delegation', {}).get('id') == delegation_id]
    if len(matches) != 1 or data.get('host') != 'codex' or not data.get('transcript'):
        return
    call, record = matches[0]
    if (record.get('child') or record.get('returned_child')
            or data.get('intents', {}).get(delegation_id, {}).get('call_id') != call):
        return
    path = Path(data['transcript'])
    turn = state.foreground_turns[state.session.root_actor_id]
    if not native_root_turn(root, path, str(state.session.id), turn.vendor_turn_id):
        return
    calls, results = [], []
    for row in itertools.islice(_reverse_native_records(path, {'function_call', 'function_call_output'}), 4096):
        item = row.get('payload', {})
        if item.get('call_id') != call:
            continue
        if (row.get('metadata', {}).get('client_authored') is not False
                or item.get('internal_chat_message_metadata_passthrough', {}).get('turn_id')
                    != record['foreground']['turn']):
            return
        (calls if item.get('type') == 'function_call' else results).append(item)
    if len(calls) != 1 or len(results) != 1:
        return
    if (calls[0].get('name') != 'spawn_agent'
            or calls[0].get('namespace') not in (None, 'collaboration')
            or results[0].get('output') != 'agent_name must use only lowercase letters, digits, and underscores'):
        return
    try:
        name = json.loads(calls[0]['arguments']).get('task_name')
    except (KeyError, TypeError, ValueError):
        return
    if not isinstance(name, str) or re.fullmatch(r'[a-z0-9_]+', name) is not None:
        return
    record['spawn_error'] = 'native-task-name-validation-failed'
    record['failure_evidence'] = {'call_id': call,
        'result_sha256': hashlib.sha256(json.dumps(results[0], sort_keys=True).encode()).hexdigest()}
