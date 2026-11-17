"""Oferta va maxfiylik siyosati sahifalari: rekvizitlar, amaldagi narxlar, o'zaro havolalar."""
import asyncio
import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/legal.db"
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["BASE_URL"] = "https://tayyorla.test"

from app import legal  # noqa: E402
from app.config import settings  # noqa: E402
from app.web import app  # noqa: E402


async def main():
    paths = {getattr(r, "path", "") for r in legal.router.routes}
    assert {"/oferta", "/maxfiylik", "/offer", "/privacy"} <= paths

    of = await legal.oferta()
    assert "YATT Baxromov Diyorbek Ulug‘bek o‘g‘li" in of and "52401026300010" in of
    for price in (settings.price_standart, settings.price_premium, settings.price_vip, settings.song_price, settings.video_price):
        assert legal._money(price) in of, price
    assert "Qaytarish" in of and 'href="/maxfiylik"' in of
    assert "Telefon" not in of, "kiritilmagan telefon ko'rsatilmaydi"

    settings.legal_phone = "+998 90 000 00 00"
    pv = await legal.privacy()
    assert "52401026300010" in pv and "+998 90 000 00 00" in pv and 'href="/oferta"' in pv
    assert "karta" in pv.lower()
    print("✅ Oferta va maxfiylik sahifalari tekshiruvi o'tdi")


asyncio.run(main())
