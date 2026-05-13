"""
BB Breakout — Options Market Simulation

Same daily 4-condition signal (SuperTrend + RSI>70 + R1 pivot + Upper BB)
but instead of buying the stock, buys an ATM Call option.

Pricing: Black-Scholes with IV=25% (typical NSE equity option IV),
         21-day (monthly) expiry, risk-free rate 6.5%.

Position: ₹1L in option premium per trade (same capital as equity baseline).
Exit: same triggers as equity (ST flip / -5% underlying drop / 20-day time / EOD).

Compares: Equity baseline vs Options strategy for identical signals.

Usage:
    python scripts/validate_bb_options.py
    python scripts/validate_bb_options.py --from 2021-01-01 --iv 0.25
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bb_options")

# ── Constants ─────────────────────────────────────────────────────────────────
ST_PERIOD    = 7
ST_MULT      = 3.0
RSI_PERIOD   = 14
BB_PERIOD    = 20
BB_STD       = 2.0
HARD_STOP    = 0.05
MAX_HOLD     = 20         # trading days
MAX_CONC     = 5
POSITION_INR = 100_000.0  # ₹1L in option premium per trade
MIN_DAYS     = 252
RISK_FREE    = 0.065      # 6.5% RBI repo rate
OPTION_DAYS  = 21         # monthly expiry ~ 21 trading days
DEFAULT_IV   = 0.25       # 25% annualized IV for NSE equity options

# Equity costs (baseline comparison)
EQ_COSTS = {"brokerage": 20.0, "stt_sell": 0.001, "exchange": 0.0000345,
             "gst": 0.18, "stamp": 0.00015, "slippage": 0.0005}

# Options costs
OPT_COSTS = {"brokerage": 20.0, "stt_sell": 0.0005, "exchange": 0.0005,
              "gst": 0.18, "stamp": 0.00003, "slippage": 0.005}


# ── Black-Scholes ─────────────────────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """European call price. Returns intrinsic value if T≤0."""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def _bs_delta(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Call delta."""
    if T <= 0 or sigma <= 0:
        return 1.0 if S >= K else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return _norm_cdf(d1)


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_symbols() -> list[str]:
    p = Path("data/nifty500.json")
    if not p.exists():
        p = Path(__file__).parent.parent / "data" / "nifty500.json"
    with open(p) as f:
        syms = json.load(f)["symbols"]
    return [s for s in syms if "DUMMY" not in s.upper()]


def _load_prices(symbols: list[str], start_str: str, end_str: str) -> dict[str, dict]:
    import yfinance as yf
    import pandas as pd

    try:
        from sqlalchemy import text
        from mcp_server.db import engine
        prices: dict[str, dict] = {}
        with engine.connect() as conn:
            for sym in symbols:
                rows = conn.execute(
                    text("SELECT bar_date, open, high, low, close FROM ohlcv_cache "
                         "WHERE ticker=:s AND interval='1d' "
                         "AND bar_date BETWEEN :s0 AND :e "
                         "AND close IS NOT NULL AND close > 0 ORDER BY bar_date"),
                    {"s": sym, "s0": start_str, "e": end_str},
                ).fetchall()
                if len(rows) >= MIN_DAYS:
                    prices[sym] = {
                        (r.bar_date.date() if hasattr(r.bar_date, "date") else r.bar_date): {
                            "o": float(r.open or r.close), "h": float(r.high or r.close),
                            "l": float(r.low or r.close), "c": float(r.close),
                        }
                        for r in rows
                    }
        missing = [s for s in symbols if s not in prices]
    except Exception:
        prices = {}
        missing = symbols

    logger.info("DB: %d | yfinance: %d", len(prices), len(missing))
    if missing:
        for i in range(0, len(missing), 50):
            chunk = missing[i: i + 50]
            try:
                raw = yf.download([s + ".NS" for s in chunk], start=start_str, end=end_str,
                                  auto_adjust=True, progress=False, threads=True)
                if raw is None or raw.empty:
                    continue
                for sym in chunk:
                    try:
                        yf_sym = sym + ".NS"
                        if isinstance(raw.columns, pd.MultiIndex):
                            c  = raw["Close"][yf_sym].dropna()
                            h  = raw["High"][yf_sym].reindex(c.index).fillna(c)
                            lo = raw["Low"][yf_sym].reindex(c.index).fillna(c)
                        else:
                            c  = raw["Close"].dropna()
                            h  = raw["High"].reindex(c.index).fillna(c)
                            lo = raw["Low"].reindex(c.index).fillna(c)
                        if len(c) < MIN_DAYS:
                            continue
                        prices[sym] = {
                            d.date(): {"o": float(c[d]), "h": float(h.get(d, c[d])),
                                       "l": float(lo.get(d, c[d])), "c": float(c[d])}
                            for d in c.index
                        }
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("yfinance batch %d: %s", i, e)
    logger.info("Eligible: %d stocks", len(prices))
    return prices


