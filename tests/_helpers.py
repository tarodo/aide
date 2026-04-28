"""Shared test helpers.

Currently hosts lake-sync seed helpers used by both the API-layer tests
(``tests/api/test_lake_sync.py``) and the service-layer tests
(``tests/services/test_lake_sync_service.py``). Promoted from the API
test file once the second consumer arrived.

CLAUDE.md guidance: promote to this module when a helper has 3+ copies
or two consumers in different layers. The lake-sync helpers hit the
second condition.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.dataset import Dataset, DatasetRdbms
from backend.models.dataset_schema import DatasetSchema
from backend.models.field import Field
from backend.models.field_binding import FieldBinding
from backend.models.system import System
from backend.models.system_flavor import SystemFlavor
from backend.models.type_instance import TypeInstance
from backend.scripts._seed_cast_rules_core import (
    seed_from_file as seed_casts_from_file,
)
from backend.scripts._seed_core import seed_from_file as seed_dt_from_file


async def _seed_pg_and_iceberg(session: AsyncSession) -> None:
    await seed_dt_from_file(session, Path("backend/scripts/data/postgres14.yaml"))
    await seed_dt_from_file(session, Path("backend/scripts/data/iceberg_v2.yaml"))
    await seed_casts_from_file(
        session, Path("backend/scripts/data/casts_pg14_to_iceberg_v2.yaml")
    )


async def _create_pg_system(session: AsyncSession) -> System:
    flavor = (
        (
            await session.execute(
                select(SystemFlavor).where(SystemFlavor.code == "postgres14")
            )
        )
        .scalars()
        .first()
    )
    sys = System(
        code=f"pg-src-{uuid.uuid4().hex[:6]}",
        name="PG Source",
        flavor_id=flavor.id,
    )
    session.add(sys)
    await session.flush()
    return sys


async def _create_lake_system(session: AsyncSession) -> System:
    flavor = (
        (
            await session.execute(
                select(SystemFlavor).where(SystemFlavor.code == "iceberg_v2")
            )
        )
        .scalars()
        .first()
    )
    sys = System(
        code=f"lake-{uuid.uuid4().hex[:6]}",
        name="Lake",
        flavor_id=flavor.id,
    )
    session.add(sys)
    await session.flush()
    return sys


async def _make_source_dataset(
    session: AsyncSession, system: System
) -> tuple[Dataset, DatasetSchema, list[Field]]:
    """Create a minimal pg14 source: id bigint, amount numeric(10,2), tags array<int>."""
    ds = DatasetRdbms(
        kind="rdbms",
        system_id=system.id,
        object_name="public.users",
        schema_name="public",
        table_name="users",
        layer="raw",
    )
    session.add(ds)
    await session.flush()

    schema = DatasetSchema(dataset_id=ds.id, version_num=1)
    session.add(schema)
    await session.flush()

    pg_flavor = (
        (
            await session.execute(
                select(SystemFlavor).where(SystemFlavor.code == "postgres14")
            )
        )
        .scalars()
        .first()
    )
    from backend.models.data_type import DataType

    pg_types = {
        dt.code: dt
        for dt in (
            await session.execute(
                select(DataType).where(DataType.system_flavor_id == pg_flavor.id)
            )
        ).scalars()
    }

    fields: list[Field] = []
    for idx, (name, dt_code, params, slot_children) in enumerate(
        [
            ("id", "bigint", {}, []),
            ("amount", "numeric", {"precision": 10, "scale": 2}, []),
            ("tags", "array", {}, [("item", "integer", {})]),
        ]
    ):
        fld = Field(dataset_id=ds.id, name=name, origin="mapped")
        session.add(fld)
        await session.flush()
        fields.append(fld)

        root_ti = TypeInstance(
            data_type_id=pg_types[dt_code].id,
            type_params=params or None,
            slot=None,
        )
        session.add(root_ti)
        await session.flush()
        for slot, child_code, child_params in slot_children:
            child_ti = TypeInstance(
                data_type_id=pg_types[child_code].id,
                type_params=child_params or None,
                slot=slot,
                parent_id=root_ti.id,
            )
            session.add(child_ti)
            await session.flush()

        binding = FieldBinding(
            field_id=fld.id,
            dataset_schema_id=schema.id,
            position=idx,
            is_nullable=(name != "id"),
            type_instance_id=root_ti.id,
        )
        session.add(binding)
        await session.flush()

    return ds, schema, fields
