import json
import logging
import re
import time
from datetime import datetime, date
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import pyotp
import requests

from mcp_server.config import settings

logger = logging.getLogger(__name__)

TOKEN_CACHE_PATH = Path("data/kite_token.json")

# Kite Connect endpoints
LOGIN_URL = "https://kite.zerodha.com/api/login"
TWOFA_URL = "https://kite.zerodha.com/api/twofa"
LOGIN_REFERER = "https://kite.trade/connect/login?v=3&api_key="


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
    1. GET login_url — establish session with Kite
    2. POST /api/login — authenticate with user_id + password → get request_id
    3. POST /api/twofa — verify TOTP with request_id
    4. GET login_url?skip_session=true — redirect contains request_token
    5. kite.generate_session(request_token) → access_token
    Returns access_token.
    """
    # Check cache first
    cached = _load_cached_token()
    if cached:
        logger.info("Using cached Kite token from %s", cached["date"])
        return cached["access_token"]

    logger.info("Refreshing Kite token via TOTP login...")

    from kiteconnect import KiteConnect
    kite = KiteConnect(api_key=settings.KITE_API_KEY)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "X-Kite-Version": "3",
    })

    # Step 1: Visit login page to establish session cookies
    login_page_url = kite.login_url()
    logger.info("Step 1: Visiting login page...")
    page_resp = session.get(login_page_url)
    ref_url = page_resp.url  # May redirect, save final URL
    logger.info("Login page loaded, ref_url: %s", ref_url.split("?")[0])

    # Step 2: POST login with credentials → returns request_id
    logger.info("Step 2: Submitting credentials...")
    login_resp = session.post(LOGIN_URL, data={
        "user_id": settings.KITE_USER_ID,
        "password": settings.KITE_PASSWORD,
    })
    login_data = login_resp.json()
    logger.info("Login response status: %s", login_data.get("status"))

    if login_data.get("status") != "success":
        raise RuntimeError(f"Kite login failed: {login_data}")

    # Extract request_id (NOT request_token — Zerodha changed this)
    request_id = login_data["data"].get("request_id")
    if not request_id:
        # Fallback: some versions still use request_token at this step
        request_id = login_data["data"].get("request_token")
    if not request_id:
        logger.error("Login response data keys: %s", list(login_data.get("data", {}).keys()))
        raise RuntimeError(
            f"Kite login response missing request_id/request_token. "
            f"Keys: {list(login_data.get('data', {}).keys())}"
        )
    logger.info("Got request_id from login step")

    # Step 3: TOTP 2FA
    logger.info("Step 3: Submitting TOTP...")
    totp_value = get_totp()
    twofa_resp = session.post(TWOFA_URL, data={
        "user_id": settings.KITE_USER_ID,
        "request_id": request_id,
        "twofa_value": totp_value,
        "twofa_type": "totp",
        "skip_session": "true",
    })
    twofa_data = twofa_resp.json()
    logger.info("TOTP response status: %s", twofa_data.get("status"))

    if twofa_data.get("status") != "success":
        raise RuntimeError(f"Kite TOTP failed: {twofa_data}")

    # Step 4: Extract request_token from redirect
    logger.info("Step 4: Extracting request_token from redirect...")
    request_token = None

    # Method A: Check if twofa response itself has request_token
    if "request_token" in twofa_data.get("data", {}):
        request_token = twofa_data["data"]["request_token"]
        logger.info("Got request_token from twofa response")

    # Method B: Follow login_url redirect to extract from URL
    if not request_token:
        redirect_url = ref_url
        if "skip_session" not in redirect_url:
            redirect_url += "&skip_session=true"
        redir_resp = session.get(redirect_url, allow_redirects=False)

        if redir_resp.status_code in (301, 302, 303):
            location = redir_resp.headers.get("Location", "")
            logger.info("Redirect location: %s", location.split("?")[0])
            # Extract request_token from redirect URL
            parsed = urlparse(location)
            params = parse_qs(parsed.query)
            if "request_token" in params:
                request_token = params["request_token"][0]
            else:
                # Regex fallback
                match = re.search(r"request_token=([A-Za-z0-9]+)", location)
                if match:
                    request_token = match.group(1)
        elif redir_resp.status_code == 200:
            # Some flows return 200 with token in URL params
            parsed = urlparse(str(redir_resp.url))
            params = parse_qs(parsed.query)
            if "request_token" in params:
                request_token = params["request_token"][0]

    # Method C: Try following redirects and check final URL
    if not request_token:
        redir_resp2 = session.get(ref_url, allow_redirects=True)
        parsed = urlparse(str(redir_resp2.url))
        params = parse_qs(parsed.query)
        if "request_token" in params:
            request_token = params["request_token"][0]

    if not request_token:
        raise RuntimeError(
            "Could not extract request_token after TOTP. "
            "Check if Kite API key is valid and server IP is whitelisted."
        )

    logger.info("Got request_token, generating session...")

    # Step 5: Generate session via KiteConnect SDK
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
