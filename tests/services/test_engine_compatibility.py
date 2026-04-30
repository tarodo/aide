import pytest

from backend.core.exceptions import AppException
from backend.services.engine_compatibility import assert_compatible, is_allowed


def test_cdc_on_rdbms_to_kafka_allowed():
    assert is_allowed("cdc", "rdbms", "kafka") is True


def test_cdc_on_kafka_to_hive_rejected():
    assert is_allowed("cdc", "kafka", "hive") is False


def test_compute_on_kafka_to_hive_allowed():
    assert is_allowed("compute", "kafka", "hive") is True


def test_compute_on_hive_to_hive_allowed():
    assert is_allowed("compute", "hive", "hive") is True


def test_assert_raises_with_details():
    with pytest.raises(AppException) as exc:
        assert_compatible(role="cdc", source_kind="kafka", target_kind="hive")
    assert exc.value.error_code == "ENGINE_INCOMPATIBLE_LINK"
    assert exc.value.details == {
        "engine_role": "cdc",
        "source_kind": "kafka",
        "target_kind": "hive",
    }
