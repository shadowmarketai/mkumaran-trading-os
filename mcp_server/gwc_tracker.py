"""
GWC (Goodwill Commodity) Signal Tracker

Parses Goodwill WhatsApp signals, validates via the debate pipeline,
and logs to the 'GWC TRACKER' Google Sheets tab.

GWC signals come in natural language like:
  "Buy nifty 23600ce @ 150 add more 130 sl 120 target 175 & 200"
  "ALERT : LT 4000 CE BUY AROUNDD 52/50 TRG 64/83 STOP@38"
  "Buy Sensex 74500pe @ 110 add more 80 sl 30 target 185 & 250 Exit @cost"

Differences from standard parse_signal_message:
  - "add more X" → avg_entry (averaging level, not the main entry)
  - "target X & Y" → dual targets (& separator instead of /)
  - "TRG" → treated as target keyword
  - "AROUNDD", "ARND" → typo-tolerant entry extraction
  - "Exit @cost" / "exit cost" → cost_exit flag (protect capital)
  - Sends result to Telegram and logs to GWC TRACKER Sheets tab
"""
from __future__ import annotations

import enum
import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

GWC_TRACKER_HEADERS = [
    "Date", "Time", "Source", "Ticker", "Direction",
    "Entry", "Add More", "SL", "T1", "T2", "RRR",
    "AI Verdict", "Confidence %", "Status", "Exit Price", "P&L %", "Notes",
]


# ── Parser ────────────────────────────────────────────────────────────────────

@dataclass
class GWCSignal:
    raw:        str          = ""
    date:       str          = ""
    time:       str          = ""
    ticker:     str          = ""
    exchange:   str          = "NFO"
    direction:  str          = ""       # BUY / SELL
    entry:      float        = 0.0
    add_more:   float        = 0.0      # averaging level
    sl:         float        = 0.0
    target1:    float        = 0.0
    target2:    float        = 0.0
    rrr:        float        = 0.0
    cost_exit:  bool         = False    # "Exit @cost" flag
    hero_zero:  bool         = False    # binary trade: no SL, all-or-nothing
    sl_auto:    bool         = False    # SL was computed by system, not given by GWC
    sl_method:  str          = ""      # how auto-SL was derived
    is_option:  bool         = False
    underlying: str          = ""
    strike:     float        = 0.0
    opt_type:   str          = ""       # CE / PE
    notes:      str          = ""


def _auto_sl(sig: "GWCSignal") -> tuple[float, str]:
    """
    Compute a system-derived SL when GWC doesn't provide one.

    Priority:
      1. Target known → back-calculate SL for RRR 1.5  (preserves upside)
      2. Option, no target → 50% of entry premium      (standard options rule)
      3. Equity/futures → 2% of entry price            (tight equity default)

    Returns (sl_price, method_label).
    """
    if sig.entry <= 0:
        return 0.0, ""

    best_target = sig.target2 if sig.target2 > 0 else sig.target1

    if best_target > 0:
        reward = abs(best_target - sig.entry)
        risk   = reward / 1.5           # RRR 1.5
        if sig.direction == "BUY":
            sl = max(sig.entry - risk, 1.0)
        else:
            sl = sig.entry + risk
        return round(sl, 1), "system (RRR 1.5 from target)"

    if sig.is_option:
        sl = max(sig.entry * 0.50, 1.0)
        return round(sl, 1), "system (50% premium rule)"

    sl = round(sig.entry * 0.98, 2)
    return sl, "system (2% entry rule)"


def _num(text: str, pattern: str) -> float:
    """Extract first number matching pattern. Returns 0 if not found."""
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return 0.0


