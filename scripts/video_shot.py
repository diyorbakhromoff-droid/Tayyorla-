"""Video dizayndan bir nechta kadr olib, bitta varaqqa yig'adi: python -m scripts.video_shot v-anor [--palette 2] [--t 1000,3600,7000]

Kadrlar /tmp/vshots/<id>-p<palitra>.png ga yoziladi; brauzer xatolari chiqariladi.
"""

import argparse
import asyncio
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from app import video
from app.render_core import Renderer


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--palette", type=int, default=0, help="0 — birinchi palitra")
    ap.add_argument("--t", default="1500,3600,6500,9500,13000,17000", help="kadr vaqtlari, ms")
    ap.add_argument("--long", action="store_true", help="uzun ismlar bilan")
    a = ap.parse_args()
    video.DESIGNS.clear()
    video.DESIGNS.update(video.load_designs())
    d = video.design(a.id)
    data = dict(video.DEMO[d["section"]])
    if a.long:
        for k in ("kuyov", "kelin", "ism", "mezbon", "imzo"):
            if k in data:
                data[k] = "Muhammadabdulloh Abdurahmonov"
    payload = video.build_payload(a.id, data, "uz", guest=video.DEMO_GUEST, site_url="https://tayyorla.uz/s/demo",
                                  palette=a.palette)
    html = video.page_html(a.id, payload, mode="render")
    times = [int(x) for x in a.t.split(",")]
    r = Renderer()
    await r.start()
    frames = []
    try:
        for t in times:
            frames.append(Image.open(BytesIO(await r.still(html, t, scale=1))).convert("RGB"))
    finally:
        await r.stop()
    w, h = frames[0].size
    sheet = Image.new("RGB", (w * len(frames), h + 22), "white")
    dr = ImageDraw.Draw(sheet)
    for i, (t, im) in enumerate(zip(times, frames)):
        sheet.paste(im, (i * w, 22))
        dr.text((i * w + 6, 4), f"{t} ms", fill="black")
    out = Path("/tmp/vshots") / f"{a.id}-p{a.palette}{'-long' if a.long else ''}.png"
    out.parent.mkdir(exist_ok=True)
    sheet.save(out)
    print(out)


if __name__ == "__main__":
    asyncio.run(main())
