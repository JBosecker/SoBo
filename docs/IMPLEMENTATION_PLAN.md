# SoBo – Implementation Plan

*Sonos jukebox as a Home Assistant app (formerly add-on), inspired by MuBo*
As of: 05.10.2026 · Version 3 (long polling added for the guest page)

---

## 0. Decisions

| # | Question | Decision | Impact |
|---|---|---|---|
| E1 | Primary music service | **Apple Music** | According to the SoCo fork's `VERIFIED.md`, browse, search, metadata and track playback are verified. This removes the biggest risk from v1. |
| E2 | Downvotes | **No** | Upvotes only. Ranking and data model become simpler. |
| E3 | Party display mode | **Not in the MVP** | Moved to the backlog |
| E4 | Guests should not see the Nabu Casa address | **Guest access via Cloudhook (`hooks.nabu.casa`)** | Section 3 is new, with consequences for guest UI, sessions and security |
| E5 | Live updates of the guest page | **Long polling via the Cloudhook, with automatic fallback to polling** | WebSocket and SSE are not possible via the Cloudhook (sections 3.1 and 4.4) |

---

## 1. Goal and Scope

SoBo turns a Sonos system into a party jukebox: guests scan a QR code, search for songs in Apple Music (via the account set up in the Sonos household), suggest them and vote. The queue sorts itself automatically by votes. The admin controls everything via an Ingress interface in Home Assistant.

| Requirement | Consequence for the design |
|---|---|
| Admin UI via Ingress, HA users | `ingress: true`, `panel_admin: true`, no separate user management for admins |
| Guest access without Wi-Fi via QR | Public entry point via a **Nabu Casa Cloudhook** |
| Guests do not see the HA address | No guest page under `*.ui.nabu.casa`. The Remote UI is not needed for SoBo at all. |
| Security has priority | Exactly one public endpoint that only knows jukebox actions (section 6) |
| No room selection for guests | Speaker/group only in the admin configuration |
| Automatic re-sorting by votes | SoBo holds the leading queue itself; Sonos only gets "current + next" (section 5) |
| No testing with a real system for now | Sonos access behind an adapter interface, tests against a fake (section 9) |

---

## 2. Architecture Overview

```
 Guest phone (mobile data)                      HA admin
        │ HTTPS                                    │ HTTPS (Remote UI/LAN, HA login)
        ▼                                          ▼
 https://hooks.nabu.casa/<cloudhook-id>     https://<id>.ui.nabu.casa / LAN
        │ (Nabu Casa relay, no HA address)         │
        ▼                                          ▼
 ┌──────────────────── Home Assistant Core ────────────────────────┐
 │  custom_components/sobo  (companion integration, HACS)          │
 │   • Webhook (GET+POST) + Cloudhook                              │
 │       GET  → serves a self-contained guest HTML page            │
 │       POST → JSON actions, forwarded to the app with secret     │
 │   • Entities: switch.sobo_active, sensor.sobo_guest_url …       │
 │                                     Ingress proxy (Supervisor) ─┤
 └───────────────┬──────────────────────────────────┬──────────────┘
                 │ internal guest API (shared secret)│ Ingress (admins only)
                 ▼                                   ▼
 ┌──────────────────── SoBo app (Docker) ──────────────────────────┐
 │  FastAPI/uvicorn: /admin API + admin SPA │ /guest API           │
 │  Jukebox engine (queue, votes, limits, base playlist)           │
 │  SonosAdapter ── SoCo fork (music-services) ── Sonos on LAN     │
 │  SQLite (/data)                                                 │
 └─────────────────────────────────────────────────────────────────┘
```

**Two components in one repository:**

1. **SoBo app** (Docker container, managed by the Supervisor): business logic, Sonos control, admin UI, internal guest API.
2. **SoBo integration** (`custom_components/sobo`, installed via HACS): webhook/Cloudhook as the public guest entry point, and HA entities.

