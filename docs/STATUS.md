# SoBo – Implementation status

As of: 2026-10-05

## Done

| Phase | Contents | Status |
|---|---|---|
| 0 – Setup | Repo layout, app configuration (`config.yaml`, `Dockerfile`, s6 service), CI (ruff, mypy, pytest, pip-audit, app linter, multi-arch build), Dependabot, devcontainer, SoCo fork pinned to `97dba03`, "Hello SoBo" status page | ✔ |
| 1 – Sonos adapter | `SonosAdapter` protocol, `FakeSonosAdapter` (simulated time), `SoCoAdapter` (fork), `SonosWorker` (one thread, timeouts), contract tests against both adapters | ✔ |
| 2 – Engine | Queue, ranking, sliding vote/suggestion budgets, limits (length, explicit, blocklist, cooldowns), base playlist, state machine, lookahead with fixing, `manual_override`, max volume, version counter/change signal, SQLite store + Alembic | ✔ |
| 3 – Admin UI | Admin API (status, settings, moderation, guests, audit, Sonos lists, rotation) with ingress guard and CSP; UI with live view, guest access (QR code, printing, renewal), settings, log | ✔ |
| 4 – Integration & guest access | Guest API (sessions, rate limits, long polling); integration `custom_components/sobo`: config flow (discovery + manual), webhook/cloudhook with rotation, POST proxy, entities; guest page with long polling and fallback | ✔ |
| 5 – Hardening | AppArmor profile (backend in a child profile without capabilities, writes only to `/data` and `/tmp`) with a CI smoke test of the real image under the profile; fuzzing of guest actions, settings and internal reports (Hypothesis); in-process load test with 100 long-polling guests and a Locust scenario; CSRF protection of the admin API; static checks of the container permissions; security checklist in [`docs/SECURITY.md`](SECURITY.md) | ✔ |
| 6 – Release v0.1 (prepared) | Version 0.1.0 everywhere, changelog; release workflow (build per architecture, push to GHCR, multi-arch image `ghcr.io/jbosecker/sobo`, Cosign signing and verification, version check against the tag); `image` in `config.yaml`; app icon/logo and local brand images for the integration; installation instructions; release guide incl. first real test in [`docs/RELEASE.md`](RELEASE.md) | ◐ owner steps open |
| – Language | English is the main language of the repository (code, comments, docs, commits). Admin UI, guest page, "jukebox is off" page, integration and app options are localized in English and German | ✔ |

## Tests

| Area | Where | Result |
|---|---|---|
| Backend (engine, adapters, guest/admin API, store, QR, fuzzing, load, container config) | `sobo/backend/tests` | 177 passed |
| Guest page in the browser (Playwright/Chromium), incl. German locale | `sobo/backend/tests/test_guest_page.py` | 12 passed |
| Admin UI in the browser, incl. German locale and fallback language | `sobo/backend/tests/test_admin_page.py` | 9 passed |
| Integration (`pytest-homeassistant-custom-component`) | `tests/` | 29 passed (CI) |

```bash
# Backend
cd sobo/backend && uv venv && uv pip install -e ".[dev,browser]"
uv run playwright install chromium
uv run pytest -p anyio && uv run mypy src && uv run ruff check src tests

# Integration (in the repository root)
uv venv -p 3.14 .venv-ha && source .venv-ha/bin/activate
uv pip install -r requirements_test.txt && pytest

# Rebuild the guest page after changes in frontend/guest
python3 scripts/build_guest_page.py
# To look at it with a simulated Sonos (in sobo/backend):
uv run python -m tests.guest_harness   # guest page: http://127.0.0.1:8740/g/demo
uv run python -m tests.admin_harness   # admin UI:   http://127.0.0.1:8741/
```

## Deliberate deviations from the plan

1. **Next track without `as_next=True`.** According to SoCo, `as_next` only works in
   shuffle mode. Instead the adapter removes everything after the current track and
   appends the next one. Same result as planned: Sonos queue = [current, next].
2. **The backend lives in `sobo/backend/`** instead of `backend/` in the repository
   root. The Supervisor builds locally with the app folder as the only build context.
3. **Internal API on its own port, `127.0.0.1:8738` only.** HA Core and the app both
   use the host network, so the internal API is not reachable from the LAN at all.
   The secret is still required. Admin/ingress stays on `:8737`.
4. **Rotation without a callback to the integration.** The app increments
   `rotation_requested`; the integration sees this when polling `/internal/status`
   (every 5 s), rotates and reports via `/internal/rotated`. The state can be read
   statelessly (`rotation_requested > rotation_done`) and survives restarts of both sides.
5. **In-memory search cache** instead of a `search_result_cache` table. After a
   restart guests simply search again. `guest_access` is not a table either; the
   integration reports the URL again on every start.
6. **Fallback track vs. fixing:** if a base playlist track is queued as next and a
   guest suggestion arrives, the fallback track is replaced. Guest tracks stay
   fixed, as planned.
7. **Jukebox off:** the current track plays to the end, SoBo enqueues nothing more
   (the "next" track is removed from the Sonos queue).
8. **Async tests with the anyio plugin** instead of pytest-asyncio (backend).
9. **Guest page without Vite/npm.** Hand-written HTML/CSS/JS (no framework); a
   Python script combines everything into one file and computes the CSP hashes.
   34 KB instead of the < 50 KB target, no npm dependencies.
10. **`wait` with an optional wait time.** After aborts the page sends a shorter
    wait time (plan 4.4: halve, at least 5 s); the app never uses more than the
    admin setting.
