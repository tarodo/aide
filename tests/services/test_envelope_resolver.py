from backend.models.engine import EngineDebezium, EngineOgg
from backend.services.envelope_resolver import EnvelopeResolver


def _debezium_engine() -> EngineDebezium:
    return EngineDebezium(
        code="d",
        name="d",
        kind="debezium",
        role="cdc",
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


def test_passthrough_when_engine_is_none():
    r = EnvelopeResolver(cdc_engine=None, kafka_format="json")
    assert r.path_for("foo") == "foo"


def test_debezium_json_after_path():
    r = EnvelopeResolver(cdc_engine=_debezium_engine(), kafka_format="json")
    assert r.path_for("amount") == "get_json_object(payload, '$.after.amount')"


def test_debezium_avro_after_path():
    r = EnvelopeResolver(cdc_engine=_debezium_engine(), kafka_format="avro")
    assert r.path_for("amount") == "payload.after.amount"


def test_debezium_before_side():
    r = EnvelopeResolver(cdc_engine=_debezium_engine(), kafka_format="avro")
    assert r.path_for("amount", side="before") == "payload.before.amount"


def test_op_and_ts_paths_avro():
    r = EnvelopeResolver(cdc_engine=_debezium_engine(), kafka_format="avro")
    assert r.op_path() == "payload.op"
    assert r.ts_path() == "payload.ts_ms"


def test_ogg_uses_op_ts_key():
    ogg = EngineOgg(
        code="o",
        name="o",
        kind="ogg",
        role="cdc",
        version="21c",
        envelope_template={
            "envelope_kind": "ogg",
            "after_path": "after",
            "op_path": "op_type",
            "ts_path": "op_ts",
        },
    )
    r = EnvelopeResolver(cdc_engine=ogg, kafka_format="json")
    assert r.op_path() == "get_json_object(payload, '$.op_type')"
    assert r.ts_path() == "get_json_object(payload, '$.op_ts')"
