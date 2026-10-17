#!/usr/bin/env python3
"""Builds the guest page and the party display page, each into ONE file with inline
CSS/JS and CSP hashes (plan 4.4).

python scripts/build_guest_page.py           # writes custom_components/sobo/*_page.html
python scripts/build_guest_page.py --check   # CI: fails if a file is out of date
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "custom_components" / "sobo"
# source folder under frontend/ → output file
PAGES = {"guest": "guest_page.html", "display": "display_page.html"}
MAX_BYTES = 50 * 1024


def sha256(text: str) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode()


def build(name: str) -> str:
    src = ROOT / "frontend" / name
    template = (src / "index.html").read_text(encoding="utf-8")
    style = (src / "style.css").read_text(encoding="utf-8").strip()
    script = (src / "app.js").read_text(encoding="utf-8").strip()
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
        raise SystemExit(f"{name} page is {size} bytes (target < {MAX_BYTES})")
    return page


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="only check, do not write")
    args = parser.parse_args()
    failed = False
    for name, filename in PAGES.items():
        out = OUT_DIR / filename
        page = build(name)
        size = len(page.encode())
        if args.check:
            current = out.read_text(encoding="utf-8") if out.exists() else ""
            if current != page:
                print(
                    f"{filename} is out of date: python scripts/build_guest_page.py",
                    file=sys.stderr,
                )
                failed = True
            else:
                print(f"{filename} is up to date ({size} bytes)")
            continue
        out.write_text(page, encoding="utf-8")
        print(f"{out.relative_to(ROOT)} written ({size} bytes)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