Why an integration at all? Webhooks and Cloudhooks can only be registered inside HA Core; an app cannot do that itself.

---

## 3. Guest Access via Cloudhook

### 3.1 What a Cloudhook provides

Verified in the HA source code (`components/cloud/client.py` → `async_webhook_message`, `components/webhook`, `util/aiohttp.serialize_response`):

| Property | Behavior | Consequence for SoBo |
|---|---|---|
| URL | `https://hooks.nabu.casa/<random ID>`, unrelated to the HA address | ✔ Satisfies E4 |
| Methods | Webhook can be registered with `allowed_methods={GET, POST}` | GET serves the page, POST the API |
| Request | Method, headers, query string and body (as **UTF-8 text**) are forwarded. `remote` is `None`. | **No client IP**, so rate limits cannot be per IP. Text/JSON only. |
| Response | Status, body (text) and **only the `Content-Type` header** | **No cookies, no CSP/cache headers, no ETag, no binary data (images)** |
| Paths | One fixed URL; SoBo does **not** depend on subpaths | Single page with actions in the POST body |
| Streaming | One request, one response. HA reads the response completely (`serialize_response`), **no WebSocket upgrade, no SSE**. The Nabu Casa client (`hass_nabucasa/iot.py`) handles each Cloudhook message in its own task. | **Long polling** is possible, because waiting requests do not block each other |
| Prerequisite | Active Nabu Casa subscription, cloud logged in. The Remote UI does **not** need to be active. | Show status in the admin UI |

Limits on payload size, rate and timeout are not documented (the Nabu Casa docs do not mention any). The same applies to how long the relay holds an open request. SoBo therefore keeps responses small (< 50 KB for the page, < 10 KB per JSON response), makes the long-poll wait time configurable, and automatically falls back to normal polling if problems occur.

### 3.2 Flow

1. **Activate the jukebox:** The integration generates a random `webhook_id` (≥128 bits), registers the webhook (`local_only=False`, GET+POST) and creates the public URL via `cloud.async_create_cloudhook()`. The QR code contains exactly this URL.
2. **GET** on the URL returns a **self-contained HTML page** (CSS and JS inline, no external resources except album covers). The page is generated at build time and shipped with the integration.
3. **Join:** The page sends `POST {"action":"join","nickname":…}`. SoBo returns a **session token** (random, stored hashed on the server). The token is kept in the `localStorage` of the guest's phone, because cookies do not pass through the relay.
4. **All further actions** are sent as `POST` with JSON: `{"action":"state"|"wait"|"search"|"suggest"|"vote", "session":"…", …}`. The integration forwards them to the app with the shared secret. `wait` is the long poll (section 4.4).
5. **Rotation:** The admin clicks "Renew guest access". The integration deletes the old Cloudhook (`async_delete_cloudhook`) and webhook, creates new ones, and SoBo discards all guest sessions. Old QR codes lead nowhere.
6. **Jukebox off:** The webhook stays registered but responds with a neutral page "The jukebox is currently off" (or, if the admin chooses, is unregistered entirely).

**Album covers:** Binary data does not pass through the relay. The page loads covers directly from the image URLs in the Apple Music metadata (HTTPS CDN). The admin can turn this off; then there is text only.

**No Nabu Casa available:** As an alternative, a local webhook URL (Wi-Fi only), as an admin option. The default remains the Cloudhook.

### 3.3 Coupling integration ↔ app

The app announces itself via **Supervisor discovery** (`discovery: [sobo]` in `config.yaml`, POST to `http://supervisor/discovery`) with host, port and a generated **shared secret**. The integration picks this up via `async_step_hassio` in the config flow.

The Cloudhook URL is created in the integration. The app is informed of it via the internal API so it can display it as a QR code in the admin UI. Conversely, the admin UI triggers a rotation via the app; to do so, the app calls an internal endpoint of the integration, which is also protected by the secret.

---

