"""
MKUMARAN Trading OS - Live Monthly Momentum Rebalancer (Nifty 500)

Strategy: 12-month trailing return momentum with 1-month skip (TIER_1 validated).
Universe: Nifty 500 (~504 symbols from data/nifty500.json).
Rebalance: Monthly. Hold top 20% of eligible stocks by ret_12m.

1-month skip: ranks on price[t-30] / price[t-282] to avoid short-term mean
reversion. Backtest confirms +4.7pp WinRate improvement vs no-skip variant.

Validation reference: reports/momentum_nifty500_2026-05-25.md (--skip-days 30)
  CAGR 42.1%, Sharpe 1.41, Alpha +10.9pp vs EW, WinRate 60.9%

NOTE: RRMS gate is NOT applied here. This is a portfolio-level strategy
with equal-weight sizing across N positions. RRMS gates single-trade risk
as a fraction of capital - incompatible with a multi-position equal-weight
approach. Position size = portfolio_value / N (one equal slice per stock).

Known divergence from backtest: HOLD positions are not re-sized monthly
(equal-weight drift). Backtest assumes daily equal-weight rebalance within
the month; this is a monthly snapshot. For small drift this is acceptable.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Constants matching the validated backtest exactly ─────────
# NOTE: LOOKBACK_CALENDAR_DAYS is subtracted as calendar days (not trading
# days) to match the backtest's lookback_date calculation:
#   rank_date    = today - SKIP_CALENDAR_DAYS          (1-month skip)
#   lookback_date = rank_date - LOOKBACK_CALENDAR_DAYS  (price 282 days ago)
SKIP_CALENDAR_DAYS: int = 30        # 1-month skip: avoids short-term mean reversion
LOOKBACK_CALENDAR_DAYS: int = 252   # lookback window from rank_date
TOP_QUINTILE_PCT: int = 20          # top 20% of eligible stocks
PRICE_TOLERANCE_DAYS: int = 10      # tolerance window for date-based lookup

# Data fetch covers today - 460d, well beyond the 282-day lookback
DATA_FETCH_DAYS: int = 460

BROKERAGE_PER_ORDER: Decimal = Decimal("20.0")
STT_SELL_PCT: Decimal = Decimal("0.001")
EXCHANGE_PCT: Decimal = Decimal("0.0000345")
GST_PCT: Decimal = Decimal("0.18")
STAMP_BUY_PCT: Decimal = Decimal("0.00015")
SLIPPAGE_PCT: Decimal = Decimal("0.0005")

NIFTY500_FILE = Path("data/nifty500.json")
STATE_FILE = Path("data/momentum_portfolio_live.json")

YF_SUFFIX = ".NS"

# ── Data classes ──────────────────────────────────────────────

@dataclass
class RankedStock:
    rank: int
    ticker: str
    ret_12m: float        # raw ratio (e.g. 0.41 = +41%)
    ret_12m_pct: float    # display percentage (41.0)


@dataclass
class RebalancePlan:
    rebalance_date: str          # ISO date string
    n_eligible: int              # stocks with enough data
    n_portfolio: int             # target portfolio size (top quintile)
    portfolio_value_inr: Decimal
    position_size_inr: Decimal   # = portfolio_value_inr / n_portfolio
    enters: list[RankedStock] = field(default_factory=list)
    exits: list[str] = field(default_factory=list)
    holds: list[str] = field(default_factory=list)
    rankings: list[RankedStock] = field(default_factory=list)   # full top-quintile
    estimated_cost_pct: float = 0.0
    estimated_cost_inr: Decimal = Decimal(0)
    is_first_run: bool = False
    fetch_errors: list[str] = field(default_factory=list)


# ── Universe loader ───────────────────────────────────────────

def load_nifty500() -> list[str]:
    """Load Nifty 500 symbols, filtering placeholder DUMMY entries."""
    with NIFTY500_FILE.open(encoding="utf-8") as f:
        data = json.load(f)
    symbols = [s for s in data["symbols"] if "DUMMY" not in s.upper()]
    logger.info("Nifty500 universe: %d symbols (after filtering DUMMY)", len(symbols))
    return symbols


# ── Price fetching ────────────────────────────────────────────

def _date_to_str(d: date) -> str:
    return d.isoformat()


def _load_prices_db(
    symbols: list[str], start_str: str, end_str: str
) -> dict[str, dict[date, float]]:
    """Try ohlcv_cache DB first. Returns partial dict on failure."""
    prices: dict[str, dict[date, float]] = {}
    try:
        from sqlalchemy import text

        from mcp_server.db import engine
        with engine.connect() as conn:
            for sym in symbols:
                rows = conn.execute(
                    text(
                        "SELECT bar_date, close FROM ohlcv_cache "
                        "WHERE ticker=:s AND interval='1d' "
                        "AND bar_date BETWEEN :s0 AND :e "
                        "AND close IS NOT NULL AND close > 0 "
                        "ORDER BY bar_date"
                    ),
                    {"s": sym, "s0": start_str, "e": end_str},
                ).fetchall()
                if rows:
                    prices[sym] = {
                        (r.bar_date.date() if hasattr(r.bar_date, "date") else r.bar_date): float(r.close)
                        for r in rows
                    }
        logger.info("DB cache: %d symbols loaded", len(prices))
    except Exception as exc:
        logger.warning("DB unavailable (%s) - using yfinance for all", exc.__class__.__name__)
    return prices


def _load_prices_yfinance(
    symbols: list[str], start_str: str, end_str: str, batch_size: int = 50
) -> tuple[dict[str, dict[date, float]], list[str]]:
    """Fetch prices via yfinance in batches. Returns (prices, errors)."""
    import pandas as pd
    import yfinance as yf  # type: ignore

    prices: dict[str, dict[date, float]] = {}
    errors: list[str] = []

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        batch_yf = [s + YF_SUFFIX for s in batch]
        logger.info(
            "yfinance batch %d/%d (%d symbols)",
            i // batch_size + 1,
            (len(symbols) - 1) // batch_size + 1,
            len(batch),
        )
        try:
            raw = yf.download(
                batch_yf,
                start=start_str,
                end=end_str,
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if raw.empty:
                errors.extend(batch)
                continue
            for sym, yf_sym in zip(batch, batch_yf):
                try:
                    if isinstance(raw.columns, pd.MultiIndex):
                        closes = raw["Close"][yf_sym].dropna()
                    else:
                        closes = raw["Close"].dropna()
                    if len(closes) >= 100:
                        prices[sym] = {d.date(): float(c) for d, c in closes.items()}
                except Exception:
                    errors.append(sym)
        except Exception as exc:
            logger.error("yfinance batch failed starting %s: %s", batch[0], exc)
            errors.extend(batch)

    return prices, errors


def fetch_all_prices(
    symbols: list[str], today: date
) -> tuple[dict[str, dict[date, float]], list[str]]:
    """
    Load 15 months of daily prices (DB cache first, yfinance fallback).
    Returns ({ticker: {date: close}}, error_list).
    """
    start_date = today - timedelta(days=DATA_FETCH_DAYS)
    start_str = _date_to_str(start_date)
    end_str = _date_to_str(today)

    # DB first
    db_prices = _load_prices_db(symbols, start_str, end_str)

    # yfinance for missing or thin DB entries (< 100 bars)
    need_yfinance = [s for s in symbols if s not in db_prices or len(db_prices[s]) < 100]
    logger.info("DB hit: %d  |  yfinance needed: %d", len(db_prices), len(need_yfinance))

    yf_prices, errors = _load_prices_yfinance(need_yfinance, start_str, end_str)

    all_prices = {**db_prices, **yf_prices}
    logger.info(
        "Total prices loaded: %d/%d symbols (%d errors)",
        len(all_prices), len(symbols), len(errors),
    )
    return all_prices, errors


# ── Price point lookup (tolerance-aware) ─────────────────────

def _sorted_dates(price_dict: dict[date, float]) -> list[date]:
    return sorted(price_dict.keys())


def _get_price_at(
    price_dict: dict[date, float],
    sorted_dates: list[date],
    target: date,
    tolerance: int = PRICE_TOLERANCE_DAYS,
) -> float | None:
    """Return close price nearest to target within tolerance days."""
    candidates = [d for d in sorted_dates if abs((d - target).days) <= tolerance]
    if not candidates:
        return None
    best = min(candidates, key=lambda d: abs((d - target).days))
    return price_dict.get(best)


# ── Ranking ───────────────────────────────────────────────────

def rank_by_12m_return(
    prices: dict[str, dict[date, float]],
    rank_date: date,
    lookback_calendar_days: int = LOOKBACK_CALENDAR_DAYS,
) -> tuple[list[RankedStock], int]:
    """
    Rank stocks by trailing return over lookback_calendar_days.

    Matches backtest exactly:
      lookback_date = rank_date - timedelta(days=252)
      ret = price_at(rank_date) / price_at(lookback_date) - 1
    Eligibility: any stock where both price points exist within tolerance.
    """
    lookback_date = rank_date - timedelta(days=lookback_calendar_days)
    eligible: list[tuple[str, float]] = []

    for sym, pd_data in prices.items():
        sym_dates = _sorted_dates(pd_data)
        p_now = _get_price_at(pd_data, sym_dates, rank_date)
        p_old = _get_price_at(pd_data, sym_dates, lookback_date)
        if p_now and p_old and p_old > 0:
            eligible.append((sym, p_now / p_old - 1.0))

    n_eligible = len(eligible)
    eligible.sort(key=lambda x: x[1], reverse=True)

    ranked = [
        RankedStock(
            rank=i + 1,
            ticker=t,
            ret_12m=r,
            ret_12m_pct=round(r * 100, 2),
        )
        for i, (t, r) in enumerate(eligible)
    ]
    return ranked, n_eligible


def top_quintile(ranked: list[RankedStock], n_eligible: int, pct: int = TOP_QUINTILE_PCT) -> list[RankedStock]:
    n_portfolio = max(1, int(n_eligible * pct / 100))
    return ranked[:n_portfolio]


# ── State management ──────────────────────────────────────────

def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load state %s: %s", STATE_FILE, exc)
        return {}


def save_state(plan: RebalancePlan) -> None:
    holdings = {s.ticker: {"rank": s.rank, "ret_12m_pct": s.ret_12m_pct} for s in plan.rankings}
    state = {
        "last_rebalance_date": plan.rebalance_date,
        "n_portfolio": plan.n_portfolio,
        "portfolio_value_inr": str(plan.portfolio_value_inr),
        "position_size_inr": str(plan.position_size_inr),
        "holdings": holdings,
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    logger.info("Saved portfolio state -> %s", STATE_FILE)


# ── Cost estimation ────────────────────────────────────────────

def estimate_trade_cost(
    n_trades: int,
    position_size_inr: Decimal,
    portfolio_value_inr: Decimal,
) -> tuple[Decimal, float]:
    """
    Estimate round-trip cost for n_trades.
    cost_pct = total_cost / portfolio_value (not per-trade value).
    """
    if n_trades == 0 or position_size_inr <= 0:
        return Decimal(0), 0.0

    per_trade = (
        BROKERAGE_PER_ORDER * 2
        + position_size_inr * STT_SELL_PCT
        + position_size_inr * EXCHANGE_PCT * 2
        + (BROKERAGE_PER_ORDER * 2 + position_size_inr * EXCHANGE_PCT * 2) * GST_PCT
        + position_size_inr * STAMP_BUY_PCT
        + position_size_inr * SLIPPAGE_PCT * 2
    )
    total = (per_trade * n_trades).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    pct = float(total / portfolio_value_inr * 100) if portfolio_value_inr > 0 else 0.0
    return total, round(pct, 4)


# ── Main rebalancer ───────────────────────────────────────────

def compute_rebalance_plan(
    portfolio_value_inr: Decimal,
    today: date | None = None,
) -> RebalancePlan:
    """
    Compute the full monthly rebalance plan.

    1. Load Nifty 500 universe (filtered)
    2. Fetch 15 months of prices (DB cache -> yfinance fallback)
    3. Rank by 252-calendar-day trailing return (matches backtest)
    4. Take top 20% of eligible stocks
    5. Diff vs saved state -> ENTER / EXIT / HOLD
    6. Compute equal-weight position sizes and estimated costs
    Returns RebalancePlan (does NOT save state - caller decides).
    """
    if today is None:
        today = date.today()

    tickers = load_nifty500()
    prices, errors = fetch_all_prices(tickers, today)

    # 1-month skip: rank on price[today-30] / price[today-282]
    rank_date = today - timedelta(days=SKIP_CALENDAR_DAYS)
    ranked_all, n_eligible = rank_by_12m_return(prices, rank_date=rank_date)
    top_stocks = top_quintile(ranked_all, n_eligible)
    n_portfolio = len(top_stocks)

    position_size = (
        (portfolio_value_inr / n_portfolio).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if n_portfolio > 0
        else Decimal(0)
    )

    state = load_state()
    is_first_run = "holdings" not in state or not state["holdings"]
    prev_holdings: set[str] = set(state.get("holdings", {}).keys())
    new_holdings: set[str] = {s.ticker for s in top_stocks}

    enters = [s for s in top_stocks if s.ticker not in prev_holdings]
    exits = sorted(prev_holdings - new_holdings)
    holds = sorted(prev_holdings & new_holdings)

    n_trades = len(enters) + len(exits)
    est_cost_inr, est_cost_pct = estimate_trade_cost(n_trades, position_size, portfolio_value_inr)

    return RebalancePlan(
        rebalance_date=today.isoformat(),
        n_eligible=n_eligible,
        n_portfolio=n_portfolio,
        portfolio_value_inr=portfolio_value_inr,
        position_size_inr=position_size,
        enters=enters,
        exits=exits,
        holds=holds,
        rankings=top_stocks,
        estimated_cost_pct=est_cost_pct,
        estimated_cost_inr=est_cost_inr,
        is_first_run=is_first_run,
        fetch_errors=errors,
    )


# ── Telegram formatter ────────────────────────────────────────

def format_telegram_message(plan: RebalancePlan) -> str:
    lines: list[str] = []
    header = "FIRST RUN - OPENING PORTFOLIO" if plan.is_first_run else "MONTHLY REBALANCE"
    lines.append(f"*Momentum Portfolio - {header}*")
    lines.append(f"Date: {plan.rebalance_date}")
    lines.append(
        f"Portfolio: Rs.{plan.portfolio_value_inr:,.0f} | "
        f"Positions: {plan.n_portfolio} | "
        f"Size/pos: Rs.{plan.position_size_inr:,.0f}"
    )
    lines.append(f"Eligible universe: {plan.n_eligible} stocks")
    lines.append("")

    if plan.is_first_run:
        lines.append(f"*ENTER ({len(plan.enters)} stocks - opening all positions):*")
        for s in plan.enters[:20]:
            lines.append(f"  {s.rank}. {s.ticker}  +{s.ret_12m_pct:.1f}%")
        if len(plan.enters) > 20:
            lines.append(f"  ... and {len(plan.enters) - 20} more")
    else:
        if plan.enters:
            lines.append(f"*BUY ({len(plan.enters)} new entries):*")
            for s in plan.enters[:10]:
                lines.append(f"  {s.rank}. {s.ticker}  +{s.ret_12m_pct:.1f}%")
            if len(plan.enters) > 10:
                lines.append(f"  ... and {len(plan.enters) - 10} more")
            lines.append("")
        if plan.exits:
            lines.append(f"*SELL ({len(plan.exits)} exits):*")
            for t in plan.exits[:10]:
                lines.append(f"  {t}")
            if len(plan.exits) > 10:
                lines.append(f"  ... and {len(plan.exits) - 10} more")
            lines.append("")
        if plan.holds:
            lines.append(f"*HOLD ({len(plan.holds)} unchanged)*")
            lines.append("")

    lines.append(
        f"Est. cost: Rs.{plan.estimated_cost_inr:,.0f} "
        f"({plan.estimated_cost_pct:.3f}% of portfolio)"
    )
    if plan.fetch_errors:
        lines.append(f"\nWARNING: {len(plan.fetch_errors)} symbols had no price data (skipped)")
    return "\n".join(lines)


# ── CLI entry point ───────────────────────────────────────────

def _cli_main() -> None:
    import argparse

    from mcp_server.config import settings

    parser = argparse.ArgumentParser(
        description="Monthly momentum rebalancer (Nifty 500, 1-month skip, 252-day trailing return)"
    )
    parser.add_argument("--portfolio-value", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Do NOT save state")
    parser.add_argument("--date", type=str, default=None, help="Override date YYYY-MM-DD")
    args = parser.parse_args()

    pv_raw = args.portfolio_value or float(settings.MOMENTUM_PORTFOLIO_VALUE)
    portfolio_value = Decimal(str(pv_raw))
    today = date.fromisoformat(args.date) if args.date else None

    plan = compute_rebalance_plan(portfolio_value, today=today)

    sep = "-" * 64
    print(sep)
    print(f"MOMENTUM REBALANCER - {'DRY RUN - ' if args.dry_run else ''}{plan.rebalance_date}")
    print(sep)

    if plan.is_first_run:
        print("*** FIRST RUN - No existing portfolio state found ***")
        print(f"Opening {plan.n_portfolio} positions at Rs.{plan.position_size_inr:,.0f} each")
        print(f"Total deployment: Rs.{plan.portfolio_value_inr:,.0f}")
        print()
        print(f"ENTER ({len(plan.enters)} stocks):")
        for s in plan.enters:
            print(f"  {s.rank:3d}. {s.ticker:<20}  12m_ret: {s.ret_12m_pct:+.1f}%")
    else:
        print(f"Portfolio value  : Rs.{plan.portfolio_value_inr:,.0f}")
        print(f"Positions        : {plan.n_portfolio}")
        print(f"Position size    : Rs.{plan.position_size_inr:,.0f} each")
        print(f"Eligible universe: {plan.n_eligible} stocks")
        print()
        if plan.enters:
            print(f"BUY - {len(plan.enters)} new entries:")
            for s in plan.enters:
                print(f"  {s.rank:3d}. {s.ticker:<20}  12m_ret: {s.ret_12m_pct:+.1f}%")
            print()
        if plan.exits:
            print(f"SELL - {len(plan.exits)} exits:")
            for t in plan.exits:
                print(f"       {t}")
            print()
        if plan.holds:
            print(f"HOLD - {len(plan.holds)} unchanged: {', '.join(plan.holds[:15])}")
            if len(plan.holds) > 15:
                print(f"       ... and {len(plan.holds) - 15} more")
            print()

    print(f"Estimated cost   : Rs.{plan.estimated_cost_inr:,.0f} ({plan.estimated_cost_pct:.3f}%)")

    if plan.fetch_errors:
        print(f"\nWARNING: {len(plan.fetch_errors)} symbols had no price data:")
        print(f"  {', '.join(plan.fetch_errors[:20])}")
        if len(plan.fetch_errors) > 20:
            print(f"  ... and {len(plan.fetch_errors) - 20} more")

    print(sep)
    print(f"Full top-quintile rankings ({len(plan.rankings)} stocks):")
    enter_set = {s.ticker for s in plan.enters}
    for s in plan.rankings:
        flag = "NEW " if s.ticker in enter_set else "HOLD" if s.ticker in plan.holds else "    "
        print(f"  {flag} {s.rank:3d}. {s.ticker:<20}  {s.ret_12m_pct:+.1f}%")
    print(sep)

    if not args.dry_run:
        save_state(plan)
        print(f"State saved -> {STATE_FILE}")
    else:
        print("DRY RUN - state NOT saved")
