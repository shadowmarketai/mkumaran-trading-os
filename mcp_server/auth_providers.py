"""
MKUMARAN Trading OS — Multi-Auth Providers

Supports:
1. Email + Password (existing admin auth)
2. Google OAuth2 Sign-In
3. Email OTP (6-digit code via SMTP)
4. Mobile OTP (6-digit code via MSG91)

All methods issue JWT via the existing auth.create_access_token().
No users table needed — works with the existing single/multi admin system.
"""

import hashlib
import logging
import os
import random
import string
import time
from typing import Any

import httpx

from mcp_server.config import settings

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

MSG91_AUTH_KEY = os.getenv("MSG91_AUTH_KEY", "")
MSG91_TEMPLATE_ID = os.getenv("MSG91_TEMPLATE_ID", "")
MSG91_SENDER_ID = os.getenv("MSG91_SENDER_ID", "SHADOW")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "") or SMTP_USER

# OTP store (in-memory with TTL)
_otp_store: dict[str, dict] = {}
OTP_TTL_SECONDS = 600  # 10 minutes
OTP_LENGTH = 6


# ── JWT Helper (uses existing auth system) ────────────────────

def _create_token(email: str, role: str = "user", name: str = "") -> str:
    """Create JWT using the existing auth module."""
    from mcp_server.auth import create_access_token
    return create_access_token({"sub": email, "role": role, "name": name})


# ── OTP Generation ───────────────────────────────────────────

def _generate_otp() -> str:
    return "".join(random.choices(string.digits, k=OTP_LENGTH))


def _store_otp(key: str, otp: str) -> None:
    _otp_store[key] = {"otp": otp, "created_at": time.time(), "attempts": 0}
    logger.info("OTP stored for %s (total in store: %d)", key[:15], len(_otp_store))


def _verify_otp(key: str, otp: str) -> tuple[bool, str]:
    # Clean expired entries first
    now = time.time()
    expired = [k for k, v in _otp_store.items() if now - v["created_at"] > OTP_TTL_SECONDS]
    for k in expired:
        del _otp_store[k]

    entry = _otp_store.get(key)
    if not entry:
        logger.warning("OTP not found for key: %s (store has %d entries: %s)",
                       key, len(_otp_store), list(_otp_store.keys()))
        return False, "No OTP found. Please request a new one."

    if now - entry["created_at"] > OTP_TTL_SECONDS:
        del _otp_store[key]
        return False, "OTP expired. Request a new one."

    entry["attempts"] += 1
    if entry["attempts"] > 5:
        del _otp_store[key]
        return False, "Too many attempts. Request a new OTP."

    if entry["otp"] != otp.strip():
        remaining = 5 - entry["attempts"]
        return False, f"Invalid OTP. {remaining} attempts remaining."

    del _otp_store[key]
    return True, "OTP verified"


# ── Google OAuth2 ─────────────────────────────────────────────

async def verify_google_token(id_token: str) -> dict[str, Any]:
    """Verify Google ID token and return user info."""
    if not GOOGLE_CLIENT_ID:
        raise ValueError("GOOGLE_CLIENT_ID not configured")

    # Verify with Google's tokeninfo endpoint
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
        )

    if resp.status_code != 200:
        logger.error("Google token verification failed: %s %s", resp.status_code, resp.text[:200])
        raise ValueError(f"Invalid Google token (HTTP {resp.status_code})")

    data = resp.json()

    # Check for error in response
    if "error" in data:
        raise ValueError(f"Google token error: {data['error']}")

    # Verify audience matches our client ID
    aud = data.get("aud", "")
    if aud != GOOGLE_CLIENT_ID:
        logger.error("Google audience mismatch: got %s, expected %s", aud, GOOGLE_CLIENT_ID)
        raise ValueError("Token audience mismatch")

    email_verified = data.get("email_verified")
    if email_verified not in ("true", True):
        raise ValueError("Email not verified with Google")

    return {
        "email": data.get("email", ""),
        "name": data.get("name", ""),
        "picture": data.get("picture", ""),
        "google_id": data.get("sub", ""),
    }


