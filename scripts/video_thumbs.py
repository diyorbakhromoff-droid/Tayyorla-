"""Video dizaynlar galereyasi uchun rasmlar: python -m scripts.video_thumbs [dizayn_id ...]

Har bir dizayndan bitta kadr (designs.json dagi «thumb_at», bo'lmasa 3.6 soniya) olinib,
catalog/video/thumb/<id>.jpg ga 270x480 o'lchamda yoziladi. Chromium kerak (CHROMIUM_PATH).
"""

import asyncio
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

from app import video
from app.render_core import Renderer

OUT = Path(__file__).resolve().parent.parent / "catalog" / "video" / "thumb"
SIZE = (270, 480)


async def main(ids: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    r = Renderer()
    await r.start()
    try:
        for design_id in ids or list(video.DESIGNS):
            d = video.design(design_id)
            payload = video.build_payload(design_id, video.DEMO[d["section"]], "uz", guest="", free=False,
                                          site_url="https://tayyorla.uz/s/demo")
            html = video.page_html(design_id, payload, mode="render")
            im = Image.open(BytesIO(await r.still(html, int(d.get("thumb_at", 3600)), scale=1)))
            im = im.convert("RGB").resize(SIZE, Image.LANCZOS)
            im.save(OUT / f"{design_id}.jpg", "JPEG", quality=82, optimize=True, progressive=True)
            print(design_id)
    finally:
        await r.stop()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
