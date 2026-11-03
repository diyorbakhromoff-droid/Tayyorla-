"""Tayyorla logotipi: ikat naqshli «T» — sovg'a qutisining qopqog'i (ko'ndalang) va lentasi (tik)."""
from pathlib import Path
OUT = Path("/home/user/tayyorla/static/brand")
NIGHT, ATLAS, SAFFRON, PAPER, WHITE = "#211C52", "#D02670", "#F5B20A", "#F7F5FC", "#FFFFFF"

def ikat(cx, cy, s=1.0):
    """Ikat olmos: tishli tashqi (za'faron), ichki (tun), markaz (oq)."""
    def pts(r, k):  # tishli olmos: r — yarim balandlik, k — kenglik nisbati
        h, w = r, r * k
        return [(0, -h), (w * .38, -h * .55), (w * .22, -h * .45), (w, 0), (w * .22, h * .45), (w * .38, h * .55),
                (0, h), (-w * .38, h * .55), (-w * .22, h * .45), (-w, 0), (-w * .22, -h * .45), (-w * .38, -h * .55)]
    def poly(p, fill):
        d = " ".join(f"{cx + x * s:.2f},{cy + y * s:.2f}" for x, y in p)
        return f'<polygon points="{d}" fill="{fill}"/>'
    inner = [(0, -6.5), (3.4, 0), (0, 6.5), (-3.4, 0)]
    core = [(0, -2.6), (1.4, 0), (0, 2.6), (-1.4, 0)]
    return poly(pts(11.5, .62), SAFFRON) + poly(inner, NIGHT) + poly(core, PAPER)

def mark(x0=0, y0=0, sc=1.0, light=False):
    """200x200 koordinatada belgi (fon yo'q). light — oq fon uchun (quti chegarali)."""
    g = []
    # quti tanasi
    edge = ' stroke="#D9D2EC" stroke-width="2.5"' if light else ""
    g.append(f'<rect x="52" y="96" width="96" height="76" rx="9" fill="{PAPER}"{edge}/>')
    g.append(f'<rect x="52" y="96" width="96" height="9" fill="#E4DFF2"/>')
    # T: ikat qopqoq (ko'ndalang) + ikat lenta (tik)
    g.append(f'<rect x="36" y="68" width="128" height="34" rx="9" fill="{ATLAS}"/>')
    g.append(f'<rect x="85" y="98" width="30" height="74" fill="{ATLAS}"/>')
    for x in (60, 140):
        g.append(ikat(x, 85, 1.2))
    for y in (122, 153):
        g.append(ikat(100, y, 1.2))
    # bant (za'faron), tugun (pushti)
    g.append(f'<path d="M100 70 C 78 40, 52 50, 64 66 C 72 76, 90 74, 100 70 Z" fill="{SAFFRON}"/>')
    g.append(f'<path d="M100 70 C 122 40, 148 50, 136 66 C 128 76, 110 74, 100 70 Z" fill="{SAFFRON}"/>')
    g.append(f'<path d="M100 70 C 86 54, 72 57, 76 66 Z M100 70 C 114 54, 128 57, 124 66 Z" fill="#E09A00"/>')
    g.append(f'<circle cx="100" cy="70" r="8.5" fill="{ATLAS}"/><circle cx="100" cy="70" r="3.2" fill="{SAFFRON}"/>')
    return f'<g transform="translate({x0} {y0}) scale({sc})">' + "".join(g) + "</g>"

def svg(w, h, body, bg=None):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            + (bg or "") + body + "</svg>")

# 1) belgi (shaffof)
(OUT / "tayyorla-mark.svg").write_text(svg(200, 200, mark()))
(OUT / "tayyorla-mark-light.svg").write_text(svg(200, 200, mark(light=True)))
# 2) avatar: tungi indigo, yumshoq nur, markazda belgi (aylana kesimga xavfsiz)
bg = (f'<defs><radialGradient id="g" cx="50%" cy="42%" r="62%"><stop offset="0" stop-color="#3A3290"/>'
      f'<stop offset="1" stop-color="{NIGHT}"/></radialGradient></defs><rect width="640" height="640" fill="url(#g)"/>'
      + "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}" opacity="{o}"/>' for x, y, r, c, o in
                [(176, 196, 7, SAFFRON, .9), (470, 168, 5, PAPER, .8), (500, 300, 4, SAFFRON, .7), (150, 330, 4, PAPER, .6),
                 (430, 120, 3, ATLAS, .9), (214, 120, 3, PAPER, .5)]))
(OUT / "tayyorla-avatar.svg").write_text(svg(640, 640, mark(60, 39, 2.6), bg))
print("ok")
