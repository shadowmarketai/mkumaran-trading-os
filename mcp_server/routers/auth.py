"""Authentication + user/settings — login, OTP, Google OAuth, tier, BYOK keys.

Extracted from mcp_server.mcp_server in Phase 3e of the router split.
Combines auth / user_settings / BYOK clusters into one router module
(single surface area, all live at session boundaries of the app).

15 routes moved verbatim.

Clusters:
  - Admin JWT login (/auth/login, /auth/me + /api/auth/* aliases)
  - Multi-auth registration (Google / email-OTP / mobile-OTP + password)
  - Login / reset-password flows
  - BYOK LLM API key storage (/api/settings/api-keys GET+POST)
  - Auth config discovery (/api/auth/config)
  - Tier enforcement (/api/user/tier, /api/user/check-feature/{feature})

All DB work routes through mcp_server.db.SessionLocal.
Rate-limited flows preserve @limiter.limit(...) via routers.deps.limiter.
"""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from mcp_server.config import settings
from mcp_server.db import SessionLocal
from mcp_server.routers.deps import limiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])


# ── Request models ─────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: str
    password: str


# ── Admin JWT login ────────────────────────────────────────────────


@router.post("/auth/login")
@router.post("/api/auth/login", include_in_schema=False)
@limiter.limit("5/minute")
async def auth_login(request: Request, req: LoginRequest):
    """Authenticate admin user and return JWT token."""
    from mcp_server.auth import authenticate_admin, create_access_token

    user = authenticate_admin(req.email, req.password)
    if user is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid email or password"},
        )

    token = create_access_token({"sub": user["email"], "role": user["role"]})
    return {
        "access_token": token,
        "token_type": "bearer",
        "email": user["email"],
    }


@router.get("/auth/me")
@router.get("/api/auth/me", include_in_schema=False)
async def auth_me(request: Request):
    """Get current authenticated user info."""
    if not settings.AUTH_ENABLED:
        return {"email": "dev@local", "role": "admin", "auth_enabled": False}

    user = getattr(request.state, "user", None)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

    return {"email": user.get("sub", ""), "role": user.get("role", ""), "auth_enabled": True}


# ── Multi-auth (Google / OTP / Register / Password) ───────────────


@router.post("/api/auth/google")
@limiter.limit("10/minute")
async def auth_google(request: Request):
    """Google OAuth2 — auto-register on first use, login after."""
    body = await request.json()
    id_token = body.get("credential", "")
    if not id_token:
        return JSONResponse(status_code=400, content={"detail": "Missing Google credential"})
    try:
        from mcp_server.auth_providers import google_sign_in
        db = SessionLocal()
        try:
            return await google_sign_in(db, id_token)
        finally:
            db.close()
    except ValueError as e:
        return JSONResponse(status_code=401, content={"detail": str(e)})


@router.post("/api/auth/send-otp")
@limiter.limit("3/minute")
async def auth_send_otp(request: Request):
    """Send OTP for registration or forgot password."""
    body = await request.json()
    method = body.get("method", "email")  # email or mobile
    identifier = body.get("email", "") or body.get("phone", "")
    if not identifier:
        return JSONResponse(status_code=400, content={"detail": "Email or phone required"})
    try:
        if method == "mobile":
            from mcp_server.auth_providers import send_mobile_otp
            return await send_mobile_otp(identifier)
        else:
            from mcp_server.auth_providers import send_email_otp
            return await send_email_otp(identifier)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})


@router.post("/api/auth/verify-otp")
@limiter.limit("5/minute")
async def auth_verify_otp(request: Request):
    """Verify OTP — returns verify_token for registration."""
    body = await request.json()
    identifier = body.get("email", "") or body.get("phone", "")
    otp = body.get("otp", "").strip()
    method = body.get("method", "email")
    if not identifier or not otp:
        return JSONResponse(status_code=400, content={"detail": "Identifier and OTP required"})
    try:
        from mcp_server.auth_providers import verify_registration_otp
        return await verify_registration_otp(identifier, otp, method)
    except ValueError as e:
        return JSONResponse(status_code=401, content={"detail": str(e)})


