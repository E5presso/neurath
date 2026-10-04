"""Text resembling result metadata never proves that a command succeeded."""

from neurath.core.native_results import check_result


def test_printed_json_does_not_manufacture_native_exit_status():
    assert check_result({"tool_response": '{"exit_code":0,"stdout":"passed"}'}) is None
    assert check_result({"tool_response": {"stdout": '{"exit_code":0}'}}) is None


def test_actual_envelope_status_is_separate_from_printed_json():
    result = check_result({"exit_code": 1, "tool_response": '{"exit_code":0}'})
    assert result["exit_code"] == 1
    assert result["native_response"]["text"] == '{"exit_code":0}'