def parse_gwc(text: str) -> Optional[GWCSignal]:
    """
    Parse a GWC WhatsApp signal into a GWCSignal dataclass.
    Returns None if the text doesn't look like a tradeable signal.
    """
    if not text or len(text) < 8:
        return None

    sig = GWCSignal(raw=text[:500])
    now = datetime.now()
    sig.date = now.strftime("%Y-%m-%d")
    sig.time = now.strftime("%H:%M")

    upper = text.upper()

    # Skip pure commentary / result-update lines (no trade action needed)
    commentary_markers = [
        "FROM HERE", "CAN HIT", "VOLATILE", "NO ONE SIDE",
        "TRADING BOTH SIDE", "HOPE REDUCED", "TRUMP", "BREAKING NEWS",
        "BOOK PROFITS", "DOUBLED", "WATCHLIST",
    ]
    if any(m in upper for m in commentary_markers) and not re.search(r'\bSL\b|\bSTOP\b', upper):
        return None

    # Skip pure update messages: "Till now 175 ✌️" without a buy/sell action
    if re.search(r'TILL\s+NOW\s+\d', upper) and not re.search(r'\b(BUY|SELL|LONG|SHORT)\b', upper):
        return None

    # Hero zero detection — GWC's binary expiry trade (no SL, all-or-nothing)
    if re.search(r'HERO\s*ZERO', upper):
        sig.hero_zero = True

    # Direction
    if re.search(r'\b(BUY|LONG|BULLISH)\b', upper):
        sig.direction = "BUY"
    elif re.search(r'\b(SELL|SHORT|BEARISH)\b', upper):
        sig.direction = "SELL"
    else:
        return None

    # ── Option detection ──────────────────────────────────────────────────────
    # Matches: NIFTY 23600CE, NIFTY23600PE, SENSEX 74500PE, LT 4000 CE, etc.
    opt = re.search(
        r'\b(NIFTY|BANKNIFTY|FINNIFTY|MIDCPNIFTY|SENSEX|'
        r'[A-Z]{2,10})\s*(\d{4,6})\s*(CE|PE)\b',
        upper
    )
    if opt:
        sig.is_option = True
        sig.underlying = opt.group(1)
        sig.strike     = float(opt.group(2))
        sig.opt_type   = opt.group(3)

        # Determine exchange
        index_names = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"}
        if sig.underlying in index_names:
            sig.exchange = "NFO"
            sig.ticker   = sig.underlying
        else:
            sig.exchange = "NFO"
            sig.ticker   = sig.underlying   # stock option

    else:
        # ── Equity / futures detection ────────────────────────────────────────
        equity = re.search(
            r'\b(NSE|MCX|CDS|BSE):([A-Z0-9_]+)\b', upper
        )
        if equity:
            sig.exchange = equity.group(1)
            sig.ticker   = equity.group(2)
        else:
            # Try bare ticker (e.g. "GOLD", "CRUDEOIL", "RELIANCE")
            skip = {
                "BUY", "SELL", "LONG", "SHORT", "SL", "TGT", "TRG",
                "TARGET", "STOP", "ALERT", "ENTRY", "AROUND", "AROUNDD",
                "MORE", "ADD", "AVG", "AVERAGE", "EXIT", "COST",
                "MICRO", "MINI", "POSITIONAL", "INTRADAY", "SWING",
            }
            words = re.findall(r'\b([A-Z][A-Z0-9]{2,19})\b', upper)
            for w in words:
                if w not in skip:
                    # Commodity keywords → MCX
                    if w in {"GOLD", "SILVER", "CRUDEOIL", "CRUDE", "NATURALGAS",
                             "COPPER", "ZINC", "ALUMINIUM", "NICKEL", "LEAD"}:
                        sig.exchange = "MCX"
                    sig.ticker = w
                    break

    if not sig.ticker:
        return None

    # ── Price extraction ──────────────────────────────────────────────────────
    clean = upper.replace(",", "").replace("₹", "").replace("RS.", "")
    # Expand "X lac/lakh" → actual rupee value before any number extraction.
    # "3 lac" → "300000", "2.5 lac" → "250000", "2.25 lac" → "225000"
    def _expand_lac(m: re.Match) -> str:
        return str(int(float(m.group(1)) * 100_000))
    clean = re.sub(r'(\d+\.?\d*)\s*(?:LAC|LAKH)S?\b', _expand_lac, clean)

    # Entry + add_more: handles "@125/75", "AROUND 80/50", "@55/40" formats.
    # The slash separates the initial entry from the averaging level — NOT two targets.
    entry_slash = re.search(
        r'(?:@|AROUND+)\s*(\d+\.?\d*)\s*/\s*(\d+\.?\d*)', clean
    )
    if entry_slash:
        try:
            sig.entry    = float(entry_slash.group(1))
            sig.add_more = float(entry_slash.group(2))
        except ValueError:
            pass

    if sig.entry == 0:
        # Plain: @X or ENTRY X (no slash)
        sig.entry = _num(clean, r'(?:@|ENTRY|AROUND+)\s*(\d+\.?\d*)')
    if sig.entry == 0:
        # "CAME 41" — GWC price-update shorthand
        sig.entry = _num(clean, r'CAME\s+(\d+\.?\d*)')
    if sig.entry == 0:
        sig.entry = _num(clean, r'(?:CE|PE)\s+(\d+\.?\d*)')
    if sig.entry == 0 and sig.exchange == "MCX":
        # Commodity signals often use bare prices without @ prefix:
        # "Sell silver micro 270000 sl 3 lac" → entry = 270000
        m_bare = re.search(r'\b(\d{4,7})\b', clean)
        if m_bare:
            sig.entry = float(m_bare.group(1))

    # Add more / averaging (explicit keyword, overrides slash-parsed value)
    explicit_add = _num(clean, r'ADD\s*(?:MORE)?\s*(?:@|AT)?\s*(\d+\.?\d*)')
    if explicit_add == 0:
        explicit_add = _num(clean, r'AVG(?:ERAGE)?\s*(?:@|AT)?\s*(\d+\.?\d*)')
    if explicit_add > 0:
        sig.add_more = explicit_add

    # Stop loss: SL X, STOP@X, STOP X
    sig.sl = _num(clean, r'(?:SL|STOP\s*@?|STOP\s+LOSS)\s*(\d+\.?\d*)')
    if sig.sl == 0:
        sig.sl = _num(clean, r'STOP@(\d+\.?\d*)')

    # Targets — only extract from explicit keywords (TGT / TRG / TARGET / T1 / TP)
    # Do NOT use the price-pairs fallback — it causes false matches when the
    # signal has patterns like "52/50" (entry range) or "175 & 200" that aren't targets.
    t1 = _num(clean, r'(?:TGT|TRG|TARGET)\s*(\d+\.?\d*)')
    if t1 == 0:
        t1 = _num(clean, r'(?:T1|TP1|PROFIT)\s*(\d+\.?\d*)')
    sig.target1 = t1

    # Second target — only from TGT/TRG/TARGET X & Y or X / Y
    t2_match = re.search(
        r'(?:TGT|TRG|TARGET)\s*\d+\.?\d*\s*[&/,]\s*(\d+\.?\d*)', clean
    )
    if t2_match:
        try:
            sig.target2 = float(t2_match.group(1))
        except ValueError:
            pass

    # ── Post-parse sanity checks ──────────────────────────────────────────────

    # If T1 == entry, the target number collided with the entry — discard T1.
    if sig.target1 > 0 and abs(sig.target1 - sig.entry) < 0.01:
        sig.target1 = 0.0

    # For BUY direction, targets must be above entry (option premium going up).
    # If T2 < entry it is likely a misidentified SL or random number — discard.
    if sig.direction == "BUY" and sig.target2 > 0 and sig.target2 <= sig.entry:
        if sig.sl == 0 and sig.target2 < sig.entry:
            sig.sl = sig.target2   # promote it to SL
        sig.target2 = 0.0
    if sig.direction == "BUY" and sig.target1 > 0 and sig.target1 <= sig.entry:
        sig.target1 = 0.0

    # Same for SELL direction — targets must be below entry.
    if sig.direction == "SELL" and sig.target1 > 0 and sig.target1 >= sig.entry > 0:
        sig.target1 = 0.0
    if sig.direction == "SELL" and sig.target2 > 0 and sig.target2 >= sig.entry > 0:
        sig.target2 = 0.0

    # "Exit @cost" flag
    if re.search(r'EXIT\s*@?\s*COST', upper):
        sig.cost_exit = True

    # Auto-SL: if GWC didn't provide one, derive it from the system rules
    if sig.sl == 0 and sig.entry > 0:
        auto_sl, auto_method = _auto_sl(sig)
        if auto_sl > 0:
            sig.sl        = auto_sl
            sig.sl_auto   = True
            sig.sl_method = auto_method

    # RRR — only compute when we have valid entry + SL + at least one target
    best_target = sig.target2 if sig.target2 > 0 else sig.target1
    if sig.entry > 0 and sig.sl > 0 and best_target > 0:
        risk   = abs(sig.entry - sig.sl)
        reward = abs(best_target - sig.entry)
        sig.rrr = round(reward / risk, 2) if risk > 0 else 0.0

    return sig


