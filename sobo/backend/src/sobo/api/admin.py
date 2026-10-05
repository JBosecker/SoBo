"""Admin API and admin page, reachable through ingress only (plan 4.3, 6)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from importlib import resources
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from ..context import AppContext
from ..engine.limits import RuleViolation
from ..engine.settings import JukeboxSettings
from ..qr import qr_svg
from ..sonos.adapter import SonosError

_LOG = logging.getLogger(__name__)


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActiveBody(_Body):
    active: bool


class PinBody(_Body):
    pinned: bool


class FreezeBody(_Body):
    frozen: bool


class BlockBody(_Body):
    blocked: bool


def ctx_of(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx


def actor_of(request: Request) -> str:
    """HA user from the ingress headers, for the audit log."""
    name = request.headers.get("X-Remote-User-Display-Name") or request.headers.get(
        "X-Remote-User-Name"
    )
    return (name or "admin")[:64]


Ctx = Annotated[AppContext, Depends(ctx_of)]
Actor = Annotated[str, Depends(actor_of)]

router = APIRouter(prefix="/api")


@router.get("/status")
async def status(ctx: Ctx) -> dict[str, Any]:
    view = ctx.jukebox.admin_view()
    view["guest_access"] = ctx.guest_access_view()
    return view


@router.get("/settings")
async def get_settings(ctx: Ctx) -> dict[str, Any]:
    return ctx.jukebox.settings.model_dump(mode="json")


@router.put("/settings")
async def put_settings(body: JukeboxSettings, ctx: Ctx, actor: Actor) -> dict[str, Any]:
    await ctx.jukebox.update_settings(body, actor)
    return ctx.jukebox.settings.model_dump(mode="json")


@router.post("/jukebox")
async def set_active(body: ActiveBody, ctx: Ctx, actor: Actor) -> dict[str, bool]:
    await ctx.jukebox.set_active(body.active, actor)
    return {"active": body.active}


@router.post("/queue/{item_id}/remove", status_code=204)
async def remove(item_id: str, ctx: Ctx, actor: Actor) -> None:
    await ctx.jukebox.remove_item(item_id, actor)


@router.post("/queue/{item_id}/pin", status_code=204)
async def pin(item_id: str, body: PinBody, ctx: Ctx, actor: Actor) -> None:
    await ctx.jukebox.pin_item(item_id, body.pinned, actor)


@router.post("/skip", status_code=204)
async def skip(ctx: Ctx, actor: Actor) -> None:
    await ctx.jukebox.skip(actor)


@router.post("/freeze", status_code=204)
async def freeze(body: FreezeBody, ctx: Ctx, actor: Actor) -> None:
    await ctx.jukebox.set_frozen(body.frozen, actor)


@router.post("/control/resume", status_code=204)
async def resume_control(ctx: Ctx, actor: Actor) -> None:
    await ctx.jukebox.resume_control(actor)


@router.get("/guests")
async def guests(ctx: Ctx) -> list[dict[str, Any]]:
    return ctx.jukebox.admin_guests()


@router.post("/guests/{guest_id}/block", status_code=204)
async def block(guest_id: str, body: BlockBody, ctx: Ctx, actor: Actor) -> None:
    await ctx.jukebox.block_guest(guest_id, body.blocked, actor)


@router.post("/guest-access/rotate", status_code=202)
async def rotate(ctx: Ctx, actor: Actor) -> dict[str, Any]:
    if not ctx.integration_connected:
        raise HTTPException(409, detail="integration_not_connected")
    ctx.rotation_requested += 1
    ctx.jukebox.record(actor, "rotate_requested")
    return {"generation": ctx.rotation_requested}


@router.get("/guest-access/qr.svg")
async def guest_qr(ctx: Ctx, which: Literal["cloud", "local"] = "cloud") -> Response:
    info = ctx.guest_access
    url = info.url if which == "cloud" else info.local_url
    if not url:
        raise HTTPException(404, detail="no_guest_url")
    return Response(qr_svg(url), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@router.get("/audit")
async def audit(ctx: Ctx, limit: int = 100) -> list[dict[str, str]]:
    entries = ctx.jukebox.repo.recent_audit(max(1, min(limit, 500)))
    return [
        {"at": e.at.isoformat(), "actor": e.actor, "action": e.action, "detail": e.detail}
        for e in entries
    ]


@router.get("/sonos/speakers")
async def speakers(ctx: Ctx) -> list[dict[str, Any]]:
    found = await ctx.worker.call(lambda a: a.discover(), timeout=15)
    return [
        {
            "uid": s.uid,
            "name": s.name,
            "ip": s.ip,
            "is_coordinator": s.is_coordinator,
            "group_members": list(s.group_members),
        }
        for s in found
    ]


@router.get("/sonos/accounts")
async def accounts(ctx: Ctx) -> list[dict[str, str]]:
    await ctx.jukebox.ensure_speaker()
    found = await ctx.worker.call(lambda a: a.get_accounts(), timeout=15)
    return [
        {"account_id": a.account_id, "service": a.service_name, "nickname": a.nickname}
        for a in found
    ]


@router.get("/sonos/fallback-sources")
async def fallback_sources(ctx: Ctx) -> list[dict[str, str]]:
    await ctx.jukebox.ensure_speaker()
    found = await ctx.worker.call(lambda a: a.list_fallback_sources(), timeout=15)
    return [{"source_id": s.source_id, "name": s.name, "kind": s.kind} for s in found]


ADMIN_DIR = Path(str(resources.files("sobo") / "static" / "admin"))

# Ingress loads the page inside the HA frontend (same origin) – frame-ancestors 'self'.
ADMIN_CSP = "; ".join(
    [
        "default-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' https: data:",
        "connect-src 'self'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'self'",
    ]
)
# State-changing requests must carry this header. Browsers only send custom headers
# cross-origin after a CORS preflight, which this app never allows: a foreign page
# cannot trigger admin actions even with the user's ingress session (CSRF).
REQUEST_HEADER = "X-SoBo-Request"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

SECURITY_HEADERS = {
    "Content-Security-Policy": ADMIN_CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def _index_html() -> str:
    return (ADMIN_DIR / "index.html").read_text(encoding="utf-8")


def create_admin_app(ctx: AppContext) -> FastAPI:
    app = FastAPI(title="SoBo Admin", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ctx = ctx
    trusted = ctx.options.trusted_ingress

    @app.middleware("http")
    async def ingress_guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        client = request.client.host if request.client else None
        if client not in trusted:
            # For strangers nothing exists here (plan 6).
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if request.method not in SAFE_METHODS and (
            request.headers.get(REQUEST_HEADER) != "1"
            or request.headers.get("Sec-Fetch-Site") == "cross-site"
        ):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if not request.url.path.startswith("/assets/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(RuleViolation)
    async def _rule(_: Request, exc: RuleViolation) -> JSONResponse:
        return JSONResponse({"error": exc.code}, status_code=409)

    @app.exception_handler(SonosError)
    async def _sonos(_: Request, exc: SonosError) -> JSONResponse:
        return JSONResponse({"error": "sonos_unavailable", "detail": str(exc)}, status_code=503)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _index_html()

    app.include_router(router)
    app.mount("/assets", StaticFiles(directory=ADMIN_DIR), name="assets")
    return app
