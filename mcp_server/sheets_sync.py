"""Google Sheets auto-sync for MKUMARAN Trading OS."""
import logging
from datetime import date

from mcp_server.config import settings

logger = logging.getLogger(__name__)


def _get_sheets_client():
    """Get authenticated gspread client."""
    if not settings.GOOGLE_SHEETS_CREDENTIALS or not settings.GOOGLE_SHEET_ID:
        logger.warning("Google Sheets not configured")
        return None, None

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]

        creds = Credentials.from_service_account_file(
            settings.GOOGLE_SHEETS_CREDENTIALS,
            scopes=scopes,
        )
        client = gspread.authorize(creds)
        sheet = client.open_by_key(settings.GOOGLE_SHEET_ID)

        return client, sheet

    except Exception as e:
        logger.error("Failed to connect to Google Sheets: %s", e)
        return None, None


def sync_watchlist(watchlist_items: list[dict]) -> bool:
    """
    Sync watchlist data to the WATCHLIST tab.
    Tab 1 of 5 in the Google Sheet.
    """
    _, sheet = _get_sheets_client()
    if not sheet:
        return False

    try:
        ws = sheet.worksheet("WATCHLIST")

        # Clear existing data (keep headers)
        ws.clear()

        # Headers
        headers = ["Ticker", "Name", "Timeframe", "Tier", "LTRP", "Pivot High",
                    "Active", "Source", "Added By", "Notes"]
        ws.append_row(headers)

        # Data rows
        for item in watchlist_items:
            row = [
                item.get("ticker", ""),
                item.get("name", ""),
                item.get("timeframe", "day"),
                item.get("tier", 2),
                item.get("ltrp", ""),
                item.get("pivot_high", ""),
                "Yes" if item.get("active") else "No",
                item.get("source", ""),
                item.get("added_by", ""),
                item.get("notes", ""),
            ]
            ws.append_row(row)

        logger.info("Synced %d watchlist items to Sheets", len(watchlist_items))
        return True

    except Exception as e:
        logger.error("Watchlist sync failed: %s", e)
        return False


def log_signal(signal_data: dict) -> bool:
    """
    Log a signal to the SIGNALS tab.
    Tab 2 of 5.
    """
    _, sheet = _get_sheets_client()
    if not sheet:
        return False

    try:
        ws = sheet.worksheet("SIGNALS")

        row = [
            signal_data.get("signal_date", str(date.today())),
            signal_data.get("signal_time", ""),
            signal_data.get("ticker", ""),
            signal_data.get("direction", ""),
            signal_data.get("pattern", ""),
            signal_data.get("entry_price", 0),
            signal_data.get("stop_loss", 0),
            signal_data.get("target", 0),
            signal_data.get("rrr", 0),
            signal_data.get("qty", 0),
            signal_data.get("risk_amt", 0),
            signal_data.get("ai_confidence", 0),
            "Yes" if signal_data.get("tv_confirmed") else "No",
            signal_data.get("mwa_score", ""),
            signal_data.get("scanner_count", 0),
            signal_data.get("status", "OPEN"),
        ]
        ws.append_row(row)

        logger.info("Logged signal for %s to Sheets", signal_data.get("ticker"))
        return True

    except Exception as e:
        logger.error("Signal logging failed: %s", e)
        return False


def update_accuracy(outcomes: list[dict]) -> bool:
    """
    Update the ACCURACY TRACKER tab.
    Tab 3 of 5.
    """
    _, sheet = _get_sheets_client()
    if not sheet:
        return False

    try:
        ws = sheet.worksheet("ACCURACY")
        ws.clear()

        headers = ["Signal ID", "Ticker", "Direction", "Entry", "Exit",
                    "Outcome", "P&L", "Days Held", "Exit Reason"]
        ws.append_row(headers)

        for outcome in outcomes:
            row = [
                outcome.get("signal_id", ""),
                outcome.get("ticker", ""),
                outcome.get("direction", ""),
                outcome.get("entry_price", 0),
                outcome.get("exit_price", 0),
                outcome.get("outcome", ""),
                outcome.get("pnl_amount", 0),
                outcome.get("days_held", 0),
                outcome.get("exit_reason", ""),
            ]
            ws.append_row(row)

        logger.info("Updated accuracy tracker with %d outcomes", len(outcomes))
        return True

    except Exception as e:
        logger.error("Accuracy update failed: %s", e)
        return False


def log_mwa(mwa_data: dict) -> bool:
    """
    Log daily MWA score to MWA DAILY LOG tab.
    Tab 4 of 5.
    """
    _, sheet = _get_sheets_client()
    if not sheet:
        return False

    try:
        ws = sheet.worksheet("MWA LOG")

        row = [
            mwa_data.get("score_date", str(date.today())),
            mwa_data.get("direction", ""),
            mwa_data.get("bull_score", 0),
            mwa_data.get("bear_score", 0),
            mwa_data.get("bull_pct", 0),
            mwa_data.get("bear_pct", 0),
        ]
        ws.append_row(row)

        logger.info("Logged MWA score to Sheets: %s", mwa_data.get("direction"))
        return True

    except Exception as e:
        logger.error("MWA logging failed: %s", e)
        return False


def sync_active_trades(trades: list[dict]) -> bool:
    """
    Sync active trades to ACTIVE TRADES tab.
    Tab 5 of 5.
    """
    _, sheet = _get_sheets_client()
    if not sheet:
        return False

    try:
        ws = sheet.worksheet("ACTIVE TRADES")
        ws.clear()

        headers = ["Ticker", "Entry", "Target", "SL", "PRRR", "Current",
                    "CRRR", "P&L %", "Last Updated"]
        ws.append_row(headers)

        for trade in trades:
            entry = trade.get("entry_price", 0)
            current = trade.get("current_price", 0)
            pnl_pct = ((current - entry) / entry * 100) if entry > 0 else 0

            row = [
                trade.get("ticker", ""),
                entry,
                trade.get("target", 0),
                trade.get("stop_loss", 0),
                trade.get("prrr", 0),
                current,
                trade.get("crrr", 0),
                round(pnl_pct, 2),
                trade.get("last_updated", ""),
            ]
            ws.append_row(row)

        logger.info("Synced %d active trades to Sheets", len(trades))
        return True

    except Exception as e:
        logger.error("Active trades sync failed: %s", e)
        return False