## 4. Components in Detail

### 4.1 Repository structure

```
sobo/                                  # Git repo = HA app repository
├── repository.yaml
├── sobo/                              # the app
│   ├── config.yaml                    # ingress, panel_admin, discovery, hassio_api, options/schema
│   ├── Dockerfile                     # ghcr.io/home-assistant/{arch}-base-python
│   ├── build.yaml, apparmor.txt
│   ├── DOCS.md, CHANGELOG.md, translations/{de,en}.yaml
│   └── rootfs/etc/services.d/sobo/run
├── backend/sobo/
│   ├── api/{admin,guest,ingress_guard}.py
│   ├── engine/{queue,ranking,limits,fallback,scheduler,state}.py
│   ├── sonos/{adapter,soco_adapter,fake_adapter,worker}.py
│   ├── store/{models,db}.py + migrations/
│   └── security/{sessions,ratelimit,secrets}.py
├── frontend/
│   ├── admin/                         # SPA for Ingress (Svelte/Preact + Vite)
│   └── guest/                         # built into ONE inline HTML file
├── custom_components/sobo/
│   ├── manifest.json (dependencies: webhook; after_dependencies: cloud, hassio)
│   ├── __init__.py, config_flow.py
│   ├── guest_webhook.py               # webhook/Cloudhook lifecycle + proxy
│   ├── guest_page.html                # build output from frontend/guest
│   └── switch.py, sensor.py, button.py
├── hacs.json
└── .github/workflows/
```

### 4.2 SoBo app (backend)

- **Stack:** Python 3.13, FastAPI + uvicorn, Pydantic v2, SQLite (SQLModel + Alembic), data in `/data`.
- **SoCo fork:** pin to a fixed commit (currently `97dba03` of `BookCatKid/SoCo-music-services-and-more@music-services`). MIT license.
  - Accounts via `MusicServiceBrowser.get_accounts(device)`: the Apple Music account from the Sonos household is reused; a separate login is not needed.
  - Search: `browser.search("tracks", term, index, count)`
  - Playback: `playback.build_uri/build_metadata` + `SoCo.add_uri_to_queue(..., as_next=True)`
- **Sonos worker:** SoCo is synchronous. All calls run serialized through a dedicated thread with timeouts.
- **Network:** `host_network: true` for SSDP discovery. In the MVP, **polling** of the transport status (1–2 s) instead of UPnP events, so no additional callback port.
- **Ingress guard:** The admin API only accepts requests from `172.30.32.2` and logs `X-Remote-User-*`. Base path from `X-Ingress-Path`.
- **Internal guest API:** only with the `X-SoBo-Secret` header (constant-time comparison), otherwise `404`.
- **Change signal:** The engine maintains a global **version counter**. Every relevant change (track change, vote, suggestion, re-sorting, moderation, jukebox on/off) increments it and wakes all waiters via an `asyncio.Condition`. Long-poll requests only wait for this signal and do not trigger any Sonos queries themselves.

### 4.3 Admin UI (Ingress)

**Settings**

- **Jukebox active** (on/off), optionally with a time window
- **Speakers:** coordinator, group members, initial volume, **maximum volume**
- **Account:** Apple Music account from the Sonos household (selection if there are several accounts)
- **Base playlist:** Sonos favorite, Sonos playlist or Apple Music playlist; shuffle or in order
- **Votes:** *N votes per guest per M minutes* (sliding window). Does a suggestion cost a vote?
- **Limits:** max. suggestions per guest and time window, max. track length, cooldown for recently played tracks/artists, explicit filter (if the metadata provides the flag), blocklist
- **Guest access:** Cloudhook and Nabu Casa status, show QR code and print as PDF, **renew guest access**, maximum active guests, session lifetime, optional **presence code**, album covers on/off

**Operation**

- Live view: current track, queue with votes, fallback status
- Moderation: remove track, pin, skip, block guest, freeze queue
- Audit log

