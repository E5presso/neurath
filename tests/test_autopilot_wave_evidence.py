"""Legacy autopilot phases must read the native dispatch record, not accept prose."""
from types import SimpleNamespace
import pytest
from neurath.runtime.engine import activate


def test_wave_phase_does_not_accept_labels_without_native_readback(tmp_path):
    activate(tmp_path)
    from scripts.skill_harness.phase_runner import PhaseRunner, PhaseContract
    runner = PhaseRunner(None)
    state = SimpleNamespace(skill='autopilot', adaptive_control_required=False)
    phase = PhaseContract(3, 'execute_waves', 3,
                          ('wave_plan', 'process_ticket_terminal_states', 'native_wave_receipt'))
    class Store:
        def read_native_wave(self, wave_id):
            raise ValueError('No authenticated native wave')
    failures = runner._semantic_failures(state, phase, 'completed',
        ('wave_plan: parallel', 'process_ticket_terminal_states: merged',
         'native_wave_receipt: wave_id=fiction'), {}, Store())
    assert 'native_wave_receipt' in failures


def test_wave_phase_requires_every_collected_issue_in_native_dispatch(tmp_path):
    activate(tmp_path)
    from scripts.skill_harness.phase_runner import PhaseRunner, PhaseContract
    runner = PhaseRunner(None)
    prior = {
        1: SimpleNamespace(evidence=('normalized_items: {"issues":[90,91]}',)),
        2: SimpleNamespace(evidence=('dependency_dag: {"issues":[90,91],"edges":[]}',)),
    }
    state = SimpleNamespace(skill='autopilot', adaptive_control_required=False,
                            phase=lambda phase_id: prior[phase_id])
    phase = PhaseContract(3, 'execute_waves', 3,
                          ('wave_plan', 'process_ticket_terminal_states', 'native_wave_receipt'))
    class Store:
        def read_native_wave(self, wave_id):
            return {'all_succeeded': True, 'states': {'issue-90': 'consumed'}}
    failures = runner._semantic_failures(state, phase, 'completed',
        ('wave_plan: two independent issues', 'process_ticket_terminal_states: merged',
         'native_wave_receipt: wave_id=wave-1'), {}, Store())
    assert 'autopilot.wave_scope' in failures


def test_successful_retry_preserves_original_issue_coverage(tmp_path):
    activate(tmp_path)
    from scripts.skill_harness.phase_runner import PhaseRunner, PhaseContract
    runner = PhaseRunner(None)
    prior = {2: SimpleNamespace(evidence=(
        'dependency_dag: {"issues":[90],"edges":[]}',))}
    state = SimpleNamespace(skill='autopilot', adaptive_control_required=False,
                            phase=lambda phase_id: prior[phase_id])
    phase = PhaseContract(3, 'execute_waves', 3,
                          ('wave_plan', 'process_ticket_terminal_states', 'native_wave_receipt'))
    class Store:
        def read_native_wave(self, wave_id):
            return {'all_succeeded': True, 'states': {'issue-90-retry': 'succeeded'},
                    'attempts': [{'failed': 'issue-90', 'replacement': 'issue-90-retry'}]}
    failures = runner._semantic_failures(state, phase, 'completed',
        ('wave_plan: retry', 'process_ticket_terminal_states: merged',
         'native_wave_receipt: wave_id=wave-1'), {}, Store())
    assert 'autopilot.wave_scope' not in failures


def test_all_satisfied_scope_has_explicit_native_wave_no_op(tmp_path):
    activate(tmp_path)
    from scripts.skill_harness.phase_runner import PhaseRunner, PhaseContract
    runner = PhaseRunner(None)
    prior = {2: SimpleNamespace(evidence=(
        'dependency_dag: {"issues":[],"edges":[]}',))}
    state = SimpleNamespace(skill='autopilot', adaptive_control_required=False,
                            phase=lambda phase_id: prior[phase_id])
    phase = PhaseContract(3, 'execute_waves', 3,
                          ('wave_plan', 'process_ticket_terminal_states', 'native_wave_receipt'))
    class Store:
        def read_native_wave(self, wave_id):
            raise AssertionError('no wave exists for an all-satisfied scope')
    failures = runner._semantic_failures(state, phase, 'completed',
        ('wave_plan: no work', 'process_ticket_terminal_states: already closed',
         'native_wave_receipt: no_op=all_satisfied'), {}, Store())
    assert 'native_wave_receipt' not in failures
    assert 'autopilot.wave_scope' not in failures


def test_wave_dependencies_match_frozen_dag(tmp_path):
    activate(tmp_path)
    from scripts.skill_harness.phase_runner import PhaseRunner, PhaseContract
    runner = PhaseRunner(None)
    prior = {2: SimpleNamespace(evidence=(
        'dependency_dag: {"issues":[90,91],"edges":[[90,91]]}',))}
    state = SimpleNamespace(skill='autopilot', adaptive_control_required=False,
                            phase=lambda phase_id: prior[phase_id])
    phase = PhaseContract(3, 'execute_waves', 3,
                          ('wave_plan', 'process_ticket_terminal_states', 'native_wave_receipt'))
    class Store:
        def read_native_wave(self, wave_id):
            return {'all_succeeded': True,
                    'states': {'issue-90': 'succeeded', 'issue-91': 'succeeded'},
                    'entries': [{'delegation_id': 'issue-90', 'depends_on': []},
                                {'delegation_id': 'issue-91', 'depends_on': []}]}
    failures = runner._semantic_failures(state, phase, 'completed',
        ('wave_plan: linked issues', 'process_ticket_terminal_states: merged',
         'native_wave_receipt: wave_id=wave-1'), {}, Store())
    assert 'autopilot.wave_dependencies' in failures


@pytest.mark.parametrize('change,expected', [
    ('none', None), ('not-consumed', 'native_wave_receipt'),
    ('missing-issue', 'autopilot.wave_scope'), ('missing-edge', 'autopilot.wave_dependencies'),
    ('ambiguous-backend', 'native_wave_receipt'),
])
def test_provider_wave_uses_its_own_reader_and_retains_exact_scope(tmp_path, change, expected):
    activate(tmp_path)
    from scripts.skill_harness.phase_runner import PhaseRunner, PhaseContract
    prior = SimpleNamespace(evidence=('dependency_dag: {"issues":[90,91],"edges":[[90,91]]}',))
    state = SimpleNamespace(skill='autopilot', adaptive_control_required=False, phase=lambda _: prior)
    phase = PhaseContract(3, 'execute_waves', 3,
                          ('wave_plan', 'process_ticket_terminal_states', 'native_wave_receipt'))
    class Store:
        def read_native_wave(self, wave_id):
            raise AssertionError('provider receipt must never fall back to native children')
        def read_provider_wave(self, wave_id):
            assert wave_id == 'provider-wave'
            return {'all_succeeded': change != 'not-consumed',
                'states': {'issue-90': 'succeeded'} if change == 'missing-issue' else
                          {'issue-90': 'succeeded', 'issue-91': 'succeeded'},
                'entries': [{'delegation_id': 'issue-90', 'depends_on': []},
                            {'delegation_id': 'issue-91', 'depends_on': [] if change == 'missing-edge' else ['issue-90']}]}
    receipt = 'native_wave_receipt: provider_wave_id=provider-wave'
    if change == 'ambiguous-backend':
        receipt += ' wave_id=native-wave'
    failures = PhaseRunner(None)._semantic_failures(state, phase, 'completed',
        ('wave_plan: runtime-owned DAG', 'process_ticket_terminal_states: merged', receipt), {}, Store())
    if expected is None:
        assert failures == []
    else:
        assert expected in failures
