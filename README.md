# Tayyorla 💌

Telegram bot orqali yaqinlar uchun tabrik saytlarini yaratish xizmati.

**Kategoriyalar:** 🎂 Tug'ilgan kun · 💍 To'y taklifnomasi · 💌 Sevgiliga xat · 👶 Farzand muborak · 🙏 Uzrnoma

## Imkoniyatlar

- Bot savollar beradi, mijoz tugmalar orqali tanlaydi va ma'lumot kiritadi
- Rasm (10 tagacha) va fon musiqasi yuklash, 6 xil rang uslubi
- Elementlar: konvert ochilishi, konfetti, sharlar, yuraklar, gulbarglar, taymer, «birga o'tgan vaqt», shamni puflash, «Meni sevasanmi?» o'yini, galereya, xarita, parolli sahifa
- To'y uchun RSVP: mehmon javob bersa egasiga Telegram'da xabar keladi, «📋 Mehmonlar ro'yxati»
- Claude AI tabrik matnini yozib beradi va saytni oddiy so'z bilan tahrirlaydi («fonni pushti qil»)
- To'lovgacha sayt «NAMUNA» belgisi bilan ko'rinadi
- To'lov: Rahmat havolasi → chek skrinshoti → admin «✅ Tasdiqlash» → mijozga toza link
- Sayt birinchi marta ochilganda egasiga xabar boradi

## 🎬 Video taklifnomalar (Tayyorla 2.0)

Mini App'da 5 bo'lim: **Asosiy, Videolar, Saytlar, Taklifnomalar, Profil**. Foydalanuvchi dizayn tanlaydi, ma'lumotlarni
yozadi va jonli ko'rinishda (360×640 sahifa) natijani darhol ko'radi; «Video yaratish» bosilgach 20 soniyalik 9:16 MP4
(720×1280 yoki 1080×1920, 30 kadr) bot chatiga keladi.

