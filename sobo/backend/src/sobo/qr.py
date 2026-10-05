"""QR-Code als SVG für den Gastzugang (Admin-UI, Druckansicht)."""

from __future__ import annotations

from .vendor.qrcodegen import QrCode


def qr_svg(text: str, border: int = 4) -> str:
    """Rendert `text` als QR-Code (Fehlerkorrektur M) in ein kompaktes SVG.

    Alle dunklen Module stecken in einem einzigen Pfad; das SVG skaliert ohne
    Unschärfe und eignet sich für den Druck.
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
        'aria-label="QR-Code">'
        f'<rect width="100%" height="100%" fill="#ffffff"/>'
        f'<path d="{" ".join(parts)}" fill="#000000"/></svg>'
    )
