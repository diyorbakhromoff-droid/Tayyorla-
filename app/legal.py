"""Ommaviy oferta va maxfiylik siyosati (to'lov tizimlarini ulash uchun talab qilinadi).

Sahifalar: /oferta va /maxfiylik. Narxlar sozlamalardan olinadi, shuning uchun hujjat har doim amaldagi narxni ko'rsatadi.
Murojaat uchun: Telegram bot va Ijrochining e-pochtasi.
"""

import html

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from .config import settings

router = APIRouter()

EDITION = "17.11.2026"
SELLER = "YATT Baxromov Diyorbek Ulug‘bek o‘g‘li"
PINFL = "52401026300010"
EMAIL = "diyorbakhromoff@gmail.com"


def _money(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " so‘m"


def _site() -> str:
    return settings.base_url.rstrip("/")


def requisites() -> str:
    rows = [
        ("Ijrochi", SELLER),
        ("JSHSHIR", PINFL),
        ("Xizmat", f"Tayyorla — Telegram bot @{settings.bot_username} va {_site()}"),
    ]
    rows.append(("E-pochta", EMAIL))
    rows.append(("Murojaat", f"Telegram: @{settings.bot_username} (/help)"))
    return "<table class='req'>" + "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>" for k, v in rows) + "</table>"


def _prices() -> str:
    song = settings.song_price
    items = [
        ("Tabrik / taklifnoma sayti — Standart tarif", _money(settings.price_standart)),
        ("Tabrik / taklifnoma sayti — Premium tarif", _money(settings.price_premium)),
        ("Tabrik / taklifnoma sayti — VIP tarif", _money(settings.price_vip)),
        ("Shaxsiy qo‘shiq (to‘liq versiya)", _money(song)),
        (f"Video taklifnoma (kuniga {settings.free_videos_per_day} tasi bepul, keyingilari)", _money(settings.video_price)),
    ]
    return "<table class='req'>" + "".join(f"<tr><th>{html.escape(k)}</th><td>{v}</td></tr>" for k, v in items) + "</table>"


CSS = """
:root{--bg:#f7f5fb;--card:#fff;--ink:#1d1830;--muted:#6b6580;--line:#e6e1f0;--acc:#7a3cff}
@media (prefers-color-scheme:dark){:root{--bg:#14121c;--card:#1d1a28;--ink:#eeeaf7;--muted:#a49cbb;--line:#2e2a3d;--acc:#b79bff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:760px;margin:0 auto;padding:28px 16px 64px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px 20px}
h1{font-size:26px;line-height:1.25;margin:0 0 4px}h2{font-size:18px;margin:28px 0 8px}
.meta{color:var(--muted);font-size:14px;margin:0 0 18px}p,li{margin:6px 0}ol,ul{padding-left:22px}
a{color:var(--acc)}nav{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:14px;font-size:15px}
.req{width:100%;border-collapse:collapse;margin:8px 0;font-size:15px}.req th,.req td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line);vertical-align:top}
.req th{width:46%;font-weight:600;color:var(--muted)}
"""


def page(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)} — Tayyorla</title>
<style>{CSS}</style></head><body><main>
<nav><a href="/oferta">Ommaviy oferta</a><a href="/maxfiylik">Maxfiylik siyosati</a><a href="https://t.me/{settings.bot_username}">Telegram bot</a></nav>
<article class="card"><h1>{html.escape(title)}</h1><p class="meta">Tahrir sanasi: {EDITION} · {html.escape(SELLER)}</p>{body}</article>
</main></body></html>"""


def oferta_html() -> str:
    site = html.escape(_site())
    bot = html.escape(settings.bot_username)
    body = f"""
<p>Ushbu hujjat {html.escape(SELLER)} (keyingi o‘rinlarda — «Ijrochi») tomonidan Tayyorla xizmatidan foydalanuvchi har qanday
jismoniy shaxsga (keyingi o‘rinlarda — «Foydalanuvchi») qaratilgan ommaviy oferta hisoblanadi (O‘zbekiston Respublikasi Fuqarolik
kodeksining 367–370-moddalari). Xizmat uchun to‘lov qilish yoki balansni to‘ldirish ushbu oferta shartlarini to‘liq va so‘zsiz
qabul qilish (aksept) hisoblanadi.</p>

