import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import System, SystemFlavor, SystemKind
from backend.models.dataset import DatasetRdbms
from backend.models.dataset_link import DatasetLink
from backend.models.field import Field
from backend.models.field_link import FieldLink
from backend.repositories.field_link import FieldLinkRepository


async def _make_system(session: AsyncSession, *, code_suffix: str) -> System:
    kind = SystemKind(code=f"KIND_FLR_{code_suffix}", name=f"Kind FLR {code_suffix}")
    flavor = SystemFlavor(
        code=f"FL_FLR_{code_suffix}", name=f"Flavor FLR {code_suffix}", kind=kind
    )
    system = System(
        code=f"SYS_FLR_{code_suffix}", name=f"System FLR {code_suffix}", flavor=flavor
    )
    session.add_all([kind, flavor, system])
    await session.flush()
    return system


async def _scaffold(session: AsyncSession, sys: System):
    src = DatasetRdbms(
        system_id=sys.id,
        object_name="s_fl",
        kind="rdbms",
        schema_name="s",
        table_name="s_fl",
    )
    tgt = DatasetRdbms(
        system_id=sys.id,
        object_name="t_fl",
        kind="rdbms",
        schema_name="s",
        table_name="t_fl",
    )
    session.add_all([src, tgt])
    await session.flush()
    link = DatasetLink(source_dataset_id=src.id, target_dataset_id=tgt.id)
    session.add(link)
    await session.flush()
    return src, tgt, link


@pytest.mark.asyncio
async def test_list_by_dataset_link(transactional_session: AsyncSession):
    seeded = await _make_system(transactional_session, code_suffix="LIST")
    src, tgt, link = await _scaffold(transactional_session, seeded)
    sf = Field(dataset_id=src.id, name="c1")
    tf = Field(dataset_id=tgt.id, name="c1")
    transactional_session.add_all([sf, tf])
    await transactional_session.flush()
    fl = FieldLink(
        dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf.id
    )
    transactional_session.add(fl)
    await transactional_session.flush()

    repo = FieldLinkRepository(transactional_session)
    items = await repo.list_by_dataset_link(link.id)
    assert len(items) == 1 and items[0].id == fl.id


@pytest.mark.asyncio
async def test_get_by_target_in_link(transactional_session: AsyncSession):
    seeded = await _make_system(transactional_session, code_suffix="TGT")
    src, tgt, link = await _scaffold(transactional_session, seeded)
    sf = Field(dataset_id=src.id, name="c2")
    tf = Field(dataset_id=tgt.id, name="c2")
    transactional_session.add_all([sf, tf])
    await transactional_session.flush()

    repo = FieldLinkRepository(transactional_session)
    assert await repo.get_by_target_in_link(link.id, tf.id) is None

    fl = FieldLink(
        dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf.id
    )
    transactional_session.add(fl)
    await transactional_session.flush()
    assert (await repo.get_by_target_in_link(link.id, tf.id)).id == fl.id


@pytest.mark.asyncio
async def test_list_by_target_field(transactional_session: AsyncSession):
    seeded = await _make_system(transactional_session, code_suffix="BYTGT")
    src, tgt, link = await _scaffold(transactional_session, seeded)
    sf = Field(dataset_id=src.id, name="c3")
    tf = Field(dataset_id=tgt.id, name="c3")
    transactional_session.add_all([sf, tf])
    await transactional_session.flush()

    repo = FieldLinkRepository(transactional_session)
    assert list(await repo.list_by_target_field(tf.id)) == []
    fl = FieldLink(
        dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf.id
    )
    transactional_session.add(fl)
    await transactional_session.flush()
    items = await repo.list_by_target_field(tf.id)
    assert len(items) == 1 and items[0].id == fl.id


@pytest.mark.asyncio
async def test_unmapped_non_tech_fields(transactional_session: AsyncSession):
    seeded = await _make_system(transactional_session, code_suffix="UNMAP")
    src, tgt, link = await _scaffold(transactional_session, seeded)
    sf = Field(dataset_id=src.id, name="c4")
    mapped_tf = Field(dataset_id=tgt.id, name="c4")
    unmapped_tf = Field(dataset_id=tgt.id, name="c5")
    tech_tf = Field(dataset_id=tgt.id, name="etl_ts", origin="tech")
    transactional_session.add_all([sf, mapped_tf, unmapped_tf, tech_tf])
    await transactional_session.flush()
    fl = FieldLink(
        dataset_link_id=link.id,
        source_field_id=sf.id,
        target_field_id=mapped_tf.id,
    )
    transactional_session.add(fl)
    await transactional_session.flush()

    repo = FieldLinkRepository(transactional_session)
    orphans = await repo.unmapped_non_tech_fields(tgt.id)
    orphan_ids = {f.id for f in orphans}
    assert unmapped_tf.id in orphan_ids
    assert mapped_tf.id not in orphan_ids
    assert tech_tf.id not in orphan_ids
