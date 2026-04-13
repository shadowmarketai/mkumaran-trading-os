"""
MKUMARAN Trading OS — User Registration & Login

Flow:
  REGISTER: Email/Phone → OTP verify → Set password → Account created
  LOGIN:    Email/Phone + Password → JWT (no OTP needed)
  GOOGLE:   One-click → Auto-register/login → JWT
  FORGOT:   Email/Phone → OTP → Reset password

Uses app_users table. OTP only for registration + forgot password.
"""

import hashlib
import logging
import os
import random
import string
import time

import bcrypt
import httpx

from mcp_server.config import settings

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")

MSG91_AUTH_KEY = os.getenv("MSG91_AUTH_KEY", "")
MSG91_TEMPLATE_ID = os.getenv("MSG91_TEMPLATE_ID", "")
MSG91_SENDER_ID = os.getenv("MSG91_SENDER_ID", "SHADOW")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "") or SMTP_USER

# In-memory OTP store
_otp_store: dict[str, dict] = {}
OTP_TTL = 600


# ── Password Hashing ─────────────────────────────────────────

def _hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_pw(password: str, hashed: str) -> bool:
    if hashed.startswith("$2b$") or hashed.startswith("$2a$"):
        return bcrypt.checkpw(password.encode(), hashed.encode())
    return password == hashed  # plain fallback


# ── JWT ───────────────────────────────────────────────────────

def _create_token(email: str, role: str = "user", name: str = "") -> str:
    from mcp_server.auth import create_access_token
    return create_access_token({"sub": email, "role": role, "name": name})


# ── OTP ───────────────────────────────────────────────────────

def _gen_otp() -> str:
    return "".join(random.choices(string.digits, k=6))


def _store_otp(key: str, otp: str):
    _otp_store[key] = {"otp": otp, "ts": time.time(), "attempts": 0}


def _check_otp(key: str, otp: str) -> tuple[bool, str]:
    now = time.time()
    # Clean expired
    for k in [k for k, v in _otp_store.items() if now - v["ts"] > OTP_TTL]:
        del _otp_store[k]

    entry = _otp_store.get(key)
    if not entry:
        return False, "No OTP found. Request a new one."
    if now - entry["ts"] > OTP_TTL:
        del _otp_store[key]
        return False, "OTP expired."
    entry["attempts"] += 1
    if entry["attempts"] > 5:
        del _otp_store[key]
        return False, "Too many attempts."
    if entry["otp"] != otp.strip():
        return False, f"Wrong OTP. {5 - entry['attempts']} tries left."
    del _otp_store[key]
    return True, "OK"


def _normalize_phone(phone: str) -> str:
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("0"):
        phone = phone[1:]
    if not phone.startswith("+91"):
        if phone.startswith("91") and len(phone) == 12:
            phone = "+" + phone
        else:
            phone = "+91" + phone
    return phone


# ── SEND OTP (for registration / forgot password) ────────────

