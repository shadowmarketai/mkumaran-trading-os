"""
MKUMARAN Trading OS — Multi-Auth Providers

Supports:
1. Email + Password (existing)
2. Google OAuth2 Sign-In
3. Email OTP (6-digit code via SMTP)
4. Mobile OTP (6-digit code via MSG91)

All methods return a JWT token on success.
"""

import hashlib
import logging
import os
import random
import secrets
import string
import time
from datetime import datetime, timedelta
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
SMTP_FROM = os.getenv("SMTP_FROM", "noreply@shadowmarket.ai")

# OTP store (in-memory, TTL 10 min) — for production use Redis
_otp_store: dict[str, dict] = {}
OTP_TTL_SECONDS = 600  # 10 minutes
OTP_LENGTH = 6


# ── OTP Generation ───────────────────────────────────────────

def _generate_otp() -> str:
    """Generate a 6-digit numeric OTP."""
    return "".join(random.choices(string.digits, k=OTP_LENGTH))


def _store_otp(key: str, otp: str, method: str) -> None:
    """Store OTP with TTL."""
    _otp_store[key] = {
        "otp": otp,
        "method": method,
        "created_at": time.time(),
        "attempts": 0,
    }


def _verify_otp(key: str, otp: str) -> tuple[bool, str]:
    """Verify OTP. Returns (success, message)."""
    entry = _otp_store.get(key)
    if not entry:
        return False, "No OTP found. Request a new one."

    # Check expiry
    if time.time() - entry["created_at"] > OTP_TTL_SECONDS:
        del _otp_store[key]
        return False, "OTP expired. Request a new one."

    # Rate limit: max 5 attempts
    entry["attempts"] += 1
    if entry["attempts"] > 5:
        del _otp_store[key]
        return False, "Too many attempts. Request a new OTP."

    if entry["otp"] != otp:
        return False, f"Invalid OTP. {5 - entry['attempts']} attempts remaining."

    # Success — clean up
    del _otp_store[key]
    return True, "OTP verified"


# ── Google OAuth2 ─────────────────────────────────────────────

async def verify_google_token(id_token: str) -> dict[str, Any]:
    """Verify Google ID token and return user info.

    Args:
        id_token: The credential from Google Sign-In

    Returns:
        Dict with email, name, picture, google_id
    """
    if not GOOGLE_CLIENT_ID:
        raise ValueError("GOOGLE_CLIENT_ID not configured")

    # Verify token with Google
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
        )

    if resp.status_code != 200:
        raise ValueError("Invalid Google token")

    data = resp.json()

    # Verify audience matches our client ID
    if data.get("aud") != GOOGLE_CLIENT_ID:
        raise ValueError("Token audience mismatch")

    # Verify email is verified
    if data.get("email_verified") != "true":
        raise ValueError("Email not verified with Google")

    return {
        "email": data.get("email", ""),
        "name": data.get("name", ""),
        "picture": data.get("picture", ""),
        "google_id": data.get("sub", ""),
    }


async def google_sign_in(db_session, id_token: str) -> dict:
    """Handle Google Sign-In — create or login user.

    Returns JWT token and user info.
    """
    from sqlalchemy import text

    google_user = await verify_google_token(id_token)
    email = google_user["email"].lower()

    # Check if user exists
    user = db_session.execute(
        text("SELECT id, email FROM users WHERE email = :email"),
        {"email": email}
    ).mappings().first()

    if not user:
        # Auto-create user from Google
        db_session.execute(
            text("""INSERT INTO users (email, password_hash, auth_provider, name, avatar_url, created_at)
                    VALUES (:email, :pw, 'google', :name, :pic, NOW())"""),
            {
                "email": email,
                "pw": f"google:{google_user['google_id']}",
                "name": google_user.get("name", ""),
                "pic": google_user.get("picture", ""),
            }
        )
        db_session.commit()
        user = db_session.execute(
            text("SELECT id, email FROM users WHERE email = :email"),
            {"email": email}
        ).mappings().first()

    # Generate JWT
    token = _create_jwt(user["id"], email)

    return {
        "access_token": token,
        "email": email,
        "name": google_user.get("name", ""),
        "picture": google_user.get("picture", ""),
        "auth_method": "google",
    }


# ── Email OTP ─────────────────────────────────────────────────

async def send_email_otp(email: str) -> dict:
    """Send a 6-digit OTP to email via SMTP."""
    if not SMTP_USER or not SMTP_PASS:
        raise ValueError("Email SMTP not configured")

    otp = _generate_otp()
    _store_otp(f"email:{email.lower()}", otp, "email")

    # Send email
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
      <p style="color:#CBD5E1;font-size:10px;margin-top:24px;">
        AI-powered market analytics. Not SEBI-registered investment advice.
      </p>
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
        raise ValueError(f"Failed to send OTP: {e}")


async def verify_email_otp(db_session, email: str, otp: str) -> dict:
    """Verify email OTP and return JWT."""
    from sqlalchemy import text

    email = email.lower()
    ok, msg = _verify_otp(f"email:{email}", otp)
    if not ok:
        raise ValueError(msg)

    # Check/create user
    user = db_session.execute(
        text("SELECT id, email FROM users WHERE email = :email"),
        {"email": email}
    ).mappings().first()

    if not user:
        db_session.execute(
            text("""INSERT INTO users (email, password_hash, auth_provider, created_at)
                    VALUES (:email, :pw, 'email_otp', NOW())"""),
            {"email": email, "pw": f"otp:{secrets.token_hex(16)}"}
        )
        db_session.commit()
        user = db_session.execute(
            text("SELECT id, email FROM users WHERE email = :email"),
            {"email": email}
        ).mappings().first()

    token = _create_jwt(user["id"], email)
    return {"access_token": token, "email": email, "auth_method": "email_otp"}


