"""Yangi dizaynlarni umumiy tabrik dvigateli ustiga yig'adi: python -m scripts.build_skins

Har bir dizayn catalog/skins/<id>/ papkasida: skin.json (ma'lumot va ranglar), skin.css, hero.html, skin.js.
Dvigatel (umumiy uslublar va JS) mavjud shablondan olinadi, natija catalog/namuna/<bo'lim>/<id>.html ga yoziladi
va catalog/catalog.json yangilanadi.
"""

import colorsys
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAT = ROOT / "catalog"
SKINS = CAT / "skins"
ENGINE_SRC = CAT / "namuna" / "tugilgan-kun" / "tk-tort.html"

SECTION_NAMES = {"tugilgan-kun": "Tug'ilgan kun tabrigi", "toy": "To'y taklifnomasi", "sevgi": "Sevgi izhori",
                 "farzand": "Farzand muborak", "uzr": "Uzrnoma"}
DEMO_FROM = {"tugilgan-kun": "tugilgan-kun/tk-tort.html", "toy": "toy/toy-klassik.html", "sevgi": "sevgi/sv-yulduz.html",
             "farzand": "farzand/fz-bulut.html", "uzr": "uzr/uz-kechir.html"}
BLOCKS = {
    "tugilgan-kun": ["message", "photo", "counter", "list", "gallery", "story", "scratch", "quiz", "video", "footer"],
    "toy": ["message", "place", "counter", "gallery", "program", "story", "rsvp", "scratch", "video", "footer"],
    "sevgi": ["message", "photo", "counter", "list", "gallery", "story", "scratch", "quiz", "video", "footer"],
    "farzand": ["message", "stats", "photo", "counter", "list", "gallery", "story", "scratch", "quiz", "video", "footer"],
    "uzr": ["message", "photo", "counter", "list", "gallery", "story", "scratch", "video", "footer"],
}


# ---------------------------------------------------------------- ranglar

def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _hex(c):
    return "#" + "".join(f"{round(max(0, min(1, x)) * 255):02X}" for x in c)


def mix(a, b, t):
    a, b = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * t for x, y in zip(a, b)))


