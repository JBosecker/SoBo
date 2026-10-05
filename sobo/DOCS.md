# SoBo

SoBo macht dein Sonos-System zur Party-Jukebox.

## Einrichtung

1. App installieren und starten.
2. Die SoBo-Integration über HACS installieren (für den Gastzugang per QR-Code).
3. In der Seitenleiste **SoBo** öffnen, Lautsprecher, Apple-Music-Konto und
   Basis-Playlist wählen und die Jukebox einschalten.

## Bedienung

- **Live:** Was läuft, was als Nächstes kommt, die Warteschlange mit Stimmen und die
  Gäste. Songs lassen sich anpinnen oder entfernen, Gäste sperren, die Warteschlange
  anhalten. Wird in der Sonos-App etwas anderes gestartet, wartet SoBo, bis du
  „Wieder übernehmen“ wählst.
- **Gastzugang:** QR-Code zum Aushängen (über „QR-Code drucken“ als A4-Blatt oder PDF),
  Link kopieren, Gastzugang erneuern. Nach dem Erneuern funktionieren alte QR-Codes nicht mehr.
- **Einstellungen:** Lautsprecher und Höchstlautstärke, Apple-Music-Konto,
  Basis-Playlist, Stimmen, Regeln für Wünsche, Zeitfenster.
- **Protokoll:** Wer hat wann was geändert.

## Optionen

| Option | Bedeutung |
|---|---|
| `log_level` | Ausführlichkeit der Protokollierung |
| `fake_sonos` | Nur für Entwicklung: simulierter Lautsprecher statt echter Geräte |

## Sicherheit

Die Admin-Oberfläche ist nur über Home Assistant (Ingress) erreichbar. Gäste
erreichen ausschließlich die Jukebox-Funktionen über eine Nabu-Casa-Cloudhook-URL,
die keine Rückschlüsse auf deine Home-Assistant-Adresse zulässt.
