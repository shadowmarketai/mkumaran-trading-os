"""
MKUMARAN Trading OS — Intraday Scanner (Multi-Timeframe)

Runs every 5 minutes during NSE hours on a curated F&O watchlist.
Fetches BOTH 5m and 15m OHLCV for each ticker. Some scanners operate
on a single timeframe, others require multi-timeframe confirmation
(signal on 5m, trend confirmed on 15m) for higher-quality entries.

Scanners (8 total):

  ORB (Opening Range Breakout)           5m only
      Close breaks first-15min range with volume >= 1.2× average.

  VWAP Reclaim / Reject                  5m only
      3-bar flip above/below session VWAP.

  5m Momentum                            5m only
      3 consecutive same-direction bars with rising volume.

  EMA 9/21 Crossover                     5m + 15m confirmation
      Fast EMA crosses slow EMA on 5m, same direction on 15m.

  Previous Day High/Low Breakout         5m only
      Price breaks above yesterday's high or below yesterday's low.

  Supertrend                             15m
      ATR-based trend following — very popular with Indian traders.

  VWAP + EMA Confluence                  5m only
      Price above both VWAP and 9 EMA (strong bull) or below both.

  RSI Reversal                           15m
      RSI crosses back above 30 (oversold bounce) or below 70
      (overbought rejection) on 15m bars.

Gated by settings.INTRADAY_SIGNALS_ENABLED (default false).
"""

from __future__ import annotations

import logging
from datetime import time
from typing import Any

import numpy as np
import pandas as pd

from mcp_server.config import settings
from mcp_server.market_calendar import is_market_open, now_ist

logger = logging.getLogger(__name__)


# ── Default watchlist (30 liquid F&O large-caps) ────────────────
DEFAULT_WATCHLIST: list[str] = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS",
    "SBIN", "AXISBANK", "KOTAKBANK", "LT", "ITC",
    "HINDUNILVR", "BHARTIARTL", "MARUTI", "TATAMOTORS", "TATASTEEL",
    "BAJFINANCE", "HCLTECH", "WIPRO", "ADANIENT", "ADANIPORTS",
    "SUNPHARMA", "ASIANPAINT", "TITAN", "ULTRACEMCO", "POWERGRID",
    "NTPC", "ONGC", "JSWSTEEL", "HINDALCO", "VEDL",
]


def _watchlist() -> list[str]:
    raw = getattr(settings, "INTRADAY_WATCHLIST", "") or ""
    if raw.strip():
        base = [s.strip().upper() for s in raw.split(",") if s.strip()]
    else:
        base = list(DEFAULT_WATCHLIST)

    # Dynamically add today's top movers to the intraday watchlist.
    # The top gainers/losers are the most-traded stocks — prime intraday
    # candidates that the static list might miss.
    try:
        from mcp_server.mcp_server import _market_movers_cache
        if _market_movers_cache:
            existing = set(base)
            for cat in ("gainers", "losers", "most_active"):
                for item in (_market_movers_cache.get(cat, []) or [])[:5]:
                    t = item.get("symbol", "")
                    if t and t not in existing:
                        base.append(t)
                        existing.add(t)
    except Exception:
        pass

    return base


# ── Helpers ─────────────────────────────────────────────────────

def _ok(df: pd.DataFrame | None, min_bars: int = 6) -> bool:
    if df is None or df.empty:
        return False
    needed = {"open", "high", "low", "close", "volume"}
    if not needed.issubset(set(df.columns.str.lower())):
        return False
    return len(df) >= min_bars


def _vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    cum_pv = (typical * df["volume"]).cumsum()
    cum_v = df["volume"].cumsum().replace(0, np.nan)
    return cum_pv / cum_v


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.Series:
    """Returns a Series of +1 (uptrend) / -1 (downtrend)."""
    hl2 = (df["high"] + df["low"]) / 2
    atr = (df["high"] - df["low"]).rolling(period).mean()
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr

    direction = pd.Series(1, index=df.index)
    for i in range(1, len(df)):
        if df["close"].iloc[i] > upper.iloc[i - 1]:
            direction.iloc[i] = 1
        elif df["close"].iloc[i] < lower.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]
    return direction


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    """Average True Range over the last `period` 5m bars."""
    if len(df) < period + 1:
        return float(df["close"].iloc[-1]) * 0.002
    highs  = df["high"].values
    lows   = df["low"].values
    closes = df["close"].values
    trs = [
        max(highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1]))
        for i in range(max(1, len(df) - period), len(df))
    ]
    return sum(trs) / len(trs)


