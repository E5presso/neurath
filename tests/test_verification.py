"""Configured commands retain execution identity and before/after evidence."""

import subprocess
import sys

import pytest

from neurath.runtime.verification import VerificationError, verify


def test_generic_command_records_failure_digest_and_mutation(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    result = verify(
        tmp_path,
        {"argv": [sys.executable, "-c", "print('evidence')"], "cwd": ".", "success_codes": [0]},
    )
    assert result["status"] == "passed"
    assert len(result["output_sha256"]) == 64
    assert result["before_fingerprint"] == result["after_fingerprint"]
    result = verify(
        tmp_path,
        {
            "argv": [
                sys.executable,
                "-c",
                "from pathlib import Path; Path('changed').write_text('x'); raise SystemExit(7)",
            ],
            "cwd": ".",
            "success_codes": [0],
        },
    )
    assert result["status"] == "failed" and result["exit_code"] == 7
    assert result["worktree_changed"]


def test_no_shell_or_escaping_cwd(tmp_path):
    with pytest.raises(VerificationError):
        verify(tmp_path, {"argv": "echo not-an-argv", "cwd": "."})
    with pytest.raises(VerificationError):
        verify(tmp_path, {"argv": ["echo", "x"], "cwd": ".."})


def test_failed_project_check_returns_bounded_sanitized_diagnostics(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    result = verify(tmp_path, {"argv": [sys.executable, "-c",
        "print('x'*10000); print('assertion failed; password=private-value'); raise SystemExit(1)"]})
    assert result['status'] == 'failed'
    assert 'assertion failed' in result['diagnostic_tail']
    assert 'private-value' not in result['diagnostic_tail']
    assert len(result['diagnostic_tail']) <= 8192
