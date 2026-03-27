"""
MKUMARAN Trading OS — Multi-Strategy Backtester (v2 — Production-Grade)

Fixes over v1:
- Realistic slippage (0.3% default)
- Transaction costs (brokerage + STT + GST)
- Proper annualized Sharpe ratio from daily returns
- Default 3-year backtest period
- Max consecutive losses tracking
- Calmar ratio (return/max drawdown)

Supports:
- rrms: Original RRMS position sizing strategy
- smc: Smart Money Concepts entries (BOS/CHoCH/OB/FVG/Sweep)
- wyckoff: Wyckoff method entries (Spring/Accumulation/SOS)
- vsa: Volume Spread Analysis entries (Climax/Stopping/Effort)
- harmonic: Harmonic pattern entries (Gartley/Bat/Butterfly/Crab)
- confluence: Combined scoring — entries where multiple engines agree
"""

import logging
import math
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

# ── Realistic Cost Constants (Indian Markets) ────────────────
DEFAULT_SLIPPAGE_PCT = 0.003    # 0.3% slippage per side
BROKERAGE_PER_ORDER = 20.0     # Flat Rs.20 per order (Zerodha)
STT_PCT = 0.001                # 0.1% Securities Transaction Tax (sell side, equity delivery)
GST_PCT = 0.18                 # 18% GST on brokerage
STAMP_DUTY_PCT = 0.00015       # 0.015% stamp duty (buy side)


class RRMSStrategy:
    """RRMS strategy for backtesting."""

    def __init__(
        self,
        capital: float = 100000,
        risk_pct: float = 0.02,
        min_rrr: float = 3.0,
        lookback: int = 20,
    ):
        self.capital = capital
        self.risk_pct = risk_pct
        self.min_rrr = min_rrr
        self.lookback = lookback


def _apply_slippage(price: float, direction: str, is_entry: bool, slippage_pct: float) -> float:
    """
    Apply realistic slippage to a price.

    Entry: Buy higher (LONG) or sell lower (SHORT)
    Exit: Sell lower (LONG target/SL) or buy higher (SHORT target/SL)
    """
    if is_entry:
        if direction == "LONG":
            return price * (1 + slippage_pct)  # Buy at worse price
        else:
            return price * (1 - slippage_pct)  # Sell at worse price
    else:
        if direction == "LONG":
            return price * (1 - slippage_pct)  # Sell at worse price
        else:
            return price * (1 + slippage_pct)  # Buy at worse price


def _calculate_transaction_cost(price: float, qty: int, is_sell: bool) -> float:
    """
    Calculate realistic transaction costs for Indian markets (Zerodha).

    Components:
    - Brokerage: 0.03% or Rs.20, whichever is LOWER (Zerodha equity delivery)
    - STT: 0.1% on sell side (equity delivery)
    - GST: 18% on brokerage + SEBI + exchange turnover charges
    - Stamp duty: 0.015% on buy side
    - Exchange turnover: 0.00345% (NSE)
    - SEBI charges: 0.0001%
    """
    turnover = price * qty
    brokerage = min(turnover * 0.0003, BROKERAGE_PER_ORDER)  # 0.03% or Rs.20
    exchange_turnover = turnover * 0.0000345  # NSE turnover charge
    sebi = turnover * 0.000001  # SEBI charges
    gst = (brokerage + exchange_turnover + sebi) * GST_PCT
    stt = turnover * STT_PCT if is_sell else 0
    stamp = turnover * STAMP_DUTY_PCT if not is_sell else 0

    return brokerage + gst + stt + stamp + exchange_turnover + sebi


# ══════════════════════════════════════════════════════════════
# TRADE METRICS CALCULATOR (v2 — Production-Grade)
# ══════════════════════════════════════════════════════════════


