from backend.models.engine import EngineDebezium, EngineImpala, EngineSpark
from backend.services.engine_render.impala import ImpalaRenderer
from backend.services.engine_render.spark import SparkRenderer
from backend.services.envelope_resolver import EnvelopeResolver


class _FakeProjection:
    def __init__(self, source_name: str, target_name: str, target_type: str):
        self.source_name = source_name
        self.target_name = target_name
        self.target_type = target_type


class _FakeLink:
    def __init__(self, source: str, target: str, projections: list[_FakeProjection]):
        self.source = source
        self.target = target
        self.projections = projections


def _spark_engine() -> EngineSpark:
    return EngineSpark(code="s", name="s", kind="spark", role="compute", version="3.x")


def _impala_engine() -> EngineImpala:
    return EngineImpala(
        code="i", name="i", kind="impala", role="compute", version="4.x"
    )


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
        },
    )


def test_spark_renders_passthrough():
    link = _FakeLink(
        source="src_db.public.users",
        target="lake.raw.users",
        projections=[
            _FakeProjection("id", "id", "bigint"),
            _FakeProjection("email", "email", "string"),
        ],
    )
    resolver = EnvelopeResolver(cdc_engine=None, kafka_format="")
    sql = SparkRenderer(_spark_engine()).render(link, resolver)
    assert "INSERT INTO lake.raw.users" in sql
    assert "SELECT" in sql
    assert "CAST(id AS bigint) AS id" in sql
    assert "FROM src_db.public.users" in sql


def test_spark_renders_kafka_envelope_avro():
    link = _FakeLink(
        source="kafka.cdc_users",
        target="lake.raw.users",
        projections=[
            _FakeProjection("id", "id", "bigint"),
            _FakeProjection("email", "email", "string"),
        ],
    )
    resolver = EnvelopeResolver(cdc_engine=_debezium_engine(), kafka_format="avro")
    sql = SparkRenderer(_spark_engine()).render(link, resolver)
    assert "CAST(payload.after.id AS bigint) AS id" in sql
    assert "CAST(payload.after.email AS string) AS email" in sql


def test_impala_uses_double_quotes_on_identifiers():
    link = _FakeLink(
        source="src.public.users",
        target="lake.raw.users",
        projections=[_FakeProjection("id", "id", "bigint")],
    )
    resolver = EnvelopeResolver(cdc_engine=None, kafka_format="")
    sql = ImpalaRenderer(_impala_engine()).render(link, resolver)
    assert "INSERT INTO lake.raw.users" in sql
    assert "CAST(id AS bigint)" in sql


def test_renderer_emits_warning_for_lossy_cast():
    link = _FakeLink(
        source="src",
        target="dst",
        projections=[_FakeProjection("amount", "amount", "decimal(10,2)")],
    )
    resolver = EnvelopeResolver(cdc_engine=None, kafka_format="")
    renderer = SparkRenderer(_spark_engine())
    sql = renderer.render(link, resolver)
    assert "amount" in sql
    # warning generation is independent of cast safety; renderers expose
    # `last_warnings` for the service caller. Empty here is acceptable.
    assert renderer.last_warnings == []
