"""
MKUMARAN Trading OS — Multi-Provider AI Engine

Supports 6 LLM providers with per-user BYOK keys:
  1. Grok    (xAI)        — api.x.ai/v1
  2. Kimi    (Moonshot)   — api.moonshot.cn/v1
  3. OpenAI  (GPT)        — api.openai.com/v1
  4. Claude  (Anthropic)  — Anthropic SDK
  5. Gemini  (Google)     — Google GenAI SDK
  6. DeepSeek             — api.deepseek.com/v1

Priority: User's BYOK key → System default → Fallback chain.
Auto-detects provider from key format when possible.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

# ── System-level config (env vars) ───────────────────────────
PROVIDERS = {
    "grok": {
        "base_url": "https://api.x.ai/v1",
        "model": os.getenv("GROK_MODEL", "grok-3-mini"),
        "system_key": os.getenv("GROK_API_KEY", ""),
        "type": "openai_compat",
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "model": os.getenv("KIMI_MODEL", "moonshot-v1-8k"),
        "system_key": os.getenv("KIMI_API_KEY", ""),
        "type": "openai_compat",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "system_key": os.getenv("OPENAI_API_KEY", ""),
        "type": "openai_compat",
    },
    "claude": {
        "base_url": "https://api.anthropic.com",
        "model": os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
        "system_key": os.getenv("ANTHROPIC_API_KEY", ""),
        "type": "anthropic",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com",
        "model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        "system_key": os.getenv("GEMINI_API_KEY", ""),
        "type": "gemini",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "system_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "type": "openai_compat",
    },
}

AI_PRIMARY = os.getenv("AI_PRIMARY_PROVIDER", "grok").lower()


# ── Key format auto-detection ────────────────────────────────

def detect_provider(key: str) -> str | None:
    """Auto-detect provider from API key format."""
    key = key.strip()
    if key.startswith("xai-"):
        return "grok"
    if key.startswith("sk-ant-"):
        return "claude"
    if key.startswith("AIza"):
        return "gemini"
    # Ambiguous sk- keys — check length patterns
    if key.startswith("sk-") and len(key) > 80:
        return "openai"  # OpenAI keys tend to be longer
    return None


# ── Call a specific provider ─────────────────────────────────

def _call_openai_compat(api_key: str, base_url: str, model: str,
                         prompt: str, system_prompt: str | None,
                         max_tokens: int, temperature: float) -> str:
    """Call OpenAI-compatible API (Grok, Kimi, OpenAI, DeepSeek)."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    resp = client.chat.completions.create(
        model=model, messages=messages,
        max_tokens=max_tokens, temperature=temperature,
    )
    return resp.choices[0].message.content.strip()


def _call_claude(api_key: str, model: str, prompt: str,
                  system_prompt: str | None, max_tokens: int,
                  temperature: float) -> str:
    """Call Anthropic Claude API."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    resp = client.messages.create(**kwargs)
    return resp.content[0].text.strip()


def _call_gemini(api_key: str, model: str, prompt: str,
                  system_prompt: str | None, max_tokens: int) -> str:
    """Call Google Gemini API."""
    import httpx
    full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
    resp = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
        json={"contents": [{"parts": [{"text": full_prompt}]}],
              "generationConfig": {"maxOutputTokens": max_tokens}},
        timeout=30,
    )
    if resp.status_code == 200:
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    raise ValueError(f"Gemini API error {resp.status_code}: {resp.text[:200]}")


def _call_provider(provider: str, api_key: str, prompt: str,
                    system_prompt: str | None, max_tokens: int,
                    temperature: float) -> str:
    """Route call to the correct provider backend."""
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise ValueError(f"Unknown provider: {provider}")

    model = cfg["model"]
    ptype = cfg["type"]

    if ptype == "openai_compat":
        return _call_openai_compat(api_key, cfg["base_url"], model,
                                    prompt, system_prompt, max_tokens, temperature)
    elif ptype == "anthropic":
        return _call_claude(api_key, model, prompt, system_prompt,
                             max_tokens, temperature)
    elif ptype == "gemini":
        return _call_gemini(api_key, model, prompt, system_prompt, max_tokens)

    raise ValueError(f"Unknown provider type: {ptype}")


# ── Per-user key lookup ──────────────────────────────────────

def _get_user_keys(user_email: str | None) -> dict:
    """Get user's BYOK keys if available."""
    if not user_email:
        return {}
    try:
        from mcp_server.db import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        try:
            row = db.execute(
                text("SELECT setting_value FROM user_settings WHERE setting_key = :k"),
                {"k": f"llm_keys:{user_email}"}
            ).first()
            if row:
                from mcp_server.config import settings
                from mcp_server.auth_providers import _xor_decrypt
                return json.loads(_xor_decrypt(row[0], settings.JWT_SECRET_KEY))
        except Exception:
            pass
        finally:
            db.close()
    except Exception:
        pass
    return {}