def _make_signal(
    direction: str, entry: float, sl: float,
    pattern: str, scanner: str, rrr_mult: float = 2.0,
) -> dict[str, Any]:
    risk = abs(entry - sl)
    if risk <= 0:
        risk = entry * 0.002
    return {
        "direction": direction,
        "entry": float(entry),
        "sl": float(sl),
        "target": float(entry + risk * rrr_mult) if direction == "LONG" else float(entry - risk * rrr_mult),
        "pattern": pattern,
        "scanner": scanner,
    }


# ══════════════════════════════════════════════════════════════════
# SCANNERS — 5m timeframe
# ══════════════════════════════════════════════════════════════════

def scan_orb(df5: pd.DataFrame, **_kw: Any) -> dict[str, Any] | None:
    """Opening Range Breakout — first 15 min (bars 0-2)."""
    if not _ok(df5, 4):
        return None
    opening = df5.iloc[:3]
    rest = df5.iloc[3:]
    if rest.empty:
        return None
    or_high = opening["high"].max()
    or_low = opening["low"].min()
    avg_vol = opening["volume"].mean() or 1.0
    last = rest.iloc[-1]
    if last["close"] > or_high and last["volume"] >= avg_vol * 1.2:
        return _make_signal("LONG", last["close"], or_low, "ORB breakout", "orb")
    if last["close"] < or_low and last["volume"] >= avg_vol * 1.2:
        return _make_signal("SHORT", last["close"], or_high, "ORB breakdown", "orb")
    return None


def scan_vwap(df5: pd.DataFrame, **_kw: Any) -> dict[str, Any] | None:
    """VWAP reclaim (bull) or reject (bear) — 3-bar state flip.

    SL uses the wider of: 3-bar swing low/high OR 1.5×ATR from entry.
    The original 3-bar SL was too tight — stocks were whipsawing through
    it and then recovering in the intended direction (Session 2: 82 SL
    hits vs 89 targets at RRR 1.0).
    """
    if not _ok(df5, 6):
        return None
    vwap  = _vwap(df5)
    last  = df5.iloc[-1]
    prev3 = df5.iloc[-4:-1]
    atr_val = _atr(df5)
    if (prev3["close"].values < vwap.iloc[-4:-1].values).all() and last["close"] > vwap.iloc[-1]:
        swing_sl  = float(prev3["low"].min())
        atr_sl    = last["close"] - 1.5 * atr_val
        sl        = min(swing_sl, atr_sl)   # lower price = wider stop for LONG
        return _make_signal("LONG", last["close"], sl, "VWAP reclaim", "vwap")
    if (prev3["close"].values > vwap.iloc[-4:-1].values).all() and last["close"] < vwap.iloc[-1]:
        swing_sl  = float(prev3["high"].max())
        atr_sl    = last["close"] + 1.5 * atr_val
        sl        = max(swing_sl, atr_sl)   # higher price = wider stop for SHORT
        return _make_signal("SHORT", last["close"], sl, "VWAP reject", "vwap")
    return None


def scan_momentum(df5: pd.DataFrame, **_kw: Any) -> dict[str, Any] | None:
    """3 consecutive 5m bars in same direction with rising volume."""
    if not _ok(df5, 4):
        return None
    recent = df5.iloc[-3:]
    closes = recent["close"].values
    opens = recent["open"].values
    vols = recent["volume"].values
    last = recent.iloc[-1]
    if (closes > opens).all() and vols[0] < vols[1] < vols[2]:
        sl = float(recent["low"].min())
        return _make_signal("LONG", last["close"], sl, "5m momentum bull", "momentum")
    if (closes < opens).all() and vols[0] < vols[1] < vols[2]:
        sl = float(recent["high"].max())
        return _make_signal("SHORT", last["close"], sl, "5m momentum bear", "momentum")
    return None


