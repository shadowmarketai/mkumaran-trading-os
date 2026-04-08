"""
MKUMARAN Trading OS — Telegram Signal Receiver + Google Sheets Tracker

Receives trading signals via Telegram bot, parses them,
records to Google Sheets, and tracks accuracy (target hit / SL hit).

Setup:
1. Create Telegram bot via @BotFather → get BOT_TOKEN
2. Create Google Sheet → share with service account email
3. Set env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
   GOOGLE_SHEET_ID, GOOGLE_SHEETS_CREDENTIALS (path to JSON)
4. Run: python -m mcp_server.telegram_receiver

Google Sheet columns:
A: Signal ID | B: Date | C: Ticker | D: Exchange | E: Asset Class
F: Direction | G: Entry Price | H: Stop Loss | I: Target | J: RRR
K: Pattern | L: Confidence | M: Status | N: Exit Price | O: Exit Date
P: P&L % | Q: P&L Rs | R: Result | S: Notes

Segment routing: signals also written to segment-specific tabs
(SIGNALS_EQUITY, SIGNALS_COMMODITY, SIGNALS_FNO, SIGNALS_FOREX)
"""

import logging
import os
import re
from datetime import date

from mcp_server.market_calendar import now_ist
from dataclasses import dataclass

from mcp_server.config import settings

logger = logging.getLogger(__name__)


# ── Signal Data Model ────────────────────────────────────────

EXCHANGE_TO_ASSET_CLASS = {
    "NSE": "EQUITY",
    "BSE": "EQUITY",
    "MCX": "COMMODITY",
    "CDS": "CURRENCY",
    "NFO": "FNO",
}

EXCHANGE_TO_SEGMENT_TAB = {
    "NSE": "SIGNALS_EQUITY",
    "BSE": "SIGNALS_EQUITY",
    "MCX": "SIGNALS_COMMODITY",
    "NFO": "SIGNALS_FNO",
    "CDS": "SIGNALS_FOREX",
}


@dataclass
class TelegramSignal:
    """Parsed signal from Telegram message."""
    signal_id: str = ""
    date: str = ""
    ticker: str = ""
    exchange: str = "NSE"
    asset_class: str = "EQUITY"
    direction: str = ""  # BUY / SELL / LONG / SHORT
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target: float = 0.0
    rrr: float = 0.0
    pattern: str = ""
    confidence: int = 0
    status: str = "OPEN"  # OPEN / TARGET_HIT / SL_HIT / PARTIAL / EXPIRED / CANCELLED
    exit_price: float = 0.0
    exit_date: str = ""
    pnl_pct: float = 0.0
    pnl_rs: float = 0.0
    result: str = ""  # WIN / LOSS / BREAKEVEN
    notes: str = ""
    raw_message: str = ""


# ── Signal Parser ────────────────────────────────────────────

