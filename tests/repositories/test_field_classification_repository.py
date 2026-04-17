from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    DatasetRdbms,
    Field,
    FieldClassification,
    System,
    SystemFlavor,
    SystemKind,
)
from backend.repositories.field_classification import (
    FieldClassificationRepository,
)


async def _make_field(session: AsyncSession, *, code_suffix: str) -> Field:
    kind = SystemKind(code=f"KIND_FCR_{code_suffix}", name=f"Kind FCR {code_suffix}")
    flavor = SystemFlavor(
        code=f"FL_FCR_{code_suffix}", name=f"Flavor FCR {code_suffix}", kind=kind
    )
    system = System(
        code=f"SYS_FCR_{code_suffix}", name=f"System FCR {code_suffix}", flavor=flavor
    )
    dataset = DatasetRdbms(
        system=system,
        object_name=f"customers_fcr_{code_suffix}",
        schema_name="public",
        table_name="customers",
    )
    field = Field(dataset=dataset, name=f"email_{code_suffix}")
    session.add_all([kind, flavor, system, dataset, field])
    await session.flush()
    return field


@pytest.mark.asyncio
async def test_get_current_returns_latest_row(transactional_session: AsyncSession):
    field = await _make_field(transactional_session, code_suffix="A")
    repo = FieldClassificationRepository(transactional_session)

    base = datetime.now(timezone.utc).replace(tzinfo=None)
    first = FieldClassification(field_id=field.id, pii_tags=["email"], created_at=base)
    transactional_session.add(first)
    await transactional_session.flush()
    second = FieldClassification(
        field_id=field.id,
        pii_tags=["email", "phone"],
        created_at=base + timedelta(milliseconds=100),
    )
    transactional_session.add(second)
    await transactional_session.flush()

    current = await repo.get_current(field.id)
    assert current is not None
    assert current.id == second.id
    assert current.pii_tags == ["email", "phone"]


@pytest.mark.asyncio
async def test_get_current_returns_none_when_no_rows(
    transactional_session: AsyncSession,
):
    field = await _make_field(transactional_session, code_suffix="B")
    repo = FieldClassificationRepository(transactional_session)

    current = await repo.get_current(field.id)
    assert current is None


@pytest.mark.asyncio
async def test_list_by_field_returns_history_desc(
    transactional_session: AsyncSession,
):
    field = await _make_field(transactional_session, code_suffix="C")
    repo = FieldClassificationRepository(transactional_session)

    base = datetime.now(timezone.utc).replace(tzinfo=None)
    first = FieldClassification(field_id=field.id, pii_tags=["email"], created_at=base)
    transactional_session.add(first)
    await transactional_session.flush()
    second = FieldClassification(
        field_id=field.id,
        pii_tags=["email", "phone"],
        created_at=base + timedelta(milliseconds=100),
    )
    transactional_session.add(second)
    await transactional_session.flush()

    rows = await repo.list_by_field(field.id)
    assert [r.id for r in rows] == [second.id, first.id]
