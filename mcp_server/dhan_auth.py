"""
MKUMARAN Trading OS — Dhan TOTP Auto-Authentication

Generates and refreshes Dhan access tokens programmatically using the
DhanLogin SDK (v2.2.0+). No browser, no manual paste — just PIN + TOTP.

Flow:
  1. Check cached token in data/dhan_token.json — if valid for >1h, reuse.
  2. If expiring soon, try renew_token() (extends without re-login).
  3. If expired or no cache, generate fresh token via PIN + TOTP.

Env vars:
  DHAN_CLIENT_ID     — Dhan client ID (the numeric dhanClientId)
  DHAN_PIN           — 6-digit trading PIN
  DHAN_TOTP_KEY      — TOTP secret from Dhan's 2FA setup
  DHAN_ACCESS_TOKEN  — optional manual override (skips auto-login)
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_TOKEN_CACHE_PATH = Path("data/dhan_token.json")
_MIN_HOURS_REMAINING = 1.0


def _decode_jwt_exp(token: str) -> float:
    """Extract exp timestamp from a JWT without verifying signature."""
    try:
        import base64
        payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
        return float(payload.get("exp", 0))
    except Exception:
        return 0.0


def _hours_remaining(token: str) -> float:
    exp = _decode_jwt_exp(token)
    if exp <= 0:
        return 0.0
    return (exp - time.time()) / 3600


def _load_cached_token() -> str | None:
    """Load token from disk cache if still valid for >1h."""
    if not _TOKEN_CACHE_PATH.exists():
        return None
    try:
        data = json.loads(_TOKEN_CACHE_PATH.read_text())
        token = data.get("access_token", "")
        if token and _hours_remaining(token) > _MIN_HOURS_REMAINING:
            logger.info("Dhan token from cache — %.1fh remaining", _hours_remaining(token))
            return token
    except Exception as e:
        logger.debug("Dhan token cache read failed: %s", e)
    return None


def _save_token(token: str) -> None:
    try:
        _TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_CACHE_PATH.write_text(json.dumps({
            "access_token": token,
            "cached_at": datetime.now(tz=timezone.utc).isoformat(),
            "expires_at": datetime.fromtimestamp(
                _decode_jwt_exp(token), tz=timezone.utc
            ).isoformat() if _decode_jwt_exp(token) else "unknown",
        }))
    except Exception as e:
        logger.debug("Dhan token cache write failed: %s", e)


def _generate_totp() -> str:
    """Generate current TOTP code from the secret key."""
    totp_key = os.environ.get("DHAN_TOTP_KEY", "").strip()
    if not totp_key:
        raise ValueError("DHAN_TOTP_KEY not set")
    import pyotp
    return pyotp.TOTP(totp_key).now()


def generate_fresh_token() -> str:
    """Full login: PIN + TOTP → new access token."""
    from dhanhq.auth import DhanLogin

    client_id = os.environ.get("DHAN_CLIENT_ID", "").strip()
    pin = os.environ.get("DHAN_PIN", "").strip()
    if not client_id or not pin:
        raise ValueError("DHAN_CLIENT_ID and DHAN_PIN must be set")

    totp = _generate_totp()
    login = DhanLogin(client_id)
    resp = login.generate_token(pin=pin, totp=totp)

    if not resp or not isinstance(resp, dict):
        raise RuntimeError(f"Dhan generate_token returned: {resp}")

    token = resp.get("data", {}).get("accessToken") or resp.get("accessToken") or resp.get("access_token", "")
    if not token:
        raise RuntimeError(f"No accessToken in Dhan response: {resp}")

    _save_token(token)
    logger.info("Dhan token generated via TOTP — valid for %.1fh", _hours_remaining(token))
    return token


def renew_existing_token(current_token: str) -> str:
    """Renew an expiring (but not yet expired) token."""
    from dhanhq.auth import DhanLogin

    client_id = os.environ.get("DHAN_CLIENT_ID", "").strip()
    if not client_id:
        raise ValueError("DHAN_CLIENT_ID not set")

    login = DhanLogin(client_id)
    resp = login.renew_token(current_token)

    if not resp or not isinstance(resp, dict):
        raise RuntimeError(f"Dhan renew_token returned: {resp}")

    token = resp.get("data", {}).get("accessToken") or resp.get("accessToken") or resp.get("access_token", "")
    if not token:
        raise RuntimeError(f"No accessToken in Dhan renew response: {resp}")

    _save_token(token)
    logger.info("Dhan token renewed — valid for %.1fh", _hours_remaining(token))
    return token


def get_dhan_token() -> str:
    """Main entry: return a valid Dhan access token.

    Priority: env override → cached → renew → generate fresh.
    """
    # 1. Manual override from env (the user pasted one via Coolify)
    env_token = os.environ.get("DHAN_ACCESS_TOKEN", "").strip()
    if env_token and _hours_remaining(env_token) > _MIN_HOURS_REMAINING:
        return env_token

    # 2. Disk cache
    cached = _load_cached_token()
    if cached:
        return cached

    # 3. Try renewing the env/cached token (works if not fully expired)
    stale = env_token or (cached if cached else "")
    if stale and _hours_remaining(stale) > 0:
        try:
            return renew_existing_token(stale)
        except Exception as renew_err:
            logger.warning("Dhan token renew failed: %s — falling back to fresh generate", renew_err)

    # 4. Full TOTP login
    totp_key = os.environ.get("DHAN_TOTP_KEY", "").strip()
    pin = os.environ.get("DHAN_PIN", "").strip()
    if totp_key and pin:
        return generate_fresh_token()

    raise RuntimeError(
        "Dhan token expired and auto-refresh not possible "
        "(set DHAN_TOTP_KEY + DHAN_PIN for auto-login, or paste via /dhantoken)"
    )
