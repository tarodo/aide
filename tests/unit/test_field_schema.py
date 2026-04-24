import uuid

import pytest
from pydantic import ValidationError

from aide_schemas.field import FieldCreate, FieldOrigin, FieldUpdate


def test_field_create_accepts_origin_as_string():
    field = FieldCreate(
        dataset_id=uuid.uuid4(),
        name="col",
        origin="mapped",
    )
    assert field.origin == FieldOrigin.MAPPED


def test_field_create_default_origin_is_mapped():
    field = FieldCreate(
        dataset_id=uuid.uuid4(),
        name="col",
    )
    assert field.origin == FieldOrigin.MAPPED


def test_field_create_rejects_invalid_origin():
    with pytest.raises(ValidationError):
        FieldCreate(
            dataset_id=uuid.uuid4(),
            name="col",
            origin="bogus",
        )


def test_field_update_accepts_none_origin():
    update = FieldUpdate(row_version=1)
    assert update.origin is None


def test_field_update_accepts_enum_origin():
    update = FieldUpdate(row_version=1, origin=FieldOrigin.DEPRECATED)
    assert update.origin == FieldOrigin.DEPRECATED
