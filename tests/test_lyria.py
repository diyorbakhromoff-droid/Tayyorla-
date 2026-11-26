"""Lyria mijozi: 429 da kutib qayta yuborish, boshqa xatolarda qayta urinmaslik, Google sababi saqlanishi.

Ishga tushirish: python -m tests.test_lyria
"""

import asyncio
import base64
import json
import os

os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app import lyria  # noqa: E402

AUDIO = base64.b64encode(b"\x00" * 6000).decode()
OK = json.dumps({"id": "i1", "status": "completed", "steps": [{"model_output": {"content": [{"type": "audio", "data": AUDIO}]}}]})
BUSY = json.dumps({"error": {"code": 429, "message": "Too many requests, please slow down.", "status": "RESOURCE_BUSY"}})
DAILY = json.dumps({"error": {"code": 429, "message": "Quota exceeded for requests per day.", "status": "RESOURCE_EXHAUSTED"}})
BLOCK = json.dumps({"error": {"code": 400, "message": "Request was blocked due to recitation of copyrighted lyrics.", "status": "INVALID_ARGUMENT"}})


class Resp:
    def __init__(self, status, body, headers=None):
        self.status, self._body, self.headers = status, body, headers or {}

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class Http:
    """Ketma-ket javoblar: posts — POST lar, gets — GET lar."""

    def __init__(self, posts, gets=()):
        self.posts, self.gets, self.n_post, self.n_get = list(posts), list(gets), 0, 0

    def __call__(self, *a, **kw):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def post(self, *a, **kw):
        self.n_post += 1
        return Resp(*self.posts.pop(0))

    def get(self, *a, **kw):
        self.n_get += 1
        return Resp(*self.gets.pop(0))


async def run(http):
    lyria.aiohttp.ClientSession = http
    return await lyria.compose("matn")


async def main() -> None:
    lyria.key = lambda: "k"
    waits = []

    async def fake_sleep(sec):
        waits.append(sec)

    lyria.asyncio.sleep = fake_sleep

    # 429 ikki marta, keyin muvaffaqiyat — qo'shiq olinadi, bitta qo'shiq uchun 3 ta POST
    h = Http([(429, BUSY), (429, BUSY, {"Retry-After": "20"}), (200, OK)])
    audio, _ = await run(h)
    assert len(audio) == 6000 and h.n_post == 3, h.n_post
    assert waits[:2] == [8, 20], waits  # Retry-After hisobga olinadi

    # doim 429 — 5 urinishdan keyin «Navbat band» (busy), pul olinmagan so'rovlar
    waits.clear()
    h = Http([(429, BUSY)] * 5)
    try:
        await run(h)
        raise AssertionError("xato kutilgan edi")
    except lyria.LyriaError as e:
        assert e.reason == "busy" and h.n_post == 5 and len(waits) == 4, (e.reason, h.n_post, waits)
        assert "RESOURCE_BUSY" in e.detail

    # kunlik kvota — kutilmaydi, darhol xato (kvota)
    waits.clear()
    h = Http([(429, DAILY)])
    try:
        await run(h)
        raise AssertionError
    except lyria.LyriaError as e:
        assert e.quota and h.n_post == 1 and not waits

    # matn rad etildi — qayta urinilmaydi, Google sababi saqlanadi
    h = Http([(400, BLOCK)])
    try:
        await run(h)
        raise AssertionError
    except lyria.LyriaError as e:
        assert e.reason == "content" and h.n_post == 1 and "recitation" in e.detail

    # holatni so'rashda 429 — kutib yana so'raydi (qo'shiq allaqachon tayyorlanyapti)
    pending = json.dumps({"id": "i1", "status": "in_progress"})
    h = Http([(200, pending)], [(429, BUSY), (200, OK)])
    audio, _ = await run(h)
    assert len(audio) == 6000 and h.n_post == 1 and h.n_get == 2

    print("test_lyria: OK")


if __name__ == "__main__":
    asyncio.run(main())
