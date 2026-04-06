"""
Angel One SmartAPI — auto-login with TOTP and token caching.

Mirrors the kite_auth.py pattern: cache today's JWT token to disk,
refresh via TOTP login when stale.
"""

import json
import logging
from datetime import datetime, date
from pathlib import Path

import pyotp

from mcp_server.config import settings

logger = logging.getLogger(__name__)

TOKEN_CACHE_PATH = Path("data/angel_token.json")


def get_totp() -> str:
    """Generate current TOTP from Angel TOTP secret."""
    return pyotp.TOTP(settings.ANGEL_TOTP_SECRET).now()


def _load_cached_token() -> dict | None:
    """Load cached Angel token if it exists and is from today."""
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


def _save_token(jwt_token: str, refresh_token: str, feed_token: str) -> None:
    """Save Angel tokens to cache file."""
    TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_CACHE_PATH, "w") as f:
        json.dump({
            "jwt_token": jwt_token,
            "refresh_token": refresh_token,
            "feed_token": feed_token,
            "date": str(date.today()),
            "timestamp": datetime.now().isoformat(),
        }, f, indent=2)
    logger.info("Angel token cached for %s", date.today())


def refresh_angel_token():
    """
    Login to Angel SmartAPI via TOTP, cache JWT, return SmartConnect client.

    Returns:
        SmartConnect client with access token set.
    """
    from SmartApi import SmartConnect

    cached = _load_cached_token()
    if cached:
        logger.info("Using cached Angel token from %s", cached["date"])
        client = SmartConnect(api_key=settings.ANGEL_API_KEY)
        client.setAccessToken(cached["jwt_token"])
        return client

    logger.info("Refreshing Angel token via TOTP login...")

    client = SmartConnect(api_key=settings.ANGEL_API_KEY)
    totp = get_totp()

    data = client.generateSession(
        settings.ANGEL_CLIENT_ID,
        settings.ANGEL_PASSWORD,
        totp,
    )

    if not data or not data.get("status"):
        raise RuntimeError(f"Angel login failed: {data}")

    jwt_token = data["data"]["jwtToken"]
    refresh_token = data["data"].get("refreshToken", "")
    feed_token = data["data"].get("feedToken", "")

    client.setAccessToken(jwt_token)

    _save_token(jwt_token, refresh_token, feed_token)
    logger.info("Angel token refreshed successfully")

    return client


def get_authenticated_angel():
    """Get an authenticated SmartConnect instance (with caching)."""
    return refresh_angel_token()
