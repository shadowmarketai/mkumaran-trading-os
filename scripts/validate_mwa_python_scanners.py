"""
MWA Python Scanner Validation

Backtests 4 clean MWA indicators on the Nifty 500 universe (daily, 2021–today).

Strategies
----------
  1. Supertrend buy   — ST(10, 3) flips -1→+1;  exit on ST flip back / -7% / 20d
  2. MACD crossover   — MACD(12,26,9) line crosses above signal; exit below / -7% / 20d
  3. EMA 9/21 cross   — EMA9 crosses above EMA21; exit below / -7% / 20d
  4. 52-Week High     — close ≥ prior 252-day max close; exit < SMA50 / -10% / 40d

Position: ₹1,00,000 per trade | Max 5 concurrent
Universe: Nifty 500 (data/nifty500.json) | Daily bars

TIER_1 : trades≥30, CAGR≥20%, Sharpe≥0.8, MaxDD≤30%, WinRate≥50%
TIER_2 : trades≥15, CAGR≥10%, Sharpe≥0.5, MaxDD≤40%, WinRate≥40%
OVERRIDE: fails Tier 2 on any gate

Usage:
    python scripts/validate_mwa_python_scanners.py
    python scripts/validate_mwa_python_scanners.py --strategy supertrend
    python scripts/validate_mwa_python_scanners.py --from 2022-01-01 --max-symbols 50
"""
from __future__ import annotations

import argparse
import heapq
import json
import logging
import math
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp1252 fix
from mcp_server.technical_scanners import compute_ema, compute_macd, compute_supertrend

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("mwa_scanner_validation")

# ── Position / cost constants ─────────────────────────────────────────────────
POSITION_INR = 100_000.0
MAX_CONC     = 5

BROKERAGE = 20.0
STT_SELL  = 0.001
EXCHANGE  = 0.0000345
GST       = 0.18
STAMP     = 0.00015
SLIPPAGE  = 0.0005

# ── Tier gates ────────────────────────────────────────────────────────────────
TIER1_TRADES = 30
TIER1_CAGR   = 0.20
TIER1_SHARPE = 0.80
TIER1_MAXDD  = 0.30
TIER1_WR     = 0.50

TIER2_TRADES = 15
TIER2_CAGR   = 0.10
TIER2_SHARPE = 0.50
TIER2_MAXDD  = 0.40
TIER2_WR     = 0.40

# ── Strategy exit parameters ──────────────────────────────────────────────────
ST_HARD_STOP   = 0.07
ST_MAX_HOLD    = 20
MACD_HARD_STOP = 0.07
MACD_MAX_HOLD  = 20
EMA_HARD_STOP  = 0.07
EMA_MAX_HOLD   = 20
W52_HARD_STOP  = 0.10
W52_MAX_HOLD   = 40


def _trade_cost() -> float:
    p = POSITION_INR
    c  = BROKERAGE * 2
    c += STT_SELL * p
    c += EXCHANGE * 2 * p
    c += (BROKERAGE * 2 + EXCHANGE * 2 * p) * GST
    c += STAMP * p + SLIPPAGE * 2 * p
    return c / p


COST = _trade_cost()


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_tickers(max_symbols: int | None = None) -> list[str]:
    p = Path(__file__).parent.parent / "data" / "nifty500.json"
    with open(p) as f:
        syms = json.load(f)["symbols"]
    if max_symbols:
        syms = syms[:max_symbols]
    return [f"{s}.NS" for s in syms]


def _load_prices(tickers: list[str], start_str: str, end_str: str) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    result: dict[str, pd.DataFrame] = {}
    batch = 100
    for i in range(0, len(tickers), batch):
        chunk = tickers[i : i + batch]
        logger.info("Downloading batch %d–%d / %d …", i + 1, i + len(chunk), len(tickers))
        try:
            raw = yf.download(
                chunk, start=start_str, end=end_str,
                auto_adjust=True, progress=False, threads=True,
            )
        except Exception as e:
            logger.warning("Batch failed: %s", e)
            continue
        if raw.empty:
            continue
        for sym in chunk:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    df_s = raw.xs(sym, level=1, axis=1).copy()
                else:
                    df_s = raw.copy()
                df_s.columns = [c.lower() for c in df_s.columns]
                df_s = df_s.dropna(subset=["close"])
                if len(df_s) >= 280:
                    result[sym] = df_s
            except Exception:
                pass
    logger.info("Loaded %d symbols with ≥280 bars", len(result))
    return result


