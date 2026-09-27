"""Wave dispatch consumes actual native spawn records and successful results."""
from types import SimpleNamespace
import pytest
from neurath.runtime.engine import activate


def domain(tmp_path):
    activate(tmp_path)
    from scripts.agent_harness.delegation_wave import validate_plan, projection, require_dispatch_before_wait
    return validate_plan, projection, require_dispatch_before_wait


def sample(capacity=2):
    return {'entries': [{'delegation_id': 'a', 'depends_on': []},
                        {'delegation_id': 'b', 'depends_on': []},
                        {'delegation_id': 'c', 'depends_on': ['a', 'b']}],
            'max_parallel': capacity, 'capacity_basis': 'native inventory has two slots',
            'serialization_reason': 'one slot available' if capacity == 1 else ''}


def test_fill_all_ready_slots_before_wait(tmp_path):
    validate, project, guard = domain(tmp_path)
    wave = validate(sample())
    process = SimpleNamespace(delegations={})
    spawns = {'spawn-a': {'delegation': {'id': 'a'}, 'returned_child': 'child-a'}}
    assert project(wave, process, spawns)['dispatch_required'] == ['b']
    with pytest.raises(ValueError, match='dispatch'):
        guard(wave, process, spawns)
    spawns['spawn-b'] = {'delegation': {'id': 'b'}, 'returned_child': 'child-b'}
    guard(wave, process, spawns)
    assert project(wave, process, spawns)['dispatch_required'] == []


def test_failed_predecessor_never_unlocks_dependent_work(tmp_path):
    validate, project, _ = domain(tmp_path)
    wave = validate(sample())
    consumed = lambda verdict: SimpleNamespace(status=SimpleNamespace(value='consumed'),
        result=SimpleNamespace(verdict=verdict, blocking_findings=()))
    state = SimpleNamespace(delegations={'a': consumed('failed'), 'b': consumed('pass')})
    result = project(wave, state, {})
    assert result['dispatch_required'] == []
    assert result['all_succeeded'] is False
    assert result['failed'] == ['a']


def test_spawn_reservation_counts_and_failure_releases_it(tmp_path):
    validate, project, guard = domain(tmp_path)
    wave = validate(sample(1)); process = SimpleNamespace(delegations={})
    spawns = {'s': {'delegation': {'id': 'a'}}}
    guard(wave, process, spawns)
    assert project(wave, process, spawns)['active'] == ['a']
    spawns['s']['spawn_error'] = 'PermissionDenied'
    assert project(wave, process, spawns)['active'] == []
    assert project(wave, process, spawns)['failed'] == ['a']


def test_invalid_codex_child_name_does_not_consume_prepared_intent(runtime):
    from neurath.hosts.identity import prepare_bound_delegation, snapshot

    store, _, task = setup_peer(runtime)
    prepare_bound_delegation(store.worktree, store.handle, 'name-check', 'Inspect wave',
                             task_id=task['id'], expected_task_revision=task['revision'])
    send = runtime[3]
    invalid = {'task_name': 'name-check', 'message': 'Inspect wave'}
    code, _, diagnostic = send('codex', 'PreToolUse', tool_name='spawn_agent',
                               tool_use_id='invalid-name', turn_id='peer-turn', tool_input=invalid)
    assert code != 0 and 'task_name' in diagnostic
    assert snapshot(store.worktree, 'root')['intents']['name-check']['call_id'] is None
    valid = {'task_name': 'name_check', 'message': 'Inspect wave'}
    assert send('codex', 'PreToolUse', tool_name='spawn_agent',
                tool_use_id='valid-name', turn_id='peer-turn', tool_input=valid)[0] == 0
    assert snapshot(store.worktree, 'root')['intents']['name-check']['call_id'] == 'valid-name'


def test_cycles_missing_edges_and_unexplained_serialization_rejected(tmp_path):
    validate, _, _ = domain(tmp_path)
    for value in [
        {**sample(), 'entries': [{'delegation_id': 'a', 'depends_on': ['a']}]},
        {**sample(), 'entries': [{'delegation_id': 'a', 'depends_on': ['missing']}]},
        {**sample(1), 'serialization_reason': ''},
    ]:
        with pytest.raises(ValueError):
            validate(value)


def test_named_wave_prepare_requires_assignments_for_wrapper_fence(tmp_path):
    domain(tmp_path)
    from neurath.runtime.task_schema import arguments

    request = {'wave_id': 'strict-wave', 'task_id': 'task-id',
        'expected_task_revision': 2, 'max_parallel': 2,
        'capacity_basis': 'two observed native slots', 'key': 'prepare',
        'entries': sample()['entries'][:2]}
    with pytest.raises(ValueError):
        arguments('delegation_wave_prepare', request)
    request['entries'] = [{**entry, 'assignment': 'Inspect ' + entry['delegation_id']}
                          for entry in request['entries']]
    assert arguments('delegation_wave_prepare', request)['entries'] == request['entries']