def lum(h):
    def ch(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(x) for x in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def shift_l(h, d):
    r, g, b = _rgb(h)
    hh, l, s = colorsys.rgb_to_hls(r, g, b)
    return _hex(colorsys.hls_to_rgb(hh, max(0, min(1, l + d)), s))


def palette(bg, accent, accent2, extra=None):
    """Asosiy uch rangdan dvigatel kutadigan to'liq rang to'plamini hosil qiladi."""
    dark = lum(bg) < 0.18
    if dark:
        ink = mix("#FFFFFF", accent2, 0.06)
        surface = mix(bg, "#FFFFFF", 0.07)
        bg2 = mix(bg, "#FFFFFF", 0.04)
        line = mix(bg, "#FFFFFF", 0.15)
        muted = mix(ink, bg, 0.36)
    else:
        ink = mix("#17131F", accent, 0.28)
        surface = mix(bg, "#FFFFFF", 0.7)
        bg2 = mix(bg, accent, 0.08)
        line = mix(bg, accent, 0.18)
        muted = mix(ink, bg, 0.42)
    # matn uchun aksent yetarlicha ko'rinadigan bo'lsin
    acc = accent
    for _ in range(12):
        if contrast(acc, bg) >= 3.2:
            break
        acc = shift_l(acc, 0.05 if dark else -0.05)
    on = "#FFFFFF" if contrast("#FFFFFF", acc) >= contrast("#1A1420", acc) else "#1A1420"
    v = {"bg": bg, "bg2": bg2, "surface": surface, "ink": ink, "muted": muted, "accent": acc, "accent2": accent2,
         "shade": shift_l(acc, -0.18), "line": line, "on-accent": on, "fx1": acc, "fx2": accent2,
         "fx3": mix(accent2, "#FFFFFF", 0.45)}
    v.update(extra or {})
    return v


def palette_css(pals):
    out = []
    for i, p in enumerate(pals, 1):
        sel = ':root,html[data-rang="1"]' if i == 1 else f'html[data-rang="{i}"]'
        out.append(sel + "{" + ";".join(f"--{k}:{v}" for k, v in p.items()) + "}")
    return "\n".join(out)


# ---------------------------------------------------------------- dvigatel

def engine_parts():
    src = ENGINE_SRC.read_text(encoding="utf-8")
    css = src[src.index("<style>") + len("<style>"):src.index("/* ===== ranglar ===== */")]
    scripts = re.findall(r"<script>(.*?)</script>", src, re.S)
    js = next(s for s in scripts if "var META = window.SKIN_META" in s)
    # premium dizaynlar: standart tarif tanlanmaydi
    anchor = "if (META.vipOnly) SEL = 3;"
    assert anchor in js
    js = js.replace(anchor, anchor + " if (META.minSel && SEL < META.minSel) SEL = META.minSel;", 1)
    return css, js


def demo_config(section, override):
    src = (CAT / "namuna" / DEMO_FROM[section]).read_text(encoding="utf-8")
    m = re.search(r'<script id="site-config" type="application/json">(.*?)</script>', src, re.S)
    cfg = json.loads(m.group(1))
    cfg.update({"tarif": "premium", "rang": 1, "demo": True})
    cfg.update(override or {})
    return cfg


def build(skin_dir: Path, css_base: str, js_engine: str) -> dict:
    meta = json.loads((skin_dir / "skin.json").read_text(encoding="utf-8"))
    sid, sec = meta["id"], meta["section"]
    pals = [palette(c["bg"], c["accent"], c["accent2"], c.get("extra")) for c in meta["colors"]]
    names = [c["name"] for c in meta["colors"]]
    skin_meta = {"id": sid, "section": sec, "intro": meta.get("intro", "none"), "fx": meta.get("fx", "none"),
                 "fxCount": meta.get("fxCount", 12), "burst": meta.get("burst"), "docTitle": meta["docTitle"],
                 "labels": meta.get("labels", {}), "minSel": meta.get("minSel", 2), "introMs": meta.get("introMs"),
                 "mins": meta.get("mins", {}), "sw": [[p["bg"], p["accent"]] for p in pals], "npal": len(pals)}
    skin_meta = {k: v for k, v in skin_meta.items() if v not in (None, {}, "")}
    cfg = demo_config(sec, meta.get("demo"))
    blocks = "\n".join(f'<section class="blk blk-{b}" data-block="{b}"></section>' for b in BLOCKS[sec])
    desc = html.escape(meta["desc"])
    title = html.escape(meta["name"])
    page = f"""<!doctype html>
<html lang="uz" data-rang="1">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta name="theme-color" content="{pals[0]['bg']}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{html.escape(meta['fonts'])}">
<style>{css_base}/* ===== ranglar ===== */
{palette_css(pals)}

/* ===== dizayn: {sid} ===== */
{(skin_dir / 'skin.css').read_text(encoding='utf-8')}
</style>
</head>
<body class="sec-{sec} skin-{sid}">
<script id="site-config" type="application/json">{json.dumps(cfg, ensure_ascii=False)}</script>
<canvas id="fx-back" aria-hidden="true"></canvas>
<main class="page">
<section class="blk blk-hero" data-block="hero" data-skin>
{(skin_dir / 'hero.html').read_text(encoding='utf-8').strip()}
</section>
{blocks}
</main>
<canvas id="fx-front" aria-hidden="true"></canvas>
<script>window.SKIN_META={json.dumps(skin_meta, ensure_ascii=False)};</script>
<script>{js_engine}</script>
<script>
(function(){{var T=window.TABRIK;if(!T)return;
{(skin_dir / 'skin.js').read_text(encoding='utf-8').strip()}
}})();
</script>
</body>
</html>
"""
    out = CAT / "namuna" / sec / f"{sid}.html"
    out.write_text(page, encoding="utf-8")
    return {"id": sid, "section": sec, "sectionName": SECTION_NAMES[sec], "name": meta["name"], "desc": meta["desc"],
            "colors": names, "swatch": [[p["bg"], p["accent"], p["accent2"]] for p in pals],
            "file": f"{sec}/{sid}.html", "vip": False, "premium": True, "new": True}


def main() -> None:
    css_base, js_engine = engine_parts()
    entries = [build(d, css_base, js_engine) for d in sorted(SKINS.iterdir()) if (d / "skin.json").exists()]
    path = CAT / "catalog.json"
    catalog = [t for t in json.loads(path.read_text(encoding="utf-8")) if t["id"] not in {e["id"] for e in entries}]
    path.write_text(json.dumps(catalog + entries, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for e in entries:
        print(f"✓ {e['file']} ({len(e['colors'])} rang)")


if __name__ == "__main__":
    main()
