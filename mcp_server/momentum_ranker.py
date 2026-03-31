"""
MKUMARAN Trading OS — Momentum Ranking Module

GreenSigma-style momentum scoring and monthly rebalance signals.
Ranks NSE universe by weighted multi-period returns + inverse volatility.

Score = 0.4*norm(12m_ret) + 0.3*norm(6m_ret) + 0.2*norm(3m_ret) + 0.1*norm(inv_vol)

All factors min-max normalized to [0,1] across the full universe before weighting.
"""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from mcp_server.nse_scanner import get_stock_data, _get_nse_universe
from mcp_server.portfolio_risk import get_sector

logger = logging.getLogger(__name__)

# ── Persistence ─────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PORTFOLIO_FILE = DATA_DIR / "momentum_portfolio.json"

# ── Weights ─────────────────────────────────────────────────
W_12M = 0.4
W_6M = 0.3
W_3M = 0.2
W_VOL = 0.1


@dataclass
class MomentumStock:
    rank: int
    ticker: str
    sector: str
    score: float
    ret_3m: float
    ret_6m: float
    ret_12m: float
    volatility: float
    prev_rank: Optional[int] = None


@dataclass
class RebalanceSignal:
    ticker: str
    sector: str
    action: str  # "BUY" or "SELL"
    score: float
    reason: str


@dataclass
class MomentumPortfolio:
    holdings: list[str]
    ranked_at: str
    top_n: int


# ── Score Calculation ───────────────────────────────────────

def calculate_momentum_score(ticker: str) -> Optional[dict]:
    """
    Calculate raw momentum factors for a single ticker.

    Returns dict with ret_3m, ret_6m, ret_12m, volatility or None on failure.
    Uses existing get_stock_data() with 1y period.
    """
    df = get_stock_data(ticker, period="1y", interval="1d")
    if df.empty or len(df) < 60:
        logger.debug("Insufficient data for %s (%d bars)", ticker, len(df))
        return None

    close = df["close"]

    # Returns over different periods
    n = len(close)
    ret_3m = (close.iloc[-1] / close.iloc[max(0, n - 63)] - 1) * 100 if n >= 63 else None
    ret_6m = (close.iloc[-1] / close.iloc[max(0, n - 126)] - 1) * 100 if n >= 126 else None
    ret_12m = (close.iloc[-1] / close.iloc[0] - 1) * 100

    # Daily return standard deviation (annualized)
    daily_ret = close.pct_change().dropna()
    volatility = float(daily_ret.std() * np.sqrt(252) * 100)

    if ret_3m is None or ret_6m is None:
        logger.debug("Not enough history for 3m/6m returns: %s", ticker)
        return None

    if volatility == 0:
        return None

    return {
        "ticker": ticker,
        "ret_3m": round(float(ret_3m), 2),
        "ret_6m": round(float(ret_6m), 2),
        "ret_12m": round(float(ret_12m), 2),
        "volatility": round(volatility, 2),
    }


def _min_max_normalize(values: list[float]) -> list[float]:
    """Normalize values to [0,1] range. Returns all 0s if constant."""
    if not values:
        return []
    mn, mx = min(values), max(values)
    if mx == mn:
        return [0.0] * len(values)
    return [(v - mn) / (mx - mn) for v in values]


