# SoBo (Deutsch)

SoBo macht dein Sonos-System zur Party-Jukebox – als Home Assistant App
(ehemals Add-on) mit passender Integration. Gäste scannen einen QR-Code,
suchen Songs in Apple Music, schlagen sie vor und stimmen ab. Die Warteschlange
sortiert sich nach Stimmen; du steuerst alles über die SoBo-Seite in Home Assistant.

Admin-Oberfläche und Gast-Seite erscheinen automatisch auf Deutsch, wenn Browser
bzw. Handy auf Deutsch eingestellt sind; sonst auf Englisch.

## Einrichtung

Voraussetzungen: Home Assistant OS oder Supervised, ein Sonos-System mit Apple-Music-Konto
und für Gäste außerhalb deines WLANs Home Assistant Cloud (Nabu Casa).

1. App: dieses Repository im App-Store hinzufügen (`https://github.com/JBosecker/SoBo`)
   und **SoBo** installieren und starten.
2. Integration: in HACS `https://github.com/JBosecker/SoBo` als benutzerdefiniertes
   Repository (Kategorie *Integration*) hinzufügen, **SoBo** installieren, Home Assistant
   neu starten und die gefundene SoBo-Integration unter Einstellungen → Geräte & Dienste
   bestätigen.
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
  Basis-Playlist (eine Playlist aus der Apple-Music-Mediathek dieses Kontos), Stimmen,
  Regeln für Wünsche, Zeitfenster.
- **Protokoll:** Wer hat wann was geändert.

Der nächste Song wird erst kurz vor dem Ende des laufenden festgelegt (standardmäßig
30 Sekunden, **Einstellungen → Stimmen**). Bis dahin können Gäste noch abstimmen und
den nächsten Song beeinflussen.

Nach den Wünschen zeigt die Warteschlange die Songs der Basis-Playlist in der Reihenfolge,
in der sie laufen werden (standardmäßig alle; **Einstellungen → Musik → Songs der
Basis-Playlist in der Warteschlange** begrenzt die Anzahl). Gäste können auch für sie
stimmen; eine Stimme macht den Song zu einem normalen Wunsch.

Wünscht sich jemand einen Song, der schon in der Basis-Playlist ist, rückt dieser nach
oben (SoBo erkennt gleichen Interpreten und Titel) und erscheint nicht doppelt.

Wird die Jukebox ausgeschaltet (oder endet ihr Zeitfenster), stoppt die Musik; der
gestoppte Song gilt als gespielt. Musik, die in der Sonos-App gestartet wurde, bleibt
unberührt. Die Lautsprecher, die SoBo gruppiert hat, werden wieder getrennt, und die
Gästeliste wird geleert: Gäste treten bei der nächsten Party neu bei. Wartende Wünsche
bleiben in der Warteschlange.

## Sicherheit

Die Admin-Oberfläche ist nur über Home Assistant (Ingress) erreichbar. Gäste
erreichen ausschließlich die Jukebox-Funktionen über eine Nabu-Casa-Cloudhook-URL,
die keine Rückschlüsse auf deine Home-Assistant-Adresse zulässt.

Technische Details (auf Englisch): [README.md](README.md), [sobo/DOCS.md](sobo/DOCS.md),
Sicherheits-Checkliste: [docs/SECURITY.md](docs/SECURITY.md).
