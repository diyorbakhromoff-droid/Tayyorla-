"""Tarifli shablonlar katalogi uchun muqova rasmlari: python scripts/v2_thumbs.py [id ...]

Har bir shablon namuna ma'lumoti bilan ochiladi va birinchi ekrani (Premium/VIP'da yopiq kirish sahnasi)
catalog/thumb/<id>.jpg ga 360x624 o'lchamda saqlanadi.
"""

import asyncio
import io
import mimetypes
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from app import catalog, catalog2  # noqa: E402,F401

W, H = 390, 676  # katalog kartochkasi nisbati 300:520


async def main(ids: list[str]) -> None:
    from playwright.async_api import async_playwright

    todo = [catalog2.TEMPLATES2[i] for i in ids] if ids else list(catalog2.TEMPLATES2.values())
    pages = {}

    async def serve(route):
        path = route.request.url.split("://", 1)[1].split("/", 1)[1].split("?")[0]
        if path in pages:
            return await route.fulfill(body=pages[path], content_type="text/html; charset=utf-8")
        for prefix, base in (("static/", ROOT / "static"), ("katalog/", ROOT / "catalog"), ("media/", ROOT / "media")):
            if path.startswith(prefix):
                f = base / path[len(prefix):]
                if f.is_file():
                    return await route.fulfill(body=f.read_bytes(), content_type=mimetypes.guess_type(str(f))[0] or "application/octet-stream")
        await route.fulfill(status=404, body="")

    exe = os.environ.get("CHROMIUM_PATH")
    default = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=exe or (str(default) if default.is_file() else None))
        page = await b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1.5)
        await page.route("http://t.local/**", serve)
        for t in todo:
            pages[t["id"]] = catalog2.render(t, catalog2.demo_config(t), "namuna", preview=False, demo=True)
            await page.goto(f"http://t.local/{t['id']}", wait_until="networkidle")
            await page.wait_for_timeout(2200)
            png = await page.screenshot()
            img = Image.open(io.BytesIO(png)).convert("RGB").resize((360, 624), Image.LANCZOS)
            out = ROOT / "catalog" / "thumb" / f"{t['id']}.jpg"
            img.save(out, "JPEG", quality=82, optimize=True, progressive=True)
            print(out.relative_to(ROOT))
        await b.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
