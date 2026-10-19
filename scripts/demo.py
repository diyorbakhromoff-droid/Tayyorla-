"""Namuna saytlarni yaratadi (to'langan holatda): python -m scripts.demo"""
import asyncio

from app.db import Session, Site, init_db, get_site
from app.sites import build_config

DEMOS = {
    "demo-tugilgan": ("birthday", {
        "name": "Madina", "age": "25", "date": "24.10.2026", "sender": "Seni sevuvchi oilang",
        "message": "Aziz Madina! Bugun sening kuning — dunyoga quyosh nuri kabi kelgan kuning.\nSenga mustahkam sog'liq, cheksiz baxt va har bir orzuingning ro'yobini tilaymiz. Kulging hech qachon so'nmasin, yuragingdagi mehr hammamizni isitib tursin.\nTug'ilgan kuning muborak, jonimiz!",
        "palette": "atirgul",
        "features": ["envelope", "confetti", "balloons", "cake", "gallery", "countdown"],
    }),
    "demo-toy": ("wedding", {
        "groom": "Jasur", "bride": "Nilufar", "date": "12.06.2027", "time": "18:00",
        "venue": "«Oqsaroy» to'yxonasi", "address": "Toshkent sh., Yunusobod tumani, Amir Temur ko'chasi 108",
        "hosts": "Karimovlar va Rahimovlar oilasi",
        "message": "Hayotimizning eng baxtli kunida — farzandlarimizning nikoh to'yida sizni aziz mehmonimiz sifatida ko'rishdan mamnun bo'lamiz.\nTashrifingiz biz uchun katta sharaf.",
        "palette": "oltin",
    }),
    "demo-sevgi": ("love", {
        "name": "Shirinim", "sender": "Sening Akmaling", "date": "14.02.2024",
        "message": "Sen bilan tanishgan kunimdan beri har bir tongim boshqacha otadi.\nKulishing, gapirishing, hatto jim turishing ham men uchun dunyodagi eng go'zal manzara.\nSeni har kuni yanada ko'proq sevaman.",
        "palette": "lavanda",
    }),
    "demo-chaqaloq": ("baby", {
        "gender": "boy", "baby_name": "Muhammadali", "parents": "Jasur va Nilufar", "date": "15.10.2026",
        "stats": "3.6 kg, 53 sm", "sender": "Buvi va bobosi",
        "message": "Aziz farzandlarimiz! Oilangizga kelgan bu kichkina quvonch bilan chin dildan tabriklaymiz.\nMuhammadalijon sog'-salomat, aqlli va odobli bo'lib ulg'aysin. Uning kulgusi uyingizni doim nurga to'ldirsin.",
        "palette": "osmon",
    }),
    "demo-uzr": ("apology", {
        "name": "Malika", "sender": "Sardor",
        "message": "Kecha aytgan so'zlarim uchun chin dildan uzr so'rayman. Seni xafa qilmoqchi emasdim, lekin baribir qildim — va bu meni tinch qo'ymayapti.\nSen men uchun juda qadrlisan. Xatoyimni tushundim.",
        "promises": "Endi gapingni oxirigacha tinglayman\nJahl ustida gapirmayman\nHar kuni kamida bir marta seni kuldiraman",
        "palette": "lavanda",
    }),
}

async def main():
    await init_db()
    async with Session() as s:
        for slug, (cat, answers) in DEMOS.items():
            site = await get_site(s, slug)
            cfg = build_config(cat, answers)
            if site:
                site.config = cfg
            else:
                s.add(Site(slug=slug, owner_id=0, category=cat, config=cfg, status="paid"))
        await s.commit()
    print("ok")

asyncio.run(main())
