# SoBo – Security checklist

Phase 5 review of the threat list in [plan section 6](IMPLEMENTATION_PLAN.md#6-security-concept).
Each measure names where it is implemented and which test backs it.

Guiding principle: **exactly one public endpoint (the cloudhook), which only knows
jukebox actions.** The Home Assistant address stays hidden from guests.

| # | Threat | Measures | Tests |
|---|---|---|---|
| 1 | Admin access by unauthorized persons | Admin UI only via ingress (`panel_admin` defaults to true), only requests from the ingress IP are answered (everything else gets `404`), no `ports:` mapping, no API docs/OpenAPI | `test_api.py::test_admin_rejects_non_ingress`, `test_app_config.py::test_admin_only_through_ingress`, `test_app_config.py::test_no_extra_privileges` |
| 2 | CSRF against the admin UI (foreign page using the ingress session) | State-changing admin requests need the `X-SoBo-Request` header (forces a CORS preflight that never succeeds); `Sec-Fetch-Site: cross-site` is refused; `form-action 'none'` | `test_api.py::test_admin_rejects_requests_without_csrf_header` |
| 3 | Direct access to the app on the LAN (`host_network`) | Internal API bound to `127.0.0.1:8738` and protected by a 256-bit shared secret (file mode `0600`), wrong/missing secret → `404` | `test_api.py::test_internal_requires_secret`, `test_api.py::test_secret_file_permissions` |
| 4 | Exposure of the HA instance | Cloudhook URL (`hooks.nabu.casa`) instead of the remote UI; the guest page and all responses contain no HA URLs, versions or host names; `no-referrer` | `tests/test_guest_access.py::test_get_serves_guest_page`, `::test_response_survives_cloud_relay`, `test_fuzz.py` (leak check on every response) |
| 5 | Guessing or sharing the QR link | Random webhook ID, rotatable (invalidates all sessions), optionally unregistered while the jukebox is off; optional presence code; maximum number of active guests | `tests/test_guest_access.py::test_rotation_requested_by_app`, `::test_unregister_when_inactive`, `test_guest_service.py::test_presence_code`, `::test_rotation_invalidates_sessions` |
| 6 | Spam / DoS without client IP | One open `wait` per session, global cap on open long polls (then "use polling"), per-session and search token buckets, global join limit, global request limit, vote/suggestion budgets, blocking by the admin, emergency stop (jukebox off, rotation) | `test_guest_service.py::test_global_join_limit`, `::test_session_rate_limit`, `::test_search_rate_limit`, `::test_new_wait_replaces_old`, `::test_global_long_poll_cap`, `test_load.py` |
| 7 | Injection of arbitrary media URIs | Guests only send opaque result IDs from the server-side search cache, never URIs or metadata | `test_guest_service.py::test_search_suggest_vote_flow`, `test_fuzz.py::test_valid_session_with_hostile_strings` |
| 8 | Input attacks | Strict pydantic action list (`extra="forbid"`, strict types), 4 KB body limit in the app and the integration, length limits, parameterized SQL (SQLModel) | `test_fuzz.py` (arbitrary bytes, arbitrary JSON, random fields, deep nesting, type confusion; settings and internal reports), `tests/test_guest_access.py::test_post_too_large` |
| 9 | XSS | CSP with hashes (guest page) / `script-src 'self'` without `unsafe-inline` (admin); external data only via `textContent`; nicknames normalized (NFKC), control/format characters (incl. bidi overrides) removed, length-limited; cover URLs only `https:` | `test_guest_page.py::test_xss_in_nickname_is_rendered_as_text`, CSP violation recorder in all browser tests, `test_fuzz.py::test_nicknames_are_cleaned`, `test_adapter_contract.py::test_soco_search_filters_non_https_art` |
| 10 | CSRF on the guest API | No cookie authentication; the session token travels in the body | (by design) |
| 11 | Session theft | Token stored only as a hash, limited lifetime (`session_hours`), rotation invalidates all sessions | `test_guest_service.py::test_token_is_stored_hashed_only`, `test_engine.py::test_session_expires` |
| 12 | Volume or speaker abuse | No guest endpoints for this; maximum volume enforced server-side; speaker only in the admin settings | `test_engine.py::test_max_volume_enforced` |
| 13 | Container | AppArmor profile (`sobo/apparmor.txt`): the Python backend runs in a child profile without capabilities, may write only to `/data` and `/tmp`; no `privileged`, `full_access`, devices or host namespaces; `hassio_api` with the default role only for discovery | `test_app_config.py`, CI job `apparmor` (parses the profile and runs the image under it with a guest flow, fails on any denial: `scripts/apparmor_smoke_test.sh`) |
| 14 | Privacy | Nicknames only, no IPs (not available through the relay), history and audit log deleted after 30 days, notice on the guest page that covers come from Apple | `test_store.py::test_audit_and_purge` |
| 15 | Dependencies | Pinned SoCo fork, Dependabot (pip, GitHub Actions), `pip-audit` in CI, ruff security rules (`S`) for backend, integration and scripts; no npm dependencies | CI jobs `backend`, `integration` |

## Residual risks

- Anyone who knows the QR link can take part until it is renewed. At a party that is
  intended; the presence code helps against sharing it outside.
- The backend runs as root inside its container (the s6 overlay of the HA base image
  starts services as root). The AppArmor child profile limits what it can do.
- Cloudhook limits (hold time, parallel requests) are undocumented; they have to be
  measured in the first real test (`sobo/backend/loadtest/locustfile.py` with
  `SOBO_TARGET=webhook`).

## Load test

- In CI: `sobo/backend/tests/test_load.py` (100 guests with open long polls: one change
  wakes everyone in well under 2 s, the long-poll cap sends the rest to polling, a burst
  of ~500 actions stays below 10 s, the default limits absorb wake-up storms).
- Against a running app or through Home Assistant: Locust scenario in
  `sobo/backend/loadtest/locustfile.py` (instructions in the file).