### 4.4 Guest page

- **One HTML file**, mobile-first, target < 50 KB, everything inline, no external JS/CSS
- **CSP via `<meta http-equiv>`**, since response headers do not arrive: `default-src 'none'; script-src 'sha256-…'; style-src 'sha256-…'; img-src https:; connect-src 'self'; form-action 'none'; base-uri 'none'`. There is no `frame-ancestors` protection via meta; however, the page has no clickable actions with potential for harm outside the jukebox.
- Features: search (debounce, min. 2 characters), suggest, upvote, remaining votes with countdown, "Now playing", queue with your own suggestions highlighted
- **Live updates via long polling:**
  1. The page sends `{"action":"wait","since":<version>,"epoch":<epoch>}`. The epoch is a random ID per start of the app (the version counter starts at 0 again after a restart).
  2. The app responds **immediately** if the current version is newer, or if `since`/`epoch` come from an earlier run of the app. Otherwise it waits for the change signal, at most `long_poll_timeout` (default 20 s, configurable in the admin UI). After that it responds with `{"changed":false,"version":…}`.
  3. The page immediately sends the next `wait` request. Its own actions (vote, suggestion) return the new state directly in their response.
  4. Responses can arrive out of order (relay, a poll overlapping an action). The page ignores a state with a lower version than the one it shows (same epoch), so a newer state is never replaced by an older one (since 0.2.5).
  5. The integration proxy has a timeout of wait time + 5 s.
- **Fallback:** If a `wait` fails with a network error or 5xx before the wait time is up, the page halves the wait time (lower bound 5 s). After 3 consecutive failures it switches to normal polling every ~5 s (`action:"state"`) and retries long polling after a few minutes. On errors there is backoff with jitter, so that not all guests retry at the same time.
- **Economical:** When the tab is in the background (Page Visibility API), no requests are made. On returning, a `state` is sent immediately.
- No room selection, no volume, no playback control

### 4.5 HA integration – entities

`switch.sobo_active`, `sensor.sobo_now_playing`, `sensor.sobo_queue_length`, `sensor.sobo_active_guests`, `sensor.sobo_guest_url` (for a QR card in your own dashboard), `button.sobo_skip`, `button.sobo_rotate_guest_access`.

---

## 5. Jukebox Engine

### 5.1 "SoBo leads, Sonos plays"

SoCo cannot re-sort the Sonos queue. Therefore:

- The **leading queue lives in SoBo** and is re-sorted on every vote.
- **The Sonos queue only contains `[current, next]`.** When a track starts, the then-best track is enqueued as next (`as_next=True`) so that playback stays gapless. From then on the "next" track is **fixed**.
- If the guest queue is empty, the next track comes from the **base playlist**.
- URIs and metadata are resolved **only at enqueue time**, because track URIs may be signed, expiring URLs.
- **External interventions** (Sonos app): if the track differs, SoBo switches to `manual_override` and notifies the admin.

### 5.2 Ranking (upvotes only)

```
sorted by: pinned DESC, votes DESC, reached_at ASC
```

`reached_at` is the time of the item's latest vote, i.e. when it reached its current vote
count (votes can only be added). On a tie the song that got there first leads (changed in
0.2.4; before, the tie-breaker was `submitted_at`).

A suggestion automatically counts as the suggester's first vote. A fairness bonus based on waiting time remains a later option.

### 5.3 Rules

- Vote budget in a sliding window per guest. One vote per guest and track. Votes cannot be withdrawn (this prevents tactical voting).
- Suggesting a track that is already in the queue counts as a vote.
- Cooldown after playback, length limit, blocklist, optional explicit filter.

### 5.4 States

`inactive → idle → playing_guest | playing_fallback → paused | manual_override → …`

---

## 6. Security Concept

Guiding principle: **Exactly one public endpoint (the Cloudhook), which only knows jukebox actions.** The HA address stays hidden from guests.

