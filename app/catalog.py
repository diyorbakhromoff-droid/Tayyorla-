"""Tayyor shablonlar katalogi (Standart / Premium / VIP tariflar).

Har bir shablon HTML fayl bo'lib, ma'lumotni <script id="site-config"> ichidagi JSON dan oladi.
Bu modul mijoz ma'lumotini tekshiradi, tarif cheklovlarini qo'llaydi va tayyor sahifani yig'adi.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date

from fastapi import HTTPException

from .config import MEDIA_DIR, ROOT, settings

CATALOG_DIR = ROOT / "catalog"
TEMPLATES = {t["id"]: t for t in json.loads((CATALOG_DIR / "catalog.json").read_text(encoding="utf-8"))}

SECTIONS = {
    "tugilgan-kun": "🎂 Tug'ilgan kun",
    "toy": "💍 To'y taklifnomasi",
    "sevgi": "💌 Sevgi izhori",
    "farzand": "👶 Farzand muborak",
    "uzr": "🙏 Uzrnoma",
}
# Eski kategoriyalar bilan bog'lash (AI uchun matn turi)
SECTION_TO_CATEGORY = {"tugilgan-kun": "birthday", "toy": "wedding", "sevgi": "love", "farzand": "baby", "uzr": "apology"}

TIERS = {
    "standart": {"level": 1, "title": "Standart", "colors": 3, "photos": 6,
                 "features": ["3 ta rang", "Ism, sana, tabrik matni va dizayn interaktivi",
                              "Fon musiqasi, jonli taymer va 6 tagacha surat", "Tilaklar ro'yxati va uchib yuruvchi effektlar"]},
    "premium": {"level": 2, "title": "Premium", "colors": 10, "photos": 40,
                "features": ["10 ta rang", "Kirish animatsiyasi (konvert, sovg'a, muhr yoki eshik)",
                             "Hikoya, sirli xabar, test va video", "Reklama yozuvisiz, 40 tagacha surat"]},
    "vip": {"level": 3, "title": "VIP", "colors": 15, "photos": 40,
            "features": ["15 ta rang", "Premiumdagi hamma narsa", "«Maktub» to'plamidagi VIP shablonlar",
                         "Muhrli konvert, kalendar, anketa, sirpanuvchi yurak"]},
}


def tier_price(tarif: str) -> int:
    return {"standart": settings.price_standart, "premium": settings.price_premium, "vip": settings.price_vip}[tarif]


@dataclass
class Field:
    key: str
    label: str
    kind: str = "text"  # text | textarea | date | time | choice | lines | url | tel | photo | items
    required: bool = False
    tier: int = 1  # qaysi tarifdan boshlab: 1 standart, 2 premium, 3 vip
    only: tuple = ()  # faqat shu shablonlarda
    options: dict | None = None
    sub: list = field(default_factory=list)  # items uchun: [(kalit, nom, tur)]
    hint: str = ""
    ai: bool = False  # AI yozib berishi mumkin


STORY = Field("hikoya", "📖 Esda qolgan kunlar (hikoya)", "items", tier=2,
              sub=[("sana", "Yil yoki sana", "text"), ("sarlavha", "Sarlavha", "text"), ("matn", "Qisqa matn", "text")],
              hint="Vaqt chizig'i ko'rinishida chiqadi")
SECRET = Field("sirli_xabar", "🔒 Sirli xabar", "textarea", tier=2, hint="Ustini o'chirib o'qiladi")
QUIZ = Field("savollar", "❓ Xotiralar testi", "items", tier=2,
             sub=[("savol", "Savol", "text"), ("javoblar", "3 ta javob (vergul bilan)", "csv"), ("togri", "To'g'ri javob raqami (1-3)", "index")])
VIDEO = Field("video", "🎬 Video (YouTube havolasi)", "url", tier=2)

FIELDS: dict[str, list[Field]] = {
    "tugilgan-kun": [
        Field("kimga", "Kimni tabriklaymiz?", required=True),
        Field("kimdan", "Tabrik kimdan?", required=True, hint="Masalan: «Sevimli o'g'ling Sardor»"),
        Field("murojaat", "Murojaat", "choice", options={"sen": "«Sen» deb", "siz": "«Siz» deb"}),
        Field("sana", "Bayram sanasi", "date", required=True),
        Field("tugilgan_sana", "Tug'ilgan sanasi (yoshini hisoblaydi)", "date"),
        Field("matn", "Tabrik matni", "textarea", required=True, ai=True),
        Field("royxat", "Tilaklar ro'yxati", "lines", hint="Har birini yangi qatordan"),
        Field("tilaklar", "Qisqa tilaklar (1-2 so'z)", "lines", hint="Masalan: Baxt, Omad, Sog'lik"),
        STORY, SECRET, QUIZ, VIDEO,
    ],
    "toy": [
        Field("yuqori_matn", "Eng yuqoridagi yozuv", only=("toy-milliy",), hint="Masalan: «Bismillahir Rohmanir Rohiym»"),
        Field("kuyov", "Kuyovning ismi", required=True),
        Field("kelin", "Kelinning ismi", required=True),
        Field("sana", "To'y sanasi", "date", required=True),
        Field("vaqt", "Boshlanish vaqti", "time", required=True),
        Field("manzil_nomi", "To'yxona nomi", required=True),
        Field("manzil", "Manzil", required=True),
        Field("xarita", "Xarita havolasi (Google yoki Yandex)", "url"),
        Field("taklif_qiluvchilar", "Taklif qiluvchilar", hint="Masalan: «Karimovlar oilasi»"),
        Field("kimdan", "Imzo", hint="Masalan: «Jasur va Malika»"),
        Field("matn", "Taklif matni", "textarea", required=True, ai=True),
        Field("telefon", "Aloqa uchun telefon", "tel"),
        Field("dastur", "🗓 To'y dasturi", "items", tier=2, sub=[("vaqt", "Vaqt", "time"), ("nomi", "Nima bo'ladi", "text"), ("izoh", "Izoh", "text")]),
        STORY, SECRET, VIDEO,
        Field("kimga", "Mehmon ismi (shaxsiy taklif)", tier=3, only=("toy-maktub",)),
        Field("joy_rasmi", "To'yxona surati", "photo", tier=3, only=("toy-maktub",)),
        Field("istaklar", "💐 Mehmonlarga iltimoslar", "items", tier=3, only=("toy-maktub",), sub=[("sarlavha", "Sarlavha", "text"), ("matn", "Matn", "text")]),
        Field("anketa_savollar", "📋 Anketa savollari", "items", tier=3, only=("toy-maktub",), sub=[("savol", "Savol", "text"), ("variantlar", "Variantlar (vergul bilan)", "csv")]),
        Field("anketa_muddat", "Anketaga javob berish muddati", "date", tier=3, only=("toy-maktub",)),
        Field("telegram_guruh", "Mehmonlar Telegram guruhi havolasi", "url", tier=3, only=("toy-maktub",)),
    ],
    "sevgi": [
        Field("kimga", "Kimga?", required=True),
        Field("kimdan", "Kimdan?", required=True),
        Field("tanishgan_sana", "Tanishgan kuningiz", "date"),
        Field("sana", "Bugungi (bayram) sana", "date"),
        Field("matn", "Sevgi izhori", "textarea", required=True, ai=True),
        Field("royxat", "Seni sevishimning sabablari", "lines", hint="Har birini yangi qatordan"),
        STORY, SECRET, QUIZ, VIDEO,
    ],
    "farzand": [
        Field("jins", "O'g'il yoki qiz?", "choice", required=True, options={"ogil": "👦 O'g'il", "qiz": "👧 Qiz"}),
        Field("chaqaloq", "Chaqaloqning ismi"),
        Field("kimga", "Ota-onasi", required=True, hint="Masalan: «Bekzod va Dilnoza»"),
        Field("kimdan", "Tabrik kimdan?", required=True),
        Field("sana", "Tug'ilgan sanasi", "date", required=True),
        Field("vaqt", "Tug'ilgan vaqti", "time"),
        Field("vazn", "Vazni", hint="Masalan: 3,4 kg"),
        Field("boy", "Bo'yi", hint="Masalan: 51 sm"),
        Field("matn", "Tabrik matni", "textarea", required=True, ai=True),
        Field("royxat", "Tilaklar ro'yxati", "lines", hint="Har birini yangi qatordan"),
        STORY, SECRET, QUIZ, VIDEO,
    ],
    "uzr": [
        Field("kimga", "Kimdan uzr so'raysiz?", required=True),
        Field("kimdan", "Ismingiz", required=True),
        Field("uzr_sana", "Sana", "date"),
        Field("matn", "Uzr matni", "textarea", required=True, ai=True),
        Field("javob_matni", "«Kechiraman» bosilganda chiqadigan so'z", hint="Masalan: «Rahmat! So'zimda turaman»"),
        Field("royxat", "Va'dalarim", "lines", hint="Har birini yangi qatordan"),
        STORY, SECRET, QUIZ, VIDEO,
    ],
}


def fields_for(template_id: str, tarif: str) -> list[Field]:
    t = TEMPLATES[template_id]
    level = TIERS[tarif]["level"]
    return [f for f in FIELDS[t["section"]] if f.tier <= level and (not f.only or template_id in f.only)]


def color_limit(template_id: str, tarif: str) -> int:
    return min(len(TEMPLATES[template_id]["colors"]), TIERS[tarif]["colors"])


# ---------------------------------------------------------------- tekshirish

def _own_media(path) -> bool:
    if not isinstance(path, str):
        return False
    name = path.removeprefix("/media/")
    return path.startswith("/media/") and "/" not in name and (MEDIA_DIR / name).is_file()


def _text(v, limit=300) -> str:
    return str(v).strip()[:limit] if v not in (None, "") else ""


def _clean_value(f: Field, v):
    if f.kind == "date":
        v = _text(v, 20)
        if not v:
            return None
        try:
            return date.fromisoformat(v).isoformat()
        except ValueError:
            raise HTTPException(400, f"Sana noto'g'ri: {f.label}")
    if f.kind == "time":
        v = _text(v, 5)
        if v and not re.fullmatch(r"\d{1,2}:\d{2}", v):
            raise HTTPException(400, f"Vaqt noto'g'ri: {f.label}")
        return v or None
    if f.kind == "choice":
        return v if v in (f.options or {}) else None
    if f.kind == "textarea":
        return _text(v, 3000) or None
    if f.kind == "lines":
        items = v if isinstance(v, list) else str(v or "").split("\n")
        items = [_text(x, 200) for x in items if _text(x, 200)]
        return items[:20] or None
    if f.kind == "url":
        v = _text(v, 500)
        return v if re.match(r"^https://", v) else None
    if f.kind == "photo":
        return v if _own_media(v) else None
    if f.kind == "items":
        out = []
        for item in (v if isinstance(v, list) else [])[:20]:
            if not isinstance(item, dict):
                continue
            row = {}
            for key, _, kind in f.sub:
                x = item.get(key)
                if kind == "csv":
                    parts = x if isinstance(x, list) else str(x or "").split(",")
                    row[key] = [_text(p, 100) for p in parts if _text(p, 100)][:6]
                elif kind == "index":
                    try:
                        row[key] = max(0, int(x))
                    except (TypeError, ValueError):
                        row[key] = 0
                else:
                    row[key] = _text(x, 300)
            if any(row.get(k) for k, _, kind in f.sub if kind not in ("index",)):
                out.append(row)
        if f.key == "savollar":
            out = [q for q in out if q.get("savol") and len(q.get("javoblar", [])) >= 2]
            for q in out:
                q["togri"] = min(q["togri"], len(q["javoblar"]) - 1)
        return out or None
    return _text(v) or None


def clean_order(body: dict, strict: bool) -> dict:
    """Mini App yoki AI dan kelgan buyurtmani tekshirib, saqlanadigan konfiguratsiyaga aylantiradi."""
    tid = body.get("template")
    if tid not in TEMPLATES:
        raise HTTPException(400, "Noma'lum shablon")
    t = TEMPLATES[tid]
    tarif = body.get("tarif") if body.get("tarif") in TIERS else "premium"
    if t["vip"] and tarif != "vip":
        raise HTTPException(400, "Bu shablon faqat VIP tarifda")
    if t.get("premium") and tarif == "standart":
        raise HTTPException(400, "Bu dizayn Premium va VIP tarifda")
    try:
        rang = int(body.get("rang") or 1)
    except (TypeError, ValueError):
        rang = 1
    rang = rang if 1 <= rang <= color_limit(tid, tarif) else 1
    raw = body.get("data") if isinstance(body.get("data"), dict) else {}
    data = {}
    for f in fields_for(tid, tarif):
        v = _clean_value(f, raw.get(f.key))
        if v is not None:
            data[f.key] = v
        elif strict and f.required:
            raise HTTPException(400, f"To'ldirilmagan: {f.label}")
    photos = [p for p in (body.get("photos") or []) if _own_media(p)][: TIERS[tarif]["photos"]]
    music = body.get("music") if _own_media(body.get("music")) else None
    out = {"engine": "catalog", "category": SECTION_TO_CATEGORY[t["section"]], "template": tid,
           "tarif": tarif, "rang": rang, "data": data, "photos": photos, "music": music}
    if body.get("unlock_at"):
        from .surprise import clean_unlock
        unlock = clean_unlock(body["unlock_at"])
        if unlock:
            out["unlock_at"] = unlock
        elif strict:
            raise HTTPException(400, "Syurpriz vaqti o'tib ketgan — boshqa vaqt tanlang")
    return out


# ---------------------------------------------------------------- sahifani yig'ish

_CONFIG_RE = re.compile(r'(<script id="site-config" type="application/json">)(.*?)(</script>)', re.S)

WATERMARK = """
<style>
.tyr-wm-bar{position:fixed;top:0;left:0;right:0;z-index:2147483646;background:#111;color:#fff;text-align:center;
 font:600 13px/1.4 system-ui,sans-serif;padding:9px 12px}
