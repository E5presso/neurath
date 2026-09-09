"""Exercise real pytest parameter selection and preserve rejected process evidence."""
import json
import sys

import pytest


@pytest.fixture
def parameter_project(tmp_path):
    from neurath.runtime.engine import activate
    activate()
    (tmp_path / ".neurath").mkdir()
    (tmp_path / ".neurath/project.json").write_text(json.dumps({"verification": {
        "pytest": {"argv": [sys.executable, "-m", "pytest"]}}}))
    (tmp_path / "test_sample.py").write_text(
        "import pytest\n"
        "@pytest.mark.parametrize('value', [False, True])\n"
        "def test_all(value):\n    assert isinstance(value, bool)\n"
        "@pytest.mark.parametrize('value', [False, True])\n"
        "def test_partial(value):\n"
        "    if value:\n        pytest.skip('partial-case-sentinel')\n"
    )
    return tmp_path


def test_parameter_selector_grammar_preserves_exact_identity(parameter_project):
    from scripts.agent_harness.verification_runner import (
        VerificationKind, VerificationRequest, VerificationRequestInvalid,
    )
    for node in ("test_sample.py::test_all[False]", "test_sample.py::test_all",
                 "test_sample.py::TestAPI::test_case[한국어]"):
        assert VerificationRequest(VerificationKind.PYTEST, (node,)).nodes == (node,)
    for node in ("test_sample.py::test_all[]", "test_sample.py::test_all[x]::extra",
                 "test_sample.py::test_all[has space]", "test_sample.py::helper[False]"):
        with pytest.raises(VerificationRequestInvalid):
            VerificationRequest(VerificationKind.PYTEST, (node,))


def test_parameter_base_and_exact_leaf_execute_successfully(parameter_project):
    from scripts.agent_harness.harness_incident import _execute_regression_command
    from scripts.agent_harness.verification_runner import VerificationKind, VerificationRequest
    for node in ("test_sample.py::test_all", "test_sample.py::test_all[False]"):
        request = VerificationRequest(VerificationKind.PYTEST, (node,))
        result, digest = _execute_regression_command(parameter_project, request.commands[0])
        assert result.returncode == 0
        assert len(digest) == 64
        assert b"test_all[False] PASSED" in result.stdout
        if node.endswith("[False]"):
            assert b"test_all[True]" not in result.stdout


def test_parameter_partial_success_retains_actual_process_failure_evidence(parameter_project):
    from scripts.agent_harness.harness_incident import (
        HarnessRegressionExecutionError, _execute_regression_command,
    )
    with pytest.raises(HarnessRegressionExecutionError) as caught:
        _execute_regression_command(parameter_project,
            ".neurath/run verify pytest --node test_sample.py::test_partial")
    error = caught.value
    assert error.exit_code == 0
    assert len(error.output_sha256) == 64
    assert "SKIPPED" in error.diagnostic_tail
    assert "did not fully pass" in str(error)


def test_missing_expected_stdout_retains_process_receipt(parameter_project):
    from scripts.agent_harness.harness_incident import (
        HarnessRegressionExecutionError, _execute_regression_command,
    )
    path = parameter_project / ".neurath/project.json"
    config = json.loads(path.read_text())
    config["verification"]["pytest"]["stdout_contains"] = "ABSENT_SUCCESS_SENTINEL"
    path.write_text(json.dumps(config))
    with pytest.raises(HarnessRegressionExecutionError) as caught:
        _execute_regression_command(parameter_project,
            ".neurath/run verify pytest --node test_sample.py::test_all")
    assert caught.value.exit_code == 0
    assert len(caught.value.output_sha256) == 64
    assert "PASSED" in caught.value.diagnostic_tail