def parse_signal_message(text: str) -> TelegramSignal | None:
    """
    Parse a trading signal from Telegram message text.

    Supports multiple formats:
    1. Structured: "BUY NSE:RELIANCE @ 2500 SL 2400 TGT 2800"
    2. MCP format: "SIGNAL: RELIANCE | BUY | Entry: 2500 | SL: 2400 | Target: 2800"
    3. Simple: "RELIANCE BUY 2500 SL 2400 TARGET 2800"
    """
    if not text or len(text) < 10:
        return None

    signal = TelegramSignal(
        date=date.today().isoformat(),
        signal_id=f"SIG-{now_ist().strftime('%Y%m%d%H%M%S')}",
        raw_message=text[:500],
    )

    upper = text.upper()

    # Direction
    if any(w in upper for w in ("BUY", "LONG", "BULLISH")):
        signal.direction = "BUY"
    elif any(w in upper for w in ("SELL", "SHORT", "BEARISH")):
        signal.direction = "SELL"
    else:
        return None  # No direction = not a signal

    # Ticker — look for EXCHANGE:SYMBOL or known patterns
    ticker_match = re.search(r'(NSE|BSE|MCX|CDS|NFO):([A-Z0-9_]+)', upper)
    if ticker_match:
        signal.exchange = ticker_match.group(1)
        signal.ticker = f"{ticker_match.group(1)}:{ticker_match.group(2)}"
    else:
        # Try to find a standalone ticker (uppercase word, 3-20 chars)
        words = re.findall(r'\b([A-Z][A-Z0-9]{2,19})\b', upper)
        skip = {"BUY", "SELL", "LONG", "SHORT", "BULLISH", "BEARISH",
                "ENTRY", "TARGET", "TGT", "STOP", "LOSS", "SIGNAL",
                "ALERT", "WATCHLIST", "CMP", "SL", "TP", "OPEN", "CLOSE",
                "HIGH", "LOW", "PATTERN", "CONFIDENCE", "RRR", "SKIP",
                "NSE", "BSE", "MCX", "CDS", "NFO"}
        for w in words:
            if w not in skip and len(w) >= 3:
                signal.ticker = f"NSE:{w}"
                break

    if not signal.ticker:
        return None

    # Prices — extract numbers following keywords
    def _extract_price(pattern: str) -> float:
        m = re.search(pattern, upper.replace(",", ""))
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        return 0.0

    signal.entry_price = _extract_price(r'(?:ENTRY|@|CMP|PRICE)[:\s]*₹?\s*(\d+\.?\d*)')
    if signal.entry_price == 0:
        # Try: number right after ticker
        m = re.search(r'(?:BUY|SELL|LONG|SHORT)\s+\S+\s+(\d+\.?\d*)', upper)
        if m:
            signal.entry_price = float(m.group(1))

    signal.stop_loss = _extract_price(r'(?:SL|STOP\s*LOSS|STOPLOSS)[:\s]*₹?\s*(\d+\.?\d*)')
    signal.target = _extract_price(r'(?:TGT|TARGET|TP|TAKE\s*PROFIT)[:\s]*₹?\s*(\d+\.?\d*)')

    # RRR
    if signal.stop_loss > 0 and signal.target > 0 and signal.entry_price > 0:
        risk = abs(signal.entry_price - signal.stop_loss)
        reward = abs(signal.target - signal.entry_price)
        signal.rrr = round(reward / risk, 2) if risk > 0 else 0

    # Pattern
    pattern_match = re.search(r'(?:PATTERN|SETUP)[:\s]*([A-Za-z_ ]+?)(?:\||$|\n)', text, re.IGNORECASE)
    if pattern_match:
        signal.pattern = pattern_match.group(1).strip()

    # Confidence
    conf_match = re.search(r'(?:CONFIDENCE|CONF)[:\s]*(\d+)', upper)
    if conf_match:
        signal.confidence = int(conf_match.group(1))

    # Derive asset_class from exchange
    signal.asset_class = EXCHANGE_TO_ASSET_CLASS.get(signal.exchange, "EQUITY")

    return signal


# ── Google Sheets Integration ────────────────────────────────

