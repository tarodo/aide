from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.cast_rule import CastRule
from backend.models.data_type import DataType
from backend.models.system_flavor import SystemFlavor


class TypeRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flavor: str
    code: str


class CastMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: TypeRef
    target: TypeRef
    safety: Literal["implicit", "safe", "unsafe"]
    params: dict[str, Any] = {}


class CastRulesSeedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mappings: list[CastMapping]


def load_seed_file(path: Path | str) -> CastRulesSeedFile:
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"Seed file {path} did not parse to a mapping")
    return CastRulesSeedFile.model_validate(raw)


@dataclass
class CastRulesSeedReport:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0


async def _resolve_data_type(session: AsyncSession, ref: TypeRef) -> DataType:
    stmt = (
        select(DataType)
        .join(SystemFlavor, SystemFlavor.id == DataType.system_flavor_id)
        .where(
            SystemFlavor.code == ref.flavor,
            DataType.code == ref.code,
            DataType.deleted_at.is_(None),
        )
    )
    result = await session.execute(stmt)
    dt = result.scalars().first()
    if dt is None:
        raise LookupError(
            f"DataType not found for flavor='{ref.flavor}' code='{ref.code}'. "
            "Seed data types first."
        )
    return dt


async def seed_from_file(
    session: AsyncSession, path: Path | str
) -> CastRulesSeedReport:
    seed = load_seed_file(path)
    report = CastRulesSeedReport()

    for mapping in seed.mappings:
        src = await _resolve_data_type(session, mapping.source)
        tgt = await _resolve_data_type(session, mapping.target)

        stmt = select(CastRule).where(
            CastRule.source_data_type_id == src.id,
            CastRule.target_data_type_id == tgt.id,
        )
        existing = (await session.execute(stmt)).scalars().first()

        if existing is None:
            session.add(
                CastRule(
                    source_data_type_id=src.id,
                    target_data_type_id=tgt.id,
                    param_mapping=dict(mapping.params),
                    safety=mapping.safety,
                )
            )
            report.inserted += 1
            continue

        changed = existing.safety != mapping.safety or existing.param_mapping != dict(
            mapping.params
        )
        if changed:
            existing.safety = mapping.safety
            existing.param_mapping = dict(mapping.params)
            report.updated += 1
        else:
            report.unchanged += 1

    await session.flush()
    return report