# ── Sheets logging ────────────────────────────────────────────────────────────

def log_to_sheets(
    sig: GWCSignal,
    verdict: str = "",
    confidence: int = 0,
    notes: str = "",
) -> bool:
    """Append a GWC signal row to the 'GWC TRACKER' Google Sheets tab."""
    try:
        from mcp_server.sheets_sync import _get_sheets_client, _get_or_create_worksheet
        _, sheet = _get_sheets_client()
        if not sheet:
            return False

        ws = _get_or_create_worksheet(
            sheet, "GWC TRACKER",
            cols=len(GWC_TRACKER_HEADERS),
            header=GWC_TRACKER_HEADERS,
        )

        t2_str    = str(sig.target2) if sig.target2 > 0 else ""
        cost_note  = " | EXIT@COST" if sig.cost_exit else ""
        hero_note  = " | HERO_ZERO" if sig.hero_zero else ""
        auto_note  = f" | SL:{sig.sl_method}" if sig.sl_auto else ""
        row = [
            sig.date,
            sig.time,
            "GWC",
            sig.ticker + (f" {int(sig.strike)}{sig.opt_type}" if sig.is_option else ""),
            sig.direction,
            sig.entry,
            sig.add_more if sig.add_more > 0 else "",
            sig.sl,
            sig.target1 if sig.target1 > 0 else "",
            t2_str,
            sig.rrr if sig.rrr > 0 else "",
            verdict,
            confidence if confidence > 0 else "",
            "OPEN",
            "",   # exit price — filled when outcome known
            "",   # P&L %
            notes + cost_note + hero_note + auto_note,
        ]
        ws.append_row(row)
        logger.info("GWC signal logged: %s %s entry=%.2f", sig.ticker, sig.direction, sig.entry)
        return True
    except Exception as exc:
        logger.warning("GWC sheet log failed: %s", exc)
        return False