async def send_email_otp(email: str) -> dict:
    if not SMTP_USER:
        raise ValueError("Email not configured")
    email = email.lower().strip()
    otp = _gen_otp()
    _store_otp(f"email:{email}", otp)

    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    msg = MIMEMultipart()
    msg["From"] = SMTP_FROM
    msg["To"] = email
    msg["Subject"] = f"Shadow Market AI — Code: {otp}"
    body = f"""<div style="font-family:Inter,sans-serif;max-width:400px;margin:0 auto;padding:32px;">
      <h2 style="color:#7C3AED;">Shadow Market AI</h2>
      <p style="color:#64748B;font-size:14px;">Your verification code:</p>
      <div style="background:#F5F3FF;border:1px solid #E9D5FF;border-radius:12px;padding:20px;text-align:center;margin:16px 0;">
        <span style="font-size:32px;font-weight:700;letter-spacing:8px;color:#7C3AED;font-family:monospace;">{otp}</span>
      </div>
      <p style="color:#94A3B8;font-size:12px;">Valid for 10 minutes.</p></div>"""
    msg.attach(MIMEText(body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)

    logger.info("Email OTP sent to %s***", email[:5])
    return {"sent": True, "to": email, "method": "email"}


async def send_mobile_otp(phone: str) -> dict:
    if not MSG91_AUTH_KEY:
        raise ValueError("SMS not configured")
    phone = _normalize_phone(phone)
    if len(phone) != 13:
        raise ValueError("Invalid Indian mobile number")
    otp = _gen_otp()
    _store_otp(f"mobile:{phone}", otp)

    async with httpx.AsyncClient(timeout=10) as client:
        if MSG91_TEMPLATE_ID:
            await client.post("https://control.msg91.com/api/v5/flow/",
                              headers={"authkey": MSG91_AUTH_KEY, "Content-Type": "application/json"},
                              json={"template_id": MSG91_TEMPLATE_ID, "sender": MSG91_SENDER_ID,
                                    "mobiles": phone, "OTP": otp})
        else:
            await client.get("https://control.msg91.com/api/v5/otp",
                             params={"authkey": MSG91_AUTH_KEY, "mobile": phone,
                                     "otp": otp, "sender": MSG91_SENDER_ID})

    logger.info("Mobile OTP sent to %s***", phone[:6])
    return {"sent": True, "to": phone[:6] + "****", "method": "mobile"}


# ── VERIFY OTP (returns temporary token for registration) ─────

async def verify_registration_otp(identifier: str, otp: str, method: str) -> dict:
    """Verify OTP during registration. Returns a temp verification token."""
    if method == "email":
        key = f"email:{identifier.lower().strip()}"
    else:
        key = f"mobile:{_normalize_phone(identifier)}"

    ok, msg = _check_otp(key, otp)
    if not ok:
        raise ValueError(msg)

    # Store verification status (valid for 15 min to complete registration)
    verify_token = hashlib.sha256(f"{identifier}:{time.time()}".encode()).hexdigest()[:32]
    _otp_store[f"verified:{verify_token}"] = {
        "identifier": identifier,
        "method": method,
        "ts": time.time(),
        "otp": "",  # dummy
        "attempts": 0,
    }

    return {"verified": True, "verify_token": verify_token, "method": method}


# ── Ensure table exists ───────────────────────────────────────

_table_checked = False


def _ensure_app_users_table(db_session):
    """Create app_users table if it doesn't exist."""
    global _table_checked
    if _table_checked:
        return
    from sqlalchemy import text
    try:
        db_session.execute(text("SELECT 1 FROM app_users LIMIT 1"))
        _table_checked = True
    except Exception:
        db_session.rollback()
        db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS app_users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE,
                phone VARCHAR(15) UNIQUE,
                password_hash VARCHAR(128) NOT NULL,
                name VARCHAR(100),
                avatar_url VARCHAR(500),
                auth_provider VARCHAR(20) DEFAULT 'email',
                google_id VARCHAR(50),
                city VARCHAR(100),
                trading_experience VARCHAR(20),
                trading_segments VARCHAR(200),
                telegram_chat_id VARCHAR(20),
                alert_enabled BOOLEAN DEFAULT true,
                subscription_tier VARCHAR(20) DEFAULT 'free',
                daily_signal_count INTEGER DEFAULT 0,
                last_signal_date DATE,
                is_verified BOOLEAN DEFAULT false,
                is_active BOOLEAN DEFAULT true,
                role VARCHAR(20) DEFAULT 'user',
                last_login TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """))
        db_session.execute(text("CREATE INDEX IF NOT EXISTS idx_app_users_email ON app_users(email)"))
        db_session.execute(text("CREATE INDEX IF NOT EXISTS idx_app_users_phone ON app_users(phone)"))
        db_session.execute(text("CREATE INDEX IF NOT EXISTS idx_app_users_telegram ON app_users(telegram_chat_id)"))
        db_session.commit()
        _table_checked = True
        logger.info("Created app_users table")


# ── REGISTER (after OTP verified) ────────────────────────────

async def register_user(
    db_session, verify_token: str, password: str, name: str = "",
    city: str = "", trading_experience: str = "", segments: str = "",
    extra_phone: str = "", extra_email: str = "",
) -> dict:
    """Complete registration after OTP verification with full profile."""
    from sqlalchemy import text
    _ensure_app_users_table(db_session)

    entry = _otp_store.get(f"verified:{verify_token}")
    if not entry:
        raise ValueError("Verification expired. Start registration again.")
    if time.time() - entry["ts"] > 900:
        del _otp_store[f"verified:{verify_token}"]
        raise ValueError("Verification expired.")

    identifier = entry["identifier"]
    method = entry["method"]
    del _otp_store[f"verified:{verify_token}"]

    if method == "email":
        email = identifier.lower().strip()
        phone = extra_phone.strip() if extra_phone else None
        if phone:
            phone = _normalize_phone(phone)
        existing = db_session.execute(
            text("SELECT id FROM app_users WHERE email = :e"), {"e": email}
        ).first()
        if existing:
            raise ValueError("Email already registered. Please login.")
    else:
        phone = _normalize_phone(identifier)
        email = extra_email.lower().strip() if extra_email else f"{phone.replace('+', '')}@phone.shadowmarket.ai"
        existing = db_session.execute(
            text("SELECT id FROM app_users WHERE phone = :p"), {"p": phone}
        ).first()
        if existing:
            raise ValueError("Phone already registered. Please login.")

    pw_hash = _hash_pw(password)
    db_session.execute(
        text("""INSERT INTO app_users
                (email, phone, password_hash, name, city, trading_experience,
                 trading_segments, auth_provider, is_verified, role, created_at)
                VALUES (:email, :phone, :pw, :name, :city, :exp, :segs, :provider, true, 'user', NOW())"""),
        {"email": email, "phone": phone, "pw": pw_hash,
         "name": name or email.split("@")[0], "city": city or None,
         "exp": trading_experience or None, "segs": segments or None,
         "provider": method}
    )
    db_session.commit()

    token = _create_token(email, role="user", name=name)
    logger.info("User registered: %s via %s (city=%s, exp=%s, segs=%s)",
                email, method, city, trading_experience, segments)

    return {
        "access_token": token,
        "token_type": "bearer",
        "email": email,
        "name": name or email.split("@")[0],
        "auth_method": method,
        "registered": True,
    }


# ── LOGIN (email/phone + password) ───────────────────────────

async def login_user(db_session, identifier: str, password: str) -> dict:
    """Login with email/phone + password."""
    from sqlalchemy import text
    _ensure_app_users_table(db_session)

    identifier = identifier.strip()

    # Try email first
    if "@" in identifier:
        user = db_session.execute(
            text("SELECT id, email, phone, password_hash, name, role, is_active FROM app_users WHERE email = :e"),
            {"e": identifier.lower()}
        ).mappings().first()
    else:
        # Try phone
        phone = _normalize_phone(identifier)
        user = db_session.execute(
            text("SELECT id, email, phone, password_hash, name, role, is_active FROM app_users WHERE phone = :p"),
            {"p": phone}
        ).mappings().first()

    if not user:
        raise ValueError("Account not found. Please register first.")

    if not user["is_active"]:
        raise ValueError("Account deactivated.")

    if not _verify_pw(password, user["password_hash"]):
        raise ValueError("Wrong password.")

    # Update last login
    db_session.execute(
        text("UPDATE app_users SET last_login = NOW() WHERE id = :id"),
        {"id": user["id"]}
    )
    db_session.commit()

    token = _create_token(user["email"], role=user["role"], name=user["name"] or "")
    logger.info("User login: %s", user["email"])

    return {
        "access_token": token,
        "token_type": "bearer",
        "email": user["email"],
        "name": user["name"] or "",
        "auth_method": "password",
    }


# ── GOOGLE SIGN-IN (auto register/login) ─────────────────────

async def google_sign_in(db_session, id_token: str) -> dict:
    """Google Sign-In — auto-creates account on first use."""
    from sqlalchemy import text
    _ensure_app_users_table(db_session)

    if not GOOGLE_CLIENT_ID:
        raise ValueError("Google Sign-In not configured")

    # Verify token
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}")

    if resp.status_code != 200:
        raise ValueError("Invalid Google token")

    data = resp.json()
    if data.get("aud") != GOOGLE_CLIENT_ID:
        raise ValueError("Token audience mismatch")
    if data.get("email_verified") not in ("true", True):
        raise ValueError("Google email not verified")

    email = data["email"].lower()
    name = data.get("name", email.split("@")[0])
    picture = data.get("picture", "")
    google_id = data.get("sub", "")

    # Check if user exists
    user = db_session.execute(
        text("SELECT id, email, name, role FROM app_users WHERE email = :e OR google_id = :g"),
        {"e": email, "g": google_id}
    ).mappings().first()

    if not user:
        # Auto-register
        pw_hash = _hash_pw(f"google:{google_id}")
        db_session.execute(
            text("""INSERT INTO app_users (email, password_hash, name, avatar_url, auth_provider, google_id, is_verified, role, created_at)
                    VALUES (:email, :pw, :name, :pic, 'google', :gid, true, 'user', NOW())"""),
            {"email": email, "pw": pw_hash, "name": name, "pic": picture, "gid": google_id}
        )
        db_session.commit()
        user = db_session.execute(
            text("SELECT id, email, name, role FROM app_users WHERE email = :e"), {"e": email}
        ).mappings().first()
        logger.info("Google auto-register: %s", email)
    else:
        # Update last login
        db_session.execute(
            text("UPDATE app_users SET last_login = NOW(), avatar_url = :pic WHERE id = :id"),
            {"pic": picture, "id": user["id"]}
        )
        db_session.commit()
        logger.info("Google login: %s", email)

    token = _create_token(user["email"], role=user["role"], name=user["name"] or "")

    return {
        "access_token": token,
        "token_type": "bearer",
        "email": email,
        "name": user["name"] or name,
        "picture": picture,
        "auth_method": "google",
    }


# ── FORGOT PASSWORD ──────────────────────────────────────────

async def reset_password(db_session, verify_token: str, new_password: str) -> dict:
    """Reset password after OTP verification."""
    from sqlalchemy import text

    entry = _otp_store.get(f"verified:{verify_token}")
    if not entry:
        raise ValueError("Verification expired.")
    if time.time() - entry["ts"] > 900:
        del _otp_store[f"verified:{verify_token}"]
        raise ValueError("Verification expired.")

    identifier = entry["identifier"]
    method = entry["method"]
    del _otp_store[f"verified:{verify_token}"]

    pw_hash = _hash_pw(new_password)

    if method == "email":
        db_session.execute(
            text("UPDATE app_users SET password_hash = :pw WHERE email = :e"),
            {"pw": pw_hash, "e": identifier.lower()}
        )
    else:
        phone = _normalize_phone(identifier)
        db_session.execute(
            text("UPDATE app_users SET password_hash = :pw WHERE phone = :p"),
            {"pw": pw_hash, "p": phone}
        )
    db_session.commit()

    return {"reset": True, "message": "Password updated. Please login."}


# ── BYOK ──────────────────────────────────────────────────────

async def save_user_api_keys(db_session, user_email: str, keys: dict) -> dict:
    from sqlalchemy import text
    import json
    raw = json.dumps(keys)
    encrypted = _xor_encrypt(raw, settings.JWT_SECRET_KEY)
    try:
        existing = db_session.execute(
            text("SELECT id FROM user_settings WHERE setting_key = :k"),
            {"k": f"llm_keys:{user_email}"}
        ).first()
        if existing:
            db_session.execute(
                text("UPDATE user_settings SET setting_value = :v, updated_at = NOW() WHERE setting_key = :k"),
                {"v": encrypted, "k": f"llm_keys:{user_email}"}
            )
        else:
            db_session.execute(
                text("INSERT INTO user_settings (user_id, setting_key, setting_value, created_at, updated_at) VALUES (0, :k, :v, NOW(), NOW())"),
                {"k": f"llm_keys:{user_email}", "v": encrypted}
            )
        db_session.commit()
    except Exception:
        _otp_store[f"byok:{user_email}"] = {"keys": keys, "ts": time.time(), "otp": "", "attempts": 0}
    return {"saved": True}


async def get_user_api_keys(db_session, user_email: str) -> dict:
    from sqlalchemy import text
    import json
    try:
        row = db_session.execute(
            text("SELECT setting_value FROM user_settings WHERE setting_key = :k"),
            {"k": f"llm_keys:{user_email}"}
        ).first()
        if row:
            return json.loads(_xor_decrypt(row[0], settings.JWT_SECRET_KEY))
    except Exception:
        entry = _otp_store.get(f"byok:{user_email}")
        if entry:
            return entry["keys"]
    return {}


def _xor_encrypt(text: str, key: str) -> str:
    import base64
    kb = hashlib.sha256(key.encode()).digest()
    enc = bytes(a ^ b for a, b in zip(text.encode(), (kb * (len(text) // len(kb) + 1))[:len(text)]))
    return base64.b64encode(enc).decode()


def _xor_decrypt(encrypted: str, key: str) -> str:
    import base64
    kb = hashlib.sha256(key.encode()).digest()
    data = base64.b64decode(encrypted)
    return bytes(a ^ b for a, b in zip(data, (kb * (len(data) // len(kb) + 1))[:len(data)])).decode()
