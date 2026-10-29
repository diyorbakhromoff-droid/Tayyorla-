"""Video taklifnoma: dizaynlar, maydonlarni tekshirish, sahifa ma'lumoti (payload), HTML va Telegram izohi.

Bitta payload uch joyda ishlatiladi: Mini App dagi jonli ko'rinish, renderer (MP4) va dizayn rasmlari.
"""

import hashlib
import html
import json
import re
from datetime import date
from functools import lru_cache

from fastapi import HTTPException

from . import i18n
from .config import MEDIA_DIR, ROOT, settings
from .qr import qr_path

VIDEO_DIR = ROOT / "catalog" / "video"
DESIGNS: dict[str, dict] = {d["id"]: d for d in json.loads((VIDEO_DIR / "designs.json").read_text(encoding="utf-8"))}
SECTIONS = ["toy", "osh", "gap", "choy", "tk"]
SECTION_EMOJI = {"toy": "💍", "osh": "🍚", "gap": "🌸", "choy": "🫖", "tk": "🎂"}
EVENT_KEYS = {
    "toy": ["nikoh", "qizlar", "fotiha", "kelin"],
    "osh": ["nahorgi", "osh_toyi", "sunnat", "beshik"],
    "gap": ["gap", "qizlar", "kelinlar", "qoshnilar"],
    "choy": ["choyxona"],
    "tk": ["tk", "yubiley", "bayram"],
}
HTML_LANG = {"uz": "uz", "cy": "uz-Cyrl", "ru": "ru", "en": "en", "kaa": "kaa", "tg": "tg", "kk": "kk"}

# kalit: (turi, uzunlik chegarasi)
COMMON_FIELDS = {
    "sana": ("date", 10), "ikki_kunlik": ("bool", 0), "sana2": ("date", 10), "vaqt": ("time", 5),
    "joy": ("text", 80), "manzil": ("text", 140), "xarita": ("map", 300),
    "matn": ("text", 200), "imzo": ("text", 60),
    "toyona": ("bool", 0), "karta": ("card", 19), "karta_egasi": ("text", 40),
    "kimga": ("text", 60), "rasm": ("photo", 0),
}
SECTION_FIELDS = {
    "toy": {"marosim": ("choice", 0), "marosim_nomi": ("text", 40), "kuyov": ("text", 30), "kelin": ("text", 30)},
    "osh": {"nomi": ("choice", 0), "nomi_matn": ("text", 40), "sababi": ("text", 90)},
    "gap": {"nomi": ("choice", 0), "nomi_matn": ("text", 40), "navbat": ("text", 40), "kassa": ("money", 0)},
    "choy": {"guruh": ("text", 40), "navbat": ("text", 40), "kassa": ("money", 0)},
    "tk": {"sarlavha": ("choice", 0), "ism": ("text", 30), "yosh": ("int", 0)},
}
REQUIRED = {
    "toy": ["kuyov", "kelin", "sana", "vaqt", "joy"],
    "osh": ["sana", "vaqt", "joy", "imzo"],
    "gap": ["sana", "vaqt", "joy"],
    "choy": ["sana", "vaqt", "joy"],
    "tk": ["ism", "sana", "vaqt", "joy"],
}
NAME_FIELDS = {"kuyov", "kelin", "ism", "navbat", "karta_egasi", "kimga"}

