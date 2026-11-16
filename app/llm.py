"""Matn yozuvchi AI: Anthropic (Claude) yoki Google (Gemini). Qaysi xizmat va model — admin paneldan tanlanadi.

Barcha AI chaqiruvlari shu yerdan o'tadi: generate(tier, system, prompt, ...) -> (matn, usage).
  tier «main»  — qo'shiq she'ri, sayt matni, sayt tahriri (sifat muhim)
  tier «light» — video matni, tarjima (oddiy ish, arzon model yetarli)
Narxlar rasmiy sahifalardan ($ / 1 mln token, kirish va chiqish; chiqishga fikrlash tokenlari ham kiradi):
  Anthropic: platform.claude.com/docs/en/about-claude/pricing; Google: aistudio.google.com/docs/pricing
"""

import json
import logging
from types import SimpleNamespace

import aiohttp
import anthropic

from . import store
from .config import settings

log = logging.getLogger(__name__)

KEY = "ai"
PROVIDERS = {"anthropic": "Anthropic (Claude)", "gemini": "Google (Gemini)"}
# model -> (nomi, kirish $, chiqish $)
MODELS = {
    "anthropic": {
        "claude-opus-5-5": ("Claude Opus 5.5 — eng kuchli", 4.0, 20.0),
        "claude-sonnet-5-5": ("Claude Sonnet 5.5 — muvozanatli", 2.0, 10.0),
        "claude-haiku-5-5": ("Claude Haiku 5.5 — eng arzon", 0.10, 0.50),
    },
    "gemini": {
        "gemini-4-hydrogen": ("Gemini 4 Hydrogen", 1.50, 7.50),
        "gemini-3.8-flash": ("Gemini 3.8 Flash", 0.75, 3.75),
        "gemini-3.5-flash-lite": ("Gemini 3.5 Flash-Lite", 0.30, 2.50),
        "gemini-3.1-flash-lite": ("Gemini 3.1 Flash-Lite — eng arzon", 0.25, 1.50),
        "gemini-4-argon": ("Gemini 4 Argon", 2.0, 10.0),
    },
}
DEFAULTS = {
    "provider": "anthropic",
    "anthropic": {"main": settings.ai_model, "light": settings.ai_model},
    "gemini": {"main": "gemini-3.8-flash", "light": "gemini-3.5-flash-lite"},
}
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_client: anthropic.AsyncAnthropic | None = None


class LLMError(Exception):
    pass


def price(model: str) -> tuple[float, float] | None:
    for models in MODELS.values():
        if model in models:
            return models[model][1], models[model][2]
    return None


async def config() -> dict:
    v = await store.get(KEY) or {}
    out = {"provider": v.get("provider", DEFAULTS["provider"])}
    for p in MODELS:
        cur = v.get(p) or {}
        out[p] = {t: cur.get(t) if cur.get(t) in MODELS[p] else DEFAULTS[p][t] for t in ("main", "light")}
    return out


async def save(provider: str | None, models: dict) -> dict:
    cfg = await config()
    if provider in PROVIDERS:
        cfg["provider"] = provider
    for p, tiers in (models or {}).items():
        for t, m in (tiers or {}).items():
            if p in MODELS and t in ("main", "light") and m in MODELS[p]:
                cfg[p][t] = m
    await store.put(KEY, cfg)
    return cfg


async def active(tier: str) -> tuple[str, str]:
    """(xizmat, model). Gemini tanlangan, lekin kaliti yo'q bo'lsa — Anthropic."""
    cfg = await config()
    p = cfg["provider"]
    if p == "gemini" and not settings.gemini_key:
        p = "anthropic"
    return p, cfg[p][tier]


async def generate(tier: str, system: str, prompt: str, max_tokens: int, effort: str = "medium",
                   schema: dict | None = None, provider: str | None = None, model: str | None = None):
    """Matn (schema bo'lsa — JSON matn) va usage (input_tokens, output_tokens, model)."""
    if not provider or not model:
        provider, model = await active(tier)
    if provider == "gemini":
        return await _gemini(model, system, prompt, max_tokens, effort, schema)
    return await _anthropic(model, system, prompt, max_tokens, effort, schema)


# ---------------------------------------------------------------- Anthropic

def _anthropic_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or None)
    return _client


async def _anthropic(model, system, prompt, max_tokens, effort, schema):
    output_config = {"effort": effort}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    args = dict(model=model, max_tokens=max_tokens, output_config=output_config, system=system,
                messages=[{"role": "user", "content": prompt}])
    if model != "claude-haiku-5-5":  # Haiku 5.5 da server tomonidagi zaxira model yo'q
        args.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        resp = await _anthropic_client().beta.messages.create(**args)
    else:
        resp = await _anthropic_client().messages.create(**args)
    if resp.stop_reason == "refusal":
        raise LLMError("refusal")
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    u = resp.usage
    tin = (u.input_tokens or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0)
    return text, SimpleNamespace(input_tokens=tin, output_tokens=u.output_tokens or 0, model=getattr(resp, "model", model) or model)


# ---------------------------------------------------------------- Google Gemini (generateContent)

async def _gemini(model, system, prompt, max_tokens, effort, schema):
    key = settings.gemini_key
    if not key:
        raise LLMError("Gemini kaliti kiritilmagan")
    gen = {"maxOutputTokens": max_tokens, "thinkingConfig": {"thinkingLevel": effort if effort in ("low", "medium", "high") else "medium"}}
    if schema:
        gen["responseFormat"] = {"text": {"mimeType": "APPLICATION_JSON", "schema": schema}}
    body = {"system_instruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": gen}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as http:
        async with http.post(GEMINI_URL.format(model=model), headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                             json=body) as r:
            raw = await r.text()
            if r.status != 200:
                log.warning("Gemini %s %s: %s", model, r.status, raw[:1500])
                raise LLMError(f"gemini {r.status}")
    data = json.loads(raw)
    cand = (data.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    um = data.get("usageMetadata") or {}
    usage = SimpleNamespace(input_tokens=int(um.get("promptTokenCount") or 0),
                            output_tokens=int(um.get("candidatesTokenCount") or 0) + int(um.get("thoughtsTokenCount") or 0),
                            model=model)
    if not text:
        log.warning("Gemini bo'sh javob (%s): %s", cand.get("finishReason"), raw[:800])
        raise LLMError(f"empty:{cand.get('finishReason')}")
    return text, usage
