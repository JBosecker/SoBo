# SoBo – Implementierungsplan

*Sonos-Jukebox als Home Assistant App (ehem. Add-on), inspiriert von MuBo*
Stand: 05.10.2026 · Version 3 (Long Polling für die Gast-Seite ergänzt)

---

## 0. Entscheidungen

| # | Frage | Entscheidung | Auswirkung |
|---|---|---|---|
| E1 | Primärer Musikdienst | **Apple Music** | Laut `VERIFIED.md` des SoCo-Forks sind Browse, Suche, Metadaten und Track-Wiedergabe verifiziert. Das größte Risiko aus v1 entfällt damit. |
| E2 | Downvotes | **Nein** | Nur Upvotes. Ranking und Datenmodell werden einfacher. |
| E3 | Party-Display-Modus | **Nicht im MVP** | In den Backlog verschoben |
| E4 | Gäste sollen die Nabu-Casa-Adresse nicht sehen | **Gastzugang über Cloudhook (`hooks.nabu.casa`)** | Abschnitt 3 neu, mit Folgen für Gast-UI, Sessions und Sicherheit |
| E5 | Live-Aktualisierung der Gast-Seite | **Long Polling über den Cloudhook, mit automatischem Rückfall auf Polling** | WebSocket und SSE sind über den Cloudhook nicht möglich (Abschnitte 3.1 und 4.4) |

---

## 1. Ziel und Rahmen

SoBo macht ein Sonos-System zur Party-Jukebox: Gäste scannen einen QR-Code, suchen Songs in Apple Music (über das im Sonos-Haushalt eingerichtete Konto), schlagen sie vor und voten. Die Warteschlange sortiert sich automatisch nach Votes. Der Admin steuert alles über eine Ingress-Oberfläche in Home Assistant.

| Vorgabe | Konsequenz im Design |
|---|---|
| Admin-UI über Ingress, HA-User | `ingress: true`, `panel_admin: true`, keine eigene Benutzerverwaltung für Admins |
| Gästezugang ohne WLAN per QR | Öffentlicher Einstieg über einen **Nabu-Casa-Cloudhook** |
| Gäste sehen die HA-Adresse nicht | Keine Gastseite unter `*.ui.nabu.casa`. Die Remote-UI wird für SoBo gar nicht benötigt. |
| Sicherheit hat Priorität | Genau ein öffentlicher Endpunkt, der nur Jukebox-Aktionen kennt (Abschnitt 6) |
| Keine Raumwahl für Gäste | Lautsprecher/Gruppe nur in der Admin-Konfiguration |
| Auto-Umsortierung nach Votes | SoBo hält die führende Queue selbst, Sonos bekommt nur „aktuell + nächster“ (Abschnitt 5) |
| Vorerst kein Test mit echtem System | Sonos-Zugriff hinter einer Adapter-Schnittstelle, Tests gegen einen Fake (Abschnitt 9) |

---

## 2. Architektur im Überblick

```
 Gast-Handy (Mobilfunk)                         HA-Admin
        │ HTTPS                                    │ HTTPS (Remote UI/LAN, HA-Login)
        ▼                                          ▼
 https://hooks.nabu.casa/<cloudhook-id>     https://<id>.ui.nabu.casa / LAN
        │ (Nabu-Casa-Relay, ohne HA-Adresse)       │
        ▼                                          ▼
 ┌──────────────────── Home Assistant Core ────────────────────────┐
 │  custom_components/sobo  (Begleit-Integration, HACS)            │
 │   • Webhook (GET+POST) + Cloudhook                              │
 │       GET  → liefert eine in sich geschlossene Gast-HTML-Seite  │
 │       POST → JSON-Aktionen, Weiterleitung an App mit Secret     │
 │   • Entitäten: switch.sobo_active, sensor.sobo_guest_url …      │
 │                                     Ingress-Proxy (Supervisor) ─┤
 └───────────────┬──────────────────────────────────┬──────────────┘
                 │ interne Gast-API (Shared Secret)  │ Ingress (nur Admins)
                 ▼                                   ▼
 ┌──────────────────── SoBo App (Docker) ──────────────────────────┐
 │  FastAPI/uvicorn: /admin-API + Admin-SPA │ /guest-API           │
 │  Jukebox-Engine (Queue, Votes, Limits, Basis-Playlist)          │
 │  SonosAdapter ── SoCo-Fork (music-services) ── Sonos im LAN     │
 │  SQLite (/data)                                                 │
 └─────────────────────────────────────────────────────────────────┘
```

