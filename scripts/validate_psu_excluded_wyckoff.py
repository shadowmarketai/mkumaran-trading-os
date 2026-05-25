"""
MKUMARAN Trading OS — PSU-Excluded Wyckoff Backtest

Tests Wyckoff standalone on the non-PSU subset of Nifty 100 (~74 tickers).
Compares to the 2026-04-28 full-universe baseline (PF 0.67, WF Sharpe -0.25).

Hypothesis: PSU stocks have policy-driven price behaviour that Wyckoff cannot
read. Removing them may surface real underlying edge in the remaining universe.

Criteria doc: docs/strategy_validation/psu_excluded_wyckoff_criteria.md
Baseline:     docs/strategy_validation/portfolio_v1_2026_04_28.md (Wyckoff row)

Usage
─────
    python scripts/validate_psu_excluded_wyckoff.py --poc
    python scripts/validate_psu_excluded_wyckoff.py --workers 4
    python scripts/validate_psu_excluded_wyckoff.py --full-universe   # baseline
    python scripts/validate_psu_excluded_wyckoff.py --resume
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp1252 fix

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("psu_wyckoff")


# ── PSU exclusion list (locked — from criteria doc 2026-05-08) ────────

PSU_EXCLUDE = frozenset({
    "SBIN", "POWERGRID", "ONGC", "NTPC", "COALINDIA",
    "ADANIENT", "AMBUJACEM", "BANDHANBNK", "AUROPHARMA", "ALKEM",
    "CONCOR", "SIEMENS", "BOSCHLTD", "LUPIN", "SUNPHARMA", "BHEL",
})

# ── Full Nifty 100 universe ───────────────────────────────────────────

NIFTY_100 = [
    "HDFCBANK", "RELIANCE", "ICICIBANK", "INFY", "TCS",
    "BHARTIARTL", "SBIN", "KOTAKBANK", "BAJFINANCE",
    "LT", "AXISBANK", "WIPRO", "ASIANPAINT", "MARUTI",
    "TITAN", "SUNPHARMA", "ULTRACEMCO", "NTPC", "POWERGRID",
    "ONGC", "TECHM", "HCLTECH", "BAJAJFINSV", "TATAMOTORS",
    "NESTLEIND", "M&M", "JSWSTEEL", "TATASTEEL", "INDUSINDBK",
    "HINDALCO", "CIPLA", "ADANIPORTS", "GRASIM", "BPCL",
    "COALINDIA", "EICHERMOT", "DRREDDY", "DIVISLAB", "SBILIFE",
    "BRITANNIA", "HEROMOTOCO", "APOLLOHOSP", "BAJAJ-AUTO", "TATACONSUM",
    "SHRIRAMFIN", "ADANIENT", "HDFCLIFE", "ICICIGI", "PIDILITIND",
    "HAVELLS", "DMART", "SIEMENS", "BOSCHLTD", "ABB",
    "MUTHOOTFIN", "CHOLAFIN", "GODREJCP", "MARICO", "TORNTPHARM",
    "DABUR", "PGHH", "COLPAL", "BERGEPAINT", "AMBUJACEM",
    "ACC", "MOTHERSON", "TVSMOTOR", "MCDOWELL-N",
    "BANKBARODA", "CANBK", "PNB", "IDFCFIRSTB", "FEDERALBNK",
    "AUBANK", "RBLBANK", "BANDHANBNK", "LUPIN", "BIOCON",
    "AUROPHARMA", "ALKEM", "IPCALAB",
    "PETRONET", "IGL", "MGL", "GUJGASLTD", "CONCOR",
    "IRCTC", "DELHIVERY", "ZOMATO",
    "ADANIGREEN", "ATGL", "CESC", "TORNTPOWER",
]

NON_PSU_UNIVERSE = [t for t in NIFTY_100 if t not in PSU_EXCLUDE]
POC_TICKERS = ["HDFCBANK", "ICICIBANK", "DRREDDY", "TORNTPHARM", "FEDERALBNK"]

# ── Baseline from 2026-04-28 individual engine test ───────────────────

BASELINE_PF = 0.67
BASELINE_SHARPE = -0.25
BASELINE_WR = 23.6

# ── Backtest parameters (locked, match individual engine test) ─────────

DAYS = 1095
CAPITAL = 100_000
DEFAULT_WORKERS = 4


# ── Checkpoint helpers ────────────────────────────────────────────────

def _ckpt(reports_dir: Path, ticker: str, suffix: str) -> Path:
    return reports_dir / "psu_wyckoff_ckpts" / f"{ticker}{suffix}.json"


def _load(path: Path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return None


def _save(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, default=str, indent=2))


# ── Per-ticker runner ─────────────────────────────────────────────────

def run_ticker(ticker: str, days: int, reports_dir: Path, resume: bool, suffix: str) -> dict:
    ckpt = _ckpt(reports_dir, ticker, suffix)
    if resume and (cached := _load(ckpt)) is not None:
        return cached

    try:
        from mcp_server.backtester import (
            run_backtest,
            DEFAULT_SLIPPAGE_PCT,
        )

        result = run_backtest(
            ticker=ticker,
            strategy="wyckoff",
            days=days,
            capital=CAPITAL,
            slippage_pct=DEFAULT_SLIPPAGE_PCT,
        )
        result["ticker"] = ticker
        # run_backtest returns metrics directly — add status so aggregation can filter
        if "error" not in result:
            result["status"] = "ok"
        else:
            result["status"] = "data_unavailable"

    except Exception as exc:
        import traceback as _tb
        result = {
            "ticker": ticker,
            "status": "error",
            "error": str(exc),
            "traceback": _tb.format_exc(),
        }
        logger.warning("Error on %s: %s", ticker, exc)

    _save(ckpt, result)
    return result


# ── Aggregation ───────────────────────────────────────────────────────

def _safe(v, default=None):
    try:
        f = float(v)
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def aggregate(results: list[dict], universe: list[str]) -> dict:
    ok = [r for r in results if r.get("status") == "ok" and r.get("total_trades", 0) > 0]
    pfs = [s for r in ok if (s := _safe(r.get("profit_factor"))) is not None and s < 100]
    wrs = [s for r in ok if (s := _safe(r.get("win_rate"))) is not None]
    sharpes = [s for r in ok if (s := _safe(r.get("sharpe_ratio"))) is not None]
    total_trades = sum(int(r.get("total_trades") or 0) for r in ok)
    profitable = sum(1 for r in ok if _safe(r.get("profit_factor"), 0) >= 1.0)

    return {
        "universe_size": len(universe),
        "psu_excluded": len(NIFTY_100) - len(NON_PSU_UNIVERSE),
        "ok_count": len(ok),
        "total_trades": total_trades,
        "pf_median": round(median(pfs), 3) if pfs else None,
        "wr_median": round(median(wrs), 1) if wrs else None,
        "sharpe_median": round(median(sharpes), 3) if sharpes else None,
        "profitable_tickers": profitable,
        "profitable_pct": round(profitable / len(ok) * 100, 1) if ok else 0,
    }


# ── Report ────────────────────────────────────────────────────────────

def write_report(agg: dict, results: list[dict], path: Path, full_universe: bool) -> None:
    pf = agg["pf_median"]
    pf_lift = round(pf - BASELINE_PF, 3) if pf is not None else None
    wr = agg["wr_median"]
    sh = agg["sharpe_median"]

    # Pre-compute strings with complex quoting to avoid nested f-string issues
    univ_label = (
        "FULL Nifty 100 (baseline comparison)" if full_universe
        else "Non-PSU ({} tickers, {} excluded)".format(agg["universe_size"], agg["psu_excluded"])
    )
    pf_lift_str = "{:+.3f}".format(pf_lift) if pf_lift is not None else "—"
    wr_str = "{:.1f}%".format(wr) if wr is not None else "—"

    lines = [
        "# PSU-Excluded Wyckoff — {}".format(date.today()),
        "",
        "## Configuration",
        "- Universe: {}".format(univ_label),
        "- Engine: Wyckoff standalone (no filters)",
        "- Lookback: {} days | Capital: Rs.{:,}/ticker".format(DAYS, CAPITAL),
        "",
        "## Portfolio Summary vs Baseline",
        "",
        "| Metric | This run | Baseline (full universe) | Lift |",
        "|---|---|---|---|",
        "| Median PF | {} | {} | {} |".format(pf or "—", BASELINE_PF, pf_lift_str),
        "| Median WR | {} | {}% | — |".format(wr_str, BASELINE_WR),
        "| Median Sharpe | {} | {} | — |".format(sh or "—", BASELINE_SHARPE),
        f"| Total trades | {agg['total_trades']:,} | 744 (pipeline) | — |",
        f"| Profitable tickers | {agg['profitable_tickers']}/{agg['ok_count']} ({agg['profitable_pct']}%) | — | — |",
        "",
        "## Tier Assessment",
        "",
    ]

    if pf is None:
        lines.append("Insufficient data.")
    elif pf >= 1.2 and agg["profitable_pct"] >= 40 and agg["total_trades"] >= 200:
        lines.append("**TIER 1** — PSU exclusion rescues Wyckoff. Pipeline with PSU filter is next step.")
        lines.append("Run: `python scripts/validate_production_pipeline.py --psu-exclude --workers 4`")
    elif pf >= 0.8:
        lines.append("**TIER 2** — PSU exclusion helps but insufficient for standalone viability.")
        lines.append("Per criteria doc: test ONE structural change (MWA filter OR 2-engine confluence) with new criteria doc.")
    else:
        lines.append("**TIER 3** — PSU exclusion does not rescue Wyckoff standalone.")
        lines.append("Wyckoff failure is in the engine signals themselves on Indian daily data, not universe contamination.")

    if pf_lift is not None and pf_lift > 0:
        lines.append(f"\nLift over full-universe baseline: +{pf_lift:.3f} PF.")
    elif pf_lift is not None:
        lines.append(f"\nDrag vs baseline: {pf_lift:.3f} PF (PSU exclusion made no difference or hurt).")

    lines.extend([
        "",
        "## Per-Ticker Results",
        "",
        "| Ticker | Trades | PF | WR | Sharpe | PSU? |",
        "|---|---|---|---|---|---|",
    ])
    for r in sorted(results, key=lambda x: -(x.get("total_trades") or 0)):
        is_psu = "✓" if r["ticker"] in PSU_EXCLUDE else ""
        if r.get("status") in ("data_unavailable", "error"):
            lines.append(f"| {r['ticker']} | — | — | — | — | {is_psu} |")
        else:
            pf_t = _safe(r.get("profit_factor"))
            wr_t = _safe(r.get("win_rate"))
            sh_t = _safe(r.get("sharpe_ratio"))
            lines.append(
                f"| {r['ticker']} | {r.get('total_trades', 0)} |"
                f" {f'{pf_t:.2f}' if pf_t is not None else '—'} |"
                f" {f'{wr_t:.0f}%' if wr_t is not None else '—'} |"
                f" {f'{sh_t:.2f}' if sh_t is not None else '—'} |"
                f" {is_psu} |"
            )

    path.write_text("\n".join(lines))
    logger.info("Report: %s", path)


# ── Main ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poc", action="store_true")
    parser.add_argument("--full-universe", action="store_true", help="Run on full Nifty 100 (baseline)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--days", type=int, default=DAYS)
    args = parser.parse_args()

    universe = NIFTY_100 if args.full_universe else NON_PSU_UNIVERSE
    if args.poc:
        universe = POC_TICKERS

    suffix = "_full" if args.full_universe else "_psu_excluded"
    reports_dir = Path("reports") / "psu_wyckoff"
    reports_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "PSU-excluded Wyckoff: %d tickers (%s), workers=%d",
        len(universe),
        "FULL UNIVERSE" if args.full_universe else "PSU-EXCLUDED",
        args.workers,
    )

    results: list[dict] = []
    t0 = time.monotonic()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(run_ticker, ticker, args.days, reports_dir, args.resume, suffix): ticker
            for ticker in universe
        }
        done = 0
        for fut in as_completed(futures):
            ticker = futures[fut]
            try:
                result = fut.result()
                results.append(result)
            except Exception as exc:
                results.append({"ticker": ticker, "status": "error", "error": str(exc)})
            done += 1
            elapsed = time.monotonic() - t0
            eta = (elapsed / done) * (len(universe) - done)
            logger.info("[%d/%d] %s done — ETA %.0fs", done, len(universe), ticker, eta)

    agg = aggregate(results, universe)
    suffix_date = f"_{date.today()}{suffix}"
    report_path = reports_dir / f"psu_wyckoff{suffix_date}.md"
    write_report(agg, results, report_path, args.full_universe)

    print(f"\n{'='*60}")
    print("PSU-EXCLUDED WYCKOFF — RESULTS")
    print(f"{'='*60}")
    print(f"Universe:    {len(universe)} tickers ({'full' if args.full_universe else 'PSU-excluded'})")
    print(f"Total trades:{agg['total_trades']:>6}")
    print(f"Median PF:   {agg['pf_median'] or 'insufficient data'}")
    print(f"Baseline PF: {BASELINE_PF}")
    if agg["pf_median"] is not None:
        print(f"Lift:        {agg['pf_median'] - BASELINE_PF:+.3f}")
    print(f"Profitable:  {agg['profitable_tickers']}/{agg['ok_count']} ({agg['profitable_pct']}%)")
    print(f"Report:      {report_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
