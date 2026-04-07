"""
MKUMARAN Trading OS — Goodwill (GWC) auto-login via direct API.

Flow (discovered via Playwright network recon):
  1. POST /v1/quickauth  {api_key, clnt_id, password(b64), factor2: totp}
        → {"status":"success","data":{"ru":"...?request_token=XXX"}}
  2. POST /v1/login-response  {api_key, request_token, signature}
        → {"status":"success","data":{"access_token":"..."}}

IMPORTANT: We deliberately skip /v1/getotp. That endpoint sends an SMS OTP
to the registered mobile number every time it is called, which is not
required when we already have a client-generated TOTP via pyotp. Going
straight to /v1/quickauth with factor2=totp works and avoids the SMS.

Tokens expire daily at midnight IST — we cache to data/gwc_token.json with
a date key and auto-refresh when stale.
"""

import base64
import hashlib
import json
import logging
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import pyotp
import requests

from mcp_server.config import settings

logger = logging.getLogger(__name__)

TOKEN_CACHE_PATH = Path("data/gwc_token.json")

# GWC API endpoints
BASE = "https://api.gwcindia.in/v1"
QUICKAUTH_URL = f"{BASE}/quickauth"
LOGIN_RESPONSE_URL = f"{BASE}/login-response"


# ══════════════════════════════════════════════════════════════
# Token cache
# ══════════════════════════════════════════════════════════════

def _load_cached_token() -> dict | None:
    """Load cached token if from today."""
    if not TOKEN_CACHE_PATH.exists():
        return None
    try:
        with open(TOKEN_CACHE_PATH) as f:
            data = json.load(f)
        if data.get("date") == str(date.today()):
            return data
    except (json.JSONDecodeError, KeyError, OSError):
        pass
    return None


def _save_token(access_token: str, request_token: str) -> None:
    """Persist token to cache with today's date."""
    TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_CACHE_PATH, "w") as f:
        json.dump({
            "access_token": access_token,
            "request_token": request_token,
            "date": str(date.today()),
            "timestamp": datetime.now().isoformat(),
        }, f, indent=2)
    logger.info("GWC token cached for %s", date.today())


# ══════════════════════════════════════════════════════════════
# Auto-login flow
# ══════════════════════════════════════════════════════════════

def _get_totp() -> str:
    """Generate current TOTP from GOODWILL_TOTP_KEY."""
    secret = getattr(settings, "GOODWILL_TOTP_KEY", "") or ""
    if not secret:
        raise RuntimeError("GOODWILL_TOTP_KEY not configured")
    return pyotp.TOTP(secret).now()


def _encode_password() -> str:
    """Base64-encode GOODWILL_PASSWORD (GWC requirement)."""
    pwd = getattr(settings, "GOODWILL_PASSWORD", "") or ""
    if not pwd:
        raise RuntimeError("GOODWILL_PASSWORD not configured")
    return base64.b64encode(pwd.encode()).decode()


def _step1_quickauth(api_key: str, client_id: str, password_b64: str, totp: str) -> str:
    """Submit client_id + password + TOTP. Returns request_token."""
    r = requests.post(
        QUICKAUTH_URL,
        json={
            "api_key": api_key,
            "clnt_id": client_id,
            "password": password_b64,
            "factor2": totp,
        },
        timeout=15,
    )
    data = r.json()
    if data.get("status") != "success":
        raise RuntimeError(f"GWC quickauth failed: {data.get('error_msg', data)}")

    ru = data.get("data", {}).get("ru", "")
    if not ru:
        raise RuntimeError(f"GWC quickauth response missing 'ru': {data}")

    parsed = urlparse(ru)
    params = parse_qs(parsed.query)
    if "request_token" not in params:
        raise RuntimeError(f"GWC redirect URL missing request_token: {ru}")
    return params["request_token"][0]


def _step2_exchange(api_key: str, api_secret: str, request_token: str) -> str:
    """Exchange request_token for access_token via signature."""
    signature = hashlib.sha256(
        (api_key + request_token + api_secret).encode()
    ).hexdigest()
    r = requests.post(
        LOGIN_RESPONSE_URL,
        json={
            "api_key": api_key,
            "request_token": request_token,
            "signature": signature,
        },
        timeout=15,
    )
    data = r.json()
    if data.get("status") != "success":
        raise RuntimeError(f"GWC login-response failed: {data.get('error_msg', data)}")

    access_token = data.get("data", {}).get("access_token", "")
    if not access_token:
        raise RuntimeError(f"GWC login-response missing access_token: {data}")
    return access_token


def refresh_gwc_token() -> str:
    """
    Full GWC login flow using direct API (no browser).
    Returns access_token, caches to disk for the day.
    """
    cached = _load_cached_token()
    if cached:
        logger.info("Using cached GWC token from %s", cached["date"])
        return cached["access_token"]

    api_key = settings.GWC_API_KEY
    api_secret = settings.GWC_API_SECRET
    client_id = getattr(settings, "GWC_CLIENT_ID", "") or ""

    if not api_key or not api_secret or not client_id:
        raise RuntimeError(
            "GWC credentials incomplete: need GWC_API_KEY, GWC_API_SECRET, GWC_CLIENT_ID"
        )

    password_b64 = _encode_password()
    totp = _get_totp()

    logger.info("Refreshing GWC token via direct API (client_id=%s)...", client_id)
    request_token = _step1_quickauth(api_key, client_id, password_b64, totp)
    logger.info("GWC quickauth OK, got request_token")

    access_token = _step2_exchange(api_key, api_secret, request_token)
    _save_token(access_token, request_token)
    logger.info("GWC token refreshed successfully")
    return access_token


def get_gwc_login_url() -> str:
    """Return manual browser login URL (fallback)."""
    return f"{BASE}/login?api_key={settings.GWC_API_KEY}"


def handle_gwc_callback(request_token: str) -> str:
    """Exchange a request_token from browser redirect into an access_token.

    Used by /api/gwc_callback endpoint when the user completes manual
    browser login instead of the auto-login flow.
    """
    access_token = _step2_exchange(
        settings.GWC_API_KEY,
        settings.GWC_API_SECRET,
        request_token,
    )
    _save_token(access_token, request_token)
    logger.info("GWC manual login successful — token cached")
    return access_token