11. **Webhook ID in the config entry** (plain text) instead of hashed in the app:
    the integration needs it to register the webhook.
12. **The cloudhook survives reloads**, otherwise the QR code would get a new URL
    after every HA restart. It is deleted on rotation and when the integration is removed.
13. **Own HTTP session in the integration** without a per-host connection limit
    (HA's shared session only allows 100 connections per host; long polls need more).
14. **Entity IDs** follow the translated names, e.g. `switch.sobo_jukebox` instead
    of `switch.sobo_active`.
15. **Admin UI without Svelte/Preact/Vite.** Static HTML/CSS/JS (no framework, no
    build step), served by the app with CSP `script-src 'self'`. Forms are built from
    a field list; validation errors from the API appear next to the field.
16. **QR code rendered server-side as SVG** with Project Nayuki's generator (MIT,
    unmodified under `sobo/vendor/`). "Print as PDF" via the browser's print view
    (A4 poster with QR code and, if set, the presence code).
17. **Idempotent rotation:** the integration remembers the executed rotation and,
    if the confirmation is lost, only repeats the report, never the rotation.
18. **Localization without a framework.** Each UI carries an `I18N` dictionary
    (`en`, `de`); the language comes from `navigator.languages`, falling back to
    English. The HTML contains the English texts with `data-i18n` keys. The
    "jukebox is off" page (no JavaScript) is chosen by `Accept-Language`.
19. **Load test in two parts:** fast in-process checks in CI (`tests/test_load.py`)
    plus a Locust scenario for a running app or the real cloudhook
    (`sobo/backend/loadtest/`), instead of Locust only.
20. **CSRF header for the admin API** (`X-SoBo-Request`), not in the plan: ingress
    sessions are cookies, so state-changing requests need a header a foreign page
    cannot send.
21. **Demo data in English:** the simulated speakers are "Living Room" and "Kitchen",
    the demo playlist is "Party Basics".
22. **Local brand images** in `custom_components/sobo/brand/` (Home Assistant 2026.3+)
    instead of a pull request to home-assistant/brands; rendered by
    `scripts/make_brand_images.py`.
23. **Multi-arch image** `ghcr.io/jbosecker/sobo` (generic name, recommended since the
    BuildKit builder) instead of `{arch}-sobo` in `config.yaml`.

## Security details

- CSP via meta tag with hashes for script and style, `connect-src 'self'`, `img-src https:`.
- `referrer: no-referrer`: when covers are loaded, the page URL (the access key)
  is not sent to Apple's CDN.
- Foreign data only via `textContent`; verified in a browser test with XSS in the nickname.
- Local access additionally gets `nosniff`, `no-store` and `no-referrer` headers
  (through the relay only status, body and `Content-Type` arrive).
- Webhook handlers catch all errors themselves: otherwise HA would answer with 200.
- Admin UI: only reachable from the ingress IP, CSP without `unsafe-inline`,
  `frame-ancestors 'self'`, `no-store`; foreign data only via `textContent`.

## Findings from the first real test

| Version | Finding | Fix |
|---|---|---|
| 0.1.0 | The Apple Music account was not offered ("Sonos is not responding right now"): Sonos sends the account list AES-encrypted and the image lacked `cryptography` | 0.1.1: dependency `soco[music-services]`, unit test with a real envelope, smoke test checks the image; the admin UI shows the reason of Sonos errors |
| 0.1.1 | Search failed with `Client.AuthTokenExpired` (`InvalidTokenException`): Apple rejected the sign-in read from the household, even after the fork's token refresh | 0.1.2: re-read the household credentials and retry once; if still rejected, banner with re-authorization hint and a log line describing the stored sign-in (open: confirm on the real system) |
| 0.1.2 | Still `AuthTokenExpired`. `scripts/diagnose_apple_music.py` on the real household: the account UDN carries the UID 0, the fork's account-scoped identity `<household>_00000000` is rejected by Apple, the plain household identity works for search and token refresh on every speaker | 0.1.3: plain household identity for accounts without a UID (`use_household_identity_if_unscoped`); report to the fork |

## Open points / risks

- The HACS check only runs once the repository is public (HACS loads files without authentication).
- Build after HA's switch to BuildKit: the base image is set in the `Dockerfile`
  (`base-python:3.13-alpine3.24`, multi-arch), `build.yaml` is gone. CI builds with
  `home-assistant/builder/actions/build-image@2026.09.0`; CI builds without push, the
  release workflow pushes and signs. `config.yaml` points to `ghcr.io/jbosecker/sobo`,
  so `main` must always carry a released version (see `docs/RELEASE.md`).
- Condensed font on the guest page: Avenir Next Condensed (iOS), otherwise Roboto
  Condensed or Arial Narrow; without these the normal system font.
- The AppArmor profile is verified in CI on Ubuntu; on HAOS it is first exercised in the real test.
- The backend runs as root inside its container (s6 overlay of the HA base image), limited by AppArmor.
- Discovery host `127.0.0.1` requires HA Core on the host network (HAOS/Supervised: yes).
- The store keeps timestamps with the UTC time zone (SQLModel ≥ 0.0.47 requires this).
- Database growth: history and audit log are deleted after 30 days.
- Measure cloudhook limits (hold time, parallel requests) in the first real test (plan 10).

## Next steps

- **Phase 6, owner steps** (checklist in `docs/RELEASE.md`): make the repository public,
  description and topics, publish the GitHub release `0.1.0`, set the GHCR packages to
  public, check the `hacs` job.
- **Then:** first real test with Sonos and Nabu Casa (not part of the plan; steps in
  `docs/RELEASE.md`), afterwards HACS default store / community app list.