<h2>1. Atamalar</h2>
<ul>
<li><b>Xizmat</b> — Telegram bot <a href="https://t.me/{bot}">@{bot}</a>, uning ichidagi ilova (Mini App) va {site} sayti orqali taqdim etiladigan raqamli xizmatlar.</li>
<li><b>Mahsulot</b> — Foydalanuvchi buyurtmasi asosida yaratiladigan raqamli natija: tabrik yoki taklifnoma sayti, video taklifnoma, shaxsiy qo‘shiq.</li>
<li><b>Balans</b> — Foydalanuvchining Xizmatdagi ichki hisobi; unga to‘langan mablag‘ Mahsulotlar uchun ishlatiladi.</li>
<li><b>Namuna</b> — Mahsulotning to‘lovgacha ko‘rsatiladigan bepul, cheklangan versiyasi.</li>
</ul>

<h2>2. Oferta predmeti</h2>
<p>Ijrochi Foydalanuvchi kiritgan ma’lumotlar asosida Mahsulotni yaratib beradi, Foydalanuvchi esa uning narxini to‘laydi.
Mahsulotlar sun’iy intellekt vositalari yordamida avtomatik yaratiladi. Xizmat raqamli shaklda ko‘rsatiladi, jismoniy tovar yetkazib berilmaydi.</p>

<h2>3. Narxlar</h2>
<p>Amaldagi narxlar (QQS hisoblanmaydi):</p>
{_prices()}
<p>Narxlar buyurtma oldidan Xizmatda ko‘rsatiladi. Ijrochi narxlarni o‘zgartirishi mumkin; o‘zgarish allaqachon to‘langan buyurtmalarga ta’sir qilmaydi.</p>

<h2>4. Buyurtma va to‘lov tartibi</h2>
<ol>
<li>Foydalanuvchi Xizmatda Mahsulot turini tanlaydi, kerakli ma’lumotlarni kiritadi va bepul Namunani ko‘radi.</li>
<li>To‘lov Click va Ijrochi ulagan boshqa to‘lov tizimlari orqali milliy valyutada (so‘m) amalga oshiriladi. Bank kartasi ma’lumotlari
to‘lov tizimi tomonida qayta ishlanadi, Ijrochi ularni olmaydi va saqlamaydi.</li>
<li>To‘lov muvaffaqiyatli o‘tgach, mablag‘ avtomatik ravishda Balansga tushadi yoki buyurtmaga yo‘naltiriladi.</li>
<li>Balansdagi mablag‘ faqat Xizmatdagi Mahsulotlar uchun sarflanadi va muddatsiz saqlanadi. Balansdagi mablag‘ni naqd pulga
yoki kartaga yechib olish (chiqarish) imkoniyati mavjud emas, 6-bo‘limda ko‘rsatilgan hollar bundan mustasno.</li>
</ol>

<h2>5. Xizmatni ko‘rsatish (yetkazib berish)</h2>
<ul>
<li>Sayt to‘lovdan so‘ng darhol faollashadi: «Namuna» belgisi olib tashlanadi va toza havola Telegram orqali yuboriladi.</li>
<li>Shaxsiy qo‘shiq to‘lovdan so‘ng odatda bir necha daqiqa ichida tayyorlanib, ilova va Telegram orqali beriladi.</li>
<li>Video taklifnoma navbat tartibida tayyorlanib, Telegram chatiga yuboriladi.</li>
<li>Texnik sabablarga ko‘ra kechikish bo‘lsa, Foydalanuvchiga xabar beriladi va Mahsulot imkon qadar tez yetkaziladi.</li>
</ul>

<h2>6. Qaytarish (refund) shartlari</h2>
<ul>
<li>Mahsulot to‘lovdan oldin bepul Namuna sifatida ko‘rsatilgani sababli, to‘liq yetkazilgan raqamli Mahsulot uchun to‘langan pul qaytarilmaydi.</li>
<li>Balansga to‘langan mablag‘ Xizmatdagi Mahsulotlarga sarflash uchun mo‘ljallangan va Foydalanuvchi xohishiga ko‘ra qaytarilmaydi.</li>
<li>Mablag‘ faqat quyidagi hollarda qaytariladi:
<ul>
<li>Ijrochi xatosi bilan Balansdan ortiqcha summa yechilgan bo‘lsa;</li>
<li>to‘langan xizmat belgilangan vaqtda bajarilmagan yoki texnik nosozlik tufayli umuman bajarilmagan bo‘lsa;</li>
<li>to‘lov tizimidagi xatolik yoki ikki marta to‘lov sababli ortiqcha pul yechilgan bo‘lsa.</li>
</ul></li>
<li>Bunday hollarda Foydalanuvchi @{bot} yoki <a href="mailto:{EMAIL}">{EMAIL}</a> orqali murojaat qiladi. Mablag‘ Foydalanuvchi tanlovi bo‘yicha
Balansga yoki to‘lov qilingan karta/hisobga, murojaat tasdiqlangan kundan boshlab 15 ish kuni ichida qaytariladi.</li>
</ul>

