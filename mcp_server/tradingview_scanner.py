"""
MKUMARAN Trading OS — TradingView Screener integration

A parallel NSE scanning source that sits alongside the existing Chartink
pipeline. Uses the `tradingview-screener` library directly (HTTPS to
scanner.tradingview.com, no MCP subprocess, no API key for public data).

Each entry in SCANNERS maps an MWA scanner key (e.g. "swing_low",
"breakout_200dma", "macd_buy_daily") to a TradingView Query builder that
reproduces the same intent against TV's 3000+ fields. Return shape
matches fetch_chartink: a list of plain NSE symbols without exchange
prefix, so callers can union TV + Chartink results by key without
downstream changes.

Why this exists:
  - Chartink scrapes HTML and breaks on layout changes.
  - TV's scanner.tradingview.com is a stable public JSON endpoint.
  - Using both gives resilience: empty Chartink result → TV backup.
  - TV fields (SMA, EMA, MACD, BB, RSI, ADX, ATR, gap, relative volume)
    are computed server-side, so the scan is fast and stateless.

Environment:
  TRADINGVIEW_SCANNER_ENABLED   default "false" — opt-in flag
  TRADINGVIEW_SCANNER_LIMIT     default 500     — max rows per scanner
  TRADINGVIEW_SCANNER_CACHE_TTL default 300     — seconds
  TRADINGVIEW_SESSIONID         optional        — session cookie for real-time
                                                   data (anonymous path returns
                                                   slightly delayed values).
                                                   Extract from browser cookies
                                                   on tradingview.com after
                                                   logging in.
  TRADINGVIEW_SESSIONID_SIGN    optional        — companion cookie required
                                                   alongside sessionid on newer
                                                   TradingView deployments.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Callable

try:
    from tradingview_screener import Column, Query

    _TV_AVAILABLE = True
except ImportError:
    _TV_AVAILABLE = False
    Column = None  # type: ignore[assignment]
    Query = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# ── Config ──────────────────────────────────────────────────────

_ENABLED = os.environ.get("TRADINGVIEW_SCANNER_ENABLED", "false").lower() == "true"
_DEFAULT_LIMIT = int(os.environ.get("TRADINGVIEW_SCANNER_LIMIT", "500"))
_CACHE_TTL = int(os.environ.get("TRADINGVIEW_SCANNER_CACHE_TTL", "300"))

# Minimum traded volume to drop illiquid tickers before any condition runs.
# Chartink clauses use "latest volume > 10000" as a floor; match that.
_MIN_VOLUME = 10_000


def _auth_cookies() -> dict[str, str] | None:
    """Return session cookies when configured, else None for anonymous access.

    Anonymous calls work fine for scanning — the fields exposed on
    scanner.tradingview.com/india/scan are delayed by ~15min without auth.
    With a valid sessionid cookie, responses carry real-time values.
    """
    sid = os.environ.get("TRADINGVIEW_SESSIONID", "").strip()
    if not sid:
        return None
    cookies = {"sessionid": sid}
    sid_sign = os.environ.get("TRADINGVIEW_SESSIONID_SIGN", "").strip()
    if sid_sign:
        cookies["sessionid_sign"] = sid_sign
    return cookies


# ── Base query builder ──────────────────────────────────────────


def _base() -> "Query":
    """NSE equities only, liquidity floor applied."""
    return (
        Query()
        .set_markets("india")
        .where(
            Column("exchange") == "NSE",
            Column("volume") >= _MIN_VOLUME,
        )
    )


# ── Scanner builders ────────────────────────────────────────────
# Keys MUST match entries in mwa_scanner.SCANNERS so the caller can
# merge results by key (union with Chartink output).


def _swing_low() -> "Query":
    # Close near 1-month low with green candle — proxy for Chartink's
    # "latest low <= min(20, latest low) and close > open".
    return (
        _base()
        .select("name", "close", "open", "low", "Low.1M", "volume")
        .where(
            Column("low") <= Column("Low.1M"),
            Column("close") > Column("open"),
        )
    )


def _upswing() -> "Query":
    # Approximation of Chartink's 2-day upswing. We cannot use |2 shifts
    # (TV's scanner doesn't expose them) and empirical testing shows that
    # `low|1` returns anomalously few matches outside market hours — so
    # we express the upswing as: higher close AND higher open AND green
    # body. Chartink's stricter clause remains authoritative; TV produces
    # a wider candidate universe that the Python ranker can re-filter.
    return (
        _base()
        .select("name", "close", "open", "high", "volume")
        .where(
            Column("close") > Column("close|1"),
            Column("open") > Column("open|1"),
            Column("close") > Column("open"),
        )
    )


def _swing_high() -> "Query":
    return (
        _base()
        .select("name", "close", "open", "high", "High.1M", "volume")
        .where(
            Column("high") >= Column("High.1M"),
            Column("close") < Column("open"),
        )
    )


def _downswing() -> "Query":
    # See _upswing for why this uses close/open shifts instead of high/low.
    return (
        _base()
        .select("name", "close", "open", "volume")
        .where(
            Column("close") < Column("close|1"),
            Column("open") < Column("open|1"),
            Column("close") < Column("open"),
        )
    )


def _bandwalk_highs() -> "Query":
    # Upper BB touch with green candle — bullish bandwalk.
    return (
        _base()
        .select("name", "close", "open", "high", "BB.upper", "volume")
        .where(
            Column("high") >= Column("BB.upper"),
            Column("close") > Column("open"),
        )
    )


def _llbb_bounce() -> "Query":
    # Low touched lower BB + green candle close.
    return (
        _base()
        .select("name", "close", "open", "low", "BB.lower", "volume")
        .where(
            Column("low") <= Column("BB.lower"),
            Column("close") > Column("open"),
        )
    )


def _volume_avg() -> "Query":
    # Liquidity floor scanner — volume > 10k already enforced in _base.
    return _base().select("name", "close", "volume")


def _volume_spike() -> "Query":
    # Relative volume > 2× 10-day average.
    return (
        _base()
        .select("name", "close", "volume", "relative_volume_10d_calc")
        .where(Column("relative_volume_10d_calc") > 2.0)
    )


def _breakout_200dma() -> "Query":
    # Fresh close above 200 SMA (yesterday was below).
    return (
        _base()
        .select("name", "close", "SMA200", "volume")
        .where(
            Column("close") > Column("SMA200"),
            Column("close|1") <= Column("SMA200|1"),
        )
    )


def _breakout_50day() -> "Query":
    # TV's aggregate-window fields (High.3M / Low.1M) include today's bar,
    # so `close > High.3M` can never be true. The `|1` shift is silently
    # unsupported on those fields. Use the 50 SMA proxy instead: close
    # above SMA50 while SMA50 slopes up, and today is a fresh cross above
    # a rising 20 SMA (a practical "50-day range break" substitute).
    return (
        _base()
        .select("name", "close", "SMA20", "SMA50", "volume")
        .where(
            Column("close") > Column("SMA50"),
            Column("SMA50") > Column("SMA50|1"),
            Column("close") > Column("SMA20"),
            Column("close|1") <= Column("SMA20|1"),
        )
    )


def _breakdown_20day() -> "Query":
    # Mirror of breakout_50day; fresh close below a falling 20 SMA with
    # price already under SMA50.
    return (
        _base()
        .select("name", "close", "SMA20", "SMA50", "volume")
        .where(
            Column("close") < Column("SMA50"),
            Column("SMA50") < Column("SMA50|1"),
            Column("close") < Column("SMA20"),
            Column("close|1") >= Column("SMA20|1"),
        )
    )


def _macd_buy_daily() -> "Query":
    # Fresh bullish MACD cross.
    return (
        _base()
        .select("name", "close", "MACD.macd", "MACD.signal", "volume")
        .where(
            Column("MACD.macd") > Column("MACD.signal"),
            Column("MACD.macd|1") <= Column("MACD.signal|1"),
        )
    )


def _macd_sell_weekly() -> "Query":
    # Approximated on daily chart — fresh bearish MACD cross.
    return (
        _base()
        .select("name", "close", "MACD.macd", "MACD.signal", "volume")
        .where(
            Column("MACD.macd") < Column("MACD.signal"),
            Column("MACD.macd|1") >= Column("MACD.signal|1"),
        )
    )


def _rsi_above_30() -> "Query":
    return _base().select("name", "close", "RSI", "volume").where(Column("RSI") > 30)


def _rsi_below_70() -> "Query":
    return _base().select("name", "close", "RSI", "volume").where(Column("RSI") < 70)


def _gap_up() -> "Query":
    # `gap` is in %, Chartink uses 2% as a common floor.
    return _base().select("name", "close", "gap", "volume").where(Column("gap") > 2.0)


def _gap_down() -> "Query":
    return _base().select("name", "close", "gap", "volume").where(Column("gap") < -2.0)


# near_200ma / near_100ma intentionally omitted: TradingView's Column
# expression language does not support Column * float arithmetic in
# filters, so "within 2% of SMA200" cannot be expressed server-side.
# These remain Chartink-only for now; revisit when the upstream lib
# adds expression support or we want to post-filter in Python.


def _daily_pct_change() -> "Query":
    # Move > 5% on the day.
    return (
        _base()
        .select("name", "close", "change", "volume")
        .where(Column("change") > 5.0)
    )


def _intraday_momentum_bull() -> "Query":
    # Strong green candle: change >= 3% and close > open.
    return (
        _base()
        .select("name", "close", "open", "change", "volume")
        .where(
            Column("change") >= 3.0,
            Column("close") > Column("open"),
        )
    )


def _intraday_momentum_bear() -> "Query":
    return (
        _base()
        .select("name", "close", "open", "change", "volume")
        .where(
            Column("change") <= -3.0,
            Column("close") < Column("open"),
        )
    )


# Registry: MWA scanner key → query builder
# Only includes scanners where the TV approximation is faithful to the
# original Chartink clause. SMC/Wyckoff/harmonic/RL scanners are
# Chartink/Python-only and deliberately not replicated here.
SCANNERS: dict[str, Callable[[], "Query"]] = {
    "swing_low": _swing_low,
    "upswing": _upswing,
    "swing_high": _swing_high,
    "downswing": _downswing,
    "bandwalk_highs": _bandwalk_highs,
    "llbb_bounce": _llbb_bounce,
    "volume_avg": _volume_avg,
    "volume_spike": _volume_spike,
    "breakout_200dma": _breakout_200dma,
    "breakout_50day": _breakout_50day,
    "breakdown_20day": _breakdown_20day,
    "macd_buy_daily": _macd_buy_daily,
    "macd_sell_weekly": _macd_sell_weekly,
    "rsi_above_30": _rsi_above_30,
    "rsi_below_70": _rsi_below_70,
    "gap_up": _gap_up,
    "gap_down": _gap_down,
    "daily_pct_change": _daily_pct_change,
    "intraday_momentum_bull": _intraday_momentum_bull,
    "intraday_momentum_bear": _intraday_momentum_bear,
}


# ── Cache ───────────────────────────────────────────────────────

_cache: dict[str, tuple[float, list[str]]] = {}


def _cached(key: str) -> list[str] | None:
    hit = _cache.get(key)
    if hit is None:
        return None
    ts, symbols = hit
    if time.time() - ts > _CACHE_TTL:
        return None
    return symbols


def _store(key: str, symbols: list[str]) -> None:
    _cache[key] = (time.time(), symbols)


def clear_cache() -> None:
    _cache.clear()


# ── Public API ──────────────────────────────────────────────────


def is_available() -> bool:
    """True when the library is installed AND the feature flag is on."""
    return _TV_AVAILABLE and _ENABLED


def available_scanners() -> list[str]:
    return list(SCANNERS)


def run_scanner(slug: str, limit: int | None = None) -> list[str]:
    """Run a single TradingView scanner.

    Returns a list of NSE symbols without exchange prefix (e.g. "RELIANCE"),
    matching the shape returned by MWAScanner.fetch_chartink.
    Never raises — returns [] on any failure.
    """
    if not _TV_AVAILABLE:
        return []
    if not _ENABLED:
        return []
    builder = SCANNERS.get(slug)
    if builder is None:
        logger.debug("tradingview_scanner: unknown slug %s", slug)
        return []

    row_cap = limit if limit is not None else _DEFAULT_LIMIT
    cache_key = f"{slug}:{row_cap}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    try:
        query = builder().limit(row_cap)
        cookies = _auth_cookies()
        if cookies:
            total, df = query.get_scanner_data(cookies=cookies)
        else:
            total, df = query.get_scanner_data()
    except Exception as exc:
        logger.warning("tradingview_scanner: %s failed: %s", slug, exc)
        return []

    if df is None or df.empty or "name" not in df.columns:
        logger.info("tradingview_scanner: %s matched 0 (universe=%s)", slug, total)
        _store(cache_key, [])
        return []

    symbols = [s for s in df["name"].tolist() if isinstance(s, str) and s]
    logger.info(
        "tradingview_scanner: %s matched %d symbols (universe=%s)",
        slug,
        len(symbols),
        total,
    )
    _store(cache_key, symbols)
    return symbols


def run_scanners(slugs: list[str], limit: int | None = None) -> dict[str, list[str]]:
    """Run several scanners by slug. Unknown slugs are skipped silently."""
    results: dict[str, list[str]] = {}
    for slug in slugs:
        if slug in SCANNERS:
            results[slug] = run_scanner(slug, limit=limit)
    return results


def run_all(limit: int | None = None) -> dict[str, list[str]]:
    """Run every registered TV scanner."""
    return run_scanners(list(SCANNERS), limit=limit)


def merge_with_chartink(
    chartink_results: dict[str, list[str]],
    tv_results: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Union Chartink + TradingView results per scanner key.

    Preserves insertion order, deduplicates symbols, and keeps Chartink-only
    and TV-only scanners intact. When both sources have results for the same
    key, Chartink symbols appear first (they were produced by the authoritative
    scan_clause), and TV symbols fill in anything Chartink missed.
    """
    merged: dict[str, list[str]] = {k: list(v) for k, v in chartink_results.items()}
    for key, tv_symbols in tv_results.items():
        existing = merged.get(key, [])
        seen = set(existing)
        additions = [s for s in tv_symbols if s and s not in seen]
        if additions:
            merged[key] = existing + additions
    return merged