# ── Concurrency filter ────────────────────────────────────────────────────────

def _apply_concurrency(trades: list[dict], max_conc: int) -> list[dict]:
    """Keep at most max_conc simultaneously open trades (earliest entry wins)."""
    trades = sorted(trades, key=lambda t: (t["entry_date"], t["sym"]))
    heap: list = []
    kept: list[dict] = []
    for t in trades:
        while heap and heap[0] < t["entry_date"]:
            heapq.heappop(heap)
        if len(heap) < max_conc:
            heapq.heappush(heap, t["exit_date"])
            kept.append(t)
    return kept


# ── Metrics & verdict ─────────────────────────────────────────────────────────

def _metrics(trades: list[dict]) -> dict:
    if not trades:
        return {
            "n": 0, "cagr": 0.0, "sharpe": 0.0,
            "max_dd": 0.0, "win_rate": 0.0, "avg_hold": 0.0, "years": 0.0,
        }
    trades = sorted(trades, key=lambda t: t["entry_date"])
    n    = len(trades)
    rets = [t["net_ret"] for t in trades]

    win_rate = sum(1 for r in rets if r > 0) / n
    first_date = min(t["entry_date"] for t in trades)
    last_date  = max(t["exit_date"]  for t in trades)
    years = max((last_date - first_date).days / 365.25, 0.1)

    # Scale each trade return by 1/MAX_CONC: each trade occupies 1 of MAX_CONC slots.
    # Trades are concurrent so the portfolio equity must reflect the per-slot fraction,
    # not a sequential product of all raw trade returns (which would show 99% MaxDD).
    scaled = [r / MAX_CONC for r in rets]

    equity = 1.0
    for r in scaled:
        equity *= (1 + r)
    cagr = equity ** (1 / years) - 1

    avg_hold = sum(t["days_held"] for t in trades) / n
    mean_r   = sum(scaled) / n
    std_r    = math.sqrt(sum((r - mean_r) ** 2 for r in scaled) / max(n - 1, 1))
    tpy      = 252 / max(avg_hold, 1)
    sharpe   = (mean_r / std_r) * math.sqrt(tpy) if std_r > 0 else 0.0

    cum = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in scaled:
        cum  *= (1 + r)
        peak  = max(peak, cum)
        if peak > 0:
            max_dd = max(max_dd, (peak - cum) / peak)

    return {
        "n": n, "cagr": cagr, "sharpe": sharpe,
        "max_dd": max_dd, "win_rate": win_rate,
        "avg_hold": avg_hold, "years": years,
    }


def _verdict(m: dict) -> str:
    n, cagr, sh, dd, wr = m["n"], m["cagr"], m["sharpe"], m["max_dd"], m["win_rate"]
    if n >= TIER1_TRADES and cagr >= TIER1_CAGR and sh >= TIER1_SHARPE and dd <= TIER1_MAXDD and wr >= TIER1_WR:
        return "TIER_1"
    if n >= TIER2_TRADES and cagr >= TIER2_CAGR and sh >= TIER2_SHARPE and dd <= TIER2_MAXDD and wr >= TIER2_WR:
        return "TIER_2"
    return "OVERRIDE"


def _make_trade(sym: str, ep: float, ed, xp: float, xd, hold: int, reason: str) -> dict:
    return {
        "sym": sym, "entry_date": ed, "entry_price": ep,
        "exit_date": xd, "exit_price": xp,
        "net_ret": (xp / ep - 1) - COST,
        "days_held": hold, "exit_reason": reason,
    }


# ── Per-symbol trade generators ───────────────────────────────────────────────