<h2>7. Tomonlarning majburiyatlari</h2>
<p><b>Foydalanuvchi:</b> to‘g‘ri ma’lumot kiritadi; uchinchi shaxslarning shaxsiy ma’lumotlari va suratlarini ularning roziligi bilan joylaydi;
qonunga zid, haqoratli yoki mualliflik huquqini buzuvchi matn va materiallarni yuklamaydi.</p>
<p><b>Ijrochi:</b> to‘langan Mahsulotni o‘z vaqtida yetkazadi; Foydalanuvchi ma’lumotlarini <a href="/maxfiylik">Maxfiylik siyosati</a>ga muvofiq himoya qiladi;
murojaatlarga 3 ish kuni ichida javob beradi.</p>

<h2>8. Javobgarlik</h2>
<p>Sun’iy intellekt yaratgan matn, qo‘shiq va dizayn Foydalanuvchi kiritgan ma’lumotlarga asoslanadi; Foydalanuvchi to‘lovdan oldin Namunani
ko‘rib chiqadi va uning mazmuni uchun o‘zi javobgar. Ijrochi Telegram, to‘lov tizimlari va internet provayderlarining nosozliklari uchun
javobgar emas. Tomonlarning javobgarligi to‘langan summa bilan cheklanadi.</p>

<h2>9. Intellektual mulk</h2>
<p>Foydalanuvchi to‘langan Mahsulotdan shaxsiy maqsadlarda (tabriklash, taklif qilish, ijtimoiy tarmoqlarda ulashish) cheklovsiz foydalanishi mumkin.
Xizmat dizaynlari va dasturiy ta’minoti Ijrochiga tegishli.</p>

<h2>10. Nizolarni hal qilish</h2>
<p>Nizolar muzokara yo‘li bilan hal qilinadi. Kelishuvga erishilmasa, O‘zbekiston Respublikasi qonunchiligiga muvofiq sudda ko‘riladi.</p>

<h2>11. Amal qilish muddati</h2>
<p>Oferta Xizmatda e’lon qilingan paytdan boshlab amal qiladi. Ijrochi ofertani o‘zgartirishi mumkin; yangi tahrir shu sahifada e’lon qilingan
kundan kuchga kiradi.</p>

<h2>12. Ijrochi rekvizitlari</h2>
{requisites()}
"""
    return page("Ommaviy oferta", body)


def privacy_html() -> str:
    bot = html.escape(settings.bot_username)
    body = f"""
<p>Ushbu siyosat {html.escape(SELLER)} (keyingi o‘rinlarda — «Ijrochi») Tayyorla xizmati (Telegram bot @{bot}, ilova va sayt) orqali
olinadigan shaxsiy ma’lumotlarni qanday yig‘ishi, ishlatishi va himoya qilishini belgilaydi. Hujjat O‘zbekiston Respublikasining
«Shaxsga doir ma’lumotlar to‘g‘risida»gi Qonuniga muvofiq tuzilgan. Xizmatdan foydalanish ushbu siyosatga rozilik bildirishni anglatadi.</p>

<h2>1. Qanday ma’lumotlar yig‘iladi</h2>
<ul>
<li><b>Telegram ma’lumotlari:</b> Telegram ID, ism, foydalanuvchi nomi (username), interfeys tili.</li>
<li><b>Buyurtma ma’lumotlari:</b> siz kiritgan ismlar, sanalar, manzillar, telefon raqamlari, tabrik matnlari va yuklagan suratlaringiz.</li>
<li><b>Mehmonlar javoblari:</b> sayt orqali yuborilgan taklifnomaga javoblar (ism, kelish-kelmasligi, izoh).</li>
<li><b>To‘lov ma’lumotlari:</b> to‘lov summasi, sanasi va to‘lov tizimidagi tranzaksiya raqami. Bank kartasi raqami va boshqa karta ma’lumotlari
Ijrochiga berilmaydi — ular faqat to‘lov tizimi (Click va boshqalar) tomonidan qayta ishlanadi.</li>
<li><b>Texnik ma’lumotlar:</b> sahifa ko‘rishlari soni, qaysi havola orqali kelganingiz, xatoliklar jurnali.</li>
</ul>