# ── Indicators ────────────────────────────────────────────────────────────────

def _compute_indicators(ohlcv: list[dict]) -> list[dict]:
    n = len(ohlcv)
    closes = [b["c"] for b in ohlcv]
    highs  = [b["h"] for b in ohlcv]
    lows   = [b["l"] for b in ohlcv]

    rsi = [50.0] * n
    if n > RSI_PERIOD:
        gains  = [max(closes[i] - closes[i-1], 0) for i in range(1, n)]
        losses = [max(closes[i-1] - closes[i], 0) for i in range(1, n)]
        alpha  = 1.0 / RSI_PERIOD
        ag     = sum(gains[:RSI_PERIOD]) / RSI_PERIOD
        al     = sum(losses[:RSI_PERIOD]) / RSI_PERIOD
        rsi[RSI_PERIOD] = 100 - 100 / (1 + ag / al) if al > 0 else 100.0
        for i in range(RSI_PERIOD, len(gains)):
            ag = (1 - alpha) * ag + alpha * gains[i]
            al = (1 - alpha) * al + alpha * losses[i]
            rsi[i + 1] = 100 - 100 / (1 + ag / al) if al > 0 else 100.0

    upper_bb = [float("nan")] * n
    for i in range(BB_PERIOD - 1, n):
        w    = closes[i - BB_PERIOD + 1 : i + 1]
        mean = sum(w) / BB_PERIOD
        std  = math.sqrt(sum((x - mean) ** 2 for x in w) / BB_PERIOD)
        upper_bb[i] = mean + BB_STD * std

    st_dir  = [0] * n
    st_line = [0.0] * n
    for i in range(1, n):
        if i < ST_PERIOD:
            continue
        atr = sum(
            max(highs[j] - lows[j],
                abs(highs[j] - closes[j-1]),
                abs(lows[j]  - closes[j-1]))
            for j in range(i - ST_PERIOD + 1, i + 1)
        ) / ST_PERIOD
        hl2   = (highs[i] + lows[i]) / 2
        upper = hl2 + ST_MULT * atr
        lower = hl2 - ST_MULT * atr
        prev  = st_line[i-1] if st_line[i-1] else upper
        if closes[i] > prev:
            st_line[i] = max(lower, st_line[i-1]) if st_dir[i-1] == 1 else lower
            st_dir[i]  = 1
        else:
            st_line[i] = min(upper, st_line[i-1]) if st_dir[i-1] == -1 else upper
            st_dir[i]  = -1

    r1_vals = [float("nan")] * n
    for i in range(1, n):
        ph, pl, pc = highs[i-1], lows[i-1], closes[i-1]
        pivot   = (ph + pl + pc) / 3
        r1_vals[i] = 2 * pivot - pl

    result = [dict(b) for b in ohlcv]
    for i, bar in enumerate(result):
        bar["rsi"]      = rsi[i]
        bar["upper_bb"] = upper_bb[i]
        bar["st_dir"]   = st_dir[i]
        bar["r1"]       = r1_vals[i]
    return result


