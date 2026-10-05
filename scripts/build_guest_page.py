#!/usr/bin/env python3
"""Baut die Gast-Seite zu EINER Datei mit Inline-CSS/JS und CSP-Hashes (Plan 4.4).

python scripts/build_guest_page.py           # schreibt custom_components/sobo/guest_page.html
python scripts/build_guest_page.py --check   # CI: bricht ab, wenn die Datei veraltet ist
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "guest"
OUT = ROOT / "custom_components" / "sobo" / "guest_page.html"
MAX_BYTES = 50 * 1024


def sha256(text: str) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode()


def build() -> str:
    template = (SRC / "index.html").read_text(encoding="utf-8")
    style = (SRC / "style.css").read_text(encoding="utf-8").strip()
    script = (SRC / "app.js").read_text(encoding="utf-8").strip()
    for marker in ("{{CSP}}", "{{STYLE}}", "{{SCRIPT}}"):
        if template.count(marker) != 1:
            raise SystemExit(f"Platzhalter {marker} muss genau einmal vorkommen")
    if "</script" in script.lower() or "</style" in style.lower():
        raise SystemExit("Schließendes Tag im Inline-Inhalt")
    csp = "; ".join(
        [
            "default-src 'none'",
            f"script-src '{sha256(script)}'",
            f"style-src '{sha256(style)}'",
            "img-src https:",
            "connect-src 'self'",
            "form-action 'none'",
            "base-uri 'none'",
        ]
    )
    page = (
        template.replace("{{CSP}}", csp).replace("{{STYLE}}", style).replace("{{SCRIPT}}", script)
    )
    size = len(page.encode("utf-8"))
    if size > MAX_BYTES:
        raise SystemExit(f"Gast-Seite ist {size} Bytes groß (Ziel < {MAX_BYTES})")
    return page


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="nur prüfen, nicht schreiben")
    args = parser.parse_args()
    page = build()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != page:
            print(
                "guest_page.html ist veraltet: python scripts/build_guest_page.py", file=sys.stderr
            )
            return 1
        print(f"guest_page.html aktuell ({len(page.encode())} Bytes)")
        return 0
    OUT.write_text(page, encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)} geschrieben ({len(page.encode())} Bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
