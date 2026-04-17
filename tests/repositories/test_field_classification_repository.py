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


@pytest.mark.asyncio
async def test_list_current_by_dataset_returns_one_per_classified_field(
    transactional_session: AsyncSession,
):
    # Two fields in the same dataset; one has multiple classifications, one has none.
    kind = SystemKind(code="KIND_FCR_D", name="Kind FCR D")
    flavor = SystemFlavor(code="FL_FCR_D", name="Flavor FCR D", kind=kind)
    system = System(code="SYS_FCR_D", name="System FCR D", flavor=flavor)
    dataset = DatasetRdbms(
        system=system,
        object_name="customers_fcr_d",
        schema_name="public",
        table_name="customers",
    )
    email = Field(dataset=dataset, name="email_d")
    phone = Field(dataset=dataset, name="phone_d")
    transactional_session.add_all([kind, flavor, system, dataset, email, phone])
    await transactional_session.flush()

    base = datetime.now(timezone.utc).replace(tzinfo=None)
    c1 = FieldClassification(field_id=email.id, pii_tags=["email"], created_at=base)
    transactional_session.add(c1)
    await transactional_session.flush()
    c2 = FieldClassification(
        field_id=email.id,
        pii_tags=["email", "login"],
        created_at=base + timedelta(milliseconds=100),
    )
    transactional_session.add(c2)
    await transactional_session.flush()

    # Second dataset — make sure the filter excludes its rows.
    kind2 = SystemKind(code="KIND_FCR_D2", name="Kind FCR D2")
    flavor2 = SystemFlavor(code="FL_FCR_D2", name="Flavor FCR D2", kind=kind2)
    system2 = System(code="SYS_FCR_D2", name="System FCR D2", flavor=flavor2)
    dataset2 = DatasetRdbms(
        system=system2,
        object_name="customers_fcr_d2",
        schema_name="public",
        table_name="customers",
    )
    other_field = Field(dataset=dataset2, name="email_d2")
    transactional_session.add_all([kind2, flavor2, system2, dataset2, other_field])
    await transactional_session.flush()
    transactional_session.add(
        FieldClassification(
            field_id=other_field.id,
            pii_tags=["email"],
            created_at=base + timedelta(milliseconds=200),
        )
    )
    await transactional_session.flush()

    repo = FieldClassificationRepository(transactional_session)
    rows = await repo.list_current_by_dataset(dataset.id)
    assert len(rows) == 1
    assert rows[0].id == c2.id
    assert rows[0].field_id == email.id


@pytest.mark.asyncio
async def test_list_current_by_dataset_breaks_tie_on_id(
    transactional_session: AsyncSession,
):
    kind = SystemKind(code="KIND_FCR_TIE", name="Kind FCR Tie")
    flavor = SystemFlavor(code="FL_FCR_TIE", name="Flavor FCR Tie", kind=kind)
    system = System(code="SYS_FCR_TIE", name="System FCR Tie", flavor=flavor)
    dataset = DatasetRdbms(
        system=system,
        object_name="customers_fcr_tie",
        schema_name="public",
        table_name="customers",
    )
    field = Field(dataset=dataset, name="email_tie")
    transactional_session.add_all([kind, flavor, system, dataset, field])
    await transactional_session.flush()

    t = datetime.now(timezone.utc).replace(tzinfo=None)
    # Two rows with identical created_at. The tie-breaker on id.desc() should
    # pick the row with the larger UUID deterministically.
    a = FieldClassification(field_id=field.id, pii_tags=["email"], created_at=t)
    b = FieldClassification(
        field_id=field.id, pii_tags=["email", "login"], created_at=t
    )
    transactional_session.add_all([a, b])
    await transactional_session.flush()

    repo = FieldClassificationRepository(transactional_session)
    rows = await repo.list_current_by_dataset(dataset.id)
    assert len(rows) == 1
    assert rows[0].id == max(a.id, b.id)
