import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import System, SystemFlavor, SystemKind
from backend.models.data_type import DataType
from backend.models.dataset import DatasetRdbms
from backend.models.dataset_schema import DatasetSchema
from backend.models.field import Field
from backend.models.field_binding import FieldBinding
from backend.models.type_instance import TypeInstance
from backend.repositories.field_binding import FieldBindingRepository


@pytest.mark.asyncio
async def test_get_by_field_and_schema_returns_correct_row(
    transactional_session: AsyncSession,
):
    kind = SystemKind(code="FB_GBF_K", name="FB GBF Kind")
    flavor = SystemFlavor(code="FB_GBF_FL", name="FB GBF Flavor", kind=kind)
    system = System(code="FB_GBF_S", name="FB GBF System", flavor=flavor)
    ds = DatasetRdbms(
        system=system,
        object_name="fb_gbf_ds",
        kind="rdbms",
        schema_name="s",
        table_name="t",
    )
    dt = DataType(code="integer", system_flavor=flavor, params_schema={})
    ti = TypeInstance(data_type=dt, type_params={})
    f1 = Field(dataset=ds, name="col1", origin="mapped")
    f2 = Field(dataset=ds, name="col2", origin="mapped")
    schema = DatasetSchema(dataset=ds, version_num=1, schema={})
    transactional_session.add_all([kind, flavor, system, ds, dt, ti, f1, f2, schema])
    await transactional_session.flush()

    binding1 = FieldBinding(
        field_id=f1.id,
        dataset_schema_id=schema.id,
        position=0,
        is_nullable=True,
        type_instance_id=ti.id,
    )
    binding2 = FieldBinding(
        field_id=f2.id,
        dataset_schema_id=schema.id,
        position=1,
        is_nullable=True,
        type_instance_id=ti.id,
    )
    transactional_session.add_all([binding1, binding2])
    await transactional_session.flush()

    repo = FieldBindingRepository(transactional_session)
    found = await repo.get_by_field_and_schema(f1.id, schema.id)
    assert found is not None
    assert found.id == binding1.id
    other = await repo.get_by_field_and_schema(f2.id, schema.id)
    assert other is not None
    assert other.id == binding2.id


@pytest.mark.asyncio
async def test_get_by_field_and_schema_returns_none(
    transactional_session: AsyncSession,
):
    repo = FieldBindingRepository(transactional_session)
    result = await repo.get_by_field_and_schema(uuid.uuid4(), uuid.uuid4())
    assert result is None
