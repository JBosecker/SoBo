# Changelog

## 0.2.5

- Fix: votes sometimes vanished from the guest page for a moment and came back later.
  Answers from SoBo can arrive out of order (through the Nabu Casa relay, or when a
  regular update overlaps a vote), and the page showed whichever came last, even an
  older state. The guest page and the admin UI now ignore states older than the one
  they show.
- Fix: after a restart of the app, open guest pages could stay on the old state until
  the guest did something. The page now notices the restart and updates right away.

## 0.2.4

- Fix: on a tie in votes the queue order now follows who got there first. A song that
  reached its vote count earlier stays ahead of one that only caught up later, even if
  the latter was requested earlier. Before, only the time of the request counted, so a
  song could jump ahead with a vote that came after the other song's vote.

## 0.2.3

- Fix: a vote in the last seconds of a song could stop the music, with the voted song
  stuck as "next". Once the next song is fixed (setting **Votes → Fix the next song this
  many seconds before the end**), votes and new requests no longer change it, not even
  when it comes from the base playlist; they count for the song after. If Sonos stops
  at the end of a song anyway, SoBo starts the next one itself.
- Fix: requesting a song that is also in the base playlist showed it twice. SoBo now
  recognises the same song (same artist and title) even though Apple Music uses other
  IDs in the library than in the search: the request moves the song up instead, and
  the base playlist does not play it again later in that round.
- Switching the jukebox off now resets it as if freshly started: the speaker group
  SoBo formed is dissolved, the guest list is emptied (all guest sessions end; guests
  join again for the next party), waiting requests are removed, a frozen queue is
  released and the base playlist is planned anew.
- Guest page: "Your request" and "Pinned by the host" moved to a small line below the
  artist. The song that is fixed to play next is the first, highlighted row of the queue
  ("Up next", no voting), instead of a line below the current song.
- Admin UI: the fixed next song is also the first, highlighted row of the queue.

## 0.2.2

- The queue shows all songs of the base playlist after the requests, no longer only
  the next five. New setting **Music → Base playlist songs shown in the queue**
  (0 = all, the default).
- Switching the jukebox off (or the end of its time window) now stops the music. The
  stopped song counts as played; switching on again continues with the next song.
  Music someone started in the Sonos app is left alone.
- Guest page: queue rows look like a music app list (cover, title, artist below).
  Each row has a vote button "▲ votes" on the right, a hint explains it, and the
  requests and the songs from the party playlist are shown as two sections.
- Admin UI: the queue uses the same rows (cover, title, artist, request details) with
  the votes as "▲ count" next to Pin and Remove; the base playlist songs follow in their
  own section with their number.

## 0.2.1

- The queue shows what the base playlist will play after the requests (next five
  songs, marked "From the party playlist" on the guest page and "From the base
  playlist" in the admin UI).
- Guests can vote for these songs too. A vote turns the song into a regular request
  (it costs a vote like any other), so it moves up with the other requests. The admin
  UI marks it "From the base playlist, voted up by guests".

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
