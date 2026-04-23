import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import System, SystemFlavor, SystemKind
from backend.models.dataset import DatasetRdbms
from backend.models.dataset_link import DatasetLink
from backend.models.dataset_schema import DatasetSchema
from backend.repositories.dataset_link import DatasetLinkRepository


async def _make_system(session: AsyncSession, *, code_suffix: str) -> System:
    kind = SystemKind(code=f"KIND_DLR_{code_suffix}", name=f"Kind DLR {code_suffix}")
    flavor = SystemFlavor(
        code=f"FL_DLR_{code_suffix}", name=f"Flavor DLR {code_suffix}", kind=kind
    )
    system = System(
        code=f"SYS_DLR_{code_suffix}", name=f"System DLR {code_suffix}", flavor=flavor
    )
    session.add_all([kind, flavor, system])
    await session.flush()
    return system


@pytest.mark.asyncio
async def test_has_active_links_for_dataset(transactional_session: AsyncSession):
    seeded_system = await _make_system(transactional_session, code_suffix="HAS")
    src = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="s",
        kind="rdbms",
        schema_name="s",
        table_name="s",
    )
    tgt = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="t",
        kind="rdbms",
        schema_name="s",
        table_name="t",
    )
    transactional_session.add_all([src, tgt])
    await transactional_session.flush()

    src_schema = DatasetSchema(dataset_id=src.id, version_num=1, schema={})
    tgt_schema = DatasetSchema(dataset_id=tgt.id, version_num=1, schema={})
    transactional_session.add_all([src_schema, tgt_schema])
    await transactional_session.flush()

    repo = DatasetLinkRepository(transactional_session)
    assert await repo.has_active_links_for_dataset(src.id) is False

    link = DatasetLink(
        source_dataset_id=src.id,
        target_dataset_id=tgt.id,
        source_schema_id=src_schema.id,
        target_schema_id=tgt_schema.id,
    )
    transactional_session.add(link)
    await transactional_session.flush()

    assert await repo.has_active_links_for_dataset(src.id) is True
    assert await repo.has_active_links_for_dataset(tgt.id) is True


@pytest.mark.asyncio
async def test_get_active_between(transactional_session: AsyncSession):
    seeded_system = await _make_system(transactional_session, code_suffix="BTW")
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

    a_schema = DatasetSchema(dataset_id=a.id, version_num=1, schema={})
    b_schema = DatasetSchema(dataset_id=b.id, version_num=1, schema={})
    transactional_session.add_all([a_schema, b_schema])
    await transactional_session.flush()

    repo = DatasetLinkRepository(transactional_session)
    assert await repo.get_active_between(a.id, b.id) is None

    link = DatasetLink(
        source_dataset_id=a.id,
        target_dataset_id=b.id,
        source_schema_id=a_schema.id,
        target_schema_id=b_schema.id,
    )
    transactional_session.add(link)
    await transactional_session.flush()

    found = await repo.get_active_between(a.id, b.id)
    assert found is not None and found.id == link.id


@pytest.mark.asyncio
async def test_list_by_source_and_target(transactional_session: AsyncSession):
    seeded_system = await _make_system(transactional_session, code_suffix="LST")
    a = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="a1",
        kind="rdbms",
        schema_name="s",
        table_name="a1",
    )
    b = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="b1",
        kind="rdbms",
        schema_name="s",
        table_name="b1",
    )
    c = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="c1",
        kind="rdbms",
        schema_name="s",
        table_name="c1",
    )
    transactional_session.add_all([a, b, c])
    await transactional_session.flush()

    a_schema = DatasetSchema(dataset_id=a.id, version_num=1, schema={})
    b_schema = DatasetSchema(dataset_id=b.id, version_num=1, schema={})
    c_schema = DatasetSchema(dataset_id=c.id, version_num=1, schema={})
    transactional_session.add_all([a_schema, b_schema, c_schema])
    await transactional_session.flush()

    transactional_session.add(
        DatasetLink(
            source_dataset_id=a.id,
            target_dataset_id=b.id,
            source_schema_id=a_schema.id,
            target_schema_id=b_schema.id,
        )
    )
    transactional_session.add(
        DatasetLink(
            source_dataset_id=a.id,
            target_dataset_id=c.id,
            source_schema_id=a_schema.id,
            target_schema_id=c_schema.id,
        )
    )
    transactional_session.add(
        DatasetLink(
            source_dataset_id=b.id,
            target_dataset_id=c.id,
            source_schema_id=b_schema.id,
            target_schema_id=c_schema.id,
        )
    )
    await transactional_session.flush()

    repo = DatasetLinkRepository(transactional_session)
    downstream_of_a = await repo.list_by_source(a.id)
    upstream_of_c = await repo.list_by_target(c.id)
    assert len(downstream_of_a) == 2
    assert len(upstream_of_c) == 2


async def _seed_linked_pair(
    session: AsyncSession, name: str, src_version: int, tgt_version: int
):
    kind = SystemKind(code=f"DL_K_{name}", name=f"DL K {name}")
    flavor = SystemFlavor(code=f"DL_F_{name}", name=f"DL F {name}", kind=kind)
    system = System(code=f"DL_S_{name}", name=f"DL S {name}", flavor=flavor)
    src = DatasetRdbms(
        system=system,
        object_name=f"{name}_src",
        kind="rdbms",
        schema_name="s",
        table_name="src",
    )
    tgt = DatasetRdbms(
        system=system,
        object_name=f"{name}_tgt",
        kind="rdbms",
        schema_name="s",
        table_name="tgt",
    )
    session.add_all([kind, flavor, system, src, tgt])
    await session.flush()

    src_schemas = [
        DatasetSchema(dataset=src, version_num=v, schema={})
        for v in range(1, src_version + 1)
    ]
    tgt_schemas = [
        DatasetSchema(dataset=tgt, version_num=v, schema={})
        for v in range(1, tgt_version + 1)
    ]
    session.add_all(src_schemas + tgt_schemas)
    await session.flush()

    link = DatasetLink(
        source_dataset_id=src.id,
        target_dataset_id=tgt.id,
        source_schema_id=src_schemas[0].id,  # pinned v1 (old)
        target_schema_id=tgt_schemas[0].id,
    )
    session.add(link)
    await session.flush()
    return link, src, tgt, src_schemas, tgt_schemas


@pytest.mark.asyncio
async def test_list_with_compat_summary_reports_drift(
    transactional_session: AsyncSession,
):
    link, src, tgt, src_schemas, tgt_schemas = await _seed_linked_pair(
        transactional_session, "drift", src_version=3, tgt_version=1
    )
    repo = DatasetLinkRepository(transactional_session)
    rows = await repo.list_with_compat_summary()
    target_rows = [r for r in rows if r["dataset_link_id"] == link.id]
    assert len(target_rows) == 1
    row = target_rows[0]
    assert row["source_pinned_version"] == 1
    assert row["source_latest_version"] == 3
    assert row["target_pinned_version"] == 1
    assert row["target_latest_version"] == 1
    assert row["source_has_drift"] is True
    assert row["target_has_drift"] is False