async def google_sign_in(id_token: str) -> dict:
    """Handle Google Sign-In — verify token and issue JWT."""
    google_user = await verify_google_token(id_token)
    email = google_user["email"].lower()
    name = google_user.get("name", email.split("@")[0])

    token = _create_token(email, role="user", name=name)

    logger.info("Google sign-in: %s (%s)", email, name)
    return {
        "access_token": token,
        "token_type": "bearer",
        "email": email,
        "name": name,
        "picture": google_user.get("picture", ""),
        "auth_method": "google",
    }


# ── Email OTP ─────────────────────────────────────────────────

async def send_email_otp(email: str) -> dict:
    """Send a 6-digit OTP to email via SMTP."""
    if not SMTP_USER or not SMTP_PASS:
        raise ValueError("Email SMTP not configured")

    email = email.lower().strip()
    otp = _generate_otp()
    _store_otp(f"email:{email}", otp)

    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    msg = MIMEMultipart()
    msg["From"] = SMTP_FROM
    msg["To"] = email
    msg["Subject"] = f"Shadow Market AI — Login Code: {otp}"

    body = f"""
    <div style="font-family:Inter,sans-serif;max-width:400px;margin:0 auto;padding:32px;">
      <h2 style="color:#7C3AED;margin-bottom:8px;">Shadow Market AI</h2>
      <p style="color:#64748B;font-size:14px;">Your login verification code:</p>
      <div style="background:#F5F3FF;border:1px solid #E9D5FF;border-radius:12px;padding:20px;text-align:center;margin:16px 0;">
        <span style="font-size:32px;font-weight:700;letter-spacing:8px;color:#7C3AED;font-family:monospace;">{otp}</span>
      </div>
      <p style="color:#94A3B8;font-size:12px;">Valid for 10 minutes. Do not share this code.</p>
    </div>
    """
    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        logger.info("Email OTP sent to %s", email[:5] + "***")
        return {"sent": True, "email": email, "expires_in": OTP_TTL_SECONDS}
    except Exception as e:
        logger.error("Email OTP send failed: %s", e)
        raise ValueError(f"Failed to send email: {e}")


async def verify_email_otp(email: str, otp: str) -> dict:
    """Verify email OTP and return JWT. No database needed."""
    email = email.lower().strip()
    ok, msg = _verify_otp(f"email:{email}", otp)
    if not ok:
        raise ValueError(msg)

    token = _create_token(email, role="user")
    logger.info("Email OTP login: %s", email)
    return {
        "access_token": token,
        "token_type": "bearer",
        "email": email,
        "auth_method": "email_otp",
    }


# ── Mobile OTP (MSG91) ───────────────────────────────────────

async def send_mobile_otp(phone: str) -> dict:
    """Send OTP to Indian mobile number via MSG91."""
    if not MSG91_AUTH_KEY:
        raise ValueError("MSG91_AUTH_KEY not configured")

    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("0"):
        phone = phone[1:]
    if not phone.startswith("+91"):
        if phone.startswith("91") and len(phone) == 12:
            phone = "+" + phone
        else:
            phone = "+91" + phone

    if len(phone) != 13:
        raise ValueError("Invalid Indian mobile number (need 10 digits)")

    otp = _generate_otp()
    _store_otp(f"mobile:{phone}", otp)

    # If no template ID, use MSG91 OTP API directly
    if MSG91_TEMPLATE_ID:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://control.msg91.com/api/v5/flow/",
                headers={"authkey": MSG91_AUTH_KEY, "Content-Type": "application/json"},
                json={
                    "template_id": MSG91_TEMPLATE_ID,
                    "sender": MSG91_SENDER_ID,
                    "short_url": "0",
                    "mobiles": phone,
                    "OTP": otp,
                }
            )
    else:
        # Use MSG91 OTP send API (simpler, auto-generates template)
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://control.msg91.com/api/v5/otp",
                params={
                    "authkey": MSG91_AUTH_KEY,
                    "mobile": phone,
                    "otp": otp,
                    "sender": MSG91_SENDER_ID,
                }
            )

    if resp.status_code == 200:
        logger.info("Mobile OTP sent to %s***", phone[:6])
        return {"sent": True, "phone": phone[:6] + "****", "expires_in": OTP_TTL_SECONDS}
    else:
        logger.error("MSG91 OTP failed (%d): %s", resp.status_code, resp.text[:200])
        raise ValueError("Failed to send SMS OTP")