def scan_prev_day_hl(
    df5: pd.DataFrame,
    prev_day_high: float | None = None,
    prev_day_low: float | None = None,
    **_kw: Any,
) -> dict[str, Any] | None:
    """Breakout above previous day's high or below previous day's low.

    Uses actual prev-day H/L when supplied (run_scan passes these from the
    2-day 15m fetch). Falls back to today's opening 30-min range as a proxy
    only when called without historical context (unit tests, ad-hoc).

    Proximity filter: only fires when price has broken the level by ≤ 0.3%.
    Avoids chasing moves that already ran 1–2% past the level — the 90-day
    backtest showed 0 targets hit when this filter was absent.
    """
    if not _ok(df5, 6):
        return None
    if prev_day_high is not None and prev_day_low is not None:
        ph, pl = prev_day_high, prev_day_low
    else:
        ph = df5["high"].iloc[:6].max()
        pl = df5["low"].iloc[:6].min()
    last = df5.iloc[-1]
    vol_ok = last["volume"] > df5["volume"].mean() * 1.2
    if last["close"] > ph and vol_ok:
        if (last["close"] - ph) / ph <= 0.003:
            return _make_signal("LONG", last["close"], pl, "Prev-day H/L breakout", "prev_day_hl")
    if last["close"] < pl and vol_ok:
        if (pl - last["close"]) / pl <= 0.003:
            return _make_signal("SHORT", last["close"], ph, "Prev-day H/L breakdown", "prev_day_hl")
    return None


def scan_vwap_ema_confluence(df5: pd.DataFrame, **_kw: Any) -> dict[str, Any] | None:
    """Price above both VWAP and 9 EMA = strong bull; below both = strong bear."""
    if not _ok(df5, 12):
        return None
    vwap = _vwap(df5)
    ema9 = _ema(df5["close"], 9)
    last = df5.iloc[-1]
    prev = df5.iloc[-2]
    # Require fresh cross — previous bar wasn't in confluence, current is
    vwap_last = vwap.iloc[-1]
    ema_last = ema9.iloc[-1]
    vwap_prev = vwap.iloc[-2]
    ema_prev = ema9.iloc[-2]

    bull_now = last["close"] > vwap_last and last["close"] > ema_last
    bull_prev = prev["close"] > vwap_prev and prev["close"] > ema_prev
    bear_now = last["close"] < vwap_last and last["close"] < ema_last
    bear_prev = prev["close"] < vwap_prev and prev["close"] < ema_prev

    if bull_now and not bull_prev:
        sl = min(float(vwap_last), float(ema_last)) * 0.998
        return _make_signal("LONG", last["close"], sl, "VWAP+EMA confluence bull", "vwap_ema")
    if bear_now and not bear_prev:
        sl = max(float(vwap_last), float(ema_last)) * 1.002
        return _make_signal("SHORT", last["close"], sl, "VWAP+EMA confluence bear", "vwap_ema")
    return None


# ══════════════════════════════════════════════════════════════════
# SCANNERS — 15m timeframe
# ══════════════════════════════════════════════════════════════════

def scan_supertrend_15m(df15: pd.DataFrame, **_kw: Any) -> dict[str, Any] | None:
    """Supertrend direction flip on 15m bars."""
    if df15 is None or not _ok(df15, 12):
        return None
    st = _supertrend(df15, period=10, multiplier=3.0)
    if len(st) < 2:
        return None
    last = df15.iloc[-1]
    # Fresh flip: previous bar was opposite direction
    if st.iloc[-1] == 1 and st.iloc[-2] == -1:
        sl = float(df15["low"].iloc[-3:].min())
        return _make_signal("LONG", last["close"], sl, "Supertrend bull (15m)", "supertrend")
    if st.iloc[-1] == -1 and st.iloc[-2] == 1:
        sl = float(df15["high"].iloc[-3:].max())
        return _make_signal("SHORT", last["close"], sl, "Supertrend bear (15m)", "supertrend")
    return None


def scan_rsi_reversal_15m(df15: pd.DataFrame, **_kw: Any) -> dict[str, Any] | None:
    """RSI crossing back from oversold/overbought on 15m."""
    if df15 is None or not _ok(df15, 16):
        return None
    delta = df15["close"].diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    if rsi.isna().iloc[-1] or rsi.isna().iloc[-2]:
        return None
    last = df15.iloc[-1]
    # Oversold bounce: RSI was <30, now crossed above 30
    if rsi.iloc[-2] < 30 and rsi.iloc[-1] >= 30:
        sl = float(df15["low"].iloc[-3:].min())
        return _make_signal("LONG", last["close"], sl, "RSI oversold bounce (15m)", "rsi_reversal")
    # Overbought rejection: RSI was >70, now crossed below 70
    if rsi.iloc[-2] > 70 and rsi.iloc[-1] <= 70:
        sl = float(df15["high"].iloc[-3:].max())
        return _make_signal("SHORT", last["close"], sl, "RSI overbought reject (15m)", "rsi_reversal")
    return None