**Zwei Komponenten in einem Repository:**

1. **SoBo App** (Docker-Container, verwaltet vom Supervisor): Geschäftslogik, Sonos-Steuerung, Admin-UI, interne Gast-API.
2. **SoBo Integration** (`custom_components/sobo`, Installation über HACS): Webhook/Cloudhook als öffentlicher Gast-Einstieg und HA-Entitäten.

Warum überhaupt eine Integration? Webhooks und Cloudhooks lassen sich nur innerhalb von HA Core registrieren, eine App kann das nicht selbst.

---

## 3. Gastzugang über Cloudhook

### 3.1 Was ein Cloudhook leistet

Verifiziert im HA-Quellcode (`components/cloud/client.py` → `async_webhook_message`, `components/webhook`, `util/aiohttp.serialize_response`):

| Eigenschaft | Verhalten | Folge für SoBo |
|---|---|---|
| URL | `https://hooks.nabu.casa/<zufällige ID>`, ohne Bezug zur HA-Adresse | ✔ Erfüllt E4 |
| Methoden | Webhook kann mit `allowed_methods={GET, POST}` registriert werden | GET liefert die Seite, POST die API |
| Anfrage | Methode, Header, Query-String und Body (als **UTF-8-Text**) werden weitergeleitet. `remote` ist `None`. | **Keine Client-IP**, also Rate-Limits nicht per IP. Nur Text/JSON. |
| Antwort | Status, Body (Text) und **nur der Header `Content-Type`** | **Keine Cookies, kein CSP-/Cache-Header, kein ETag, keine Binärdaten (Bilder)** |
| Pfade | Eine feste URL; SoBo ist **nicht** auf Unterpfade angewiesen | Single-Page mit Aktionen im POST-Body |
| Streaming | Eine Anfrage, eine Antwort. HA liest die Antwort komplett ein (`serialize_response`), **kein WebSocket-Upgrade, kein SSE**. Der Nabu-Casa-Client (`hass_nabucasa/iot.py`) bearbeitet jede Cloudhook-Nachricht in einem eigenen Task. | **Long Polling** möglich, weil wartende Anfragen sich nicht gegenseitig blockieren |
| Voraussetzung | Aktives Nabu-Casa-Abo, Cloud eingeloggt. Die Remote-UI muss **nicht** aktiv sein. | Status in der Admin-UI anzeigen |

Nicht dokumentiert sind Limits zu Payload-Größe, Rate und Timeout (die Nabu-Casa-Doku nennt keine). Das gilt auch dafür, wie lange der Relay eine offene Anfrage hält. SoBo hält Antworten deshalb klein (< 50 KB für die Seite, < 10 KB je JSON-Antwort), macht die Long-Poll-Wartezeit einstellbar und fällt bei Problemen automatisch auf normales Polling zurück.

### 3.2 Ablauf

1. **Jukebox aktivieren:** Die Integration erzeugt eine zufällige `webhook_id` (≥128 Bit), registriert den Webhook (`local_only=False`, GET+POST) und legt per `cloud.async_create_cloudhook()` die öffentliche URL an. Der QR-Code enthält genau diese URL.
2. **GET** auf die URL liefert eine **in sich geschlossene HTML-Seite** (CSS und JS inline, keine externen Ressourcen außer Albumcovern). Die Seite wird beim Build erzeugt und in der Integration ausgeliefert.
3. **Beitreten:** Die Seite sendet `POST {"action":"join","nickname":…}`. SoBo gibt ein **Session-Token** zurück (zufällig, serverseitig gehasht gespeichert). Das Token liegt im `localStorage` des Gast-Handys, weil Cookies den Relay nicht passieren.
4. **Alle weiteren Aktionen** laufen als `POST` mit JSON: `{"action":"state"|"wait"|"search"|"suggest"|"vote", "session":"…", …}`. Die Integration leitet sie mit Shared Secret an die App weiter. `wait` ist der Long-Poll (Abschnitt 4.4).
5. **Rotation:** Der Admin klickt „Gastzugang erneuern“. Die Integration löscht den alten Cloudhook (`async_delete_cloudhook`) und Webhook, erzeugt neue, und SoBo verwirft alle Gast-Sessions. Alte QR-Codes laufen ins Leere.
6. **Jukebox aus:** Der Webhook bleibt registriert, antwortet aber mit einer neutralen Seite „Jukebox ist gerade aus“ (oder wird nach Admin-Wahl ganz abgemeldet).

