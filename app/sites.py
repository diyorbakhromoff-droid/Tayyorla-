"""Kategoriyalar, ularning savollari, rang palitralari va qo'shimcha elementlar.

Yangi kategoriya qo'shish uchun CATEGORIES ga yozuv qo'shib, templates/ ichida
<kalit>.html shablonini yaratish kifoya.
"""

from dataclasses import dataclass, field

PALETTES: dict[str, dict] = {
    "atirgul": {"title": "🌸 Atirgul", "bg": "#fff5f7", "surface": "#ffffff", "primary": "#d6336c", "accent": "#f8b4cb", "text": "#4a1d2e"},
    "oltin": {"title": "✨ Oltin tun", "bg": "#15110d", "surface": "#221b14", "primary": "#d4af37", "accent": "#8a6d1f", "text": "#f5efe3"},
    "osmon": {"title": "🩵 Osmon", "bg": "#f1f7ff", "surface": "#ffffff", "primary": "#2563eb", "accent": "#a5c8ff", "text": "#0f2a4a"},
    "yalpiz": {"title": "🌿 Yalpiz", "bg": "#f0faf6", "surface": "#ffffff", "primary": "#0f8a68", "accent": "#a7e3cc", "text": "#0b3b2e"},
    "lavanda": {"title": "💜 Lavanda", "bg": "#f7f3ff", "surface": "#ffffff", "primary": "#7c3aed", "accent": "#cdbcff", "text": "#2e1a52"},
    "shaftoli": {"title": "🍑 Shaftoli", "bg": "#fff6ef", "surface": "#ffffff", "primary": "#e0590f", "accent": "#ffc79b", "text": "#4a2511"},
}


@dataclass
class Step:
    key: str
    prompt: str
    kind: str = "text"  # text | number | date | time | location | choice | message | photos | music | palette | features
    optional: bool = False
    options: dict[str, str] | None = None  # choice uchun: qiymat -> tugma nomi


@dataclass
class Category:
    key: str
    title: str
    intro: str
    steps: list[Step]
    features: dict[str, str]  # kalit -> tugma nomi
    default_features: list[str]
    default_palette: str
    ai_brief: str  # AI ga matn turi haqida ko'rsatma
    extra: dict = field(default_factory=dict)


COMMON_TAIL = [
    Step("photos", "📸 Rasmlarni yuboring (10 tagacha). Tugatgach «✅ Tayyor» ni bosing.\nRasmsiz davom etish ham mumkin.", "photos", optional=True),
    Step("music", "🎵 Fon musiqasi uchun audio fayl (mp3) yuboring yoki o'tkazib yuboring.", "music", optional=True),
    Step("palette", "🎨 Sayt qaysi ranglarda bo'lsin?\n\n"
         "🌸 Atirgul — oq-pushti, nozik\n✨ Oltin tun — qora fon, oltin yozuvlar (hashamatli)\n"
         "🩵 Osmon — och havorang va ko'k\n🌿 Yalpiz — och yashil, tabiiy\n"
         "💜 Lavanda — och binafsha, romantik\n🍑 Shaftoli — iliq sarg'ish-sabzirang\n\n"
         "Keyinroq «Tahrirlash» orqali istalgan rangga o'zgartirish mumkin.", "palette"),
    Step("features", "🪄 Saytga qaysi elementlar qo'shilsin? Bosib yoqing/o'chiring, so'ng «✅ Tayyor».", "features"),
]

