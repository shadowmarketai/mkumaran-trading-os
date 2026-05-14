"""
Intraday Scanner Validation — all 8 patterns
Dhan 1-min data resampled to 5m / 15m bars. Max window: 90 trading days.

Each scanner is evaluated independently. One position per scanner per
ticker per day. Exit rules: target (RRR 2×SL), SL touch, or EOD force-
close at 15:10 IST. Costs follow the same model as validate_bb_3min_dhan.py.

Tier criteria (90-day window, ~50 tickers):
  TIER_1 : ≥ 20 trades, WR ≥ 55%, Sharpe ≥ 0.8
  TIER_2 : ≥ 10 trades, WR ≥ 45%, Sharpe ≥ 0.5
  OVERRIDE: below TIER_2 — confluence input only, disable standalone emission

After running, set in .env:
  INTRADAY_VALIDATED_SCANNERS="orb,vwap,..."   (comma-separated TIER_1/TIER_2 names)

Usage:
    python scripts/validate_intraday_scanners.py
    python scripts/validate_intraday_scanners.py --days 60
    python scripts/validate_intraday_scanners.py --tickers RELIANCE HDFCBANK ONGC
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from datetime import date, time as dtime
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("intraday_val")

# ── Universe ──────────────────────────────────────────────────────────────────

NIFTY50: list[str] = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJFINSV", "BAJFINANCE", "BEL", "BHARTIARTL", "BPCL",
    "BRITANNIA", "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT",
    "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY", "ITC",
    "JSWSTEEL", "KOTAKBANK", "LT", "MARUTI", "NESTLEIND",
    "NTPC", "ONGC", "POWERGRID", "RELIANCE", "SBILIFE",
    "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM", "TATAMOTORS",
    "TATASTEEL", "TCS", "TECHM", "TITAN", "TRENT",
    "ULTRACEMCO", "WIPRO", "ZOMATO",
]

# ── Cost model (intraday) ─────────────────────────────────────────────────────

POSITION_INR = 100_000.0
BROKERAGE    = 20.0
STT_SELL     = 0.00025    # 0.025% sell side, intraday
EXCHANGE     = 0.0000345
GST          = 0.18
STAMP        = 0.00003
SLIPPAGE     = 0.001      # 0.1% per leg

SESSION_END = dtime(15, 10)   # force-close all positions at 15:10 IST

# ── Tier criteria ─────────────────────────────────────────────────────────────

TIER1 = {"trades": 20, "wr": 0.55, "sharpe": 0.8}
TIER2 = {"trades": 10, "wr": 0.45, "sharpe": 0.5}


def _cost(pos: float) -> float:
    buy  = pos * (1 + SLIPPAGE)
    sell = pos * (1 - SLIPPAGE)
    c    = BROKERAGE * 2 + sell * STT_SELL
    c   += (buy + sell) * EXCHANGE
    c   += (BROKERAGE * 2 + (buy + sell) * EXCHANGE) * GST
    c   += buy * STAMP
    return c


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_dhan_1min(symbols: list[str], days: int) -> dict[str, pd.DataFrame]:
    """Fetch Dhan 1-min bars for each symbol. Returns {sym: df} indexed by ts."""
    from mcp_server.data_provider import DhanSource
    dhan = DhanSource()
    if not dhan.login():
        logger.error(
            "Dhan login failed — set DHAN_CLIENT_ID + DHAN_ACCESS_TOKEN "
            "(or DHAN_TOTP_KEY + DHAN_PIN for auto-refresh)"
        )
        return {}

    logger.info("Fetching 1-min data: %d symbols × %d days...", len(symbols), days)
    result: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        try:
            df = dhan.get_historical(sym, interval="1minute", days=days, exchange="NSE")
            if df is None or df.empty:
                continue
            df = df.copy()
            df["ts"] = pd.to_datetime(df["date"])
            df = df.set_index("ts").sort_index()
            df.columns = [c.lower() for c in df.columns]
            result[sym] = df
            logger.debug("Loaded %s: %d bars", sym, len(df))
        except Exception as exc:
            logger.warning("Skip %s: %s", sym, exc)

    logger.info("Loaded %d / %d symbols", len(result), len(symbols))
    return result


def _resample(df1m: pd.DataFrame, freq: str) -> pd.DataFrame:
    agg: dict = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df1m.columns:
        agg["volume"] = "sum"
    return df1m.resample(freq).agg(agg).dropna(subset=["close"])


def _split_by_date(df: pd.DataFrame) -> dict[date, pd.DataFrame]:
    """Split resampled DataFrame into per-day slices, NSE session only."""
    days: dict[date, pd.DataFrame] = {}
    for d, grp in df.groupby(df.index.date):
        session = grp.between_time("09:15", "15:30")
        if len(session) >= 4:
            days[d] = session
    return days


def _prev_hl(days: dict[date, pd.DataFrame], today: date) -> tuple[float | None, float | None]:
    """Previous trading day's high and low from the supplied per-day map."""
    sorted_days = sorted(days.keys())
    if today not in sorted_days:
        return None, None
    idx = sorted_days.index(today)
    if idx == 0:
        return None, None
    prev_df = days[sorted_days[idx - 1]]
    return float(prev_df["high"].max()), float(prev_df["low"].min())