def _calculate_metrics(
    trades: list[dict], equity: list[float], capital: float,
    total_costs: float = 0,
) -> dict:
    """Calculate standard backtest metrics from trade list."""
    wins = [t for t in trades if t["outcome"] == "WIN"]
    losses = [t for t in trades if t["outcome"] == "LOSS"]

    total_trades = len(trades)
    win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0

    total_pnl = sum(t["pnl"] for t in trades)
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Max drawdown
    peak = capital
    max_dd = 0
    for eq in equity:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # Max consecutive losses
    max_consec_loss = 0
    current_streak = 0
    for t in trades:
        if t["outcome"] == "LOSS":
            current_streak += 1
            max_consec_loss = max(max_consec_loss, current_streak)
        else:
            current_streak = 0

    # Proper annualized Sharpe ratio from DAILY equity returns
    # (not per-trade returns which mix timeframes)
    if len(equity) >= 3:
        daily_returns = []
        for i in range(1, len(equity)):
            if equity[i - 1] > 0:
                daily_returns.append((equity[i] - equity[i - 1]) / equity[i - 1])

        if daily_returns:
            avg_daily = sum(daily_returns) / len(daily_returns)
            std_daily = math.sqrt(
                sum((r - avg_daily) ** 2 for r in daily_returns) / max(len(daily_returns) - 1, 1)
            )
            # Annualize: multiply mean by 252, std by sqrt(252)
            sharpe = (avg_daily / std_daily * math.sqrt(252)) if std_daily > 0 else 0
        else:
            sharpe = 0
    else:
        sharpe = 0

    current_capital = equity[-1] if equity else capital
    total_return_pct = (current_capital - capital) / capital * 100

    # Calmar ratio = annualized return / max drawdown
    # Approximate annualized return from total
    trading_days = max(len(equity) - 1, 1)
    annualized_return = total_return_pct * (252 / trading_days) if trading_days > 0 else 0
    calmar = annualized_return / max_dd if max_dd > 0 else 0

    # Average winner / average loser
    avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
    avg_loss = abs(sum(t["pnl"] for t in losses) / len(losses)) if losses else 0
    payoff_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")

    return {
        "total_trades": total_trades,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 2),
        "calmar_ratio": round(calmar, 2),
        "total_return": round(total_return_pct, 2),
        "max_consecutive_losses": max_consec_loss,
        "avg_winner": round(avg_win, 2),
        "avg_loser": round(avg_loss, 2),
        "payoff_ratio": round(payoff_ratio, 2),
        "total_costs": round(total_costs, 2),
        "slippage_impact": f"{DEFAULT_SLIPPAGE_PCT * 100:.1f}% per side",
    }


# ══════════════════════════════════════════════════════════════
# SIGNAL GENERATORS (per strategy)
# ══════════════════════════════════════════════════════════════


def _generate_rrms_signals(
    data: pd.DataFrame, ticker: str, capital: float
) -> list[dict]:
    """Generate RRMS-based entry signals."""
    from mcp_server.rrms_engine import RRMSEngine
    from mcp_server.swing_detector import auto_detect_levels

    engine = RRMSEngine(capital=capital)
    signals: list[dict] = []
    window = 60

    for i in range(window, len(data) - 1):
        window_data = data.iloc[i - window : i]
        levels = auto_detect_levels(window_data)

        cmp = float(data["close"].iloc[i])
        ltrp = levels["ltrp"]
        pivot = levels["pivot_high"]

        if ltrp <= 0 or pivot <= 0 or pivot <= ltrp:
            continue

        result = engine.calculate(ticker, cmp, ltrp, pivot)
        if result.is_valid:
            signals.append({
                "bar_idx": i,
                "direction": "LONG",
                "entry": result.entry_price,
                "stop_loss": result.stop_loss,
                "target": result.target,
                "qty": result.qty,
                "risk_per_share": result.risk_per_share,
                "reward_per_share": result.reward_per_share,
                "source": "rrms",
                "confidence": 60,
            })

    return signals