DEMO = {
    "toy": {"marosim": "nikoh", "kuyov": "Jasur", "kelin": "Malika", "sana": "2026-11-21", "vaqt": "18:00",
            "joy": "«Navro‘z» to‘yxonasi", "manzil": "Toshkent, Chilonzor, Bunyodkor ko‘chasi 12",
            "matn": "Qalblarimiz birlashadigan kunda sizni yonimizda ko‘rishdan baxtiyormiz.",
            "imzo": "Karimovlar oilasi", "toyona": True, "karta": "8600123456789012", "karta_egasi": "Malika Karimova",
            "xarita": "41.2856, 69.2034"},
    "osh": {"nomi": "nahorgi", "sababi": "O‘g‘limiz Sardorning to‘yi munosabati bilan", "sana": "2026-11-22", "vaqt": "06:00",
            "joy": "«Ko‘kcha» guzari", "manzil": "Toshkent, Ko‘kcha dahasi 5", "imzo": "Karimovlar oilasi",
            "matn": "Ertalabki oshimizga marhamat qiling.", "xarita": "41.3205, 69.2190"},
    "gap": {"nomi": "qizlar", "navbat": "Nigora", "kassa": 500000, "sana": "2026-11-14", "vaqt": "19:00",
            "joy": "«Bahor» kafesi", "manzil": "Toshkent, Yunusobod 4-mavze", "imzo": "Dugonalaring",
            "matn": "Bu safar gap bizda! Kechikmay keling.", "toyona": True, "karta": "9860123412341234", "karta_egasi": "Nigora Aliyeva"},
    "choy": {"guruh": "Choyxona gurungi", "navbat": "Anvar aka", "kassa": 300000, "sana": "2026-11-13", "vaqt": "20:00",
             "joy": "«Bog‘ishamol» choyxonasi", "manzil": "Toshkent, Yunusobod, Bog‘ishamol ko‘chasi 3", "imzo": "Gurung a’zolari",
             "matn": "Haftalik gurungimizga sizni kutamiz.", "xarita": "41.3510, 69.2890"},
    "tk": {"sarlavha": "tk", "ism": "Madina", "yosh": 25, "sana": "2026-12-05", "vaqt": "19:00",
           "joy": "«Oqshom» restorani", "manzil": "Toshkent, Mirobod ko‘chasi 7", "imzo": "Madina",
           "matn": "Bayramimni siz bilan nishonlashni istayman!", "xarita": "41.2995, 69.2790"},
}
DEMO_GUEST = "Aziz aka"


def designs_for(section: str | None = None) -> list[dict]:
    return [d for d in DESIGNS.values() if not section or d["section"] == section]


def design(design_id: str) -> dict:
    d = DESIGNS.get(design_id)
    if not d:
        raise HTTPException(400, "unknown_design")
    return d


# ---------------------------------------------------------------- tekshirish

COORD_RE = re.compile(r"^\s*(-?\d{1,2}\.\d{3,})\s*[,; ]\s*(-?\d{1,3}\.\d{3,})\s*$")


def map_link(value: str | None) -> str:
    """Xarita: havola yoki koordinata (41.31, 69.27). Boshqa narsa bo'lsa bo'sh."""
    v = (value or "").strip()
    if not v:
        return ""
    m = COORD_RE.match(v)
    if m:
        lat, lon = m.groups()
        return f"https://yandex.uz/maps/?pt={lon},{lat}&z=17&l=map"
    if re.match(r"^https://\S+$", v):
        return v[:300]
    return ""


def own_media(path) -> bool:
    if not isinstance(path, str) or not path.startswith("/media/"):
        return False
    name = path.removeprefix("/media/")
    return "/" not in name and ".." not in name and (MEDIA_DIR / name).is_file()


def _text(v, limit: int) -> str:
    if v in (None, ""):
        return ""
    return " ".join(str(v).split())[:limit]


