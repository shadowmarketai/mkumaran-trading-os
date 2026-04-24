"""Tests for Telegram market hours gate in send_telegram_message().

Implementation note: send_telegram_message posts directly to the Telegram
Bot HTTP API via httpx.AsyncClient. The old path that instantiated a
telegram.Bot class per call was removed because it was prone to timeouts
under scan load. Tests mock httpx.AsyncClient.post.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_server.telegram_bot import send_telegram_message


@pytest.fixture(autouse=True)
def _configure_telegram(monkeypatch):
    """Ensure Telegram settings are present for all tests."""
    monkeypatch.setattr("mcp_server.telegram_bot.settings.TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr("mcp_server.telegram_bot.settings.TELEGRAM_CHAT_ID", "123456")


def _mock_httpx_ok():
    """Patch httpx.AsyncClient with a 200/ok response. Returns (patch, post_mock)."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"ok": True, "result": {}}

    client_instance = AsyncMock()
    client_instance.__aenter__.return_value = client_instance
    client_instance.__aexit__.return_value = None
    client_instance.post = AsyncMock(return_value=resp)

    return (
        patch("httpx.AsyncClient", return_value=client_instance),
        client_instance.post,
    )


# ── Tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skip_on_weekend():
    """Messages should be skipped when market is closed on weekends."""
    with patch("mcp_server.market_calendar.is_market_open", return_value=False), \
         patch("mcp_server.market_calendar.get_market_status", return_value={"reason": "WEEKEND"}):
        client_patch, post_mock = _mock_httpx_ok()
        with client_patch:
            await send_telegram_message("Test signal", exchange="NSE")
            post_mock.assert_not_called()


@pytest.mark.asyncio
async def test_allow_during_market_hours():
    """Messages should be sent when market is open."""
    with patch("mcp_server.market_calendar.is_market_open", return_value=True):
        client_patch, post_mock = _mock_httpx_ok()
        with client_patch:
            await send_telegram_message("Test signal", exchange="NSE")
            post_mock.assert_called_once()


@pytest.mark.asyncio
async def test_force_override():
    """force=True should bypass market hours check entirely."""
    # is_market_open intentionally NOT mocked — force path shouldn't call it.
    client_patch, post_mock = _mock_httpx_ok()
    with client_patch:
        await send_telegram_message("KILL SWITCH TRIGGERED", exchange="NSE", force=True)
        post_mock.assert_called_once()


@pytest.mark.asyncio
async def test_holiday_block():
    """Messages should be skipped on market holidays."""
    with patch("mcp_server.market_calendar.is_market_open", return_value=False), \
         patch("mcp_server.market_calendar.get_market_status", return_value={"reason": "HOLIDAY"}):
        client_patch, post_mock = _mock_httpx_ok()
        with client_patch:
            await send_telegram_message("Holiday signal", exchange="NSE")
            post_mock.assert_not_called()


@pytest.mark.asyncio
async def test_mcx_evening_allowed():
    """MCX is open until 23:30 — evening messages should go through."""
    with patch("mcp_server.market_calendar.is_market_open", return_value=True):
        client_patch, post_mock = _mock_httpx_ok()
        with client_patch:
            await send_telegram_message("MCX Gold signal", exchange="MCX")
            post_mock.assert_called_once()


@pytest.mark.asyncio
async def test_default_exchange_nse():
    """Default exchange should be NSE when not specified."""
    with patch("mcp_server.market_calendar.is_market_open", return_value=True) as mock_check:
        client_patch, _ = _mock_httpx_ok()
        with client_patch:
            await send_telegram_message("Default exchange test")
            mock_check.assert_called_once_with("NSE")
