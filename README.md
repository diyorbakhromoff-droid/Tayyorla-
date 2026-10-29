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
  bot/handlers.py  bot ssenariysi, tahrir, to'lov, admin
  bot/keyboards.py tugmalar
catalog/           30 ta tayyor dizayn, rasmlari va namuna suratlari (skins/ — yangi dizaynlar manbasi)
templates/         oddiy shablonlar va Mini App (HTML)
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

Sinov: `.venv/bin/python -m tests.test_flow`, `.venv/bin/python -m tests.test_webapp` va `.venv/bin/python -m tests.test_reminders`

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
