"""
MKUMARAN Trading OS — PSU-Excluded All-Engines Backtest

Runs all signal engines on the PSU-excluded Nifty 100 subset (~75 tickers)
and compares each to its baseline from the 2026-04-28 individual engine test.

Engines: SMC, Wyckoff, VSA, Harmonic, Confluence-2, Confluence-3

Criteria doc: docs/strategy_validation/psu_excluded_all_engines_criteria.md
Baselines:    docs/strategy_validation/portfolio_v1_2026_04_28.md

Usage
─────
    python scripts/validate_psu_excluded_all_engines.py --poc
    python scripts/validate_psu_excluded_all_engines.py --workers 4
    python scripts/validate_psu_excluded_all_engines.py --engines wyckoff,vsa
    python scripts/validate_psu_excluded_all_engines.py --workers 4 --resume
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("psu_all_engines")


# ── PSU exclusion list (locked — from criteria doc 2026-05-08) ────────

PSU_EXCLUDE = frozenset({
    "SBIN", "POWERGRID", "ONGC", "NTPC", "COALINDIA",
    "ADANIENT", "AMBUJACEM", "BANDHANBNK", "AUROPHARMA", "ALKEM",
    "CONCOR", "SIEMENS", "BOSCHLTD", "LUPIN", "SUNPHARMA", "BHEL",
})

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

NON_PSU = [t for t in NIFTY_100 if t not in PSU_EXCLUDE]
POC_TICKERS = ["HDFCBANK", "ICICIBANK", "DRREDDY", "TORNTPOWER", "FEDERALBNK"]

# ── Engine config ─────────────────────────────────────────────────────

ALL_ENGINES = [
    {"name": "wyckoff",      "strategy": "wyckoff",     "min_engines": 2, "baseline_pf": 0.67, "baseline_wr": 23.6},
    {"name": "vsa",          "strategy": "vsa",          "min_engines": 2, "baseline_pf": 0.54, "baseline_wr": 19.1},
    {"name": "smc",          "strategy": "smc",          "min_engines": 2, "baseline_pf": 0.42, "baseline_wr": 15.6},
    {"name": "harmonic",     "strategy": "harmonic",     "min_engines": 2, "baseline_pf": 0.00, "baseline_wr":  0.0},
    {"name": "confluence_2", "strategy": "confluence",   "min_engines": 2, "baseline_pf": 0.49, "baseline_wr": 18.2},
    {"name": "confluence_3", "strategy": "confluence",   "min_engines": 3, "baseline_pf": 0.49, "baseline_wr": 18.2},
]

DAYS = 1095
CAPITAL = 100_000
DEFAULT_WORKERS = 4

# ── Checkpoint helpers ────────────────────────────────────────────────

def _ckpt(reports_dir: Path, engine_name: str, ticker: str) -> Path:
    return reports_dir / "ckpts" / engine_name / f"{ticker}.json"


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

def run_ticker(
    ticker: str,
    engine: dict,
    days: int,
    reports_dir: Path,
    resume: bool,
) -> dict:
    ckpt = _ckpt(reports_dir, engine["name"], ticker)
    if resume and (cached := _load(ckpt)) is not None:
        return cached

    try:
        from mcp_server.backtester import run_backtest, DEFAULT_SLIPPAGE_PCT

        result = run_backtest(
            ticker=ticker,
            strategy=engine["strategy"],
            days=days,
            capital=CAPITAL,
            slippage_pct=DEFAULT_SLIPPAGE_PCT,
            min_engines=engine["min_engines"],
        )
        result["ticker"] = ticker
        result["engine"] = engine["name"]
        result["status"] = "data_unavailable" if "error" in result else "ok"

    except Exception as exc:
        import traceback as _tb
        result = {
            "ticker": ticker,
            "engine": engine["name"],
            "status": "error",
            "error": str(exc),
            "traceback": _tb.format_exc(),
        }
        logger.warning("[%s] %s: %s", engine["name"], ticker, exc)

    _save(ckpt, result)
    return result


# ── Per-engine aggregation ────────────────────────────────────────────

def _safe(v, default=None):
    try:
        f = float(v)
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def aggregate_engine(results: list[dict], engine: dict) -> dict:
    ok = [r for r in results if r.get("status") == "ok" and r.get("total_trades", 0) > 0]
    pfs = [s for r in ok if (s := _safe(r.get("profit_factor"))) is not None and s < 100]
    wrs = [s for r in ok if (s := _safe(r.get("win_rate"))) is not None]
    sharpes = [s for r in ok if (s := _safe(r.get("sharpe_ratio"))) is not None]
    total_trades = sum(int(r.get("total_trades") or 0) for r in ok)
    profitable = sum(1 for r in ok if _safe(r.get("profit_factor"), 0) >= 1.0)
    ok_count = len(ok)

    pf_med = round(median(pfs), 3) if pfs else None
    wr_med = round(median(wrs), 1) if wrs else None
    profitable_pct = round(profitable / ok_count * 100, 1) if ok_count else 0

    # Tier assessment
    if pf_med is None:
        tier = "INCONCLUSIVE"
    elif pf_med >= 1.2 and profitable_pct >= 40 and total_trades >= 200:
        tier = "TIER_1"
    elif pf_med >= 0.8 and profitable_pct >= 25:
        tier = "TIER_2"
    else:
        tier = "TIER_3"

    pf_lift = round(pf_med - engine["baseline_pf"], 3) if pf_med is not None else None

    return {
        "engine": engine["name"],
        "strategy": engine["strategy"],
        "ok_count": ok_count,
        "total_trades": total_trades,
        "pf_median": pf_med,
        "wr_median": wr_med,
        "sharpe_median": round(median(sharpes), 3) if sharpes else None,
        "profitable_tickers": profitable,
        "profitable_pct": profitable_pct,
        "baseline_pf": engine["baseline_pf"],
        "pf_lift": pf_lift,
        "tier": tier,
    }


# ── Report ────────────────────────────────────────────────────────────

def write_report(
    engine_summaries: list[dict],
    all_results: dict[str, list[dict]],
    path: Path,
) -> None:
    lines = [
        "# PSU-Excluded All-Engines — {}".format(date.today()),
        "",
        "## Engine Summary",
        "",
        "| Engine | Trades | Median PF | Baseline PF | Lift | WR | Profitable | Tier |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in engine_summaries:
        lift_str = "{:+.3f}".format(s["pf_lift"]) if s["pf_lift"] is not None else "—"
        wr_str = "{:.1f}%".format(s["wr_median"]) if s["wr_median"] is not None else "—"
        lines.append(
            "| {} | {:,} | {} | {} | {} | {} | {}/{} ({:.0f}%) | {} |".format(
                s["engine"],
                s["total_trades"],
                s["pf_median"] or "—",
                s["baseline_pf"],
                lift_str,
                wr_str,
                s["profitable_tickers"], s["ok_count"], s["profitable_pct"],
                s["tier"],
            )
        )

    lines.extend(["", "## Tier Assessment", ""])
    t1 = [s for s in engine_summaries if s["tier"] == "TIER_1"]
    t2 = [s for s in engine_summaries if s["tier"] == "TIER_2"]
    t3 = [s for s in engine_summaries if s["tier"] == "TIER_3"]

    if t1:
        lines.append("**TIER 1** — Positive expectancy confirmed (walk-forward validation next):")
        for s in t1:
            lines.append("  - {}: PF {}, {}% profitable".format(s["engine"], s["pf_median"], s["profitable_pct"]))
    if t2:
        lines.append("**TIER 2** — Marginal improvement (one additional filter, new criteria doc):")
        for s in t2:
            lines.append("  - {}: PF {}, {}% profitable".format(s["engine"], s["pf_median"], s["profitable_pct"]))
    if t3:
        lines.append("**TIER 3** — PSU exclusion does not rescue:")
        for s in t3:
            lines.append("  - {}: PF {} (baseline {}), lift {}".format(
                s["engine"], s["pf_median"] or "—", s["baseline_pf"],
                "{:+.3f}".format(s["pf_lift"]) if s["pf_lift"] is not None else "—",
            ))

    # Top tickers per engine
    lines.extend(["", "## Top Tickers Per Engine", ""])
    for s in engine_summaries:
        eng_name = s["engine"]
        results = all_results.get(eng_name, [])
        top = sorted(
            [r for r in results if r.get("status") == "ok" and r.get("total_trades", 0) > 0],
            key=lambda r: _safe(r.get("profit_factor"), 0),
            reverse=True,
        )[:5]
        if top:
            lines.append("### {}".format(eng_name))
            lines.append("| Ticker | Trades | PF | WR |")
            lines.append("|---|---|---|---|")
            for r in top:
                pf_t = _safe(r.get("profit_factor"))
                wr_t = _safe(r.get("win_rate"))
                lines.append("| {} | {} | {} | {} |".format(
                    r["ticker"],
                    r.get("total_trades", 0),
                    "{:.2f}".format(pf_t) if pf_t is not None else "—",
                    "{:.0f}%".format(wr_t) if wr_t is not None else "—",
                ))
            lines.append("")

    path.write_text("\n".join(lines))
    logger.info("Report: %s", path)


# ── Main ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poc", action="store_true")
    parser.add_argument("--engines", default="", help="Comma-separated engine names to run")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--days", type=int, default=DAYS)
    args = parser.parse_args()

    universe = POC_TICKERS if args.poc else NON_PSU

    if args.engines:
        requested = {e.strip().lower() for e in args.engines.split(",")}
        engines = [e for e in ALL_ENGINES if e["name"] in requested]
        if not engines:
            logger.error("No matching engines for: %s", args.engines)
            return
    else:
        engines = ALL_ENGINES

    reports_dir = Path("reports") / "psu_all_engines"
    reports_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "PSU-excluded all-engines: %d tickers, %d engines, workers=%d",
        len(universe), len(engines), args.workers,
    )

    all_results: dict[str, list[dict]] = {e["name"]: [] for e in engines}
    t0 = time.monotonic()

    for engine in engines:
        logger.info("Running engine: %s", engine["name"])
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(run_ticker, ticker, engine, args.days, reports_dir, args.resume): ticker
                for ticker in universe
            }
            done = 0
            for fut in as_completed(futures):
                ticker = futures[fut]
                try:
                    result = fut.result()
                    all_results[engine["name"]].append(result)
                except Exception as exc:
                    all_results[engine["name"]].append({
                        "ticker": ticker, "engine": engine["name"],
                        "status": "error", "error": str(exc),
                    })
                done += 1
                elapsed = time.monotonic() - t0
                total_work = len(universe) * len(engines)
                completed = sum(len(v) for v in all_results.values())
                eta = (elapsed / completed) * (total_work - completed) if completed else 0
                if done % 10 == 0 or done == len(universe):
                    logger.info("[%s %d/%d] ETA %.0fs", engine["name"], done, len(universe), eta)

    engine_summaries = [aggregate_engine(all_results[e["name"]], e) for e in engines]

    report_path = reports_dir / "psu_all_engines_{}.md".format(date.today())
    write_report(engine_summaries, all_results, report_path)

    print("\n" + "="*70)
    print("PSU-EXCLUDED ALL-ENGINES — RESULTS")
    print("="*70)
    print("{:<16} {:>7} {:>10} {:>10} {:>7} {:>8}".format(
        "Engine", "Trades", "Median PF", "Baseline", "Lift", "Tier"
    ))
    print("-"*70)
    for s in engine_summaries:
        lift_str = "{:+.3f}".format(s["pf_lift"]) if s["pf_lift"] is not None else "  —  "
        print("{:<16} {:>7,} {:>10} {:>10} {:>7} {:>8}".format(
            s["engine"],
            s["total_trades"],
            str(s["pf_median"] or "—"),
            str(s["baseline_pf"]),
            lift_str,
            s["tier"],
        ))
    print("="*70)
    print("Report:", report_path)
    print()


if __name__ == "__main__":
    main()
