"""Ko'p tillilik: interfeys lug'atlari, taklifnoma (kartochka) so'zlari, sana formatlari va transliteratsiya.

Tillar: uz (o'zbek lotin), cy (o'zbek kirill), ru, en, kaa (qoraqalpoq), tg (tojik), kk (qozoq).
"""

import json
import logging
import re
from datetime import date
from functools import lru_cache

from .config import ROOT

log = logging.getLogger(__name__)

LANGS = ["uz", "cy", "ru", "en", "kaa", "tg", "kk"]
LANG_NAMES = {"uz": "O‘zbekcha", "cy": "Ўзбекча", "ru": "Русский", "en": "English",
              "kaa": "Qaraqalpaqsha", "tg": "Тоҷикӣ", "kk": "Қазақша"}
UI_DIR = ROOT / "static" / "i18n"
CARD: dict[str, dict] = json.loads((ROOT / "app" / "locales" / "card.json").read_text(encoding="utf-8"))


def norm_lang(code: str | None) -> str:
    return code if code in LANGS else "uz"


def from_telegram(code: str | None) -> str:
    """Telegram language_code dan interfeys tili."""
    code = (code or "").lower()
    if code.startswith("uz"):
        return "cy" if "cyrl" in code else "uz"
    for lang in ("ru", "en", "kk", "tg", "kaa"):
        if code.startswith(lang):
            return lang
    if code in ("be", "uk"):
        return "ru"
    return "uz"


# ---------------------------------------------------------------- interfeys matnlari

@lru_cache(maxsize=None)
def ui(lang: str) -> dict:
    lang = norm_lang(lang)
    path = UI_DIR / f"{lang}.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if lang != "uz":
        base = ui("uz")
        data = {**base, **{k: v for k, v in data.items() if v}}
    return data


def tr(lang: str, key: str, **kw) -> str:
    """Bot va sahifalar uchun tarjima: kalit topilmasa o'zbekcha, u ham bo'lmasa kalitning o'zi."""
    text = ui(lang).get(key) or ui("uz").get(key) or key
    try:
        return text.format(**kw) if kw else text
    except (KeyError, IndexError, ValueError):
        return text


# ---------------------------------------------------------------- taklifnoma so'zlari va sanalar

def card(lang: str) -> dict:
    return CARD[norm_lang(lang)]


def _plural(lang: str, rule, n: int) -> str:
    if isinstance(rule, str):
        return rule.format(n=n)
    if lang == "ru":
        if n % 10 == 1 and n % 100 != 11:
            form = "one"
        elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            form = "few"
        else:
            form = "many"
    else:
        form = "one" if n == 1 else "many"
    return (rule.get(form) or rule.get("many") or "{n}").format(n=n)


def fmt_date(lang: str, d: date) -> str:
    L = card(lang)
    return L["date"].format(d=d.day, m=L["months"][d.month - 1], y=d.year)


def fmt_day_month(lang: str, d: date) -> str:
    L = card(lang)
    return L["day_month"].format(d=d.day, m=L["months"][d.month - 1])


def fmt_range(lang: str, d1: date, d2: date | None) -> str:
    if not d2 or d2 == d1:
        return fmt_date(lang, d1)
    L = card(lang)
    if (d1.year, d1.month) == (d2.year, d2.month):
        return L["range_same"].format(d1=d1.day, d2=d2.day, m=L["months"][d1.month - 1], y=d1.year)
    return L["range"].format(d1=d1.day, m1=L["months"][d1.month - 1], d2=d2.day, m2=L["months"][d2.month - 1], y=d2.year)


def fmt_weekday(lang: str, d: date) -> str:
    return card(lang)["weekdays"][d.weekday()]


def fmt_time(lang: str, t: str) -> str:
    return card(lang)["time"].format(t=t)


def fmt_age(lang: str, n: int) -> str:
    return _plural(lang, card(lang)["age"], n)


def fmt_sum(lang: str, n: int) -> str:
    return card(lang)["sum"].format(n=f"{n:,}".replace(",", " "))


def event_label(lang: str, section: str, key: str | None) -> str:
    return card(lang)["events"].get(section, {}).get(key or "", "")


# ---------------------------------------------------------------- transliteratsiya

_APOS_RE = re.compile("[ʻ‘’`´ʼ']")


def _norm_apos(s: str) -> str:
    return _APOS_RE.sub("'", s)


