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
