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

import logging
import re
from dataclasses import dataclass
from datetime import datetime
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
