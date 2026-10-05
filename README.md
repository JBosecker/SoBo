# SoBo

Sonos-Jukebox als Home Assistant App (ehem. Add-on): Gäste scannen einen QR-Code,
suchen Songs in Apple Music, schlagen sie vor und voten. Die Warteschlange sortiert
sich nach Votes; der Admin steuert alles über Ingress in Home Assistant.

Plan: [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) ·
Stand: [`docs/STATUS.md`](docs/STATUS.md)

## Aufbau

| Pfad | Inhalt |
|---|---|
| `sobo/` | Die App (Supervisor-Build-Kontext): `config.yaml`, `Dockerfile`, `rootfs/` |
| `sobo/backend/` | Python-Backend (FastAPI, Engine, Sonos-Adapter, SQLite) mit Tests |
| `custom_components/sobo/` | HA-Integration für Webhook/Cloudhook (Phase 4) |
| `frontend/` | Admin-SPA und Gast-Seite (Phasen 3–4) |

## Entwicklung

```bash
cd sobo/backend
uv venv && uv pip install -e ".[dev]"
uv run pytest -p anyio          # Tests (gegen simulierten Sonos)
uv run ruff check src tests && uv run mypy src

# App lokal mit Sonos-Simulation (10x Zeitraffer), Admin-UI auf http://127.0.0.1:8737
../../scripts/dev-run.sh
```
