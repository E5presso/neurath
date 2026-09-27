"""Partial development runs must never impersonate the complete source gate."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "neurath_check_runner", Path(__file__).parents[1] / "tools/check.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

pytestmark = pytest.mark.fast


def test_full_check_stops_on_failure_without_success_marker(monkeypatch, capsys):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=7 if 'ruff' in command else 0)

    monkeypatch.setattr(check.subprocess, 'run', run)
    assert check.main([]) == 7
    assert len(calls) == 2
    assert not any('pytest' in command for command in calls)
    assert 'CHECK_OK' not in capsys.readouterr().out


def test_full_check_includes_both_test_corpora_before_success(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(check.subprocess, 'run',
                        lambda command, **kwargs: calls.append(command) or SimpleNamespace(returncode=0))
    assert check.main(['--workers', '2']) == 0
    assert len(calls) == 4
    assert calls[2][1:3] == ['-m', 'pytest']
    assert calls[2][calls[2].index('-n') + 1] == '2'
    assert calls[3][1:] == ['tools/run_core_regressions.py', '--workers', '2']
    assert 'NEURATH_CHECK_OK' in capsys.readouterr().out


@pytest.mark.parametrize('suite', ['fast', 'package', 'runtime'])
def test_partial_selection_never_emits_full_gate_marker(monkeypatch, capsys, suite):
    calls = []
    monkeypatch.setattr(check.subprocess, 'run',
                        lambda command, **kwargs: calls.append(command) or SimpleNamespace(returncode=0))
    assert check.main(['--suite', suite]) == 0
    assert len(calls) == 1
    if suite == 'fast':
        assert calls[0][-2:] == ['-m', 'fast']
        assert calls[0][calls[0].index('-n') + 1] == '0'
    output = capsys.readouterr().out
    assert 'NEURATH_CHECK_OK' not in output
    assert f'NEURATH_PARTIAL_CHECK_OK suite={suite}' in output


def test_invalid_worker_count_starts_no_commands(monkeypatch):
    monkeypatch.setattr(check.subprocess, 'run', lambda *a, **k: pytest.fail('unexpected process'))
    with pytest.raises(SystemExit) as error:
        check.main(['--workers', '-1'])
    assert error.value.code == 2