def update_gwc_outcome(
    ticker: str,
    direction: str,
    signal_date: str,
    exit_price: float,
    status: str,       # "TARGET1", "TARGET2", "SL", "COST_EXIT", "OPEN"
) -> bool:
    """Update status + exit price + P&L on an existing GWC TRACKER row."""
    try:
        from mcp_server.sheets_sync import _get_sheets_client
        _, sheet = _get_sheets_client()
        if not sheet:
            return False

        ws = sheet.worksheet("GWC TRACKER")
        rows = ws.get_all_values()
        header = rows[0] if rows else []

        # Column indices
        try:
            col_date    = header.index("Date") + 1
            col_ticker  = header.index("Ticker") + 1
            col_dir     = header.index("Direction") + 1
            col_entry   = header.index("Entry") + 1
            col_status  = header.index("Status") + 1
            col_exit    = header.index("Exit Price") + 1
            col_pnl     = header.index("P&L %") + 1
        except ValueError:
            return False

        for i, row in enumerate(rows[1:], start=2):
            if (len(row) > max(col_date, col_ticker, col_dir) - 1
                    and row[col_date - 1] == signal_date
                    and ticker.upper() in row[col_ticker - 1].upper()
                    and row[col_dir - 1] == direction
                    and row[col_status - 1] == "OPEN"):
                try:
                    entry = float(row[col_entry - 1])
                    if entry > 0:
                        pnl = ((exit_price - entry) / entry * 100
                               if direction == "BUY"
                               else (entry - exit_price) / entry * 100)
                        ws.update_cell(i, col_status, status)
                        ws.update_cell(i, col_exit,   exit_price)
                        ws.update_cell(i, col_pnl,    round(pnl, 2))
                        logger.info(
                            "GWC outcome updated: %s %s → %s exit=%.2f pnl=%.1f%%",
                            ticker, direction, status, exit_price, pnl,
                        )
                        return True
                except (ValueError, IndexError):
                    pass

        return False
    except Exception as exc:
        logger.warning("GWC outcome update failed: %s", exc)
        return False


# ── Validation pipeline ───────────────────────────────────────────────────────

def validate_gwc_signal(sig: GWCSignal) -> dict:
    """
    Run the full debate validator on a GWC signal.
    Returns {"verdict": str, "confidence": int, "reasoning": str}.
    """
    if sig.entry <= 0 or sig.sl <= 0:
        return {"verdict": "SKIP", "confidence": 0,
                "reasoning": "Entry or SL missing — cannot validate."}

    best_target = sig.target2 if sig.target2 > 0 else sig.target1
    if best_target <= 0:
        return {"verdict": "SKIP", "confidence": 0,
                "reasoning": "Target missing — cannot compute RRR."}

    try:
        from mcp_server.debate_validator import run_debate
        from mcp_server.db import SessionLocal
        from mcp_server.models import MWAScore

        mwa_direction = "UNKNOWN"
        try:
            db = SessionLocal()
            mwa = db.query(MWAScore).order_by(MWAScore.score_date.desc()).first()
            if mwa:
                mwa_direction = mwa.direction or "UNKNOWN"
            db.close()
        except Exception:
            pass

        pattern = (f"GWC: {sig.underlying}{int(sig.strike)}{sig.opt_type}"
                   if sig.is_option else "GWC: External Signal")

        result = run_debate(
            ticker=sig.ticker,
            direction="LONG" if sig.direction == "BUY" else "SHORT",
            pattern=pattern,
            rrr=sig.rrr,
            entry_price=sig.entry,
            stop_loss=sig.sl,
            target=best_target,
            mwa_direction=mwa_direction,
            scanner_count=0,
            tv_confirmed=False,
            sector_strength="NEUTRAL",
            fii_net=0,
            delivery_pct=0,
            confidence_boosts=["GWC Office signal", f"RRR {sig.rrr:.1f}"] if sig.rrr >= 1.5 else [],
            pre_confidence=45,
        )
        return {
            "verdict":    result.recommendation,
            "confidence": result.final_confidence,
            "reasoning":  result.reasoning,
        }
    except Exception as exc:
        logger.warning("GWC debate validation failed: %s", exc)
        return {"verdict": "REVIEW", "confidence": 50,
                "reasoning": f"Debate unavailable: {exc}"}


# ── Format Telegram reply ─────────────────────────────────────────────────────

