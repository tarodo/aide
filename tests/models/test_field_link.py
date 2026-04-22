import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import System, SystemFlavor, SystemKind
from backend.models.dataset import DatasetRdbms
from backend.models.dataset_link import DatasetLink
from backend.models.field import Field
from backend.models.field_link import FieldLink


async def _make_system(session: AsyncSession, *, code_suffix: str) -> System:
    kind = SystemKind(code=f"KIND_FL_{code_suffix}", name=f"Kind FL {code_suffix}")
    flavor = SystemFlavor(
        code=f"FL_FL_{code_suffix}", name=f"Flavor FL {code_suffix}", kind=kind
    )
    system = System(
        code=f"SYS_FL_{code_suffix}", name=f"System FL {code_suffix}", flavor=flavor
    )
    session.add_all([kind, flavor, system])
    await session.flush()
    return system


async def _scaffold(session: AsyncSession, sys: System):
    src = DatasetRdbms(
        system_id=sys.id,
        object_name="srcd",
        kind="rdbms",
        schema_name="s",
        table_name="srcd",
    )
    tgt = DatasetRdbms(
        system_id=sys.id,
        object_name="tgtd",
        kind="rdbms",
        schema_name="s",
        table_name="tgtd",
    )
    session.add_all([src, tgt])
    await session.flush()
    link = DatasetLink(source_dataset_id=src.id, target_dataset_id=tgt.id)
    session.add(link)
    await session.flush()
    sf = Field(dataset_id=src.id, name="col_s")
    tf = Field(dataset_id=tgt.id, name="col_t")
    session.add_all([sf, tf])
    await session.flush()
    return link, sf, tf


@pytest.mark.asyncio
async def test_field_link_create(transactional_session: AsyncSession):
    seeded = await _make_system(transactional_session, code_suffix="CREATE")
    link, sf, tf = await _scaffold(transactional_session, seeded)
    fl = FieldLink(
        dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf.id
    )
    transactional_session.add(fl)
    await transactional_session.flush()
    await transactional_session.refresh(fl)
    assert fl.id is not None
    assert fl.row_version == 1


@pytest.mark.asyncio
async def test_field_link_target_uniqueness(transactional_session: AsyncSession):
    seeded = await _make_system(transactional_session, code_suffix="TARGET")
    link, sf, tf = await _scaffold(transactional_session, seeded)
    sf2 = Field(dataset_id=sf.dataset_id, name="col_s2")
    transactional_session.add(sf2)
    await transactional_session.flush()
    transactional_session.add(
        FieldLink(dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf.id)
    )
    await transactional_session.flush()
    transactional_session.add(
        FieldLink(
            dataset_link_id=link.id, source_field_id=sf2.id, target_field_id=tf.id
        )
    )
    with pytest.raises(IntegrityError):
        await transactional_session.flush()


@pytest.mark.asyncio
async def test_field_link_source_fanout_allowed(transactional_session: AsyncSession):
    seeded = await _make_system(transactional_session, code_suffix="FANOUT")
    link, sf, tf = await _scaffold(transactional_session, seeded)
    tf2 = Field(dataset_id=tf.dataset_id, name="col_t2")
    transactional_session.add(tf2)
    await transactional_session.flush()
    transactional_session.add(
        FieldLink(dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf.id)
    )
    transactional_session.add(
        FieldLink(
            dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf2.id
        )
    )
    await transactional_session.flush()


@pytest.mark.asyncio
async def test_field_link_triple_unique(transactional_session: AsyncSession):
    seeded = await _make_system(transactional_session, code_suffix="TRIPLE")
    link, sf, tf = await _scaffold(transactional_session, seeded)
    transactional_session.add(
        FieldLink(dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf.id)
    )
    await transactional_session.flush()
    transactional_session.add(
        FieldLink(dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf.id)
    )
    with pytest.raises(IntegrityError):
        await transactional_session.flush()


@pytest.mark.asyncio
async def test_field_link_cascade_on_dataset_link_delete(
    transactional_session: AsyncSession,
):
    seeded = await _make_system(transactional_session, code_suffix="CASCADE")
    link, sf, tf = await _scaffold(transactional_session, seeded)
    fl = FieldLink(
        dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf.id
    )
    transactional_session.add(fl)
    await transactional_session.flush()

    await transactional_session.delete(link)
    await transactional_session.flush()
    remaining = (await transactional_session.execute(select(FieldLink))).scalars().all()
    assert len(remaining) == 0
