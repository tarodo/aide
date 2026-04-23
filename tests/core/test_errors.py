import pytest

from backend.core import errors


@pytest.mark.parametrize(
    "code,expected_status",
    [
        (errors.SCHEMA_DATASET_MISMATCH, 422),
        (errors.FIELD_ORIGIN_CONFLICT, 409),
        (errors.FIELD_BINDING_MISSING, 422),
        (errors.DATASET_SCHEMA_IN_USE, 409),
    ],
)
def test_new_lineage_error_codes_registered(code: str, expected_status: int):
    assert code in errors.ERROR_MAP
    status_code, detail = errors.ERROR_MAP[code]
    assert status_code == expected_status
    assert detail  # non-empty message
