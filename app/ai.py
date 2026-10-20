"""Claude bilan ishlash: tabrik matnini yozish va saytni so'rov bo'yicha tahrirlash."""

import json
import logging
import re

import anthropic

from .config import ROOT, settings
from .sites import CATEGORIES, PALETTES

log = logging.getLogger(__name__)

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or None)

COMMON_ARGS = dict(
    model=settings.ai_model,
    betas=["server-side-fallback-2026-07-01"],
    fallbacks="default",
)


class AIError(Exception):
    pass


def _text(resp) -> str:
    if resp.stop_reason == "refusal":
        raise AIError("refusal")
    return "".join(b.text for b in resp.content if b.type == "text").strip()


# Shablonlardagi t.get('kalit', 'standart matn') larni yig'ib, AI ga qaysi sarlavhalarni o'zgartirish mumkinligini ko'rsatamiz
_TEXT_KEY_RE = re.compile(r"t\.get\('(\w+)',\s*'((?:[^'\\]|\\.)*)'\)")


def text_keys(category: str) -> dict[str, str]:
    keys = {}
    for name in ("base.html", f"{category}.html"):
        src = (ROOT / "templates" / name).read_text(encoding="utf-8")
        for k in re.findall(r"t\.get\('(\w+)'", src):
            keys.setdefault(k, "")
        for k, v in _TEXT_KEY_RE.findall(src):
            keys[k] = v.replace("\\'", "'")
    return keys


WRITER_SYSTEM = """Sen o'zbek tilida yozadigan iste'dodli adib va tabrik matnlari ustasisan.
Vazifang: foydalanuvchi bergan ma'lumotlar asosida tabrik sayti uchun samimiy, ta'sirli va o'ziga xos matn yozish.

Qoidalar:
- Faqat o'zbek tilida, lotin alifbosida yoz (o', g', sh, ch harflarini to'g'ri ishlat).
- Shablon gaplardan, quruq va rasmiy iboralardan qoch. Berilgan tafsilotlarni (xarakter, xotiralar) matnga tabiiy singdir.
- 3-5 xatboshi, jami 80-160 so'z. Xatboshilarni bo'sh qator bilan ajrat.
- Imzo, sarlavha, emoji va izoh qo'shma. Faqat matnning o'zini qaytar.
- Agar ma'lumot kam bo'lsa ham, chiroyli va iliq matn yoz."""


async def write_message(category: str, answers: dict, brief: str, previous: str | None = None) -> str:
    cat = CATEGORIES[category]
    facts = {k: v for k, v in answers.items() if isinstance(v, str) and k not in ("message", "palette", "music", "password")}
    prompt = (
        f"Matn turi: {cat.ai_brief}.\n"
        f"Ma'lumotlar: {json.dumps(facts, ensure_ascii=False)}\n"
        f"Foydalanuvchi istagi va tafsilotlar: {brief or 'maxsus istak yoq'}"
    )
    if previous:
        prompt += f"\n\nOldingi variant yoqmadi, butunlay boshqacha yondashuvda yoz:\n{previous}"
    resp = await client.beta.messages.create(
        **COMMON_ARGS,
        max_tokens=8000,
        output_config={"effort": "high"},
        system=WRITER_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return _text(resp)


_KV = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
        "required": ["key", "value"],
        "additionalProperties": False,
    },
}

EDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "Foydalanuvchiga qisqa javob: nima o'zgardi (o'zbekcha, 1-2 gap)"},
        "colors": {
            "type": "object",
            "properties": {k: {"type": "string"} for k in ("bg", "surface", "primary", "accent", "text")},
            "required": ["bg", "surface", "primary", "accent", "text"],
            "additionalProperties": False,
        },
        "fields": _KV,
        "texts": _KV,
        "message": {"type": "string"},
        "features": {"type": "array", "items": {"type": "string"}},
        "photo_order": {"type": "array", "items": {"type": "integer"}},
        "custom_css": {"type": "string"},
    },
    "required": ["reply", "colors", "fields", "texts", "message", "features", "photo_order", "custom_css"],
    "additionalProperties": False,
}