class SheetsTracker:
    """
    Records signals to Google Sheets and tracks accuracy.

    Requires:
    - pip install gspread google-auth
    - Service account JSON credentials
    - Sheet shared with service account email
    """

    def __init__(self, sheet_id: str = "", credentials_path: str = ""):
        self.sheet_id = sheet_id or settings.GOOGLE_SHEET_ID
        self.credentials_path = credentials_path or settings.GOOGLE_SHEETS_CREDENTIALS
        self._sheet = None
        self._worksheet = None

        # Resolve relative/Docker paths to actual project path
        if self.credentials_path and not os.path.isabs(self.credentials_path):
            # Try relative to project root
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            candidate = os.path.join(project_root, self.credentials_path)
            if os.path.exists(candidate):
                self.credentials_path = candidate
        elif self.credentials_path and not os.path.exists(self.credentials_path):
            # Docker path like /app/data/... — try mapping to local project
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            # Strip leading /app/ prefix if present
            local_path = self.credentials_path
            for prefix in ("/app/", "/app\\"):
                if local_path.startswith(prefix):
                    local_path = local_path[len(prefix):]
                    break
            candidate = os.path.join(project_root, local_path)
            if os.path.exists(candidate):
                self.credentials_path = candidate

    def _connect(self):
        """Lazy-connect to Google Sheets."""
        if self._sheet is not None:
            return

        if not self.sheet_id or not self.credentials_path:
            logger.warning("Google Sheets not configured (missing GOOGLE_SHEET_ID or credentials)")
            return

        try:
            import gspread
            from google.oauth2.service_account import Credentials

            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = Credentials.from_service_account_file(self.credentials_path, scopes=scopes)
            gc = gspread.authorize(creds)
            self._sheet = gc.open_by_key(self.sheet_id)

            # Get or create "Signals" worksheet
            try:
                self._worksheet = self._sheet.worksheet("Signals")
            except gspread.WorksheetNotFound:
                self._worksheet = self._sheet.add_worksheet("Signals", rows=1000, cols=19)
                self._write_headers()

            logger.info("Connected to Google Sheet: %s", self.sheet_id)
        except ImportError:
            logger.error("gspread not installed. Run: pip install gspread google-auth")
        except Exception as e:
            logger.error("Failed to connect to Google Sheets: %s", e)

    def _write_headers(self):
        """Write column headers to the worksheet."""
        headers = [
            "Signal ID", "Date", "Ticker", "Exchange", "Asset Class",
            "Direction", "Entry Price", "Stop Loss", "Target", "RRR",
            "Pattern", "Confidence", "Status", "Exit Price", "Exit Date",
            "P&L %", "P&L Rs", "Result", "Notes",
        ]
        if self._worksheet:
            self._worksheet.update("A1:S1", [headers])

    def _ensure_segment_tab(self, exchange: str):
        """Get or create a segment-specific tab for the given exchange."""
        tab_name = EXCHANGE_TO_SEGMENT_TAB.get(exchange, "SIGNALS_EQUITY")
        try:
            return self._sheet.worksheet(tab_name)
        except Exception:
            ws = self._sheet.add_worksheet(title=tab_name, rows=1000, cols=19)
            headers = [
                "Signal ID", "Date", "Ticker", "Exchange", "Asset Class",
                "Direction", "Entry Price", "Stop Loss", "Target", "RRR",
                "Pattern", "Confidence", "Status", "Exit Price", "Exit Date",
                "P&L %", "P&L Rs", "Result", "Notes",
            ]
            ws.update("A1:S1", [headers])
            logger.info("Created segment sheet tab: %s", tab_name)
            return ws

    def record_signal(self, signal: TelegramSignal) -> bool:
        """Record a new signal to master Signals tab + segment-specific tab."""
        self._connect()
        if self._worksheet is None:
            logger.warning("Cannot record signal — Sheets not connected")
            return False

        try:
            row = [
                signal.signal_id, signal.date, signal.ticker, signal.exchange,
                signal.asset_class, signal.direction, signal.entry_price,
                signal.stop_loss, signal.target, signal.rrr, signal.pattern,
                signal.confidence, signal.status, signal.exit_price,
                signal.exit_date, signal.pnl_pct, signal.pnl_rs,
                signal.result, signal.notes,
            ]
            # Write to master Signals tab
            self._worksheet.append_row(row, value_input_option="USER_ENTERED")

            # Write to segment-specific tab (SIGNALS_EQUITY, SIGNALS_COMMODITY, etc.)
            if self._sheet:
                try:
                    seg_ws = self._ensure_segment_tab(signal.exchange)
                    seg_ws.append_row(row, value_input_option="USER_ENTERED")
                    logger.info("Recorded signal %s to Signals + %s",
                                signal.signal_id,
                                EXCHANGE_TO_SEGMENT_TAB.get(signal.exchange, "SIGNALS_EQUITY"))
                except Exception as e:
                    logger.warning("Segment tab write failed (master succeeded): %s", e)
            else:
                logger.info("Recorded signal %s to Signals tab", signal.signal_id)

            return True
        except Exception as e:
            logger.error("Failed to record signal: %s", e)
            return False

    def update_signal_status(
        self,
        signal_id: str,
        status: str,
        exit_price: float = 0,
        notes: str = "",
    ) -> bool:
        """Update an existing signal's status (TARGET_HIT, SL_HIT, etc)."""
        self._connect()
        if self._worksheet is None:
            return False

        try:
            # Find the row with this signal_id
            cell = self._worksheet.find(signal_id, in_column=1)
            if cell is None:
                logger.warning("Signal %s not found in sheet", signal_id)
                return False

            row = cell.row

            # Get entry price (col G=7) and direction (col F=6) for P&L calc
            entry_price = float(self._worksheet.cell(row, 7).value or 0)
            direction = self._worksheet.cell(row, 6).value or "BUY"

            # Calculate P&L
            if exit_price > 0 and entry_price > 0:
                if direction in ("BUY", "LONG"):
                    pnl_pct = (exit_price - entry_price) / entry_price * 100
                else:
                    pnl_pct = (entry_price - exit_price) / entry_price * 100
                pnl_rs = (exit_price - entry_price) if direction in ("BUY", "LONG") else (entry_price - exit_price)
            else:
                pnl_pct = 0
                pnl_rs = 0

            # Determine result
            if status == "TARGET_HIT":
                result = "WIN"
            elif status == "SL_HIT":
                result = "LOSS"
            elif pnl_pct > 0:
                result = "WIN"
            elif pnl_pct < 0:
                result = "LOSS"
            else:
                result = "BREAKEVEN"

            # Update columns M (Status) through S (Notes)
            updates = [
                [status, exit_price, date.today().isoformat(),
                 round(pnl_pct, 2), round(pnl_rs, 2), result, notes],
            ]
            self._worksheet.update(f"M{row}:S{row}", updates, value_input_option="USER_ENTERED")
            logger.info("Updated signal %s: %s (P&L: %.2f%%)", signal_id, status, pnl_pct)
            return True

        except Exception as e:
            logger.error("Failed to update signal %s: %s", signal_id, e)
            return False

    def _update_open_row_on_ws(
        self,
        ws,
        ticker: str,
        signal_date: str,
        direction: str,
        status: str,
        exit_price: float,
        notes: str,
    ) -> bool:
        """Find an OPEN row on `ws` matching ticker+date+direction and patch
        columns M:S (Status through Notes). Returns True if a row was updated.

        Uses a single get_all_values() API call then finds the most recent
        matching OPEN row (searches bottom-up so re-opened signals work).
        """
        try:
            all_rows = ws.get_all_values()
            if not all_rows or len(all_rows) < 2:
                return False

            ticker_u = (ticker or "").strip().upper()
            direction_u = (direction or "").strip().upper()
            # Treat BUY/LONG and SELL/SHORT as aliases
            if direction_u in ("BUY", "LONG"):
                dir_aliases = {"BUY", "LONG"}
            elif direction_u in ("SELL", "SHORT"):
                dir_aliases = {"SELL", "SHORT"}
            else:
                dir_aliases = {direction_u}
            date_str = str(signal_date).strip()

            row_idx = None
            # Search from bottom (most recent first), skip header row 0
            for i in range(len(all_rows) - 1, 0, -1):
                row = all_rows[i]
                if len(row) < 13:
                    continue
                row_ticker = (row[2] or "").strip().upper()        # col C
                row_date = (row[1] or "").strip()                  # col B
                row_dir = (row[5] or "").strip().upper()           # col F
                row_status = (row[12] or "").strip().upper()       # col M
                if (
                    row_ticker == ticker_u
                    and row_date == date_str
                    and row_dir in dir_aliases
                    and row_status == "OPEN"
                ):
                    row_idx = i + 1  # gspread rows are 1-indexed
                    break

            if row_idx is None:
                return False

            # Entry price is col G (index 6 in 0-based list)
            try:
                entry_price = float((all_rows[row_idx - 1][6] or "0").replace(",", ""))
            except (ValueError, IndexError):
                entry_price = 0.0

            # Calculate P&L
            if exit_price > 0 and entry_price > 0:
                if direction_u in ("BUY", "LONG"):
                    pnl_pct = (exit_price - entry_price) / entry_price * 100
                    pnl_rs = exit_price - entry_price
                else:
                    pnl_pct = (entry_price - exit_price) / entry_price * 100
                    pnl_rs = entry_price - exit_price
            else:
                pnl_pct = 0.0
                pnl_rs = 0.0

            # Determine result
            if status == "TARGET_HIT":
                result = "WIN"
            elif status == "SL_HIT":
                result = "LOSS"
            elif pnl_pct > 0:
                result = "WIN"
            elif pnl_pct < 0:
                result = "LOSS"
            else:
                result = "BREAKEVEN"

            updates = [[
                status,
                exit_price,
                date.today().isoformat(),
                round(pnl_pct, 2),
                round(pnl_rs, 2),
                result,
                notes,
            ]]
            ws.update(f"M{row_idx}:S{row_idx}", updates, value_input_option="USER_ENTERED")
            return True

        except Exception as e:
            logger.debug("_update_open_row_on_ws failed for %s: %s", ticker, e)
            return False

    def update_signal_status_by_match(
        self,
        ticker: str,
        signal_date: str,
        direction: str,
        exchange: str,
        status: str,
        exit_price: float = 0,
        notes: str = "",
    ) -> bool:
        """Update an OPEN signal by matching ticker + date + direction.

        This is the correct lookup path for DB-originated signals where the
        integer DB id does not correspond to the ``SIG-YYYYMMDDHHMMSS`` string
        ID stored in column A of the Google Sheet. Updates both the master
        ``Signals`` tab and the segment-specific tab (SIGNALS_EQUITY, etc.).

        Returns True if at least one tab was updated.
        """
        self._connect()
        if self._worksheet is None:
            return False

        # Master Signals tab
        updated_master = self._update_open_row_on_ws(
            self._worksheet, ticker, signal_date, direction, status, exit_price, notes
        )

        # Segment-specific tab (same row schema since written via record_signal)
        updated_segment = False
        try:
            if self._sheet is not None:
                tab_name = EXCHANGE_TO_SEGMENT_TAB.get(
                    (exchange or "NSE").upper(), "SIGNALS_EQUITY"
                )
                try:
                    seg_ws = self._sheet.worksheet(tab_name)
                    updated_segment = self._update_open_row_on_ws(
                        seg_ws, ticker, signal_date, direction, status, exit_price, notes
                    )
                except Exception as ws_err:
                    logger.debug("Segment tab %s not accessible: %s", tab_name, ws_err)
        except Exception as seg_err:
            logger.debug("Segment tab lookup failed for %s: %s", exchange, seg_err)

        if updated_master or updated_segment:
            logger.info(
                "Sheets closed %s %s %s (master=%s, segment=%s)",
                ticker, direction, status, updated_master, updated_segment,
            )
            return True

        logger.warning(
            "No OPEN row found in Sheets for %s %s %s (date=%s)",
            ticker, direction, exchange, signal_date,
        )
        return False

    def get_accuracy_stats(self) -> dict:
        """Calculate accuracy statistics from the sheet."""
        self._connect()
        if self._worksheet is None:
            return {"error": "Sheets not connected"}

        try:
            all_records = self._worksheet.get_all_records()
            if not all_records:
                return {"total": 0, "message": "No signals recorded"}

            total = len(all_records)
            closed = [r for r in all_records if r.get("Status") in ("TARGET_HIT", "SL_HIT", "PARTIAL", "EXPIRED")]
            wins = [r for r in closed if r.get("Result") == "WIN"]
            losses = [r for r in closed if r.get("Result") == "LOSS"]
            open_signals = [r for r in all_records if r.get("Status") == "OPEN"]

            total_pnl = sum(float(r.get("P&L Rs", 0) or 0) for r in closed)
            avg_win = sum(float(r.get("P&L %", 0) or 0) for r in wins) / len(wins) if wins else 0
            avg_loss = sum(float(r.get("P&L %", 0) or 0) for r in losses) / len(losses) if losses else 0

            return {
                "total_signals": total,
                "open": len(open_signals),
                "closed": len(closed),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
                "total_pnl_rs": round(total_pnl, 2),
                "avg_win_pct": round(avg_win, 2),
                "avg_loss_pct": round(avg_loss, 2),
                "expectancy": round(avg_win * (len(wins) / max(len(closed), 1)) + avg_loss * (len(losses) / max(len(closed), 1)), 2),
            }
        except Exception as e:
            logger.error("Failed to get accuracy stats: %s", e)
            return {"error": str(e)}


