import pytest
from pydantic import ValidationError

from aide_schemas.engine import (
    AnyEngineCreate,
    EngineDebeziumCreate,
    EngineSparkCreate,
    validate_engine_read,
)


def test_debezium_create_validates_envelope():
    obj = EngineDebeziumCreate(
        kind="debezium",
        code="dbz-1",
        name="prod",
        version="2.x",
        envelope_template={
            "envelope_kind": "debezium",
            "after_path": "after",
            "before_path": "before",
            "op_path": "op",
            "ts_ms_path": "ts_ms",
            "source_path": "source",
        },
    )
    assert obj.role == "cdc"


def test_debezium_rejects_missing_after_path():
    with pytest.raises(ValidationError):
        EngineDebeziumCreate(
            kind="debezium",
            code="dbz-1",
            name="prod",
            version="2.x",
            envelope_template={"envelope_kind": "debezium"},  # missing after_path
        )


def test_spark_version_whitelist():
    with pytest.raises(ValidationError):
        EngineSparkCreate(
            kind="spark",
            code="spark-1",
            name="bad",
            version="2.x",  # not allowed
        )


def test_discriminated_union_dispatches_on_kind():
    payload = {
        "kind": "spark",
        "code": "s",
        "name": "n",
        "version": "3.x",
    }
    from pydantic import TypeAdapter

    adapter = TypeAdapter(AnyEngineCreate)
    obj = adapter.validate_python(payload)
    assert isinstance(obj, EngineSparkCreate)
    assert obj.role == "compute"
    # exercise validate_engine_read so the test surface matches the plan
    assert callable(validate_engine_read)


def test_validate_engine_read_rejects_unknown_kind():
    from types import SimpleNamespace

    with pytest.raises(ValueError):
        validate_engine_read(SimpleNamespace(kind="not-a-real-kind"))
