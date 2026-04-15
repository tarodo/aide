from pydantic import BaseModel

from backend.schemas.batch import BatchCreateRequest, BatchCreateResponse


class _Item(BaseModel):
    name: str


def test_batch_request_requires_nonempty_items():
    from pydantic import ValidationError
    import pytest

    BatchCreateRequest[_Item].model_validate({"items": [{"name": "a"}]})

    with pytest.raises(ValidationError):
        BatchCreateRequest[_Item].model_validate({"items": []})


def test_batch_response_shape():
    resp = BatchCreateResponse[_Item].model_validate(
        {"items": [{"name": "a"}, {"name": "b"}], "count": 2}
    )
    assert resp.count == 2
    assert [i.name for i in resp.items] == ["a", "b"]