# ── Telegram Bot ─────────────────────────────────────────────

class TelegramSignalBot:
    """
    Telegram bot that listens for signals and records them.

    Usage:
        bot = TelegramSignalBot()
        bot.start()  # Blocking — runs event loop
    """

    def __init__(self):
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.tracker = SheetsTracker()
        self._app = None

    def _setup(self):
        """Set up the Telegram bot application."""
        try:
            from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters
            self._app = ApplicationBuilder().token(self.token).build()

            # Handlers
            self._app.add_handler(CommandHandler("start", self._cmd_start))
            self._app.add_handler(CommandHandler("stats", self._cmd_stats))
            self._app.add_handler(CommandHandler("update", self._cmd_update))
            self._app.add_handler(MessageHandler(
                filters.TEXT & ~filters.COMMAND, self._on_message
            ))

            logger.info("Telegram bot configured")
        except ImportError:
            logger.error("python-telegram-bot not installed. Run: pip install python-telegram-bot")

    async def _cmd_start(self, update, context):
        """Handle /start command."""
        await update.message.reply_text(
            "MKUMARAN Trading OS — Signal Tracker\n\n"
            "Send me trading signals and I'll record them to Google Sheets.\n\n"
            "Format: BUY NSE:RELIANCE @ 2500 SL 2400 TGT 2800\n\n"
            "Commands:\n"
            "/stats — View accuracy statistics\n"
            "/update SIGNAL_ID STATUS EXIT_PRICE — Update signal\n"
            "  Status: TARGET_HIT, SL_HIT, PARTIAL, EXPIRED, CANCELLED"
        )

    async def _cmd_stats(self, update, context):
        """Handle /stats command — show accuracy."""
        stats = self.tracker.get_accuracy_stats()
        if "error" in stats:
            await update.message.reply_text(f"Error: {stats['error']}")
            return

        msg = (
            f"📊 Signal Accuracy Report\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Total Signals: {stats['total_signals']}\n"
            f"Open: {stats['open']} | Closed: {stats['closed']}\n"
            f"Wins: {stats['wins']} | Losses: {stats['losses']}\n"
            f"Win Rate: {stats['win_rate']}%\n"
            f"Total P&L: Rs.{stats['total_pnl_rs']:,.2f}\n"
            f"Avg Win: {stats['avg_win_pct']}%\n"
            f"Avg Loss: {stats['avg_loss_pct']}%\n"
            f"Expectancy: {stats['expectancy']}%"
        )
        await update.message.reply_text(msg)

    async def _cmd_update(self, update, context):
        """Handle /update SIGNAL_ID STATUS EXIT_PRICE."""
        args = context.args
        if len(args) < 2:
            await update.message.reply_text(
                "Usage: /update SIGNAL_ID STATUS [EXIT_PRICE]\n"
                "Example: /update SIG-20260327120000 TARGET_HIT 2800"
            )
            return

        signal_id = args[0]
        status = args[1].upper()
        exit_price = float(args[2]) if len(args) > 2 else 0

        valid_statuses = {"TARGET_HIT", "SL_HIT", "PARTIAL", "EXPIRED", "CANCELLED"}
        if status not in valid_statuses:
            await update.message.reply_text(f"Invalid status. Use: {', '.join(valid_statuses)}")
            return

        success = self.tracker.update_signal_status(signal_id, status, exit_price)
        if success:
            await update.message.reply_text(f"Updated {signal_id} → {status}")
        else:
            await update.message.reply_text(f"Failed to update {signal_id}")

    async def _on_message(self, update, context):
        """Handle incoming text messages — try to parse as signal."""
        text = update.message.text
        signal = parse_signal_message(text)

        if signal is None:
            # Not a signal — ignore silently
            return

        # Record to Google Sheets
        recorded = self.tracker.record_signal(signal)

        if recorded:
            response = (
                f"Signal Recorded\n"
                f"━━━━━━━━━━━━━━━\n"
                f"ID: {signal.signal_id}\n"
                f"Ticker: {signal.ticker}\n"
                f"Direction: {signal.direction}\n"
                f"Entry: {signal.entry_price}\n"
                f"SL: {signal.stop_loss}\n"
                f"Target: {signal.target}\n"
                f"RRR: {signal.rrr}\n"
                f"Status: OPEN"
            )
        else:
            response = (
                f"Signal Parsed (not recorded — Sheets not connected)\n"
                f"Ticker: {signal.ticker} | {signal.direction}\n"
                f"Entry: {signal.entry_price} | SL: {signal.stop_loss} | TGT: {signal.target}"
            )

        await update.message.reply_text(response)

    def start(self):
        """Start the bot (blocking)."""
        if not self.token:
            logger.error("TELEGRAM_BOT_TOKEN not set — cannot start bot")
            return

        self._setup()
        if self._app is None:
            return

        logger.info("Starting Telegram Signal Bot...")
        self._app.run_polling()


