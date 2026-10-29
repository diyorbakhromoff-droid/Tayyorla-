"""Video yasash yadrosi: Chromium sahifani kadrma-kadr suratga oladi, ffmpeg MP4 ga yig'adi.

Sahifa resurslari (shriftlar, dvigatel, rasmlar) diskdan beriladi — render paytida internet kerak emas.
"""

import asyncio
import base64
import logging
import mimetypes
import os
import shutil
from pathlib import Path

from .config import MEDIA_DIR, ROOT, settings

log = logging.getLogger(__name__)

ORIGIN = "http://render.local"
SECONDS = settings.video_seconds
_STATIC = {"/static/": ROOT / "static", "/media/": MEDIA_DIR, "/katalog/": ROOT / "catalog"}


def _local_file(path: str) -> Path | None:
    for prefix, base in _STATIC.items():
        if path.startswith(prefix):
            p = (base / path[len(prefix):]).resolve()
            if base.resolve() in p.parents and p.is_file():
                return p
    return None


def _clip(scale: float) -> dict:
    """CDP ekran surati CSS pikselda qaytadi; to'liq aniqlik (1080x1920) uchun masshtab clip orqali beriladi."""
    return {"x": 0, "y": 0, "width": 360, "height": 640, "scale": scale}


class Renderer:
    """Bitta Chromium jarayoni; har bir video uchun yangi sahifa ochiladi."""

    def __init__(self) -> None:
        self._pw = None
        self.browser = None

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        args = ["--font-render-hinting=none", "--disable-lcd-text", "--hide-scrollbars", "--mute-audio",
                "--disable-dev-shm-usage", "--no-sandbox", "--force-color-profile=srgb"]
        exe = os.environ.get("CHROMIUM_PATH") or None
        self.browser = await self._pw.chromium.launch(args=args, executable_path=exe)

    async def stop(self) -> None:
        if self.browser:
            await self.browser.close()
        if self._pw:
            await self._pw.stop()

    async def _page(self, html: str, scale: float):
        ctx = await self.browser.new_context(viewport={"width": 360, "height": 640}, device_scale_factor=scale)
        page = await ctx.new_page()

        async def route(r):
            url = r.request.url
            path = url[len(ORIGIN):].split("?", 1)[0] if url.startswith(ORIGIN) else None
            if path == "/__page":
                return await r.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
            f = _local_file(path) if path else None
            if f:
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                return await r.fulfill(status=200, content_type=ctype, body=f.read_bytes())
            # tashqi so'rovlar (shrift CDN va h.k.) render paytida bloklanadi
            return await r.fulfill(status=404, body="")

        await page.route("**/*", route)
        await page.goto(f"{ORIGIN}/__page", wait_until="load")
        await page.wait_for_function("window.__ready === true", timeout=30000)
        cdp = await ctx.new_cdp_session(page)
        return ctx, page, cdp

    async def frames(self, html: str, start_ms: int, end_ms: int, fps: int, scale: float, sink, on_frame=None, quality: int = 92):
        """[start_ms, end_ms) oralig'idagi kadrlarni JPEG ko'rinishida sink(bytes) ga beradi."""
        ctx, page, cdp = await self._page(html, scale)
        try:
            first = round(start_ms * fps / 1000)
            last = round(end_ms * fps / 1000)
            for i in range(first, last):
                await page.evaluate("t => window.__seek(t)", i * 1000 / fps)
                shot = await cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": quality, "optimizeForSpeed": True,
                                                                  "clip": _clip(scale)})
                await sink(base64.b64decode(shot["data"]), i)
                if on_frame:
                    await on_frame(i - first + 1, last - first)
        finally:
            await ctx.close()

    async def still(self, html: str, t_ms: int, scale: float = 1, quality: int = 88) -> bytes:
        ctx, page, cdp = await self._page(html, scale)
        try:
            await page.evaluate("t => window.__seek(t)", t_ms)
            shot = await cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": quality, "clip": _clip(scale)})
            return base64.b64decode(shot["data"])
        finally:
            await ctx.close()


# ---------------------------------------------------------------- ffmpeg

def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def audio_args(music: dict | None, seconds: float) -> tuple[list[str], list[str]]:
    """(kirish argumentlari, filtr argumentlari). Musiqa bo'lmasa jim trek — Telegram videoni GIF deb o'ylamasin."""
    path = (music or {}).get("path")
    if path and Path(path).is_file():
        start = max(0.0, float((music or {}).get("start") or 0))
        fade_at = max(0.0, seconds - 1.2)
        return (["-ss", f"{start:.2f}", "-t", f"{seconds:.2f}", "-i", str(path)],
                ["-af", f"afade=t=in:st=0:d=0.3,afade=t=out:st={fade_at:.2f}:d=1.2"])
    return ["-f", "lavfi", "-t", f"{seconds:.2f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"], []


VIDEO_CODEC = ["-c:v", "libx264", "-preset", "veryfast", "-tune", "animation", "-crf", "21", "-pix_fmt", "yuv420p",
               "-profile:v", "high", "-level", "4.1"]


async def encode(render_frames, out: Path, fps: int, seconds: float, music: dict | None = None, with_audio: bool = True) -> None:
    """render_frames(sink) kadrlarni beradi; natija — faststart MP4 (H.264 + AAC)."""
    a_in, a_filter = audio_args(music, seconds) if with_audio else ([], [])
    cmd = [_ffmpeg(), "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
           *a_in, *VIDEO_CODEC, "-r", str(fps)]
    if with_audio:
        cmd += ["-map", "0:v", "-map", "1:a", *a_filter, "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-shortest"]
    else:
        cmd += ["-an"]
    cmd += ["-movflags", "+faststart", str(out)]
    proc = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

    async def sink(data: bytes, _i: int) -> None:
        proc.stdin.write(data)
        await proc.stdin.drain()

    try:
        await render_frames(sink)
    finally:
        if proc.stdin and not proc.stdin.is_closing():
            proc.stdin.close()
    err = await proc.stderr.read()
    if await proc.wait() != 0:
        raise RuntimeError(f"ffmpeg: {err.decode(errors='ignore')[-400:]}")


async def concat_with_audio(parts: list[Path], out: Path, seconds: float, music: dict | None) -> None:
    """Bir xil parametrli video bo'laklarni qayta kodlamasdan ulaydi va ovoz qo'shadi."""
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    a_in, a_filter = audio_args(music, seconds)
    cmd = [_ffmpeg(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), *a_in,
           "-map", "0:v", "-map", "1:a", "-c:v", "copy", *a_filter, "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
           "-shortest", "-movflags", "+faststart", str(out)]
    proc = await asyncio.create_subprocess_exec(*cmd, stderr=asyncio.subprocess.PIPE)
    err = await proc.stderr.read()
    code = await proc.wait()
    lst.unlink(missing_ok=True)
    if code != 0:
        raise RuntimeError(f"ffmpeg concat: {err.decode(errors='ignore')[-400:]}")
