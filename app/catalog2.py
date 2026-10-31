"""Tarifli shablonlar (v2): har bir shablon faqat o'z tarifida, bloklari bo'limga xos va olib tashlanadi.

Shablon — dizayn kanvasidagi .dc.html fayl (catalog/v2/<bo'lim>/<id>.dc.html) va uning manifesti (<id>.json).
Sahifa static/site2/dc.js orqali brauzerda yig'iladi; bu modul maydonlar, bloklar va konfiguratsiyani beradi.
"""

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from html import escape

from .catalog import CATALOG_DIR, Field, _safe_json
from .config import ROOT, settings

V2_DIR = CATALOG_DIR / "v2"
TIER_LEVEL = {"standart": 1, "premium": 2, "vip": 3}


@dataclass
class Block:
    key: str
    title: str
    fields: list = field(default_factory=list)  # blokka tegishli maydonlar
    needs: list = field(default_factory=list)  # blok ko'rinishi uchun to'ldirilishi shart (@photos, @music)
    hint: str = ""


# ---------------------------------------------------------------- bo'limlar bo'yicha maydonlar

_ITEMS_YOL = [("yil", "Yil yoki sana", "text"), ("sarlavha", "Sarlavha", "text"), ("matn", "Qisqa matn", "text")]
_ITEMS_TILAK = [("ism", "Kimdan", "text"), ("matn", "Tilak", "text")]

FIELDS2: dict[str, list[Field]] = {
    "tugilgan-kun": [
        Field("kimga", "Kimni tabriklaymiz?", required=True, hint="Masalan: Madina"),
        Field("yosh", "Nechchi yoshga to'lyapti?", hint="Masalan: 25"),
        Field("sana", "Tug'ilgan kun sanasi", "date", required=True),
        Field("kimdan", "Tabrik kimdan?", hint="Masalan: Dugonalaring: Laylo va Sevara"),
        Field("matn", "Tabrik matni", "textarea", ai=True),
        Field("tilaklar", "Tilaklar", "lines", hint="Har birini yangi qatordan, 3–6 ta"),
        Field("sirli_tilak", "Sirli tilak", "textarea", hint="Mehmon bosgandagina ochiladi"),
        Field("bazm_sana", "Bazm sanasi", "date"),
        Field("bazm_vaqt", "Bazm vaqti", "time"),
        Field("bazm_joy", "Bazm joyi", hint="Masalan: «Bahor» kafesi"),
        Field("bazm_manzil", "Manzil"),
        Field("xarita", "Xarita havolasi (Google yoki Yandex)", "url"),
        Field("dress_kod", "Kiyinish uslubi", hint="Masalan: Oltin va qora"),
        Field("xronika", "Yil xronikasi", "items", sub=[("yosh", "Yoshi", "text"), ("matn", "Qisqa izoh", "text")],
              hint="Suratlar tartib bo'yicha qo'yiladi"),
        Field("mehmon_tilaklari", "Yaqinlar tilaklari", "items", sub=_ITEMS_TILAK),
    ],
    "toy": [
        Field("kuyov", "Kuyovning ismi", required=True),
        Field("kelin", "Kelinning ismi", required=True),
        Field("sana", "To'y sanasi", "date", required=True),
        Field("vaqt", "Boshlanish vaqti", "time", required=True),
        Field("mehmon", "Mehmon ismi", hint="Mehmonlar ro'yxatidan yuborilsa, har biriga o'z ismi chiqadi"),
        Field("matn", "Taklif matni", "textarea", ai=True),
        Field("taklif_qiluvchilar", "Taklif qiluvchilar", hint="Masalan: Karimovlar va Rahimovlar oilasi"),
        Field("manzil_nomi", "To'yxona nomi"),
        Field("manzil", "Manzil"),
        Field("xarita", "Xarita havolasi (Google yoki Yandex)", "url"),
        Field("joy_rasmi", "To'yxona surati", "photo"),
        Field("dastur", "To'y dasturi", "items", sub=[("vaqt", "Vaqt", "time"), ("nomi", "Nima bo'ladi", "text")]),
        Field("hikoya", "Sevgi tarixi", "items", sub=_ITEMS_YOL),
        Field("dress_kod", "Kiyinish uslubi", hint="Masalan: Zumrad, shampan va oltin ranglar"),
        Field("telegram_guruh", "Mehmonlar Telegram guruhi", "url"),
        Field("telefon", "Aloqa uchun telefon", "tel"),
    ],
    "sevgi": [
        Field("kimga", "Kimga?", required=True),
        Field("kimdan", "Kimdan?", required=True),
        Field("tanishgan_sana", "Tanishgan kuningiz", "date"),
        Field("matn", "Maktub matni", "textarea", ai=True),
        Field("sabablar", "Seni sevishimning sabablari", "lines", hint="Har birini yangi qatordan"),
        Field("yol", "Bizning yo'limiz", "items", sub=_ITEMS_YOL),
        Field("sirli_soz", "Yashirin so'z", "textarea", hint="Bosgandagina ochiladi"),
        Field("savol", "Muhim savol", hint="Masalan: Menga turmushga chiqasanmi?"),
    ],
    "farzand": [
        Field("chaqaloq", "Chaqaloqning ismi", required=True),
        Field("jins", "O'g'il yoki qiz?", "choice", required=True, options={"ogil": "O'g'il", "qiz": "Qiz"}),
        Field("sana", "Tug'ilgan sanasi", "date", required=True),
        Field("vaqt", "Tug'ilgan vaqti", "time"),
        Field("ota_ona", "Ota-onasi", required=True, hint="Masalan: Bekzod va Zarina"),
        Field("vazn", "Vazni", hint="Masalan: 3,4 kg"),
        Field("boy", "Bo'yi", hint="Masalan: 52 sm"),
        Field("matn", "Xabar matni", "textarea", ai=True),
        Field("bobo_buvi", "Buvi va bobolari", "lines", hint="Har bir juftlik yangi qatordan"),
        Field("tilaklar", "Tilaklar", "lines", hint="Har birini yangi qatordan"),
        Field("mehmon_tilaklari", "Yaqinlar tilaklari", "items", sub=_ITEMS_TILAK),
    ],
    "uzr": [
        Field("kimga", "Kimdan uzr so'raysiz?", required=True),
        Field("kimdan", "Ismingiz", required=True),
        Field("matn", "Uzr matni", "textarea", ai=True),
        Field("vadalar", "Va'dalarim", "lines", hint="Har birini yangi qatordan"),
        Field("taklif", "Yarashish taklifi", hint="Masalan: Bir piyola choyga chiqamizmi?"),
        Field("taklif_vaqt", "Qachon?", hint="Masalan: Shanba, 17:00"),
        Field("taklif_joy", "Qayerda?", hint="Masalan: Sevimli kafemiz"),
        Field("javob_matni", "«Kechirdim» bosilganda chiqadigan so'z", hint="Masalan: Rahmat! So'zimda turaman"),
    ],
}

