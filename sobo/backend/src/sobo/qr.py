"""QR code as SVG for the guest access (admin UI, print view)."""

from __future__ import annotations

from functools import lru_cache

from .vendor.qrcodegen import QrCode


def qr_svg(text: str, border: int = 4) -> str:
    """Render `text` as a QR code (error correction M) into a compact SVG.

    All dark modules live in a single path; the SVG scales without blurring and
    is suitable for printing.
    """
    qr = QrCode.encode_text(text, QrCode.Ecc.MEDIUM)
    size = qr.get_size()
    parts = [
        f"M{x + border},{y + border}h1v1h-1z"
        for y in range(size)
        for x in range(size)
        if qr.get_module(x, y)
    ]
    full = size + 2 * border
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'viewBox="0 0 {full} {full}" shape-rendering="crispEdges" role="img" '
        'aria-label="QR code">'
        f'<rect width="100%" height="100%" fill="#ffffff"/>'
        f'<path d="{" ".join(parts)}" fill="#000000"/></svg>'
    )


@lru_cache(maxsize=4)
def qr_rows(text: str) -> tuple[str, ...]:
    """The modules of the QR code as rows of "1" (dark) and "0" (light), without border.

    For the party display, which draws the code itself: images other than https:
    are not allowed by its CSP, and binary data does not pass the relay.
    """
    qr = QrCode.encode_text(text, QrCode.Ecc.MEDIUM)
    size = qr.get_size()
    return tuple(
        "".join("1" if qr.get_module(x, y) else "0" for x in range(size)) for y in range(size)
    )