| Threat | Measure |
|---|---|
| Admin access by unauthorized persons | Admin only via Ingress (`panel_admin: true`), Ingress IP check, no `ports:` mapping |
| Direct access to the app on the LAN (`host_network`) | Guest API only with shared secret, admin API only from the Ingress IP, otherwise `404` |
| Exposure of the HA instance | Cloudhook URL instead of Remote UI. The guest page and responses contain no HA URLs, versions or hostnames. |
| Guessing or sharing the QR link | Random 128-bit webhook ID, rotatable, only active while the jukebox is running. Optional presence code, maximum number of active guests. |
| Spam / DoS (**without client IP**) | **At most 1 open `wait` per session** (a new one replaces the old one), global cap on open long polls (above it the app immediately responds with "use polling"), per-session limits (token bucket), **global join limit** (e.g. 20 new sessions/min), global request limit, vote and suggestion budget, blocking by the admin, emergency stop (jukebox off or rotate access) |
| Injection of arbitrary media URIs | Guests **never** send URIs or metadata, only an **opaque result ID** from SoBo's server-side search cache |
| Input attacks | Pydantic validation, strict action list, body size limit, length limits, parameterized SQL queries |
| XSS | CSP with hashes via meta tag, no `innerHTML` with external data (only `textContent`), nicknames filtered and length-limited, cover URLs checked server-side for `https:` |
| CSRF | No cookie auth, session token in the body ⇒ no classic CSRF |
| Session theft | Token stored only hashed, limited lifetime, rotation invalidates all sessions |
| Volume or speaker abuse | No guest endpoints for this, max volume enforced server-side |
| Container | AppArmor, no `privileged`/`full_access`, `hassio_api` only for discovery, non-root where possible |
| Privacy | No real names, no IPs (not available anyway), history with a retention period. Notice on the page: covers come directly from the Apple CDN. |
| Dependencies | Pinned, Dependabot, `pip-audit`, `npm audit` in CI |

**Residual risk:** Anyone who knows the QR link can participate until rotation. At a party, that is intended. The presence code helps against sharing it outside (e.g. 4 digits, printed or announced by the admin).

---

## 7. Data Model (SQLite)

- `settings` (key/value, versioned)
- `guest_access` (id, webhook_id_hash, created_at, rotated_at, active)
- `guest` (id, session_token_hash, nickname, created_at, last_seen, blocked)
- `queue_item` (id, service_item_id, account_id, title, artist, album, art_url, duration, explicit, submitted_by, submitted_at, state: queued|next|playing|played|removed, pinned)
- `vote` (guest_id, queue_item_id, created_at), unique (guest, item)
- `search_result_cache` (opaque_id, account_id, item_payload, expires_at)
- `play_history`, `audit_log`

---

## 8. Phases and Milestones

| Phase | Content | Definition of Done |
|---|---|---|
| **0 – Setup** (≈ 2–3 days) | Repo, app skeleton, CI (ruff, mypy, pytest, multi-arch amd64/aarch64), SoCo fork pinned, HA devcontainer | App starts, Ingress shows "Hello SoBo" |
| **1 – Sonos adapter** (≈ 1 week) | `SonosAdapter` interface with `SoCoAdapter` and `FakeSonosAdapter`; worker thread; Apple Music search and enqueue via the fork | Engine only knows the interface; fake simulates playback with accelerated time |
| **2 – Engine** (≈ 1 week) | Queue, ranking, budget, limits, base playlist, states, lookahead, version counter/change signal | Unit and property tests (Hypothesis) green |
| **3 – Admin UI** (≈ 1–1.5 weeks) | Admin API + SPA: settings, live view, moderation, QR/PDF | Operable in the devcontainer with the fake |
| **4 – Integration & guest access** (≈ 1.5 weeks) | Discovery, config flow, webhook/Cloudhook lifecycle, rotation, POST action proxy, sessions, limits, guest page with long polling and fallback, entities | Guest flow end-to-end via the local webhook URL; Cloudhook path tested with a mocked `cloud` module |
| **5 – Hardening** (≈ 1 week) | Security review, CSP hashes in the build, AppArmor, fuzzing, audits, docs DE/EN | Checklist from section 6 ticked off and backed by tests |
| **6 – Release v0.1** | HACS + app repository, changelog | Installable. Only then a real test with Sonos and Nabu Casa (not part of this plan). |

