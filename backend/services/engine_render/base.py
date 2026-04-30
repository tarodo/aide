from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from aide_schemas.engine import RenderWarning
from backend.models.engine import Engine
from backend.services.envelope_resolver import EnvelopeResolver


@dataclass
class Projection:
    source_name: str
    target_name: str
    target_type: str


@dataclass
class RenderableLink:
    source: str
    target: str
    projections: list[Projection] = field(default_factory=list)


class EngineRenderer(Protocol):
    engine: Engine
    last_warnings: list[RenderWarning]

    def render(self, link, resolver: EnvelopeResolver) -> str: ...