# ── Load scanner functions ────────────────────────────────────────────────────

def _load_scanners() -> list[tuple[str, object, bool, bool]]:
    """
    Import scanner callables from intraday_scanner.
    Returns [(key, fn, needs_5m, needs_15m)].
    """
    from mcp_server.intraday_scanner import (
        scan_ema_crossover_mtf,
        scan_momentum,
        scan_orb,
        scan_prev_day_hl,
        scan_rsi_reversal_15m,
        scan_supertrend_15m,
        scan_vwap,
        scan_vwap_ema_confluence,
    )
    return [
        ("orb",         scan_orb,                True,  False),
        ("vwap",        scan_vwap,               True,  False),
        ("momentum",    scan_momentum,            True,  False),
        ("prev_day_hl", scan_prev_day_hl,         True,  False),
        ("vwap_ema",    scan_vwap_ema_confluence, True,  False),
        ("ema_cross",   scan_ema_crossover_mtf,   True,  True),
        ("supertrend",  scan_supertrend_15m,      False, True),
        ("rsi_rev",     scan_rsi_reversal_15m,    False, True),
    ]


# ── Simulation ────────────────────────────────────────────────────────────────

def _simulate_symbol(
    sym: str,
    days_5m: dict[date, pd.DataFrame],
    days_15m: dict[date, pd.DataFrame],
    scanners: list[tuple[str, object, bool, bool]],
) -> list[dict]:
    """
    Walk-forward day-by-day replay for one symbol.
    One position per scanner per day; no re-entry after first signal.
    """
    trades: list[dict] = []

    for day in sorted(days_5m.keys()):
        df5_day = days_5m[day]
        df15_day = days_15m.get(day, pd.DataFrame())
        ph, pl = _prev_hl(days_5m, day)

        # open_pos: {scanner_key: {direction, entry, target, sl}}
        open_pos: dict[str, dict] = {}
        fired_today: set[str] = set()

        bars = list(df5_day.iterrows())
        n = len(bars)

        for bar_idx, (ts, row) in enumerate(bars):
            is_eod = row.name.time() >= SESSION_END or bar_idx == n - 1  # type: ignore[union-attr]
            high  = float(row["high"])
            low   = float(row["low"])
            close = float(row["close"])

            # ── Exits (check BEFORE entries so no same-bar fill) ────────────
            for key in list(open_pos.keys()):
                pos = open_pos[key]
                exit_px: float | None = None
                exit_why = ""

                if pos["direction"] == "LONG":
                    if low <= pos["sl"]:
                        exit_px, exit_why = pos["sl"], "sl"
                    elif high >= pos["target"]:
                        exit_px, exit_why = pos["target"], "target"
                    elif is_eod:
                        exit_px, exit_why = close, "eod"
                else:
                    if high >= pos["sl"]:
                        exit_px, exit_why = pos["sl"], "sl"
                    elif low <= pos["target"]:
                        exit_px, exit_why = pos["target"], "target"
                    elif is_eod:
                        exit_px, exit_why = close, "eod"

                if exit_px is not None:
                    if pos["direction"] == "LONG":
                        ret = (exit_px - pos["entry"]) / pos["entry"]
                    else:
                        ret = (pos["entry"] - exit_px) / pos["entry"]
                    pnl = ret * POSITION_INR - _cost(POSITION_INR)
                    trades.append({
                        "scanner":   key,
                        "sym":       sym,
                        "date":      day,
                        "direction": pos["direction"],
                        "entry":     pos["entry"],
                        "exit":      round(exit_px, 2),
                        "exit_why":  exit_why,
                        "ret_pct":   round(ret * 100, 3),
                        "pnl":       round(pnl, 2),
                        "win":       exit_why == "target",
                    })
                    del open_pos[key]

            if is_eod:
                break

            # ── Entries ─────────────────────────────────────────────────────
            df5_so_far = df5_day.iloc[: bar_idx + 1]
            df15_so_far = df15_day[df15_day.index <= ts] if not df15_day.empty else pd.DataFrame()

            for key, fn, needs_5m, needs_15m in scanners:
                if key in open_pos or key in fired_today:
                    continue
                if needs_5m and len(df5_so_far) < 4:
                    continue
                if needs_15m and (df15_so_far is None or len(df15_so_far) < 4):
                    continue
                try:
                    hit = fn(
                        df5=df5_so_far if needs_5m else pd.DataFrame(),
                        df15=df15_so_far if needs_15m else None,
                        prev_day_high=ph,
                        prev_day_low=pl,
                    )
                except Exception:
                    hit = None

                if hit:
                    open_pos[key] = {
                        "direction": hit["direction"],
                        "entry":     hit["entry"],
                        "target":    hit["target"],
                        "sl":        hit["sl"],
                    }
                    fired_today.add(key)

    return trades


