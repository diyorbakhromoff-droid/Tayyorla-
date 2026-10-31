"""Tarifli (v2) shablonni namuna ma'lumoti bilan ochib, skrinshot oladi va brauzer xatolarini chiqaradi.

    python scripts/v2_shot.py toy2-saroy                 # 390x844, butun sahifa
    python scripts/v2_shot.py toy2-saroy --open          # kirish sahnasidagi tugmani bosib, keyin suratga oladi
    python scripts/v2_shot.py toy2-saroy --w 360 --h 640 --screen   # faqat birinchi ekran
    python scripts/v2_shot.py toy2-saroy --hide dastur,hikoya --photos 0 --long
    python scripts/v2_shot.py toy2-saroy --click "button:has-text('Boraman')"
"""

import argparse
import asyncio
import json
import mimetypes
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import catalog, catalog2  # noqa: E402,F401

LONG = {
    "kimga": "Muhammadjonova Mohinurbonu", "kuyov": "Abdurahmonjon", "kelin": "Gulchehrabonu",
    "chaqaloq": "Muhammadabdulloh", "kimdan": "Sevimli dugonalaring: Laylo, Sevara, Nigora va Dilfuza",
    "manzil_nomi": "«Oltin saroy» ko'p tarmoqli to'yxonasi",
}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--w", type=int, default=390)
    ap.add_argument("--h", type=int, default=844)
    ap.add_argument("--screen", action="store_true", help="faqat birinchi ekran")
    ap.add_argument("--open", action="store_true", help="kirish sahnasini ochish")
    ap.add_argument("--click", action="append", default=[], help="CSS/Playwright selektor, ketma-ket bosiladi")
    ap.add_argument("--hide", default="", help="olib tashlanadigan bloklar, vergul bilan")
    ap.add_argument("--photos", type=int, default=-1, help="nechta surat qoldirilsin")
    ap.add_argument("--long", action="store_true", help="uzun ismlar bilan sinash")
    ap.add_argument("--data", default="", help="JSON: maydonlarni almashtirish")
    ap.add_argument("--rang", type=int, default=1, help="palitra raqami (1 — asl)")
    ap.add_argument("--wait", type=int, default=1600, help="animatsiya uchun kutish, ms")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    catalog2.TEMPLATES2, catalog2.DEMOS = catalog2._load()
    t = catalog2.TEMPLATES2.get(a.id)
    if not t:
        sys.exit(f"Shablon topilmadi: {a.id} (manifest va .dc.html bormi?)")
    cfg = catalog2.demo_config(t)
    if a.hide:
        cfg["hidden"] = [x.strip() for x in a.hide.split(",") if x.strip()]
    if a.photos >= 0:
        cfg["photos"] = cfg["photos"][: a.photos]
    if a.long:
        cfg["data"].update({k: v for k, v in LONG.items() if k in cfg["data"]})
    if a.data:
        cfg["data"].update(json.loads(a.data))
    cfg["rang"] = a.rang
    html = catalog2.render(t, cfg, "test", preview=False, demo=True)

    from playwright.async_api import async_playwright

    async def serve(route):
        url = route.request.url.split("://", 1)[1].split("/", 1)[1].split("?")[0]
        if url == "":
            return await route.fulfill(body=html, content_type="text/html; charset=utf-8")
        for prefix, base in (("static/", ROOT / "static"), ("katalog/", ROOT / "catalog"), ("media/", ROOT / "media")):
            if url.startswith(prefix):
                f = base / url[len(prefix):]
                if f.is_file():
                    return await route.fulfill(body=f.read_bytes(), content_type=mimetypes.guess_type(str(f))[0] or "application/octet-stream")
        await route.fulfill(status=404, body="")

    out = a.out or f"/tmp/v2shots/{a.id}{'-open' if a.open else ''}-{a.w}x{a.h}.png"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        exe = os.environ.get("CHROMIUM_PATH") or ("/opt/pw-browsers/chromium-1194/chrome-linux/chrome" if Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome").is_file() else None)
        b = await p.chromium.launch(executable_path=exe)
        page = await b.new_page(viewport={"width": a.w, "height": a.h})
        errors = []
        page.on("console", lambda m: m.type in ("error", "warning") and errors.append(f"console.{m.type}: {m.text}"))
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        await page.route("http://t.local/**", serve)
        await page.goto("http://t.local/", wait_until="networkidle")
        await page.wait_for_timeout(a.wait)
        if a.open:
            btn = page.locator("[data-intro] button").last
            if await btn.count():
                await btn.click()
                await page.wait_for_timeout(5000)
            else:
                errors.append("--open: [data-intro] ichida tugma topilmadi")
        for sel in a.click:
            await page.locator(sel).first.click()
            await page.wait_for_timeout(1500)
        height = await page.evaluate("document.documentElement.scrollHeight")
        await page.screenshot(path=out, full_page=not a.screen)
        await b.close()
    print(out, f"(sahifa balandligi {height}px)")
    for e in errors:
        print(e)


if __name__ == "__main__":
    asyncio.run(main())
