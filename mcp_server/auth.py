"""
MKUMARAN Trading OS — Personal Admin Authentication

Single-user JWT auth for dashboard and API endpoints.
Opt-in via AUTH_ENABLED=true env var. When disabled, all endpoints remain public.
"""

import logging
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from mcp_server.config import settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 hours


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a bcrypt hash."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")


def create_access_token(data: dict, expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Decode and validate a JWT access token. Returns payload or None."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("JWT token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug("JWT token invalid: %s", e)
        return None


def authenticate_admin(email: str, password: str) -> dict | None:
    """
    Authenticate admin user against env-var credentials.

    Returns user dict on success, None on failure.
    """
    if not settings.ADMIN_PASSWORD_HASH:
        logger.warning("ADMIN_PASSWORD_HASH not set — login disabled")
        return None

    if email != settings.ADMIN_EMAIL:
        return None

    if not verify_password(password, settings.ADMIN_PASSWORD_HASH):
        return None

    return {
        "email": settings.ADMIN_EMAIL,
        "role": "admin",
        "name": "Admin",
    }