# ── Metrics + verdict ─────────────────────────────────────────────────────────

def _metrics(trades: list[dict]) -> dict:
    if not trades:
        return {}
    n     = len(trades)
    wins  = sum(1 for t in trades if t["win"])
    wr    = wins / n
    rets  = [t["ret_pct"] / 100 for t in trades]
    mean_r = sum(rets) / n
    std_r  = math.sqrt(sum((r - mean_r) ** 2 for r in rets) / max(n - 1, 1))
    # Annualise for 5-min bars: ~75 bars/session × 250 sessions = 18,750 bars/yr
    sharpe = (mean_r / std_r) * math.sqrt(18_750) if std_r > 0 else 0.0
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t["exit_why"]] = reasons.get(t["exit_why"], 0) + 1
    return {
        "n":         n,
        "wins":      wins,
        "wr":        wr,
        "sharpe":    round(sharpe, 2),
        "total_pnl": round(sum(t["pnl"] for t in trades), 0),
        "reasons":   reasons,
    }


def _verdict(m: dict) -> str:
    if not m:
        return "OVERRIDE"
    if m["n"] >= TIER1["trades"] and m["wr"] >= TIER1["wr"] and m["sharpe"] >= TIER1["sharpe"]:
        return "TIER_1"
    if m["n"] >= TIER2["trades"] and m["wr"] >= TIER2["wr"] and m["sharpe"] >= TIER2["sharpe"]:
        return "TIER_2"
    return "OVERRIDE"


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate all 8 intraday scanners via Dhan 1-min data"
    )
    parser.add_argument("--days", type=int, default=90,
                        help="Days of 1-min history (Dhan max ~90)")
    parser.add_argument("--tickers", nargs="+", default=None,
                        help="Override symbol list (default: Nifty 50)")
    args = parser.parse_args()

    symbols   = args.tickers or NIFTY50
    scanners  = _load_scanners()
    sep       = "=" * 74

    print()
    print(sep)
    print("INTRADAY SCANNER VALIDATION — 8 patterns × Nifty 50 × 90 days")
    print("Dhan 1-min → 5m / 15m  |  Exit: target / SL / EOD 15:10 IST")
    print(sep)

    raw = _load_dhan_1min(symbols, args.days)
    if len(raw) < 3:
        print("ERROR: too few symbols loaded. Check Dhan credentials.")
        return

    # Resample and split by date (done once per symbol)
    days_5m:  dict[str, dict[date, pd.DataFrame]] = {}
    days_15m: dict[str, dict[date, pd.DataFrame]] = {}
    for sym, df1m in raw.items():
        days_5m[sym]  = _split_by_date(_resample(df1m, "5min"))
        days_15m[sym] = _split_by_date(_resample(df1m, "15min"))

    # Walk-forward simulation across all symbols
    all_trades: list[dict] = []
    for sym in sorted(days_5m.keys()):
        sym_trades = _simulate_symbol(sym, days_5m[sym], days_15m[sym], scanners)
        all_trades.extend(sym_trades)
        if sym_trades:
            logger.debug("%s: %d trades", sym, len(sym_trades))

    logger.info("Total trades across all scanners: %d", len(all_trades))

    # Per-scanner results
    scanner_keys = [s[0] for s in scanners]
    results: dict[str, dict] = {}
    for key in scanner_keys:
        s_trades = [t for t in all_trades if t["scanner"] == key]
        m = _metrics(s_trades)
        results[key] = {"m": m, "v": _verdict(m)}

    # ── Summary table ────────────────────────────────────────────────────────
    print()
    print(f"{'Scanner':<14} {'Trades':>6} {'WinRate':>8} {'Sharpe':>7} {'P&L ₹':>12}  Verdict")
    print("-" * 74)
    validated: list[str] = []
    for key, res in results.items():
        m, v = res["m"], res["v"]
        if not m:
            print(f"{key:<14} {'0':>6} {'—':>8} {'—':>7} {'—':>12}  ✗ OVERRIDE (no trades)")
        else:
            mark = "✓" if v != "OVERRIDE" else "✗"
            wr_str = f"{m['wr']*100:.1f}%"
            reasons = ", ".join(f"{k}:{c}" for k, c in sorted(m["reasons"].items()))
            print(
                f"{key:<14} {m['n']:>6} {wr_str:>8} {m['sharpe']:>7.2f}"
                f" {m['total_pnl']:>12,.0f}  {mark} {v}  [{reasons}]"
            )
            if v != "OVERRIDE":
                validated.append(key)

    print()
    print("Tier criteria (90-day window):")
    print(f"  TIER_1 : ≥{TIER1['trades']} trades, WR≥{TIER1['wr']*100:.0f}%, Sharpe≥{TIER1['sharpe']}")
    print(f"  TIER_2 : ≥{TIER2['trades']} trades, WR≥{TIER2['wr']*100:.0f}%, Sharpe≥{TIER2['sharpe']}")
    print("  OVERRIDE: confluence only — do not emit as standalone signal")
    print()

    if validated:
        print("Validated scanners (TIER_1 or TIER_2):")
        for k in validated:
            print(f"  {k}  ({results[k]['v']})")
        print()
        print("Add to .env after reviewing results:")
        print(f'  INTRADAY_VALIDATED_SCANNERS="{",".join(validated)}"')
        print('  UNVALIDATED_SIGNAL_DISCLAIMER=""')
    else:
        print("No scanner reached TIER_1 or TIER_2 with this data window.")
        print("Keep INTRADAY_SIGNALS_ENABLED=false until more data is available,")
        print("or treat all intraday signals as educational only.")

    print()

    # ── Save markdown report ─────────────────────────────────────────────────
    out = Path("reports") / f"intraday_scanners_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        f"# Intraday Scanner Validation — {date.today()}",
        f"Universe: {len(days_5m)} symbols | Window: {args.days} days",
        "",
        "| Scanner | Trades | WinRate | Sharpe | P&L ₹ | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for key, res in results.items():
        m, v = res["m"], res["v"]
        if not m:
            lines.append(f"| {key} | 0 | — | — | — | **OVERRIDE** |")
        else:
            lines.append(
                f"| {key} | {m['n']} | {m['wr']*100:.1f}% | {m['sharpe']:.2f}"
                f" | {m['total_pnl']:,.0f} | **{v}** |"
            )
    out.write_text("\n".join(lines))
    print(f"Report saved → {out}")
    print(sep)


if __name__ == "__main__":
    main()