**Albumcover:** Binärdaten passieren den Relay nicht. Die Seite lädt Cover direkt von den Bild-URLs aus den Apple-Music-Metadaten (HTTPS-CDN). Das kann der Admin abschalten; dann gibt es nur Text.

**Kein Nabu Casa verfügbar:** Ersatzweise lokale Webhook-URL (nur im WLAN), als Admin-Option. Der Standard bleibt der Cloudhook.

### 3.3 Kopplung Integration ↔ App

Die App meldet sich per **Supervisor-Discovery** (`discovery: [sobo]` in `config.yaml`, POST an `http://supervisor/discovery`) mit Host, Port und generiertem **Shared Secret**. Die Integration übernimmt das per `async_step_hassio` im Config-Flow.

Die Cloudhook-URL entsteht in der Integration. Die App bekommt sie über die interne API gemeldet, um sie in der Admin-UI als QR-Code anzuzeigen. Umgekehrt löst die Admin-UI eine Rotation über die App aus; die App ruft dazu einen internen Endpunkt der Integration auf, der ebenfalls mit dem Secret abgesichert ist.

---

## 4. Komponenten im Detail

### 4.1 Repository-Struktur

```
sobo/                                  # Git-Repo = HA App-Repository
├── repository.yaml
├── sobo/                              # die App
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
│   ├── admin/                         # SPA für Ingress (Svelte/Preact + Vite)
│   └── guest/                         # wird zu EINER inline-HTML-Datei gebaut
├── custom_components/sobo/
│   ├── manifest.json (dependencies: webhook; after_dependencies: cloud, hassio)
│   ├── __init__.py, config_flow.py
│   ├── guest_webhook.py               # Webhook/Cloudhook-Lebenszyklus + Proxy
│   ├── guest_page.html                # Build-Ergebnis aus frontend/guest
│   └── switch.py, sensor.py, button.py
├── hacs.json
└── .github/workflows/
```

### 4.2 SoBo App (Backend)

- **Stack:** Python 3.13, FastAPI + uvicorn, Pydantic v2, SQLite (SQLModel + Alembic), Daten in `/data`.
- **SoCo-Fork:** auf einen festen Commit pinnen (aktuell `97dba03` von `BookCatKid/SoCo-music-services-and-more@music-services`). Lizenz MIT.
  - Konten über `MusicServiceBrowser.get_accounts(device)`: Das Apple-Music-Konto aus dem Sonos-Haushalt wird wiederverwendet, eine eigene Anmeldung ist nicht nötig.
  - Suche: `browser.search("tracks", term, index, count)`
  - Abspielen: `playback.build_uri/build_metadata` + `SoCo.add_uri_to_queue(..., as_next=True)`
- **Sonos-Worker:** SoCo ist synchron. Alle Aufrufe laufen serialisiert über einen dedizierten Thread mit Timeouts.
- **Netzwerk:** `host_network: true` für die SSDP-Discovery. Im MVP **Polling** des Transport-Status (1–2 s) statt UPnP-Events, also kein zusätzlicher Callback-Port.
- **Ingress-Guard:** Die Admin-API akzeptiert nur Anfragen von `172.30.32.2` und protokolliert `X-Remote-User-*`. Basis-Pfad aus `X-Ingress-Path`.
- **Interne Gast-API:** nur mit Header `X-SoBo-Secret` (konstantzeitiger Vergleich), sonst `404`.
- **Änderungssignal:** Die Engine führt einen globalen **Versionszähler**. Jede relevante Änderung (Titelwechsel, Vote, Vorschlag, Umsortierung, Moderation, Jukebox an/aus) erhöht ihn und weckt alle Wartenden über eine `asyncio.Condition`. Long-Poll-Anfragen warten nur auf dieses Signal und lösen selbst keine Sonos-Abfragen aus.

