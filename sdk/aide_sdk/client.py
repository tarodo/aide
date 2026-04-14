from __future__ import annotations

from typing import Any

import httpx

from aide_sdk.auth import TokenManager
from aide_sdk.exceptions import raise_for_status


class HttpClient:
    def __init__(self, base_url: str, token_manager: TokenManager):
        self._base_url = base_url.rstrip("/")
        self._token_manager = token_manager
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> HttpClient:
        self._client = httpx.AsyncClient()
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HttpClient not entered as context manager")
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        retry_on_401: bool = True,
    ) -> Any:
        url = f"{self._base_url}{path}"
        token = await self._token_manager.get_access_token(self.client)
        headers = {"Authorization": f"Bearer {token}"}

        response = await self.client.request(
            method, url, json=json, params=params, headers=headers
        )

        if response.status_code == 401 and retry_on_401:
            await self._token_manager.refresh(self.client)
            return await self._request(
                method, path, json=json, params=params, retry_on_401=False
            )

        if response.status_code >= 400:
            body = (
                response.json()
                if response.headers.get("content-type", "").startswith(
                    "application/json"
                )
                else {}
            )
            raise_for_status(
                response.status_code,
                body.get("error_code", "UNKNOWN"),
                body.get("detail", response.text),
            )

        if response.status_code == 204:
            return None
        return response.json()

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, *, json: Any = None) -> Any:
        return await self._request("POST", path, json=json)

    async def put(self, path: str, *, json: Any = None) -> Any:
        return await self._request("PUT", path, json=json)

    async def delete(self, path: str) -> Any:
        return await self._request("DELETE", path)


class AideClient:
    def __init__(self, base_url: str, username: str, password: str):
        self._token_manager = TokenManager(base_url, username, password)
        self._http = HttpClient(base_url, self._token_manager)

    async def __aenter__(self) -> AideClient:
        await self._http.__aenter__()
        self._init_resources()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._http.__aexit__(*args)

    def _init_resources(self) -> None:
        from aide_sdk.resources.systems import SystemsResource
        from aide_sdk.resources.datasets import DatasetsResource
        from aide_sdk.resources.fields import FieldsResource
        from aide_sdk.resources.data_types import DataTypesResource
        from aide_sdk.resources.system_flavors import SystemFlavorsResource
        from aide_sdk.resources.dataset_schemas import DatasetSchemasResource
        from aide_sdk.resources.field_bindings import FieldBindingsResource
        from aide_sdk.resources.type_instances import TypeInstancesResource
        from aide_sdk.resources.crawl_runs import CrawlRunsResource

        self.systems = SystemsResource(self._http)
        self.datasets = DatasetsResource(self._http)
        self.fields = FieldsResource(self._http)
        self.data_types = DataTypesResource(self._http)
        self.system_flavors = SystemFlavorsResource(self._http)
        self.dataset_schemas = DatasetSchemasResource(self._http)
        self.field_bindings = FieldBindingsResource(self._http)
        self.type_instances = TypeInstancesResource(self._http)
        self.crawl_runs = CrawlRunsResource(self._http)
