# Changelog

## 0.1.0-dev

- App skeleton (ingress, discovery, configuration)
- Sonos adapter (SoCo fork) and simulation
- Jukebox engine: queue, upvotes, budgets, limits, base playlist, states
- Guest page with live updates; guest access via the SoBo integration (Nabu Casa cloudhook)
- Admin UI: live view with moderation, guest access with QR code and print view,
  settings, log
- English as the main language; German localization of the admin UI, guest page,
  "jukebox is off" page, integration and app options
- Hardening: AppArmor profile, CSRF protection of the admin API, fuzzing and load tests,
  security checklist (docs/SECURITY.md)
