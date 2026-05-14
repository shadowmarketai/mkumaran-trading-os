"""
Intraday Scanner Validation — all 8 patterns, multi-RRR sweep
Dhan 1-min data resampled to 5m / 15m bars. Max window: 90 trading days.

Data is loaded once. The simulation reruns for each RRR (default: 1.0, 1.2,
1.5) so you can find the exit multiplier that gives each scanner a real edge
without refetching from Dhan.

Each scanner is evaluated independently. One position per scanner per ticker
per day. Exit rules: target (entry ± risk × RRR), SL touch, or EOD 15:10 IST.

Tier criteria (90-day window, ~50 tickers):
  TIER_1 : ≥ 20 trades, WR ≥ 55%, Sharpe ≥ 0.8
  TIER_2 : ≥ 10 trades, WR ≥ 45%, Sharpe ≥ 0.5
  OVERRIDE: below TIER_2 — confluence input only

Session 1 fixes included in this run:
  - Multi-RRR sweep (find the right exit distance)
  - prev_day_hl proximity filter (≤ 0.3% past the level)

Usage:
    python scripts/validate_intraday_scanners.py
    python scripts/validate_intraday_scanners.py --rrr 1.0 1.2 1.5 2.0
    python scripts/validate_intraday_scanners.py --days 60 --tickers RELIANCE HDFCBANK ONGC
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
STT_SELL     = 0.00025
EXCHANGE     = 0.0000345
GST          = 0.18
STAMP        = 0.00003
SLIPPAGE     = 0.001

SESSION_END = dtime(15, 10)

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
    from mcp_server.data_provider import DhanSource
    dhan = DhanSource()
    if not dhan.login():
        logger.error("Dhan login failed — set DHAN_CLIENT_ID + DHAN_ACCESS_TOKEN")
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
    days: dict[date, pd.DataFrame] = {}
    for d, grp in df.groupby(df.index.date):
        session = grp.between_time("09:15", "15:30")
        if len(session) >= 4:
            days[d] = session
    return days


def _prev_hl(days: dict[date, pd.DataFrame], today: date) -> tuple[float | None, float | None]:
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
    rrr_mult: float,
) -> list[dict]:
    """
    Walk-forward day-by-day replay for one symbol at the given RRR.
    Target is overridden by rrr_mult — scanner entry/SL are unchanged.
    One position per scanner per day; no re-entry after first signal.
    """
    trades: list[dict] = []

    for day in sorted(days_5m.keys()):
        df5_day  = days_5m[day]
        df15_day = days_15m.get(day, pd.DataFrame())
        ph, pl   = _prev_hl(days_5m, day)

        open_pos:   dict[str, dict] = {}
        fired_today: set[str] = set()

        bars = list(df5_day.iterrows())
        n    = len(bars)

        for bar_idx, (ts, row) in enumerate(bars):
            is_eod = row.name.time() >= SESSION_END or bar_idx == n - 1  # type: ignore[union-attr]
            high   = float(row["high"])
            low    = float(row["low"])
            close  = float(row["close"])

            # ── Exits ────────────────────────────────────────────────────────
            for key in list(open_pos.keys()):
                pos     = open_pos[key]
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
                    ret = ((exit_px - pos["entry"]) / pos["entry"]
                           if pos["direction"] == "LONG"
                           else (pos["entry"] - exit_px) / pos["entry"])
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

            # ── Entries ──────────────────────────────────────────────────────
            df5_so_far  = df5_day.iloc[: bar_idx + 1]
            df15_so_far = (df15_day[df15_day.index <= ts]
                           if not df15_day.empty else pd.DataFrame())

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
                    risk   = abs(hit["entry"] - hit["sl"])
                    if risk <= 0:
                        continue
                    # Override target with the test RRR (entry/SL unchanged)
                    if hit["direction"] == "LONG":
                        target = hit["entry"] + risk * rrr_mult
                    else:
                        target = hit["entry"] - risk * rrr_mult
                    open_pos[key] = {
                        "direction": hit["direction"],
                        "entry":     hit["entry"],
                        "target":    target,
                        "sl":        hit["sl"],
                    }
                    fired_today.add(key)

    return trades


# ── Metrics + verdict ─────────────────────────────────────────────────────────

def _metrics(trades: list[dict]) -> dict:
    if not trades:
        return {}
    n      = len(trades)
    wins   = sum(1 for t in trades if t["win"])
    wr     = wins / n
    rets   = [t["ret_pct"] / 100 for t in trades]
    mean_r = sum(rets) / n
    std_r  = math.sqrt(sum((r - mean_r) ** 2 for r in rets) / max(n - 1, 1))
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
        description="Validate all 8 intraday scanners — multi-RRR sweep"
    )
    parser.add_argument("--days", type=int, default=90,
                        help="Days of 1-min history (Dhan max ~90)")
    parser.add_argument("--rrr", nargs="+", type=float, default=[1.0, 1.2, 1.5],
                        help="RRR values to test (default: 1.0 1.2 1.5)")
    parser.add_argument("--tickers", nargs="+", default=None,
                        help="Override symbol list (default: Nifty 50)")
    args = parser.parse_args()

    symbols  = args.tickers or NIFTY50
    rrr_list = sorted(set(args.rrr))
    scanners = _load_scanners()
    sep      = "=" * 80

    print()
    print(sep)
    print(f"INTRADAY SCANNER VALIDATION — 8 patterns × {len(symbols)} tickers × {args.days} days")
    print(f"RRR sweep: {rrr_list}  |  Exit: target / SL / EOD 15:10 IST")
    print("Session 1 fixes: prev_day_hl proximity filter + multi-RRR exit sweep")
    print(sep)

    # ── Load data once ───────────────────────────────────────────────────────
    raw = _load_dhan_1min(symbols, args.days)
    if len(raw) < 3:
        print("ERROR: too few symbols loaded. Check Dhan credentials.")
        return

    days_5m:  dict[str, dict[date, pd.DataFrame]] = {}
    days_15m: dict[str, dict[date, pd.DataFrame]] = {}
    for sym, df1m in raw.items():
        days_5m[sym]  = _split_by_date(_resample(df1m, "5min"))
        days_15m[sym] = _split_by_date(_resample(df1m, "15min"))

    # ── Simulate for each RRR ────────────────────────────────────────────────
    # {rrr: {scanner_key: {m, v}}}
    all_results: dict[float, dict[str, dict]] = {}
    scanner_keys = [s[0] for s in scanners]

    for rrr in rrr_list:
        logger.info("Simulating RRR=%.1f ...", rrr)
        all_trades: list[dict] = []
        for sym in sorted(days_5m.keys()):
            sym_trades = _simulate_symbol(sym, days_5m[sym], days_15m[sym], scanners, rrr)
            all_trades.extend(sym_trades)

        rrr_results: dict[str, dict] = {}
        for key in scanner_keys:
            s_trades = [t for t in all_trades if t["scanner"] == key]
            m = _metrics(s_trades)
            rrr_results[key] = {"m": m, "v": _verdict(m)}
        all_results[rrr] = rrr_results
        logger.info("RRR=%.1f — total trades: %d", rrr, len(all_trades))

    # ── Per-RRR summary tables ───────────────────────────────────────────────
    for rrr in rrr_list:
        res = all_results[rrr]
        print()
        print(f"RRR = {rrr:.1f}×")
        print(f"{'Scanner':<14} {'Trades':>6} {'WinRate':>8} {'Sharpe':>7} {'P&L ₹':>12}  Verdict")
        print("-" * 60)
        for key in scanner_keys:
            r = res[key]
            m, v = r["m"], r["v"]
            if not m:
                print(f"{key:<14} {'0':>6} {'—':>8} {'—':>7} {'—':>12}  OVERRIDE")
            else:
                mark = "✓" if v != "OVERRIDE" else "✗"
                reasons = ", ".join(f"{k}:{c}" for k, c in sorted(m["reasons"].items()))
                print(
                    f"{key:<14} {m['n']:>6} {m['wr']*100:>7.1f}% {m['sharpe']:>7.2f}"
                    f" {m['total_pnl']:>12,.0f}  {mark} {v}  [{reasons}]"
                )

    # ── Best RRR per scanner ─────────────────────────────────────────────────
    print()
    print(sep)
    print("BEST RRR PER SCANNER (highest Sharpe among tested values)")
    print(sep)
    print(f"{'Scanner':<14} {'Best RRR':>8} {'WinRate':>8} {'Sharpe':>7}  Verdict")
    print("-" * 50)

    validated_by_rrr: dict[float, list[str]] = {r: [] for r in rrr_list}

    for key in scanner_keys:
        best_rrr = None
        best_sharpe = -999.0
        best_m: dict = {}
        best_v = "OVERRIDE"
        for rrr in rrr_list:
            r = all_results[rrr][key]
            m = r["m"]
            if m and m["sharpe"] > best_sharpe:
                best_sharpe = m["sharpe"]
                best_rrr = rrr
                best_m = m
                best_v = r["v"]
        if best_rrr is not None and best_m:
            mark = "✓" if best_v != "OVERRIDE" else "✗"
            print(
                f"{key:<14} {best_rrr:>8.1f} {best_m['wr']*100:>7.1f}%"
                f" {best_m['sharpe']:>7.2f}  {mark} {best_v}"
            )
            if best_v != "OVERRIDE":
                validated_by_rrr[best_rrr].append(key)
        else:
            print(f"{key:<14} {'—':>8} {'—':>8} {'—':>7}  ✗ OVERRIDE (no trades)")

    print()
    print("Tier criteria:")
    print(f"  TIER_1 : ≥{TIER1['trades']} trades, WR≥{TIER1['wr']*100:.0f}%, Sharpe≥{TIER1['sharpe']}")
    print(f"  TIER_2 : ≥{TIER2['trades']} trades, WR≥{TIER2['wr']*100:.0f}%, Sharpe≥{TIER2['sharpe']}")
    print()

    all_validated = [k for rrr in rrr_list for k in validated_by_rrr[rrr]]
    if all_validated:
        print("Recommended next steps:")
        for rrr in rrr_list:
            keys = validated_by_rrr[rrr]
            if keys:
                print(f"  Set INTRADAY_RRR_FLOOR={rrr} in .env")
                print(f'  Set INTRADAY_VALIDATED_SCANNERS="{",".join(keys)}"')
    else:
        print("No scanner reached TIER_2 at any tested RRR.")
        print("Proceed to Session 2 fixes (cross-day 15m data for supertrend/rsi_rev).")

    # ── Save report ──────────────────────────────────────────────────────────
    out = Path("reports") / f"intraday_scanners_s1_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        f"# Intraday Scanner Validation — Session 1 — {date.today()}",
        f"Universe: {len(days_5m)} symbols | Window: {args.days} days",
        f"RRR sweep: {rrr_list}",
        "Fixes: prev_day_hl proximity filter (≤0.3%)",
        "",
    ]
    for rrr in rrr_list:
        lines += [f"## RRR = {rrr:.1f}", "",
                  "| Scanner | Trades | WinRate | Sharpe | P&L ₹ | Verdict |",
                  "|---|---|---|---|---|---|"]
        for key in scanner_keys:
            r = all_results[rrr][key]
            m, v = r["m"], r["v"]
            if not m:
                lines.append(f"| {key} | 0 | — | — | — | **OVERRIDE** |")
            else:
                lines.append(
                    f"| {key} | {m['n']} | {m['wr']*100:.1f}% | {m['sharpe']:.2f}"
                    f" | {m['total_pnl']:,.0f} | **{v}** |"
                )
        lines.append("")

    out.write_text("\n".join(lines))
    print(f"Report saved → {out}")
    print(sep)


if __name__ == "__main__":
    main()