# Bosh qism: har doim ko'rinadi, olib tashlanmaydi
HERO2 = {
    "tugilgan-kun": ["kimga", "yosh", "sana"],
    "toy": ["kuyov", "kelin", "sana", "vaqt", "mehmon"],
    "sevgi": ["kimga", "kimdan"],
    "farzand": ["chaqaloq", "jins", "sana", "vaqt", "ota_ona"],
    "uzr": ["kimga", "kimdan"],
}

PHOTOS = "@photos"
MUSIC = "@music"

BLOCKS2: dict[str, list[Block]] = {
    "tugilgan-kun": [
        Block("tabrik", "Tabrik matni", ["matn", "kimdan"], ["matn"]),
        Block("tilaklar", "Tilaklar", ["tilaklar"], ["tilaklar"]),
        Block("taymer", "Taymer", [], ["sana"]),
        Block("sham", "«Shamni o'chiring»"),
        Block("sirli", "Sirli tilak", ["sirli_tilak"], ["sirli_tilak"]),
        Block("galereya", "Suratlar", [], [PHOTOS]),
        Block("xronika", "Yil xronikasi", ["xronika"], ["xronika"]),
        Block("bazm", "Bazmga taklif", ["bazm_sana", "bazm_vaqt", "bazm_joy", "bazm_manzil", "xarita", "dress_kod"], ["bazm_sana", "bazm_joy"]),
        Block("mehmonlar", "Yaqinlar tilaklari", ["mehmon_tilaklari"], ["mehmon_tilaklari"]),
        Block("javob", "«Tabrikladim» tugmasi"),
    ],
    "toy": [
        Block("taklif", "Taklif matni", ["matn", "taklif_qiluvchilar"], ["matn"]),
        Block("kun", "Sana va vaqt"),
        Block("taymer", "Taymer"),
        Block("manzil", "Manzil", ["manzil_nomi", "manzil", "xarita", "joy_rasmi"], ["manzil_nomi"]),
        Block("dastur", "To'y dasturi", ["dastur"], ["dastur"]),
        Block("hikoya", "Sevgi tarixi", ["hikoya"], ["hikoya"]),
        Block("galereya", "Suratlar", [], [PHOTOS]),
        Block("dress", "Kiyinish uslubi", ["dress_kod"], ["dress_kod"]),
        Block("rsvp", "Mehmon javobi"),
        Block("guruh", "Telegram guruhi", ["telegram_guruh"], ["telegram_guruh"]),
        Block("telefon", "Aloqa telefoni", ["telefon"], ["telefon"]),
    ],
    "sevgi": [
        Block("maktub", "Maktub", ["matn"], ["matn"]),
        Block("sabablar", "Sevishimning sabablari", ["sabablar"], ["sabablar"]),
        Block("yol", "Bizning yo'limiz", ["yol"], ["yol"]),
        Block("sirli", "Yashirin so'z", ["sirli_soz"], ["sirli_soz"]),
        Block("galereya", "Suratlar", [], [PHOTOS]),
        Block("hisob", "Birga o'tgan kunlar", ["tanishgan_sana"], ["tanishgan_sana"]),
        Block("xarita", "Yulduzlar xaritasi", ["tanishgan_sana"], ["tanishgan_sana"]),
        Block("savol", "Muhim savol", ["savol"], ["savol"]),
        Block("javob", "Javob tugmasi"),
    ],
    "farzand": [
        Block("olchov", "Tug'ilish kartochkasi", ["vazn", "boy"], ["vazn"]),
        Block("xabar", "Xabar matni", ["matn"], ["matn"]),
        Block("oila", "Oila daraxti", ["bobo_buvi"], ["bobo_buvi"]),
        Block("galereya", "Suratlar", [], [PHOTOS]),
        Block("albom", "O'sish albomi", [], [PHOTOS]),
        Block("tilaklar", "Tilaklar", ["tilaklar"], ["tilaklar"]),
        Block("alla", "Alla (musiqa)", [], [MUSIC]),
        Block("mehmonlar", "Yaqinlar tilaklari", ["mehmon_tilaklari"], ["mehmon_tilaklari"]),
        Block("javob", "«Tabriklash» tugmasi"),
    ],
    "uzr": [
        Block("maktub", "Uzr matni", ["matn"], ["matn"]),
        Block("vadalar", "Va'dalarim", ["vadalar"], ["vadalar"]),
        Block("galereya", "Suratlar", [], [PHOTOS]),
        Block("taklif", "Yarashish taklifi", ["taklif", "taklif_vaqt", "taklif_joy"], ["taklif"]),
        Block("javob", "«Kechirdim» tugmasi", ["javob_matni"]),
        Block("sorov", "Javob yozish"),
    ],
}

