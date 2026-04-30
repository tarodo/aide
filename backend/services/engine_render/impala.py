from __future__ import annotations

from aide_schemas.engine import RenderWarning
from backend.models.engine import EngineImpala
from backend.services.engine_render.base import EngineRenderer
from backend.services.envelope_resolver import EnvelopeResolver


class ImpalaRenderer:
    """Impala SQL dialect: matches Spark form for MVP (engine differences will be
    expanded in a future phase that targets quoting, complex-type access, etc.)."""

    engine: EngineImpala
    last_warnings: list[RenderWarning]

    def __init__(self, engine: EngineImpala):
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


_: EngineRenderer = ImpalaRenderer.__new__(ImpalaRenderer)  # type: ignore[arg-type, assignment]