@router.post("/api/auth/register")
@limiter.limit("5/minute")
async def auth_register(request: Request):
    """Complete registration — requires verify_token from OTP step."""
    body = await request.json()
    verify_token = body.get("verify_token", "")
    password = body.get("password", "")
    name = body.get("name", "").strip()
    city = body.get("city", "").strip()
    trading_exp = body.get("trading_experience", "").strip()
    segs = body.get("segments", "").strip()
    if not verify_token or not password:
        return JSONResponse(status_code=400, content={"detail": "verify_token and password required"})
    if len(password) < 6:
        return JSONResponse(status_code=400, content={"detail": "Password must be at least 6 characters"})
    if not name:
        return JSONResponse(status_code=400, content={"detail": "Full name is required"})
    if not city:
        return JSONResponse(status_code=400, content={"detail": "City is required"})
    if not trading_exp:
        return JSONResponse(status_code=400, content={"detail": "Trading experience is required"})
    if not segs:
        return JSONResponse(status_code=400, content={"detail": "Select at least one trading segment"})
    try:
        from mcp_server.auth_providers import register_user
        db = SessionLocal()
        try:
            return await register_user(
                db, verify_token, password, name,
                city=body.get("city", ""),
                trading_experience=body.get("trading_experience", ""),
                segments=body.get("segments", ""),
                extra_phone=body.get("phone", ""),
                extra_email=body.get("email", ""),
            )
        finally:
            db.close()
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})


@router.post("/api/auth/user-login")
@limiter.limit("5/minute")
async def auth_user_login(request: Request):
    """Login with email/phone + password."""
    body = await request.json()
    identifier = body.get("email", "") or body.get("phone", "")
    password = body.get("password", "")
    if not identifier or not password:
        return JSONResponse(status_code=400, content={"detail": "Email/phone and password required"})
    try:
        from mcp_server.auth_providers import login_user
        db = SessionLocal()
        try:
            return await login_user(db, identifier, password)
        finally:
            db.close()
    except ValueError as e:
        return JSONResponse(status_code=401, content={"detail": str(e)})


@router.post("/api/auth/reset-password")
@limiter.limit("3/minute")
async def auth_reset_password(request: Request):
    """Reset password after OTP verification."""
    body = await request.json()
    verify_token = body.get("verify_token", "")
    new_password = body.get("password", "")
    if not verify_token or not new_password:
        return JSONResponse(status_code=400, content={"detail": "verify_token and password required"})
    try:
        from mcp_server.auth_providers import reset_password
        db = SessionLocal()
        try:
            return await reset_password(db, verify_token, new_password)
        finally:
            db.close()
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})


# ── BYOK: User API Keys ────────────────────────────────────────────


@router.post("/api/settings/api-keys")
async def save_api_keys(request: Request):
    """Save user's own LLM API keys."""
    user = getattr(request.state, "user", None)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

    body = await request.json()
    from mcp_server.auth_providers import save_user_api_keys
    db = SessionLocal()
    try:
        result = await save_user_api_keys(db, user.get("sub", ""), body)
        return result
    finally:
        db.close()


@router.get("/api/settings/api-keys")
async def get_api_keys(request: Request):
    """Get user's saved API keys (masked)."""
    user = getattr(request.state, "user", None)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

    from mcp_server.auth_providers import get_user_api_keys
    db = SessionLocal()
    try:
        keys = await get_user_api_keys(db, user.get("sub", ""))
        masked = {}
        for k, v in keys.items():
            if k == "preferred_provider":
                masked[k] = v
            elif v and len(v) > 8:
                masked[k] = v[:4] + "****" + v[-4:]
            else:
                masked[k] = "****" if v else ""
        return {"keys": masked, "has_keys": bool(keys)}
    finally:
        db.close()


# ── Auth config discovery ─────────────────────────────────────────


@router.get("/api/auth/config")
async def auth_config():
    """Return auth configuration for frontend (which methods are available)."""
    import os
    return {
        "google_enabled": bool(os.getenv("GOOGLE_CLIENT_ID")),
        "google_client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "email_otp_enabled": bool(os.getenv("SMTP_USER")),
        "mobile_otp_enabled": bool(os.getenv("MSG91_AUTH_KEY")),
        "password_enabled": True,
    }


# ── Tier enforcement ──────────────────────────────────────────────


@router.get("/api/user/tier")
async def api_user_tier(request: Request):
    """Get current user's tier info + feature access map."""
    try:
        user = getattr(request.state, "user", None)
        email = user.get("sub", "") if user else ""
        from mcp_server.tier_guard import get_user_tier_info
        return get_user_tier_info(email)
    except Exception:
        # Fallback — don't block the app
        return {"tier": "admin", "paper_capital": 2500000, "watchlist_max": -1, "features": {}}


@router.get("/api/user/check-feature/{feature}")
async def api_check_feature(feature: str, request: Request):
    """Check if user can access a specific feature."""
    user = getattr(request.state, "user", None)
    email = user.get("sub", "") if user else ""
    from mcp_server.tier_guard import check_tier, TierError
    try:
        result = check_tier(email, feature, record=False)
        return result
    except TierError as e:
        return JSONResponse(status_code=403, content={
            "allowed": False,
            "message": e.message,
            "required_tier": e.required_tier,
            "current_tier": e.current_tier,
            "feature": e.feature,
        })