def format_gwc_reply(sig: GWCSignal, validation: dict) -> str:
    """Build the Telegram reply card for a GWC signal."""
    sep = "━" * 24
    verdict    = validation.get("verdict", "REVIEW")
    confidence = validation.get("confidence", 0)
    reasoning  = validation.get("reasoning", "")

    verdict_emoji = {"TAKE": "✅", "SKIP": "🔴", "REVIEW": "🟡"}.get(verdict, "🟡")
    rrr_flag = "✅" if sig.rrr >= 2.0 else "⚠️" if sig.rrr >= 1.0 else "❌"

    t2_line  = f" | T2: ₹{sig.target2:.1f}" if sig.target2 > 0 else ""
    add_line = f"\nAdd More: ₹{sig.add_more:.1f}" if sig.add_more > 0 else ""
    cost_line = "\n⚠️ Exit @Cost protection advised" if sig.cost_exit else ""
    if sig.sl > 0 and sig.sl_auto:
        sl_str = f"₹{sig.sl:.1f} 🤖 ({sig.sl_method})"
    elif sig.sl > 0:
        sl_str = f"₹{sig.sl:.1f}"
    else:
        sl_str = "₹— (missing)"
    t1_str   = f"₹{sig.target1:.1f}" if sig.target1 > 0 else "₹—"
    rrr_str  = f"{sig.rrr:.2f} {rrr_flag}" if sig.rrr > 0 else f"— {rrr_flag}"

    # Warn only when critical fields are genuinely absent
    warnings: list[str] = []
    if sig.entry == 0:
        warnings.append("⚠️ Entry price not found — resend with @ price")
    if sig.target1 == 0:
        warnings.append("ℹ️ No target in signal — add TGT X for better RRR")

    hero_line = "\n🎲 HERO ZERO — binary trade (no SL, expires worthless or wins big)" if sig.hero_zero else ""

    lines = [
        "📲 GWC Signal Tracker",
        sep,
        f"Ticker: {sig.ticker}" + (f" {int(sig.strike)}{sig.opt_type}" if sig.is_option else ""),
        f"Direction: {'🟢 BUY' if sig.direction == 'BUY' else '🔴 SELL'}",
        hero_line,
        sep,
        f"Entry: ₹{sig.entry:.1f}{add_line}" if sig.entry > 0 else "Entry: ₹— (not found)",
        f"SL: {sl_str} | T1: {t1_str}{t2_line}",
        f"RRR: {rrr_str}",
        cost_line,
        "\n".join(warnings) if warnings else "",
        sep,
        f"{verdict_emoji} Verdict: {verdict} ({confidence}%)",
    ]
    if reasoning:
        # Trim to 2 sentences for Telegram
        short = ". ".join(reasoning.split(". ")[:2]) + "."
        lines.append(f"💬 {short}")
    lines += [
        sep,
        "✅ Logged to GWC TRACKER sheet",
    ]
    return "\n".join(line for line in lines if line)


# ── Message classifier ────────────────────────────────────────────────────────

class GWCMessageType(enum.Enum):
    SIGNAL      = "SIGNAL"       # tradeable: BUY/SELL + option/ticker
    RESULT      = "RESULT"       # "Till now 175", "Target hit", price+emoji
    UPDATE      = "UPDATE"       # SL moved, new level for existing trade
    MARKET_CALL = "MARKET_CALL"  # directional view without an entry
    COMMENTARY  = "COMMENTARY"   # analysis, opinion
    NEWS        = "NEWS"         # external event (Trump, RBI, etc.)


GWC_LOG_HEADERS = [
    "Date", "Time", "Type", "Raw Message", "Ticker",
    "Key Numbers", "Linked Signal", "Notes",
]


def split_gwc_signals(text: str) -> list[str]:
    """
    Split a multi-signal GWC message into individual signal texts.

    Handles patterns like:
      "Buy banknifty 53000pe @525 sl 450 tgt 600\nAgain Buy nifty 23500pe @165 sl 140 tgt 200"
      "Buy crude @200 sl 180 tgt 220\nBuy gold @71000 sl 70500 tgt 72000"

    Returns a list with one element per signal (minimum one element = original text).
    """
    # Sentence-start keywords that indicate a new signal
    _SEP = re.compile(
        r'(?:^|\n)\s*(?:AGAIN\s+)?(?:BUY|SELL|LONG|SHORT|ALERT\s*:?)\s+',
        re.IGNORECASE | re.MULTILINE,
    )
    parts: list[str] = []
    matches = list(_SEP.finditer(text))
    if len(matches) <= 1:
        return [text.strip()]
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        segment = text[m.start():end].strip()
        if segment:
            parts.append(segment)
    return parts if parts else [text.strip()]


