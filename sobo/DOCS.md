# SoBo

SoBo macht dein Sonos-System zur Party-Jukebox.

## Einrichtung

1. App installieren und starten.
2. Die SoBo-Integration über HACS installieren (für den Gastzugang per QR-Code).
3. In der Seitenleiste **SoBo** öffnen, Lautsprecher, Apple-Music-Konto und
   Basis-Playlist wählen und die Jukebox einschalten.

## Optionen

| Option | Bedeutung |
|---|---|
| `log_level` | Ausführlichkeit der Protokollierung |
| `fake_sonos` | Nur für Entwicklung: simulierter Lautsprecher statt echter Geräte |

## Sicherheit

Die Admin-Oberfläche ist nur über Home Assistant (Ingress) erreichbar. Gäste
erreichen ausschließlich die Jukebox-Funktionen über eine Nabu-Casa-Cloudhook-URL,
die keine Rückschlüsse auf deine Home-Assistant-Adresse zulässt.