_FIELD = {s: {f.key: f for f in fs} for s, fs in FIELDS2.items()}
_BLOCK = {s: {b.key: b for b in bs} for s, bs in BLOCKS2.items()}


# ---------------------------------------------------------------- manifestlar

def _load() -> tuple[dict, dict]:
    templates, demos = {}, {}
    if not V2_DIR.is_dir():
        return templates, demos
    for sec_dir in sorted(p for p in V2_DIR.iterdir() if p.is_dir() and p.name in FIELDS2):
        demo = sec_dir / "demo.json"
        if demo.is_file():
            demos[sec_dir.name] = json.loads(demo.read_text(encoding="utf-8"))
        for mf in sorted(sec_dir.glob("*.json")):
            if mf.name == "demo.json" or not (sec_dir / f"{mf.stem}.dc.html").is_file():
                continue
            m = json.loads(mf.read_text(encoding="utf-8"))
            sec = sec_dir.name
            blocks = [b for b in m.get("blocks", []) if b in _BLOCK[sec]]
            templates[m["id"]] = {
                "id": m["id"], "section": sec, "tier": m["tier"], "name": m["name"], "desc": m.get("desc", ""),
                "file": f"v2/{sec}/{mf.stem}.dc.html", "blocks": blocks, "slots": int(m.get("slots", 6)),
                "demo_photos": m.get("demo_photos", []), "fields_off": m.get("fields_off", []),
                "order": int(m.get("order", 50)), "intro": bool(m.get("intro", m["tier"] != "standart")),
                # eski kod bilan moslik
                "v2": True, "vip": m["tier"] == "vip", "premium": m["tier"] == "premium", "new": False,
                "colors": ["Asl"], "swatch": [m.get("swatch") or ["#FFFFFF", "#888888", "#222222"]],
            }
    return templates, demos


