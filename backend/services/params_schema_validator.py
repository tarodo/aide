from __future__ import annotations

from typing import Any

from backend.core import errors
from backend.core.exceptions import AppException

_TYPE_MAP: dict[str, type] = {
    "int": int,
    "str": str,
    "bool": bool,
    "float": float,
}


def validate_type_params(
    params_schema: dict[str, Any],
    type_params: dict[str, Any] | None,
) -> None:
    """Validate TypeInstance.type_params against DataType.params_schema.

    Raises AppException(TYPE_INSTANCE_PARAMS_INVALID) on any violation.
    """
    provided = type_params or {}

    unknown = set(provided) - set(params_schema)
    if unknown:
        raise AppException(errors.TYPE_INSTANCE_PARAMS_INVALID)

    for key, rule in params_schema.items():
        if not isinstance(rule, dict):
            # Unrecognised rule format — skip validation for this param.
            continue
        required = bool(rule.get("required", False))
        if key not in provided:
            if required:
                raise AppException(errors.TYPE_INSTANCE_PARAMS_INVALID)
            continue

        value = provided[key]
        if value is None:
            if required:
                raise AppException(errors.TYPE_INSTANCE_PARAMS_INVALID)
            continue

        expected = _TYPE_MAP.get(rule.get("type", ""))
        if expected is None:
            continue

        # Reject bool where int is expected (bool is subclass of int in Python).
        if expected is int and isinstance(value, bool):
            raise AppException(errors.TYPE_INSTANCE_PARAMS_INVALID)
        if not isinstance(value, expected):
            raise AppException(errors.TYPE_INSTANCE_PARAMS_INVALID)

        if expected in (int, float):
            low = rule.get("min")
            high = rule.get("max")
            if low is not None and value < low:
                raise AppException(errors.TYPE_INSTANCE_PARAMS_INVALID)
            if high is not None and value > high:
                raise AppException(errors.TYPE_INSTANCE_PARAMS_INVALID)
