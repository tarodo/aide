import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    DatasetRdbms,
    Field,
    FieldClassification,
    System,
    SystemFlavor,
    SystemKind,
)


@pytest.mark.asyncio
async def test_cascade_delete_field_removes_classifications(
    transactional_session: AsyncSession,
):
    kind = SystemKind(code="KIND_FC_TEST", name="Kind FC Test")
    flavor = SystemFlavor(code="FL_FC_TEST", name="Flavor FC Test", kind=kind)
    system = System(code="SYS_FC_TEST", name="System FC Test", flavor=flavor)
    dataset = DatasetRdbms(
        system=system,
        object_name="customers_fc_test",
        schema_name="public",
        table_name="customers",
    )
    field = Field(dataset=dataset, name="email")
    transactional_session.add_all([kind, flavor, system, dataset, field])
    await transactional_session.flush()

    cls = FieldClassification(field_id=field.id, pii_tags=["email_address"])
    transactional_session.add(cls)
    await transactional_session.flush()

    # Delete the Field — classification row must go with it.
    await transactional_session.delete(field)
    await transactional_session.flush()

    result = await transactional_session.execute(
        select(FieldClassification).where(FieldClassification.field_id == field.id)
    )
    assert result.scalars().first() is None
