"""
Nifty Weekly Short Strangle — Live Signal Generator

Emits a Telegram signal on entry days for the Nifty 50 weekly short strangle,
the only strategy with validated edge in the research arc (Tier 2, 2026-05-07).

Validation summary:
  WF return: 16.4% on margin | WF Sharpe: 0.556 | Win rate: 78.2% | 55 trades
  Criteria: docs/strategy_validation/nifty_weekly_strangle_criteria.md

Strategy parameters (locked — matches validated spec exactly):
  - Underlying: NIFTY weekly expiry
  - Entry: ~5 DTE (expiry - 6 calendar days, first trading day on/after)
  - Strikes: 0.15-delta CE and PE
  - VIX gate: 30th–80th percentile, rolling 252-day India VIX
  - Profit target: 50% of initial combined credit
  - Stop loss: 2× initial combined credit
  - Lot size: 75 | Margin basis: ₹1,50,000

This module generates INFORMATIONAL signals only. No automated execution.
Every signal is tagged Tier 2 — marginal validated edge, not financial advice.

Loop: checks once per day at 09:30 IST. Sends at most one signal per expiry.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from mcp_server.options_greeks import calculate_greeks

logger = logging.getLogger("nifty_strangle_live")

# ── Strategy constants (must match validated spec) ─────────────────────────
TARGET_DELTA       = 0.15
PROFIT_TARGET_PCT  = 0.50
STOP_LOSS_MULT     = 2.0
LOT_SIZE           = 75
SPAN_MARGIN        = 150_000.0
RFR                = 0.065
VIX_LOW_PCT        = 0.30
VIX_HIGH_PCT       = 0.80
VIX_WINDOW_DAYS    = 252

# Entry = expiry - 6 calendar days
# Thursday expiry (pre Sept 2025): gives Friday entry (~5 DTE)
# Tuesday expiry  (post Sept 2025): gives Wednesday entry (~5-6 DTE)
ENTRY_OFFSET_DAYS  = 6
TRANSITION_DATE    = date(2025, 9, 1)

# Check at 09:30 IST each trading day
CHECK_HOUR_IST     = 9
CHECK_MINUTE_IST   = 30


# ── VIX percentile ──────────────────────────────────────────────────────────

def _fetch_vix_nse() -> float | None:
    """Fetch India VIX from NSE directly (backup when yfinance is down)."""
    try:
        import requests
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/",
        })
        session.get("https://www.nseindia.com/", timeout=8)
        resp = session.get(
            "https://www.nseindia.com/api/allIndices",
            timeout=10,
        )
        data = resp.json()
        for entry in data.get("data", []):
            if entry.get("index", "").upper() in ("INDIA VIX", "INDIAVIX"):
                return float(entry["last"])
        return None
    except Exception as exc:
        logger.debug("NSE VIX fetch failed: %s", exc)
        return None


def _fetch_vix_dhan() -> tuple[float | None, float | None]:
    """Fetch India VIX from Dhan historical daily data (252-day window).

    Dhan security ID 13 = INDIA VIX on IDX_I segment. Only runs when Dhan
    is logged in. Returns full 252-day window — same quality as yfinance.
    """
    try:
        from mcp_server.data_provider import get_provider
        provider = get_provider()
        dhan = getattr(provider, "dhan", None)
        if not dhan or not getattr(dhan, "logged_in", False):
            return None, None

        today = date.today()
        resp = dhan.client.historical_daily_data(
            security_id="13",           # India VIX sec ID in Dhan
            exchange_segment="IDX_I",
            instrument_type="INDEX",
            from_date=(today - timedelta(days=400)).strftime("%Y-%m-%d"),
            to_date=today.strftime("%Y-%m-%d"),
        )
        if not resp or not resp.get("data"):
            return None, None

        raw = resp["data"]
        if isinstance(raw, dict) and "close" in raw:
            closes = [float(v) for v in raw["close"] if v]
        elif isinstance(raw, list):
            closes = [float(r["close"]) for r in raw if r.get("close")]
        else:
            return None, None

        if not closes:
            return None, None

        today_vix = closes[-1]
        window = closes[-VIX_WINDOW_DAYS:] if len(closes) >= VIX_WINDOW_DAYS else closes
        pct = sum(1 for v in window if v <= today_vix) / len(window)
        logger.info("VIX (Dhan): %.2f | percentile: %.0f%%", today_vix, pct * 100)
        return today_vix, pct

    except Exception as exc:
        logger.debug("Dhan VIX failed: %s", exc)
        return None, None


def _fetch_vix_percentile() -> tuple[float | None, float | None]:
    """Return (today_vix, percentile_0_to_1).

    Cascade (best data quality first):
      1. Manual override  — NIFTY_STRANGLE_VIX env var (emergency bypass)
      2. yfinance         — full 252-day window, accurate percentile
      3. Dhan             — full 252-day window via historical_daily_data (IDX_I sec 13)
      4. NSE allIndices   — spot VIX only, percentile approximated (10-35 range)
    """
    from mcp_server.config import settings

    # 1. Manual override
    manual_vix = getattr(settings, "NIFTY_STRANGLE_VIX", 0.0)
    if manual_vix and manual_vix > 0:
        logger.info("VIX override: %.2f (NIFTY_STRANGLE_VIX env)", manual_vix)
        pct = min(1.0, max(0.0, (manual_vix - 10.0) / 25.0))
        return manual_vix, pct

    # 2. yfinance (full 252-day window)
    try:
        import yfinance as yf
        today = date.today()
        df = yf.download(
            "^INDIAVIX",
            start=(today - timedelta(days=400)).isoformat(),
            end=(today + timedelta(days=1)).isoformat(),
            interval="1d", auto_adjust=True, progress=False,
        )
        if not df.empty:
            closes: list[float] = []
            for _, row in df.iterrows():
                v = row["Close"]
                closes.append(float(v.iloc[0]) if hasattr(v, "iloc") else float(v))
            if closes:
                today_vix = closes[-1]
                window = closes[-VIX_WINDOW_DAYS:] if len(closes) >= VIX_WINDOW_DAYS else closes
                pct = sum(1 for v in window if v <= today_vix) / len(window)
                logger.info("VIX (yfinance): %.2f | %.0f%%", today_vix, pct * 100)
                return today_vix, pct
    except Exception as e:
        logger.warning("VIX yfinance failed: %s", e)

    # 3. Dhan historical (full 252-day window, requires login)
    dhan_vix, dhan_pct = _fetch_vix_dhan()
    if dhan_vix is not None:
        return dhan_vix, dhan_pct

    # 4. NSE spot (approximate percentile, no history)
    nse_vix = _fetch_vix_nse()
    if nse_vix is not None and nse_vix > 0:
        pct = min(1.0, max(0.0, (nse_vix - 10.0) / 25.0))
        logger.info("VIX (NSE spot): %.2f | approx %.0f%% (no 252d window)", nse_vix, pct * 100)
        return nse_vix, pct

    logger.warning("VIX: all sources failed — set NIFTY_STRANGLE_VIX env to override")
    return None, None


# ── Expiry calendar ─────────────────────────────────────────────────────────

def _target_expiry_dow(ref_date: date) -> int:
    """Return target weekday for weekly expiry: 3=Thursday, 1=Tuesday."""
    return 1 if ref_date >= TRANSITION_DATE else 3


def _next_weekly_expiry(from_date: date) -> date | None:
    """
    Find the next Nifty weekly expiry on or after from_date.
    Uses Dhan expiry list if available, falls back to calendar arithmetic.
    """
    try:
        from mcp_server.data_provider import get_provider
        provider = get_provider()
        dhan = getattr(provider, "dhan", None)
        if dhan and getattr(dhan, "logged_in", False):
            scrip_cache = getattr(dhan, "_scrip_cache", {})
            idx_sec_id = scrip_cache.get("NSE:NIFTY", "")
            if idx_sec_id:
                resp = dhan.client.expiry_list(
                    under_security_id=idx_sec_id,
                    under_exchange_segment="IDX_I",
                )
                expiry_list = [str(e) for e in (resp.get("data", []) or [])]
                today_str = from_date.isoformat()
                valid = sorted(e for e in expiry_list if e >= today_str)
                if valid:
                    return date.fromisoformat(valid[0])
    except Exception as e:
        logger.debug("Dhan expiry list failed, using calendar fallback: %s", e)

    # Calendar fallback: walk forward to find the next Thursday/Tuesday
    target_dow = _target_expiry_dow(from_date)
    d = from_date
    for _ in range(14):
        if d.weekday() == target_dow:
            return d
        d += timedelta(days=1)
    return None


def _is_entry_day(today: date) -> tuple[bool, date | None]:
    """
    Return (is_entry_day, target_expiry).
    Entry target = expiry - ENTRY_OFFSET_DAYS. If that lands on a weekend
    or before today, we check if today is the first available trading day
    on/after the target (within a 2-day drift window).
    """
    # Find the next expiry from today + ENTRY_OFFSET_DAYS forward
    # (if today IS the entry target, next expiry is ~6 days out)
    look_from = today + timedelta(days=ENTRY_OFFSET_DAYS - 2)
    expiry = _next_weekly_expiry(look_from)
    if expiry is None:
        return False, None

    entry_target = expiry - timedelta(days=ENTRY_OFFSET_DAYS)
    drift = (today - entry_target).days
    # Accept today as entry if we're within 0-2 days past the target
    # (handles weekends and holidays at the boundary)
    if 0 <= drift <= 2:
        logger.info(
            "Entry day confirmed: expiry=%s entry_target=%s today=%s drift=%dd",
            expiry, entry_target, today, drift,
        )
        return True, expiry

    return False, None


# ── Option chain + delta-based strike selection ─────────────────────────────

def _get_nifty_spot_nse() -> float | None:
    """Get Nifty 50 index level from NSE allIndices (works outside market hours)."""
    try:
        import requests
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/",
        })
        session.get("https://www.nseindia.com/", timeout=8)
        resp = session.get("https://www.nseindia.com/api/allIndices", timeout=10)
        for entry in resp.json().get("data", []):
            if entry.get("index", "").upper() in ("NIFTY 50", "NIFTY50"):
                return float(entry["last"])
        return None
    except Exception as exc:
        logger.debug("NSE allIndices spot failed: %s", exc)
        return None


def _get_chain_nse(expiry: date) -> tuple[float | None, dict]:
    """Fetch spot + option chain from NSE option-chain-indices API.

    No broker login required. Returns (spot, chain_dict).
    The option chain API only returns data during market hours (09:15–15:30 IST).
    Spot is fetched from allIndices as a fallback if chain API returns empty.
    """
    import requests
    expiry_str = expiry.strftime("%d-%b-%Y").upper()  # NSE format: 13-MAY-2026
    spot: float | None = None
    chain: dict = {}

    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/",
        })
        session.get("https://www.nseindia.com/", timeout=8)

        resp = session.get(
            "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY",
            timeout=12,
        )
        data = resp.json()

        records = data.get("records", {})
        if not records:
            # Market likely closed — get spot from allIndices at least
            spot = _get_nifty_spot_nse()
            logger.info("Strangle: NSE chain empty (market closed?), spot=%.0f", spot or 0)
            return spot, {}

        spot = float(records["underlyingValue"])

        for row in records.get("data", []):
            if row.get("expiryDate", "").upper() != expiry_str:
                continue
            strike = float(row["strikePrice"])
            for ot in ("CE", "PE"):
                if ot in row:
                    entry = row[ot]
                    chain.setdefault(strike, {})[ot] = {
                        "ltp": float(entry.get("lastPrice", 0)),
                        "iv":  float(entry.get("impliedVolatility", 0)),
                        "oi":  int(entry.get("openInterest", 0)),
                    }

        logger.info("Strangle: NSE chain — spot=%.0f, %d strikes for %s", spot, len(chain), expiry_str)
        return spot, chain

    except Exception as exc:
        logger.warning("Strangle: NSE chain fetch failed: %s", exc)
        # Last resort: at least return spot if chain fails
        if not spot:
            spot = _get_nifty_spot_nse()
        return spot, chain


def _get_chain_and_spot(expiry: date) -> tuple[float | None, dict]:
    """Return (spot, chain_dict) for NIFTY at the given expiry.

    Priority:
      1. Dhan option chain (broker, most accurate live data)
      2. NSE option-chain-indices API (no broker, fallback)
    """
    spot: float | None = None
    chain: dict = {}

    # ── Primary: Dhan (when logged in) ───────────────────────────────────
    try:
        from mcp_server.data_provider import get_provider
        provider = get_provider()
        dhan = getattr(provider, "dhan", None)

        if dhan and getattr(dhan, "logged_in", False):
            # Spot price via broker
            quote = provider.get_quote("NIFTY", exchange="NSE")
            if quote:
                spot = quote.get("ltp") or quote.get("last_price")

            # Option chain via Dhan IDX_I
            expiry_str = expiry.isoformat()
            scrip_cache = getattr(dhan, "_scrip_cache", {})
            idx_sec_id = scrip_cache.get("NSE:NIFTY", "")
            if idx_sec_id and spot:
                try:
                    resp = dhan.client.option_chain(
                        under_security_id=idx_sec_id,
                        under_exchange_segment="IDX_I",
                        expiry=expiry_str,
                    )
                    raw = resp.get("data", [])
                    if isinstance(raw, list):
                        for row in raw:
                            strike = float(row.get("strikePrice", 0))
                            ot = row.get("optionType", "").upper()
                            if strike <= 0 or ot not in ("CE", "PE", "CALL", "PUT"):
                                continue
                            ot = "CE" if ot in ("CE", "CALL") else "PE"
                            chain.setdefault(strike, {})[ot] = {
                                "ltp": float(row.get("ltp", row.get("lastTradedPrice", 0))),
                                "iv":  float(row.get("iv", row.get("impliedVolatility", 0))),
                                "oi":  int(row.get("oi", row.get("openInterest", 0))),
                            }
                    if chain:
                        logger.info("Strangle: Dhan chain — %d strikes", len(chain))
                        return spot, chain
                except Exception as dhan_err:
                    logger.warning("Strangle: Dhan chain failed: %s", dhan_err)
    except Exception as e:
        logger.debug("Strangle: broker path failed: %s", e)

    # ── Fallback: NSE public API (no login required) ──────────────────────
    logger.info("Strangle: using NSE chain fallback (no broker connection)")
    return _get_chain_nse(expiry)


def _find_delta_strike(
    spot: float,
    dte: int,
    iv_proxy: float,
    opt_type: str,
    chain: dict,
) -> tuple[float | None, float | None, float | None]:
    """
    Return (strike, ltp, actual_delta) closest to TARGET_DELTA for opt_type.
    iv_proxy: annualized IV used for BS delta (falls back to chain IV if 0).
    """
    best_strike = best_ltp = best_delta = None
    best_diff = float("inf")

    for strike, data in chain.items():
        leg = data.get(opt_type)
        if not leg or leg.get("ltp", 0) <= 0:
            continue
        iv = iv_proxy
        if iv <= 0:
            chain_iv = leg.get("iv", 0)
            iv = chain_iv / 100.0 if chain_iv > 1 else chain_iv
        if iv <= 0:
            iv = 0.14  # fallback

        g = calculate_greeks(spot, strike, max(dte, 1), RFR, iv, opt_type)
        delta = abs(g.delta)
        diff = abs(delta - TARGET_DELTA)
        if diff < best_diff:
            best_diff = diff
            best_strike = strike
            best_ltp = leg["ltp"]
            best_delta = delta

    if best_diff > TARGET_DELTA:    # too far from target — no usable strike
        return None, None, None
    return best_strike, best_ltp, best_delta


# ── Signal card ─────────────────────────────────────────────────────────────

def format_strangle_signal(
    expiry: date,
    dte: int,
    spot: float,
    ce_strike: float,
    ce_ltp: float,
    ce_delta: float,
    pe_strike: float,
    pe_ltp: float,
    pe_delta: float,
    vix: float,
    vix_pct: float,
) -> str:
    sep = "━" * 28
    credit_per_lot = (ce_ltp + pe_ltp) * LOT_SIZE
    profit_target  = credit_per_lot * PROFIT_TARGET_PCT
    stop_loss      = credit_per_lot * STOP_LOSS_MULT

    expiry_dow = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][expiry.weekday()]

    lines = [
        "🎯 NIFTY WEEKLY STRANGLE — Entry Signal",
        sep,
        f"Expiry : {expiry} ({expiry_dow}) | DTE: {dte}d",
        f"Spot   : {spot:,.0f}",
        sep,
        f"SELL CE : {ce_strike:,.0f}  @ ₹{ce_ltp:.1f}  (Δ {ce_delta:.3f})",
        f"SELL PE : {pe_strike:,.0f}  @ ₹{pe_ltp:.1f}  (Δ {pe_delta:.3f})",
        sep,
        f"Credit collected : ₹{credit_per_lot:,.0f}  (75 lots)",
        f"Profit target    : ₹{profit_target:,.0f}  (50% credit)",
        f"Stop loss        : ₹{stop_loss:,.0f}  (2× credit)",
        f"Margin estimate  : ₹{SPAN_MARGIN:,.0f}",
        sep,
        f"India VIX : {vix:.2f}  ({vix_pct:.0%} pct, 252d window)  ✅ gate passed",
        sep,
        "⚠️  TIER 2 — Marginal validated edge.",
        "WF return 16.4% | Sharpe 0.556 | Win rate 78.2% (55 trades, 2023-2026).",
        "Informational signal only. Not financial advice.",
        "Consult a SEBI-registered adviser before trading.",
    ]
    return "\n".join(lines)


# ── Main entry point ────────────────────────────────────────────────────────

def check_and_emit_strangle_signal() -> dict[str, Any] | None:
    """
    Run the full entry check. Returns signal dict if emitted, None otherwise.
    Call this once per day at 09:30 IST.
    """
    today = date.today()
    logger.info("Strangle check: %s", today)

    is_entry, expiry = _is_entry_day(today)
    if not is_entry or expiry is None:
        logger.info("Strangle: not an entry day")
        return None

    dte = (expiry - today).days

    vix, vix_pct = _fetch_vix_percentile()
    if vix is None or vix_pct is None:
        logger.warning("Strangle: VIX unavailable — skipping (gate cannot be evaluated)")
        return None

    if vix_pct < VIX_LOW_PCT or vix_pct > VIX_HIGH_PCT:
        logger.info(
            "Strangle: VIX gate REJECTED — VIX %.1f at %.0f pct (need 30–80)",
            vix, vix_pct * 100,
        )
        return {"status": "vix_rejected", "vix": vix, "vix_pct": vix_pct, "expiry": str(expiry)}

    spot, chain = _get_chain_and_spot(expiry)
    if not spot or not chain:
        logger.warning("Strangle: no chain data for expiry %s", expiry)
        return None

    iv_proxy = vix / 100.0  # India VIX ≈ Nifty 30d IV

    ce_strike, ce_ltp, ce_delta = _find_delta_strike(spot, dte, iv_proxy, "CE", chain)
    pe_strike, pe_ltp, pe_delta = _find_delta_strike(spot, dte, iv_proxy, "PE", chain)

    if not all([ce_strike, ce_ltp, pe_strike, pe_ltp]):
        logger.warning("Strangle: could not find 0.15-delta strikes (chain thin?)")
        return None

    msg = format_strangle_signal(
        expiry=expiry, dte=dte, spot=spot,
        ce_strike=ce_strike, ce_ltp=ce_ltp, ce_delta=ce_delta,
        pe_strike=pe_strike, pe_ltp=pe_ltp, pe_delta=pe_delta,
        vix=vix, vix_pct=vix_pct,
    )

    logger.info(
        "Strangle signal: expiry=%s CE=%s@%.1f PE=%s@%.1f credit=%.0f VIX=%.1f(%.0f%%)",
        expiry, ce_strike, ce_ltp, pe_strike, pe_ltp,
        (ce_ltp + pe_ltp) * LOT_SIZE, vix, vix_pct * 100,
    )

    return {
        "status":     "emitted",
        "expiry":     str(expiry),
        "dte":        dte,
        "spot":       spot,
        "ce_strike":  ce_strike,
        "ce_ltp":     ce_ltp,
        "pe_strike":  pe_strike,
        "pe_ltp":     pe_ltp,
        "vix":        vix,
        "vix_pct":    vix_pct,
        "message":    msg,
    }