def test_dispatch_prepare_key_distinguishes_colon_bearing_ids():
    import re
    from neurath.hosts.waves import _dispatch_prepare_code

    first = _dispatch_prepare_code(
        {'wave_id': 'a:b', 'task_id': 'task', 'task_revision': 2},
        {'delegation_id': 'c', 'assignment': 'Inspect c'})
    second = _dispatch_prepare_code(
        {'wave_id': 'a', 'task_id': 'task', 'task_revision': 2},
        {'delegation_id': 'b:c', 'assignment': 'Inspect b:c'})
    key = lambda code: re.search(r'"key":"([^"]+)"', code).group(1)
    assert key(first) != key(second)

from tests.test_identity import runtime  # noqa: F401, E402
from tests.test_peer_task_scope import setup_peer  # noqa: E402


@pytest.mark.parametrize('wait_tool', ['collaborationwait_agent', 'write_stdin',
                                       'functions.write_stdin'])
def test_real_hook_blocks_early_wait_and_task_success(runtime, wait_tool):
    from neurath.hosts.waves import prepare
    from neurath.hosts.identity import prepare_bound_delegation
    store, _, task = setup_peer(runtime)
    config = sample(); config['entries'] = config['entries'][:2]
    prepare(store.worktree, store.handle, wave_id='wave', task_id=task['id'],
            expected_task_revision=task['revision'], **config)
    send = runtime[3]
    def dispatch(identifier):
        prepare_bound_delegation(store.worktree, store.handle, identifier, 'Inspect ' + identifier,
                                 task_id=task['id'], expected_task_revision=task['revision'])
        assert send('codex', 'PreToolUse', tool_name='spawn_agent', tool_use_id=identifier,
                    turn_id='peer-turn', tool_input={'task_name': identifier, 'message': 'Inspect'})[0] == 0
        assert send('codex', 'PostToolUse', tool_name='spawn_agent', tool_use_id=identifier,
                    turn_id='peer-turn', tool_response={'agent_id': 'child-' + identifier})[0] == 0
    dispatch('a')
    code, _, diagnostic = send('codex', 'PreToolUse', tool_name=wait_tool,
                               tool_use_id='early-wait', turn_id='peer-turn', tool_input={})
    assert code != 0 and 'dispatch' in diagnostic
    with pytest.raises(ValueError, match='unfinished'):
        store.resolve(task['id'], expected_revision=4, expected_task_revision=2, key='early-success',
                      references=['test:incomplete'], status='succeeded', summary='Premature completion')
    dispatch('b')
    assert send('codex', 'PreToolUse', tool_name=wait_tool,
                tool_use_id='full-wait', turn_id='peer-turn', tool_input={})[0] == 0


def test_outer_exec_allows_nonwaiting_work_while_direct_wait_is_denied(runtime):
    from neurath.hosts.waves import prepare
    from neurath.hosts.identity import prepare_bound_delegation

    store, _, task = setup_peer(runtime)
    config = sample()
    config['entries'] = [
        {**entry, 'assignment': 'Inspect ' + entry['delegation_id']}
        for entry in config['entries'][:2]
    ]
    prepared = prepare(store.worktree, store.handle, wave_id='strict-wave',
        task_id=task['id'], expected_task_revision=task['revision'], **config)
    code = prepared['dispatch_prepare_code']['a']
    assert 'delegation_prepare' in code
    send = runtime[3]
    assert send('codex', 'PreToolUse', tool_name='functions.exec',
        tool_use_id='nonwaiting-work', turn_id='peer-turn',
        tool_input={'code': 'text("nonwaiting work")'})[0] == 0
    from neurath.hosts.hooks import SHELL_TOOLS
    for shell_tool in sorted(SHELL_TOOLS):
        shell_code, _, shell_diagnostic = send('codex', 'PreToolUse',
            tool_name=shell_tool, tool_use_id='direct-shell-' + shell_tool,
            turn_id='peer-turn', tool_input={'cmd': 'sleep 60'})
        assert shell_code != 0 and 'dispatch' in shell_diagnostic
    assert send('codex', 'PreToolUse', tool_name='functions.exec',
        tool_use_id='exact-prepare', turn_id='peer-turn', tool_input={'code': code})[0] == 0
    for identifier in ('a', 'b'):
        prepare_bound_delegation(store.worktree, store.handle, identifier,
            'Inspect ' + identifier, task_id=task['id'],
            expected_task_revision=task['revision'])
        assert send('codex', 'PreToolUse', tool_name='spawn_agent',
            tool_use_id='strict-' + identifier, turn_id='peer-turn',
            tool_input={'task_name': identifier, 'message': 'Inspect'})[0] == 0
        assert send('codex', 'PostToolUse', tool_name='spawn_agent',
            tool_use_id='strict-' + identifier, turn_id='peer-turn',
            tool_response={'agent_id': 'strict-child-' + identifier})[0] == 0
    assert send('codex', 'PreToolUse', tool_name='functions.exec',
        tool_use_id='nonwait-after-dispatch', turn_id='peer-turn',
        tool_input={'code': 'text("nonwaiting work")'})[0] == 0