### 4.3 Admin-UI (Ingress)

**Einstellungen**

- **Jukebox aktiv** (an/aus), optional mit Zeitfenster
- **Lautsprecher:** Koordinator, Gruppenmitglieder, Startlautstärke, **maximale Lautstärke**
- **Konto:** Apple-Music-Konto aus dem Sonos-Haushalt (bei mehreren Konten: Auswahl)
- **Basis-Playlist:** Sonos-Favorit, Sonos-Playlist oder Apple-Music-Playlist; Zufall oder Reihenfolge
- **Votes:** *N Votes pro Gast je M Minuten* (gleitendes Fenster). Kostet ein Vorschlag einen Vote?
- **Limits:** max. Vorschläge pro Gast und Zeitfenster, max. Titellänge, Sperrzeit für kürzlich gespielte Titel/Interpreten, Explicit-Filter (falls die Metadaten das Flag liefern), Sperrliste
- **Gastzugang:** Status von Cloudhook und Nabu Casa, QR-Code anzeigen und als PDF drucken, **Gastzugang erneuern**, maximale aktive Gäste, Session-Lebensdauer, optionaler **Anwesenheitscode**, Albumcover an/aus

**Betrieb**

- Live-Ansicht: aktueller Titel, Queue mit Votes, Fallback-Status
- Moderation: Titel entfernen, pinnen, überspringen, Gast sperren, Queue einfrieren
- Audit-Log

### 4.4 Gast-Seite

- **Eine HTML-Datei**, mobil-first, Ziel < 50 KB, alles inline, kein externes JS/CSS
- **CSP per `<meta http-equiv>`**, da Antwort-Header nicht ankommen: `default-src 'none'; script-src 'sha256-…'; style-src 'sha256-…'; img-src https:; connect-src 'self'; form-action 'none'; base-uri 'none'`. Es gibt keinen `frame-ancestors`-Schutz per Meta; die Seite hat aber keine klickbaren Aktionen mit Schadpotenzial außerhalb der Jukebox.
- Funktionen: Suche (Debounce, min. 2 Zeichen), vorschlagen, upvoten, verbleibende Votes mit Countdown, „Läuft gerade“, Queue mit Markierung eigener Vorschläge
- **Live-Aktualisierung per Long Polling:**
  1. Die Seite sendet `{"action":"wait","since":<Version>}`.
  2. Die App antwortet **sofort**, wenn die aktuelle Version neuer ist. Sonst wartet sie auf das Änderungssignal, höchstens `long_poll_timeout` (Standard 20 s, im Admin einstellbar). Danach antwortet sie mit `{"changed":false,"version":…}`.
  3. Die Seite schickt direkt die nächste `wait`-Anfrage. Eigene Aktionen (Vote, Vorschlag) liefern den neuen Zustand gleich in ihrer Antwort mit.
  4. Der Integrations-Proxy hat einen Timeout von Wartezeit + 5 s.
- **Rückfall:** Bricht ein `wait` mit Netzwerkfehler oder 5xx ab, bevor die Wartezeit um ist, halbiert die Seite die Wartezeit (Untergrenze 5 s). Nach 3 Fehlschlägen in Folge wechselt sie zu normalem Polling alle ~5 s (`action:"state"`) und versucht Long Polling nach einigen Minuten erneut. Bei Fehlern gibt es Backoff mit Jitter, damit nicht alle Gäste gleichzeitig neu anfragen.
- **Sparsam:** Ist der Tab im Hintergrund (Page Visibility API), laufen keine Anfragen. Beim Zurückkehren gibt es sofort ein `state`.
- Keine Raumwahl, keine Lautstärke, keine Wiedergabesteuerung

### 4.5 HA-Integration – Entitäten

