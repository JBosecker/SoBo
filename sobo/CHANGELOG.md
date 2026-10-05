# Changelog

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
