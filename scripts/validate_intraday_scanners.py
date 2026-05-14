"""
Intraday Scanner Validation — Session 2 — regime + confluence + cross-day 15m
Dhan 1-min data resampled to 5m / 15m. Max window: 90 trading days.

Session 2 fixes on top of Session 1:
  1. Regime filter   — LONG signals only on days when Nifty close > 9 EMA.
                       Bearish days: skip entirely (no signals taken).
  2. Confluence gate — require N scanners to agree on same ticker + direction
                       before opening a position. Tested at 1, 2, 3.
  3. Cross-day 15m   — supertrend and rsi_rev now receive full 15m history
                       (not just today's bars), enabling intraday direction flips.
  4. prev_day_hl     — permanently removed (1.4% WR in Session 1; no proximity
                       filter can recover a scanner with zero follow-through).

Each (RRR, confluence) combination is simulated independently.
Data loads once from Dhan; subsequent sweeps run in-memory.

Usage:
    python scripts/validate_intraday_scanners.py
    python scripts/validate_intraday_scanners.py --rrr 1.0 1.2 --confluence 2 3
    python scripts/validate_intraday_scanners.py --days 60 --tickers RELIANCE HDFCBANK
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

# ── Cost model ────────────────────────────────────────────────────────────────

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


def _load_nifty_regime(days: int) -> dict[date, bool]:
    """
    Load Nifty 50 daily closes via yfinance and compute 9 EMA.
    Returns {date: True} when Nifty close > 9 EMA (bullish → allow LONGs).
    Falls back to all-True (no filter) if yfinance is unavailable.
    """
    try:
        import yfinance as yf
        period = f"{min(days + 40, 200)}d"
        nifty = yf.download("^NSEI", period=period, interval="1d",
                            progress=False, auto_adjust=True)
        if nifty.empty:
            raise ValueError("empty")
        closes = nifty["Close"].squeeze()
        ema9 = closes.ewm(span=9, adjust=False).mean()
        regime: dict[date, bool] = {}
        for ts in closes.index:
            d = ts.date() if hasattr(ts, "date") else ts
            regime[d] = float(closes[ts]) > float(ema9[ts])
        logger.info("Nifty regime loaded: %d days (%d bullish / %d bearish)",
                    len(regime),
                    sum(v for v in regime.values()),
                    sum(not v for v in regime.values()))
        return regime
    except Exception as exc:
        logger.warning("Nifty regime unavailable (%s) — running without filter", exc)
        return {}


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


def _prev_day(days: dict[date, pd.DataFrame], today: date) -> date | None:
    sorted_days = sorted(days.keys())
    if today not in sorted_days:
        return None
    idx = sorted_days.index(today)
    return sorted_days[idx - 1] if idx > 0 else None


# ── Scanners ──────────────────────────────────────────────────────────────────

def _load_scanners() -> list[tuple[str, object, bool, bool]]:
    """
    7 scanners (prev_day_hl permanently removed — 1.4% WR in Session 1).
    Cross-day 15m fix unlocks supertrend and rsi_rev.
    """
    from mcp_server.intraday_scanner import (
        scan_ema_crossover_mtf,
        scan_momentum,
        scan_orb,
        scan_rsi_reversal_15m,
        scan_supertrend_15m,
        scan_vwap,
        scan_vwap_ema_confluence,
    )
    return [
        ("orb",        scan_orb,                True,  False),
        ("vwap",       scan_vwap,               True,  False),
        ("momentum",   scan_momentum,            True,  False),
        ("vwap_ema",   scan_vwap_ema_confluence, True,  False),
        ("ema_cross",  scan_ema_crossover_mtf,   True,  True),
        ("supertrend", scan_supertrend_15m,      False, True),
        ("rsi_rev",    scan_rsi_reversal_15m,    False, True),
    ]


def _call(fn: object, df5: pd.DataFrame, df15: pd.DataFrame | None,
          ph: float | None, pl: float | None,
          needs_5m: bool, needs_15m: bool) -> dict | None:
    if needs_5m and (df5 is None or len(df5) < 4):
        return None
    if needs_15m and (df15 is None or len(df15) < 4):
        return None
    try:
        return fn(  # type: ignore[operator]
            df5=df5 if needs_5m else pd.DataFrame(),
            df15=df15 if needs_15m else None,
            prev_day_high=ph,
            prev_day_low=pl,
        )
    except Exception:
        return None


# ── Simulation ────────────────────────────────────────────────────────────────

def _simulate_symbol(
    sym: str,
    days_5m: dict[date, pd.DataFrame],
    df15_full: pd.DataFrame,          # full cross-day 15m history (Session 2 fix)
    scanners: list[tuple[str, object, bool, bool]],
    rrr_mult: float,
    confluence: int,
    regime_map: dict[date, bool],     # date → True = bullish
) -> list[dict]:
    """
    Walk-forward replay with three Session 2 additions:
      - Cross-day 15m: df15_full sliced at each bar's timestamp
      - Regime filter: LONG signals skipped on bearish Nifty days
      - Confluence gate: position opened only when ≥ confluence scanners agree
    """
    trades: list[dict] = []

    for day in sorted(days_5m.keys()):
        df5_day = days_5m[day]
        ph, pl  = _prev_hl(days_5m, day)

        # Regime: use previous trading day's Nifty signal (no lookahead)
        prev_d      = _prev_day(days_5m, day)
        is_bullish  = regime_map.get(prev_d, True) if (prev_d and regime_map) else True

        # Skip bearish days entirely (LONG-only strategy)
        if regime_map and not is_bullish:
            continue

        # Per-scanner positions (confluence=1) or single combined position (>=2)
        open_pos:    dict[str, dict] = {}
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
                pos      = open_pos[key]
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
            df5_so_far = df5_day.iloc[: bar_idx + 1]
            # Cross-day 15m: slice full history up to current timestamp
            df15_so_far = (df15_full[df15_full.index <= ts]
                           if not df15_full.empty else pd.DataFrame())

            if confluence == 1:
                # Per-scanner mode: independent positions
                for key, fn, needs_5m, needs_15m in scanners:
                    if key in open_pos or key in fired_today:
                        continue
                    hit = _call(fn, df5_so_far, df15_so_far, ph, pl, needs_5m, needs_15m)
                    if not hit:
                        continue
                    risk = abs(hit["entry"] - hit["sl"])
                    if risk <= 0:
                        continue
                    tgt = (hit["entry"] + risk * rrr_mult if hit["direction"] == "LONG"
                           else hit["entry"] - risk * rrr_mult)
                    open_pos[key] = {
                        "direction": hit["direction"],
                        "entry": hit["entry"],
                        "target": tgt,
                        "sl": hit["sl"],
                    }
                    fired_today.add(key)

            else:
                # Confluence mode: open when ≥ N scanners agree
                if "signal" in open_pos or "signal" in fired_today:
                    continue

                long_hits: list[dict] = []
                for key, fn, needs_5m, needs_15m in scanners:
                    hit = _call(fn, df5_so_far, df15_so_far, ph, pl, needs_5m, needs_15m)
                    if hit and hit["direction"] == "LONG":
                        long_hits.append(hit)

                if len(long_hits) >= confluence:
                    chosen = long_hits[0]
                    risk   = abs(chosen["entry"] - chosen["sl"])
                    if risk > 0:
                        tgt = chosen["entry"] + risk * rrr_mult
                        open_pos["signal"] = {
                            "direction": "LONG",
                            "entry":  chosen["entry"],
                            "target": tgt,
                            "sl":     chosen["sl"],
                        }
                        fired_today.add("signal")

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
    # Annualise using trade count: ~trades/90d × 250d = trades/yr
    trades_per_yr = max(n / 90 * 250, 1)
    sharpe = (mean_r / std_r) * math.sqrt(trades_per_yr) if std_r > 0 else 0.0
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
        description="Intraday scanner validation — Session 2 (regime + confluence + cross-day 15m)"
    )
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--rrr", nargs="+", type=float, default=[1.0, 1.2, 1.5])
    parser.add_argument("--confluence", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--tickers", nargs="+", default=None)
    args = parser.parse_args()

    symbols    = args.tickers or NIFTY50
    rrr_list   = sorted(set(args.rrr))
    conf_list  = sorted(set(args.confluence))
    scanners   = _load_scanners()
    sep        = "=" * 80

    print()
    print(sep)
    print("INTRADAY SCANNER VALIDATION — Session 2")
    print(f"Tickers: {len(symbols)} | Days: {args.days} | "
          f"RRR: {rrr_list} | Confluence: {conf_list}")
    print("Fixes: regime filter (Nifty 9 EMA) + confluence gate + cross-day 15m")
    print(sep)

    # ── Load data (once) ─────────────────────────────────────────────────────
    raw        = _load_dhan_1min(symbols, args.days)
    regime_map = _load_nifty_regime(args.days)

    if len(raw) < 3:
        print("ERROR: too few symbols loaded. Check Dhan credentials.")
        return

    # 5m per-day split (for prev-day H/L helper)
    days_5m: dict[str, dict[date, pd.DataFrame]] = {}
    # Full cross-day 15m DataFrames (Session 2 fix for supertrend / rsi_rev)
    full_15m: dict[str, pd.DataFrame] = {}

    for sym, df1m in raw.items():
        df5  = _resample(df1m, "5min")
        df15 = _resample(df1m, "15min")
        days_5m[sym] = _split_by_date(df5)
        # Keep full 15m history within NSE hours (cross-day accumulation)
        full_15m[sym] = df15.between_time("09:15", "15:30")

    # ── Sweep (RRR × confluence) ──────────────────────────────────────────────
    # {(rrr, conf): {metric_key: value}}
    combo_results: dict[tuple, dict] = {}

    for rrr in rrr_list:
        for conf in conf_list:
            logger.info("Simulating RRR=%.1f | confluence=%d ...", rrr, conf)
            all_trades: list[dict] = []
            for sym in sorted(days_5m.keys()):
                sym_trades = _simulate_symbol(
                    sym, days_5m[sym],
                    full_15m.get(sym, pd.DataFrame()),
                    scanners, rrr, conf, regime_map,
                )
                all_trades.extend(sym_trades)

            m = _metrics(all_trades)
            v = _verdict(m)
            combo_results[(rrr, conf)] = {"m": m, "v": v, "trades": all_trades}
            logger.info("  → %d trades | WR=%.1f%% | Sharpe=%.2f | %s",
                        m.get("n", 0), m.get("wr", 0) * 100,
                        m.get("sharpe", 0), v)

    # ── Summary grid ─────────────────────────────────────────────────────────
    print()
    print(f"{'':16}", end="")
    for conf in conf_list:
        print(f"  confluence={conf}{'':4}", end="")
    print()
    print(f"{'':16}", end="")
    for _ in conf_list:
        print(f"  {'Trades':>6} {'WR':>6} {'Shp':>5}", end="")
    print()
    print("-" * (16 + len(conf_list) * 22))

    best_combo: tuple | None = None
    best_sharpe = -999.0

    for rrr in rrr_list:
        print(f"RRR = {rrr:.1f}×{'':8}", end="")
        for conf in conf_list:
            r = combo_results[(rrr, conf)]
            m, v = r["m"], r["v"]
            if m:
                mark = "✓" if v != "OVERRIDE" else " "
                print(f"  {m['n']:>6} {m['wr']*100:>5.1f}%{mark} {m['sharpe']:>5.2f}", end="")
                if m["sharpe"] > best_sharpe:
                    best_sharpe = m["sharpe"]
                    best_combo  = (rrr, conf)
            else:
                print(f"  {'0':>6} {'—':>6} {'—':>5}", end="")
        print()

    # ── Per-scanner breakdown (confluence=1 only) ─────────────────────────────
    print()
    print(sep)
    print("PER-SCANNER BREAKDOWN  (confluence=1, best RRR)")
    print(sep)
    best_rrr_solo = min(rrr_list)  # lowest RRR = most trades, useful for breakdown
    solo_trades   = combo_results[(best_rrr_solo, 1)]["trades"]
    scanner_keys  = [s[0] for s in scanners]
    print(f"{'Scanner':<12} {'Trades':>6} {'WinRate':>8} {'Sharpe':>7} {'P&L ₹':>12}  Verdict")
    print("-" * 60)
    for key in scanner_keys:
        s_trades = [t for t in solo_trades if t["scanner"] == key]
        m = _metrics(s_trades)
        v = _verdict(m)
        if not m:
            print(f"{key:<12} {'0':>6} {'—':>8} {'—':>7} {'—':>12}  OVERRIDE")
        else:
            mark = "✓" if v != "OVERRIDE" else "✗"
            reasons = ", ".join(f"{k}:{c}" for k, c in sorted(m["reasons"].items()))
            print(f"{key:<12} {m['n']:>6} {m['wr']*100:>7.1f}% {m['sharpe']:>7.2f}"
                  f" {m['total_pnl']:>12,.0f}  {mark} {v}  [{reasons}]")

    # ── Recommendation ────────────────────────────────────────────────────────
    print()
    print(sep)
    print("RECOMMENDATION")
    print(sep)
    print(f"Tier criteria: TIER_1 ≥{TIER1['trades']}t WR≥{TIER1['wr']*100:.0f}% Shp≥{TIER1['sharpe']}"
          f"  |  TIER_2 ≥{TIER2['trades']}t WR≥{TIER2['wr']*100:.0f}% Shp≥{TIER2['sharpe']}")
    print()

    passing = [(k, v) for k, v in combo_results.items() if v["v"] != "OVERRIDE"]
    if passing:
        print("Combinations that passed tier criteria:")
        for (rrr, conf), res in sorted(passing, key=lambda x: -x[1]["m"].get("sharpe", 0)):
            m = res["m"]
            print(f"  RRR={rrr:.1f} conf={conf} → {res['v']}"
                  f"  ({m['n']} trades, WR {m['wr']*100:.1f}%, Sharpe {m['sharpe']:.2f})")
        best_k, best_res = sorted(passing, key=lambda x: -x[1]["m"].get("sharpe", 0))[0]
        rrr_rec, conf_rec = best_k
        validated = [s for s in scanner_keys]  # all scanners contribute in confluence mode
        print()
        print("Add to .env:")
        print(f"  INTRADAY_RRR_FLOOR={rrr_rec}")
        if conf_rec == 1:
            print(f'  INTRADAY_VALIDATED_SCANNERS="{",".join(validated)}"')
        else:
            print(f'  INTRADAY_CONFLUENCE={conf_rec}')
            print(f'  INTRADAY_VALIDATED_SCANNERS="{",".join(validated)}"')
    else:
        print("No combination reached TIER_2.")
        if best_combo:
            rrr_b, conf_b = best_combo
            m_b = combo_results[best_combo]["m"]
            print(f"Closest: RRR={rrr_b:.1f} conf={conf_b} → "
                  f"WR {m_b.get('wr',0)*100:.1f}% Sharpe {m_b.get('sharpe',0):.2f}")
        print()
        print("Proceed to Session 3: relax vwap_ema / ema_cross fresh-cross condition")
        print("and add time filter (no entries after 14:00 IST).")

    # ── Save report ──────────────────────────────────────────────────────────
    out = Path("reports") / f"intraday_scanners_s2_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        f"# Intraday Scanner Validation — Session 2 — {date.today()}",
        f"Universe: {len(days_5m)} symbols | Window: {args.days} days",
        f"Regime filter: Nifty 9 EMA | RRR: {rrr_list} | Confluence: {conf_list}",
        "",
        "## Parameter Grid (Trades | WinRate | Sharpe | Verdict)",
        "",
        "| RRR | Confluence | Trades | WinRate | Sharpe | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for rrr in rrr_list:
        for conf in conf_list:
            r = combo_results[(rrr, conf)]
            m, v = r["m"], r["v"]
            if not m:
                lines.append(f"| {rrr} | {conf} | 0 | — | — | **OVERRIDE** |")
            else:
                lines.append(f"| {rrr} | {conf} | {m['n']} | {m['wr']*100:.1f}% "
                              f"| {m['sharpe']:.2f} | **{v}** |")
    out.write_text("\n".join(lines))
    print()
    print(f"Report saved → {out}")
    print(sep)


if __name__ == "__main__":
    main()