# ══════════════════════════════════════════════════════════════════
# SCANNERS — Multi-timeframe (5m signal + 15m confirmation)
# ══════════════════════════════════════════════════════════════════

def scan_ema_crossover_mtf(
    df5: pd.DataFrame, df15: pd.DataFrame | None = None, **_kw: Any,
) -> dict[str, Any] | None:
    """EMA 9/21 crossover on 5m, confirmed by 15m trend direction."""
    if not _ok(df5, 22):
        return None
    ema9 = _ema(df5["close"], 9)
    ema21 = _ema(df5["close"], 21)
    # Fresh crossover: ema9 crossed ema21 on the latest bar
    cross_bull = ema9.iloc[-1] > ema21.iloc[-1] and ema9.iloc[-2] <= ema21.iloc[-2]
    cross_bear = ema9.iloc[-1] < ema21.iloc[-1] and ema9.iloc[-2] >= ema21.iloc[-2]
    if not cross_bull and not cross_bear:
        return None

    # 15m confirmation (optional but boosts confidence)
    confirmed = True
    if df15 is not None and _ok(df15, 22):
        ema9_15 = _ema(df15["close"], 9)
        ema21_15 = _ema(df15["close"], 21)
        if cross_bull and ema9_15.iloc[-1] < ema21_15.iloc[-1]:
            confirmed = False  # 5m bullish cross but 15m trend is bearish
        if cross_bear and ema9_15.iloc[-1] > ema21_15.iloc[-1]:
            confirmed = False  # 5m bearish cross but 15m trend is bullish

    if not confirmed:
        return None

    last = df5.iloc[-1]
    suffix = " (MTF)" if df15 is not None else ""
    if cross_bull:
        sl = float(df5["low"].iloc[-5:].min())
        return _make_signal("LONG", last["close"], sl, f"EMA 9/21 cross bull{suffix}", "ema_cross")
    if cross_bear:
        sl = float(df5["high"].iloc[-5:].max())
        return _make_signal("SHORT", last["close"], sl, f"EMA 9/21 cross bear{suffix}", "ema_cross")
    return None


# ── Scanner registry ────────────────────────────────────────────
# Each entry: (key, function, needs_5m, needs_15m)
# key must match the name used in validate_intraday_scanners.py
# and in INTRADAY_VALIDATED_SCANNERS env var.
SCANNERS: list[tuple[str, Any, bool, bool]] = [
    ("orb",         scan_orb,                True,  False),
    ("vwap",        scan_vwap,               True,  False),
    ("momentum",    scan_momentum,            True,  False),
    ("prev_day_hl", scan_prev_day_hl,         True,  False),
    ("vwap_ema",    scan_vwap_ema_confluence, True,  False),
    ("ema_cross",   scan_ema_crossover_mtf,   True,  True),   # MTF: 5m + 15m confirmation
    ("supertrend",  scan_supertrend_15m,      False, True),   # 15m only
    ("rsi_rev",     scan_rsi_reversal_15m,    False, True),   # 15m only
]


# ── Intraday scan orchestrator ──────────────────────────────────