EDITOR_SYSTEM = """Sen "Tayyorla" xizmatining sayt dizayneri va muharririsan. Foydalanuvchi tayyor tabrik saytini o'zgartirishni so'raydi.
Senga saytning joriy sozlamalari (JSON) beriladi. So'rovni bajarib, YANGI sozlamalarning to'liq holatini qaytar.

Nimalarni o'zgartira olasan:
- colors: hex ranglar (bg - fon, surface - kartochkalar foni, primary - asosiy rang, accent - yordamchi rang, text - matn). Kontrastga e'tibor ber: matn fonda yaxshi o'qilsin.
- fields: ism, sana, vaqt, manzil va h.k. (faqat mavjud kalitlar).
- texts: sahifadagi sarlavha va yozuvlar. Ruxsat etilgan kalitlar va ularning standart matni berilgan. Faqat o'zgartirilganlarini yoz.
- message: asosiy tabrik/taklif matni (xatboshilar \\n bilan).
- features: yoqilgan elementlar ro'yxati (faqat ruxsat etilgan kalitlardan).
- photo_order: rasmlar tartibi (indekslar). Rasmni olib tashlash uchun uning indeksini ro'yxatga kiritma. O'zgarmasa, joriy tartibni qaytar.
- custom_css: qo'shimcha CSS (shrift o'lchami, bo'shliqlar, effektlar). url(), @import va tashqi resurslar TAQIQLANADI. CSS o'zgaruvchilari: --bg --surface --primary --accent --text. Asosiy klasslar: .hero .name .card .letter .signature .countdown .gallery .btn .eyebrow .envelope .cake section.

Qoidalar:
- Faqat so'ralgan narsani o'zgartir, qolganini aynan saqla.
- So'rov imkonsiz bo'lsa (masalan, yangi bo'lim yoki video qo'shish), hech narsani o'zgartirma va reply'da muloyimlik bilan nima qilish mumkinligini tushuntir.
- Matnlar o'zbek tilida, lotin alifbosida.
- Sayt mazmuni tabrik ruhida qolsin: haqoratli, firibgarlik yoki zararli mazmun qo'shma."""


async def apply_edit(config: dict, request: str) -> tuple[dict, str]:
    category = config["category"]
    cat = CATEGORIES[category]
    current = {
        "colors": {k: config["colors"][k] for k in ("bg", "surface", "primary", "accent", "text")},
        "fields": config.get("fields", {}),
        "texts": config.get("texts", {}),
        "message": config.get("message", ""),
        "features": [k for k, on in config.get("features", {}).items() if on],
        "photos_count": len(config.get("photos", [])),
        "custom_css": config.get("custom_css", ""),
    }
    context = {
        "category": cat.title,
        "allowed_features": cat.features,
        "allowed_text_keys": text_keys(category),
        "ready_palettes": {k: {kk: vv for kk, vv in v.items() if kk != "title"} for k, v in PALETTES.items()},
    }
    resp = await client.beta.messages.create(
        **COMMON_ARGS,
        max_tokens=16000,
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": EDIT_SCHEMA}},
        system=EDITOR_SYSTEM,
        messages=[{
            "role": "user",
            "content": (
                f"Ma'lumotnoma:\n{json.dumps(context, ensure_ascii=False)}\n\n"
                f"Joriy sozlamalar:\n{json.dumps(current, ensure_ascii=False)}\n\n"
                f"Foydalanuvchi so'rovi: {request}"
            ),
        }],
    )
    data = json.loads(_text(resp))

    new = json.loads(json.dumps(config))
    hex_re = re.compile(r"^#[0-9a-fA-F]{6}$")
    for k, v in data["colors"].items():
        if hex_re.match(v):
            new["colors"][k] = v
    for kv in data["fields"]:
        if kv["key"] in new["fields"]:
            new["fields"][kv["key"]] = kv["value"]
    allowed_texts = text_keys(category)
    new["texts"] = {kv["key"]: kv["value"] for kv in data["texts"] if kv["key"] in allowed_texts}
    new["message"] = data["message"]
    enabled = set(data["features"])
    new["features"] = {k: k in enabled for k in cat.features}
    photos = config.get("photos", [])
    order = [i for i in data["photo_order"] if 0 <= i < len(photos)]
    new["photos"] = [photos[i] for i in dict.fromkeys(order)]
    new["custom_css"] = data["custom_css"][:5000]
    return new, data["reply"]


