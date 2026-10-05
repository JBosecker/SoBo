"""Client for the internal API of the SoBo app (127.0.0.1 only, shared secret)."""

from __future__ import annotations

from typing import Any

import aiohttp

from .const import REQUEST_TIMEOUT, SECRET_HEADER


class SoboApiError(Exception):
    """App not reachable or unexpected response."""


class SoboAuthError(SoboApiError):
    """Secret rejected (the app then answers 404)."""


class SoboClient:
    def __init__(self, session: aiohttp.ClientSession, host: str, port: int, secret: str) -> None:
        self._session = session
        self._base = f"http://{host}:{port}/internal"
        self._headers = {SECRET_HEADER: secret}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        timeout: float = REQUEST_TIMEOUT,
    ) -> Any:
        try:
            async with self._session.request(
                method,
                f"{self._base}{path}",
                json=json,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status == 404:
                    raise SoboAuthError("Secret rejected")
                if response.status >= 400:
                    raise SoboApiError(f"HTTP {response.status}")
                if response.status == 204:
                    return None
                return await response.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SoboApiError(str(err) or type(err).__name__) from err

    async def status(self) -> dict[str, Any]:
        data = await self._request("GET", "/status")
        if not isinstance(data, dict):
            raise SoboApiError("Invalid status response")
        return data

    async def guest_action(self, body: bytes, timeout: float) -> tuple[int, str]:
        """Forward a guest action unchanged and return (status, JSON text)."""
        try:
            async with self._session.post(
                f"{self._base}/guest",
                data=body,
                headers={**self._headers, "Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status == 404:
                    raise SoboAuthError("Secret rejected")
                return response.status, await response.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SoboApiError(str(err) or type(err).__name__) from err

    async def report_guest_access(
        self, url: str | None, local_url: str | None, cloud_connected: bool | None
    ) -> None:
        await self._request(
            "POST",
            "/guest-access",
            json={"url": url, "local_url": local_url, "cloud_connected": cloud_connected},
        )

    async def report_rotated(
        self, generation: int, url: str | None, local_url: str | None, cloud_connected: bool | None
    ) -> None:
        await self._request(
            "POST",
            "/rotated",
            json={
                "generation": generation,
                "url": url,
                "local_url": local_url,
                "cloud_connected": cloud_connected,
            },
        )

    async def set_active(self, active: bool) -> None:
        await self._request("POST", "/active", json={"active": active})

    async def skip(self) -> None:
        await self._request("POST", "/skip")
