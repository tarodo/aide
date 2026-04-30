from __future__ import annotations

from aide_schemas.engine import RenderWarning
from backend.models.engine import EngineSpark
from backend.services.engine_render.base import EngineRenderer
from backend.services.envelope_resolver import EnvelopeResolver


class SparkRenderer:
    """Spark SQL dialect: bare identifiers, INSERT INTO ... SELECT ... FROM ..."""

    engine: EngineSpark
    last_warnings: list[RenderWarning]

    def __init__(self, engine: EngineSpark):
        self.engine = engine
        self.last_warnings = []

    def render(self, link, resolver: EnvelopeResolver) -> str:
        self.last_warnings = []
        projections: list[str] = []
        for p in link.projections:
            src_expr = resolver.path_for(p.source_name)
            projections.append(
                f"CAST({src_expr} AS {p.target_type}) AS {p.target_name}"
            )
        select_clause = ",\n    ".join(projections) if projections else "*"
        return (
            f"INSERT INTO {link.target}\n"
            f"SELECT\n    {select_clause}\n"
            f"FROM {link.source};"
        )


# Mypy: protocol conformance check
_: EngineRenderer = SparkRenderer.__new__(SparkRenderer)  # type: ignore[arg-type, assignment]
