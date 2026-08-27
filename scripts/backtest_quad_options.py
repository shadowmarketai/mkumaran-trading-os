#!/usr/bin/env python3
"""
Backtest the Quad Confluence OPTIONS strategy on index underlying moves.

WHAT THIS MEASURES
------------------
Whether the INDEX moves favourably after a 4/4 trigger, and how fast. It
reports the metrics that decide whether a long-option trade could work:

  move_pct        index move from entry to exit, signed by direction
  bars_held       time in trade -> theta exposure
  mae_pct         max adverse excursion -> would the premium stop have hit
  pts_per_bar     move speed; slow moves lose to decay even when right

WHAT THIS DOES NOT MEASURE
--------------------------
Option P&L. Premium history is not in the OHLCV cache, so entry/exit
premiums cannot be reconstructed. A favourable index move can still lose
on the option through theta or a post-entry IV drop.

Read the output as a filter, not a verdict:
  - index doesn't move after 4/4  -> the option definitely loses. Stop here.
  - index moves fast and far      -> the option MIGHT profit. Paper trade next.

ROUGH PREMIUM PROXY
-------------------
With --delta, a crude ATM approximation is applied: premium change is
estimated as delta * index move, minus a flat theta drag per bar. Delta is
assumed 0.5 at entry (ATM) and theta is a percentage of premium per bar.
This is a sanity check, NOT a pricing model — no vega, no gamma, no smile.
Treat any number it produces as an order of magnitude at best.

Usage:
    python scripts/backtest_quad_options.py --symbols NIFTY,BANKNIFTY --interval 15m --days 180
    python scripts/backtest_quad_options.py --interval 1d --days 730 --delta
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from mcp_server import quad_confluence_options as qco

YF_INDEX = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    # These two have no reliable Yahoo feed — the previously used tickers
    # returned a single bar. Left as None so they are skipped with a clear
    # message instead of silently producing garbage. Use the Dhan 15m cache
    # on the server for these.
    "FINNIFTY": None,
    "MIDCPNIFTY": None,
}
THETA_PCT_PER_BAR = 0.004   # daily-bar default; scaled by --interval below
ENTRY_DELTA = 0.5           # ATM

# Rough theta drag per bar, as a fraction of premium. Daily ~0.4%/bar; an
# intraday bar carries proportionally less decay. These are crude constants,
# not a pricing model — see the module docstring.
THETA_BY_INTERVAL = {
    "1d": 0.004,
    "60m": 0.0008,
    "30m": 0.0004,
    "15m": 0.0002,
    "5m": 0.00007,
    "3m": 0.00004,
}


def _load_bars(symbol: str, interval: str, days: int) -> pd.DataFrame:
    """Load index bars.

    Intraday: try the Dhan-populated ohlcv_cache first (server only), then
    fall back to Yahoo. Yahoo caps intraday history at ~60 days regardless
    of the --days value, so a local intraday run is always a short window.
    Daily: Yahoo.
    """
    if interval not in ("1d", "1wk"):
        try:
            from mcp_server.backtester import _load_from_cache

            for key in (symbol, f"NSE:{symbol}", f"NFO:{symbol}"):
                df = _load_from_cache(key, interval, days)
                if df is not None and not df.empty and len(df) > 60:
                    print(f"{symbol:<12} using ohlcv_cache ({len(df)} bars)")
                    return df
        except Exception as e:  # noqa: BLE001 - DB unreachable is expected off-server
            print(f"{symbol:<12} ohlcv_cache unavailable ({type(e).__name__}) — using Yahoo")

        return _yahoo_bars(symbol, interval, days)

    return _yahoo_bars(symbol, "1d", days)


def _yahoo_bars(symbol: str, interval: str, days: int) -> pd.DataFrame:
    """Fetch index bars from Yahoo. Intraday is capped at 60 days by Yahoo."""
    import yfinance as yf

    yf_sym = YF_INDEX.get(symbol)
    if not yf_sym:
        print(f"{symbol:<12} no Yahoo feed — needs ohlcv_cache on the server")
        return pd.DataFrame()

    if interval in ("1d", "1wk"):
        period = "5y" if days > 1095 else "3y" if days > 730 else "2y"
    else:
        period = "60d"          # Yahoo hard limit for intraday
        if days > 60:
            print(f"{symbol:<12} note: Yahoo caps intraday at 60d "
                  f"(asked {days}d)")

    try:
        df = yf.Ticker(yf_sym).history(period=period, interval=interval)
    except Exception as e:  # noqa: BLE001 - report and skip this symbol
        print(f"{symbol:<12} Yahoo fetch failed: {e}")
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()
    df.columns = [c.lower() for c in df.columns]
    keep = [c for c in ("open", "high", "low", "close") if c in df.columns]
    if len(keep) < 4:
        return pd.DataFrame()
    return df[keep].dropna()


def _walk(cond: pd.DataFrame, symbol: str, use_delta: bool, theta: float = THETA_PCT_PER_BAR) -> list[dict]:
    """Walk 4/4 triggers, exit on SuperTrend flip, record underlying metrics."""
    trades: list[dict] = []
    in_pos = False
    side = ""
    entry_px = 0.0
    entry_i = 0
    mae = 0.0

    start = qco.BB_PERIOD + 15
    for i in range(start, len(cond) - 1):
        if not in_pos:
            if bool(cond["entry_ce"].iloc[i]):
                side = "CE"
            elif bool(cond["entry_pe"].iloc[i]):
                side = "PE"
            else:
                continue
            entry_px = float(cond["open"].iloc[i + 1])   # next-bar open
            entry_i = i + 1
            mae = 0.0
            in_pos = True
            continue

        # Track max adverse excursion while in the trade
        if side == "CE":
            adverse = (float(cond["low"].iloc[i]) - entry_px) / entry_px * 100
            flipped = int(cond["st_dir"].iloc[i]) == -1
        else:
            adverse = (entry_px - float(cond["high"].iloc[i])) / entry_px * 100
            flipped = int(cond["st_dir"].iloc[i]) == 1
        mae = min(mae, adverse)

        if not flipped:
            continue

        exit_px = float(cond["close"].iloc[i])
        raw = (exit_px - entry_px) / entry_px * 100
        move_pct = raw if side == "CE" else -raw
        bars = i - entry_i

        rec = {
            "symbol": symbol,
            "side": side,
            "entry": round(entry_px, 2),
            "exit": round(exit_px, 2),
            "move_pct": round(move_pct, 3),
            "mae_pct": round(mae, 3),
            "bars_held": bars,
            "pts_per_bar": round((exit_px - entry_px) / max(bars, 1), 2),
        }
        if use_delta:
            # Crude ATM proxy — see module docstring. Not a pricing model.
            gross = ENTRY_DELTA * move_pct * (100 / ENTRY_DELTA) / 100
            decay = theta * 100 * bars
            rec["est_premium_pct"] = round(gross - decay, 2)
        trades.append(rec)
        in_pos = False

    return trades


def _summarise(trades: list[dict], label: str, use_delta: bool) -> dict:
    if not trades:
        return {"bucket": label, "trades": 0}
    moves = [t["move_pct"] for t in trades]
    wins = [m for m in moves if m > 0]
    row = {
        "bucket": label,
        "trades": len(trades),
        "move_win_rate": round(len(wins) / len(trades) * 100, 1),
        "avg_move_pct": round(sum(moves) / len(moves), 3),
        "avg_win_move": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_bars": round(sum(t["bars_held"] for t in trades) / len(trades), 1),
        "avg_mae_pct": round(sum(t["mae_pct"] for t in trades) / len(trades), 2),
        "worst_mae_pct": round(min(t["mae_pct"] for t in trades), 2),
    }
    if use_delta:
        est = [t["est_premium_pct"] for t in trades]
        row["est_prem_win_rate"] = round(
            sum(1 for e in est if e > 0) / len(est) * 100, 1
        )
        row["est_prem_avg_pct"] = round(sum(est) / len(est), 2)
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="NIFTY,BANKNIFTY,FINNIFTY,MIDCPNIFTY")
    ap.add_argument("--interval", default="15m")
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--delta", action="store_true", help="add crude premium proxy")
    ap.add_argument("--out", default="quad_options_results.json")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    all_trades: list[dict] = []
    per_symbol: list[dict] = []

    for sym in symbols:
        bars = _load_bars(sym, args.interval, args.days)
        if bars.empty:
            print(f"{sym:<12} no {args.interval} data — skipped")
            continue
        cond = qco.compute_index_conditions(bars)
        theta = THETA_BY_INTERVAL.get(args.interval, THETA_PCT_PER_BAR)
        trades = _walk(cond, sym, args.delta, theta)
        n4 = int(cond["entry_ce"].sum() + cond["entry_pe"].sum())
        n3 = int(((cond["ce_count"] == 3) | (cond["pe_count"] == 3)).sum())
        print(
            f"{sym:<12} bars={len(bars):>6}  4/4 triggers={n4:>4}  "
            f"3/4 bars={n3:>5}  trades={len(trades):>4}"
        )
        all_trades.extend(trades)
        per_symbol.append(_summarise(trades, sym, args.delta))

    if not all_trades:
        print("\nNo trades generated. Either no data or the gate never fired.")
        return 1

    print()
    rows = per_symbol + [_summarise(all_trades, "ALL", args.delta)]
    cols = ["bucket", "trades", "move_win_rate", "avg_move_pct", "avg_bars",
            "avg_mae_pct", "worst_mae_pct"]
    if args.delta:
        cols += ["est_prem_win_rate", "est_prem_avg_pct"]
    hdr = "".join(f"{c:>18}" if c != "bucket" else f"{c:<12}" for c in cols)
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        line = f"{r.get('bucket', ''):<12}"
        for c in cols[1:]:
            line += f"{r.get(c, 0):>18}"
        print(line)

    ce = [t for t in all_trades if t["side"] == "CE"]
    pe = [t for t in all_trades if t["side"] == "PE"]
    print(f"\nCE trades: {len(ce)}   PE trades: {len(pe)}")

    print("\nHow to read this:")
    print("  - move_win_rate is the INDEX direction hit rate, not option P&L.")
    print("  - avg_bars is theta exposure: long holds bleed premium even when right.")
    print("  - worst_mae_pct vs a 35% premium stop: a ~1% adverse index move can")
    print("    wipe ~35% of an ATM premium, so small MAE numbers still matter.")
    print("  - Under ~100 trades, treat everything here as inconclusive.")

    Path(args.out).write_text(
        json.dumps({"summary": rows, "trades": all_trades}, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
