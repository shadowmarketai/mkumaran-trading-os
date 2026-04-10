"""
MKUMARAN Trading OS — Unified AI Provider

Routes AI calls to Grok (xAI) or Kimi (Moonshot) instead of Claude/GPT.
Both use OpenAI-compatible APIs, so we use the openai SDK with custom base_url.

Provider priority (configurable via AI_PRIMARY_PROVIDER):
  1. grok  → api.x.ai (xAI Grok)
  2. kimi  → api.moonshot.cn (Moonshot Kimi)

Fallback: if primary fails, tries secondary automatically.

Environment variables:
  GROK_API_KEY          — xAI API key
  GROK_MODEL            — Model name (default: grok-3-mini)
  KIMI_API_KEY          — Moonshot API key
  KIMI_MODEL            — Model name (default: moonshot-v1-8k)
  AI_PRIMARY_PROVIDER   — "grok" or "kimi" (default: grok)
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────
GROK_API_KEY = os.getenv("GROK_API_KEY", "")
GROK_MODEL = os.getenv("GROK_MODEL", "grok-3-mini")
GROK_BASE_URL = "https://api.x.ai/v1"

KIMI_API_KEY = os.getenv("KIMI_API_KEY", "")
KIMI_MODEL = os.getenv("KIMI_MODEL", "moonshot-v1-8k")
KIMI_BASE_URL = "https://api.moonshot.cn/v1"

AI_PRIMARY_PROVIDER = os.getenv("AI_PRIMARY_PROVIDER", "grok").lower()

# Track availability
_provider_errors: dict[str, int] = {"grok": 0, "kimi": 0}


def _get_client(provider: str):
    """Get OpenAI-compatible client for the specified provider."""
    from openai import OpenAI

    if provider == "grok":
        if not GROK_API_KEY:
            raise ValueError("GROK_API_KEY not configured")
        return OpenAI(api_key=GROK_API_KEY, base_url=GROK_BASE_URL)
    elif provider == "kimi":
        if not KIMI_API_KEY:
            raise ValueError("KIMI_API_KEY not configured")
        return OpenAI(api_key=KIMI_API_KEY, base_url=KIMI_BASE_URL)
    else:
        raise ValueError(f"Unknown AI provider: {provider}")


def _get_model(provider: str) -> str:
    """Get model name for provider."""
    if provider == "grok":
        return GROK_MODEL
    elif provider == "kimi":
        return KIMI_MODEL
    return GROK_MODEL


def _get_providers() -> list[str]:
    """Get ordered list of providers to try (primary first, then fallback)."""
    providers = []
    if AI_PRIMARY_PROVIDER == "grok" and GROK_API_KEY:
        providers.append("grok")
    if AI_PRIMARY_PROVIDER == "kimi" and KIMI_API_KEY:
        providers.append("kimi")
    # Add fallback
    if "grok" not in providers and GROK_API_KEY:
        providers.append("grok")
    if "kimi" not in providers and KIMI_API_KEY:
        providers.append("kimi")
    return providers


# ── Core AI Call Functions ───────────────────────────────────

def call_ai(
    prompt: str,
    max_tokens: int = 500,
    system_prompt: str | None = None,
    temperature: float = 0.3,
    provider: str | None = None,
) -> str:
    """Call AI provider with automatic fallback.

    This is the primary function used across the entire system.
    Replaces both _call_claude() and _call_gpt().

    Args:
        prompt: User message content
        max_tokens: Max response tokens
        system_prompt: Optional system message
        temperature: Creativity (0.0 = deterministic, 1.0 = creative)
        provider: Force specific provider ("grok" or "kimi"), or None for auto

    Returns:
        AI response text, or error JSON string on failure
    """
    providers = [provider] if provider else _get_providers()

    if not providers:
        logger.error("No AI providers configured. Set GROK_API_KEY or KIMI_API_KEY.")
        return '{"error": "No AI provider configured"}'

    last_error = None
    for prov in providers:
        try:
            client = _get_client(prov)
            model = _get_model(prov)

            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            result = response.choices[0].message.content.strip()
            _provider_errors[prov] = 0  # Reset error count on success
            logger.debug("AI call OK via %s/%s (%d tokens)", prov, model, max_tokens)
            return result

        except Exception as e:
            _provider_errors[prov] = _provider_errors.get(prov, 0) + 1
            last_error = e
            logger.warning("AI call failed via %s: %s (errors: %d)",
                           prov, str(e)[:100], _provider_errors[prov])
            continue

    logger.error("All AI providers failed. Last error: %s", last_error)
    return f'{{"error": "{last_error}"}}'


def call_ai_with_system(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 500,
    temperature: float = 0.3,
) -> dict:
    """Call AI with system + user prompts, parse JSON response.

    Used by debate_validator.py for structured responses.

    Returns:
        Parsed dict from JSON response, or {"error": ...} on failure
    """
    import json

    raw = call_ai(
        prompt=user_prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    try:
        # Extract JSON from response
        if "{" in raw:
            json_str = raw[raw.index("{"):raw.rindex("}") + 1]
            return json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        pass

    return {"raw_response": raw, "confidence": 50, "recommendation": "WATCHLIST"}


def call_ai_second_opinion(
    prompt: str,
    max_tokens: int = 200,
    temperature: float = 0.3,
) -> str:
    """Call secondary provider for a second opinion.

    Used by validator.py for GPT second opinion on borderline signals.
    Routes to whichever provider is NOT the primary.
    """
    providers = _get_providers()
    # Use the second provider if available, otherwise primary
    secondary = providers[1] if len(providers) > 1 else providers[0] if providers else None
    if not secondary:
        return ""

    return call_ai(prompt=prompt, max_tokens=max_tokens,
                   temperature=temperature, provider=secondary)


# ── Status / Health ──────────────────────────────────────────

def get_ai_status() -> dict[str, Any]:
    """Get current AI provider status for health checks."""
    providers = _get_providers()
    return {
        "primary": AI_PRIMARY_PROVIDER,
        "available_providers": providers,
        "grok_configured": bool(GROK_API_KEY),
        "kimi_configured": bool(KIMI_API_KEY),
        "grok_model": GROK_MODEL,
        "kimi_model": KIMI_MODEL,
        "error_counts": dict(_provider_errors),
    }
