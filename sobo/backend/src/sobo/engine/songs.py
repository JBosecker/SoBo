"""Recognise the same song across sources (plan 5.1, changed after the real test).

Apple Music library playlists and the catalog search return different IDs for the
same song, so SoBo also compares a normalised "artist | title" key: a request for a
song that is in the base playlist is the same song, not an extra one.
"""

from __future__ import annotations

import re
import unicodedata

from ..sonos.adapter import Track

# "Song (feat. X)", "Song [Live]", "Song - Remastered 2011"
_BRACKETS = re.compile(r"[\(\[][^\)\]]*[\)\]]")
_SUFFIX = re.compile(r"\s+[-–]\s+.*$")
# "A & B", "A, B", "A feat. B", "A ft. B", "A with B"
_MORE_ARTISTS = re.compile(r"(?:\s*[,&]|\s+(?:feat\.?|ft\.?|with|x)\s).*$", re.IGNORECASE)


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if c.isalnum())


def song_key(track: Track) -> str:
    """Normalised key of the song: same artist and title → same key."""
    title = _SUFFIX.sub("", _BRACKETS.sub("", track.title))
    artist = _MORE_ARTISTS.sub("", track.artist)
    return f"{_plain(artist) or _plain(track.artist)}|{_plain(title) or _plain(track.title)}"
