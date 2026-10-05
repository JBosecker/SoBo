"""Gast-Session-Token: zufällig, nur gehasht gespeichert (Plan 3.2, 6)."""

from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata

TOKEN_BYTES = 32
NICKNAME_MAX = 24


def new_session_token() -> tuple[str, str]:
    """Gibt (Token für den Gast, Hash für die Datenbank) zurück."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


_WHITESPACE = re.compile(r"\s+")


def clean_nickname(raw: str) -> str | None:
    """Filtert Steuer-/Formatzeichen (u. a. Bidi-Overrides), normalisiert Leerraum,
    begrenzt die Länge. Gibt None zurück, wenn nichts Sinnvolles übrig bleibt."""
    text = unicodedata.normalize("NFKC", raw)
    text = "".join(ch for ch in text if not unicodedata.category(ch).startswith("C"))
    text = _WHITESPACE.sub(" ", text).strip()
    text = text[:NICKNAME_MAX].strip()
    if not text or not any(ch.isalnum() for ch in text):
        return None
    return text
