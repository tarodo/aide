from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import System, SystemFlavor, SystemKind
from backend.models.dataset import DatasetRdbms
from backend.models.dataset_link import DatasetLink


async def _make_system(session: AsyncSession, *, code_suffix: str) -> System:
    kind = SystemKind(code=f"KIND_DSL_{code_suffix}", name=f"Kind DSL {code_suffix}")
    flavor = SystemFlavor(
        code=f"FL_DSL_{code_suffix}", name=f"Flavor DSL {code_suffix}", kind=kind
    )
    system = System(
        code=f"SYS_DSL_{code_suffix}", name=f"System DSL {code_suffix}", flavor=flavor
    )
    session.add_all([kind, flavor, system])
    await session.flush()
    return system


@pytest.mark.asyncio
async def test_dataset_link_create(transactional_session: AsyncSession):
    seeded_system = await _make_system(transactional_session, code_suffix="CREATE")
    src = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="src",
        kind="rdbms",
        schema_name="s",
        table_name="src",
    )
    tgt = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="tgt",
        kind="rdbms",
        schema_name="s",
        table_name="tgt",
    )
    transactional_session.add_all([src, tgt])
    await transactional_session.flush()

    link = DatasetLink(source_dataset_id=src.id, target_dataset_id=tgt.id)
    transactional_session.add(link)
    await transactional_session.flush()
    await transactional_session.refresh(link)

    assert link.id is not None
    assert link.row_version == 1
    assert link.deleted_at is None


@pytest.mark.asyncio
async def test_dataset_link_self_reference_rejected(
    transactional_session: AsyncSession,
):
    seeded_system = await _make_system(transactional_session, code_suffix="SELF")
    ds = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="self",
        kind="rdbms",
        schema_name="s",
        table_name="self",
    )
    transactional_session.add(ds)
    await transactional_session.flush()

    link = DatasetLink(source_dataset_id=ds.id, target_dataset_id=ds.id)
    transactional_session.add(link)
    with pytest.raises(IntegrityError):
        await transactional_session.flush()


@pytest.mark.asyncio
async def test_dataset_link_pair_unique_active(
    transactional_session: AsyncSession,
):
    seeded_system = await _make_system(transactional_session, code_suffix="PAIR")
    a = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="a",
        kind="rdbms",
        schema_name="s",
        table_name="a",
    )
    b = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="b",
        kind="rdbms",
        schema_name="s",
        table_name="b",
    )
    transactional_session.add_all([a, b])
    await transactional_session.flush()
    transactional_session.add(
        DatasetLink(source_dataset_id=a.id, target_dataset_id=b.id)
    )
    await transactional_session.flush()
    transactional_session.add(
        DatasetLink(source_dataset_id=a.id, target_dataset_id=b.id)
    )
    with pytest.raises(IntegrityError):
        await transactional_session.flush()


@pytest.mark.asyncio
async def test_dataset_link_pair_unique_ignores_soft_deleted(
    transactional_session: AsyncSession,
):
    """Partial unique index allows re-linking after soft-delete."""
    seeded_system = await _make_system(transactional_session, code_suffix="SOFT")
    a = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="a_soft",
        kind="rdbms",
        schema_name="s",
        table_name="a_soft",
    )
    b = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="b_soft",
        kind="rdbms",
        schema_name="s",
        table_name="b_soft",
    )
    transactional_session.add_all([a, b])
    await transactional_session.flush()

    first = DatasetLink(source_dataset_id=a.id, target_dataset_id=b.id)
    transactional_session.add(first)
    await transactional_session.flush()

    first.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    transactional_session.add(first)
    await transactional_session.flush()

    second = DatasetLink(source_dataset_id=a.id, target_dataset_id=b.id)
    transactional_session.add(second)
    await transactional_session.flush()
    assert second.id != first.id