- **5 marosim, 20 dizayn:** to'y, osh, gap, choyxona, tug'ilgan kun — har birida 3–4 rang. Dizaynlar `catalog/video/<id>.html`
  (bo'lak) va `catalog/video/designs.json` (nom, shrift, ranglar); umumiy dvigatel `static/video/engine.{css,js}`.
  4 sahna: Konvert (mehmon ismi) · Kartochka · Tafsilotlar (QR, to'yona) · Final. Galereya rasmlari:
  `python -m scripts.video_thumbs`.
- **Narx:** kuniga `FREE_VIDEOS_PER_DAY` ta bepul (Toshkent vaqti bilan), keyingisi `VIDEO_PRICE` so'm balansdan.
  Bepul videoda `CHANNEL_ID` kanaliga obuna shart va oxirida «Siz ham yarating» yozuvi bor; pullik videoda ikkalasi ham yo'q.
  Do'st taklif qilinsa (`?start=ref_<id>`) +1 bepul video.
- **Balans:** foydalanuvchi oldindan to'ldiradi (`TOPUP_AMOUNTS`): Rahmat orqali to'lab chekni botga yuboradi, admin
  «✅» bosadi — summa balansga tushadi va to'lovni kutayotgan videolar o'zi navbatga qo'yiladi. Video, sayt va mehmon
  paketlari balansdan to'lanadi. Payme/Click keyin shu balansga ulanadi.
- **Mehmonlar:** Taklifnomalar bo'limida ro'yxat (har qatorda bitta ism, 300 tagacha). Har bir mehmon shaxsiy havola oladi
  (`/s/<slug>?g=<token>`), javobi ismi bilan belgilanadi. «Hammasiga video» — konvertida mehmon ismi yozilgan video;
  narx paket bilan (`GUEST_PACKAGES`, kattaroq paketga o'tilsa faqat farqi). Tadbir sahifasi: javob, xarita, kalendar (.ics),
  to'yona kartasini nusxalash, QR-kod.
- **7 til:** o'zbek (lotin va kirill), rus, ingliz, qoraqalpoq, tojik, qozoq — ilova, bot va taklifnoma matni.
  Lug'atlar `static/i18n/<til>.json`; o'zbekcha manba `scripts/i18n_app_uz.py`, yig'ish va tekshirish:
  `python -m scripts.i18n_build` (kirill avtomatik) va `python -m scripts.i18n_build --check-only`.
- **Musiqa:** admin Mini App → Profil → Admin panel orqali (yoki botga audio yuborib) kuy qo'shadi: mavzu
  (to'y, osh, …) va turi (qo'shiq/cholg'u). Foydalanuvchi o'z musiqasini ham yuklashi mumkin.
- **Renderer** alohida konteyner (`Dockerfile.renderer`, `python -m app.renderer`): Playwright Chromium kadrlarni chizadi,
  ffmpeg yig'adi. Navbat ma'lumotlar bazasida; mehmon videolarida umumiy 5–20 s qismi bir marta chiziladi.
  Sifat: `VIDEO_SCALE=2` — 720×1280 (4 yadroda ~40 s), `VIDEO_SCALE=3` — 1080×1920 (~1 daqiqa, server kattalashtirilganda).
- **Admin:** `/stats` — foydalanuvchilar, videolar, tushum; `/broadcast` — hammaga xabar.

Bot kanal obunasini tekshira olishi uchun uni `CHANNEL_ID` kanaliga **admin** qilib qo'shing. Inline ulashish
(«Ulashish» tugmasi) uchun BotFather'da `/setinline` ni yoqing.

## Tayyor shablonlar katalogi (asosiy)

`catalog/` — 5 bo'limda 30 ta professional dizayn (20 oddiy, 5 ta yangi Premium va 5 ta VIP «Maktub»). Har bir shablon ma'lumotni
`<script id="site-config">` JSON dan oladi; `app/catalog.py` uni to'ldiradi va tarif cheklovlarini qo'llaydi.

| Tarif | Ranglar | Suratlar | Qo'shimcha |
|---|---|---|---|
| Standart | 3 | 6 | asosiy bo'limlar, "Siz ham yarating" yozuvi |
| Premium | 10 | 40 | kirish animatsiyasi, hikoya, sirli xabar, test, video, to'y dasturi, reklamasiz |
| VIP | 15 | 40 | + «Maktub» VIP shablonlari (muhrli konvert, anketa) |

Narxlar `.env` da: `PRICE_STANDART`, `PRICE_PREMIUM`, `PRICE_VIP`. VIP to'y anketasi javoblari `/s/<slug>/anketa` ga
keladi va egasiga Telegram'da yuboriladi. Mijoz saytida tarif/rangni havola (`?tarif=`, `#vip-2`) orqali
o'zgartirib bo'lmaydi — bu faqat namunalarda ishlaydi.

## 📅 Yaqinlarim kalendari

Botdagi «📅 Yaqinlarim» (yoki /yaqinlar): foydalanuvchi yaqinlarining tug'ilgan kunlari, to'y yilligi va boshqa
sanalarini kiritadi. Bot har kuni 9:00 dan keyin (Toshkent vaqti) tekshiradi va **7 kun**, **1 kun** oldin hamda
**o'sha kuni** eslatadi (`app/reminders.py`). Eslatmadagi «✨ Tabrik tayyorlash» tugmasi Mini App'ni ism va sana
to'ldirilgan holda ochadi. Har bir eslatma faqat bir marta yuboriladi (`reminder_log` jadvali).

## ⏰ Syurpriz ochilish

Mijoz xohlasa (Mini App'ning oxirgi qadamida yoki botda «⏰ Syurpriz» tugmasi orqali) sayt belgilangan vaqtgacha
yopiq turadi: havolani ochgan odam sovg'a qutisi va orqaga sanoqni ko'radi, vaqt kelganda sahifa o'zi ochiladi.
Sayt egasi botdagi «👀 Saytni ochish» tugmasidagi maxfiy havola (`?owner=<kalit>`) orqali istalgan payt ko'radi.

## Telegram Mini App

Bot ichida ochiladigan ilova (`/app`): bo'lim → dizaynlar galereyasi → jonli namuna → tarif va rang → ma'lumotlar (AI matn bilan) → suratlar va musiqa → oldindan ko'rish → yaratish.
Mini App faqat **HTTPS** da ishlaydi. Domen bo'lmasa, bepul `sslip.io` dan foydalaning:

```
BASE_URL=https://77-42-80-83.sslip.io
SITE_ADDRESS=77-42-80-83.sslip.io
```

`BASE_URL` https bo'lsa, bot menyusiga «✨ Yaratish» tugmasi va /start ga «Ilovada yaratish» tugmasi avtomatik qo'shiladi.

## Tuzilishi

```
app/
  main.py          bot + veb-serverni birga ishga tushiradi
  config.py        sozlamalar (.env dan)
  db.py            ma'lumotlar bazasi (saytlar, mehmon javoblari)
  sites.py         kategoriyalar, savollar, ranglar, elementlar
  render.py        saytni shablondan yig'ish
  ai.py            Claude: matn yozish va tahrirlash
  catalog.py       tayyor shablonlar: maydonlar, tariflar, sahifani yig'ish
  web.py           saytlarni ko'rsatish, RSVP, parol
  reminders.py     yaqinlar kalendari va eslatmalar
  surprise.py      syurpriz ochilish, egasining maxfiy havolasi
  webapp.py        Mini App API (Telegram imzosini tekshirish, yuklash, AI, ko'rish)
  video.py         video taklifnoma: maydonlar, sahifa ma'lumotlari, izoh
  videoapi.py      video, musiqa, hamyon va admin API
  events.py        tadbirlar, mehmonlar, paketlar, tadbir sahifasi
  billing.py       bepul limit, balans, paketlar
  renderer.py      video navbati (alohida konteyner), render_core.py — Chromium + ffmpeg
  i18n.py          7 til, kirill/lotin o'girish, sanalar
  bot/handlers.py  bot ssenariysi, tahrir, to'lov, admin
  bot/keyboards.py tugmalar
catalog/           30 ta tayyor dizayn, rasmlari va namuna suratlari (skins/ — yangi dizaynlar manbasi)
templates/         oddiy shablonlar, Mini App qobig'i va tadbir sahifasi (HTML)
static/app/        Mini App (5 bo'lim: core/home/videos/sites/events/profile .js + app.css)
static/video/      video dvigateli; catalog/video/ — 20 ta video dizayn
static/i18n/       7 tildagi lug'atlar
static/            dizayn (CSS) va animatsiyalar (JS)
tests/test_flow.py botni Telegram'siz to'liq sinash
```

## Kompyuterda ishga tushirish

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # ichini to'ldiring
.venv/bin/python -m app.main
```

Namuna saytlar: `.venv/bin/python -m scripts.demo`, so'ng `http://localhost:8000/s/demo-tugilgan`, `/s/demo-toy`, `/s/demo-sevgi`.

Sinov: `.venv/bin/python -m tests.test_flow`, `tests.test_webapp`, `tests.test_reminders`, `tests.test_home` va `tests.test_video`.
Videoni kompyuterda chizish uchun Chromium kerak: `pip install playwright==1.64.0 && playwright install chromium`, ffmpeg o'rnatilgan bo'lsin.

## Serverga o'rnatish (VPS)

1. Ubuntu VPS oling (Hetzner, DigitalOcean va h.k., ~$5/oy) va Docker o'rnating:
   `curl -fsSL https://get.docker.com | sh`
2. Domen sotib oling va uning **A yozuvini** server IP manziliga yo'naltiring.
3. Kodni serverga oling: `git clone https://github.com/<siz>/tayyorla.git && cd tayyorla`
4. `cp .env.example .env` va to'ldiring (`BASE_URL=https://domeningiz`).
5. Domen bo'lsa `.env` da `SITE_ADDRESS=domeningiz` va `BASE_URL=https://domeningiz` qiling (HTTPS avtomatik).
6. `docker compose up -d --build`

Yangilash: `git pull && docker compose up -d --build`

## Admin buyruqlari

- `/stats` — saytlar soni va tushum
- To'lov chekini yuborilganda adminga «✅ Tasdiqlash / ❌ Rad etish» tugmalari keladi

## Yangi kategoriya qo'shish

1. `app/sites.py` dagi `CATEGORIES` ga yozuv qo'shing (savollar, elementlar).
2. `templates/<kalit>.html` shablonini yarating (`birthday.html` ga qarang).