def clean_data(section: str, raw: dict, strict: bool = False) -> dict:
    """Formadan kelgan ma'lumotni ruxsat etilgan, tekshirilgan qiymatlarga keltiradi.

    Xato bo'lsa HTTPException(400, "kod:maydon") — Mini App uni foydalanuvchi tilida ko'rsatadi.
    """
    if section not in SECTIONS:
        raise HTTPException(400, "unknown_section")
    raw = raw if isinstance(raw, dict) else {}
    spec = {**COMMON_FIELDS, **SECTION_FIELDS[section]}
    out: dict = {}
    for key, (kind, limit) in spec.items():
        v = raw.get(key)
        if kind == "text":
            v = _text(v, limit)
        elif kind == "date":
            v = _text(v, 10)
            if v:
                try:
                    v = date.fromisoformat(v).isoformat()
                except ValueError:
                    if strict:
                        raise HTTPException(400, f"bad_date:{key}")
                    v = ""
        elif kind == "time":
            v = _text(v, 5)
            if v and not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", v):
                if strict:
                    raise HTTPException(400, f"bad_time:{key}")
                v = ""
            if v and len(v) == 4:
                v = "0" + v
        elif kind == "bool":
            v = bool(v) and v not in ("0", "false")
        elif kind == "choice":
            v = v if v in EVENT_KEYS[section] or v == "custom" else ""
        elif kind == "money":
            digits = re.sub(r"\D", "", str(v or ""))[:11]
            v = int(digits) if digits else 0
        elif kind == "int":
            try:
                v = int(v)
            except (TypeError, ValueError):
                v = 0
            v = v if 0 < v < 150 else 0
        elif kind == "card":
            digits = re.sub(r"\D", "", str(v or ""))
            v = digits if 13 <= len(digits) <= 19 else ""
            if raw.get(key) and not v and strict and raw.get("toyona"):
                raise HTTPException(400, f"bad_card:{key}")
        elif kind == "map":
            v = _text(v, limit)
            if v and not map_link(v):
                if strict:
                    raise HTTPException(400, f"bad_map:{key}")
                v = ""
        elif kind == "photo":
            v = v if own_media(v) else ""
        if v not in (None, "", False, 0):
            out[key] = v
    if section == "gap":
        out.pop("ikki_kunlik", None)
        out.pop("sana2", None)
    if not out.get("ikki_kunlik"):
        out.pop("sana2", None)
    if out.get("sana2") and out.get("sana") and out["sana2"] <= out["sana"]:
        if strict:
            raise HTTPException(400, "bad_date:sana2")
        out.pop("sana2")
    if not out.get("toyona"):
        out.pop("karta", None)
        out.pop("karta_egasi", None)
    if strict:
        for key in REQUIRED[section]:
            if not out.get(key):
                raise HTTPException(400, f"required:{key}")
        if out.get("toyona") and not out.get("karta"):
            raise HTTPException(400, "required:karta")
    return out


# ---------------------------------------------------------------- payload

def card_number(digits: str) -> str:
    return " ".join(digits[i:i + 4] for i in range(0, len(digits), 4))


def resolve_lang(lang: str | None, data: dict) -> str:
    if lang in i18n.LANGS:
        return lang
    sample = " ".join(str(data.get(k) or "") for k in ("kuyov", "kelin", "ism", "joy", "matn", "imzo", "guruh", "navbat"))
    return i18n.detect(sample)


def event_title(section: str, data: dict, lang: str) -> str:
    """Kartochkadagi marosim/tadbir nomi: o'z nomi yozilgan bo'lsa o'sha, bo'lmasa lug'atdan."""
    key = {"toy": "marosim", "osh": "nomi", "gap": "nomi", "tk": "sarlavha"}.get(section)
    if section == "choy":
        return i18n.localize(data.get("guruh") or "", lang) or i18n.event_label(lang, "choy", "choyxona")
    if data.get(key) == "custom":
        own = data.get("marosim_nomi" if section == "toy" else "nomi_matn")
        if own:
            return i18n.localize(own, lang)
    default = EVENT_KEYS[section][0]
    return i18n.event_label(lang, section, data.get(key) or default)