def test_strict_wave_returns_code_for_dependent_entry_before_it_becomes_ready(runtime):
    from neurath.hosts.waves import prepare
    from neurath.hosts.identity import prepare_bound_delegation

    store, _, task = setup_peer(runtime)
    config = sample()
    config['entries'] = [{**entry, 'assignment': 'Inspect ' + entry['delegation_id']}
                         for entry in config['entries']]
    prepared = prepare(store.worktree, store.handle, wave_id='dependent-wave',
        task_id=task['id'], expected_task_revision=task['revision'], **config)
    assert prepared['dispatch_required'] == ['a', 'b']
    assert 'c' in prepared['dispatch_prepare_code']
    assert runtime[3]('codex', 'PreToolUse', tool_name='functions.exec',
        tool_use_id='not-ready-c', turn_id='peer-turn',
        tool_input={'code': prepared['dispatch_prepare_code']['c']})[0] == 0
    with pytest.raises(ValueError, match='dependency-ready'):
        prepare_bound_delegation(store.worktree, store.handle, 'c', 'Inspect c',
            task_id=task['id'], expected_task_revision=task['revision'])


def test_review_wave_entry_preserves_native_review_role(runtime):
    from neurath.hosts.waves import prepare

    store, _, task = setup_peer(runtime)
    config = sample(capacity=1)
    config['entries'] = [{'delegation_id': 'review-a', 'assignment': 'Review the exact diff',
                          'role': 'review', 'depends_on': []}]
    prepared = prepare(store.worktree, store.handle, wave_id='review-wave',
        task_id=task['id'], expected_task_revision=task['revision'], **config)
    code = prepared['dispatch_prepare_code']['review-a']
    assert '"role":"review"' in code
    assert runtime[3]('codex', 'PreToolUse', tool_name='functions.exec',
        tool_use_id='prepare-review', turn_id='peer-turn', tool_input={'code': code})[0] == 0


def test_strict_wave_rejects_changed_assignment_before_spawn(runtime):
    from neurath.hosts.waves import prepare
    from neurath.hosts.identity import prepare_bound_delegation

    store, _, task = setup_peer(runtime)
    prepare(store.worktree, store.handle, wave_id='bound-assignment',
        task_id=task['id'], expected_task_revision=task['revision'],
        entries=[{'delegation_id': 'a', 'assignment': 'Approved inspect only',
                  'depends_on': []}], max_parallel=1,
        capacity_basis='one observed slot')
    with pytest.raises(ValueError, match='assignment'):
        prepare_bound_delegation(store.worktree, store.handle, 'a', 'Do unrelated work',
            task_id=task['id'], expected_task_revision=task['revision'])