# ── Mobile OTP (MSG91) ───────────────────────────────────────

async def send_mobile_otp(phone: str) -> dict:
    """Send OTP to Indian mobile number via MSG91."""
    if not MSG91_AUTH_KEY:
        raise ValueError("MSG91_AUTH_KEY not configured")

    # Normalize phone — ensure +91 prefix
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("0"):
        phone = phone[1:]
    if not phone.startswith("+91"):
        if phone.startswith("91") and len(phone) == 12:
            phone = "+" + phone
        else:
            phone = "+91" + phone

    if len(phone) != 13:  # +91 + 10 digits
        raise ValueError("Invalid Indian mobile number")

    otp = _generate_otp()
    _store_otp(f"mobile:{phone}", otp, "mobile")

    # Send via MSG91 API
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

    if resp.status_code == 200:
        logger.info("Mobile OTP sent to %s***", phone[:6])
        return {"sent": True, "phone": phone[:6] + "****", "expires_in": OTP_TTL_SECONDS}
    else:
        logger.error("MSG91 OTP failed: %s", resp.text[:200])
        raise ValueError("Failed to send SMS OTP")


async def verify_mobile_otp(db_session, phone: str, otp: str) -> dict:
    """Verify mobile OTP and return JWT."""
    from sqlalchemy import text

    # Normalize phone
    phone = phone.strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+91"):
        phone = "+91" + phone.lstrip("0")

    ok, msg = _verify_otp(f"mobile:{phone}", otp)
    if not ok:
        raise ValueError(msg)

    # Check/create user by phone
    user = db_session.execute(
        text("SELECT id, email FROM users WHERE phone = :phone"),
        {"phone": phone}
    ).mappings().first()

    if not user:
        temp_email = f"{phone.replace('+', '')}@phone.shadowmarket.ai"
        db_session.execute(
            text("""INSERT INTO users (email, phone, password_hash, auth_provider, created_at)
                    VALUES (:email, :phone, :pw, 'mobile_otp', NOW())"""),
            {"email": temp_email, "phone": phone, "pw": f"otp:{secrets.token_hex(16)}"}
        )
        db_session.commit()
        user = db_session.execute(
            text("SELECT id, email FROM users WHERE phone = :phone"),
            {"phone": phone}
        ).mappings().first()

    token = _create_jwt(user["id"], user["email"])
    return {"access_token": token, "email": user["email"], "phone": phone[:6] + "****", "auth_method": "mobile_otp"}


# ── JWT Helper ────────────────────────────────────────────────

def _create_jwt(user_id: int, email: str) -> str:
    """Create a JWT token (same format as existing auth system)."""
    import jwt

    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


# ── BYOK (Bring Your Own Key) ────────────────────────────────

async def save_user_api_keys(db_session, user_id: int, keys: dict) -> dict:
    """Save user's own LLM API keys (encrypted at rest).

    Keys dict: {"grok_key": "...", "kimi_key": "...", "preferred_provider": "grok"}
    """
    from sqlalchemy import text
    import json

    # Simple XOR encryption with JWT secret (not production-grade, but protects at rest)
    raw = json.dumps(keys)
    encrypted = _simple_encrypt(raw, settings.JWT_SECRET_KEY)

    # Upsert into user_settings
    existing = db_session.execute(
        text("SELECT id FROM user_settings WHERE user_id = :uid AND setting_key = 'llm_api_keys'"),
        {"uid": user_id}
    ).first()

    if existing:
        db_session.execute(
            text("UPDATE user_settings SET setting_value = :val, updated_at = NOW() WHERE user_id = :uid AND setting_key = 'llm_api_keys'"),
            {"val": encrypted, "uid": user_id}
        )
    else:
        db_session.execute(
            text("INSERT INTO user_settings (user_id, setting_key, setting_value, created_at, updated_at) VALUES (:uid, 'llm_api_keys', :val, NOW(), NOW())"),
            {"uid": user_id, "val": encrypted}
        )

    db_session.commit()
    logger.info("Saved API keys for user %d", user_id)

    return {"saved": True, "providers": list(k for k, v in keys.items() if v and k != "preferred_provider")}


async def get_user_api_keys(db_session, user_id: int) -> dict:
    """Get user's LLM API keys (decrypted). Returns empty dict if none."""
    from sqlalchemy import text
    import json

    row = db_session.execute(
        text("SELECT setting_value FROM user_settings WHERE user_id = :uid AND setting_key = 'llm_api_keys'"),
        {"uid": user_id}
    ).first()

    if not row:
        return {}

    try:
        decrypted = _simple_decrypt(row[0], settings.JWT_SECRET_KEY)
        return json.loads(decrypted)
    except Exception:
        return {}


def _simple_encrypt(text: str, key: str) -> str:
    """Simple XOR encryption for API keys at rest."""
    import base64
    key_bytes = hashlib.sha256(key.encode()).digest()
    encrypted = bytes(a ^ b for a, b in zip(text.encode(), (key_bytes * (len(text) // len(key_bytes) + 1))[:len(text)]))
    return base64.b64encode(encrypted).decode()


def _simple_decrypt(encrypted: str, key: str) -> str:
    """Decrypt XOR-encrypted text."""
    import base64
    key_bytes = hashlib.sha256(key.encode()).digest()
    data = base64.b64decode(encrypted)
    decrypted = bytes(a ^ b for a, b in zip(data, (key_bytes * (len(data) // len(key_bytes) + 1))[:len(data)]))
    return decrypted.decode()
