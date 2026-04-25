"""
MKUMARAN Trading OS — Options Seller: IV Regime Engine

Classifies the current implied-volatility environment so the options
seller knows whether premium is worth selling and at what tenor to do it.

IV regime taxonomy (mirrors PR Sundar's teaching)
──────────────────────────────────────────────────
  CRUSHED  — IV percentile < 15: premium is historically cheap.
             Selling here means being underpaid for the risk.
             Gate: DO NOT SELL. Buy premium instead (debit spreads).

  LOW      — 15 ≤ percentile < 35: below-average premium.
             Gate: sell only on short tenors (≤ 2 DTE weekly).

  NORMAL   — 35 ≤ percentile < 65: fair premium, standard selling window.
             Gate: sell at standard tenors (5-7 DTE weekly).

  ELEVATED — 65 ≤ percentile < 85: above-average, attractive premium.
             Gate: sell at slightly wider strikes (lower delta target).

  EXTREME  — percentile ≥ 85: panic / event-driven spike.
             Markets don't panic without reason. Gate: DO NOT SELL.

Data sources
────────────
  - India VIX from NSE / yfinance (proxy for NIFTY ATM IV)
  - ATM IV from live options chain via options_selector._estimate_atm_iv
  - Historical VIX rolling window: 90-day and 252-day lookbacks

Instruments supported
─────────────────────
  NIFTY, BANKNIFTY, MIDCPNIFTY, FINNIFTY (NSE NFO)
  SENSEX, BANKEX (BSE BFO — VIX proxy only; no live BSE IV chain)

Design
──────
  Stateless per call. `get_iv_regime(instrument, spot, chain, vix_history)`
  is the primary entry point. Returns an IVRegime dataclass.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import numpy as np

logger = logging.getLogger(__name__)


# ── Regime labels ────────────────────────────────────────────
IVLabel = Literal["CRUSHED", "LOW", "NORMAL", "ELEVATED", "EXTREME"]

# ── Thresholds ───────────────────────────────────────────────
PERCENTILE_CRUSHED  = 15.0
PERCENTILE_LOW      = 35.0
PERCENTILE_ELEVATED = 65.0
PERCENTILE_EXTREME  = 85.0

# Suggested DTE per regime (calendar days to expiry to TARGET at entry)
SUGGESTED_DTE: dict[IVLabel, int] = {
    "CRUSHED":  0,   # don't sell
    "LOW":      2,   # short weekly only
    "NORMAL":   5,   # standard weekly
    "ELEVATED": 7,   # slightly longer — collect more but cap gamma
    "EXTREME":  0,   # don't sell
}

# Delta target per regime (absolute, e.g. 0.15 = 15-delta OTM)
DELTA_TARGET: dict[IVLabel, float] = {
    "CRUSHED":  0.00,
    "LOW":      0.20,   # closer strikes — more premium needed at low IV
    "NORMAL":   0.15,   # standard 15-delta
    "ELEVATED": 0.12,   # wider — let IV mean-revert more aggressively
    "EXTREME":  0.00,
}

# Instruments backed by direct VIX proxies
_NSE_INSTRUMENTS = {"NIFTY", "BANKNIFTY", "MIDCPNIFTY", "FINNIFTY"}
_BSE_INSTRUMENTS = {"SENSEX", "BANKEX"}


@dataclass
class IVRegime:
    """Output of one IV classification run."""
    instrument: str
    label: IVLabel
    vix_current: float          # India VIX or ATM IV as a percentage
    vix_percentile_90d: float   # percentile rank in 90-day window
    vix_percentile_1y: float    # percentile rank in 252-day window
    atm_iv: float               # ATM IV from live chain (0 if unavailable)
    sell_premium_ok: bool       # True if regime allows selling
    suggested_dte: int          # target calendar DTE at entry
    delta_target: float         # target absolute delta per leg
    reason: str = ""            # human-readable gate reason

    def as_dict(self) -> dict:
        return {
            "instrument":         self.instrument,
            "regime":             self.label,
            "vix_current":        round(self.vix_current, 2),
            "vix_percentile_90d": round(self.vix_percentile_90d, 1),
            "vix_percentile_1y":  round(self.vix_percentile_1y, 1),
            "atm_iv":             round(self.atm_iv, 2),
            "sell_premium_ok":    self.sell_premium_ok,
            "suggested_dte":      self.suggested_dte,
            "delta_target":       self.delta_target,
            "reason":             self.reason,
        }


# ── Percentile rank ──────────────────────────────────────────


def _percentile_rank(history: np.ndarray, value: float) -> float:
    """What percentage of `history` values is below `value`."""
    if len(history) == 0:
        return 50.0
    return float(np.mean(history < value) * 100)


# ── Classifier ───────────────────────────────────────────────


def classify_iv(
    instrument: str,
    vix_current: float,
    vix_history_90d: np.ndarray,
    vix_history_1y: np.ndarray,
    atm_iv: float = 0.0,
) -> IVRegime:
    """Classify the IV regime from VIX history arrays.

    Args:
        instrument:        e.g. "BANKNIFTY", "NIFTY", "SENSEX"
        vix_current:       today's India VIX (or ATM IV if VIX unavailable)
        vix_history_90d:   90 prior VIX daily closes (numpy array)
        vix_history_1y:    252 prior VIX daily closes (numpy array)
        atm_iv:            ATM IV from the live options chain (optional)

    Returns:
        IVRegime dataclass.
    """
    inst = instrument.upper()
    p90  = _percentile_rank(vix_history_90d, vix_current)
    p1y  = _percentile_rank(vix_history_1y, vix_current)

    # Primary classification is on 1Y percentile (avoids mean-reversion bias
    # from short windows; 90d is surfaced for operator awareness).
    pct = p1y

    if pct < PERCENTILE_CRUSHED:
        label: IVLabel = "CRUSHED"
        sell_ok = False
        reason = f"IV at {pct:.0f}th percentile — historically cheap, risk not priced"

    elif pct < PERCENTILE_LOW:
        label = "LOW"
        sell_ok = True
        reason = f"IV at {pct:.0f}th percentile — below avg; short tenor only"

    elif pct < PERCENTILE_ELEVATED:
        label = "NORMAL"
        sell_ok = True
        reason = f"IV at {pct:.0f}th percentile — fair premium window"

    elif pct < PERCENTILE_EXTREME:
        label = "ELEVATED"
        sell_ok = True
        reason = f"IV at {pct:.0f}th percentile — rich premium; widen strikes"

    else:
        label = "EXTREME"
        sell_ok = False
        reason = (
            f"IV at {pct:.0f}th percentile — panic/event spike; "
            "markets don't panic without reason"
        )

    regime = IVRegime(
        instrument=inst,
        label=label,
        vix_current=vix_current,
        vix_percentile_90d=p90,
        vix_percentile_1y=p1y,
        atm_iv=atm_iv,
        sell_premium_ok=sell_ok,
        suggested_dte=SUGGESTED_DTE[label],
        delta_target=DELTA_TARGET[label],
        reason=reason,
    )

    logger.info(
        "IV regime %s: %s (VIX=%.1f, p90=%.0f, p1y=%.0f, sell=%s)",
        inst, label, vix_current, p90, p1y, sell_ok,
    )
    return regime


# ── Live fetch helpers ───────────────────────────────────────


def _fetch_vix_history(days: int = 252) -> np.ndarray:
    """Download India VIX history via yfinance. Returns daily closes."""
    try:
        import yfinance as yf
        df = yf.download("^INDIAVIX", period=f"{days}d", progress=False, auto_adjust=True)
        if df is None or df.empty:
            return np.array([])
        closes = df["Close"].dropna().values.flatten().astype(float)
        return closes
    except Exception as e:
        logger.warning("VIX history fetch failed: %s", e)
        return np.array([])


def _fetch_vix_current() -> float:
    """Fetch the latest India VIX value."""
    try:
        from mcp_server.data_provider import get_provider
        provider = get_provider()
        quote = provider.nse.get_quote("INDIA VIX")
        if quote and isinstance(quote, dict):
            return float(quote.get("lastPrice", quote.get("ltp", 0)) or 0)
    except Exception:
        pass

    # Fallback: yfinance
    hist = _fetch_vix_history(days=5)
    return float(hist[-1]) if len(hist) > 0 else 0.0


def _fetch_atm_iv(instrument: str, spot: float, chain: dict) -> float:
    """Extract ATM IV from a live options chain dict."""
    if not chain:
        return 0.0
    try:
        from mcp_server.options_selector import _estimate_atm_iv_from_chain
        iv = _estimate_atm_iv_from_chain(chain, spot)
        return float(iv or 0.0)
    except Exception as e:
        logger.debug("ATM IV extraction failed: %s", e)
        return 0.0


def get_iv_regime(
    instrument: str,
    spot: float = 0.0,
    chain: dict | None = None,
    vix_history: np.ndarray | None = None,
) -> IVRegime:
    """Convenience entry point — fetches VIX history if not provided.

    Suitable for direct use from routes or strategy entry checks.
    Pass `vix_history` to avoid a live download (e.g. in backtests).

    Args:
        instrument:   "BANKNIFTY", "NIFTY", etc.
        spot:         current underlying price (for ATM IV extraction)
        chain:        live options chain dict from options_selector
        vix_history:  pre-fetched array; fetched if None

    Returns:
        IVRegime dataclass.
    """
    if vix_history is None or len(vix_history) == 0:
        vix_history = _fetch_vix_history(days=252)

    vix_now = _fetch_vix_current()
    atm_iv  = _fetch_atm_iv(instrument, spot, chain or {})

    hist_90  = vix_history[-90:]  if len(vix_history) >= 90  else vix_history
    hist_1y  = vix_history[-252:] if len(vix_history) >= 252 else vix_history

    return classify_iv(
        instrument=instrument,
        vix_current=vix_now,
        vix_history_90d=hist_90,
        vix_history_1y=hist_1y,
        atm_iv=atm_iv,
    )