# ── MCP Server Endpoints (non-blocking) ─────────────────────

_sheets_tracker: SheetsTracker | None = None


def get_sheets_tracker() -> SheetsTracker:
    """Get singleton SheetsTracker instance."""
    global _sheets_tracker
    if _sheets_tracker is None:
        _sheets_tracker = SheetsTracker()
    return _sheets_tracker


def record_signal_to_sheets(signal_data: dict) -> dict:
    """
    Record a signal dict to Google Sheets.

    Called by MCP server / n8n webhook when a signal is generated.
    """
    exchange = signal_data.get("exchange", "NSE")
    signal = TelegramSignal(
        signal_id=signal_data.get("signal_id", f"SIG-{now_ist().strftime('%Y%m%d%H%M%S')}"),
        date=signal_data.get("date", date.today().isoformat()),
        ticker=signal_data.get("ticker", ""),
        exchange=exchange,
        asset_class=signal_data.get("asset_class", EXCHANGE_TO_ASSET_CLASS.get(exchange, "EQUITY")),
        direction=signal_data.get("direction", ""),
        entry_price=float(signal_data.get("entry_price", 0)),
        stop_loss=float(signal_data.get("stop_loss", 0)),
        target=float(signal_data.get("target", 0)),
        rrr=float(signal_data.get("rrr", 0)),
        pattern=signal_data.get("pattern", ""),
        confidence=int(signal_data.get("confidence", 0)),
        status="OPEN",
        notes=signal_data.get("notes", ""),
    )

    tracker = get_sheets_tracker()
    success = tracker.record_signal(signal)

    return {
        "recorded": success,
        "signal_id": signal.signal_id,
        "ticker": signal.ticker,
        "direction": signal.direction,
    }


# ── CLI Entry Point ──────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    bot = TelegramSignalBot()
    bot.start()
