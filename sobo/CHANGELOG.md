# Changelog

## 0.2.0

- The next song is no longer fixed as soon as the current one starts. It stays in the
  queue, guests can keep voting, and SoBo fixes the leading request only shortly before
  the end (new setting **Votes → Fix the next song this many seconds before the end**,
  default 30 s). Skipping fixes the next song right away.
- The admin UI explains that the next song is still open.
- Base playlist: choose one of the playlists in the Apple Music library of the selected
  account (instead of Sonos playlists and favourites). The list updates when you pick
  another account. Base playlists chosen earlier keep working.

## 0.1.3

- Fix: Apple Music search failed with `AuthTokenExpired` for accounts stored without an
  account UID (`…-0-Token`). SoBo now talks to Apple Music under the plain household
  identity for such accounts, which Apple accepts (search, track details, playback
  resolution).
- `scripts/diagnose_apple_music.py` checks the Apple Music sign-in against a real
  household without playing anything.

## 0.1.2

- Searching failed with `AuthTokenExpired` when the Apple Music sign-in SoBo had read
  from the Sonos system was outdated. SoBo now reads the sign-in again and retries
  once; the Sonos players refresh it on their own.
- If Apple Music still rejects the sign-in, the admin UI shows a banner explaining how
  to sign in again in the Sonos app, and the log describes the stored sign-in (without
  secrets).

## 0.1.1

- Fix: the Apple Music account was not offered ("Sonos is not responding right now").
  Sonos sends the account list encrypted; the image now contains the `cryptography`
  package needed to read it.
- The admin UI shows the reason when Sonos lists cannot be loaded, and the app log
  records it.

## 0.1.0

First release.

- Party jukebox for Sonos: guests scan a QR code, search Apple Music, suggest songs
  and vote; the queue is sorted by votes, a base playlist fills the gaps
- Admin UI in Home Assistant (ingress): live view with moderation (pin, remove,
  block guests, skip, freeze), guest access with QR code and print view, settings
  (speaker, maximum volume, account, base playlist, votes, rules, time window), log
- Guest access through the SoBo integration (HACS) via a Nabu Casa cloudhook that
  reveals nothing about your Home Assistant address; live updates by long polling
- Entities: jukebox switch, now playing, queue length, active guests, guest URL,
  skip and renew-guest-access buttons
- English and German user interface (follows the browser or phone language)
- Hardening: AppArmor profile, CSRF protection of the admin API, rate limits,
  fuzzing and load tests; images signed with Cosign