Roughly 6–8 weeks for one person part-time, as a guideline.

---

## 9. Test Strategy (without a real system)

- **FakeSonosAdapter:** in-memory speaker with queue, transport state and simulated time; Apple Music-like search results from fixtures (fields like `MusicServiceBrowseItem`)
- **Unit:** ranking, budget window, limits, state machine, lookahead/fixing, `manual_override`
- **Contract tests:** the same suite against the fake and against `SoCoAdapter` with mocked SoCo objects
- **API:** FastAPI `TestClient` for the admin API (Ingress guard) and guest API (secret, limits, body size, unknown actions)
- **Long polling:** immediate response for a newer version, wake-up on change, timeout response, replacing an open `wait` of the same session, global cap. In the frontend (Playwright with simulated errors/timeouts): shortening the wait time, switching to polling, returning to long polling, pausing in the background.
- **Integration:** `pytest-homeassistant-custom-component`: config flow, discovery, webhook with GET/POST, Cloudhook creation and rotation (mocked `cloud`). Additionally, a test that sends a response through `serialize_response`, so that only text and `Content-Type` are used, i.e. exactly the relay behavior.
- **E2E:** Playwright with mobile viewports against the app (fake) + integration in the devcontainer
- **Security:** fuzzing of the POST actions (Schemathesis/Hypothesis), XSS payloads in nickname and search, URI injection, rotation, join flood
- **Load:** Locust with approx. 100 simulated guests, all of them with an open long poll

---

## 10. Risks and Open Issues

| Risk | Countermeasure |
|---|---|
| Undocumented Cloudhook limits (size, rate, timeout) | Small responses, configurable long-poll duration with automatic fallback to polling, measure early in the real test |
| Unknown: maximum hold time and number of simultaneously open Cloudhook requests at the Nabu Casa relay | Measure during the first real test (wait time in steps of 10/20/30 s, 50–100 concurrent guests) and set the default value afterwards |
| No Nabu Casa or cloud disconnected | Status in the admin UI, fallback to local webhook URL (Wi-Fi only) |
| Fork stability | Pin to a commit, encapsulate all SoCo calls in the adapter |
| Expiring track URIs | Resolve only at enqueue time |
| Explicit flag in Apple Music unclear | Filter only active if the metadata provides the field; otherwise grayed out in the UI |
| Concurrent use via the Sonos app | `manual_override` instead of fighting over the queue |
| S1/S2, multiple households | MVP: one household, S2 |
| Two installation steps (app + HACS integration) | Clear docs, "Integration not connected" status in the admin UI |

### Backlog (after MVP)

Party display mode (TV/tablet), fairness bonus in ranking, UPnP events instead of polling (Sonos side), real push via an external service (e.g. ntfy/Ably, version signals only, if long polling is not enough), additional music services, post-party statistics.

---

### Sources

- HA Core: `homeassistant/components/cloud/client.py` (`async_webhook_message`), `homeassistant/components/webhook/__init__.py` (`SUPPORTED_METHODS`, `allowed_methods`), `homeassistant/util/aiohttp.py` (`serialize_response`)
- [Nabu Casa – Webhooks](https://www.nabucasa.com/config/webhooks/)
- hass-nabucasa: `hass_nabucasa/iot.py` (webhook handler, one task per message)
- SoCo fork `BookCatKid/SoCo-music-services-and-more@music-services`, `soco/music_services/browser/VERIFIED.md`