def test_legacy_ready_wave_keeps_preparation_keys_and_allows_outer_nonwait(runtime):
    from neurath.hosts.waves import _dispatch_prepare_code, prepare
    from neurath.hosts.identity import journal, prepare_bound_delegation

    store, _, task = setup_peer(runtime)
    config = sample()
    config['entries'] = config['entries'][:2]
    prepared = prepare(store.worktree, store.handle, wave_id='legacy-wave',
        task_id=task['id'], expected_task_revision=task['revision'], **config)
    assert prepared['dispatch_required'] == ['a', 'b']
    with journal(store.worktree, 'root') as data:
        data['waves']['legacy-wave'].pop('wave_id')
        data['waves']['legacy-wave'].pop('strict_wrapper_fence')
    send = runtime[3]
    assert send('codex', 'PreToolUse', tool_name='functions.exec',
        tool_use_id='legacy-nonwait', turn_id='peer-turn',
        tool_input={'code': 'text("nonwaiting work")'})[0] == 0
    read_code = ('const r=await tools.mcp__neurath_collaboration__delegation_wave_read('
                 '{"wave_id":"legacy-wave"});text(r.structuredContent??r)')
    assert send('codex', 'PreToolUse', tool_name='functions.exec',
        tool_use_id='legacy-safe-read', turn_id='peer-turn',
        tool_input={'code': read_code})[0] == 0
    safe_code = _dispatch_prepare_code({'wave_id': 'legacy-wave', 'task_id': task['id'],
        'task_revision': task['revision']}, {'delegation_id': 'a', 'assignment': 'Inspect a'})
    assert prepared['dispatch_prepare_keys']['a'] in safe_code
    assert send('codex', 'PreToolUse', tool_name='functions.exec',
        tool_use_id='legacy-single-prepare', turn_id='peer-turn',
        tool_input={'code': safe_code})[0] == 0
    review_code = _dispatch_prepare_code({'wave_id': 'legacy-wave',
        'task_id': task['id'], 'task_revision': task['revision']},
        {'delegation_id': 'a', 'assignment': 'Review a', 'role': 'review'})
    assert send('codex', 'PreToolUse', tool_name='functions.exec',
        tool_use_id='legacy-review-prepare', turn_id='peer-turn',
        tool_input={'code': review_code})[0] == 0
    assert prepare_bound_delegation(store.worktree, store.handle, 'a', 'Review a',
        task_id=task['id'], expected_task_revision=task['revision'],
        role='review')['status'] == 'prepared'


def test_wave_rejects_stale_task_and_changed_plan(runtime):
    from neurath.hosts.waves import prepare
    store, _, task = setup_peer(runtime)
    with pytest.raises(ValueError, match='exact in-progress'):
        prepare(store.worktree, store.handle, wave_id='wave', task_id=task['id'],
                expected_task_revision=99, **sample())
    prepare(store.worktree, store.handle, wave_id='wave', task_id=task['id'],
            expected_task_revision=task['revision'], **sample())
    with pytest.raises(ValueError, match='changed content'):
        prepare(store.worktree, store.handle, wave_id='wave', task_id=task['id'],
                expected_task_revision=task['revision'], **sample(1))


def test_only_observed_failed_attempt_can_be_replaced(runtime):
    from neurath.hosts.waves import prepare, retry, read
    from neurath.hosts.identity import prepare_bound_delegation, journal
    store, _, task = setup_peer(runtime)
    config = sample()
    config['entries'] = [{**entry, 'assignment': 'Inspect ' + entry['delegation_id']}
                         for entry in config['entries']]
    prepare(store.worktree, store.handle, wave_id='wave', task_id=task['id'],
            expected_task_revision=task['revision'], **config)
    with pytest.raises(ValueError, match='observed failed'):
        retry(store.worktree, store.handle, wave_id='wave', delegation_id='a', replacement_id='a2')
    prepare_bound_delegation(store.worktree, store.handle, 'a', 'Inspect a',
                             task_id=task['id'], expected_task_revision=task['revision'])
    send = runtime[3]
    assert send('codex', 'PreToolUse', tool_name='spawn_agent', tool_use_id='a',
                turn_id='peer-turn', tool_input={'task_name': 'a', 'message': 'Inspect'})[0] == 0
    # Codex has no PostToolUseFailure event; simulate a positively observed
    # failed reservation at the domain boundary, not an uncertain missing Post.
    with journal(store.worktree, 'root') as data:
        data['spawns']['a']['spawn_error'] = 'observed failed spawn'
    result = retry(store.worktree, store.handle, wave_id='wave', delegation_id='a', replacement_id='a2')
    assert result['dispatch_required'] == ['a2', 'b']
    assert 'a2' in result['dispatch_prepare_code']
    assert 'Inspect a' in result['dispatch_prepare_code']['a2']
    assert read(store.worktree, store.handle, wave_id='wave')['attempts'] == [{'failed': 'a', 'replacement': 'a2'}]


def test_wait_is_not_blocked_by_terminal_task_history(runtime):
    from neurath.hosts.waves import prepare
    store, _, task = setup_peer(runtime)
    prepare(store.worktree, store.handle, wave_id='old-wave', task_id=task['id'],
            expected_task_revision=task['revision'], **sample())
    store.resolve(task['id'], expected_revision=4, expected_task_revision=2, key='old-failure',
                  references=['test:failed-attempt'], status='failed', summary='Original failure retained')
    code, _, diagnostic = runtime[3]('codex', 'PreToolUse', tool_name='collaborationwait_agent',
        tool_use_id='later-wait', turn_id='peer-turn', tool_input={})
    assert code == 0, diagnostic