def run_scan() -> list[dict[str, Any]]:
    """Run all intraday scanners across the watchlist using both 5m and 15m
    OHLCV. Returns candidate signal dicts with RRR >= floor enforced.

    Requires INTRADAY_VALIDATED_SCANNERS to be non-empty — at least one scanner
    must have reached TIER_1 or TIER_2 in validate_intraday_scanners.py before
    any signals are emitted. This enforces backtest-first discipline.
    """
    if not getattr(settings, "INTRADAY_SIGNALS_ENABLED", False):
        return []

    validated_raw = getattr(settings, "INTRADAY_VALIDATED_SCANNERS", "")
    validated_set: set[str] = {s.strip() for s in validated_raw.split(",") if s.strip()}
    if not validated_set:
        logger.warning(
            "[INTRADAY] INTRADAY_SIGNALS_ENABLED=true but INTRADAY_VALIDATED_SCANNERS is empty. "
            "Run scripts/validate_intraday_scanners.py first. No signals emitted."
        )
        return []

    now = now_ist()
    market_time = now.time()
    if not (time(9, 15) <= market_time <= time(15, 15)):
        return []
    if not is_market_open("NSE"):
        return []

    from mcp_server.data_provider import get_provider

    provider = get_provider()
    tickers = _watchlist()
    rrr_floor = float(getattr(settings, "INTRADAY_RRR_FLOOR", 2.0))
    max_per_day = int(getattr(settings, "INTRADAY_MAX_SIGNALS_PER_DAY", 5))

    candidates: list[dict[str, Any]] = []
    for ticker in tickers:
        # Fetch both timeframes
        df5: pd.DataFrame | None = None
        df15: pd.DataFrame | None = None
        try:
            df5 = provider.get_ohlcv(ticker, interval="5minute", days=1, exchange="NSE")
            if df5 is not None and not df5.empty:
                df5 = df5.rename(columns={c: c.lower() for c in df5.columns})
        except Exception:
            df5 = None
        try:
            df15 = provider.get_ohlcv(ticker, interval="15minute", days=2, exchange="NSE")
            if df15 is not None and not df15.empty:
                df15 = df15.rename(columns={c: c.lower() for c in df15.columns})
        except Exception:
            df15 = None

        if df5 is None and df15 is None:
            continue

        # Extract real prev-day H/L from the 2-day 15m fetch.
        prev_day_high: float | None = None
        prev_day_low: float | None = None
        if df15 is not None and not df15.empty:
            try:
                today = now_ist().date()
                idx = pd.to_datetime(df15.index) if not isinstance(df15.index, pd.DatetimeIndex) else df15.index
                prev_mask = idx.date < today
                prev_bars = df15[prev_mask]
                if not prev_bars.empty:
                    prev_day_high = float(prev_bars["high"].max())
                    prev_day_low = float(prev_bars["low"].min())
            except Exception:
                pass

        hits: list[dict[str, Any]] = []
        for scanner_key, scanner_fn, needs_5m, needs_15m in SCANNERS:
            if scanner_key not in validated_set:
                continue  # skip scanners not yet validated via backtest
            if needs_5m and (df5 is None or df5.empty):
                continue
            if needs_15m and (df15 is None or df15.empty):
                continue
            try:
                hit = scanner_fn(
                    df5=df5 if needs_5m else pd.DataFrame(),
                    df15=df15 if needs_15m else None,
                    prev_day_high=prev_day_high,
                    prev_day_low=prev_day_low,
                )
            except Exception as scan_err:
                logger.debug(
                    "Scanner %s failed for %s: %s",
                    scanner_key, ticker, scan_err,
                )
                hit = None
            if hit:
                hits.append(hit)

        if not hits:
            continue

        # Pick direction with most scanner agreement
        long_hits = [h for h in hits if h["direction"] == "LONG"]
        short_hits = [h for h in hits if h["direction"] == "SHORT"]
        if len(long_hits) > len(short_hits):
            chosen = long_hits[0]
            scanner_count = len(long_hits)
        elif len(short_hits) > len(long_hits):
            chosen = short_hits[0]
            scanner_count = len(short_hits)
        else:
            continue  # conflicting

        entry = chosen["entry"]
        sl = chosen["sl"]
        target = chosen["target"]
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        rrr = round(abs(target - entry) / risk, 2)
        if rrr < rrr_floor:
            continue

        # Collect which scanners fired for this ticker
        scanner_names = [h["scanner"] for h in (long_hits if len(long_hits) > len(short_hits) else short_hits)]

        candidates.append({
            "ticker": ticker,
            "exchange": "NSE",
            "asset_class": "EQUITY",
            "direction": chosen["direction"],
            "entry": round(entry, 2),
            "sl": round(sl, 2),
            "target": round(target, 2),
            "rrr": rrr,
            "qty": 0,
            "pattern": chosen["pattern"],
            "scanner_count": scanner_count,
            "scanner_names": scanner_names,
            "timeframe": "5m",
            "source": "intraday",
        })

    candidates.sort(key=lambda c: (-c["scanner_count"], abs(c["entry"] - c["sl"])))
    logger.info(
        "[INTRADAY] %d candidates pass RRR>=%.1f (watchlist=%d, scanners=8)",
        len(candidates), rrr_floor, len(tickers),
    )
    return candidates[:max_per_day]
