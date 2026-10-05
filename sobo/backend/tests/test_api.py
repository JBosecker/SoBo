"""HTTP-Schicht: Ingress-Guard, Secret-Guard, Admin- und interne Routen (Plan 9)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
import httpx

from sobo.api.admin import create_admin_app
from sobo.api.internal import SECRET_HEADER, create_internal_app
from sobo.clock import ManualClock
from sobo.config import AppOptions
from sobo.context import AppContext
from sobo.engine.persistence import MemoryRepository
from sobo.sonos.fake_adapter import FakeSonosAdapter

from .conftest import active_settings

pytestmark = pytest.mark.anyio

INGRESS = ("172.30.32.2", 50000)
STRANGER = ("192.168.1.50", 50000)


@pytest.fixture
async def ctx(tmp_path: Path) -> AsyncIterator[AppContext]:
    clock = ManualClock()
    repo = MemoryRepository()
    repo.save_settings(active_settings())
    context = AppContext.build(
        AppOptions(data_dir=tmp_path), adapter=FakeSonosAdapter(clock), repo=repo, clock=clock
    )
    yield context
    await context.stop()


def admin_client(ctx: AppContext, client: tuple[str, int] = INGRESS) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_admin_app(ctx), client=client)
    return httpx.AsyncClient(transport=transport, base_url="http://sobo")


def internal_client(ctx: AppContext, secret: str | None = None) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_internal_app(ctx), client=("127.0.0.1", 1))
    headers = {SECRET_HEADER: secret if secret is not None else ctx.secret}
    return httpx.AsyncClient(transport=transport, base_url="http://sobo", headers=headers)


# --------------------------------------------------------------------------- Guards


@pytest.mark.parametrize("path", ["/", "/api/status", "/api/settings", "/docs", "/openapi.json"])
async def test_admin_rejects_non_ingress(ctx: AppContext, path: str) -> None:
    async with admin_client(ctx, STRANGER) as client:
        response = await client.get(path)
    assert response.status_code == 404


async def test_admin_index_via_ingress(ctx: AppContext) -> None:
    async with admin_client(ctx) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert "Hello SoBo" in response.text


@pytest.mark.parametrize("secret", ["", "falsch", "x" * 43])
async def test_internal_requires_secret(ctx: AppContext, secret: str) -> None:
    async with internal_client(ctx, secret) as client:
        response = await client.get("/internal/status")
    assert response.status_code == 404
    assert not ctx.integration_connected


async def test_secret_file_permissions(ctx: AppContext) -> None:
    mode = ctx.options.secret_path.stat().st_mode & 0o777
    assert mode == 0o600
    assert len(ctx.secret) >= 40


# --------------------------------------------------------------------------- Admin


async def test_admin_status_and_settings_roundtrip(ctx: AppContext) -> None:
    async with admin_client(ctx) as client:
        status = (await client.get("/api/status")).json()
        assert status["state"] == "inactive"
        assert status["guest_access"]["integration_connected"] is False
        settings = (await client.get("/api/settings")).json()
        settings["votes"]["votes_per_window"] = 9
        response = await client.put(
            "/api/settings", json=settings, headers={"X-Remote-User-Name": "johannes"}
        )
        assert response.status_code == 200
        assert response.json()["votes"]["votes_per_window"] == 9
        bad = dict(settings, speaker={"max_volume": 200})
        assert (await client.put("/api/settings", json=bad)).status_code == 422
        audit = (await client.get("/api/audit")).json()
    assert audit[0] == {**audit[0], "actor": "johannes", "action": "settings"}


async def test_admin_moderation_flow(ctx: AppContext) -> None:
    jb = ctx.jukebox
    guest = jb.join("Mia", "h", None)
    hits = await jb.search(guest, "comet")
    item = await jb.suggest(guest, hits[0].opaque_id)
    async with admin_client(ctx) as client:
        assert (
            await client.post(f"/api/queue/{item.id}/pin", json={"pinned": True})
        ).status_code == 204
        assert item.pinned
        response = await client.post(f"/api/guests/{guest.id}/block", json={"blocked": True})
        assert response.status_code == 204 and guest.blocked
        assert (await client.post(f"/api/queue/{item.id}/remove")).status_code == 204
        again = await client.post(f"/api/queue/{item.id}/remove")
        assert (again.status_code, again.json()) == (409, {"error": "unknown_item"})
        guests = (await client.get("/api/guests")).json()
        assert guests[0]["nickname"] == "Mia" and guests[0]["blocked"] is True


async def test_admin_sonos_lists(ctx: AppContext) -> None:
    async with admin_client(ctx) as client:
        speakers = (await client.get("/api/sonos/speakers")).json()
        accounts = (await client.get("/api/sonos/accounts")).json()
        sources = (await client.get("/api/sonos/fallback-sources")).json()
    assert {s["name"] for s in speakers} == {"Wohnzimmer", "Küche"}
    assert accounts[0]["service"] == "Apple Music"
    assert sources[0]["source_id"].startswith("fake_playlist:")


async def test_rotation_requires_integration(ctx: AppContext) -> None:
    async with admin_client(ctx) as client:
        response = await client.post("/api/guest-access/rotate")
        assert response.status_code == 409
        async with internal_client(ctx) as internal:
            await internal.get("/internal/status")
        response = await client.post("/api/guest-access/rotate")
        assert response.status_code == 202
        status = (await client.get("/api/status")).json()
    assert status["guest_access"]["rotation_pending"] is True


# --------------------------------------------------------------------------- Intern


async def test_internal_guest_proxy_and_rotation(ctx: AppContext) -> None:
    async with internal_client(ctx) as client:
        response = await client.post("/internal/guest", json={"action": "join", "nickname": "Mia"})
        assert response.status_code == 200
        session = response.json()["session"]
        response = await client.post("/internal/guest", content=b"{" + b" " * 5000 + b"}")
        assert response.status_code == 413

        status = (await client.get("/internal/status")).json()
        assert status["guest_access_reported"] is False
        assert status["long_poll_timeout"] == 20
        ctx.rotation_requested = 1
        status = (await client.get("/internal/status")).json()
        assert (status["rotation_requested"], status["rotation_done"]) == (1, 0)
        response = await client.post(
            "/internal/rotated",
            json={"generation": 1, "url": "https://hooks.nabu.casa/abc", "cloud_connected": True},
        )
        assert response.status_code == 204
        response = await client.post(
            "/internal/guest", json={"action": "state", "session": session}
        )
        assert response.status_code == 401
        status = (await client.get("/internal/status")).json()
        assert (status["rotation_done"], status["guest_access_reported"]) == (1, True)
    assert ctx.guest_access_view()["url"] == "https://hooks.nabu.casa/abc"
    assert ctx.guest_access_view()["rotation_pending"] is False


async def test_internal_rejects_non_https_guest_url(ctx: AppContext) -> None:
    async with internal_client(ctx) as client:
        response = await client.post("/internal/guest-access", json={"url": "http://evil"})
    assert response.status_code == 422


async def test_internal_active_and_skip(ctx: AppContext) -> None:
    async with internal_client(ctx) as client:
        assert (await client.post("/internal/active", json={"active": False})).status_code == 204
        assert ctx.jukebox.settings.active is False
        assert (await client.post("/internal/skip")).status_code == 204
