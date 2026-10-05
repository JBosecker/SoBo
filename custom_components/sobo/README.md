# SoBo-Integration (Phase 4)

Registriert Webhook und Cloudhook als öffentlichen Gast-Einstieg und leitet
Gast-Aktionen an die App weiter (`POST http://127.0.0.1:8738/internal/guest`,
Header `X-SoBo-Secret`). Kopplung per Supervisor-Discovery (`service: sobo`).