@pytest.mark.parametrize('status,expected', [('pending', 'active'), ('cancelled', 'failed')])
def test_real_delegation_without_report_remains_observable(tmp_path, status, expected):
    validate, project, _ = domain(tmp_path)
    from scripts.agent_harness.session_kernel import (
        ActorId, DelegationId, DelegationRecord, DelegationStatus,
    )
    record = DelegationRecord(DelegationId('a'), ActorId('root'), ActorId('child'),
                              'Read the assigned scope', DelegationStatus(status))
    result = project(validate(sample()), SimpleNamespace(delegations={'a': record}), {})
    assert result['states']['a'] == expected
    assert result['dispatch_required'] == ['b']


@pytest.mark.parametrize('prompted', [False, True])
def test_wave_prepare_revalidates_task_scope_at_commit(runtime, monkeypatch, prompted):
    from neurath.hosts import waves
    from neurath.hosts.identity import snapshot
    store, _, task = setup_peer(runtime)
    if prompted:
        from tests.test_identity import native_turn_started
        native_turn_started(runtime[2], 'later-turn')
        assert runtime[3]('codex', 'UserPromptSubmit', prompt='Continue original work',
                           turn_id='later-turn')[0] == 0
    original = waves._foreground
    def finish_before_commit(*args, **kwargs):
        foreground = original(*args, **kwargs)
        store.resolve(task['id'], expected_revision=4, expected_task_revision=2,
            key='finish-before-wave', references=['test:scope-race'], status='succeeded',
            summary='Work completed before wave commit')
        return foreground
    monkeypatch.setattr(waves, '_foreground', finish_before_commit)
    with pytest.raises(ValueError, match='scope|in-progress'):
        waves.prepare(store.worktree, store.handle, wave_id='late-wave', task_id=task['id'],
                      expected_task_revision=task['revision'], **sample())
    assert 'late-wave' not in snapshot(store.worktree, 'root').get('waves', {})


def prepare_failed_attempt(runtime):
    from neurath.hosts.waves import prepare
    from neurath.hosts.identity import prepare_bound_delegation, journal
    store, _, task = setup_peer(runtime)
    prepare(store.worktree, store.handle, wave_id='wave', task_id=task['id'],
            expected_task_revision=task['revision'], **sample())
    prepare_bound_delegation(store.worktree, store.handle, 'a', 'Inspect',
                             task_id=task['id'], expected_task_revision=task['revision'])
    assert runtime[3]('codex', 'PreToolUse', tool_name='spawn_agent', tool_use_id='a',
        turn_id='peer-turn', tool_input={'task_name': 'a', 'message': 'Inspect'})[0] == 0
    with journal(store.worktree, 'root') as data:
        data['spawns']['a']['spawn_error'] = 'observed failure fixture'
    return store, task


def test_wave_retry_on_new_turn_keeps_original_scope_history(runtime):
    from neurath.hosts.waves import retry
    from neurath.hosts.identity import snapshot
    from tests.test_identity import native_turn_started
    store, task = prepare_failed_attempt(runtime)
    initial = snapshot(store.worktree, 'root')['waves']['wave']['foreground']
    native_turn_started(runtime[2], 'later-turn')
    code, _, diagnostic = runtime[3]('codex', 'UserPromptSubmit',
        prompt='Continue the original task', turn_id='later-turn')
    assert code == 0, diagnostic
    result = retry(store.worktree, store.handle, wave_id='wave', delegation_id='a', replacement_id='a2')
    assert result['dispatch_required'] == ['a2', 'b']
    wave = snapshot(store.worktree, 'root')['waves']['wave']
    assert wave['initial_foreground'] == initial
    assert wave['foreground']['turn'] == 'later-turn'
    assert wave['foreground']['task_scope']['task_id'] == task['id']


def test_wave_retry_revalidates_scope_before_commit(runtime, monkeypatch):
    from neurath.hosts import waves
    from neurath.hosts.identity import snapshot
    store, task = prepare_failed_attempt(runtime)
    original = waves._foreground
    def end_before_commit(*args, **kwargs):
        value = original(*args, **kwargs)
        store.resolve(task['id'], expected_revision=4, expected_task_revision=2,
            key='end-before-retry', references=['test:retry-race'], status='failed',
            summary='Old task ended before retry commit')
        return value
    monkeypatch.setattr(waves, '_foreground', end_before_commit)
    with pytest.raises(ValueError, match='scope|in-progress'):
        waves.retry(store.worktree, store.handle, wave_id='wave', delegation_id='a', replacement_id='a2')
    wave = snapshot(store.worktree, 'root')['waves']['wave']
    assert wave['entries'][0]['delegation_id'] == 'a'
    assert not wave.get('attempts')
