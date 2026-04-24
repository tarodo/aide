import uuid

import pytest


@pytest.mark.asyncio
async def test_compat_method_calls_expected_path():
    from aide_sdk.resources.dataset_links import DatasetLinksResource

    calls: list[dict] = []

    class FakeHttp:
        async def get(self, path, *, params=None):
            calls.append({"path": path, "params": params})
            link_id = path.split("/")[-2]
            return {
                "dataset_link_id": link_id,
                "pin_drift": {
                    "source": {
                        "pinned_version": 1,
                        "latest_version": 1,
                        "has_drift": False,
                    },
                    "target": {
                        "pinned_version": 1,
                        "latest_version": 1,
                        "has_drift": False,
                    },
                },
                "field_compat": [],
                "summary": {"ok": 0, "warn": 0, "error": 0, "total": 0},
                "status": "ok",
            }

    resource = DatasetLinksResource.__new__(DatasetLinksResource)
    resource._http = FakeHttp()
    resource._path = "/api/v1/dataset-links"

    link_id = uuid.uuid4()
    report = await resource.compat(link_id)

    assert report.status.value == "ok"
    assert calls[0]["path"] == f"/api/v1/dataset-links/{link_id}/compat"


@pytest.mark.asyncio
async def test_list_compat_passes_filters():
    from aide_sdk.resources.dataset_links import DatasetLinksResource

    calls: list[dict] = []

    class FakeHttp:
        async def get(self, path, *, params=None):
            calls.append({"path": path, "params": params})
            return {
                "items": [],
                "total": 0,
                "page": 1,
                "size": 20,
                "pages": 0,
            }

    resource = DatasetLinksResource.__new__(DatasetLinksResource)
    resource._http = FakeHttp()
    resource._path = "/api/v1/dataset-links"

    page = await resource.list_compat(status=["error", "warn"], has_drift=True)

    assert page.total == 0
    assert calls[0]["path"] == "/api/v1/dataset-links/compat"
    assert "status" in calls[0]["params"]
    assert calls[0]["params"]["has_drift"] is True