def classify_gwc_message(text: str) -> tuple[GWCMessageType, dict]:
    """
    Classify a raw GWC forwarded message.
    Returns (GWCMessageType, extracted_data_dict).
    extracted_data may contain: ticker, direction, entry, price, levels.
    """
    if not text or len(text) < 3:
        return GWCMessageType.COMMENTARY, {}

    upper = text.upper().strip()
    extracted: dict = {}

    # ── RESULT patterns ───────────────────────────────────────────────────────

    till_now = re.search(r'TILL\s+NOW\s+(\d+\.?\d*)', upper)
    if till_now:
        extracted["price"] = float(till_now.group(1))
        extracted["type"]  = "till_now"
        return GWCMessageType.RESULT, extracted

    if re.search(r'TARGET\s+(?:HIT|ACHIEVED|DONE|COMPLETE[D]?)', upper):
        nums = re.findall(r'\b(\d{2,6}\.?\d*)\b', upper)
        if nums:
            extracted["price"] = float(nums[-1])
        extracted["type"] = "target_hit"
        return GWCMessageType.RESULT, extracted

    if re.search(r'\b(?:BOOK(?:ED)?|PROFIT\s+BOOK)', upper):
        nums = re.findall(r'\b(\d{2,6}\.?\d*)\b', upper)
        if nums:
            extracted["price"] = float(nums[-1])
        extracted["type"] = "profit_book"
        return GWCMessageType.RESULT, extracted

    # Line is just digits + win-emoji (e.g. "250 ✌️" or "175 🎯")
    if re.match(r'^\s*\d+\.?\d*\s*[\U0001F300-\U0001FFFF✌🎯✅💰🔥👍⭐🏆]+\s*$', text):
        m = re.search(r'(\d+\.?\d*)', text)
        if m:
            extracted["price"] = float(m.group(1))
        extracted["type"] = "price_emoji"
        return GWCMessageType.RESULT, extracted

    # ── SIGNAL — try parse_gwc() as ground truth ─────────────────────────────

    has_direction = bool(re.search(r'\b(BUY|SELL|LONG|SHORT)\b', upper))
    has_option    = bool(re.search(
        r'\b(?:NIFTY|BANKNIFTY|FINNIFTY|MIDCPNIFTY|SENSEX|[A-Z]{2,10})\s*\d{4,6}\s*(?:CE|PE)\b',
        upper,
    ))
    has_entry_hint = bool(re.search(r'(?:@|AROUND+|ENTRY)\s*\d+', upper))
    # Commodity/equity signals often have bare entry prices without @ prefix:
    # "Sell silver micro 270000 sl 3 lac" — detect instrument name + large number
    has_commodity  = bool(re.search(
        r'\b(?:GOLD|SILVER|CRUDE|NATURALGAS|COPPER|ZINC|ALUMINIUM|'
        r'SILVER\s*MICRO|GOLD\s*MINI|CRUDEOIL)\b',
        upper,
    ))
    # Bare 4-6 digit number after direction word counts as entry hint
    has_bare_price = bool(re.search(r'\b(?:BUY|SELL|LONG|SHORT)\b.*?\b\d{4,6}\b', upper))

    if has_direction and (has_option or has_entry_hint or has_commodity or has_bare_price):
        sig = parse_gwc(text)
        if sig is not None:
            extracted["ticker"]    = sig.ticker
            extracted["direction"] = sig.direction
            extracted["entry"]     = sig.entry
            return GWCMessageType.SIGNAL, extracted

    # ── UPDATE — SL moved, level change ──────────────────────────────────────

    if re.search(r'(?:STOP|SL)\s+(?:NOW|MOVE[DS]?|TRAIL)', upper):
        m = re.search(r'(\d+\.?\d*)', upper)
        if m:
            extracted["price"] = float(m.group(1))
        extracted["type"] = "sl_update"
        return GWCMessageType.UPDATE, extracted

    # ── MARKET_CALL — view without an explicit entry ──────────────────────────

    market_call_pats = [
        r'CAN\s+HIT', r'WILL\s+HIT', r'LIKELY\s+TO', r'EXPECTING',
        r'FROM\s+HERE', r'WATCHLIST', r'WATCH\s+FOR', r'NO\s+ONE\s+SIDE',
        r'TRADING\s+BOTH', r'VOLATILE', r'RANGE\s+BOUND',
    ]
    if any(re.search(p, upper) for p in market_call_pats):
        nums = re.findall(r'\b(\d{4,6})\b', upper)
        if nums:
            extracted["levels"] = [float(n) for n in nums[:4]]
        return GWCMessageType.MARKET_CALL, extracted

    # ── NEWS — external events ────────────────────────────────────────────────

    news_kws = [
        "TRUMP", "FOMC", "RBI", "FED", "OPEC", "GDP", "CPI", "INFLATION",
        "BREAKING", "BUDGET", "ELECTION", "WAR", "CEASEFIRE",
    ]
    if any(kw in upper for kw in news_kws):
        return GWCMessageType.NEWS, extracted

    return GWCMessageType.COMMENTARY, extracted


def log_raw_to_sheets(
    text: str,
    msg_type: GWCMessageType,
    extracted: dict,
    linked_signal: str = "",
    notes: str = "",
) -> bool:
    """Append a raw GWC message to the 'GWC LOG' Google Sheets tab."""
    try:
        from mcp_server.sheets_sync import _get_sheets_client, _get_or_create_worksheet
        _, sheet = _get_sheets_client()
        if not sheet:
            return False

        ws = _get_or_create_worksheet(
            sheet, "GWC LOG",
            cols=len(GWC_LOG_HEADERS),
            header=GWC_LOG_HEADERS,
        )

        now       = datetime.now()
        ticker    = extracted.get("ticker", "")
        price     = extracted.get("price", "")
        levels    = extracted.get("levels", [])
        key_nums  = (str(price) if price
                     else ", ".join(str(int(lv)) for lv in levels) if levels
                     else "")

        row = [
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M"),
            msg_type.value,
            text[:300],
            ticker,
            key_nums,
            linked_signal,
            notes,
        ]
        ws.append_row(row)
        logger.info("GWC LOG: %s — %s", msg_type.value, text[:60])
        return True
    except Exception as exc:
        logger.warning("GWC LOG sheet failed: %s", exc)
        return False


