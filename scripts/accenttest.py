"""Sinov: o'zbekcha talaffuz (aksent). Bitta matn 4 xil usulda kuylanadi va adminlarga botda yuboriladi:

  1) hozirgi usul (o'zbek lotin matni, hozirgi ko'rsatmalar)
  2) kuchliroq ko'rsatmalar (ona tili o'zbek qo'shiqchi, inglizcha/ruscha/turkcha aksent taqiqlangan)
  3) 2 + matn model uchun talaffuzga moslab yozilgan (x→kh, q→k, g'→gh, o'→o)
  4) 2 + matn kirill yozuvida

Matnda model adashishi mumkin bo'lgan tovushlar ko'p: x, q, g', o', h, sh, ch, ng va tutuq belgisi.
Har biri ~30 soniya, qancha kredit ketgani yoziladi. Hech bir so'rov qayta yuborilmaydi; biri xato bersa, qolganlari davom etadi.

Ishga tushirish (serverda):  docker compose exec app python -m scripts.accenttest
Erkak ovozi bilan:            docker compose exec app python -m scripts.accenttest male
"""

import asyncio
import re
import sys

from aiogram import Bot
from aiogram.types import FSInputFile

from app import songs
from app.config import MEDIA_DIR, settings
from app.i18n import to_cyrillic

OUT = MEDIA_DIR.parent / "accenttest"

LYRICS = """[Naqorat]
Xush kelibsan, quvonchim, qo'shig'im o'zingsan
G'olib yurak bilan seni qishda ham kutganman
Xayolimda tog'lar, bog'lar, oqar shoxli daryo
Ko'nglim xursand, yuzlarimda xandon tabassum
Qadrdonim, oq yo'l tilab, qo'lingni ushlayman
Og'ir kunlar o'tib ketdi, quyosh chiqdi, xo'p
Shu'la sochgan oydek go'zal, ma'sum chehrang
Hayot g'oyat shirin, sen bilan har on"""

STRONG = ["sung in Uzbek language", "native Uzbek singer", "authentic Uzbek pronunciation", "Uzbek estrada vocal style",
          "Central Asian vocal ornamentation"]
NO_ACCENT = ["English accent", "American accent", "Russian accent", "Turkish accent"]


def phonetic(text: str) -> str:
    """Model uchun talaffuzga yaqin yozuv: inglizcha o'qilganda o'zbekchaga yaqinroq eshitiladi."""
    text = re.sub(r"([Gg])['‘’ʻʼ`]", lambda m: m.group(1) + "h", text)
    text = re.sub(r"([Oo])['‘’ʻʼ`]", r"\1", text)
    text = text.replace("x", "kh").replace("X", "Kh").replace("q", "k").replace("Q", "K")
    return re.sub(r"['‘’ʻʼ`]", "", text)


def say(msg: str) -> None:
    print(msg, flush=True)


async def used() -> int | None:
    c = await songs.credits(force=True)
    return c["used"] if c else None


async def main() -> None:
    if not settings.elevenlabs_api_key:
        return say("ELEVENLABS kaliti sozlanmagan.")
    voice = "male" if len(sys.argv) > 1 and sys.argv[1] == "male" else "female"
    plan, _, _ = songs.build_plan(songs.parse_lyrics(LYRICS), "pop", voice, [])
    base = next(c for c in plan["chunks"] if c["text"].startswith("[Chorus]"))
    header, body = base["text"].split("\n", 1)
    rest = [x for x in base["positive_styles"] if x not in ("sung in Uzbek language", "clear Uzbek pronunciation")]
    strong = {**base, "positive_styles": [*STRONG, *rest][:50], "negative_styles": [*base["negative_styles"], *NO_ACCENT][:50]}
    variants = [
        ("1) hozirgi usul", base),
        ("2) kuchli ko'rsatmalar", strong),
        ("3) kuchli + talaffuzga moslangan yozuv", {**strong, "text": header + "\n" + phonetic(body)}),
        ("4) kuchli + kirill yozuvi", {**strong, "text": header + "\n" + to_cyrillic(body)}),
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    say(f"Ovoz: {voice}, har biri {base['duration_ms'] / 1000:.0f} s")
    results = []
    for i, (name, chunk) in enumerate(variants, 1):
        before = await used()
        try:
            data = await songs.compose({"chunks": [chunk]})
        except Exception as e:  # biri xato bersa ham qolganlari sinaladi (qayta urinilmaydi)
            results.append((name, None, f"xato: {e}"))
            say(f"{name}: xato — {e}")
            continue
        after = await used()
        path = OUT / f"{i}-{voice}.mp3"
        path.write_bytes(data)
        cost = (after - before) if before is not None and after is not None else "?"
        results.append((name, path, f"{cost} kredit"))
        say(f"{name}: tayyor, {cost} kredit")

    text = ("🗣 O'zbekcha talaffuz sinovi (" + ("erkak" if voice == "male" else "ayol") + " ovozi)\n\n"
            + "\n".join(f"{n} — {c}" for n, _, c in results)
            + "\n\nMatn:\n" + LYRICS.split("\n", 1)[1]
            + "\n\n3-usulda modelga ketgan yozuv:\n" + phonetic(LYRICS.split("\n", 1)[1])
            + "\n\nQaysi biri o'zbekchaga eng yaqin? Raqamini yozib yuboring.")
    bot = Bot(settings.bot_token) if settings.bot_token else None
    if not bot:
        return say(text)
    try:
        for admin in settings.admins:
            try:
                await bot.send_message(admin, text[:4000])
                for name, path, _ in results:
                    if path:
                        await bot.send_audio(admin, FSInputFile(path, filename=path.name), title=name, performer="Talaffuz sinovi")
            except Exception as e:
                say(f"Adminga yuborib bo'lmadi ({admin}): {e}")
    finally:
        await bot.session.close()
    say(text)


if __name__ == "__main__":
    asyncio.run(main())