TEMPLATES2, DEMOS = _load()


def _attach() -> None:
    """Yangi shablonlarni umumiy katalogga qo'shadi; eskilari yashiriladi (to'langan saytlari ishlayveradi)."""
    from . import catalog

    for t in TEMPLATES2.values():
        t["colors"], t["swatch"] = palette_swatches(t)
    if TEMPLATES2:
        for t in catalog.TEMPLATES.values():
            if not t.get("v2"):
                t["legacy"] = True
        catalog.TEMPLATES.update(TEMPLATES2)



def hero_fields(t: dict) -> list[str]:
    return [k for k in HERO2[t["section"]] if k not in t["fields_off"]]


def fields_for(t: dict) -> list[Field]:
    """Shablonda ishlatiladigan maydonlar: bosh qism + shablondagi bloklarning maydonlari."""
    keys = list(hero_fields(t))
    for b in t["blocks"]:
        keys += [k for k in _BLOCK[t["section"]][b].fields if k not in keys and k not in t["fields_off"]]
    return [f for f in FIELDS2[t["section"]] if f.key in keys]


def block_meta(t: dict) -> list[dict]:
    sec = t["section"]
    return [{"key": b, "title": _BLOCK[sec][b].title,
             "fields": [k for k in _BLOCK[sec][b].fields if k not in t["fields_off"]],
             "needs": _BLOCK[sec][b].needs} for b in t["blocks"]]


def _filled(v) -> bool:
    if isinstance(v, (list, dict)):
        return bool(v)
    return v not in (None, "")


def visible_blocks(t: dict, data: dict, photos: list, music, hidden: list) -> dict:
    out = {}
    for key in t["blocks"]:
        ok = key not in hidden
        for need in _BLOCK[t["section"]][key].needs:
            if need == PHOTOS:
                ok = ok and bool(photos)
            elif need == MUSIC:
                ok = ok and bool(music)
            else:
                ok = ok and _filled(data.get(need))
        out[key] = ok
    return out


def clean_hidden(t: dict, hidden) -> list[str]:
    return [b for b in (hidden if isinstance(hidden, list) else []) if b in t["blocks"]][:20]


# ---------------------------------------------------------------- sahifani yig'ish

_HELMET = re.compile(r"<helmet>(.*?)</helmet>", re.S)
_XDC = re.compile(r"<x-dc>(.*?)</x-dc>", re.S)
_SCRIPT = re.compile(r"<script type=\"text/x-dc\" data-dc-script[^>]*>(.*?)</script>", re.S)

BASE_CSS = ("html,body{margin:0;padding:0}body{-webkit-text-size-adjust:100%;overflow-x:hidden}"
            "#dc-root{width:390px;margin:0 auto;position:relative}")


@lru_cache(maxsize=128)
def _parts(path: str, mtime: float) -> tuple[str, str, str]:
    src = (CATALOG_DIR / path).read_text(encoding="utf-8")
    helmet = _HELMET.search(src)
    xdc = _XDC.search(src)
    script = _SCRIPT.search(src)
    markup = _HELMET.sub("", xdc.group(1)) if xdc else ""
    return (helmet.group(1).strip() if helmet else ""), markup.strip(), (script.group(1).strip() if script else "")


def _asset_v(rel: str) -> int:
    p = ROOT / rel
    return int(p.stat().st_mtime) if p.is_file() else 0


def page_title(section: str, d: dict) -> str:
    if section == "toy":
        names = " va ".join(x for x in (d.get("kuyov"), d.get("kelin")) if x)
        return f"{names} — to'y taklifnomasi" if names else "To'y taklifnomasi"
    if section == "tugilgan-kun":
        return f"{d.get('kimga')}, tug'ilgan kuning muborak!" if d.get("kimga") else "Tug'ilgan kuning muborak!"
    if section == "sevgi":
        return f"{d.get('kimga')} uchun" if d.get("kimga") else "Sevgi maktubi"
    if section == "farzand":
        return f"{d.get('chaqaloq')} dunyoga keldi" if d.get("chaqaloq") else "Farzand muborak"
    return f"{d.get('kimga')}, kechirasanmi?" if d.get("kimga") else "Uzr"


