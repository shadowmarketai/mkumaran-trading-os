"""
F&O Analytics Auto-Monitor — background task for index F&O analytics.

Periodically polls IV rank, OI buildup, PCR, max-pain and expiry status for
the major index symbols (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY) during
F&O market hours and fires Telegram alerts ON TRANSITIONS only.

The previous design exposed these signals only via manual GET endpoints
(/api/fno/snapshot/NIFTY, /api/fno/iv_rank/NIFTY, ...). This monitor brings
them to parity with the MWA scanner — no manual polling required.

Transitions tracked per symbol:
  - IV rank crosses 80   → SHORT_VOLATILITY alert (sell premium edge)
  - IV rank crosses 20   → LONG_VOLATILITY alert (cheap premium edge)
  - PCR crosses 1.30     → BULLISH sentiment alert
  - PCR crosses 0.70     → BEARISH sentiment alert
  - OI significance      → transition out of NEUTRAL/UNAVAILABLE
  - Max-pain shift > 100 → strike re-anchor alert
  - Expiry day           → fired once on the morning of expiry

Alerts are de-duplicated via a JSON state file at
``data/fno_analytics_state.json`` so a server restart never floods the
Telegram channel with stale repeats.

Runs every 5 minutes during F&O hours (09:15-15:30 IST). Outside those
hours the loop sleeps and skips work — no Kite calls, no spam.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from mcp_server.config import settings
from mcp_server.market_calendar import is_market_open, now_ist

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────
MONITOR_INTERVAL = 300  # 5 minutes
INDEX_SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
STATE_FILE = Path("data/fno_analytics_state.json")

# IV rank thresholds
IV_RANK_HIGH = 80.0
IV_RANK_LOW = 20.0

# PCR thresholds
PCR_BULLISH = 1.30
PCR_BEARISH = 0.70

# Max-pain shift threshold (points)
MAX_PAIN_SHIFT = 100.0

# OI buildup transitions worth alerting on (avoid noise from FLAT/UNAVAILABLE)
ALERTABLE_OI_STATES = {"BULLISH", "BEARISH"}


# ── State persistence ────────────────────────────────────────────
def _load_state() -> dict[str, Any]:
    """Load previous monitor state from disk. Returns {} on first run / corruption."""
    try:
        if STATE_FILE.exists():
            with STATE_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception as e:
        logger.warning("F&O state load failed (%s) — starting fresh", e)
    return {}


def _save_state(state: dict[str, Any]) -> None:
    """Persist monitor state to disk. Non-fatal on failure."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with STATE_FILE.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        logger.warning("F&O state save failed: %s", e)


# ── Kite helper ──────────────────────────────────────────────────
def _get_kite_for_fo():
    """Return active Kite client from data provider, or None if not connected."""
    try:
        from mcp_server.data_provider import get_provider
        provider = get_provider()
        if hasattr(provider, "kite") and provider.kite:
            return getattr(provider.kite, "kite", None) or getattr(provider.kite, "client", None)
    except Exception as e:
        logger.debug("Kite unavailable for F&O analytics monitor: %s", e)
    return None