# ── Cost models ───────────────────────────────────────────────────────────────

def _eq_cost(pos: float) -> float:
    c = EQ_COSTS
    buy  = pos * (1 + c["slippage"])
    sell = pos * (1 - c["slippage"])
    cost = c["brokerage"] * 2 + sell * c["stt_sell"]
    cost += (buy + sell) * c["exchange"]
    cost += (c["brokerage"] * 2 + (buy + sell) * c["exchange"]) * c["gst"]
    cost += buy * c["stamp"]
    return cost


def _opt_cost(premium: float) -> float:
    """Round-trip cost on option premium spent."""
    c    = OPT_COSTS
    cost = c["brokerage"] * 2
    cost += premium * (c["stt_sell"] + c["exchange"] * 2)
    cost += (c["brokerage"] * 2 + premium * c["exchange"] * 2) * c["gst"]
    cost += premium * c["stamp"]
    return cost


# ── Backtest ──────────────────────────────────────────────────────────────────

def _run_equity(prices: dict[str, dict], indicators: dict[str, list[dict]],
                date_to_idx: dict[str, dict], all_dates: list[date],
                start: date) -> list[dict]:
    open_pos: list[dict] = []
    closed: list[dict] = []

    for today in all_dates:
        if today < start:
            continue
        still_open: list[dict] = []
        for pos in open_pos:
            sym = pos["sym"]
            idx = date_to_idx.get(sym, {}).get(today)
            if idx is None:
                pos["days_held"] += 1
                still_open.append(pos)
                continue
            bar  = indicators[sym][idx]
            held = pos["days_held"] + 1
            stop = pos["entry_px"] * (1 - HARD_STOP)
            ex   = None
            px   = bar["c"]
            if bar["c"] <= stop:
                ex, px = "hard_stop", stop
            elif bar["st_dir"] == -1:
                ex = "st_flip"
            elif held >= MAX_HOLD:
                ex = "time"
            if ex:
                pnl = (px - pos["entry_px"]) / pos["entry_px"] * POSITION_INR - _eq_cost(POSITION_INR)
                closed.append({"sym": sym, "entry_date": pos["entry_day"],
                               "exit_date": today, "ret_pct": round(pnl / POSITION_INR * 100, 2),
                               "net_pnl": round(pnl, 2), "exit_reason": ex,
                               "entry_rsi": pos["entry_rsi"]})
            else:
                pos["days_held"] = held
                still_open.append(pos)
        open_pos = still_open

        slots  = MAX_CONC - len(open_pos)
        if slots <= 0:
            continue
        already = {p["sym"] for p in open_pos}
        for sym, ind in indicators.items():
            if sym in already:
                continue
            idx = date_to_idx.get(sym, {}).get(today)
            if idx is None or idx < BB_PERIOD + ST_PERIOD:
                continue
            bar = ind[idx]
            r1  = bar.get("r1", float("nan"))
            ub  = bar.get("upper_bb", float("nan"))
            if (bar["st_dir"] == 1 and bar["rsi"] > 70
                    and not math.isnan(r1) and bar["c"] > r1
                    and not math.isnan(ub) and bar["c"] > ub):
                open_pos.append({"sym": sym, "entry_day": today,
                                 "entry_px": bar["c"], "entry_rsi": bar["rsi"], "days_held": 0})
                if len(open_pos) >= MAX_CONC:
                    break
    return closed


