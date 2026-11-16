"""AI xizmati: Anthropic/Gemini almashtirgich, Gemini so'rovi va javobi, model narxi bo'yicha xarajat.

Ishga tushirish: python -m tests.test_llm
"""

import asyncio
import json
import os
import tempfile
from types import SimpleNamespace

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/llm.db"
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_IDS"] = "999"

from app import ai, costs, llm, store  # noqa: E402
from app.config import RUNTIME  # noqa: E402
from app.db import init_db  # noqa: E402

SENT = []


class FakeResp:
    def __init__(self, status, body):
        self.status, self._body = status, body

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeSession:
    reply = (200, "{}")

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def post(self, url, headers=None, json=None):
        SENT.append((url, headers, json))
        return FakeResp(*FakeSession.reply)


async def main() -> None:
    await init_db()
    llm.aiohttp.ClientSession = FakeSession

    # standart: Anthropic, hozirgi model
    cfg = await llm.config()
    assert cfg["provider"] == "anthropic" and cfg["gemini"]["main"] == "gemini-3.8-flash"
    # Gemini tanlansa-yu kalit bo'lmasa — Anthropic ishlayveradi
    await llm.save("gemini", {"gemini": {"main": "gemini-4-hydrogen", "light": "nomalum-model"}})
    cfg = await llm.config()
    assert cfg["provider"] == "gemini" and cfg["gemini"]["main"] == "gemini-4-hydrogen" and cfg["gemini"]["light"] == "gemini-3.5-flash-lite"
    assert (await llm.active("main"))[0] == "anthropic"
    RUNTIME["gemini_key"] = "AIzaTESTkey_1234567890abcd"
    assert await llm.active("main") == ("gemini", "gemini-4-hydrogen")
    assert await llm.active("light") == ("gemini", "gemini-3.5-flash-lite")

    # Gemini so'rovi: tizim ko'rsatmasi, JSON sxema, fikrlash darajasi; javobdan matn va tokenlar (fikrlash ham chiqishga)
    FakeSession.reply = (200, json.dumps({
        "candidates": [{"content": {"parts": [{"text": "o'ylash", "thought": True}, {"text": '{"reply": "ok"}'}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 1200, "candidatesTokenCount": 300, "thoughtsTokenCount": 500}}))
    resp = await ai.client.beta.messages.create(max_tokens=4000, system=ai.TRANSLATE_SYSTEM,
                                                messages=[{"role": "user", "content": "Salom"}],
                                                output_config={"effort": "low", "format": {"type": "json_schema", "schema": {"type": "object"}}})
    url, headers, body = SENT[-1]
    assert url.endswith("/models/gemini-3.5-flash-lite:generateContent"), url  # tarjima — yengil model
    assert headers["x-goog-api-key"] == "AIzaTESTkey_1234567890abcd"
    assert body["system_instruction"]["parts"][0]["text"] == ai.TRANSLATE_SYSTEM
    assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "low"
    assert body["generationConfig"]["responseFormat"]["text"]["mimeType"] == "APPLICATION_JSON"
    assert resp.content[0].text == '{"reply": "ok"}' and resp.usage.input_tokens == 1200 and resp.usage.output_tokens == 800
    # «high» so'ralsa ham xarajat uchun «medium» yuboriladi; asosiy vazifa — asosiy model
    await ai.client.beta.messages.create(max_tokens=8000, system=ai.WRITER_SYSTEM, messages=[{"role": "user", "content": "x"}],
                                         output_config={"effort": "high"})
    url, _, body = SENT[-1]
    assert "gemini-4-hydrogen" in url and body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "medium"
    assert "responseFormat" not in body["generationConfig"]

    # xato va bo'sh javob — AIError
    FakeSession.reply = (429, '{"error": "quota"}')
    try:
        await ai.client.beta.messages.create(max_tokens=10, messages=[{"role": "user", "content": "x"}])
        raise AssertionError("xato o'tib ketdi")
    except ai.AIError:
        pass
    FakeSession.reply = (200, json.dumps({"candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}]}))
    try:
        await ai.client.beta.messages.create(max_tokens=10, messages=[{"role": "user", "content": "x"}])
        raise AssertionError("bo'sh javob o'tib ketdi")
    except ai.AIError:
        pass

    # xarajat: har model o'z narxida (Opus 4/20, Haiku 0.10/0.50, Gemini Hydrogen 1.5/7.5); noma'lum model — paneldagi narx
    r = await costs.rates()
    opus = costs.som_of("ai", 1_000_000, 1_000_000, r, "claude-opus-5-5")
    haiku = costs.som_of("ai", 1_000_000, 1_000_000, r, "claude-haiku-5-5")
    hyd = costs.som_of("ai", 1_000_000, 1_000_000, r, "gemini-4-hydrogen")
    assert round(opus) == round(24 * r["usd_som"]) and round(haiku) == round(0.6 * r["usd_som"]) and round(hyd) == round(9 * r["usd_som"])
    assert costs.som_of("ai", 1_000_000, 0, r, "") == r["ai_in_per_m"] * r["usd_som"]
    row = costs.ai_row(SimpleNamespace(input_tokens=10, output_tokens=5, model="gemini-3.8-flash"), "site_text")
    assert row.model == "gemini-3.8-flash"

    # qaytarish: Anthropic
    await llm.save("anthropic", {})
    assert (await llm.active("main"))[0] == "anthropic"
    store.forget()
    print("✅ AI xizmati tekshiruvlari o'tdi")


asyncio.run(main())


def routes() -> None:
    """Admin manzillari boshqa bo'limlar bilan to'qnashmasin (masalan, video kuylarini yuklash /api/admin/music)."""
    os.environ.setdefault("ADMIN_IDS", "999")
    from fastapi.testclient import TestClient
    from app import admin
    from app.web import app
    c, h = TestClient(app), {"X-Admin-Token": admin.make_token(999)}
    r = c.post("/api/admin/song-provider", json={"provider": "elevenlabs", "lang": "uz", "gemini_key": "AIzaSyD-TEST_key1234567890abcdefGHIJ"}, headers=h)
    assert r.status_code == 200 and r.json()["lyria_key"] and "AIza" not in r.text, r.text
    r = c.post("/api/admin/ai", json={"provider": "anthropic", "gemini": {"main": "gemini-3.8-flash"}}, headers=h)
    assert r.status_code == 200 and r.json()["gemini"]["main"] == "gemini-3.8-flash", r.text
    print("✅ Admin manzillari tekshiruvi o'tdi")


routes()
