"""Erfundener Apple-Music-artiger Katalog für den Fake-Adapter (Plan 9)."""

from __future__ import annotations

from .adapter import Track

FAKE_ACCOUNT_ID = "fake-apple-1"

_RAW: list[tuple[str, str, str, int, bool | None]] = [
    ("Neon Harbor", "The Midnight Ferries", "Lanterns", 214, False),
    ("Paper Satellites", "The Midnight Ferries", "Lanterns", 198, False),
    ("Salt & Static", "Ivy Calloway", "Low Tide", 241, False),
    ("Copper Sky", "Ivy Calloway", "Low Tide", 187, None),
    ("Dancefloor Cartography", "Disco Atlas", "Maps for Feet", 305, False),
    ("Mirrorball Weather", "Disco Atlas", "Maps for Feet", 276, False),
    ("Basement Constellations", "Disco Atlas", "Maps for Feet", 259, True),
    ("Velvet Engine", "Koto Fuzz", "Overdrive Garden", 222, False),
    ("Garden of Amps", "Koto Fuzz", "Overdrive Garden", 189, True),
    ("Slow Comet", "Mira Okonkwo", "Orbit Songs", 263, False),
    ("Gravity Lessons", "Mira Okonkwo", "Orbit Songs", 231, False),
    ("Sunday Static", "Bruno Kessel", "Radio Kessel", 176, False),
    ("Autobahn Lullaby", "Bruno Kessel", "Radio Kessel", 402, False),
    ("Lemonade Protocol", "The Citrus Union", "Pulp", 193, False),
    ("Zest Mode", "The Citrus Union", "Pulp", 167, None),
    ("Thunder in a Teacup", "Hollis & Wren", "Small Storms", 244, False),
    ("Rain Check Waltz", "Hollis & Wren", "Small Storms", 209, False),
    ("Electric Grandma", "Synthia Park", "Family Circuits", 228, False),
    ("Robot Picnic", "Synthia Park", "Family Circuits", 201, False),
    ("Bassline Diplomacy", "DJ Konsul", "Embassy Nights", 356, True),
    ("Visa for the Weekend", "DJ Konsul", "Embassy Nights", 318, False),
    ("Fog Machine Romance", "Lea Marchetti", "Smoke & Glitter", 237, False),
    ("Glitter Tax", "Lea Marchetti", "Smoke & Glitter", 205, False),
    ("Kilometer Zero", "Nordlicht Express", "Fahrplan", 262, False),
    ("Last Train Funk", "Nordlicht Express", "Fahrplan", 289, False),
    ("Cactus Disco", "Los Pinchos", "Desierto Brillante", 211, False),
    ("Tumbleweed Two-Step", "Los Pinchos", "Desierto Brillante", 184, False),
    ("Marble Hallways", "Quiet Architects", "Floorplans", 297, False),
    ("Blueprint Heart", "Quiet Architects", "Floorplans", 246, False),
    ("Wiggle Theory", "Professor Groove", "Applied Funk", 233, False),
    ("Hypothesis of Hips", "Professor Groove", "Applied Funk", 219, False),
    ("Moonlight Spreadsheet", "Office Party", "Q4 Feelings", 188, False),
    ("Overtime Anthem", "Office Party", "Q4 Feelings", 205, True),
    ("Ten Minute Epic", "Long Players", "Side B", 612, False),
]


def fake_catalog() -> list[Track]:
    tracks: list[Track] = []
    for n, (title, artist, album, duration, explicit) in enumerate(_RAW, start=1):
        tracks.append(
            Track(
                item_id=f"song:{1_000_000 + n}",
                title=title,
                artist=artist,
                album=album,
                art_url=f"https://example.invalid/cover/{n}/300x300.jpg",
                duration=duration,
                explicit=explicit,
                account_id=FAKE_ACCOUNT_ID,
            )
        )
    return tracks
