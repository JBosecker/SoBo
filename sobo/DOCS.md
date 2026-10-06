# SoBo

SoBo turns your Sonos system into a party jukebox.

The admin UI and the guest page are available in English and German; they follow
the language of the browser or phone.

## Setup

1. Install and start the app.
2. Install the SoBo integration via HACS (custom repository
   `https://github.com/JBosecker/SoBo`, category *Integration*) and restart Home
   Assistant. The app announces itself: confirm the discovered SoBo under
   Settings → Devices & services. It provides guest access via QR code.
3. Open **SoBo** in the sidebar, choose the speaker, the Apple Music account and a
   base playlist, then turn the jukebox on.

## Usage

- **Live:** what is playing, what comes next, the queue with votes and the guests.
  Songs can be pinned or removed, guests blocked and the queue frozen. If something
  else is started in the Sonos app, SoBo waits until you choose "Take over again".
- **Guest access:** a QR code to put up (use "Print QR code" for an A4 sheet or a PDF),
  copy the link, renew guest access. After renewing, old QR codes stop working.
- **Settings:** speaker and maximum volume, Apple Music account, base playlist (a
  playlist from that account's Apple Music library), votes, rules for requests, time
  window.
- **Log:** who changed what and when.

The next song is fixed only shortly before the current one ends (30 seconds by default,
**Settings → Votes**). Until then guests can still vote, and the leading request moves
up; once fixed, it is handed to Sonos so the transition is seamless.

After the requests, the queue shows the songs of the base playlist in the order they
will play (all of them by default; **Settings → Music → Base playlist songs shown in the
queue** limits the number). Guests can vote for them too: a vote turns the song into a
regular request.

Turning the jukebox off (or the end of its time window) stops the music; the stopped
song counts as played. Music started in the Sonos app is left alone.

## Options

| Option | Meaning |
|---|---|
| `log_level` | How verbose the log output is |
| `fake_sonos` | Development only: a simulated speaker instead of real devices |

## Security

The admin UI is only reachable through Home Assistant (ingress). Guests can only
reach the jukebox functions through a Nabu Casa cloudhook URL that reveals nothing
about your Home Assistant address.
