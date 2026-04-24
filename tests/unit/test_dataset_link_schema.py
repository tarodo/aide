import uuid

import pytest
from pydantic import ValidationError

from aide_schemas.dataset_link import DatasetLinkCreate, DatasetLinkUpdate


def test_dataset_link_create_requires_schema_ids():
    with pytest.raises(ValidationError) as exc_info:
        DatasetLinkCreate(
            source_dataset_id=uuid.uuid4(),
            target_dataset_id=uuid.uuid4(),
        )
    missing = {err["loc"][0] for err in exc_info.value.errors()}
    assert {"source_schema_id", "target_schema_id"}.issubset(missing)


def test_dataset_link_create_accepts_schema_ids():
    link = DatasetLinkCreate(
        source_dataset_id=uuid.uuid4(),
        target_dataset_id=uuid.uuid4(),
        source_schema_id=uuid.uuid4(),
        target_schema_id=uuid.uuid4(),
    )
    assert link.source_schema_id != link.target_schema_id


def test_dataset_link_update_rejects_dataset_ids():
    with pytest.raises(ValidationError) as exc_info:
        DatasetLinkUpdate(
            row_version=1,
            source_dataset_id=uuid.uuid4(),
            target_dataset_id=uuid.uuid4(),
        )
    forbidden = {err["loc"][0] for err in exc_info.value.errors()}
    assert "source_dataset_id" in forbidden
    assert "target_dataset_id" in forbidden


def test_dataset_link_update_rejects_explicit_null_pin():
    """Client cannot 'unpin' a schema — PATCH with null pin is 422."""
    with pytest.raises(ValidationError) as exc_info:
        DatasetLinkUpdate(
            row_version=1,
            source_schema_id=None,
        )
    errors = exc_info.value.errors()
    assert any("explicitly null" in str(err.get("msg", "")).lower() for err in errors)


def test_dataset_link_update_accepts_omitted_pins():
    """Omitting pins keeps the update semantically 'just update note/row_version'."""
    update = DatasetLinkUpdate(row_version=1, note="x")
    assert update.source_schema_id is None
    assert update.target_schema_id is None
    assert "source_schema_id" not in update.model_fields_set