.tyr-wm{position:fixed;inset:-50%;z-index:2147483645;pointer-events:none;transform:rotate(-24deg);display:flex;flex-wrap:wrap;
 align-content:center;justify-content:center;gap:60px 80px;opacity:.12;font:800 34px/1 system-ui,sans-serif;color:#000;
 text-shadow:0 0 2px #fff;user-select:none}
</style>
<div class="tyr-wm-bar">👀 Bu NAMUNA. To'liq versiya to'lovdan so'ng ochiladi — @{bot}</div>
<div class="tyr-wm">{marks}</div>
"""


def _safe_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")


# Katalog dizaynlaridagi «Albatta boraman / Afsuski, bora olmayman» tugmalari javobni serverga yuborishi uchun.
# Shablon o'zi «Rahmat» xabarini ko'rsatadi; bu skript uning ostiga ism va kishilar sonini so'rab, /rsvp ga yuboradi.
RSVP_SCRIPT = """<script>(function(){var U=__URL__,G=__GUEST__;
function send(box,going,name,n){var b=box.querySelector('.tyr-send');if(b){b.disabled=true;}
fetch(U,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name,attending:going?'yes':'no',guests:n,g:G&&G.t})})
.then(function(r){if(!r.ok)throw 0;box.innerHTML='<p class="tyr-ok" style="margin:10px 0 0;font-weight:600">✓ Javobingiz yetkazildi</p>';})
.catch(function(){if(b){b.disabled=false;}var e=box.querySelector('.tyr-err');if(e)e.hidden=false;});}
document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('.rsvp [data-a]');if(!b)return;
var going=b.getAttribute('data-a')==='ha',root=b.closest('.rsvp');setTimeout(function(){var done=root.querySelector('.rsvp-done');if(!done||done.querySelector('.tyr-rsvp'))return;
var box=document.createElement('form');box.className='tyr-rsvp';box.style.cssText='margin-top:12px;display:grid;gap:8px;text-align:left';
var st='width:100%;min-height:46px;padding:0 12px;border-radius:12px;border:1.5px solid currentColor;background:transparent;color:inherit;font:inherit;opacity:.95';
box.innerHTML=(G?'':'<input name="n" maxlength="100" placeholder="Ismingiz" aria-label="Ismingiz" style="'+st+'">')+
(going?'<label style="display:flex;align-items:center;justify-content:space-between;gap:8px">Necha kishi bo‘lasiz?<input name="p" type="number" min="1" max="20" value="1" style="'+st+';width:84px"></label>':'')+
'<button type="submit" class="tyr-send" style="min-height:46px;border-radius:12px;border:0;font:inherit;font-weight:700;cursor:pointer;background:var(--accent,#D02670);color:var(--on-accent,#fff)">Javobni yuborish</button>'+
'<p class="tyr-err" hidden style="margin:0;font-size:14px">Yuborilmadi, qayta urinib ko‘ring.</p>';
box.onsubmit=function(ev){ev.preventDefault();var nm=G?G.n:(box.n.value||'').trim();if(!nm){box.n.focus();return;}send(box,going,nm,going?Math.max(1,Math.min(20,+(box.p&&box.p.value)||1)):1);};
done.appendChild(box);},0);},true);})();</script>"""


def render_catalog(config: dict, slug: str, preview: bool, guest=None) -> str:
    t = TEMPLATES[config["template"]]
    html = (CATALOG_DIR / "namuna" / t["file"]).read_text(encoding="utf-8")
    cfg = dict(config.get("data", {}))
    if guest is not None:
        cfg["kimga"] = guest.name
    cfg.update({
        "tarif": config["tarif"],
        "rang": config["rang"],
        "demo": False,
        "rasmlar": config.get("photos", []),
        "brend": {"matn": "Siz ham shunday sayt yarating", "havola": f"https://t.me/{settings.bot_username}"},
    })
    if config.get("music"):
        cfg["musiqa"] = config["music"]
    if t["vip"] and t["section"] == "toy":
        cfg["anketa_url"] = f"{settings.base_url}/s/{slug}/anketa" + (f"?g={guest.token}" if guest is not None else "")
    html = _CONFIG_RE.sub(lambda m: m.group(1) + _safe_json(cfg) + m.group(3), html, count=1)
    if not preview and "rsvp-done" in html:
        script = RSVP_SCRIPT.replace("__URL__", _safe_json(f"/s/{slug}/rsvp")).replace(
            "__GUEST__", _safe_json({"t": guest.token, "n": guest.name} if guest is not None else None))
        html = html.replace("</body>", script + "</body>", 1)
    if preview:
        html = html.replace("<head>", '<head><meta name="robots" content="noindex">', 1)
        mark = WATERMARK.replace("{bot}", settings.bot_username).replace("{marks}", "<span>NAMUNA • TAYYORLA</span>" * 40)
        html = html.replace("</body>", mark + "</body>", 1)
    return html


# ---------------------------------------------------------------- Mini App uchun ma'lumot

def catalog_meta() -> dict:
    def fdict(f: Field) -> dict:
        return {"key": f.key, "label": f.label, "kind": f.kind, "required": f.required, "tier": f.tier,
                "only": list(f.only), "options": f.options, "sub": f.sub, "hint": f.hint, "ai": f.ai}

    return {
        "sections": [{"key": k, "title": v} for k, v in SECTIONS.items()],
        "templates": [
            {"id": t["id"], "section": t["section"], "name": t["name"], "desc": t["desc"], "vip": t["vip"],
             "premium": t.get("premium", False), "new": t.get("new", False),
             "colors": t["colors"], "swatch": t["swatch"], "thumb": f"/katalog/thumb/{t['id']}.jpg",
             "demo": f"/katalog/namuna/{t['file']}"}
            for t in TEMPLATES.values()
        ],
        "tiers": [{"key": k, **{kk: vv for kk, vv in v.items()}, "price": tier_price(k)} for k, v in TIERS.items()],
        "fields": {s: [fdict(f) for f in fs] for s, fs in FIELDS.items()},
        "relations": [{"key": k, **v} for k, v in RELATIONS.items()],
    }


# ---------------------------------------------------------------- bot uchun yordamchilar

def site_price(config: dict) -> int:
    if config.get("engine") == "video":
        return settings.video_price
    return tier_price(config["tarif"]) if config.get("engine") == "catalog" else settings.price


def site_title(config: dict) -> str:
    if config.get("engine") == "video":
        from .video import SECTION_EMOJI, event_title
        sec, data = config.get("section", "toy"), config.get("data", {})
        who = " & ".join(x for x in (data.get("kuyov"), data.get("kelin")) if x) or data.get("ism") or ""
        return f"{SECTION_EMOJI.get(sec, '✨')} {event_title(sec, data, 'uz')}" + (f" • {who}" if who else "")
    if config.get("engine") == "catalog":
        t = TEMPLATES[config["template"]]
        return f"{SECTIONS[t['section']]} • «{t['name']}» • {TIERS[config['tarif']]['title']}"
    from .sites import CATEGORIES
    return CATEGORIES[config["category"]].title


def photo_limit(config: dict) -> int:
    if config.get("engine") == "video":
        return 1
    return TIERS[config["tarif"]]["photos"] if config.get("engine") == "catalog" else 10


# ---------------------------------------------------------------- «Kim uchun?» tavsiyalari

RELATIONS: dict[str, dict] = {
    "ona": {"title": "Onam", "emoji": "🌷", "kimga": "Onajonim", "tone": "onasiga, chuqur minnatdorlik va mehr bilan",
            "picks": ["tk-oltin", "tk-salyut", "tk-polaroid", "tk-tort", "tk-maktub"], "why": "Mehrini eslatadigan, iliq dizaynlar"},
    "ota": {"title": "Otam", "emoji": "🕊️", "kimga": "Otajonim", "tone": "otasiga, hurmat va faxr bilan, ortiqcha his-tuyg'usiz",
            "picks": ["tk-oltin", "tk-salyut", "tk-maktub", "tk-polaroid"], "why": "Salobatli va hurmatli uslub"},
    "jufti": {"title": "Turmush o'rtog'im", "emoji": "💞", "kimga": "", "tone": "turmush o'rtog'iga, sevgi va birga o'tgan yillar haqida",
              "picks": ["sv-yurak", "sv-hikoya", "sv-konvert", "sv-maktub", "tk-polaroid", "uz-kechir"], "why": "Birga bosib o'tgan yo'lingiz haqida"},
    "sevgili": {"title": "Sevgilim", "emoji": "❤️", "kimga": "", "tone": "sevgilisiga, romantik va samimiy",
                "picks": ["sv-yurak", "sv-yulduz", "sv-atirgul", "sv-konvert", "sv-maktub", "uz-ayiqcha"], "why": "Yuragini titratadigan izhorlar"},
    "farzand": {"title": "Farzandim", "emoji": "🧸", "kimga": "", "tone": "farzandiga, quvnoq va g'ururli",
                "picks": ["tk-salyut", "tk-sharlar", "tk-tort", "tk-polaroid", "fz-bulut"], "why": "Quvnoq, rang-barang va o'yinli"},
    "qarindosh": {"title": "Aka-uka, opa-singil", "emoji": "🤝", "kimga": "", "tone": "aka-uka yoki opa-singilga, samimiy va biroz hazil bilan",
                  "picks": ["tk-salyut", "tk-sharlar", "tk-polaroid", "tk-tort"], "why": "Bolalikdan beri birga — shunday tabrik ham"},
    "dost": {"title": "Do'stim", "emoji": "🎈", "kimga": "", "tone": "do'stiga, quvnoq va hazilomuz",
             "picks": ["tk-salyut", "tk-sharlar", "tk-polaroid", "uz-ayiqcha", "tk-tort"], "why": "Kuldiradigan va esda qoladigan"},
    "hamkasb": {"title": "Hamkasbim", "emoji": "💼", "kimga": "", "tone": "hamkasbiga, hurmatli va iliq, rasmiyroq",
                "picks": ["tk-oltin", "tk-salyut", "tk-sharlar"], "why": "Ishxonada ham chiroyli ko'rinadigan"},
    "ustoz": {"title": "Ustozim", "emoji": "📚", "kimga": "Hurmatli ustozim", "tone": "ustoziga, chuqur hurmat va minnatdorlik bilan",
              "picks": ["tk-oltin", "tk-maktub", "tk-polaroid"], "why": "Minnatdorlikni munosib ifodalaydigan"},
    "mehmonlar": {"title": "To'yga mehmonlar", "emoji": "💍", "kimga": "", "tone": "to'yga taklif, rasmiy va samimiy",
                  "picks": ["toy-parda", "toy-maktub", "toy-milliy", "toy-klassik", "toy-gullar", "toy-minimal"], "why": "Taklifnoma, xarita va mehmonlar javobi bilan"},
}
for _r in RELATIONS.values():
    assert all(t in TEMPLATES for t in _r["picks"]), _r
