import re
from datetime import date, datetime
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import ROOT, settings
from .sites import CATEGORIES

env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html"]))

MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"]
WEEKDAYS = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]


def parse_date(text: str | None) -> date | None:
    if not text:
        return None
    m = re.search(r"(\d{1,2})[./\-\s](\d{1,2})[./\-\s](\d{2,4})", text)
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    if y < 100:
        y += 2000
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def human_date(text: str | None) -> str:
    d = parse_date(text)
    if not d:
        return text or ""
    return f"{d.day}-{MONTHS[d.month - 1]}, {d.year}"


def weekday(text: str | None) -> str:
    d = parse_date(text)
    return WEEKDAYS[d.weekday()].capitalize() if d else ""


_CSS_BLOCKLIST = re.compile(r"(</|<|@import|url\s*\(|expression\s*\(|javascript:|behavior\s*:)", re.I)


def safe_css(css: str) -> str:
    """AI yozgan CSS dan tashqi resurs va HTML ga chiqib ketish imkoniyatlarini olib tashlaydi."""
    return _CSS_BLOCKLIST.sub("", css or "")


def map_url(fields: dict) -> str:
    if fields.get("lat") and fields.get("lon"):
        return f"https://yandex.uz/maps/?pt={fields['lon']},{fields['lat']}&z=17&l=map"
    return "https://yandex.uz/maps/?text=" + quote(f"{fields.get('venue', '')} {fields.get('address', '')}".strip())


def on_color(hex_color: str) -> str:
    """Fon rangiga qarab o'qiladigan matn rangini tanlaydi."""
    h = (hex_color or "#000000").lstrip("#")
    if len(h) != 6:
        return "#ffffff"
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#1b1308" if (0.299 * r + 0.587 * g + 0.114 * b) > 160 else "#ffffff"


def render_site(site, preview: bool) -> str:
    cfg = site.config
    fields = cfg.get("fields", {})
    target = parse_date(fields.get("date"))
    time = fields.get("time") or "00:00"
    iso = None
    if target:
        hh, mm = (re.findall(r"\d{1,2}", time) + ["0", "0"])[:2]
        iso = datetime(target.year, target.month, target.day, min(int(hh), 23), min(int(mm), 59)).isoformat()
    tpl = env.get_template(f"{cfg['category']}.html")
    return tpl.render(
        slug=site.slug,
        cfg=cfg,
        f=fields,
        c=cfg["colors"],
        feat=cfg.get("features", {}),
        t=cfg.get("texts", {}),
        message_paragraphs=[p.strip() for p in (cfg.get("message") or "").split("\n") if p.strip()],
        date_human=human_date(fields.get("date")),
        weekday=weekday(fields.get("date")),
        target_iso=iso,
        map_url=map_url(fields),
        custom_css=safe_css(cfg.get("custom_css", "")),
        on_primary=on_color(cfg["colors"].get("primary")),
        preview=preview,
        base_url=settings.base_url,
        bot_username=settings.bot_username,
        category=CATEGORIES[cfg["category"]],
    )
