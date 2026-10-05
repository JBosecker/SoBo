"""Guest session tokens: random, stored only as a hash (plan 3.2, 6)."""

from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata

TOKEN_BYTES = 32
NICKNAME_MAX = 24


def new_session_token() -> tuple[str, str]:
    """Return (token for the guest, hash for the database)."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


_WHITESPACE = re.compile(r"\s+")


def clean_nickname(raw: str) -> str | None:
    """Strip control/format characters (incl. bidi overrides), normalise whitespace
    and limit the length. Returns None if nothing meaningful is left."""
    text = unicodedata.normalize("NFKC", raw)
    text = "".join(ch for ch in text if not unicodedata.category(ch).startswith("C"))
    text = _WHITESPACE.sub(" ", text).strip()
    text = text[:NICKNAME_MAX].strip()
    if not text or not any(ch.isalnum() for ch in text):
        return None
    return text