def _run_options(prices: dict[str, dict], indicators: dict[str, list[dict]],
                 date_to_idx: dict[str, dict], all_dates: list[date],
                 start: date, iv: float) -> list[dict]:
    """Same signals as equity but trade ATM call options."""
    open_pos: list[dict] = []
    closed: list[dict] = []

    for today in all_dates:
        if today < start:
            continue
        still_open: list[dict] = []
        for pos in open_pos:
            sym       = pos["sym"]
            idx       = date_to_idx.get(sym, {}).get(today)
            if idx is None:
                pos["days_held"] += 1
                still_open.append(pos)
                continue
            bar       = indicators[sym][idx]
            S         = bar["c"]
            K         = pos["strike"]
            days_held = pos["days_held"] + 1
            days_left = max(0, OPTION_DAYS - days_held)
            T_left    = days_left / 252.0

            # Check underlying exit conditions
            stop = pos["entry_stock_px"] * (1 - HARD_STOP)
            ex   = None
            if S <= stop:
                ex = "hard_stop"
            elif bar["st_dir"] == -1:
                ex = "st_flip"
            elif days_held >= MAX_HOLD:
                ex = "time"
            elif days_left == 0:
                ex = "expiry"

            if ex:
                exit_premium = _bs_call(S, K, T_left, RISK_FREE, iv)
                # P&L per share * shares_bought
                pnl_per_share = exit_premium - pos["entry_premium"]
                total_pnl     = pnl_per_share * pos["shares"] - _opt_cost(pos["premium_paid"])
                ret_pct       = total_pnl / POSITION_INR * 100
                closed.append({"sym": sym, "entry_date": pos["entry_day"],
                               "exit_date": today, "ret_pct": round(ret_pct, 2),
                               "net_pnl": round(total_pnl, 2), "exit_reason": ex,
                               "entry_rsi": pos["entry_rsi"],
                               "delta_at_entry": round(pos["entry_delta"], 2),
                               "entry_premium": round(pos["entry_premium"], 2)})
            else:
                pos["days_held"] = days_held
                still_open.append(pos)
        open_pos = still_open

        slots  = MAX_CONC - len(open_pos)
        if slots <= 0:
            continue
        already = {p["sym"] for p in open_pos}
        for sym, ind in indicators.items():
            if sym in already:
                continue
            idx = date_to_idx.get(sym, {}).get(today)
            if idx is None or idx < BB_PERIOD + ST_PERIOD:
                continue
            bar = ind[idx]
            r1  = bar.get("r1", float("nan"))
            ub  = bar.get("upper_bb", float("nan"))
            if not (bar["st_dir"] == 1 and bar["rsi"] > 70
                    and not math.isnan(r1) and bar["c"] > r1
                    and not math.isnan(ub) and bar["c"] > ub):
                continue
            S = bar["c"]
            K = S                         # ATM: strike = current stock price
            T = OPTION_DAYS / 252.0
            premium = _bs_call(S, K, T, RISK_FREE, iv)
            if premium <= 0:
                continue
            shares = POSITION_INR / premium   # shares exposure for ₹1L premium
            delta  = _bs_delta(S, K, T, RISK_FREE, iv)
            open_pos.append({
                "sym": sym, "entry_day": today,
                "entry_stock_px": S, "strike": K,
                "entry_premium": premium, "shares": shares,
                "premium_paid": POSITION_INR,
                "entry_delta": delta,
                "entry_rsi": bar["rsi"], "days_held": 0,
            })
            if len(open_pos) >= MAX_CONC:
                break
    return closed


# ── Metrics ───────────────────────────────────────────────────────────────────

def _metrics(trades: list[dict], years: float) -> dict:
    if not trades:
        return {}
    returns  = [t["ret_pct"] / 100 for t in trades]
    n        = len(trades)
    wins     = sum(1 for r in returns if r > 0)
    total    = sum(returns)
    cagr     = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else -1.0
    mean_r   = total / n
    std_r    = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1))
    avg_hold = sum(t.get("days_held", 0) if "days_held" in t else 0 for t in trades) / n
    sharpe   = (mean_r / std_r) * math.sqrt(252 / max(avg_hold, 1)) if std_r > 0 else 0.0
    ref      = float(MAX_CONC * POSITION_INR)
    cum = peak = max_dd = 0.0
    for t in sorted(trades, key=lambda x: x["exit_date"]):
        cum  += t["net_pnl"]
        peak  = max(peak, cum)
        max_dd = max(max_dd, (peak - cum) / ref)
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
    return {"n_trades": n, "win_rate": wins / n, "cagr": cagr, "sharpe": sharpe,
            "max_dd": max_dd, "total_pnl": sum(t["net_pnl"] for t in trades),
            "avg_ret_pct": mean_r * 100, "exit_reasons": reasons}