`switch.sobo_active`, `sensor.sobo_now_playing`, `sensor.sobo_queue_length`, `sensor.sobo_active_guests`, `sensor.sobo_guest_url` (für eine QR-Karte im eigenen Dashboard), `button.sobo_skip`, `button.sobo_rotate_guest_access`.

---

## 5. Jukebox-Engine

### 5.1 „SoBo führt, Sonos spielt“

SoCo hat kein Umsortieren der Sonos-Queue. Deshalb gilt:

- Die **führende Queue liegt in SoBo** und wird bei jedem Vote neu sortiert.
- **Die Sonos-Queue enthält nur `[aktuell, nächster]`.** Beim Start eines Titels wird der dann beste Titel als nächster eingereiht (`as_next=True`), damit die Wiedergabe lückenlos bleibt. Der „nächste“ ist ab dann **fixiert**.
- Ist die Gast-Queue leer, kommt der nächste Titel aus der **Basis-Playlist**.
- URIs und Metadaten werden **erst beim Einreihen** aufgelöst, weil Track-URIs signierte, ablaufende URLs sein können.
- **Externe Eingriffe** (Sonos-App): Weicht der Titel ab, wechselt SoBo in `manual_override` und informiert den Admin.

### 5.2 Ranking (nur Upvotes)

```
sortiert nach: pinned DESC, votes DESC, submitted_at ASC
```

Ein Vorschlag zählt automatisch als erster Vote des Vorschlagenden. Ein Fairness-Bonus nach Wartezeit bleibt eine spätere Option.

### 5.3 Regeln

- Vote-Budget im gleitenden Fenster pro Gast. Ein Vote pro Gast und Titel. Votes können nicht zurückgenommen werden (das verhindert Taktieren).
- Wird ein Titel vorgeschlagen, der schon in der Queue steht, zählt das als Vote.
- Sperrzeit nach dem Abspielen, Längenlimit, Sperrliste, optional Explicit-Filter.

### 5.4 Zustände

`inactive → idle → playing_guest | playing_fallback → paused | manual_override → …`

---

## 6. Sicherheitskonzept

Leitlinie: **Genau ein öffentlicher Endpunkt (der Cloudhook), der nur Jukebox-Aktionen kennt.** Die HA-Adresse bleibt den Gästen verborgen.

| Bedrohung | Maßnahme |
|---|---|
| Admin-Zugriff durch Unbefugte | Admin nur via Ingress (`panel_admin: true`), Ingress-IP-Prüfung, kein `ports:`-Mapping |
| Direkter Zugriff auf die App im LAN (`host_network`) | Gast-API nur mit Shared Secret, Admin-API nur von der Ingress-IP, sonst `404` |
| Preisgabe der HA-Instanz | Cloudhook-URL statt Remote-UI. Gast-Seite und Antworten enthalten keine HA-URLs, Versionen oder Hostnamen. |
| Erraten oder Weitergeben des QR-Links | Zufällige 128-Bit-Webhook-ID, rotierbar, nur aktiv solange die Jukebox läuft. Optionaler Anwesenheitscode, maximale Zahl aktiver Gäste. |
| Spam / DoS (**ohne Client-IP**) | **Höchstens 1 offenes `wait` pro Session** (ein neues ersetzt das alte), globale Obergrenze offener Long-Polls (darüber antwortet die App sofort mit „Polling verwenden“), Limits pro Session (Token Bucket), **globales Join-Limit** (z. B. 20 neue Sessions/min), globales Request-Limit, Vote- und Vorschlagsbudget, Sperren durch den Admin, Not-Aus (Jukebox aus oder Zugang rotieren) |
| Injection beliebiger Medien-URIs | Gäste senden **nie** URIs oder Metadaten, nur eine **opake Ergebnis-ID** aus SoBos serverseitigem Such-Cache |
| Eingabe-Angriffe | Pydantic-Validierung, strikte Aktionsliste, Größenlimit für den Body, Längenlimits, parametrisierte SQL-Abfragen |
| XSS | CSP mit Hashes per Meta-Tag, kein `innerHTML` mit Fremddaten (nur `textContent`), Spitznamen gefiltert und begrenzt, Cover-URLs serverseitig auf `https:` geprüft |
| CSRF | Kein Cookie-Auth, Session-Token im Body ⇒ kein klassisches CSRF |
| Session-Diebstahl | Token nur gehasht gespeichert, Lebensdauer begrenzt, Rotation invalidiert alle Sessions |
| Lautstärke- oder Lautsprecher-Missbrauch | Keine Gast-Endpunkte dafür, Max-Lautstärke wird serverseitig erzwungen |
| Container | AppArmor, kein `privileged`/`full_access`, `hassio_api` nur für Discovery, Non-Root wo möglich |
| Datenschutz | Keine Klarnamen, keine IPs (stehen ohnehin nicht zur Verfügung), Historie mit Aufbewahrungsfrist. Hinweis auf der Seite: Cover kommen direkt vom Apple-CDN. |
| Abhängigkeiten | Gepinnt, Dependabot, `pip-audit`, `npm audit` in der CI |

