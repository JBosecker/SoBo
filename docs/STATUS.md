# SoBo – Implementierungsstand

Stand: 05.10.2026

## Erledigt

| Phase | Inhalt | Status |
|---|---|---|
| 0 – Setup | Repo-Struktur, App-Konfiguration (`config.yaml`, `build.yaml`, `Dockerfile`, s6-Dienst), CI (ruff, mypy, pytest, pip-audit, App-Linter, Multi-Arch-Build), Dependabot, Devcontainer, SoCo-Fork auf `97dba03` gepinnt, Statusseite „Hello SoBo“ | ✔ (Docker-Build noch nicht ausgeführt) |
| 1 – Sonos-Adapter | `SonosAdapter`-Protokoll, `FakeSonosAdapter` (simulierte Zeit), `SoCoAdapter` (Fork), `SonosWorker` (ein Thread, Timeouts), Vertragstests gegen beide Adapter | ✔ |
| 2 – Engine | Queue, Ranking, Vote-/Vorschlagsbudget (gleitend), Limits (Länge, Explicit, Sperrliste, Sperrzeiten), Basis-Playlist, Zustandsautomat, Lookahead mit Fixierung, `manual_override`, Max-Lautstärke, Versionszähler/Änderungssignal, SQLite-Store + Alembic | ✔ (Store-Tests noch nicht ausgeführt) |
| 4 (Teil) – Gast-API | Strikte Aktionsliste, Sessions (gehasht), Rate-Limits (global, Join, Session, Suche), Long Polling inkl. Ersetzen und globaler Obergrenze, Body-Limit | ✔ |
| 3 (Teil) – Admin-API | Status, Einstellungen, Moderation, Gäste, Audit, Sonos-Listen, Rotation anstoßen; Ingress-Guard | ✔ (Tests noch nicht ausgeführt) |

Testergebnis in der Entwicklungsumgebung: **126 bestanden**, 3 Module übersprungen
(FastAPI, SQLModel/Alembic und Hypothesis waren dort nicht installierbar).
`ruff` und `mypy --strict` sind für alle Module ohne diese Pakete sauber.

**Vor dem nächsten Schritt lokal ausführen:**

```bash
cd sobo/backend && uv venv && uv pip install -e ".[dev]"
uv run pytest -p anyio && uv run mypy src && uv run ruff check src tests
```

## Abweichungen vom Plan (bewusst)

1. **Nächster Titel ohne `as_next=True`.** Laut SoCo wirkt `as_next` nur im
   Shuffle-Modus. Der Adapter entfernt stattdessen alles hinter dem aktuellen Titel
   und hängt den nächsten ans Ende. Ergebnis wie geplant: Sonos-Queue = [aktuell, nächster].
2. **Backend liegt in `sobo/backend/`** statt `backend/` im Repo-Root. Der
   Supervisor baut lokal nur mit dem App-Ordner als Build-Kontext.
3. **Interne API auf eigenem Port, nur `127.0.0.1:8738`.** HA Core und App laufen
   beide im Host-Netz; die interne API ist damit im LAN gar nicht erreichbar.
   Das Secret bleibt zusätzlich Pflicht. Admin/Ingress bleibt auf `:8737`.
4. **Rotation ohne Rückkanal zur Integration.** Statt dass die App einen Endpunkt
   der Integration aufruft, zählt die App `rotation_requested` hoch; die Integration
   fragt `/internal/status` ohnehin regelmäßig ab, rotiert und meldet über
   `/internal/rotated`. Spart einen zweiten abgesicherten Endpunkt in HA.
5. **Such-Cache im Speicher** statt Tabelle `search_result_cache`. Nach einem
   Neustart suchen Gäste einfach neu. `guest_access` wird ebenfalls nicht als
   Tabelle geführt; die Integration meldet die URL bei jedem Start.
6. **Fallback-Titel vs. Fixierung:** Steht ein Titel aus der Basis-Playlist als
   nächster an und kommt ein Gastvorschlag, wird der Fallback-Titel ersetzt.
   Gasttitel bleiben fixiert, wie geplant.
7. **Jukebox aus:** Der laufende Titel spielt zu Ende, SoBo reiht nichts mehr ein
   (der „nächste“ wird aus der Sonos-Queue entfernt).
8. **Async-Tests mit dem anyio-Plugin** statt pytest-asyncio (anyio kommt mit FastAPI).

## Offene Punkte / Risiken aus der Umsetzung

- `build.yaml`: Tag `3.13-alpine3.21` der HA-Base-Images beim ersten CI-Lauf prüfen.
- AppArmor-Profil folgt in Phase 5 (bis dahin Supervisor-Standardprofil).
- Discovery-Host `127.0.0.1` setzt voraus, dass HA Core im Host-Netz läuft (HAOS/Supervised: ja).
- Datenbank wächst; Aufbewahrung: Historie und Audit-Log werden nach 30 Tagen gelöscht.

## Nächste Schritte

- **Phase 3:** Admin-SPA (Svelte/Preact + Vite) auf Basis der vorhandenen Admin-API.
- **Phase 4:** `custom_components/sobo` (Config-Flow mit Discovery, Webhook/Cloudhook,
  Proxy auf `/internal/guest`, Entitäten) und die Gast-Seite mit Long Polling.