def _extract_underlying(text: str) -> str:
    """Extract the underlying instrument name from a GWC message."""
    upper = text.upper()
    # Order matters: BANKNIFTY/FINNIFTY before NIFTY (substring collision)
    for name in (
        "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTY",
        "SENSEX", "BANKEX",
        "CRUDEOIL", "NATURALGAS", "GOLD", "SILVER",
        "COPPER", "ZINC", "ALUMINIUM",
    ):
        if name in upper:
            return name
    # Stock ticker before CE/PE strike (e.g. "LT 4000 CE")
    m = re.search(r'\b([A-Z]{2,10})\s*\d{4,6}\s*(?:CE|PE)\b', upper)
    if m:
        return m.group(1)
    return ""


def link_gwc_outcome_from_message(
    text: str,
    extracted: dict,
    as_of_date: Optional[date] = None,
) -> str:
    """
    For a RESULT message, find the open GWC TRACKER row and update its status.
    Returns a human-readable description of the match, or "" if no match found.

    as_of_date anchors the 2-day search window (default: today). Pass the LOG
    row's date when running a historical backfill.
    """
    price      = extracted.get("price", 0)
    res_type   = extracted.get("type", "")
    msg_ticker = _extract_underlying(text)

    if not price and not msg_ticker:
        return ""

    ref_date    = as_of_date or date.today()
    yesterday   = ref_date - timedelta(days=1)
    valid_dates = {ref_date.strftime("%Y-%m-%d"), yesterday.strftime("%Y-%m-%d")}

    try:
        from mcp_server.sheets_sync import _get_sheets_client
        _, sheet = _get_sheets_client()
        if not sheet:
            return ""

        ws   = sheet.worksheet("GWC TRACKER")
        rows = ws.get_all_values()
        if not rows:
            return ""

        header = rows[0]
        try:
            col_date   = header.index("Date")       + 1
            col_ticker = header.index("Ticker")     + 1
            col_dir    = header.index("Direction")  + 1
            col_entry  = header.index("Entry")      + 1
            col_t1     = header.index("T1")         + 1
            col_t2     = header.index("T2")         + 1
            col_status = header.index("Status")     + 1
            col_exit   = header.index("Exit Price") + 1
            col_notes  = header.index("Notes")      + 1
        except ValueError:
            return ""

        col_pnl = header.index("P&L %") + 1 if "P&L %" in header else 0

        for i, row in enumerate(rows[1:], start=2):
            needed = max(col_date, col_ticker, col_t1, col_t2, col_status, col_notes)
            if len(row) < needed:
                continue
            if row[col_status - 1] != "OPEN":
                continue
            if row[col_date - 1] not in valid_dates:
                continue

            # Skip embedded-signal placeholders to avoid circular false-positives
            notes_cell = row[col_notes - 1] if len(row) >= col_notes else ""
            if "[embedded in result message]" in notes_cell.lower():
                continue

            row_ticker = row[col_ticker - 1].upper()
            # Ticker pre-filter: skip rows that clearly belong to a different instrument
            if msg_ticker and row_ticker:
                if msg_ticker not in row_ticker and row_ticker not in msg_ticker:
                    continue

            direction = row[col_dir - 1].upper() if len(row) >= col_dir else ""

            try:
                t1    = float(row[col_t1 - 1])    if row[col_t1 - 1]                              else 0.0
                t2    = float(row[col_t2 - 1])    if row[col_t2 - 1]                              else 0.0
                entry = float(row[col_entry - 1]) if len(row) >= col_entry and row[col_entry - 1] else 0.0
            except ValueError:
                continue

            matched = ""
            pnl_pct = ""

            if price:
                is_buy = direction in ("BUY", "LONG")
                # Generous ±5% window: "price close to T1" counts as a hit
                if t1 > 0:
                    hit = (price >= t1 * 0.95) if is_buy else (price <= t1 * 1.05)
                    if hit:
                        matched = "TARGET1"
                if not matched and t2 > 0:
                    hit = (price >= t2 * 0.95) if is_buy else (price <= t2 * 1.05)
                    if hit:
                        matched = "TARGET2"

                if matched and entry > 0:
                    pnl_pct = (
                        f"{(price - entry) / entry * 100:.1f}"
                        if is_buy
                        else f"{(entry - price) / entry * 100:.1f}"
                    )
            else:
                # No price extracted: link by ticker + explicit target-hit keyword
                if res_type in ("target_hit", "profit_book") and msg_ticker:
                    matched = "TARGET1"

            if matched:
                ticker = row[col_ticker - 1]
                ws.update_cell(i, col_status, matched)
                if price:
                    ws.update_cell(i, col_exit, price)
                if pnl_pct and col_pnl:
                    ws.update_cell(i, col_pnl, pnl_pct)
                logger.info(
                    "GWC auto-linked: %s %s -> %s (price=%.1f pnl=%s%%)",
                    ticker, direction, matched, price or 0, pnl_pct or "?",
                )
                desc = f"{ticker} {direction} -> {matched}"
                if pnl_pct:
                    desc += f" ({pnl_pct}%)"
                return desc

        return ""
    except Exception as exc:
        logger.warning("GWC outcome auto-link failed: %s", exc)
        return ""