def rank_universe(top_n: int = 10) -> list[MomentumStock]:
    """
    Score and rank all stocks in the NSE universe.

    1. Fetch raw factors for every stock
    2. Min-max normalize each factor across universe
    3. Compute weighted composite score
    4. Return top_n sorted by score descending
    """
    universe = _get_nse_universe()
    logger.info("Momentum scan: scoring %d stocks...", len(universe))

    raw: list[dict] = []
    for ticker in universe:
        result = calculate_momentum_score(ticker)
        if result:
            raw.append(result)

    if not raw:
        logger.warning("Momentum scan: no valid scores computed")
        return []

    # Normalize each factor
    ret_12m_vals = [r["ret_12m"] for r in raw]
    ret_6m_vals = [r["ret_6m"] for r in raw]
    ret_3m_vals = [r["ret_3m"] for r in raw]
    inv_vol_vals = [1.0 / r["volatility"] for r in raw]

    n12 = _min_max_normalize(ret_12m_vals)
    n6 = _min_max_normalize(ret_6m_vals)
    n3 = _min_max_normalize(ret_3m_vals)
    nvol = _min_max_normalize(inv_vol_vals)

    # Composite score
    scored: list[dict] = []
    for i, r in enumerate(raw):
        score = W_12M * n12[i] + W_6M * n6[i] + W_3M * n3[i] + W_VOL * nvol[i]
        scored.append({**r, "score": round(score, 4)})

    scored.sort(key=lambda x: x["score"], reverse=True)

    # Load previous rankings for rank-change arrows
    prev_portfolio = get_momentum_portfolio()
    prev_rank_map: dict[str, int] = {}
    if prev_portfolio and prev_portfolio.get("rankings"):
        for item in prev_portfolio["rankings"]:
            prev_rank_map[item["ticker"]] = item["rank"]

    result: list[MomentumStock] = []
    for rank, s in enumerate(scored[:top_n], 1):
        result.append(MomentumStock(
            rank=rank,
            ticker=s["ticker"],
            sector=get_sector(s["ticker"]),
            score=s["score"],
            ret_3m=s["ret_3m"],
            ret_6m=s["ret_6m"],
            ret_12m=s["ret_12m"],
            volatility=s["volatility"],
            prev_rank=prev_rank_map.get(s["ticker"]),
        ))

    logger.info("Momentum scan complete: top %d of %d stocks scored", len(result), len(raw))
    return result


# ── Rebalance Signal Generation ─────────────────────────────

def generate_rebalance_signals(
    current_holdings: list[str],
    new_rankings: list[MomentumStock],
    top_n: int = 10,
) -> list[RebalanceSignal]:
    """
    Compare current portfolio to new rankings and emit BUY/SELL signals.
    """
    new_tickers = {s.ticker for s in new_rankings[:top_n]}
    new_map = {s.ticker: s for s in new_rankings[:top_n]}
    current_set = set(current_holdings)

    signals: list[RebalanceSignal] = []

    # SELL: in current but not in new top_n
    for ticker in sorted(current_set - new_tickers):
        signals.append(RebalanceSignal(
            ticker=ticker,
            sector=get_sector(ticker),
            action="SELL",
            score=0.0,
            reason=f"Dropped out of top {top_n} momentum ranking",
        ))

    # BUY: in new top_n but not in current
    for ticker in sorted(new_tickers - current_set):
        stock = new_map[ticker]
        signals.append(RebalanceSignal(
            ticker=ticker,
            sector=stock.sector,
            action="BUY",
            score=stock.score,
            reason=f"Entered top {top_n} at rank #{stock.rank}",
        ))

    return signals


# ── Portfolio Persistence ───────────────────────────────────

def get_momentum_portfolio() -> Optional[dict]:
    """Load saved momentum portfolio from JSON file."""
    if not PORTFOLIO_FILE.exists():
        return None
    try:
        return json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to read momentum portfolio: %s", e)
        return None


def save_momentum_portfolio(
    rankings: list[MomentumStock],
    signals: list[RebalanceSignal],
    top_n: int = 10,
) -> dict:
    """Save rankings + signals to JSON for caching and dashboard."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    payload = {
        "ranked_at": datetime.now().isoformat(),
        "top_n": top_n,
        "holdings": [s.ticker for s in rankings[:top_n]],
        "rankings": [asdict(s) for s in rankings],
        "signals": [asdict(s) for s in signals],
    }

    PORTFOLIO_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Momentum portfolio saved: %d rankings, %d signals", len(rankings), len(signals))
    return payload
