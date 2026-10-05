# SoBo – Implementierungsstand

Stand: 05.10.2026

## Erledigt

| Phase | Inhalt | Status |
|---|---|---|
| 0 – Setup | Repo-Struktur, App-Konfiguration (`config.yaml`, `Dockerfile`, s6-Dienst), CI (ruff, mypy, pytest, pip-audit, App-Linter, Multi-Arch-Build), Dependabot, Devcontainer, SoCo-Fork auf `97dba03` gepinnt, Statusseite „Hello SoBo“ | ✔ |
| 1 – Sonos-Adapter | `SonosAdapter`-Protokoll, `FakeSonosAdapter` (simulierte Zeit), `SoCoAdapter` (Fork), `SonosWorker` (ein Thread, Timeouts), Vertragstests gegen beide Adapter | ✔ |
| 2 – Engine | Queue, Ranking, Vote-/Vorschlagsbudget (gleitend), Limits (Länge, Explicit, Sperrliste, Sperrzeiten), Basis-Playlist, Zustandsautomat, Lookahead mit Fixierung, `manual_override`, Max-Lautstärke, Versionszähler/Änderungssignal, SQLite-Store + Alembic | ✔ |
| 3 – Admin-UI | Admin-API (Status, Einstellungen, Moderation, Gäste, Audit, Sonos-Listen, Rotation) mit Ingress-Guard und CSP; Oberfläche mit Live-Ansicht, Gastzugang (QR-Code, Drucken, Erneuern), Einstellungen, Protokoll | ✔ |
| 4 – Integration & Gastzugang | Gast-API (Sessions, Rate-Limits, Long Polling); Integration `custom_components/sobo`: Config-Flow (Discovery + manuell), Webhook/Cloudhook mit Rotation, POST-Proxy, Entitäten; Gast-Seite mit Long Polling und Rückfall | ✔ |

## Tests

| Bereich | Wo | Stand |
|---|---|---|
| Backend (Engine, Adapter, Gast-/Admin-API, Store, QR) | `sobo/backend/tests` | 153 bestanden |
| Gast-Seite im Browser (Playwright/Chromium) | `sobo/backend/tests/test_guest_page.py` | 10 bestanden |
| Admin-Oberfläche im Browser | `sobo/backend/tests/test_admin_page.py` | 7 bestanden |
| Integration (`pytest-homeassistant-custom-component`) | `tests/` | 29 bestanden (CI) |