def get_gwc_learn_insights() -> str:
    """
    Pull GWC LOG + GWC TRACKER data and return a pattern summary string
    suitable for a Telegram message.
    """
    try:
        from mcp_server.sheets_sync import _get_sheets_client
        _, sheet = _get_sheets_client()
        if not sheet:
            return "❌ Google Sheets not connected."

        try:
            log_ws   = sheet.worksheet("GWC LOG")
            log_rows = log_ws.get_all_values()
        except Exception:
            return "ℹ️ GWC LOG tab not found yet. Forward some messages first."

        if len(log_rows) <= 1:
            return "ℹ️ GWC LOG is empty. Forward some GWC messages first."

        header = log_rows[0]
        data   = log_rows[1:]

        try:
            col_type   = header.index("Type")
            col_time   = header.index("Time")
            col_ticker = header.index("Ticker")
            col_linked = header.index("Linked Signal")
        except ValueError:
            return "❌ GWC LOG header mismatch — re-forward a message to rebuild headers."

        type_counts = Counter(
            row[col_type] for row in data if len(row) > col_type and row[col_type]
        )

        signal_times = [
            row[col_time] for row in data
            if len(row) > col_time and row[col_type] == "SIGNAL"
        ]

        tickers = [
            row[col_ticker] for row in data
            if len(row) > col_ticker and row[col_ticker]
        ]
        ticker_counts = Counter(tickers)

        linked_count    = sum(1 for row in data if len(row) > col_linked and row[col_linked])
        total_signals   = type_counts.get("SIGNAL", 0)
        total_results   = type_counts.get("RESULT", 0)

        lines = [
            "📊 GWC Pattern Insights",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            f"Total messages: {len(data)}",
            "",
            "By Type:",
        ]
        for t, c in type_counts.most_common():
            lines.append(f"  {t}: {c}")

        if signal_times:
            lines += [
                "",
                f"Signal Timing ({len(signal_times)} signals):",
                f"  First: {min(signal_times)}  Last: {max(signal_times)}",
            ]

        if ticker_counts:
            lines += ["", "Top Tickers:"]
            for t, c in ticker_counts.most_common(6):
                lines.append(f"  {t}: {c}x")

        if total_results > 0:
            link_rate = linked_count / total_results * 100
            lines += [
                "",
                "Result Auto-Linking:",
                f"  Results received : {total_results}",
                f"  Matched to signal: {linked_count} ({link_rate:.0f}%)",
            ]

        # ── TRACKER actual outcomes ────────────────────────────────────────────
        try:
            tracker_ws   = sheet.worksheet("GWC TRACKER")
            tracker_rows = tracker_ws.get_all_values()
            if len(tracker_rows) > 1:
                t_header = tracker_rows[0]
                t_data   = tracker_rows[1:]
                t_col_status = t_header.index("Status") if "Status" in t_header else -1
                t_col_pnl    = t_header.index("P&L %")  if "P&L %"  in t_header else -1

                if t_col_status >= 0:
                    status_counts = Counter(
                        row[t_col_status] for row in t_data
                        if len(row) > t_col_status and row[t_col_status]
                    )
                    wins   = status_counts.get("TARGET1", 0) + status_counts.get("TARGET2", 0)
                    losses = status_counts.get("SL_HIT",  0) + status_counts.get("EXPIRED", 0)
                    open_  = status_counts.get("OPEN",    0)
                    closed = wins + losses

                    pnl_vals: list[float] = []
                    if t_col_pnl >= 0:
                        for row in t_data:
                            if len(row) > t_col_pnl and row[t_col_pnl]:
                                try:
                                    pnl_vals.append(float(row[t_col_pnl]))
                                except ValueError:
                                    pass

                    lines += ["", "GWC TRACKER Outcomes:"]
                    lines.append(f"  Win  (T1/T2): {wins}")
                    lines.append(f"  Loss (SL/Exp): {losses}")
                    lines.append(f"  Open: {open_}")
                    if closed > 0:
                        real_wr = wins / closed * 100
                        lines.append(f"  Real Win Rate: {real_wr:.0f}%  ({wins}/{closed} closed)")
                    else:
                        lines.append("  Real Win Rate: n/a (no closed trades yet)")
                    if pnl_vals:
                        avg_pnl = sum(pnl_vals) / len(pnl_vals)
                        lines.append(f"  Avg P&L %: {avg_pnl:.1f}%")
        except Exception:
            pass  # TRACKER tab may not exist yet

        lines += [
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            "💡 Forward more messages to grow the dataset.",
        ]
        return "\n".join(lines)

    except Exception as exc:
        logger.warning("GWC learn insights failed: %s", exc)
        return f"❌ Analysis error: {exc}"
