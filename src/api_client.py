from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_PREFIX = "/v0/management"


class APIClient:
    """Async client for CLIProxyAPI management endpoints."""

    def __init__(self, base_url: str, management_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {management_key}"}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers,
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def list_auth_files(self) -> list[dict[str, Any]]:
        """GET /v0/management/auth-files — list all OAuth credentials.

        Response format: {"files": [{"name": ..., "status": ..., ...}, ...]}
        """
        client = await self._get_client()
        resp = await client.get(f"{API_PREFIX}/auth-files")
        resp.raise_for_status()
        data = resp.json()
        # API returns {"files": [...]} wrapper
        if isinstance(data, dict):
            return data.get("files", [])
        # Fallback: if API returns a plain list
        if isinstance(data, list):
            return data
        return []

    async def set_auth_file_status(self, name: str, disabled: bool) -> None:
        """PATCH /v0/management/auth-files/status — toggle disabled state."""
        client = await self._get_client()
        resp = await client.patch(
            f"{API_PREFIX}/auth-files/status",
            json={"name": name, "disabled": disabled},
        )
        resp.raise_for_status()
        action = "Disabled" if disabled else "Enabled"
        logger.info("%s auth file: %s", action, name)

    async def download_auth_file(self, name: str) -> bytes:
        """GET /v0/management/auth-files/download?name=xxx — download credential file."""
        client = await self._get_client()
        resp = await client.get(f"{API_PREFIX}/auth-files/download", params={"name": name})
        resp.raise_for_status()
        return resp.content

    async def delete_auth_file(self, name: str) -> None:
        """DELETE /v0/management/auth-files?name=xxx — remove credential."""
        client = await self._get_client()
        resp = await client.delete(f"{API_PREFIX}/auth-files", params={"name": name})
        resp.raise_for_status()
        logger.info("Deleted auth file: %s", name)

    async def upload_auth_file(self, name: str, content: bytes) -> None:
        """POST /v0/management/auth-files/upload — upload credential file."""
        client = await self._get_client()
        resp = await client.post(
            f"{API_PREFIX}/auth-files/upload",
            files={"file": (name, content, "application/json")},
        )
        resp.raise_for_status()
        logger.info("Uploaded auth file: %s", name)

    async def get_usage(self) -> dict[str, Any]:
        """GET /v0/management/usage — request statistics."""
        client = await self._get_client()
        resp = await client.get(f"{API_PREFIX}/usage")
        resp.raise_for_status()
        return resp.json()