def _resolve_key_and_provider(user_email: str | None = None,
                                preferred: str | None = None) -> list[tuple[str, str]]:
    """Resolve which provider+key pairs to try, in priority order.

    Returns list of (provider_name, api_key) tuples.
    Priority: user BYOK key → system default → fallback chain.
    """
    attempts = []

    # 1. User's BYOK keys (if available)
    if user_email:
        user_keys = _get_user_keys(user_email)
        user_pref = user_keys.get("preferred_provider", "")

        # User's preferred provider first
        if user_pref and user_keys.get(f"{user_pref}_key"):
            attempts.append((user_pref, user_keys[f"{user_pref}_key"]))

        # Then all other user keys
        for provider in PROVIDERS:
            key = user_keys.get(f"{provider}_key", "")
            if key and (provider, key) not in attempts:
                attempts.append((provider, key))

    # 2. System defaults
    # Primary
    primary = preferred or AI_PRIMARY
    if PROVIDERS.get(primary, {}).get("system_key"):
        pair = (primary, PROVIDERS[primary]["system_key"])
        if pair not in attempts:
            attempts.append(pair)

    # Fallbacks
    for provider, cfg in PROVIDERS.items():
        if cfg.get("system_key"):
            pair = (provider, cfg["system_key"])
            if pair not in attempts:
                attempts.append(pair)

    return attempts


# ── Public API ───────────────────────────────────────────────

def call_ai(
    prompt: str,
    max_tokens: int = 500,
    system_prompt: str | None = None,
    temperature: float = 0.3,
    provider: str | None = None,
    user_email: str | None = None,
) -> str:
    """Call AI with automatic provider resolution and fallback.

    Args:
        prompt: User message
        max_tokens: Max response tokens
        system_prompt: Optional system message
        temperature: 0.0-1.0
        provider: Force specific provider (skip resolution)
        user_email: User email for BYOK key lookup

    Returns:
        AI response text
    """
    attempts = _resolve_key_and_provider(user_email, provider)

    if not attempts:
        logger.error("No AI providers configured and no BYOK keys available")
        return '{"error": "No AI provider available"}'

    last_err = None
    for prov, key in attempts:
        try:
            result = _call_provider(prov, key, prompt, system_prompt,
                                     max_tokens, temperature)
            is_byok = user_email and key != PROVIDERS.get(prov, {}).get("system_key", "")
            logger.debug("AI call OK via %s (byok=%s, tokens=%d)", prov, is_byok, max_tokens)
            return result
        except Exception as e:
            last_err = e
            logger.warning("AI call failed via %s: %s", prov, str(e)[:100])

    logger.error("All AI providers failed. Last: %s", last_err)
    return f'{{"error": "{last_err}"}}'


def call_ai_with_system(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 500,
    temperature: float = 0.3,
    user_email: str | None = None,
) -> dict:
    """Call AI with system+user prompts, parse JSON response."""
    raw = call_ai(prompt=user_prompt, system_prompt=system_prompt,
                   max_tokens=max_tokens, temperature=temperature,
                   user_email=user_email)
    try:
        if "{" in raw:
            return json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except (json.JSONDecodeError, ValueError):
        pass
    return {"raw_response": raw, "confidence": 50, "recommendation": "WATCHLIST"}


def call_ai_second_opinion(
    prompt: str, max_tokens: int = 200, temperature: float = 0.3,
    user_email: str | None = None,
) -> str:
    """Call secondary provider for second opinion."""
    attempts = _resolve_key_and_provider(user_email)
    secondary = attempts[1] if len(attempts) > 1 else attempts[0] if attempts else None
    if not secondary:
        return ""
    return call_ai(prompt=prompt, max_tokens=max_tokens, temperature=temperature,
                    provider=secondary[0], user_email=user_email)


# ── Status ───────────────────────────────────────────────────

def get_ai_status(user_email: str | None = None) -> dict:
    """Get AI provider status."""
    system_available = [p for p, c in PROVIDERS.items() if c.get("system_key")]
    user_keys = _get_user_keys(user_email) if user_email else {}
    user_providers = [p for p in PROVIDERS if user_keys.get(f"{p}_key")]

    return {
        "primary": AI_PRIMARY,
        "system_providers": system_available,
        "user_providers": user_providers,
        "has_byok": bool(user_providers),
        "supported": list(PROVIDERS.keys()),
    }
