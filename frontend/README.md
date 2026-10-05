# Frontend

- `guest/` – Gast-Seite (HTML, CSS, JS ohne Framework). `scripts/build_guest_page.py`
  fügt sie zu **einer** Datei mit CSP-Hashes zusammen:
  `custom_components/sobo/guest_page.html`. Nach Änderungen neu bauen; die CI prüft das.
- `admin/` – Admin-SPA für Ingress (Phase 3). Bis dahin liefert die App eine
  einfache Statusseite (`sobo/backend/src/sobo/static/admin.html`).