**Verbleibendes Risiko:** Wer den QR-Link kennt, kann bis zur Rotation mitmachen. Bei einer Party ist das gewollt. Gegen Weitergabe nach außen hilft der Anwesenheitscode (z. B. 4 Ziffern, ausgedruckt oder vom Admin angesagt).

---

## 7. Datenmodell (SQLite)

- `settings` (key/value, versioniert)
- `guest_access` (id, webhook_id_hash, created_at, rotated_at, active)
- `guest` (id, session_token_hash, nickname, created_at, last_seen, blocked)
- `queue_item` (id, service_item_id, account_id, title, artist, album, art_url, duration, explicit, submitted_by, submitted_at, state: queued|next|playing|played|removed, pinned)
- `vote` (guest_id, queue_item_id, created_at), unique (guest, item)
- `search_result_cache` (opaque_id, account_id, item_payload, expires_at)
- `play_history`, `audit_log`

---

## 8. Phasen und Meilensteine

| Phase | Inhalt | Definition of Done |
|---|---|---|
| **0 – Setup** (≈ 2–3 Tage) | Repo, App-Skeleton, CI (ruff, mypy, pytest, Multi-Arch amd64/aarch64), SoCo-Fork gepinnt, HA-Devcontainer | App startet, Ingress zeigt „Hello SoBo“ |
| **1 – Sonos-Adapter** (≈ 1 Woche) | `SonosAdapter`-Interface mit `SoCoAdapter` und `FakeSonosAdapter`; Worker-Thread; Apple-Music-Suche und Enqueue über den Fork | Engine kennt nur das Interface; Fake simuliert Wiedergabe mit beschleunigter Zeit |
| **2 – Engine** (≈ 1 Woche) | Queue, Ranking, Budget, Limits, Basis-Playlist, Zustände, Lookahead, Versionszähler/Änderungssignal | Unit- und Property-Tests (Hypothesis) grün |
| **3 – Admin-UI** (≈ 1–1,5 Wochen) | Admin-API + SPA: Einstellungen, Live-Ansicht, Moderation, QR/PDF | Bedienung im Devcontainer mit Fake |
| **4 – Integration & Gastzugang** (≈ 1,5 Wochen) | Discovery, Config-Flow, Webhook/Cloudhook-Lebenszyklus, Rotation, POST-Aktions-Proxy, Sessions, Limits, Gast-Seite mit Long Polling und Rückfall, Entitäten | Gast-Flow Ende-zu-Ende über die lokale Webhook-URL; Cloudhook-Pfad mit gemocktem `cloud`-Modul getestet |
| **5 – Härtung** (≈ 1 Woche) | Security-Review, CSP-Hashes im Build, AppArmor, Fuzzing, Audits, Docs DE/EN | Checkliste aus Abschnitt 6 abgehakt und mit Tests belegt |
| **6 – Release v0.1** | HACS + App-Repository, Changelog | Installierbar. Erst danach Echttest mit Sonos und Nabu Casa (nicht Teil dieses Plans). |

Grob 6–8 Wochen bei einer Person in Teilzeit, als Orientierung.

---

## 9. Teststrategie (ohne echtes System)