CATALOG_EDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "Foydalanuvchiga qisqa javob: nima o'zgardi (o'zbekcha, 1-2 gap)"},
        "rang": {"type": "integer", "description": "Rang raqami (ruxsat etilgan oraliqda)"},
        "data_json": {"type": "string", "description": "Saytning yangi ma'lumotlari: to'liq JSON obyekt matni"},
    },
    "required": ["reply", "rang", "data_json"],
    "additionalProperties": False,
}

CATALOG_EDITOR_SYSTEM = """Sen "Tayyorla" xizmatining muharririsan. Mijozning tayyor tabrik sayti professional shablon asosida qurilgan.
Saytning dizayni o'zgarmaydi; sen faqat uning MA'LUMOTLARINI va RANGINI o'zgartira olasan.

Senga beriladi: ruxsat etilgan maydonlar ro'yxati (kalit, nomi, turi), ranglar ro'yxati va joriy ma'lumotlar (JSON).
Vazifang: so'rovni bajarib, ma'lumotlarning TO'LIQ yangi holatini data_json ga JSON matn ko'rinishida yoz.

Qoidalar:
- Faqat ruxsat etilgan kalitlardan foydalan. Turlar: text/textarea/url/tel - satr; date - "YYYY-MM-DD"; time - "HH:MM";
  lines - satrlar ro'yxati; choice - ko'rsatilgan variantlardan biri; items - obyektlar ro'yxati (ko'rsatilgan ichki kalitlar bilan;
  csv turidagi ichki kalit - satrlar ro'yxati; index - 0 dan boshlanadigan raqam).
- Faqat so'ralgan narsani o'zgartir, qolganini aynan saqla.
- Rang so'ralsa, ranglar ro'yxatidan mosini tanla (raqami 1 dan boshlanadi), aks holda joriy rangni qoldir.
- So'rov imkonsiz bo'lsa (masalan, dizaynni yoki shriftni o'zgartirish, yangi bo'lim qo'shish), hech narsani o'zgartirma va reply'da
  muloyimlik bilan nima qilish mumkinligini tushuntir. Agar so'ralgan imkoniyat yuqori tarifda bo'lsa, shuni ayt.
- Matnlar o'zbek tilida, lotin alifbosida. Mazmun tabrik ruhida qolsin."""


async def apply_catalog_edit(config: dict, request: str) -> tuple[dict, str]:
    from .catalog import TEMPLATES, color_limit, clean_order, fields_for

    tid, tarif = config["template"], config["tarif"]
    t = TEMPLATES[tid]
    fields = [{"key": f.key, "label": f.label, "kind": f.kind, "options": f.options,
               "sub": [{"key": k, "label": lbl, "kind": kind} for k, lbl, kind in f.sub]} for f in fields_for(tid, tarif)]
    colors = {i + 1: name for i, name in enumerate(t["colors"][: color_limit(tid, tarif)])}
    resp = await client.beta.messages.create(
        **COMMON_ARGS,
        max_tokens=16000,
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": CATALOG_EDIT_SCHEMA}},
        system=CATALOG_EDITOR_SYSTEM,
        messages=[{
            "role": "user",
            "content": (
                f"Shablon: «{t['name']}» ({t['section']}), tarif: {tarif}\n"
                f"Ruxsat etilgan maydonlar:\n{json.dumps(fields, ensure_ascii=False)}\n\n"
                f"Ranglar: {json.dumps(colors, ensure_ascii=False)}\nJoriy rang: {config['rang']}\n\n"
                f"Joriy ma'lumotlar:\n{json.dumps(config.get('data', {}), ensure_ascii=False)}\n\n"
                f"Foydalanuvchi so'rovi: {request}"
            ),
        }],
    )
    out = json.loads(_text(resp))
    try:
        data = json.loads(out["data_json"])
    except (json.JSONDecodeError, TypeError):
        data = config.get("data", {})
    if not isinstance(data, dict):
        data = config.get("data", {})
    new = clean_order({"template": tid, "tarif": tarif, "rang": out.get("rang"), "data": data,
                       "photos": config.get("photos", []), "music": config.get("music")}, strict=False)
    return new, out["reply"]
