from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.system_flavor import SystemFlavor
from backend.models.system_kind import SystemKind


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


def load_seed_file(path: Path | str) -> SeedFile:
    path = Path(path)
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"Seed file {path} did not parse to a mapping")
    return SeedFile.model_validate(raw)


UpsertStatus = Literal["inserted", "updated", "unchanged", "restored"]


@dataclass
class SeedReport:
    kind: UpsertStatus | None = None
    flavor: UpsertStatus | None = None
    types_inserted: int = 0
    types_updated: int = 0
    types_unchanged: int = 0
    types_restored: int = 0


async def upsert_system_kind(
    session: AsyncSession, spec: SeedKind
) -> tuple[SystemKind, UpsertStatus]:
    stmt = select(SystemKind).where(SystemKind.code == spec.code)
    existing = (await session.execute(stmt)).scalars().first()

    if existing is None:
        obj = SystemKind(code=spec.code, name=spec.name)
        session.add(obj)
        await session.flush()
        return obj, "inserted"

    if existing.deleted_at is not None:
        existing.deleted_at = None
        existing.name = spec.name
        await session.flush()
        return existing, "restored"

    if existing.name != spec.name:
        existing.name = spec.name
        await session.flush()
        return existing, "updated"

    return existing, "unchanged"


async def upsert_system_flavor(
    session: AsyncSession, spec: SeedFlavor, kind_id: uuid.UUID
) -> tuple[SystemFlavor, UpsertStatus]:
    stmt = select(SystemFlavor).where(SystemFlavor.code == spec.code)
    existing = (await session.execute(stmt)).scalars().first()

    if existing is None:
        obj = SystemFlavor(
            code=spec.code,
            name=spec.name,
            vendor=spec.vendor,
            versions=list(spec.versions),
            kind_id=kind_id,
        )
        session.add(obj)
        await session.flush()
        return obj, "inserted"

    fields_changed = (
        existing.name != spec.name
        or existing.vendor != spec.vendor
        or list(existing.versions or []) != list(spec.versions)
        or existing.kind_id != kind_id
    )

    if existing.deleted_at is not None:
        existing.deleted_at = None
        existing.name = spec.name
        existing.vendor = spec.vendor
        existing.versions = list(spec.versions)
        existing.kind_id = kind_id
        await session.flush()
        return existing, "restored"

    if fields_changed:
        existing.name = spec.name
        existing.vendor = spec.vendor
        existing.versions = list(spec.versions)
        existing.kind_id = kind_id
        await session.flush()
        return existing, "updated"

    return existing, "unchanged"
