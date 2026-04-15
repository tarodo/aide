import uuid
from unittest.mock import AsyncMock

import pytest

from aide_schemas.type_instance import TypeInstanceTree
from aide_sdk.resources.type_instances import TypeInstancesResource


@pytest.mark.asyncio
async def test_get_tree_validates_response():
    now = "2026-04-15T10:00:00Z"
    child_id = str(uuid.uuid4())
    root_id = str(uuid.uuid4())
    dt_array = str(uuid.uuid4())
    dt_text = str(uuid.uuid4())

    payload = {
        "id": root_id,
        "data_type_id": dt_array,
        "type_params": None,
        "slot": None,
        "row_version": 0,
        "created_at": now,
        "updated_at": now,
        "children": [
            {
                "id": child_id,
                "data_type_id": dt_text,
                "type_params": None,
                "slot": "item",
                "row_version": 0,
                "created_at": now,
                "updated_at": now,
                "children": [],
            }
        ],
    }

    http = AsyncMock()
    http.get = AsyncMock(return_value=payload)
    resource = TypeInstancesResource(http)

    tree = await resource.get_tree(uuid.UUID(root_id))

    assert isinstance(tree, TypeInstanceTree)
    assert str(tree.id) == root_id
    assert len(tree.children) == 1
    assert tree.children[0].slot == "item"
    assert str(tree.children[0].data_type_id) == dt_text
    http.get.assert_awaited_once_with(f"/api/v1/type-instances/{root_id}/tree")