<h2>2. Maqsadlar</h2>
<ul>
<li>Buyurtma qilingan sayt, video va qo‘shiqni yaratish va yetkazish;</li>
<li>to‘lovlarni hisobga olish va Balansni yuritish;</li>
<li>buyurtma holati, eslatmalar va xizmat yangiliklari haqida Telegram orqali xabar yuborish (botni to‘xtatib, ulardan voz kechish mumkin);</li>
<li>xizmat sifatini yaxshilash va suiiste’mollikning oldini olish.</li>
</ul>

<h2>3. Uchinchi tomonlarga berish</h2>
<p>Ma’lumotlar sotilmaydi. Ular faqat xizmatni ko‘rsatish uchun zarur bo‘lgan hajmda quyidagilarga uzatiladi:</p>
<ul>
<li>sun’iy intellekt xizmatlari (matn va qo‘shiq yaratish uchun: Google, Anthropic, ElevenLabs) — faqat buyurtma matni (Telegram ID va to‘lov ma’lumotlarisiz);</li>
<li>to‘lov tizimlari — to‘lovni amalga oshirish uchun;</li>
<li>Telegram — xabar va fayllarni yetkazish uchun;</li>
<li>qonunda belgilangan hollarda vakolatli davlat organlariga.</li>
</ul>

<h2>4. Ommaga ko‘rinadigan ma’lumotlar</h2>
<p>Yaratilgan sayt havolaga ega bo‘lgan har kimga ochiq bo‘ladi. Saytga faqat ulashishni xohlagan ma’lumotlaringizni kiriting.
Sayt uchun parol o‘rnatish yoki uni o‘chirish mumkin.</p>

<h2>5. Saqlash va himoya</h2>
<p>Ma’lumotlar himoyalangan serverlarda saqlanadi, ularga kirish cheklangan. Ma’lumotlar xizmat ko‘rsatish uchun zarur bo‘lgan muddat davomida,
to‘lov yozuvlari esa qonunchilikda belgilangan muddat davomida saqlanadi.</p>

<h2>6. Cookie fayllari</h2>
<p>Sayt parol bilan ochilganda va ilovada sozlamalarni eslab qolish uchun brauzerda kichik texnik fayllar (cookie, localStorage) ishlatiladi.
Reklama kuzatuvchilari ishlatilmaydi.</p>

<h2>7. Sizning huquqlaringiz</h2>
<p>Siz o‘zingiz haqingizdagi ma’lumotlar bilan tanishish, ularni tuzatish yoki o‘chirishni talab qilishingiz mumkin. Buning uchun @{bot}
yoki <a href="mailto:{EMAIL}">{EMAIL}</a> orqali murojaat qiling — so‘rov 15 ish kuni ichida bajariladi. Ma’lumotlar o‘chirilgach, yaratilgan saytlar ham o‘chiriladi.</p>

<h2>8. Bolalar</h2>
<p>Xizmat 16 yoshdan katta foydalanuvchilar uchun mo‘ljallangan. Yoshi kichiklar ota-ona roziligi bilan foydalanadi.</p>

<h2>9. O‘zgarishlar</h2>
<p>Siyosat yangilanishi mumkin; yangi tahrir shu sahifada e’lon qilingan kundan kuchga kiradi.</p>

<h2>10. Aloqa</h2>
{requisites()}
<p>Shuningdek qarang: <a href="/oferta">Ommaviy oferta</a>.</p>
"""
    return page("Maxfiylik siyosati", body)


@router.get("/oferta", response_class=HTMLResponse)
@router.get("/offer", response_class=HTMLResponse, include_in_schema=False)
async def oferta():
    return oferta_html()


@router.get("/maxfiylik", response_class=HTMLResponse)
@router.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
async def privacy():
    return privacy_html()
