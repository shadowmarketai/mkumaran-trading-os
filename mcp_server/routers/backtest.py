"""Backtest — historical strategy testing + RRMS position sizing.

Extracted from mcp_server.mcp_server in Phase 3b of the router split.
6 routes moved verbatim.

Clusters:
  - RRMS position sizing (dashboard-facing + n8n)
  - Strategy backtest (single + all-strategy comparison)
  - Statistical validation (Monte Carlo / Bootstrap / Walk-Forward)
  - Dashboard-friendly /api/backtest variants

All handlers wrap mcp_server.backtester helpers. Pure computation —
no live broker or DB state.
"""
import asyncio
import logging
from dataclasses import asdict

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["backtest"])


# ── Request models ─────────────────────────────────────────────────


class BacktestRequest(BaseModel):
    ticker: str
    strategy: str = "rrms"
    days: int = 180


class BacktestCompareRequest(BaseModel):
    ticker: str
    days: int = 1095


# ── RRMS position sizing ───────────────────────────────────────────


@router.post("/tools/run_rrms")
async def tool_run_rrms(
    ticker: str,
    cmp: float = 0,
    ltrp: float = 0,
    pivot_high: float = 0,
    direction: str = "LONG",
):
    """Run RRMS position sizing calculation."""
    from mcp_server.rrms_engine import RRMSEngine

    engine = RRMSEngine()

    if cmp <= 0:
        # Try to fetch live price via yfinance
        from mcp_server.nse_scanner import get_stock_data

        df = await asyncio.to_thread(get_stock_data, ticker, "5d", "1d")
        if df is not None and not df.empty:
            cmp = float(df["Close"].iloc[-1])
        else:
            return {"status": "error", "message": "CMP required (auto-fetch failed)"}

    result = engine.calculate(ticker, cmp, ltrp, pivot_high, direction)
    return {"status": "ok", "tool": "run_rrms", **asdict(result)}


# ── Strategy backtests ─────────────────────────────────────────────


@router.post("/tools/backtest_confluence")
async def tool_backtest_confluence(ticker: str, days: int = 365):
    """Compare all strategies side-by-side on a stock."""
    from mcp_server.backtester import run_backtest_all_strategies

    result = run_backtest_all_strategies(ticker, days=days)
    return {"status": "ok", "tool": "backtest_confluence", **result}


@router.post("/tools/backtest_strategy")
async def tool_backtest_strategy(
    ticker: str,
    strategy: str = "rrms",
    days: int = 365,
):
    """Backtest a strategy on historical data."""
    from mcp_server.backtester import run_backtest

    result = run_backtest(ticker, strategy=strategy, days=days)
    return {"status": "ok", "tool": "backtest_strategy", **result}


@router.post("/tools/backtest_validate")
async def tool_backtest_validate(
    ticker: str,
    strategy: str = "rrms",
    days: int = 1095,
    n_simulations: int = 1000,
    n_bootstrap: int = 1000,
    n_windows: int = 5,
):
    """Run a backtest and then put its results through three statistical
    validation tests — Monte Carlo permutation, Bootstrap Sharpe CI, and
    Walk-Forward consistency — to check whether the observed edge is real
    or a lucky path. Adapted from Vibe-Trading's validation suite.

    Interpretation guide:
      - monte_carlo.p_value_sharpe < 0.05  → strategy beats random ordering
      - bootstrap.ci_crosses_zero == false → Sharpe is robustly positive
      - walk_forward.consistency_rate >= 0.6 → durable across regimes
    """
    from mcp_server.backtest_validation import run_full_validation, summarise
    from mcp_server.backtester import run_backtest

    def _compute() -> dict:
        bt = run_backtest(ticker, strategy=strategy, days=days)
        validation = run_full_validation(
            bt,
            monte_carlo_kwargs={"n_simulations": n_simulations},
            bootstrap_kwargs={"n_bootstrap": n_bootstrap},
            walk_forward_kwargs={"n_windows": n_windows},
        )
        return {
            "status": "ok",
            "tool": "backtest_validate",
            "ticker": ticker,
            "strategy": strategy,
            "summary": summarise(validation),
            "backtest_metrics": {
                k: bt.get(k) for k in (
                    "total_trades", "win_rate", "profit_factor",
                    "sharpe_ratio", "max_drawdown_pct",
                )
            },
            "validation": validation,
        }

    # Monte Carlo + bootstrap loops are CPU-bound; run off the event loop.
    return await asyncio.to_thread(_compute)


# ── Dashboard-friendly wrappers ───────────────────────────────────


@router.post("/api/backtest")
async def api_backtest(req: BacktestRequest):
    """Run backtest from dashboard."""
    from mcp_server.backtester import run_backtest

    result = run_backtest(req.ticker, strategy=req.strategy, days=req.days)
    return result


@router.post("/api/backtest/compare")
async def api_backtest_compare(req: BacktestCompareRequest):
    """Compare all 6 strategies side-by-side with equity curves."""
    from mcp_server.backtester import run_backtest_all_strategies

    result = run_backtest_all_strategies(req.ticker, days=req.days)

    # Reshape comparison into strategies array for frontend
    strategies = result.get("comparison", [])

    # Extract equity curves per strategy from detail results
    equity_curves: dict = {}
    details = result.get("details", {})
    for strat_name, detail in details.items():
        if isinstance(detail, dict) and "equity_curve" in detail:
            equity_curves[strat_name] = detail["equity_curve"]

    return {
        "ticker": result.get("ticker", req.ticker),
        "period": result.get("period", f"{req.days} days"),
        "strategies": strategies,
        "equity_curves": equity_curves,
        "best_strategy": result.get("best_strategy", "none"),
    }
