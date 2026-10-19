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

## Telegram Mini App

Bot ichida ochiladigan forma (`/app`): kategoriya → ma'lumotlar → AI matn → rasm/musiqa → ranglar (jonli namunalar bilan) → oldindan ko'rish → yaratish.
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
  web.py           saytlarni ko'rsatish, RSVP, parol
  webapp.py        Mini App API (Telegram imzosini tekshirish, yuklash, AI, ko'rish)
  bot/handlers.py  bot ssenariysi, tahrir, to'lov, admin
  bot/keyboards.py tugmalar
templates/         sayt shablonlari (HTML)
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

Sinov: `.venv/bin/python -m tests.test_flow` va `.venv/bin/python -m tests.test_webapp`

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