def _translit(text: str, digraphs: list[tuple[str, str]], singles: dict[str, str], e_initial: str = "") -> str:
    s = _norm_apos(text)
    out, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        for src, dst in digraphs:
            seg = s[i:i + len(src)]
            if seg.lower() == src:
                if seg[0].isupper() and dst:
                    rest = seg[1:].replace("'", "")
                    dst = dst.upper() if rest and rest.isupper() else dst[0].upper() + dst[1:]
                out.append(dst)
                i += len(src)
                break
        else:
            low = ch.lower()
            if low == "e" and e_initial and (i == 0 or not s[i - 1].isalpha()):
                m = e_initial
            else:
                m = singles.get(low)
            out.append(ch if m is None else (m.upper() if ch.isupper() else m))
            i += 1
    return "".join(out)


_UZ_SINGLES = {"a": "а", "b": "б", "c": "с", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "ҳ", "i": "и", "j": "ж", "k": "к",
               "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "q": "қ", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в",
               "w": "в", "x": "х", "y": "й", "z": "з", "'": "ъ"}
_COMMON_DIGRAPHS = [("sh", "ш"), ("ch", "ч"), ("yo", "ё"), ("yu", "ю"), ("ya", "я"), ("ye", "е")]


def to_cyrillic(text: str) -> str:
    """O'zbek lotin -> o'zbek kirill."""
    return _translit(text, [("yo'", "йў"), ("o'", "ў"), ("g'", "ғ")] + _COMMON_DIGRAPHS, _UZ_SINGLES, "э")


def to_russian(text: str) -> str:
    """O'zbek ismlarini rus yozuviga: Jasur -> Жасур, G'ayrat -> Гайрат."""
    return _translit(text, [("yo'", "йу"), ("o'", "у"), ("g'", "г")] + _COMMON_DIGRAPHS,
                     {**_UZ_SINGLES, "q": "к", "h": "х", "'": ""}, "э")


def to_tajik(text: str) -> str:
    return _translit(text, [("yo'", "йӯ"), ("o'", "ӯ"), ("g'", "ғ")] + _COMMON_DIGRAPHS, {**_UZ_SINGLES, "j": "ҷ"}, "э")


def to_kazakh(text: str) -> str:
    return _translit(text, [("yo'", "йө"), ("o'", "ө"), ("g'", "ғ")] + _COMMON_DIGRAPHS, {**_UZ_SINGLES, "h": "һ", "'": ""}, "э")


def to_karakalpak(text: str) -> str:
    return _translit(text, [("o'", "ó"), ("g'", "ǵ")], {})


_CYR_TO_LAT = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i", "й": "y",
               "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
               "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "’", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
               "ў": "o‘", "қ": "q", "ғ": "g‘", "ҳ": "h"}


def to_latin(text: str) -> str:
    """O'zbek kirill -> lotin (foydalanuvchi kirillda yozib, lotin kartochka tanlasa)."""
    out = []
    for i, ch in enumerate(text):
        low = ch.lower()
        if low == "е" and (i == 0 or not text[i - 1].isalpha()):
            m = "ye"
        else:
            m = _CYR_TO_LAT.get(low)
        if m is None:
            out.append(ch)
        elif ch.isupper() and m:
            nxt = text[i + 1] if i + 1 < len(text) else ""
            prev = text[i - 1] if i else ""
            out.append(m.upper() if nxt.isupper() or prev.isupper() else m[0].upper() + m[1:])
        else:
            out.append(m)
    return "".join(out)


_HAS_LAT = re.compile("[A-Za-z]")
_HAS_CYR = re.compile("[А-Яа-яЁёЎўҚқҒғҲҳ]")


def detect(text: str) -> str:
    """«Avto» kartochka tili: matn yozuviga qarab."""
    s = (text or "").lower()
    cyr = len(re.findall("[а-яёўқғҳәңөұүһіҷӣӯ]", s))
    lat = len(re.findall("[a-záǵıńóú]", s))
    if cyr > lat:
        if re.search("[ҷӣӯ]", s):
            return "tg"
        if re.search("[әңөұүһі]", s):
            return "kk"
        if re.search("[ўқғҳ]", s):
            return "cy"
        return "ru"
    if re.search("[áǵıńú]", s):
        return "kaa"
    return "uz"


def localize(value: str, lang: str, name: bool = False) -> str:
    """Foydalanuvchi matnini kartochka yozuviga moslaydi.

    Kirill: hammasi avtomatik o'giriladi. Rus/tojik/qozoq: faqat ismlar (qolganini AI tarjima qiladi).
    """
    if not value:
        return value
    if lang == "cy":
        return to_cyrillic(value) if _HAS_LAT.search(value) else value
    if lang in ("uz", "kaa", "en"):
        if _HAS_CYR.search(value) and not _HAS_LAT.search(value):
            value = to_latin(value)
        return to_karakalpak(value) if lang == "kaa" else value
    if name and _HAS_LAT.search(value) and not _HAS_CYR.search(value):
        return {"ru": to_russian, "tg": to_tajik, "kk": to_kazakh}[lang](value)
    return value
