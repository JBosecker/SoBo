"""Internal API for the HA integration (plan 3.3).

Bound to 127.0.0.1 only and additionally protected by `X-SoBo-Secret`; without a
valid secret every route answers 404.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..context import AppContext
from ..security.secrets import constant_time_equals
from ..sonos.adapter import SonosError
from .guest_service import MAX_BODY_BYTES

SECRET_HEADER = "X-SoBo-Secret"  # noqa: S105 – header name, not a secret


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GuestAccessReport(_Body):
    url: str | None = Field(default=None, max_length=300, pattern=r"^https://")
    local_url: str | None = Field(default=None, max_length=300, pattern=r"^https?://")
    cloud_connected: bool | None = None


class RotatedReport(GuestAccessReport):
    generation: int = Field(ge=0)


class ActiveBody(_Body):
    active: bool


def ctx_of(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx


Ctx = Annotated[AppContext, Depends(ctx_of)]
ACTOR = "integration"

router = APIRouter(prefix="/internal")


@router.post("/guest")
async def guest_action(request: Request, ctx: Ctx) -> JSONResponse:
    """Forwarded guest action (POST body from the cloudhook, unchanged)."""
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            break
    status, payload = await ctx.guest_service.handle(body)
    return JSONResponse(payload, status_code=status)


@router.get("/status")
async def status(ctx: Ctx) -> dict[str, Any]:
    jb = ctx.jukebox
    current = jb.queue.playing
    return {
        "version": jb.notifier.version,
        "active": jb.settings.active,
        "effectively_active": jb.effectively_active,
        "state": jb.state.value,
        "now_playing": {"title": current.track.title, "artist": current.track.artist}
        if current
        else None,
        "queue_length": len(jb.queue.waiting()),
        "active_guests": jb.active_guest_count(),
        "rotation_requested": ctx.rotation_requested,
        "rotation_done": ctx.rotation_done,
        # After an app restart the URL is unknown → the integration reports it again.
        "guest_access_reported": ctx.guest_access.reported_at is not None,
        "long_poll_timeout": jb.settings.guest_access.long_poll_timeout,
        "unregister_when_inactive": jb.settings.guest_access.unregister_when_inactive,
    }


@router.post("/guest-access", status_code=204)
async def report_guest_access(body: GuestAccessReport, ctx: Ctx) -> None:
    info = ctx.guest_access
    info.url, info.local_url, info.cloud_connected = body.url, body.local_url, body.cloud_connected
    info.reported_at = ctx.clock.now()


@router.post("/rotated", status_code=204)
async def rotated(body: RotatedReport, ctx: Ctx) -> None:
    """The integration renewed webhook/cloudhook → discard all guest sessions."""
    await report_guest_access(body, ctx)
    ctx.rotation_done = max(ctx.rotation_done, body.generation)
    ctx.guest_service.reset()
    await ctx.jukebox.rotate_sessions(ACTOR)


@router.post("/active", status_code=204)
async def set_active(body: ActiveBody, ctx: Ctx) -> None:
    await ctx.jukebox.set_active(body.active, ACTOR)


@router.post("/skip", status_code=204)
async def skip(ctx: Ctx) -> None:
    await ctx.jukebox.skip(ACTOR)


def create_internal_app(ctx: AppContext) -> FastAPI:
    app = FastAPI(title="SoBo intern", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ctx = ctx

    @app.middleware("http")
    async def secret_guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not constant_time_equals(request.headers.get(SECRET_HEADER), ctx.secret):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        ctx.integration_seen()
        return await call_next(request)

    @app.exception_handler(SonosError)
    async def _sonos(_: Request, exc: SonosError) -> JSONResponse:
        return JSONResponse({"error": "sonos_unavailable"}, status_code=503)

    app.include_router(router)
    return app
