"""
Signal Gates — earnings blackout and FII directional filters for unvalidated scanners.

Both gates are fail-open: if the underlying API is unavailable, the signal passes.
Caching prevents repeated NSE API hits within a single scan cycle.

Usage (automatic via base_agent.validate()):
    from mcp_server.signal_gates import apply_signal_gates
    filtered = apply_signal_gates(candidates)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# ── Earnings Gate ─────────────────────────────────────────────────────────────


class _EarningsCache:
    """Caches NSE earnings calendar for the current calendar day."""

    def __init__(self) -> None:
        self._cache_date: date | None = None
        self._blocked_tickers: set[str] = set()

    def _refresh_if_stale(self, days_ahead: int) -> None:
        today = date.today()
        if self._cache_date == today:
            return
        try:
            from mcp_server.earnings_calendar import fetch_nse_earnings_calendar
            events = fetch_nse_earnings_calendar(days_ahead=days_ahead)
            cutoff = today + timedelta(days=days_ahead)
            blocked: set[str] = set()
            for ev in events:
                try:
                    results_date = date.fromisoformat(ev["results_date"])
                    if today <= results_date <= cutoff:
                        blocked.add(ev["ticker"].upper())
                except Exception:
                    continue
            self._blocked_tickers = blocked
            self._cache_date = today
            logger.info(
                "[EarningsGate] refreshed: %d tickers blocked (next %dd)",
                len(blocked), days_ahead,
            )
        except Exception as exc:
            logger.warning("[EarningsGate] refresh failed (fail-open): %s", exc)

    def is_blocked(self, ticker: str, days_ahead: int) -> bool:
        self._refresh_if_stale(days_ahead)
        clean = ticker.upper().replace("NSE:", "").replace("BSE:", "")
        return clean in self._blocked_tickers


_earnings_cache = _EarningsCache()


def is_earnings_blocked(ticker: str, days_ahead: int = 7) -> bool:
    """Return True if ticker has earnings in the next days_ahead days."""
    return _earnings_cache.is_blocked(ticker, days_ahead)


# ── FII Gate ──────────────────────────────────────────────────────────────────


class _FiiCache:
    """Caches FII net flow, refreshed at most once per hour."""

    _REFRESH_INTERVAL = timedelta(hours=1)

    def __init__(self) -> None:
        self._fii_net: float = 0.0
        self._last_refresh: datetime | None = None

    def _refresh_if_stale(self) -> None:
        now = datetime.utcnow()
        if self._last_refresh and (now - self._last_refresh) < self._REFRESH_INTERVAL:
            return
        try:
            from mcp_server.fii_dii_filter import get_fii_dii_data
            data = get_fii_dii_data()
            self._fii_net = float(data.get("fii_net", 0.0))
            self._last_refresh = now
            logger.info("[FiiGate] refreshed: FII net=%.0f Cr", self._fii_net)
        except Exception as exc:
            logger.warning("[FiiGate] refresh failed (fail-open): %s", exc)

    @property
    def fii_net(self) -> float:
        self._refresh_if_stale()
        return self._fii_net


_fii_cache = _FiiCache()

# Threshold: FII net sell > 2000 Cr → strong institutional exit → block LONG
_FII_BLOCK_THRESHOLD = -2000.0


def is_fii_long_blocked() -> bool:
    """Return True if FII is strongly selling (net < -2000 Cr) — blocks LONG signals."""
    return _fii_cache.fii_net < _FII_BLOCK_THRESHOLD


# ── Combined gate application ─────────────────────────────────────────────────


def apply_signal_gates(
    candidates: list[dict[str, Any]],
    earnings_gate: bool = True,
    fii_gate: bool = True,
    earnings_days: int = 7,
) -> list[dict[str, Any]]:
    """
    Filter candidates through earnings blackout and FII directional gates.

    Both gates are fail-open — a gate error never drops a signal silently.
    Reason for rejection is logged at INFO level for audit trail.

    Args:
        candidates: signal dicts, each with 'ticker' and 'direction' keys
        earnings_gate: enable earnings blackout filter
        fii_gate: enable FII net flow directional filter
        earnings_days: look-ahead window for earnings blackout

    Returns:
        Filtered list of candidates that passed all active gates.
    """
    if not candidates:
        return candidates

    fii_blocks_long = fii_gate and is_fii_long_blocked()
    if fii_blocks_long:
        logger.info(
            "[FiiGate] ACTIVE — FII net %.0f Cr < %.0f threshold, LONG signals blocked",
            _fii_cache.fii_net, _FII_BLOCK_THRESHOLD,
        )

    passed: list[dict[str, Any]] = []
    for sig in candidates:
        ticker = sig.get("ticker", "")
        direction = sig.get("direction", "").upper()

        if earnings_gate and is_earnings_blocked(ticker, earnings_days):
            logger.info(
                "[EarningsGate] blocked %s — earnings in next %dd", ticker, earnings_days
            )
            sig["gate_blocked"] = f"earnings_blackout:{earnings_days}d"
            continue

        if fii_blocks_long and direction == "LONG":
            logger.info(
                "[FiiGate] blocked %s %s — strong FII selling (net %.0f Cr)",
                ticker, direction, _fii_cache.fii_net,
            )
            sig["gate_blocked"] = f"fii_long_block:{_fii_cache.fii_net:.0f}Cr"
            continue

        passed.append(sig)

    dropped = len(candidates) - len(passed)
    if dropped:
        logger.info(
            "[SignalGates] %d/%d signals passed (%d blocked by gates)",
            len(passed), len(candidates), dropped,
        )
    return passed
