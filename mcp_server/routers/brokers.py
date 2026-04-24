"""Broker OAuth callbacks + token refresh endpoints.

Extracted from mcp_server.mcp_server in Phase 1e of the router split.
All 7 handlers moved verbatim.

Covers: Kite Connect (Zerodha), GWC (Goodwill), Angel One token
management. Mostly blocking-I/O wrappers around the broker auth modules
(kite_auth / gwc_auth / angel_auth), run via asyncio.to_thread.

Routes that mutate `_order_manager` or call `_now_ist()` use deferred
imports — those singletons + helpers still live in mcp_server.mcp_server
per the plan's "helpers stay" rule.
"""
import asyncio
import logging

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from mcp_server.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["brokers"])


# ── Kite (Zerodha) ─────────────────────────────────────────────────


@router.post("/tools/refresh_kite_token")
async def tool_refresh_kite_token():
    """Refresh Kite access token via TOTP login (standalone, no order manager needed)."""
    try:
        from mcp_server.kite_auth import refresh_kite_token
        # TOTP login is blocking I/O — run in worker thread
        access_token = await asyncio.to_thread(refresh_kite_token)

        # Clear the sticky "_kite_failed_today" flag + force-reload the
        # instrument cache. Without this, an earlier morning failure leaves
        # MCX/NFO/CDS resolution broken for the rest of the day even after
        # a successful token refresh.
        cache_tokens = 0
        try:
            from mcp_server.data_provider import force_reload_instrument_cache
            cache_tokens = await asyncio.to_thread(force_reload_instrument_cache)
        except Exception as exc:
            logger.warning("Instrument cache reload after TOTP refresh failed: %s", exc)

        return {
            "success": True,
            "message": "Kite token refreshed",
            "token_prefix": access_token[:8] + "..." if access_token else None,
            "instrument_cache_tokens": cache_tokens,
        }
    except Exception as e:
        logger.error("Kite token refresh failed: %s", e)
        return {
            "success": False,
            "message": f"Token refresh failed: {e}",
        }


@router.get("/api/kite_callback")
async def api_kite_callback(request_token: str = Query(...)):
    """Browser redirect callback from Kite Connect login.

    User logs in at Kite → Kite redirects here with ?request_token=XXX
    → we generate a session, cache the token, and show a success page.
    """
    try:
        from mcp_server.kite_auth import handle_kite_callback
        access_token = await asyncio.to_thread(handle_kite_callback, request_token)

        try:
            from kiteconnect import KiteConnect
            from mcp_server import mcp_server as _ms
            kite = KiteConnect(api_key=settings.KITE_API_KEY)
            kite.set_access_token(access_token)
            manager = _ms._get_order_manager()
            manager.kite = kite
            logger.info("Order manager connected to Kite via manual login")
        except Exception as e:
            logger.warning("Order manager Kite connect skipped: %s", e)

        try:
            from mcp_server import data_provider
            data_provider._kite_failed_today = False
        except Exception:
            pass

        # Kite login success is confirmed by the HTML page returned below.
        # No Telegram notification — it was drowning trade signals during
        # repeated OAuth callback hits.
        from mcp_server.mcp_server import _now_ist
        logger.info(
            "Kite login cached via callback at %s IST",
            _now_ist().strftime("%H:%M"),
        )

        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
            "<h1>✅ Kite Login Successful</h1>"
            "<p>Access token has been cached. You can close this window.</p>"
            "<p style='color:#888;font-size:14px'>Token will be valid until end of day.</p>"
            "</body></html>"
        )
    except Exception as e:
        logger.error("Kite callback failed: %s", e)
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
            f"<h1>❌ Kite Login Failed</h1><p>{e}</p>"
            "</body></html>",
            status_code=500,
        )