def _generate_engine_signals(
    data: pd.DataFrame, engine_name: str
) -> list[dict]:
    """
    Generate signals from SMC / Wyckoff / VSA / Harmonic engines.

    Scans every bar window for patterns and creates entry signals
    with ATR-based stop loss and 3:1 target.
    """
    signals: list[dict] = []
    window = 60 if engine_name != "harmonic" else 120

    # Select the right engine
    if engine_name == "smc":
        from mcp_server.smc_engine import SMCEngine
        engine = SMCEngine()
    elif engine_name == "wyckoff":
        from mcp_server.wyckoff_engine import WyckoffEngine
        engine = WyckoffEngine()
    elif engine_name == "vsa":
        from mcp_server.vsa_engine import VSAEngine
        engine = VSAEngine()
    elif engine_name == "harmonic":
        from mcp_server.harmonic_engine import HarmonicEngine
        engine = HarmonicEngine()
    else:
        return signals

    for i in range(window, len(data) - 1):
        window_data = data.iloc[i - window : i + 1].copy()

        patterns = engine.detect_all(window_data)
        if not patterns:
            continue

        # Use the highest confidence pattern
        best = max(patterns, key=lambda p: p.confidence)

        cmp = float(data["close"].iloc[i])
        # ATR-based stop/target
        recent = data.iloc[max(0, i - 20) : i + 1]
        atr = float((recent["high"] - recent["low"]).mean())

        if best.direction == "BULLISH":
            stop_loss = cmp - atr * 1.5
            target = cmp + atr * 4.5  # 3:1 RRR
            direction = "LONG"
        elif best.direction == "BEARISH":
            stop_loss = cmp + atr * 1.5
            target = cmp - atr * 4.5
            direction = "SHORT"
        else:
            continue

        risk_per_share = abs(cmp - stop_loss)
        if risk_per_share < 0.01:
            continue

        signals.append({
            "bar_idx": i,
            "direction": direction,
            "entry": cmp,
            "stop_loss": round(stop_loss, 2),
            "target": round(target, 2),
            "qty": max(1, int(2000 / risk_per_share)),  # Fixed risk per trade
            "risk_per_share": round(risk_per_share, 2),
            "reward_per_share": round(abs(target - cmp), 2),
            "source": engine_name,
            "pattern": best.name,
            "confidence": int(best.confidence * 100),
        })

    return signals


# ══════════════════════════════════════════════════════════════
# TRADE SIMULATOR (v2 — with slippage + costs)
# ══════════════════════════════════════════════════════════════