def render(t: dict, config: dict, slug: str, preview: bool, guest=None, demo: bool = False, watermark: str = "") -> str:
    path = CATALOG_DIR / t["file"]
    helmet, markup, script = _parts(t["file"], path.stat().st_mtime)
    data = dict(config.get("data") or {})
    photos = list(config.get("photos") or [])
    music = config.get("music")
    hidden = config.get("hidden") or []
    if guest is not None:
        data["mehmon"] = guest.name
    cfg = {
        "tarif": t["tier"], "data": data, "photos": photos, "slots": t["slots"], "music": music,
        "pal": palette(t, config.get("rang")),
        "b": visible_blocks(t, data, photos, music, hidden),
        "guest": {"n": guest.name, "t": guest.token} if guest is not None else None,
        "urls": {} if demo else {"react": f"/s/{slug}/react", "rsvp": f"/s/{slug}/rsvp"},
        "demo": demo, "preview": preview,
    }
    title = page_title(t["section"], data)
    og_img = photos[0] if photos else f"/katalog/thumb/{t['id']}.jpg"
    if og_img.startswith("/"):
        og_img = settings.base_url.rstrip("/") + og_img
    head = [
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
        f"<title>{escape(title)}</title>",
        f'<meta property="og:title" content="{escape(title)}">',
        f'<meta property="og:image" content="{escape(og_img)}">',
        '<meta property="og:type" content="website">',
    ]
    if preview or demo:
        head.append('<meta name="robots" content="noindex">')
    v_dc = _asset_v("static/site2/dc.js")
    return (
        "<!doctype html><html lang=\"uz\"><head>" + "".join(head) + helmet + f"<style>{BASE_CSS}</style></head><body>"
        '<div id="dc-root"><div id="dc-mount"></div></div>'
        f'<template id="dc-tpl">{markup}</template>'
        f'<script id="site-config" type="application/json">{_safe_json(cfg)}</script>'
        '<script src="/static/vendor/preact-10.26.9.min.js"></script>'
        f'<script src="/static/site2/dc.js?v={v_dc}"></script>'
        f"<script>{script}\nDC.boot(Component);</script>"
        + watermark + "</body></html>"
    )


# ---------------------------------------------------------------- rang palitralari
# Palitra dizaynning kayfiyatini saqlagan holda ohangini o'zgartiradi: rang aylanishi (±40° gacha),
# to'yinganlik va yorqinlik. Suratlar o'z rangida qoladi. Tarif birinchi N tasini oladi (3 / 8 / 12).
PALETTES = [  # (nomi, hue°, to'yinganlik, yorqinlik)
    ("Asl", 0, 1.0, 1.0), ("Iliq", 16, 1.0, 1.0), ("Salqin", -16, 1.0, 1.0),
    ("Yumshoq", 0, 0.72, 1.05), ("Yorqin", 0, 1.25, 0.98), ("Shaftoli", 30, 0.92, 1.02),
    ("Tong", -30, 0.92, 1.02), ("Kechki", 0, 1.08, 0.88), ("Pastel", 10, 0.6, 1.08),
    ("Jozibali", -10, 1.3, 0.95), ("Kuz", 40, 0.85, 0.96), ("Ayoz", -40, 0.85, 1.0),
]
PAL_COUNT = {"standart": 3, "premium": 8, "vip": 12}


def palette(t: dict, rang) -> list:
    try:
        i = int(rang or 1) - 1
    except (TypeError, ValueError):
        i = 0
    _, h, sat, br = PALETTES[i] if 0 <= i < PAL_COUNT[t["tier"]] else PALETTES[0]
    return [h, sat, br]


def palette_swatches(t: dict) -> tuple[list, list]:
    """Mini App uchun: palitra nomlari va har birining 3 rangi (manifestdagi swatch o'zgartirilgan holda)."""
    import colorsys

    def shift(hexc: str, h: int, sat: float, br: float) -> str:
        r, g, b = (int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5))
        hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
        r, g, b = colorsys.hls_to_rgb((hh + h / 360) % 1, min(1, ll * br), min(1, ss * sat))
        return "#%02X%02X%02X" % tuple(round(x * 255) for x in (r, g, b))

    base = t["swatch"][0]
    pals = PALETTES[:PAL_COUNT[t["tier"]]]
    return [p[0] for p in pals], [[shift(c, h, sat, br) for c in base] for _, h, sat, br in pals]


def demo_config(t: dict) -> dict:
    return {"template": t["id"], "tarif": t["tier"], "data": dict(DEMOS.get(t["section"], {})),
            "photos": list(t["demo_photos"]), "music": None, "hidden": []}


_attach()