CATEGORIES: dict[str, Category] = {
    "birthday": Category(
        key="birthday",
        title="🎂 Tug'ilgan kun tabrigi",
        intro="Ajoyib! Tug'ilgan kun tabrigini birga tayyorlaymiz 🎉",
        steps=[
            Step("name", "👤 Kimning tug'ilgan kuni? Ismini yozing:"),
            Step("age", "🔢 Necha yoshga to'lyapti? (raqam yozing yoki o'tkazib yuboring)", "number", optional=True),
            Step("date", "📅 Tug'ilgan kun sanasi (masalan: 25.12.2026):", "date"),
            Step("sender", "✍️ Tabrik kimdan? (masalan: «Sevimli o'g'ling Sardor» yoki «Do'stlaring»)"),
            Step("message", "💬 Tabrik matni:", "message"),
            *COMMON_TAIL,
        ],
        features={
            "envelope": "✉️ Konvertni ochish",
            "confetti": "🎊 Konfetti",
            "balloons": "🎈 Uchuvchi sharlar",
            "countdown": "⏳ Sanagacha taymer",
            "cake": "🕯 Shamni puflash",
            "gallery": "🖼 Rasm galereyasi",
        },
        default_features=["envelope", "confetti", "balloons", "cake", "gallery"],
        default_palette="atirgul",
        ai_brief="tug'ilgan kun tabrigi",
    ),
    "wedding": Category(
        key="wedding",
        title="💍 To'y taklifnomasi",
        intro="Tabriklaymiz! Chiroyli to'y taklifnomasini tayyorlaymiz 💍",
        steps=[
            Step("groom", "🤵 Kuyovning ismi:"),
            Step("bride", "👰 Kelinning ismi:"),
            Step("date", "📅 To'y sanasi (masalan: 12.06.2027):", "date"),
            Step("time", "🕖 To'y vaqti (masalan: 18:00):", "time"),
            Step("venue", "🏛 To'yxona nomi:"),
            Step("address", "📍 Manzilni yozing yoki Telegram orqali 📎 → Joylashuv yuboring:", "location"),
            Step("hosts", "👨‍👩‍👧 Taklif qiluvchilar (masalan: «Karimovlar oilasi»):", optional=True),
            Step("message", "💬 Taklif matni:", "message"),
            *COMMON_TAIL,
        ],
        features={
            "envelope": "✉️ Konvertni ochish",
            "petals": "🌸 Yog'ayotgan gulbarglar",
            "countdown": "⏳ To'ygacha taymer",
            "map": "🗺 Xarita tugmasi",
            "rsvp": "✅ Mehmonlar javobi (RSVP)",
            "gallery": "🖼 Rasm galereyasi",
        },
        default_features=["envelope", "petals", "countdown", "map", "rsvp", "gallery"],
        default_palette="oltin",
        ai_brief="to'yga taklifnoma matni (rasmiy, samimiy, o'zbek an'analariga mos)",
    ),
    "love": Category(
        key="love",
        title="💌 Sevgiliga xat",
        intro="Qanday romantik! Unutilmas sevgi maktubini tayyorlaymiz 💌",
        steps=[
            Step("name", "💖 Xat kimga? Uning ismini (yoki erkalab chaqiradigan ismini) yozing:"),
            Step("sender", "✍️ Xat kimdan? Ismingiz:"),
            Step("date", "📅 Birinchi tanishgan kuningiz (masalan: 14.02.2024) — «birga o'tgan kunlar» hisoblanadi:", "date", optional=True),
            Step("message", "💬 Sevgi maktubi:", "message"),
            Step("password", "🔐 Saytni maxfiy parol bilan yopaylikmi? Parolni yozing (masalan, birinchi uchrashgan joyingiz) yoki o'tkazib yuboring.", optional=True),
            *COMMON_TAIL,
        ],
        features={
            "envelope": "✉️ Konvertni ochish",
            "hearts": "💕 Uchuvchi yuraklar",
            "together": "⏱ Birga o'tgan vaqt",
            "question": "😍 «Meni sevasanmi?» o'yini",
            "gallery": "🖼 Rasm galereyasi",
        },
        default_features=["envelope", "hearts", "together", "question", "gallery"],
        default_palette="atirgul",
        ai_brief="sevgilisiga romantik maktub",
    ),
    "baby": Category(
        key="baby",
        title="👶 Farzand muborak",
        intro="Qanday quvonchli xabar! Chaqaloq tug'ilgani munosabati bilan tabrik tayyorlaymiz 👶",
        steps=[
            Step("gender", "👶 O'g'il yoki qiz?", "choice", options={"boy": "👦 O'g'il", "girl": "👧 Qiz"}),
            Step("baby_name", "🍼 Chaqaloqning ismi (hali qo'yilmagan bo'lsa, o'tkazib yuboring):", optional=True),
            Step("parents", "👨‍👩‍👧 Ota-onasi kimlar? (masalan: «Jasur va Nilufar» yoki «Karimovlar oilasi»)"),
            Step("date", "📅 Tug'ilgan sanasi (masalan: 19.10.2026):", "date"),
            Step("stats", "⚖️ Vazni va bo'yi (masalan: «3.4 kg, 52 sm») yoki o'tkazib yuboring:", optional=True),
            Step("sender", "✍️ Tabrik kimdan? (masalan: «Buvi va bobosi», «Do'stlaringiz»)"),
            Step("message", "💬 Tabrik matni:", "message"),
            *COMMON_TAIL,
        ],
        features={
            "envelope": "✉️ Konvertni ochish",
            "stars": "⭐ Uchuvchi yulduzchalar",
            "balloons": "🎈 Uchuvchi sharlar",
            "confetti": "🎊 Konfetti",
            "since": "⏱ Dunyoga kelganiga ... kun",
            "gallery": "🖼 Rasm galereyasi",
        },
        default_features=["envelope", "stars", "balloons", "since", "gallery"],
        default_palette="osmon",
        ai_brief="farzand (chaqaloq) tug'ilgani munosabati bilan ota-onaga tabrik, chaqaloqqa duo va ezgu tilaklar",
    ),
    "apology": Category(
        key="apology",
        title="🙏 Uzrnoma",
        intro="Kechirim so'rash — kuchli insonlarning ishi 🤍 Chiroyli uzrnoma tayyorlaymiz.",
        steps=[
            Step("name", "💌 Kimdan uzr so'rayapsiz? Uning ismini yozing:"),
            Step("sender", "✍️ Ismingiz:"),
            Step("message", "💬 Uzr matni:", "message"),
            Step("promises", "🤞 Va'dalaringizni yozing — har birini yangi qatordan (masalan: «Endi kech qolmayman»). Yoki o'tkazib yuboring:", optional=True),
            *COMMON_TAIL,
        ],
        features={
            "envelope": "✉️ Konvertni ochish",
            "question": "🥺 «Kechirasanmi?» o'yini",
            "hearts": "💕 Uchuvchi yuraklar",
            "gallery": "🖼 Rasm galereyasi",
        },
        default_features=["envelope", "question", "hearts", "gallery"],
        default_palette="lavanda",
        ai_brief="samimiy uzrnoma (kechirim so'rash xati): aybni tan olish, afsus, qadrlash va yaxshi tomonga o'zgarish istagi, haddan tashqari dramasiz",
    ),
}


def build_config(category: str, answers: dict) -> dict:
    cat = CATEGORIES[category]
    palette = answers.get("palette") or cat.default_palette
    return {
        "category": category,
        "palette": palette,
        "colors": {k: v for k, v in PALETTES[palette].items() if k != "title"},
        "fields": {
            **{s.key: answers.get(s.key) for s in cat.steps if s.kind not in ("photos", "music", "palette", "features", "message")},
            **{k: answers[k] for k in ("lat", "lon") if answers.get(k)},
        },
        "message": answers.get("message", ""),
        "photos": answers.get("photos", []),
        "music": answers.get("music"),
        "features": {k: k in answers.get("features", cat.default_features) for k in cat.features},
        "texts": {},
        "custom_css": "",
    }