def build_payload(design_id: str, data: dict, lang: str | None = "uz", *, guest: str | None = None,
                  free: bool = True, site_url: str | None = None, palette: int = 0, plain_dear: bool = False) -> dict:
    d = design(design_id)
    section = d["section"]
    lang = resolve_lang(lang, data)
    L = i18n.card(lang)

    def loc(key: str) -> str:
        return i18n.localize(str(data.get(key) or ""), lang, name=key in NAME_FIELDS)

    try:
        d1 = date.fromisoformat(data.get("sana") or "")
    except ValueError:
        d1 = date.fromisoformat(DEMO[section]["sana"])
    d2 = None
    if data.get("sana2"):
        try:
            d2 = date.fromisoformat(data["sana2"])
        except ValueError:
            d2 = None
        if d2 and d2 <= d1:
            d2 = None
    vaqt = data.get("vaqt") or "18:00"
    event = event_title(section, data, lang)
    n1, n2 = loc("kuyov"), loc("kelin")
    name = loc("ism")
    if section == "toy":
        names_line = f"{n1} & {n2}" if n1 and n2 else n1 or n2
        initials = f"{n1[:1]}&{n2[:1]}" if n1 and n2 else (n1 or n2)[:2]
    elif section == "tk":
        names_line, initials = name, name[:1]
    else:
        names_line, initials = event, event[:1]
    if d2 and d2.month != d1.month:
        month = f"{L['months'][d1.month - 1]} – {L['months'][d2.month - 1]}"
    else:
        month = L["months"][d1.month - 1]
    weekday = i18n.fmt_weekday(lang, d1) + (f" – {i18n.fmt_weekday(lang, d2)}" if d2 else "")
    time_line = i18n.fmt_time(lang, vaqt)
    mlink = map_link(data.get("xarita"))
    qr_text = mlink or site_url or ""
    guest_name = i18n.localize(guest, lang, name=True) if guest else ""
    yosh = data.get("yosh") or 0
    signature = loc("imzo")
    t = {
        "invite": L["invite"],
        "dear": (f"{guest_name}!" if plain_dear else L["dear"].format(name=guest_name)) if guest_name else "",
        "guest": guest_name,
        "from": signature or names_line,
        "event": event,
        "title": event,
        "name1": n1, "name2": n2, "name": name, "names_line": names_line, "initials": initials,
        "date": i18n.fmt_range(lang, d1, d2),
        "day": f"{d1.day}–{d2.day}" if d2 else str(d1.day),
        "month": month,
        "year": str(d1.year),
        "weekday": weekday,
        "time": vaqt,
        "time_line": time_line,
        "wt": f"{weekday}, {time_line}",
        "message": loc("matn"),
        "venue": loc("joy"),
        "address": loc("manzil"),
        "scan": L["scan_map"] if mlink else L["scan_site"],
        "respect": L["respect"],
        "signature": signature,
        "waiting": L["waiting"],
        "card_title": L["kassa_card"] if section in ("gap", "choy") else L["toyona"],
        "card_number": card_number(data.get("karta") or ""),
        "card_owner": loc("karta_egasi"),
        "brand": L["brand"],
        "bot": "@" + settings.bot_username,
        "age": i18n.fmt_age(lang, yosh) if yosh else "",
        "age_n": str(yosh) if yosh else "",
        "reason": loc("sababi"),
        "turn": L["turn"].format(name=loc("navbat")) if data.get("navbat") else "",
        "kassa": L["kassa"].format(sum=i18n.fmt_sum(lang, data["kassa"])) if data.get("kassa") else "",
    }
    f = {
        section: True,
        "guest": bool(guest_name),
        "message": bool(t["message"]),
        "venue": bool(t["venue"]),
        "address": bool(t["address"]),
        "qr": bool(qr_text),
        "toyona": bool(data.get("toyona") and data.get("karta")),
        "photo": bool(data.get("rasm")),
        "free": bool(free),
        "two_day": bool(d2),
        "reason": bool(t["reason"]),
        "turn": bool(t["turn"]),
        "kassa": bool(t["kassa"]),
        "extra": bool(t["reason"] or t["turn"] or t["kassa"]),
        "age": bool(yosh),
        "signature": bool(signature),
        "names2": bool(n1 and n2),
    }
    palettes = d.get("palettes") or [{"vars": {}}]
    pal = palettes[palette if 0 <= palette < len(palettes) else 0]
    return {
        "design": design_id, "section": section, "lang": lang, "html_lang": HTML_LANG[lang],
        "t": t, "f": f, "vars": pal["vars"],
        "qr": qr_path(qr_text) if qr_text else None,
        "photo": data.get("rasm") or "",
        "map": mlink,
    }