# ── Per-symbol checks ────────────────────────────────────────────
def _check_iv_rank_transitions(
    symbol: str,
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Detect IV-rank crossings (above 80 or below 20)."""
    alerts: list[dict[str, Any]] = []
    if current.get("status") != "LIVE":
        return alerts

    cur_rank = float(current.get("iv_rank") or 0)
    prev_rank = float((previous or {}).get("iv_rank") or 0) if previous else None

    # First-run alerts: only fire if extreme on first observation
    if prev_rank is None:
        if cur_rank >= IV_RANK_HIGH:
            alerts.append({
                "type": "IV_RANK_HIGH",
                "symbol": symbol,
                "iv_rank": cur_rank,
                "current_iv": current.get("current_iv"),
                "atm_strike": current.get("atm_strike"),
                "rationale": f"IV rank {cur_rank:.0f}% — expensive premium, sell edge",
            })
        elif cur_rank > 0 and cur_rank <= IV_RANK_LOW:
            alerts.append({
                "type": "IV_RANK_LOW",
                "symbol": symbol,
                "iv_rank": cur_rank,
                "current_iv": current.get("current_iv"),
                "atm_strike": current.get("atm_strike"),
                "rationale": f"IV rank {cur_rank:.0f}% — cheap premium, buy edge",
            })
        return alerts

    # Transition alerts: only fire on the cycle that crosses the threshold
    if prev_rank < IV_RANK_HIGH <= cur_rank:
        alerts.append({
            "type": "IV_RANK_HIGH",
            "symbol": symbol,
            "iv_rank": cur_rank,
            "previous_rank": prev_rank,
            "current_iv": current.get("current_iv"),
            "atm_strike": current.get("atm_strike"),
            "rationale": (
                f"IV rank crossed above {IV_RANK_HIGH:.0f} "
                f"({prev_rank:.0f}% → {cur_rank:.0f}%) — sell premium"
            ),
        })
    elif prev_rank > IV_RANK_LOW >= cur_rank > 0:
        alerts.append({
            "type": "IV_RANK_LOW",
            "symbol": symbol,
            "iv_rank": cur_rank,
            "previous_rank": prev_rank,
            "current_iv": current.get("current_iv"),
            "atm_strike": current.get("atm_strike"),
            "rationale": (
                f"IV rank crossed below {IV_RANK_LOW:.0f} "
                f"({prev_rank:.0f}% → {cur_rank:.0f}%) — buy premium"
            ),
        })

    return alerts


def _check_pcr_transitions(
    symbol: str,
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Detect PCR sentiment crossings."""
    alerts: list[dict[str, Any]] = []
    if current.get("status") != "LIVE":
        return alerts

    cur_pcr = float(current.get("pcr") or 0)
    prev_pcr = float((previous or {}).get("pcr") or 0) if previous else None

    if cur_pcr <= 0:
        return alerts

    if prev_pcr is None or prev_pcr <= 0:
        if cur_pcr >= PCR_BULLISH:
            alerts.append({
                "type": "PCR_BULLISH",
                "symbol": symbol,
                "pcr": cur_pcr,
                "rationale": f"PCR {cur_pcr:.2f} — bullish (puts > calls)",
            })
        elif cur_pcr <= PCR_BEARISH:
            alerts.append({
                "type": "PCR_BEARISH",
                "symbol": symbol,
                "pcr": cur_pcr,
                "rationale": f"PCR {cur_pcr:.2f} — bearish (calls > puts)",
            })
        return alerts

    if prev_pcr < PCR_BULLISH <= cur_pcr:
        alerts.append({
            "type": "PCR_BULLISH",
            "symbol": symbol,
            "pcr": cur_pcr,
            "previous_pcr": prev_pcr,
            "rationale": f"PCR crossed above {PCR_BULLISH:.2f} ({prev_pcr:.2f} → {cur_pcr:.2f})",
        })
    elif prev_pcr > PCR_BEARISH >= cur_pcr:
        alerts.append({
            "type": "PCR_BEARISH",
            "symbol": symbol,
            "pcr": cur_pcr,
            "previous_pcr": prev_pcr,
            "rationale": f"PCR crossed below {PCR_BEARISH:.2f} ({prev_pcr:.2f} → {cur_pcr:.2f})",
        })

    return alerts


def _check_oi_transitions(
    symbol: str,
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Detect OI buildup significance + max-pain shift."""
    alerts: list[dict[str, Any]] = []
    if current.get("status") != "LIVE":
        return alerts

    cur_sig = current.get("significance")
    prev_sig = (previous or {}).get("significance") if previous else None

    # Significance transition (NEUTRAL/None → BULLISH/BEARISH)
    if cur_sig in ALERTABLE_OI_STATES and cur_sig != prev_sig:
        alerts.append({
            "type": f"OI_{cur_sig}",
            "symbol": symbol,
            "significance": cur_sig,
            "previous_significance": prev_sig or "—",
            "net_oi": current.get("net_oi"),
            "call_oi": current.get("call_oi_total"),
            "put_oi": current.get("put_oi_total"),
            "max_pain": current.get("max_pain_strike"),
            "rationale": f"OI buildup turned {cur_sig} (was {prev_sig or 'neutral'})",
        })

    # Max-pain shift
    cur_mp = float(current.get("max_pain_strike") or 0)
    prev_mp = float((previous or {}).get("max_pain_strike") or 0) if previous else 0
    if prev_mp > 0 and cur_mp > 0 and abs(cur_mp - prev_mp) >= MAX_PAIN_SHIFT:
        direction = "up" if cur_mp > prev_mp else "down"
        alerts.append({
            "type": "MAX_PAIN_SHIFT",
            "symbol": symbol,
            "max_pain": cur_mp,
            "previous_max_pain": prev_mp,
            "shift_points": round(cur_mp - prev_mp, 1),
            "rationale": f"Max-pain shifted {direction} {prev_mp:.0f} → {cur_mp:.0f}",
        })

    return alerts


def _check_expiry(
    symbol: str,
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Fire one expiry-day alert per symbol per day."""
    alerts: list[dict[str, Any]] = []
    if not current.get("is_expiry_day"):
        return alerts

    today = current.get("today")
    last_alerted_date = (previous or {}).get("expiry_alerted_date")
    if last_alerted_date == today:
        return alerts

    alerts.append({
        "type": "EXPIRY_DAY",
        "symbol": symbol,
        "weekday": current.get("weekday"),
        "trading_advice": current.get("trading_advice"),
        "rationale": (
            f"Today is {symbol} weekly expiry — manage open positions, avoid fresh entries"
        ),
    })
    return alerts


# ── Snapshot collection ──────────────────────────────────────────
def _collect_symbol_snapshot(kite, symbol: str) -> dict[str, Any]:
    """
    Pull the four data points we monitor for one symbol.

    Always returns a dict (even on partial failure) so transition logic can
    safely diff against previous state.
    """
    from mcp_server.fo_module import (
        get_iv_rank,
        get_oi_change,
        get_pcr,
        is_expiry_day,
    )

    out: dict[str, Any] = {"symbol": symbol, "ts": now_ist().isoformat()}

    try:
        out["iv_rank"] = get_iv_rank(kite, symbol)
    except Exception as e:
        logger.debug("iv_rank %s failed: %s", symbol, e)
        out["iv_rank"] = {"status": "ERROR", "message": str(e)}

    try:
        out["pcr"] = get_pcr(kite, symbol)
    except Exception as e:
        logger.debug("pcr %s failed: %s", symbol, e)
        out["pcr"] = {"status": "ERROR", "message": str(e)}

    try:
        out["oi"] = get_oi_change(kite, symbol)
    except Exception as e:
        logger.debug("oi %s failed: %s", symbol, e)
        out["oi"] = {"status": "ERROR", "message": str(e)}

    try:
        out["expiry"] = is_expiry_day(kite, symbol)
    except Exception as e:
        logger.debug("expiry %s failed: %s", symbol, e)
        out["expiry"] = {"is_expiry_day": False, "message": str(e)}

    return out


def check_fno_analytics_once() -> dict[str, Any]:
    """
    Run one F&O analytics cycle for all index symbols.

    This is the synchronous core — usable from a manual endpoint.
    Returns a dict with `alerts` (list) and `snapshots` (per-symbol).
    """
    kite = _get_kite_for_fo()
    if kite is None:
        logger.debug("F&O analytics: Kite not connected — skipping")
        return {"status": "skipped", "reason": "kite_not_connected", "alerts": []}

    state = _load_state()
    snapshots: dict[str, Any] = {}
    all_alerts: list[dict[str, Any]] = []

    for symbol in INDEX_SYMBOLS:
        try:
            snap = _collect_symbol_snapshot(kite, symbol)
            snapshots[symbol] = snap
            previous = state.get(symbol, {})

            alerts: list[dict[str, Any]] = []
            alerts.extend(_check_iv_rank_transitions(symbol, snap["iv_rank"], previous.get("iv_rank")))
            alerts.extend(_check_pcr_transitions(symbol, snap["pcr"], previous.get("pcr")))
            alerts.extend(_check_oi_transitions(symbol, snap["oi"], previous.get("oi")))
            alerts.extend(_check_expiry(symbol, snap["expiry"], previous))

            all_alerts.extend(alerts)

            # Save fresh state for next cycle
            new_sym_state: dict[str, Any] = {
                "iv_rank": snap["iv_rank"],
                "pcr": snap["pcr"],
                "oi": snap["oi"],
                "expiry_alerted_date": (
                    snap["expiry"].get("today")
                    if any(a["type"] == "EXPIRY_DAY" for a in alerts)
                    else previous.get("expiry_alerted_date")
                ),
                "last_check": snap["ts"],
            }
            state[symbol] = new_sym_state
        except Exception as e:
            logger.error("F&O analytics check failed for %s: %s", symbol, e)

    state["_last_run"] = now_ist().isoformat()
    _save_state(state)

    return {
        "status": "ok",
        "ran_at": state["_last_run"],
        "alerts": all_alerts,
        "snapshots": snapshots,
    }


# ── Telegram formatter ───────────────────────────────────────────
_ALERT_EMOJI = {
    "IV_RANK_HIGH": "\U0001f4c8",   # 📈
    "IV_RANK_LOW": "\U0001f4c9",    # 📉
    "PCR_BULLISH": "\U0001f7e2",    # 🟢
    "PCR_BEARISH": "\U0001f534",    # 🔴
    "OI_BULLISH": "\U0001f4a5",     # 💥
    "OI_BEARISH": "\U0001f4a5",     # 💥
    "MAX_PAIN_SHIFT": "\U0001f3af", # 🎯
    "EXPIRY_DAY": "\u26a0\ufe0f",   # ⚠️
}


def format_alert(alert: dict[str, Any]) -> str:
    """Convert one alert dict into a Telegram-ready text card."""
    a_type = alert.get("type", "UNKNOWN")
    emoji = _ALERT_EMOJI.get(a_type, "\U0001f514")  # 🔔
    symbol = alert.get("symbol", "—")
    rationale = alert.get("rationale", "")

    sep = "\u2501" * 24

    lines = [f"{emoji} F&O Alert — {a_type.replace('_', ' ')}", sep, f"Symbol: {symbol}"]

    if "iv_rank" in alert:
        lines.append(f"IV Rank: {float(alert['iv_rank']):.1f}%")
        if alert.get("current_iv"):
            lines.append(f"Current IV: {float(alert['current_iv']):.2f}%")
        if alert.get("atm_strike"):
            lines.append(f"ATM Strike: {alert['atm_strike']}")
    if "pcr" in alert:
        lines.append(f"PCR: {float(alert['pcr']):.2f}")
    if "significance" in alert:
        lines.append(f"OI Signal: {alert['significance']}")
        if alert.get("net_oi") is not None:
            lines.append(f"Net OI: {int(alert['net_oi']):,}")
        if alert.get("max_pain"):
            lines.append(f"Max Pain: {alert['max_pain']}")
    if a_type == "MAX_PAIN_SHIFT":
        lines.append(f"Max Pain: {alert['previous_max_pain']:.0f} → {alert['max_pain']:.0f}")
        lines.append(f"Shift: {alert['shift_points']:+.0f} pts")
    if a_type == "EXPIRY_DAY":
        lines.append(f"Day: {alert.get('weekday', '')}")
        lines.append(f"Advice: {alert.get('trading_advice', '')}")

    lines.append("")
    lines.append(rationale)
    return "\n".join(lines)


async def _send_alerts(alerts: list[dict[str, Any]]) -> None:
    """Push alerts to Telegram, one card per alert."""
    if not alerts:
        return
    from mcp_server.telegram_bot import send_telegram_message
    for alert in alerts:
        try:
            msg = format_alert(alert)
            await send_telegram_message(msg, force=True)
        except Exception as e:
            logger.warning("F&O alert telegram send failed: %s", e)


# ── Background loop ──────────────────────────────────────────────
async def fno_analytics_loop() -> None:
    """
    Background async loop — runs every MONITOR_INTERVAL seconds during NFO hours.

    Mirrors `_auto_scan_loop` and `signal_monitor_loop`. Always runs the
    snapshot in a worker thread because Kite calls are blocking.
    """
    logger.info("F&O analytics monitor started (interval=%ds)", MONITOR_INTERVAL)

    while True:
        try:
            await asyncio.sleep(MONITOR_INTERVAL)

            # F&O index trading hours = NFO (09:15-15:30 IST)
            try:
                if not is_market_open("NFO"):
                    logger.debug("F&O analytics: NFO closed, skipping cycle")
                    continue
            except Exception:
                pass  # Calendar failure → run anyway

            logger.info("F&O analytics: running cycle...")
            result = await asyncio.to_thread(check_fno_analytics_once)

            if result.get("status") == "skipped":
                logger.debug("F&O analytics skipped: %s", result.get("reason"))
                continue

            alerts = result.get("alerts", [])
            if alerts:
                logger.info("F&O analytics: %d alerts firing", len(alerts))
                await _send_alerts(alerts)
            else:
                logger.debug("F&O analytics: no transitions")

        except asyncio.CancelledError:
            logger.info("F&O analytics monitor stopped")
            break
        except Exception as e:
            logger.error("F&O analytics loop error: %s", e)
            await asyncio.sleep(60)


__all__ = [
    "check_fno_analytics_once",
    "fno_analytics_loop",
    "format_alert",
    "INDEX_SYMBOLS",
    "STATE_FILE",
]


# Settings hook for explicit-import callers
_ENABLED = getattr(settings, "FNO_ANALYTICS_ENABLED", True)