- **FakeSonosAdapter:** In-Memory-Lautsprecher mit Queue, Transport-State und simulierter Zeit; Apple-Music-artige Suchergebnisse aus Fixtures (Felder wie `MusicServiceBrowseItem`)
- **Unit:** Ranking, Budget-Fenster, Limits, Zustandsautomat, Lookahead/Fixierung, `manual_override`
- **Vertrags-Tests:** dieselbe Suite gegen den Fake und gegen `SoCoAdapter` mit gemockten SoCo-Objekten
- **API:** FastAPI `TestClient` für Admin-API (Ingress-Guard) und Gast-API (Secret, Limits, Body-Größe, unbekannte Aktionen)
- **Long Polling:** sofortige Antwort bei neuerer Version, Aufwachen bei Änderung, Timeout-Antwort, Ersetzen eines offenen `wait` derselben Session, globale Obergrenze. Im Frontend (Playwright mit simulierten Fehlern/Timeouts): Verkürzen der Wartezeit, Wechsel zu Polling, Rückkehr zu Long Polling, Pause im Hintergrund.
- **Integration:** `pytest-homeassistant-custom-component`: Config-Flow, Discovery, Webhook mit GET/POST, Cloudhook-Erzeugung und -Rotation (gemocktes `cloud`). Zusätzlich ein Test, der eine Antwort durch `serialize_response` schickt, damit nur Text und `Content-Type` verwendet werden, also exakt das Relay-Verhalten.
- **E2E:** Playwright mit mobilen Viewports gegen App (Fake) + Integration im Devcontainer
- **Security:** Fuzzing der POST-Aktionen (Schemathesis/Hypothesis), XSS-Payloads in Spitzname und Suche, URI-Injection, Rotation, Join-Flut
- **Last:** Locust mit ca. 100 simulierten Gästen, davon alle mit offenem Long-Poll

---

## 10. Risiken und offene Punkte

| Risiko | Gegenmaßnahme |
|---|---|
| Undokumentierte Cloudhook-Limits (Größe, Rate, Timeout) | Kleine Antworten, einstellbare Long-Poll-Dauer mit automatischem Rückfall auf Polling, früh im Echttest messen |
| Unbekannt: maximale Haltezeit und Zahl gleichzeitig offener Cloudhook-Anfragen am Nabu-Casa-Relay | Beim ersten Echttest messen (Wartezeit stufenweise 10/20/30 s, 50–100 parallele Gäste) und den Standardwert danach festlegen |
| Kein Nabu Casa oder Cloud getrennt | Status in der Admin-UI, Fallback auf lokale Webhook-URL (nur WLAN) |
| Fork-Stabilität | Auf Commit pinnen, alle SoCo-Aufrufe im Adapter kapseln |
| Ablaufende Track-URIs | Erst beim Einreihen auflösen |
| Explicit-Flag bei Apple Music unklar | Filter nur aktiv, wenn die Metadaten das Feld liefern; sonst in der UI ausgegraut |
| Parallelbedienung über die Sonos-App | `manual_override` statt Kampf um die Queue |
| S1/S2, mehrere Haushalte | MVP: ein Haushalt, S2 |
| Zwei Installationsschritte (App + HACS-Integration) | Klare Docs, Status „Integration nicht verbunden“ in der Admin-UI |

### Backlog (nach MVP)

Party-Display-Modus (TV/Tablet), Fairness-Bonus im Ranking, UPnP-Events statt Polling (Sonos-Seite), echtes Push über einen externen Dienst (z. B. ntfy/Ably, nur Versionssignale, falls Long Polling nicht reicht), weitere Musikdienste, Statistik nach der Party.

---

### Quellen

- HA Core: `homeassistant/components/cloud/client.py` (`async_webhook_message`), `homeassistant/components/webhook/__init__.py` (`SUPPORTED_METHODS`, `allowed_methods`), `homeassistant/util/aiohttp.py` (`serialize_response`)
- [Nabu Casa – Webhooks](https://www.nabucasa.com/config/webhooks/)
- hass-nabucasa: `hass_nabucasa/iot.py` (Webhook-Handler, ein Task pro Nachricht)
- SoCo-Fork `BookCatKid/SoCo-music-services-and-more@music-services`, `soco/music_services/browser/VERIFIED.md`