@router.get("/api/kite_login_url")
async def api_kite_login_url():
    """Return the Kite Connect login URL for manual browser login."""
    try:
        from mcp_server.kite_auth import get_kite_login_url
        url = get_kite_login_url()
        return {
            "login_url": url,
            "instructions": "Open this URL in your browser, complete Zerodha 2FA, "
                            "and the system will automatically capture the token.",
        }
    except Exception as e:
        return {"error": str(e)}


# ── GWC (Goodwill) ─────────────────────────────────────────────────


@router.post("/tools/refresh_gwc_token")
async def tool_refresh_gwc_token():
    """Refresh Goodwill (GWC) access token via auto-login.

    Uses /v1/quickauth with client-generated TOTP (no SMS OTP), then
    /v1/login-response to exchange the request_token for an access_token.
    Result is cached to data/gwc_token.json for the rest of the trading day.
    """
    try:
        from mcp_server.gwc_auth import refresh_gwc_token
        from mcp_server.data_provider import get_provider
        access_token = await asyncio.to_thread(refresh_gwc_token)
        try:
            provider = get_provider()
            provider.gwc.set_access_token(access_token)
            provider._sources["gwc"] = True
        except Exception as exc:
            logger.warning("GWC token set on provider failed: %s", exc)
        return {
            "success": True,
            "message": "GWC token refreshed",
            "token_prefix": access_token[:8] + "..." if access_token else None,
        }
    except Exception as e:
        logger.error("GWC token refresh failed: %s", e)
        return {
            "success": False,
            "message": f"Token refresh failed: {e}",
        }


@router.get("/api/gwc_callback")
async def api_gwc_callback(request_token: str = Query(...)):
    """Browser redirect callback from GWC OAuth login.

    User logs in at GWC → GWC redirects here with ?request_token=XXX
    → we exchange it for an access token and activate the GWC source.
    """
    try:
        from mcp_server.gwc_auth import handle_gwc_callback
        access_token = await asyncio.to_thread(handle_gwc_callback, request_token)

        from mcp_server.data_provider import get_provider
        provider = get_provider()
        provider.gwc.set_access_token(access_token)
        provider._sources["gwc"] = True

        try:
            from mcp_server.mcp_server import _now_ist
            from mcp_server.telegram_bot import send_telegram_message
            asyncio.ensure_future(send_telegram_message(
                "✅ GWC Login Successful\n"
                f"Token set at {_now_ist().strftime('%H:%M IST')}\n"
                "Goodwill is now the primary LTP source.",
                force=True,
            ))
        except Exception:
            pass

        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
            "<h1>✅ GWC Login Successful</h1>"
            "<p>Goodwill access token has been set. You can close this window.</p>"
            "<p style='color:#888;font-size:14px'>GWC is now the primary live price source.</p>"
            "</body></html>"
        )
    except Exception as e:
        logger.error("GWC callback failed: %s", e)
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
            f"<h1>❌ GWC Login Failed</h1><p>{e}</p>"
            "</body></html>",
            status_code=500,
        )


@router.get("/api/gwc_login_url")
async def api_gwc_login_url():
    """Return the GWC OAuth login URL for manual browser login."""
    if not settings.GWC_API_KEY:
        return {"error": "GWC_API_KEY not configured"}
    return {
        "login_url": f"https://api.gwcindia.in/v1/login?api_key={settings.GWC_API_KEY}",
        "instructions": "Open this URL in your browser, complete Goodwill 2FA, "
                        "and the system will automatically capture the token.",
    }


# ── Angel One ──────────────────────────────────────────────────────


@router.post("/tools/refresh_angel_token")
async def tool_refresh_angel_token():
    """Refresh Angel access token via TOTP login (standalone)."""
    try:
        from mcp_server.angel_auth import refresh_angel_token
        # TOTP login is blocking I/O — run in worker thread
        await asyncio.to_thread(refresh_angel_token)
        return {
            "success": True,
            "message": "Angel token refreshed",
        }
    except Exception as e:
        logger.error("Angel token refresh failed: %s", e)
        return {
            "success": False,
            "message": f"Angel token refresh failed: {e}",
        }