```bash
# Backend
cd sobo/backend && uv venv && uv pip install -e ".[dev,browser]"
uv run playwright install chromium
uv run pytest -p anyio && uv run mypy src && uv run ruff check src tests

# Integration (im Repo-Root)
uv venv -p 3.14 .venv-ha && source .venv-ha/bin/activate
uv pip install -r requirements_test.txt && pytest

# Gast-Seite nach Änderungen in frontend/guest neu bauen
python3 scripts/build_guest_page.py
# Zum Ansehen mit simuliertem Sonos (im Ordner sobo/backend):
uv run python -m tests.guest_harness   # Gast-Seite:  http://127.0.0.1:8740/g/demo
uv run python -m tests.admin_harness   # Admin-UI:    http://127.0.0.1:8741/
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
4. **Rotation ohne Rückkanal zur Integration.** Die App zählt `rotation_requested`
   hoch; die Integration sieht das beim Abfragen von `/internal/status` (alle 5 s),
   rotiert und meldet über `/internal/rotated`. Stand ist zustandslos ablesbar
   (`rotation_requested > rotation_done`), übersteht also Neustarts beider Seiten.
5. **Such-Cache im Speicher** statt Tabelle `search_result_cache`. Nach einem
   Neustart suchen Gäste einfach neu. `guest_access` wird ebenfalls nicht als
   Tabelle geführt; die Integration meldet die URL bei jedem Start erneut.
6. **Fallback-Titel vs. Fixierung:** Steht ein Titel aus der Basis-Playlist als
   nächster an und kommt ein Gastvorschlag, wird der Fallback-Titel ersetzt.
   Gasttitel bleiben fixiert, wie geplant.
7. **Jukebox aus:** Der laufende Titel spielt zu Ende, SoBo reiht nichts mehr ein
   (der „nächste“ wird aus der Sonos-Queue entfernt).
8. **Async-Tests mit dem anyio-Plugin** statt pytest-asyncio (Backend).
9. **Gast-Seite ohne Vite/npm.** Handgeschriebenes HTML/CSS/JS (ohne Framework),
   ein Python-Skript fügt alles zu einer Datei zusammen und berechnet die CSP-Hashes.
   27 KB statt Ziel < 50 KB, keine npm-Abhängigkeiten.
10. **`wait` mit optionaler Wartezeit.** Die Seite schickt nach Abbrüchen eine
    kürzere Wartezeit mit (Plan 4.4: halbieren, mindestens 5 s); die App nimmt
    nie mehr als die im Admin eingestellte.
11. **Webhook-ID im Config-Entry** (Klartext) statt gehasht in der App: Die
    Integration muss sie zum Registrieren kennen.
12. **Cloudhook bleibt beim Neuladen erhalten**, sonst hätte der QR-Code nach jedem
    HA-Neustart eine neue URL. Gelöscht wird er bei Rotation und beim Entfernen der Integration.
13. **Eigene HTTP-Session in der Integration** ohne Verbindungslimit pro Host
    (HAs gemeinsame Session erlaubt nur 100 Verbindungen pro Host; Long-Polls brauchen mehr).
14. **Entitäts-IDs** folgen den übersetzten Namen, z. B. `switch.sobo_jukebox`
    statt `switch.sobo_active`.
15. **Admin-UI ohne Svelte/Preact/Vite.** Statisches HTML/CSS/JS (ohne Framework,
    ohne Build-Schritt), ausgeliefert von der App mit CSP `script-src 'self'`.
    Formulare entstehen aus einer Feldliste; Prüffehler der API erscheinen am Feld.
16. **QR-Code serverseitig als SVG** mit dem Generator von Project Nayuki (MIT,
    unverändert unter `sobo/vendor/`). „Als PDF drucken“ über die Druckansicht des
    Browsers (A4-Aushang mit QR-Code und ggf. Anwesenheitscode).
17. **Rotation idempotent:** Die Integration merkt sich die ausgeführte Rotation und
    wiederholt bei ausbleibender Bestätigung nur die Meldung, nie die Rotation.

## Sicherheitsdetails

- CSP per Meta-Tag mit Hashes für Skript und Stil, `connect-src 'self'`, `img-src https:`.
- `referrer: no-referrer`: Beim Laden der Cover geht die Seiten-URL (der Zugangsschlüssel)
  nicht an das Apple-CDN.
- Fremddaten nur über `textContent`; im Browser-Test mit XSS im Spitznamen geprüft.
- Lokaler Zugriff bekommt zusätzlich `X-Frame-Options`, `nosniff`, `no-store`
  (über den Relay kommen nur Status, Body und `Content-Type` an).
- Webhook-Handler fangen alle Fehler selbst ab: HA würde sonst mit 200 antworten.
- Admin-UI: nur von der Ingress-IP erreichbar, CSP ohne `unsafe-inline`,
  `frame-ancestors 'self'`, `no-store`; Fremddaten nur über `textContent`.

## Offene Punkte / Risiken

- HACS-Prüfung läuft erst, wenn das Repository öffentlich ist (HACS lädt Dateien ohne Anmeldung).
- Build nach der BuildKit-Umstellung von HA: Basis-Image steht im `Dockerfile`
  (`base-python:3.13-alpine3.24`, Multi-Arch), `build.yaml` entfällt. CI baut mit
  `home-assistant/builder/actions/build-image@2026.09.0`, vorerst ohne Push und Signatur.
- Schmale Schrift der Gast-Seite: Avenir Next Condensed (iOS), sonst Roboto Condensed
  oder Arial Narrow; ohne diese die normale Systemschrift.
- AppArmor-Profil folgt in Phase 5 (bis dahin Supervisor-Standardprofil).
- Discovery-Host `127.0.0.1` setzt voraus, dass HA Core im Host-Netz läuft (HAOS/Supervised: ja).
- Store speichert Zeitstempel mit UTC-Zeitzone (SQLModel ≥ 0.0.47 verlangt das).
- Datenbank wächst; Aufbewahrung: Historie und Audit-Log werden nach 30 Tagen gelöscht.
- Cloudhook-Limits (Haltezeit, parallele Anfragen) beim ersten Echttest messen (Plan 10).

## Nächste Schritte

- **Phase 5:** Härtung (AppArmor, Fuzzing der Gast-Aktionen, Lasttest, Audits, Docs DE/EN).
- **Phase 6:** Release v0.1 (Images veröffentlichen und signieren, Repository öffentlich, HACS).
