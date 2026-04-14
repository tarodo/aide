from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator


class SeedParamSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["int", "str", "bool"]
    required: bool = False
    default: Any = None


class SeedKind(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str


class SeedFlavor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    vendor: str | None = None
    versions: list[str] = []


class SeedType(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    params_schema: dict[str, SeedParamSpec] = {}
    render_template: str | None = None


class SeedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: SeedKind
    flavor: SeedFlavor
    types: list[SeedType]

    @field_validator("types")
    @classmethod
    def _unique_codes(cls, v: list[SeedType]) -> list[SeedType]:
        codes = [t.code for t in v]
        if len(codes) != len(set(codes)):
            dups = {c for c in codes if codes.count(c) > 1}
            raise ValueError(f"Duplicate type codes in seed file: {sorted(dups)}")
        return v