def _verdict(m: dict) -> str:
    if not m:
        return "OVERRIDE"
    TIER1 = {"trades": 30, "cagr": 0.20, "sharpe": 0.8, "maxdd": 0.30, "winrate": 0.50}
    TIER2 = {"trades": 15, "cagr": 0.10, "sharpe": 0.5, "maxdd": 0.40, "winrate": 0.40}
    if all([m["n_trades"] >= TIER1["trades"], m["cagr"] >= TIER1["cagr"],
            m["sharpe"] >= TIER1["sharpe"], m["max_dd"] <= TIER1["maxdd"],
            m["win_rate"] >= TIER1["winrate"]]):
        return "TIER_1"
    if all([m["n_trades"] >= TIER2["trades"], m["cagr"] >= TIER2["cagr"],
            m["sharpe"] >= TIER2["sharpe"], m["max_dd"] <= TIER2["maxdd"],
            m["win_rate"] >= TIER2["winrate"]]):
        return "TIER_2"
    return "OVERRIDE"


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from",  dest="start", default="2021-01-01")
    parser.add_argument("--to",    dest="end",   default=str(date.today()))
    parser.add_argument("--iv",    type=float,   default=DEFAULT_IV,
                        help="Implied volatility for B-S pricing (default 0.25 = 25%%)")
    args = parser.parse_args()

    start      = date.fromisoformat(args.start)
    end        = date.fromisoformat(args.end)
    data_start = date(start.year - 1, start.month, 1)
    years      = (end - start).days / 365.25

    logger.info("Loading OHLCV data...")
    symbols = _load_symbols()
    prices  = _load_prices(symbols, data_start.isoformat(), end.isoformat())

    # Pre-compute indicators
    indicators:   dict[str, list[dict]] = {}
    date_to_idx:  dict[str, dict]       = {}
    for sym, pd_data in prices.items():
        sym_dates = sorted(pd_data.keys())
        bars      = [pd_data[d] for d in sym_dates]
        indicators[sym]  = _compute_indicators(bars)
        date_to_idx[sym] = {d: i for i, d in enumerate(sym_dates)}

    all_dates = sorted({d for pd_data in prices.values() for d in pd_data
                        if start <= d <= end})

    logger.info("Running equity baseline...")
    eq_trades  = _run_equity(prices, indicators, date_to_idx, all_dates, start)
    logger.info("Running options simulation (IV=%.0f%%)...", args.iv * 100)
    opt_trades = _run_options(prices, indicators, date_to_idx, all_dates, start, args.iv)

    eq_m  = _metrics(eq_trades, years)
    opt_m = _metrics(opt_trades, years)
    eq_v  = _verdict(eq_m)
    opt_v = _verdict(opt_m)

    sep = "=" * 68
    print()
    print(sep)
    print(f"BB BREAKOUT — EQUITY vs OPTIONS  |  {args.start} → {end}")
    print(f"Options: ATM Call | IV={args.iv*100:.0f}% | {OPTION_DAYS}-day expiry | ₹1L premium/trade")
    print(sep)

    def _row(label: str, m: dict, v: str) -> None:
        if not m:
            print(f"\n{label}: No trades")
            return
        print(f"\n{label}  [{v}]")
        print(f"  Trades     : {m['n_trades']}")
        print(f"  Win rate   : {m['win_rate']*100:.1f}%")
        print(f"  Avg return : {m['avg_ret_pct']:+.2f}%  per trade")
        print(f"  Total P&L  : ₹{m['total_pnl']:,.0f}")
        print(f"  CAGR       : {m['cagr']*100:+.1f}%")
        print(f"  Sharpe     : {m['sharpe']:.2f}")
        print(f"  Max DD     : {m['max_dd']*100:.1f}%")
        exits = ", ".join(f"{k}:{c}" for k, c in sorted(m["exit_reasons"].items()))
        print(f"  Exits      : {exits}")

    _row("EQUITY  (buy stock)", eq_m, eq_v)
    _row(f"OPTIONS (buy ATM call, IV {args.iv*100:.0f}%)", opt_m, opt_v)

    print()
    print(sep)
    print("SIDE-BY-SIDE COMPARISON")
    print(sep)
    print(f"{'Metric':<20} {'Equity':>12} {'Options':>12}  Winner")
    print("-" * 68)

    def cmp(label: str, eq_val, opt_val, higher_better: bool = True) -> None:
        winner = "Options ✅" if ((opt_val > eq_val) == higher_better) else "Equity ✅"
        if abs(opt_val - eq_val) < 0.001:
            winner = "Tie"
        print(f"{label:<20} {eq_val:>12.2f} {opt_val:>12.2f}  {winner}")

    if eq_m and opt_m:
        cmp("Trades",       eq_m["n_trades"],          opt_m["n_trades"],      True)
        cmp("Win rate %",   eq_m["win_rate"] * 100,    opt_m["win_rate"] * 100, True)
        cmp("Avg ret/trade",eq_m["avg_ret_pct"],       opt_m["avg_ret_pct"],   True)
        cmp("CAGR %",       eq_m["cagr"] * 100,        opt_m["cagr"] * 100,    True)
        cmp("Sharpe",       eq_m["sharpe"],             opt_m["sharpe"],        True)
        cmp("Max DD %",     eq_m["max_dd"] * 100,       opt_m["max_dd"] * 100, False)

    print(sep)
    print()
    print("KEY INSIGHT:")
    if opt_m and eq_m:
        leverage = opt_m["avg_ret_pct"] / eq_m["avg_ret_pct"] if eq_m["avg_ret_pct"] != 0 else 0
        print(f"  Options avg return is {leverage:.1f}x equity return per trade.")
        print(f"  Options position = ₹1L in PREMIUM (controls ₹{100_000/0.25/100:.0f}+ of stock)")
        print(f"  Theta decay ≈ {args.iv*100:.0f}% IV / sqrt(252) ≈ {args.iv/math.sqrt(252)*100:.2f}% per day on premium")
    print()
    print("ASSUMPTIONS:")
    print(f"  IV={args.iv*100:.0f}% fixed (real IV varies 15-40% for NSE stocks)")
    print("  ATM strike = exact entry price (no rounding to NSE strike grid)")
    print("  No liquidity premium / bid-ask spread modelled beyond slippage 0.5%")
    print("  Monthly expiry (21 trading days) — no weekly expiry modelled")
    print()

    # Save report
    out = Path("reports") / f"bb_options_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        f"# BB Breakout — Options vs Equity  ({date.today()})",
        f"IV={args.iv*100:.0f}% | ATM Call | {OPTION_DAYS}-day expiry | ₹1L premium/trade",
        "",
        "| Metric | Equity | Options |",
        "|---|---|---|",
    ]
    if eq_m and opt_m:
        for label, ev, ov in [
            ("Trades",   eq_m["n_trades"],       opt_m["n_trades"]),
            ("Win rate", f"{eq_m['win_rate']*100:.1f}%", f"{opt_m['win_rate']*100:.1f}%"),
            ("CAGR",     f"{eq_m['cagr']*100:.1f}%",     f"{opt_m['cagr']*100:.1f}%"),
            ("Sharpe",   f"{eq_m['sharpe']:.2f}",         f"{opt_m['sharpe']:.2f}"),
            ("Max DD",   f"{eq_m['max_dd']*100:.1f}%",    f"{opt_m['max_dd']*100:.1f}%"),
            ("Verdict",  eq_v,                             opt_v),
        ]:
            lines.append(f"| {label} | {ev} | {ov} |")
    out.write_text("\n".join(lines))
    logger.info("Report saved: %s", out)


if __name__ == "__main__":
    main()
