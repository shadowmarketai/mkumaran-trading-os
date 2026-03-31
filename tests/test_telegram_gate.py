"""Tests for Telegram market hours gate in send_telegram_message()."""

from unittest.mock import AsyncMock, patch

import pytest

from mcp_server.telegram_bot import send_telegram_message


@pytest.fixture(autouse=True)
def _configure_telegram(monkeypatch):
    """Ensure Telegram settings are present for all tests."""
    monkeypatch.setattr("mcp_server.telegram_bot.settings.TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr("mcp_server.telegram_bot.settings.TELEGRAM_CHAT_ID", "123456")


def _mock_bot():
    """Return a patched telegram.Bot whose send_message is an AsyncMock."""
    bot_instance = AsyncMock()
    return patch("telegram.Bot", return_value=bot_instance), bot_instance


# ── Tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skip_on_weekend():
    """Messages should be skipped when market is closed on weekends."""
    with patch("mcp_server.market_calendar.is_market_open", return_value=False), \
         patch("mcp_server.market_calendar.get_market_status", return_value={"reason": "WEEKEND"}):
        bot_patch, bot_mock = _mock_bot()
        with bot_patch:
            await send_telegram_message("Test signal", exchange="NSE")
            bot_mock.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_allow_during_market_hours():
    """Messages should be sent when market is open."""
    with patch("mcp_server.market_calendar.is_market_open", return_value=True):
        bot_patch, bot_mock = _mock_bot()
        with bot_patch:
            await send_telegram_message("Test signal", exchange="NSE")
            bot_mock.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_force_override():
    """force=True should bypass market hours check entirely."""
    bot_patch, bot_mock = _mock_bot()
    with bot_patch:
        await send_telegram_message("KILL SWITCH TRIGGERED", exchange="NSE", force=True)
        bot_mock.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_holiday_block():
    """Messages should be skipped on market holidays."""
    with patch("mcp_server.market_calendar.is_market_open", return_value=False), \
         patch("mcp_server.market_calendar.get_market_status", return_value={"reason": "HOLIDAY"}):
        bot_patch, bot_mock = _mock_bot()
        with bot_patch:
            await send_telegram_message("Holiday signal", exchange="NSE")
            bot_mock.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_mcx_evening_allowed():
    """MCX is open until 23:30 — evening messages should go through."""
    with patch("mcp_server.market_calendar.is_market_open", return_value=True):
        bot_patch, bot_mock = _mock_bot()
        with bot_patch:
            await send_telegram_message("MCX Gold signal", exchange="MCX")
            bot_mock.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_default_exchange_nse():
    """Default exchange should be NSE when not specified."""
    with patch("mcp_server.market_calendar.is_market_open", return_value=True) as mock_check:
        bot_patch, bot_mock = _mock_bot()
        with bot_patch:
            await send_telegram_message("Default exchange test")
            mock_check.assert_called_once_with("NSE")
