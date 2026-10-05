#!/usr/bin/env python3
"""Builds the guest page into ONE file with inline CSS/JS and CSP hashes (plan 4.4).

python scripts/build_guest_page.py           # writes custom_components/sobo/guest_page.html
python scripts/build_guest_page.py --check   # CI: fails if the file is out of date
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
            raise SystemExit(f"Placeholder {marker} must occur exactly once")
    if "</script" in script.lower() or "</style" in style.lower():
        raise SystemExit("Closing tag inside inline content")
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
        raise SystemExit(f"Guest page is {size} bytes (target < {MAX_BYTES})")
    return page


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="only check, do not write")
    args = parser.parse_args()
    page = build()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != page:
            print(
                "guest_page.html is out of date: python scripts/build_guest_page.py",
                file=sys.stderr,
            )
            return 1
        print(f"guest_page.html is up to date ({len(page.encode())} bytes)")
        return 0
    OUT.write_text(page, encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)} written ({len(page.encode())} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