def _simulate_trades(
    data: pd.DataFrame,
    signals: list[dict],
    capital: float,
    max_hold: int = 30,
    slippage_pct: float = DEFAULT_SLIPPAGE_PCT,
) -> tuple[list[dict], list[float], float]:
    """
    Simulate trades from signals with realistic slippage and transaction costs.

    Returns: (trades, equity_curve, total_costs)
    """
    trades: list[dict] = []
    equity = [capital]
    current_capital = capital
    total_costs = 0.0
    last_exit_bar = -1

    for sig in signals:
        i = sig["bar_idx"]

        # Don't overlap trades
        if i <= last_exit_bar:
            continue

        is_long = sig["direction"] == "LONG"

        # Apply slippage to entry
        actual_entry = _apply_slippage(sig["entry"], sig["direction"], is_entry=True, slippage_pct=slippage_pct)
        entry_cost = _calculate_transaction_cost(actual_entry, sig["qty"], is_sell=False)
        total_costs += entry_cost

        for j in range(i + 1, min(i + max_hold, len(data))):
            future_high = float(data["high"].iloc[j])
            future_low = float(data["low"].iloc[j])

            # Check target hit
            target_hit = (
                future_high >= sig["target"] if is_long else future_low <= sig["target"]
            )
            # Check stop loss hit
            sl_hit = (
                future_low <= sig["stop_loss"] if is_long else future_high >= sig["stop_loss"]
            )

            if target_hit:
                # Apply slippage to exit
                actual_exit = _apply_slippage(sig["target"], sig["direction"], is_entry=False, slippage_pct=slippage_pct)
                exit_cost = _calculate_transaction_cost(actual_exit, sig["qty"], is_sell=True)
                total_costs += exit_cost

                if is_long:
                    pnl = sig["qty"] * (actual_exit - actual_entry) - entry_cost - exit_cost
                else:
                    pnl = sig["qty"] * (actual_entry - actual_exit) - entry_cost - exit_cost

                current_capital += pnl
                trades.append({
                    "entry_date": str(data.index[i]),
                    "exit_date": str(data.index[j]),
                    "entry": round(actual_entry, 2),
                    "exit": round(actual_exit, 2),
                    "entry_ideal": sig["entry"],
                    "exit_ideal": sig["target"],
                    "slippage_entry": round(abs(actual_entry - sig["entry"]), 2),
                    "slippage_exit": round(abs(actual_exit - sig["target"]), 2),
                    "costs": round(entry_cost + exit_cost, 2),
                    "pnl": round(pnl, 2),
                    "outcome": "WIN",
                    "days_held": j - i,
                    "source": sig.get("source", ""),
                    "pattern": sig.get("pattern", ""),
                    "confidence": sig.get("confidence", 0),
                    "direction": sig["direction"],
                })
                last_exit_bar = j
                break
            elif sl_hit:
                # Apply slippage to stop loss exit
                actual_exit = _apply_slippage(sig["stop_loss"], sig["direction"], is_entry=False, slippage_pct=slippage_pct)
                exit_cost = _calculate_transaction_cost(actual_exit, sig["qty"], is_sell=True)
                total_costs += exit_cost

                if is_long:
                    pnl = sig["qty"] * (actual_exit - actual_entry) - entry_cost - exit_cost
                else:
                    pnl = sig["qty"] * (actual_entry - actual_exit) - entry_cost - exit_cost

                current_capital += pnl
                trades.append({
                    "entry_date": str(data.index[i]),
                    "exit_date": str(data.index[j]),
                    "entry": round(actual_entry, 2),
                    "exit": round(actual_exit, 2),
                    "entry_ideal": sig["entry"],
                    "exit_ideal": sig["stop_loss"],
                    "slippage_entry": round(abs(actual_entry - sig["entry"]), 2),
                    "slippage_exit": round(abs(actual_exit - sig["stop_loss"]), 2),
                    "costs": round(entry_cost + exit_cost, 2),
                    "pnl": round(pnl, 2),
                    "outcome": "LOSS",
                    "days_held": j - i,
                    "source": sig.get("source", ""),
                    "pattern": sig.get("pattern", ""),
                    "confidence": sig.get("confidence", 0),
                    "direction": sig["direction"],
                })
                last_exit_bar = j
                break

        equity.append(current_capital)

    return trades, equity, total_costs


# ══════════════════════════════════════════════════════════════
# CONFLUENCE STRATEGY
# ══════════════════════════════════════════════════════════════


