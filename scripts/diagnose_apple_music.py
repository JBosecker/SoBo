#!/usr/bin/env python3
"""Diagnose Apple Music browsing against a real Sonos household (no playback).

Run from the backend environment (contains the pinned SoCo fork):

    cd sobo/backend
    uv run python ../../scripts/diagnose_apple_music.py            # all speakers
    uv run python ../../scripts/diagnose_apple_music.py --ip 192.168.1.20

Your computer must be on the same network as the speakers (the account list
arrives as an event from a speaker; allow incoming connections if macOS asks).
The output contains no tokens or keys, only their length and the fault messages
from Apple. Nothing is played and nothing is changed on the Sonos system.
"""

from __future__ import annotations

import argparse
import copy
import sys
import traceback
from typing import Any

TERM = "love"
NEEDS_REAUTH = "needs_reauth"  # marker Sonos stores instead of a token


def short(value: object, limit: int = 300) -> str:
    text = str(value).replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + " …"


def fault_text(error: BaseException) -> str:
    parts = [f"{type(error).__name__}: {short(error)}"]
    for attr in ("code", "message", "http_status"):
        if hasattr(error, attr):
            parts.append(f"{attr}={short(getattr(error, attr), 120)}")
    detail = getattr(error, "detail", None)
    if detail is not None:
        keys = sorted(detail) if isinstance(detail, dict) else type(detail).__name__
        parts.append(f"detail={short(keys, 200)}")
    cause = error.__cause__
    if cause is not None and cause is not error:
        parts.append(f"cause=({fault_text(cause)})")
    return " | ".join(parts)


def step(label: str, fn: Any) -> Any:
    try:
        result = fn()
    except Exception as error:
        print(f"    ✗ {label}: {fault_text(error)}")
        return None
    print(f"    ✓ {label}: {short(result, 200)}")
    return result if result is not None else True


def describe_account(account: Any) -> str:
    token = str(getattr(account, "token", "") or "")
    key = str(getattr(account, "key", "") or "")
    try:
        uid = f"{account.account_uid:x}"
    except Exception as error:
        uid = f"? ({error})"
    return (
        f"service={account.service_id} serial={account.serial_number} "
        f"nickname={account.nickname!r} udn_suffix={str(account.udn).split('_X_')[-1]!r} "
        f"account_uid={uid} token_len={len(token)} key_len={len(key)} "
        f"key_is_digits={key.isdigit()} needs_reauth={token == NEEDS_REAUTH} "
        f"tier={getattr(account, 'tier', '')!r}"
    )


def check_speaker(speaker: Any, account: Any) -> None:
    from soco.music_services.browser import MusicServiceBrowser

    print(f"\n  Speaker {speaker.player_name} ({speaker.ip_address}, {speaker.uid})")
    acc = copy.copy(account)  # refreshes change the token in memory only
    browser = step(
        "construct browser (credential refresh off)",
        lambda: MusicServiceBrowser(
            "Apple Music", account=acc, device=speaker, allow_credential_refresh=False
        ),
    )
    if browser is None or browser is True:
        return
    service = browser.music_service
    caps = int(service.capabilities)
    print(
        f"    · auth_type={service.auth_type} capabilities={caps} (bin {caps:b}) "
        f"bearer_header={bool(caps & 8)} zone_player_id={bool(caps & (1 << 18))} "
        f"transport={browser.root_transport} time_zone={browser.time_zone!r}"
    )
    variants = service._get_search_variants().get("tracks") or []
    print(f"    · track search variants: {variants}")

    step(
        "search tracks (scoped identity, as SoBo does)",
        lambda: _count(browser.search("tracks", TERM, 0, 3)),
    )
    if variants:
        mapped = variants[0][1]
        step(
            "search tracks with the plain household identity",
            lambda: _count_page(browser._client.search(mapped, TERM, 0, 3)),
        )
    step("content/root browse", lambda: _count(browser.get_metadata()))
    step("SMAPI root (household identity)", lambda: _tree(browser._client, "root"))
    step("library playlists as SoBo finds them", lambda: _library(speaker, account))

    scoped = browser._scoped_client()
    refreshed = step("refreshAuthToken (scoped identity)", lambda: _refresh(scoped, acc))
    if refreshed:
        step("search tracks after refresh", lambda: _count(browser.search("tracks", TERM, 0, 3)))
    else:
        acc2 = copy.copy(account)
        browser2 = MusicServiceBrowser(
            "Apple Music", account=acc2, device=speaker, allow_credential_refresh=False
        )
        step(
            "refreshAuthToken (plain household identity)", lambda: _refresh(browser2._client, acc2)
        )


def _refresh(client: Any, account: Any) -> str:
    before = len(str(account.token or ""))
    client.refresh_auth_token()
    after = len(str(account.token or ""))
    return f"new token_len={after} (was {before}), key_len={len(str(account.key or ''))}"


def _tree(client: Any, object_id: str) -> str:
    page = client.get_metadata(object_id, 0, 50)
    return ", ".join(
        f"{r.get('title')!r}<{r.get('itemType')}:{r.get('id')}>" for r in page.get("items", [])
    )


def _library(speaker: Any, account: Any) -> str:
    from sobo.sonos.soco_adapter import _default_browser, library_playlists

    found = library_playlists(_default_browser(speaker, copy.copy(account)))
    return f"{len(found)} playlists: {[title for _, title in found[:15]]}"


def _count(result: Any) -> str:
    items = list(getattr(result, "items", []) or [])
    titles = [getattr(i, "title", "?") for i in items[:3]]
    return f"{len(items)} items {titles}"


def _count_page(page: Any) -> str:
    items = page.get("items", []) if isinstance(page, dict) else []
    return f"{len(items)} items {[i.get('title') for i in items[:3]]}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", help="only test this speaker")
    parser.add_argument("--max-speakers", type=int, default=4)
    args = parser.parse_args()

    import soco
    from soco.music_services.browser import MusicServiceBrowser

    print(f"SoCo {getattr(soco, '__version__', '?')} from {soco.__file__}")
    if args.ip:
        speakers = [soco.SoCo(args.ip)]
    else:
        found = soco.discover(timeout=5) or set()
        speakers = sorted(found, key=lambda s: s.player_name)
    if not speakers:
        print("No speakers found. Pass --ip <speaker address>.")
        return 1
    print("Speakers:", ", ".join(f"{s.player_name} ({s.ip_address})" for s in speakers))
    base = speakers[0]
    print(f"Household: {base.household_id[:12]}… via {base.player_name}")

    try:
        accounts = MusicServiceBrowser.get_accounts(device=base)
    except Exception as error:
        print(f"Reading accounts failed: {fault_text(error)}")
        traceback.print_exc()
        return 1
    print(f"\nAccounts in the household ({len(accounts)}):")
    for account in accounts:
        print("  -", describe_account(account))
    apple = [a for a in accounts if a.service_id == 204]
    if not apple:
        print("No Apple Music account (service 204) found.")
        return 1

    for account in apple:
        print(f"\n=== Apple Music account serial={account.serial_number} ===")
        for speaker in speakers[: args.max_speakers]:
            check_speaker(speaker, account)
    print("\nDone. Please send the whole output.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
