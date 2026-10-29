"""QR-kodni SVG yo'li (path) ko'rinishida yasash: video kartochkasi va tadbir sahifasi uchun."""

from functools import lru_cache

import segno


@lru_cache(maxsize=512)
def qr_path(text: str) -> dict:
    """{"n": modullar soni, "d": SVG path} — viewBox="0 0 n n" ichida qora kvadratchalar."""
    qr = segno.make(text or " ", error="m", micro=False)
    rows = [list(r) for r in qr.matrix]
    parts = []
    for y, row in enumerate(rows):
        x = 0
        while x < len(row):
            if row[x]:
                start = x
                while x < len(row) and row[x]:
                    x += 1
                parts.append(f"M{start} {y}h{x - start}v1h-{x - start}z")
            else:
                x += 1
    return {"n": len(rows), "d": "".join(parts)}


def qr_svg(text: str, color: str = "#1C1830", size: int = 160) -> str:
    q = qr_path(text)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {q["n"]} {q["n"]}" '
            f'shape-rendering="crispEdges" role="img" aria-label="QR"><path fill="{color}" d="{q["d"]}"/></svg>')
