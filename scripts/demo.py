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