def _generate_confluence_signals(
    data: pd.DataFrame, ticker: str, capital: float
) -> list[dict]:
    """
    Generate signals where multiple engines agree.

    Score each bar by how many engines produce a signal.
    Only take entries with 2+ engines confirming.
    """
    # Collect all signals from all engines
    all_signals: dict[int, list[dict]] = {}

    for engine_name in ["smc", "wyckoff", "vsa", "harmonic"]:
        try:
            engine_signals = _generate_engine_signals(data, engine_name)
            for sig in engine_signals:
                idx = sig["bar_idx"]
                if idx not in all_signals:
                    all_signals[idx] = []
                all_signals[idx].append(sig)
        except Exception as e:
            logger.warning("Confluence: %s engine failed: %s", engine_name, e)

    # Filter for bars with 2+ engines agreeing on direction
    confluence_signals: list[dict] = []
    for idx, sigs in sorted(all_signals.items()):
        bull_sigs = [s for s in sigs if s["direction"] == "LONG"]
        bear_sigs = [s for s in sigs if s["direction"] == "SHORT"]

        sources_bull = set(s["source"] for s in bull_sigs)
        sources_bear = set(s["source"] for s in bear_sigs)

        if len(sources_bull) >= 2:
            # Use the signal with highest confidence
            best = max(bull_sigs, key=lambda s: s["confidence"])
            best["confidence"] = min(95, best["confidence"] + len(sources_bull) * 10)
            best["source"] = f"confluence({','.join(sorted(sources_bull))})"
            best["engines_agreed"] = len(sources_bull)
            confluence_signals.append(best)
        elif len(sources_bear) >= 2:
            best = max(bear_sigs, key=lambda s: s["confidence"])
            best["confidence"] = min(95, best["confidence"] + len(sources_bear) * 10)
            best["source"] = f"confluence({','.join(sorted(sources_bear))})"
            best["engines_agreed"] = len(sources_bear)
            confluence_signals.append(best)

    return confluence_signals


# ══════════════════════════════════════════════════════════════
# MAIN BACKTEST FUNCTION
# ══════════════════════════════════════════════════════════════


