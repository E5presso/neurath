"""Array diagnostics identify which bound was violated."""
import pytest

from neurath.runtime.task_schema import TaskError, _validate


@pytest.mark.parametrize("value,message", [([], "too few items"), ([1, 2, 3], "too many items")])
def test_array_bound_errors_distinguish_minimum_and_maximum(value, message):
    with pytest.raises(TaskError, match=message):
        _validate(value, {"type": "array", "minItems": 1, "maxItems": 2,
                          "items": {"type": "integer"}}, "values")


@pytest.mark.parametrize("value", [[1], [1, 2]])
def test_array_bounds_accept_endpoints(value):
    _validate(value, {"type": "array", "minItems": 1, "maxItems": 2,
                      "items": {"type": "integer"}}, "values")
