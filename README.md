# SoBo

Sonos jukebox as a Home Assistant app (formerly add-on): guests scan a QR code,
search for songs on Apple Music, suggest them and vote. The queue is sorted by
votes; the admin controls everything via ingress in Home Assistant.

The admin UI and the guest page are available in English and German and follow
the browser or phone language. [Deutsche Kurzbeschreibung](README.de.md)

Plan: [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) ·
Status: [`docs/STATUS.md`](docs/STATUS.md) ·
User guide: [`sobo/DOCS.md`](sobo/DOCS.md)

## Layout

| Path | Contents |
|---|---|
| `sobo/` | The app (Supervisor build context): `config.yaml`, `Dockerfile`, `rootfs/` |
| `sobo/backend/` | Python backend (FastAPI, engine, Sonos adapter, SQLite, admin UI) with tests |
| `custom_components/sobo/` | HA integration: guest access via webhook/cloudhook, entities |
| `tests/` | Integration tests (`pytest-homeassistant-custom-component`) |
| `frontend/guest/` | Guest page sources (build: `scripts/build_guest_page.py`) |

## Development

```bash
cd sobo/backend
uv venv && uv pip install -e ".[dev,browser]"
uv run playwright install chromium
uv run pytest -p anyio          # tests (against a simulated Sonos)
uv run ruff check src tests && uv run mypy src

# Run the app locally with the Sonos simulation (10x time lapse), admin UI on http://127.0.0.1:8737
../../scripts/dev-run.sh
```

## Translations

| What | Where |
|---|---|
| Admin UI | `I18N` in `sobo/backend/src/sobo/static/admin/admin.js` |
| Guest page | `I18N` in `frontend/guest/app.js` (then rebuild the page) |
| "Jukebox is off" page | `INACTIVE_TEXTS` in `custom_components/sobo/guest_access.py` |
| Integration (config flow, entities) | `custom_components/sobo/translations/*.json` |
| App options | `sobo/translations/*.yaml` |

English is the default; a language is used when the browser or phone prefers it.
