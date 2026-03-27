import json
import logging
import time
from datetime import datetime, date
from pathlib import Path

import pyotp
import requests

from mcp_server.config import settings

logger = logging.getLogger(__name__)

TOKEN_CACHE_PATH = Path("data/kite_token.json")


def get_totp() -> str:
    """Generate current TOTP from secret key."""
    totp = pyotp.TOTP(settings.KITE_TOTP_KEY)
    return totp.now()


def _load_cached_token() -> dict | None:
    """Load cached token if it exists and is from today."""
    if not TOKEN_CACHE_PATH.exists():
        return None
    try:
        with open(TOKEN_CACHE_PATH) as f:
            data = json.load(f)
        if data.get("date") == str(date.today()):
            return data
    except (json.JSONDecodeError, KeyError):
        pass
    return None


def _save_token(access_token: str, request_token: str) -> None:
    """Save token to cache file."""
    TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_CACHE_PATH, "w") as f:
        json.dump({
            "access_token": access_token,
            "request_token": request_token,
            "date": str(date.today()),
            "timestamp": datetime.now().isoformat()
        }, f, indent=2)
    logger.info("Kite token cached for %s", date.today())


def refresh_kite_token() -> str:
    """
    Full Kite login flow with TOTP:
    1. POST login with user_id + password
    2. POST twofa with TOTP
    3. POST session token exchange
    Returns access_token.
    """
    # Check cache first
    cached = _load_cached_token()
    if cached:
        logger.info("Using cached Kite token from %s", cached["date"])
        return cached["access_token"]

    logger.info("Refreshing Kite token via TOTP login...")

    session = requests.Session()

    # Step 1: Login
    login_url = "https://kite.zerodha.com/api/login"
    login_resp = session.post(login_url, data={
        "user_id": settings.KITE_USER_ID,
        "password": settings.KITE_PASSWORD,
    })
    login_data = login_resp.json()

    if login_data.get("status") != "success":
        raise RuntimeError(f"Kite login failed: {login_data}")

    request_token = login_data["data"]["request_token"]

    # Step 2: TOTP
    twofa_url = "https://kite.zerodha.com/api/twofa"
    totp_value = get_totp()
    twofa_resp = session.post(twofa_url, data={
        "user_id": settings.KITE_USER_ID,
        "request_token": request_token,
        "twofa_value": totp_value,
        "twofa_type": "totp",
    })
    twofa_data = twofa_resp.json()

    if twofa_data.get("status") != "success":
        raise RuntimeError(f"Kite TOTP failed: {twofa_data}")

    # Step 3: Generate session (via kiteconnect SDK)
    from kiteconnect import KiteConnect
    kite = KiteConnect(api_key=settings.KITE_API_KEY)
    session_data = kite.generate_session(
        request_token, api_secret=settings.KITE_API_SECRET
    )
    access_token = session_data["access_token"]

    _save_token(access_token, request_token)
    logger.info("Kite token refreshed successfully")

    return access_token


def get_authenticated_kite():
    """Get an authenticated KiteConnect instance."""
    from kiteconnect import KiteConnect
    access_token = refresh_kite_token()
    kite = KiteConnect(api_key=settings.KITE_API_KEY)
    kite.set_access_token(access_token)
    return kite