def demo_payload(design_id: str, lang: str = "uz", guest: bool = True) -> dict:
    d = design(design_id)
    return build_payload(design_id, DEMO[d["section"]], lang, guest=DEMO_GUEST if guest else None, free=True,
                         site_url=f"{settings.base_url}/s/demo")


def render_hash(payload: dict, music: dict | None) -> str:
    raw = json.dumps([payload, music or {}], sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode()).hexdigest()


# ---------------------------------------------------------------- HTML

_STYLE_RE = re.compile(r"<style>(.*?)</style>", re.S)


@lru_cache(maxsize=64)
def _fragment(design_id: str, mtime: float) -> tuple[str, str]:
    src = (VIDEO_DIR / f"{design_id}.html").read_text(encoding="utf-8")
    css = "\n".join(_STYLE_RE.findall(src))
    return css, _STYLE_RE.sub("", src)


def asset_version() -> str:
    files = [ROOT / "static" / "video" / "engine.js", ROOT / "static" / "video" / "engine.css"]
    return str(int(max(p.stat().st_mtime for p in files)))


def _json_script(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")


def page_html(design_id: str, payload: dict, mode: str = "live", t: int = 0, autoplay: bool = True) -> str:
    design(design_id)
    path = VIDEO_DIR / f"{design_id}.html"
    css, body = _fragment(design_id, path.stat().st_mtime)
    v = asset_version()
    boot = {"mode": mode, "payload": payload, "t": t, "autoplay": autoplay}
    return (
        f'<!doctype html><html lang="{html.escape(payload.get("html_lang", "uz"))}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=360, initial-scale=1"><meta name="robots" content="noindex">'
        f'<title>{html.escape(DESIGNS[design_id]["name"])}</title>'
        f'<link rel="stylesheet" href="/static/fonts/fonts.css?v={v}">'
        f'<link rel="stylesheet" href="/static/video/engine.css?v={v}">'
        f"<style>{css}</style></head><body><div id=\"tv\">{body}</div>"
        f"<script>window.__TV={_json_script(boot)};</script>"
        f'<script src="/static/video/engine.js?v={v}"></script></body></html>'
    )


# ---------------------------------------------------------------- Telegram izohi

def caption(payload: dict, *, paid: bool = False, guest: str | None = None) -> str:
    """Video ostidagi izoh (HTML): sana, joy, xarita va bir bosishda nusxalanadigan karta raqami."""
    t, f = payload["t"], payload["f"]
    L = i18n.card(payload["lang"])
    esc = html.escape
    head = t["names_line"] if payload["section"] in ("toy", "tk") else ""
    title = f"{SECTION_EMOJI.get(payload['section'], '✨')} <b>{esc(t['event'])}</b>" + (f" — {esc(head)}" if head and head != t["event"] else "")
    lines = []
    if guest:
        lines.append(esc(L["dear"].format(name=guest)))
    lines.append(title)
    lines.append(f"📅 {esc(t['date'])}, {esc(t['wt'])}")
    place = ", ".join(x for x in (t["venue"], t["address"]) if x)
    if place:
        lines.append(f"📍 {esc(place)}")
    if payload.get("map"):
        lines.append(f'🗺 <a href="{esc(payload["map"], quote=True)}">{esc(L["page"]["open_map"])}</a>')
    if t["turn"]:
        lines.append(f"👤 {esc(t['turn'])}")
    if t["kassa"]:
        lines.append(f"💰 {esc(t['kassa'])}")
    if f["toyona"]:
        owner = f" ({esc(t['card_owner'])})" if t["card_owner"] else ""
        lines.append(f"💳 {esc(t['card_title'])}: <code>{esc(t['card_number'])}</code>{owner}")
    if not paid:
        lines.append(f"\n✨ {esc(L['brand'])}: @{esc(settings.bot_username)}")
    return "\n".join(lines)[:1024]