async def verify_mobile_otp(phone: str, otp: str) -> dict:
    """Verify mobile OTP and return JWT. No database needed."""
    phone = phone.strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+91"):
        phone = "+91" + phone.lstrip("0")

    ok, msg = _verify_otp(f"mobile:{phone}", otp)
    if not ok:
        raise ValueError(msg)

    email = f"{phone.replace('+', '')}@phone.shadowmarket.ai"
    token = _create_token(email, role="user")
    logger.info("Mobile OTP login: %s", phone[:6] + "****")
    return {
        "access_token": token,
        "token_type": "bearer",
        "email": email,
        "phone": phone[:6] + "****",
        "auth_method": "mobile_otp",
    }


# ── BYOK (Bring Your Own Key) ────────────────────────────────

async def save_user_api_keys(db_session, user_email: str, keys: dict) -> dict:
    """Save user's LLM API keys to user_settings table."""
    from sqlalchemy import text
    import json

    raw = json.dumps(keys)
    encrypted = _simple_encrypt(raw, settings.JWT_SECRET_KEY)

    try:
        db_session.execute(
            text("""INSERT INTO user_settings (user_id, setting_key, setting_value, created_at, updated_at)
                    VALUES (0, :key, :val, NOW(), NOW())
                    ON CONFLICT ON CONSTRAINT uq_user_setting
                    DO UPDATE SET setting_value = :val, updated_at = NOW()"""),
            {"key": f"llm_keys:{user_email}", "val": encrypted}
        )
        db_session.commit()
    except Exception:
        # Table might not exist yet — store in memory as fallback
        _otp_store[f"byok:{user_email}"] = {"keys": keys, "created_at": time.time()}

    return {"saved": True, "providers": [k for k, v in keys.items() if v and k != "preferred_provider"]}


async def get_user_api_keys(db_session, user_email: str) -> dict:
    """Get user's LLM API keys."""
    from sqlalchemy import text
    import json

    try:
        row = db_session.execute(
            text("SELECT setting_value FROM user_settings WHERE setting_key = :key"),
            {"key": f"llm_keys:{user_email}"}
        ).first()

        if row:
            decrypted = _simple_decrypt(row[0], settings.JWT_SECRET_KEY)
            return json.loads(decrypted)
    except Exception:
        # Fallback to in-memory
        entry = _otp_store.get(f"byok:{user_email}")
        if entry:
            return entry["keys"]

    return {}


def _simple_encrypt(text: str, key: str) -> str:
    import base64
    key_bytes = hashlib.sha256(key.encode()).digest()
    encrypted = bytes(a ^ b for a, b in zip(text.encode(), (key_bytes * (len(text) // len(key_bytes) + 1))[:len(text)]))
    return base64.b64encode(encrypted).decode()


def _simple_decrypt(encrypted: str, key: str) -> str:
    import base64
    key_bytes = hashlib.sha256(key.encode()).digest()
    data = base64.b64decode(encrypted)
    decrypted = bytes(a ^ b for a, b in zip(data, (key_bytes * (len(data) // len(key_bytes) + 1))[:len(data)]))
    return decrypted.decode()
