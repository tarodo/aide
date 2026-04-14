from __future__ import annotations

import httpx


class TokenManager:
    def __init__(self, base_url: str, username: str, password: str):
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    async def get_access_token(self, client: httpx.AsyncClient) -> str:
        if self._access_token is None:
            await self._login(client)
        return self._access_token  # type: ignore[return-value]

    async def refresh(self, client: httpx.AsyncClient) -> str:
        if self._refresh_token is None:
            await self._login(client)
            return self._access_token  # type: ignore[return-value]

        response = await client.post(
            f"{self._base_url}/api/v1/login/refresh",
            json={"refresh_token": self._refresh_token},
        )
        if response.status_code == 200:
            data = response.json()
            self._access_token = data["access_token"]
            self._refresh_token = data.get("refresh_token", self._refresh_token)
            return self._access_token
        else:
            await self._login(client)
            return self._access_token  # type: ignore[return-value]

    async def _login(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            f"{self._base_url}/api/v1/login/",
            data={"username": self._username, "password": self._password},
        )
        response.raise_for_status()
        data = response.json()
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token")

    def auth_headers(self) -> dict[str, str]:
        if self._access_token is None:
            return {}
        return {"Authorization": f"Bearer {self._access_token}"}
