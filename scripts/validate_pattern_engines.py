"""
Pattern Engine Validation — Sliding-Window Backtest

Backtests 4 pattern-detection engines using the correct point-in-time approach:
for each bar T, passes df.iloc[:T+1] to detect_all() so the engine sees only
historical data (its internal .tail(lookback) then uses the 60/120 most recent
bars ending at T — no lookahead).

Engines tested:
  1. SMC   — Break of Structure, CHoCH, Order Blocks, FVG, Liquidity Sweep, etc.
  2. VSA   — Volume Spread Analysis (stopping volume, climax, no-supply)
  3. Wyckoff — Accumulation/Distribution, Spring, Upthrust
  4. Harmonic — Gartley, Bat, Crab, Cypher bullish patterns

Signal: ANY bullish PatternResult from detect_all() fires -> entry at next open
Exit  : -7% hard stop OR 20 trading days (whichever first)

Performance note: sliding-window is O(N×T) per engine. Default --step 5 samples
every 5th bar (~weekly) to keep total runtime ~15-20 min for all 4 engines on
Nifty 500. Use --step 1 for daily (3-4x slower per engine).

Usage:
    python scripts/validate_pattern_engines.py
    python scripts/validate_pattern_engines.py --engine smc --max-symbols 50
    python scripts/validate_pattern_engines.py --step 1 --max-symbols 100
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pattern_engine_validation")

# ── Position / cost constants ─────────────────────────────────────────────────
POSITION_INR = 100_000.0
MAX_CONC     = 5
HARD_STOP    = 0.07
MAX_HOLD     = 20

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


def _trade_cost() -> float:
    p = POSITION_INR
    c  = BROKERAGE * 2
    c += STT_SELL * p
    c += EXCHANGE * 2 * p
    c += (BROKERAGE * 2 + EXCHANGE * 2 * p) * GST
    c += STAMP * p + SLIPPAGE * 2 * p
    return c / p


COST = _trade_cost()


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
        logger.info("Downloading batch %d-%d / %d ...", i + 1, i + len(chunk), len(tickers))
        try:
            raw = yf.download(chunk, start=start_str, end=end_str,
                              auto_adjust=True, progress=False, threads=True)
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
                if len(df_s) >= 150:
                    result[sym] = df_s
            except Exception:
                pass
    logger.info("Loaded %d symbols", len(result))
    return result


# ── Concurrency + metrics (same as validate_mwa_python_scanners) ──────────────

def _apply_concurrency(trades: list[dict], max_conc: int) -> list[dict]:
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


def _metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "cagr": 0.0, "sharpe": 0.0, "max_dd": 0.0, "win_rate": 0.0, "avg_hold": 0.0}
    trades = sorted(trades, key=lambda t: t["entry_date"])
    n    = len(trades)
    rets = [t["net_ret"] for t in trades]
    win_rate  = sum(1 for r in rets if r > 0) / n
    first_date = min(t["entry_date"] for t in trades)
    last_date  = max(t["exit_date"]  for t in trades)
    years = max((last_date - first_date).days / 365.25, 0.1)

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

    return {"n": n, "cagr": cagr, "sharpe": sharpe, "max_dd": max_dd,
            "win_rate": win_rate, "avg_hold": avg_hold, "years": years}


def _verdict(m: dict) -> str:
    n, cagr, sh, dd, wr = m["n"], m["cagr"], m["sharpe"], m["max_dd"], m["win_rate"]
    if n >= TIER1_TRADES and cagr >= TIER1_CAGR and sh >= TIER1_SHARPE and dd <= TIER1_MAXDD and wr >= TIER1_WR:
        return "TIER_1"
    if n >= TIER2_TRADES and cagr >= TIER2_CAGR and sh >= TIER2_SHARPE and dd <= TIER2_MAXDD and wr >= TIER2_WR:
        return "TIER_2"
    return "OVERRIDE"


# ── Core sliding-window backtest ──────────────────────────────────────────────

def _backtest_engine(
    engine_name: str,
    engine,
    sym_data: dict[str, pd.DataFrame],
    start: pd.Timestamp,
    end: pd.Timestamp,
    step: int,
) -> list[dict]:
    """
    Slide a window through each symbol's history.
    For every bar T (sampled every `step` bars), call detect_all(df[:T+1]).
    If any BULLISH pattern fires -> entry at open[T+1].
    Exit: -7% hard stop OR 20-bar max hold.
    """
    lookback = engine.lookback
    all_trades: list[dict] = []
    total = len(sym_data)

    for si, (sym, df) in enumerate(sym_data.items(), 1):
        if si % 50 == 0:
            logger.info("[%s] %d/%d symbols processed ...", engine_name, si, total)

        closes = df["close"].values
        opens  = df["open"].values
        idx    = df.index
        n      = len(df)

        in_trade   = False
        entry_price = None
        entry_date  = None
        hold        = 0

        i = lookback  # start after warmup
        while i < n:
            dt    = idx[i]
            close = float(closes[i])

            if in_trade:
                hold += 1
                pct  = close / entry_price - 1
                stop = pct <= -HARD_STOP
                time_exit = hold >= MAX_HOLD

                if stop or time_exit:
                    net = pct - COST
                    all_trades.append({
                        "sym": sym, "engine": engine_name,
                        "entry_date": entry_date, "entry_price": entry_price,
                        "exit_date": dt, "exit_price": close,
                        "net_ret": net, "days_held": hold,
                        "exit_reason": "stop" if stop else "time",
                    })
                    in_trade = False
                i += 1
                continue

            # Only check for new signals on sampled bars
            if (i - lookback) % step == 0 and start <= dt <= end:
                try:
                    patterns = engine.detect_all(df.iloc[: i + 1])
                    has_bull = any(p.direction == "BULLISH" for p in patterns)
                except Exception:
                    has_bull = False

                if has_bull and i + 1 < n:
                    entry_price = float(opens[i + 1])
                    entry_date  = idx[i + 1]
                    in_trade    = True
                    hold        = 0
                    i += 1
                    continue

            i += 1

    return all_trades


# ── Runner + output ───────────────────────────────────────────────────────────

def _run(name: str, engine, sym_data, start, end, step) -> tuple[list[dict], dict, str]:
    logger.info("=== %s === (step=%d, %d symbols)", name, step, len(sym_data))
    trades = _backtest_engine(name, engine, sym_data, start, end, step)
    logger.info("[%s] Raw trades: %d | applying concurrency ...", name, len(trades))
    trades = _apply_concurrency(trades, MAX_CONC)
    m = _metrics(trades)
    v = _verdict(m)
    logger.info(
        "[%s] %d trades | CAGR %+.1f%% | Sharpe %.2f | MaxDD %.1f%% | WR %.1f%% -> %s",
        name, m["n"], m["cagr"] * 100, m["sharpe"], m["max_dd"] * 100, m["win_rate"] * 100, v,
    )
    return trades, m, v


def _print_result(name: str, m: dict, v: str) -> None:
    sep = "=" * 66
    print()
    print(sep)
    print(f"ENGINE: {name}")
    print(sep)
    if m["n"] == 0:
        print("  No trades generated.")
        print(sep)
        return
    print(f"{'Trades':<35}: {m['n']}")
    print(f"{'CAGR (portfolio)':<35}: {m['cagr']*100:+.1f}%")
    print(f"{'Sharpe (ann.)':<35}: {m['sharpe']:.2f}")
    print(f"{'Max drawdown':<35}: {m['max_dd']*100:.1f}%")
    print(f"{'Win rate':<35}: {m['win_rate']*100:.1f}%")
    print(f"{'Avg hold (days)':<35}: {m['avg_hold']:.1f}")
    print()
    print(f"VERDICT: {v}")
    checks = [
        (f"Trades >= {TIER1_TRADES}",        m["n"]        >= TIER1_TRADES,  f"{m['n']}"),
        (f"CAGR >= {TIER1_CAGR*100:.0f}%",   m["cagr"]     >= TIER1_CAGR,    f"{m['cagr']*100:.1f}%"),
        (f"Sharpe >= {TIER1_SHARPE}",         m["sharpe"]   >= TIER1_SHARPE,  f"{m['sharpe']:.2f}"),
        (f"MaxDD <= {TIER1_MAXDD*100:.0f}%",  m["max_dd"]   <= TIER1_MAXDD,   f"{m['max_dd']*100:.1f}%"),
        (f"WinRate >= {TIER1_WR*100:.0f}%",   m["win_rate"] >= TIER1_WR,      f"{m['win_rate']*100:.1f}%"),
    ]
    for label, ok, val in checks:
        mark = "OK" if ok else "--"
        print(f"  [{mark}] {label} -> {val}")
    print(sep)


def _print_summary(results: dict) -> None:
    sep = "=" * 72
    print()
    print(sep)
    print("SUMMARY — Pattern Engine Backtest")
    print(f"{'Engine':<20} {'Trades':>6} {'CAGR':>7} {'Sharpe':>7} {'MaxDD':>7} {'WinRate':>8}  Verdict")
    print("-" * 72)
    for name, (_, m, v) in results.items():
        print(
            f"{name:<20} {m['n']:>6}  {m['cagr']*100:>+5.1f}%  {m['sharpe']:>6.2f}  "
            f"{m['max_dd']*100:>5.1f}%   {m['win_rate']*100:>5.1f}%  {v}"
        )
    print(sep)


# ── Main ──────────────────────────────────────────────────────────────────────

_ENGINE_CHOICES = ["smc", "vsa", "wyckoff", "harmonic", "all"]


def main() -> None:
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Pattern Engine Sliding-Window Backtest")
    parser.add_argument("--from",        dest="start",       default="2021-01-01")
    parser.add_argument("--to",          dest="end",         default=str(date.today()))
    parser.add_argument("--engine",      choices=_ENGINE_CHOICES, default="all")
    parser.add_argument("--step",        type=int,           default=5,
                        help="Sample every N bars (1=daily, 5=weekly). Default 5.")
    parser.add_argument("--max-symbols", type=int,           default=None,
                        help="Limit to first N symbols for quick testing")
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)
    data_start = start_date.replace(year=start_date.year - 1).isoformat()

    tickers  = _load_tickers(args.max_symbols)
    sym_data = _load_prices(tickers, data_start, args.end)
    if not sym_data:
        logger.error("No data loaded.")
        return

    start_ts = pd.Timestamp(args.start)
    end_ts   = pd.Timestamp(args.end)

    # Instantiate engines
    from mcp_server.smc_engine      import SMCEngine
    from mcp_server.vsa_engine      import VSAEngine
    from mcp_server.wyckoff_engine  import WyckoffEngine
    from mcp_server.harmonic_engine import HarmonicEngine

    all_engines = {
        "SMC":      SMCEngine(),
        "VSA":      VSAEngine(),
        "Wyckoff":  WyckoffEngine(),
        "Harmonic": HarmonicEngine(),
    }
    engine_map = {
        "smc":      {"SMC":      all_engines["SMC"]},
        "vsa":      {"VSA":      all_engines["VSA"]},
        "wyckoff":  {"Wyckoff":  all_engines["Wyckoff"]},
        "harmonic": {"Harmonic": all_engines["Harmonic"]},
        "all":      all_engines,
    }
    engines_to_run = engine_map[args.engine]

    results: dict[str, tuple] = {}
    for name, engine in engines_to_run.items():
        trades, m, v = _run(name, engine, sym_data, start_ts, end_ts, args.step)
        results[name] = (trades, m, v)
        _print_result(name, m, v)

    if len(results) > 1:
        _print_summary(results)

    # Save markdown report
    out = Path("reports") / f"pattern_engines_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        f"# Pattern Engine Backtest — {date.today()}",
        f"Universe: Nifty 500 | Period: {args.start} -> {args.end} | Step: {args.step} bars | Max conc: {MAX_CONC}",
        f"Exit: -{HARD_STOP*100:.0f}% stop OR {MAX_HOLD}d max hold",
        "",
        "| Engine | Trades | CAGR | Sharpe | MaxDD | WinRate | Verdict |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, (_, m, v) in results.items():
        lines.append(
            f"| {name} | {m['n']} | {m['cagr']*100:+.1f}% | {m['sharpe']:.2f} "
            f"| {m['max_dd']*100:.1f}% | {m['win_rate']*100:.1f}% | **{v}** |"
        )
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Report saved: %s", out)

    # Log to Google Sheets
    try:
        from mcp_server.sheets_sync import log_backtest_result
        for name, (_, m, v) in results.items():
            log_backtest_result({
                "strategy": f"Pattern Engine: {name}",
                "timeframe": "1d",
                "period": f"{args.start} to {args.end}",
                "universe": f"Nifty 500 ({len(sym_data)} symbols)",
                "trades": m["n"],
                "cagr": round(m["cagr"] * 100, 2),
                "sharpe": round(m["sharpe"], 2),
                "max_dd": round(m["max_dd"] * 100, 2),
                "win_rate": round(m["win_rate"] * 100, 2),
                "verdict": v,
                "notes": (
                    f"Sliding window step={args.step}. "
                    f"Exit: -{HARD_STOP*100:.0f}% stop OR {MAX_HOLD}d. "
                    "Standalone engine — confluence input to MWA composite."
                ),
            })
    except Exception as e:
        logger.warning("Sheets logging skipped: %s", e)


if __name__ == "__main__":
    main()