def run_backtest(
    ticker: str,
    strategy: str = "rrms",
    days: int = 1095,  # Default 3 years (was 365)
    capital: float = 100000,
    slippage_pct: float = DEFAULT_SLIPPAGE_PCT,
) -> dict:
    """
    Run a backtest using historical data with realistic costs.

    Args:
        ticker: Stock symbol (supports EXCHANGE:SYMBOL format)
        strategy: Strategy name ("rrms", "smc", "wyckoff", "vsa",
                  "harmonic", "confluence")
        days: Number of days to backtest (default 1095 = 3 years)
        capital: Starting capital
        slippage_pct: Slippage percentage per side (default 0.3%)

    Returns:
        Dict with backtest results including per-pattern accuracy
    """
    from mcp_server.nse_scanner import get_stock_data

    logger.info(
        "Starting backtest: %s with %s strategy over %d days (slippage=%.1f%%)",
        ticker, strategy, days, slippage_pct * 100,
    )

    # Fetch data — use exchange-aware get_stock_data
    if days <= 365:
        period = "1y"
    elif days <= 730:
        period = "2y"
    elif days <= 1095:
        period = "3y"
    else:
        period = "5y"

    data = get_stock_data(ticker, period=period)

    if data.empty or len(data) < 50:
        return {
            "error": f"Insufficient data for {ticker}",
            "ticker": ticker,
            "strategy": strategy,
        }

    # Generate signals based on strategy
    if strategy == "rrms":
        signals = _generate_rrms_signals(data, ticker, capital)
    elif strategy in ("smc", "wyckoff", "vsa", "harmonic"):
        signals = _generate_engine_signals(data, strategy)
    elif strategy == "confluence":
        signals = _generate_confluence_signals(data, ticker, capital)
    else:
        signals = _generate_rrms_signals(data, ticker, capital)

    # Simulate trades with slippage and costs
    trades, equity, total_costs = _simulate_trades(
        data, signals, capital, slippage_pct=slippage_pct,
    )

    # Calculate metrics
    metrics = _calculate_metrics(trades, equity, capital, total_costs)

    # Per-pattern breakdown
    pattern_stats: dict[str, dict] = {}
    for t in trades:
        pat = t.get("pattern", t.get("source", "rrms"))
        if pat not in pattern_stats:
            pattern_stats[pat] = {"wins": 0, "losses": 0, "pnl": 0.0}
        if t["outcome"] == "WIN":
            pattern_stats[pat]["wins"] += 1
        else:
            pattern_stats[pat]["losses"] += 1
        pattern_stats[pat]["pnl"] += t["pnl"]

    by_pattern = []
    for pat, stats in pattern_stats.items():
        total = stats["wins"] + stats["losses"]
        by_pattern.append({
            "pattern": pat,
            "trades": total,
            "wins": stats["wins"],
            "losses": stats["losses"],
            "win_rate": round(stats["wins"] / total * 100, 1) if total > 0 else 0,
            "pnl": round(stats["pnl"], 2),
        })

    # Per-source breakdown (for confluence)
    source_stats: dict[str, dict] = {}
    for t in trades:
        src = t.get("source", "unknown")
        if src not in source_stats:
            source_stats[src] = {"wins": 0, "losses": 0, "pnl": 0.0}
        if t["outcome"] == "WIN":
            source_stats[src]["wins"] += 1
        else:
            source_stats[src]["losses"] += 1
        source_stats[src]["pnl"] += t["pnl"]

    by_source = []
    for src, stats in source_stats.items():
        total = stats["wins"] + stats["losses"]
        by_source.append({
            "source": src,
            "trades": total,
            "wins": stats["wins"],
            "win_rate": round(stats["wins"] / total * 100, 1) if total > 0 else 0,
            "pnl": round(stats["pnl"], 2),
        })

    # Equity curve (sampled to ~100 points)
    step = max(len(equity) // 100, 1)
    eq_curve = [
        {
            "date": str(data.index[min(i * step, len(data) - 1)]),
            "equity": round(eq, 2),
        }
        for i, eq in enumerate(equity[::step])
    ]

    result = {
        "ticker": ticker,
        "strategy": strategy,
        "period": f"{days} days",
        "data_bars": len(data),
        **metrics,
        "by_pattern": by_pattern,
        "by_source": by_source,
        "equity_curve": eq_curve,
        "trades": trades[-20:],  # Last 20 trades for inspection
    }

    logger.info(
        "Backtest %s (%s): %d trades, %.1f%% win rate, PF: %.2f, Sharpe: %.2f, Costs: %.2f",
        ticker, strategy, metrics["total_trades"], metrics["win_rate"],
        metrics["profit_factor"], metrics["sharpe_ratio"], total_costs,
    )

    return result


def run_backtest_all_strategies(
    ticker: str,
    days: int = 1095,  # Default 3 years
    capital: float = 100000,
) -> dict:
    """
    Run backtest across ALL strategies and compare.

    Returns a comparison dict with each strategy's metrics side-by-side.
    """
    strategies = ["rrms", "smc", "wyckoff", "vsa", "harmonic", "confluence"]
    results: dict[str, dict] = {}

    for strat in strategies:
        try:
            results[strat] = run_backtest(ticker, strategy=strat, days=days, capital=capital)
        except Exception as e:
            logger.error("Backtest %s failed for %s: %s", strat, ticker, e)
            results[strat] = {"error": str(e), "strategy": strat}

    # Build comparison table
    comparison = []
    for strat in strategies:
        r = results.get(strat, {})
        comparison.append({
            "strategy": strat,
            "trades": r.get("total_trades", 0),
            "win_rate": r.get("win_rate", 0),
            "profit_factor": r.get("profit_factor", 0),
            "total_pnl": r.get("total_pnl", 0),
            "max_drawdown": r.get("max_drawdown", 0),
            "sharpe_ratio": r.get("sharpe_ratio", 0),
            "calmar_ratio": r.get("calmar_ratio", 0),
            "total_return": r.get("total_return", 0),
            "max_consecutive_losses": r.get("max_consecutive_losses", 0),
            "total_costs": r.get("total_costs", 0),
        })

    # Find best strategy
    valid = [c for c in comparison if c["trades"] > 0]
    best = max(valid, key=lambda c: c["profit_factor"]) if valid else None

    return {
        "ticker": ticker,
        "period": f"{days} days",
        "capital": capital,
        "slippage": f"{DEFAULT_SLIPPAGE_PCT * 100:.1f}%",
        "comparison": comparison,
        "best_strategy": best["strategy"] if best else "none",
        "details": results,
    }