def _gen_supertrend(
    sym: str, df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> list[dict]:
    if len(df) < 50:
        return []
    try:
        df = compute_supertrend(df, period=10, multiplier=3.0)
    except Exception as e:
        logger.debug("ST failed %s: %s", sym, e)
        return []

    trades: list[dict] = []
    in_trade = False
    ep = ed = None
    hold = 0

    dirs = df["st_direction"].values
    closes = df["close"].values
    opens  = df["open"].values
    idx    = df.index

    for i in range(1, len(df)):
        dt    = idx[i]
        close = float(closes[i])
        curr_d = int(dirs[i]) if not pd.isna(dirs[i]) else 0
        prev_d = int(dirs[i - 1]) if not pd.isna(dirs[i - 1]) else 0

        if in_trade:
            hold += 1
            pct  = close / ep - 1
            flip = curr_d == -1
            stop = pct <= -ST_HARD_STOP
            time = hold >= ST_MAX_HOLD
            if flip or stop or time:
                reason = "flip" if flip else ("stop" if stop else "time")
                trades.append(_make_trade(sym, ep, ed, close, dt, hold, reason))
                in_trade = False

        if not in_trade and start <= dt <= end:
            if curr_d == 1 and prev_d == -1 and i + 1 < len(df):
                ep = float(opens[i + 1])
                ed = idx[i + 1]
                in_trade = True
                hold = 0

    return trades


def _gen_macd(
    sym: str, df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> list[dict]:
    if len(df) < 50:
        return []
    try:
        macd_line, signal_line, _ = compute_macd(df)
    except Exception as e:
        logger.debug("MACD failed %s: %s", sym, e)
        return []

    trades: list[dict] = []
    in_trade = False
    ep = ed = None
    hold = 0

    closes = df["close"].values
    opens  = df["open"].values
    idx    = df.index
    ml     = macd_line.values
    sl     = signal_line.values

    for i in range(1, len(df)):
        dt    = idx[i]
        close = float(closes[i])
        m_cur = ml[i]
        s_cur = sl[i]
        m_prv = ml[i - 1]
        s_prv = sl[i - 1]

        valid     = not (pd.isna(m_cur) or pd.isna(s_cur))
        valid_prv = not (pd.isna(m_prv) or pd.isna(s_prv))

        if in_trade:
            hold += 1
            pct  = close / ep - 1
            flip = valid and m_cur < s_cur
            stop = pct <= -MACD_HARD_STOP
            time = hold >= MACD_MAX_HOLD
            if flip or stop or time:
                reason = "flip" if flip else ("stop" if stop else "time")
                trades.append(_make_trade(sym, ep, ed, close, dt, hold, reason))
                in_trade = False

        if not in_trade and start <= dt <= end:
            if valid and valid_prv and m_cur > s_cur and m_prv <= s_prv and i + 1 < len(df):
                ep = float(opens[i + 1])
                ed = idx[i + 1]
                in_trade = True
                hold = 0

    return trades


def _gen_ema(
    sym: str, df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> list[dict]:
    if len(df) < 25:
        return []
    try:
        ema9  = compute_ema(df["close"], 9).values
        ema21 = compute_ema(df["close"], 21).values
    except Exception as e:
        logger.debug("EMA failed %s: %s", sym, e)
        return []

    trades: list[dict] = []
    in_trade = False
    ep = ed = None
    hold = 0

    closes = df["close"].values
    opens  = df["open"].values
    idx    = df.index

    for i in range(1, len(df)):
        dt    = idx[i]
        close = float(closes[i])
        e9    = ema9[i]
        e21   = ema21[i]
        e9p   = ema9[i - 1]
        e21p  = ema21[i - 1]

        valid     = not (pd.isna(e9)  or pd.isna(e21))
        valid_prv = not (pd.isna(e9p) or pd.isna(e21p))

        if in_trade:
            hold += 1
            pct  = close / ep - 1
            flip = valid and e9 < e21
            stop = pct <= -EMA_HARD_STOP
            time = hold >= EMA_MAX_HOLD
            if flip or stop or time:
                reason = "flip" if flip else ("stop" if stop else "time")
                trades.append(_make_trade(sym, ep, ed, close, dt, hold, reason))
                in_trade = False

        if not in_trade and start <= dt <= end:
            if valid and valid_prv and e9 > e21 and e9p <= e21p and i + 1 < len(df):
                ep = float(opens[i + 1])
                ed = idx[i + 1]
                in_trade = True
                hold = 0

    return trades


def _gen_52w_high(
    sym: str, df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> list[dict]:
    if len(df) < 280:
        return []
    try:
        prior_max = df["close"].shift(1).rolling(252, min_periods=252).max()
        sma50     = df["close"].rolling(50, min_periods=50).mean()
    except Exception as e:
        logger.debug("52w failed %s: %s", sym, e)
        return []

    trades: list[dict] = []
    in_trade = False
    ep = ed = None
    hold = 0

    closes  = df["close"].values
    opens   = df["open"].values
    idx     = df.index
    pm_vals = prior_max.values
    sm_vals = sma50.values

    for i in range(252, len(df)):
        dt    = idx[i]
        close = float(closes[i])
        pm    = pm_vals[i]
        sm    = sm_vals[i]

        if in_trade:
            hold += 1
            pct      = close / ep - 1
            sma_exit = (not pd.isna(sm)) and close < float(sm)
            stop     = pct <= -W52_HARD_STOP
            time     = hold >= W52_MAX_HOLD
            if sma_exit or stop or time:
                reason = "sma" if sma_exit else ("stop" if stop else "time")
                trades.append(_make_trade(sym, ep, ed, close, dt, hold, reason))
                in_trade = False

        if not in_trade and start <= dt <= end:
            if (not pd.isna(pm)) and close >= float(pm) and i + 1 < len(df):
                ep = float(opens[i + 1])
                ed = idx[i + 1]
                in_trade = True
                hold = 0

    return trades


# ── Runner ────────────────────────────────────────────────────────────────────

def _run_strategy(
    name: str,
    gen_fn,
    sym_data: dict[str, pd.DataFrame],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[list[dict], dict, str]:
    all_trades: list[dict] = []
    for sym, df in sym_data.items():
        all_trades.extend(gen_fn(sym, df, start, end))
    logger.info("[%s] Raw trades: %d — applying concurrency filter …", name, len(all_trades))
    all_trades = _apply_concurrency(all_trades, MAX_CONC)
    m = _metrics(all_trades)
    v = _verdict(m)
    logger.info(
        "[%s] %d trades | CAGR %+.1f%% | Sharpe %.2f | MaxDD %.1f%% | WR %.1f%% → %s",
        name, m["n"], m["cagr"] * 100, m["sharpe"],
        m["max_dd"] * 100, m["win_rate"] * 100, v,
    )
    return all_trades, m, v


# ── Output ────────────────────────────────────────────────────────────────────

def _print_result(name: str, m: dict, v: str) -> None:
    sep = "=" * 66
    print()
    print(sep)
    print(f"STRATEGY: {name}")
    print(sep)
    if m["n"] == 0:
        print("  No trades generated.")
        print(sep)
        return
    print(f"{'Trades':<35}: {m['n']}")
    print(f"{'CAGR':<35}: {m['cagr']*100:+.1f}%")
    print(f"{'Sharpe (ann.)':<35}: {m['sharpe']:.2f}")
    print(f"{'Max drawdown':<35}: {m['max_dd']*100:.1f}%")
    print(f"{'Win rate':<35}: {m['win_rate']*100:.1f}%")
    print(f"{'Avg hold (trading days)':<35}: {m['avg_hold']:.1f}")
    print()
    print(f"VERDICT: {v}")
    checks = [
        (f"Trades ≥ {TIER1_TRADES}",          m["n"]        >= TIER1_TRADES,  f"{m['n']}"),
        (f"CAGR ≥ {TIER1_CAGR*100:.0f}%",     m["cagr"]     >= TIER1_CAGR,    f"{m['cagr']*100:.1f}%"),
        (f"Sharpe ≥ {TIER1_SHARPE}",           m["sharpe"]   >= TIER1_SHARPE,  f"{m['sharpe']:.2f}"),
        (f"MaxDD ≤ {TIER1_MAXDD*100:.0f}%",    m["max_dd"]   <= TIER1_MAXDD,   f"{m['max_dd']*100:.1f}%"),
        (f"WinRate ≥ {TIER1_WR*100:.0f}%",     m["win_rate"] >= TIER1_WR,      f"{m['win_rate']*100:.1f}%"),
    ]
    for label, ok, val in checks:
        mark = "OK" if ok else "--"
        print(f"  [{mark}] {label} -> {val}")
    print(sep)


def _print_summary(results: dict) -> None:
    sep = "=" * 75
    print()
    print(sep)
    print("SUMMARY — MWA Scanner Backtest")
    print(f"{'Strategy':<28} {'Trades':>6} {'CAGR':>7} {'Sharpe':>7} {'MaxDD':>7} {'WinRate':>8}  Verdict")
    print("-" * 75)
    for name, (_, m, v) in results.items():
        print(
            f"{name:<28} {m['n']:>6}  {m['cagr']*100:>+5.1f}%  {m['sharpe']:>6.2f}  "
            f"{m['max_dd']*100:>5.1f}%   {m['win_rate']*100:>5.1f}%  {v}"
        )
    print(sep)


# ── Main ──────────────────────────────────────────────────────────────────────

_STRATEGY_MAP = {
    "supertrend": ("Supertrend (10,3) flip", _gen_supertrend),
    "macd":       ("MACD (12,26,9) cross",   _gen_macd),
    "ema":        ("EMA 9/21 cross",          _gen_ema),
    "52w":        ("52-Week High breakout",   _gen_52w_high),
}


def main() -> None:
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="MWA Python Scanner Validation")
    parser.add_argument("--from",        dest="start",       default="2021-01-01")
    parser.add_argument("--to",          dest="end",         default=str(date.today()))
    parser.add_argument("--strategy",    choices=list(_STRATEGY_MAP) + ["all"], default="all")
    parser.add_argument("--max-symbols", type=int, default=None,
                        help="Limit symbols for quick testing (e.g. 50)")
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)
    data_start = start_date.replace(year=start_date.year - 1).isoformat()

    tickers  = _load_tickers(args.max_symbols)
    sym_data = _load_prices(tickers, data_start, args.end)
    if not sym_data:
        logger.error("No data loaded. Exiting.")
        return

    start_ts = pd.Timestamp(args.start)
    end_ts   = pd.Timestamp(args.end)

    if args.strategy == "all":
        strategies = list(_STRATEGY_MAP.values())
    else:
        strategies = [_STRATEGY_MAP[args.strategy]]

    results: dict[str, tuple] = {}
    for name, fn in strategies:
        trades, m, v = _run_strategy(name, fn, sym_data, start_ts, end_ts)
        results[name] = (trades, m, v)
        _print_result(name, m, v)

    if len(results) > 1:
        _print_summary(results)

    out = Path("reports") / f"mwa_scanner_validation_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        f"# MWA Scanner Validation — {date.today()}",
        f"Universe: Nifty 500 | Period: {args.start} → {args.end} | ₹{POSITION_INR/1000:.0f}k/trade | Max {MAX_CONC} concurrent",
        "",
        "| Strategy | Trades | CAGR | Sharpe | MaxDD | WinRate | Verdict |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, (_, m, v) in results.items():
        lines.append(
            f"| {name} | {m['n']} | {m['cagr']*100:+.1f}% | {m['sharpe']:.2f} "
            f"| {m['max_dd']*100:.1f}% | {m['win_rate']*100:.1f}% | **{v}** |"
        )
    out.write_text("\n".join(lines, encoding='utf-8'), encoding="utf-8")
    logger.info("Report saved: %s", out)

    try:
        from mcp_server.sheets_sync import log_backtest_result
        for name, (_, m, v) in results.items():
            log_backtest_result({
                "strategy": f"MWA: {name}",
                "timeframe": "1d",
                "period": f"{args.start} to {args.end}",
                "universe": f"Nifty 500 ({len(sym_data)} symbols)",
                "trades": m["n"],
                "cagr": round(m["cagr"] * 100, 2),
                "sharpe": round(m["sharpe"], 2),
                "max_dd": round(m["max_dd"] * 100, 2),
                "win_rate": round(m["win_rate"] * 100, 2),
                "verdict": v,
                "notes": "Standalone indicator. OVERRIDE expected — confluence input to composite MWA score.",
            })
    except Exception as e:
        logger.warning("Sheets logging skipped: %s", e)


if __name__ == "__main__":
    main()
