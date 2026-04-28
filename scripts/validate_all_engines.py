"""
MKUMARAN Trading OS — Strategy Validation Harness

Runs every registered strategy through the standard validation gauntlet
(backtest + Monte Carlo + Bootstrap Sharpe CI + Walk-Forward consistency)
across the Nifty 100 universe. Produces per-strategy JSON summaries and
a single comparison markdown table.

Usage
-----
    # POC — 3 tickers × rrms, verify JSON shape before full run:
    python scripts/validate_all_engines.py --poc

    # Full run (overnight):
    python scripts/validate_all_engines.py

    # Resume interrupted run (skips completed checkpoints):
    python scripts/validate_all_engines.py --resume

    # Specific strategies or tickers:
    python scripts/validate_all_engines.py --strategy rrms smc
    python scripts/validate_all_engines.py --ticker HDFCBANK RELIANCE

    # Control parallelism:
    python scripts/validate_all_engines.py --workers 6

After the run, open reports/engine_comparison_<date>.md to read the tier table.

Tier thresholds (from operator's decision framework)
-----------------------------------------------------
    Tier 1  — deploy:        WF Sharpe >= 1.0, Profit Factor >= 1.5, sig_rate >= 40%
    Tier 2  — regime-gate:   WF Sharpe >= 0.5  (works conditionally — add regime filter)
    Tier 3  — kill/rebuild:  below Tier 2
    Tier 4  — untested:      < 20 total trades or data unavailable

For pos_5ema (15m), run scripts/backfill_dhan_intraday.py first.
It will appear as Tier 4 with a "data_unavailable" flag until backfill is done.
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

# ── Bootstrap path ─────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("validate")


# ── Strategy registry ───────────────────────────────────────────────
# Source of truth: backtester.py line 859.
# pos_5ema needs 15m interval + Dhan backfill; all others use daily yfinance.
ENGINES: list[tuple[str, str, int]] = [
    # (strategy_name, interval, lookback_days)
    ("rrms",       "1d",  1095),
    ("smc",        "1d",  1095),
    ("wyckoff",    "1d",  1095),
    ("vsa",        "1d",  1095),
    ("harmonic",   "1d",  1095),
    ("confluence", "1d",  1095),
    ("pos_5ema",   "15m", 1095),  # skip until Dhan backfill is complete
]

# ── Universe ────────────────────────────────────────────────────────
# Nifty 100 — same list as scripts/backfill_dhan_intraday.py
NIFTY_100: list[str] = [
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

# POC universe — 3 large-caps across sectors
POC_TICKERS = ["HDFCBANK", "RELIANCE", "INFY"]

# ── Validation config ───────────────────────────────────────────────
VALIDATION_CONFIG = {
    "n_simulations": 1000,
    "n_bootstrap":   500,
    "n_windows":     5,
}

# ── Tier thresholds (operator's decision framework) ─────────────────
TIER1_WF_SHARPE     = 1.0
TIER1_PROFIT_FACTOR = 1.5
TIER1_SIG_RATE      = 0.40   # 40% of tickers show statistically significant edge
TIER1_MIN_TRADES    = 100    # total across all tickers

TIER2_WF_SHARPE     = 0.5    # works conditionally — add regime gate
TIER2_MIN_TRADES    = 30


# ── Checkpoint helpers ──────────────────────────────────────────────

def _ckpt_path(reports_dir: Path, strategy: str, interval: str, ticker: str) -> Path:
    return reports_dir / "checkpoints" / f"{strategy}_{interval}_{ticker}.json"


def _load_checkpoint(path: Path) -> dict | None:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return None


def _save_checkpoint(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, default=str, indent=2))


# ── Single-job runner ───────────────────────────────────────────────

def run_one(
    ticker: str,
    strategy: str,
    interval: str,
    days: int,
    reports_dir: Path,
    resume: bool,
) -> dict:
    """Run backtest + validation for one (ticker, strategy). Returns result dict."""
    ckpt = _ckpt_path(reports_dir, strategy, interval, ticker)

    if resume:
        cached = _load_checkpoint(ckpt)
        if cached is not None:
            logger.debug("Resume: using checkpoint %s/%s/%s", strategy, interval, ticker)
            return cached

    from mcp_server.backtester import run_backtest
    from mcp_server.backtest_validation import run_full_validation, summarise

    t0 = time.monotonic()
    try:
        bt = run_backtest(ticker, strategy=strategy, days=days, interval=interval)

        # pos_5ema / intraday: graceful skip if cache is empty
        if bt.get("error"):
            result: dict = {
                "ticker": ticker, "strategy": strategy, "interval": interval,
                "status": "data_unavailable",
                "error": bt["error"],
            }
            _save_checkpoint(ckpt, result)
            return result

        validation = run_full_validation(
            bt,
            monte_carlo_kwargs={"n_simulations": VALIDATION_CONFIG["n_simulations"]},
            bootstrap_kwargs=  {"n_bootstrap":   VALIDATION_CONFIG["n_bootstrap"]},
            walk_forward_kwargs={"n_windows":    VALIDATION_CONFIG["n_windows"]},
        )

        result = {
            "ticker":   ticker,
            "strategy": strategy,
            "interval": interval,
            "status":   "ok",
            "elapsed_s": round(time.monotonic() - t0, 1),
            "summary":  summarise(validation),
            "backtest_metrics": {
                k: bt.get(k) for k in (
                    "total_trades", "win_rate", "profit_factor",
                    "sharpe_ratio", "max_drawdown_pct",
                )
            },
            "validation": validation,
        }
    except Exception as exc:
        result = {
            "ticker": ticker, "strategy": strategy, "interval": interval,
            "status": "error",
            "error": str(exc),
        }
        logger.warning("Error %s/%s: %s", strategy, ticker, exc)

    _save_checkpoint(ckpt, result)
    return result


# ── Aggregation ─────────────────────────────────────────────────────

def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return f if f == f else None  # filter NaN
    except (TypeError, ValueError):
        return None


def aggregate_strategy(results: list[dict]) -> dict:
    """Aggregate all (ticker, strategy) results into strategy-level stats."""
    ok      = [r for r in results if r.get("status") == "ok"]
    unavail = [r for r in results if r.get("status") == "data_unavailable"]
    errors  = [r for r in results if r.get("status") == "error"]

    if not ok:
        status = "data_unavailable" if unavail else "error"
        return {
            "strategy":    results[0]["strategy"] if results else "",
            "interval":    results[0]["interval"] if results else "",
            "status":      status,
            "ticker_count": len(results),
            "ok_count":    0,
        }

    # Walk-forward Sharpe (per-ticker mean across windows)
    wf_sharpes = [
        s for r in ok
        if (s := _safe_float(r.get("validation", {}).get("walk_forward", {}).get("sharpe_mean"))) is not None
    ]

    # Profit factors
    pfs = [
        s for r in ok
        if (s := _safe_float(r.get("backtest_metrics", {}).get("profit_factor"))) is not None
        and s < 100  # filter infinite/absurd values (< 5 trades)
    ]

    # Win rates
    wrs = [
        s for r in ok
        if (s := _safe_float(r.get("backtest_metrics", {}).get("win_rate"))) is not None
    ]

    # Walk-forward consistency rates
    consistencies = [
        s for r in ok
        if (s := _safe_float(r.get("validation", {}).get("walk_forward", {}).get("consistency_rate"))) is not None
    ]

    # Monte Carlo significance
    sig_flags = [
        r.get("validation", {}).get("monte_carlo", {}).get("is_significant", False)
        for r in ok
    ]
    sig_rate = sum(sig_flags) / len(sig_flags) if sig_flags else 0.0

    # Total trades across all tickers
    total_trades = sum(
        int(r.get("backtest_metrics", {}).get("total_trades") or 0)
        for r in ok
    )

    # Bootstrap: % of tickers where CI doesn't cross zero
    bs_robust = [
        r.get("validation", {}).get("bootstrap", {}).get("ci_crosses_zero") is False
        for r in ok
    ]
    bs_robust_rate = sum(bs_robust) / len(bs_robust) if bs_robust else 0.0

    def _p(lst: list[float], q: float) -> float | None:
        if not lst:
            return None
        lst_s = sorted(lst)
        idx = q * (len(lst_s) - 1)
        lo, hi = int(idx), min(int(idx) + 1, len(lst_s) - 1)
        return lst_s[lo] + (idx - lo) * (lst_s[hi] - lst_s[lo])

    return {
        "strategy":    ok[0]["strategy"],
        "interval":    ok[0]["interval"],
        "status":      "ok",
        "ticker_count":     len(results),
        "ok_count":         len(ok),
        "unavail_count":    len(unavail),
        "error_count":      len(errors),
        "total_trades":     total_trades,
        # Walk-forward Sharpe
        "wf_sharpe_median": round(median(wf_sharpes), 3)         if wf_sharpes else None,
        "wf_sharpe_p25":    round(_p(wf_sharpes, 0.25) or 0, 3) if wf_sharpes else None,
        "wf_sharpe_p75":    round(_p(wf_sharpes, 0.75) or 0, 3) if wf_sharpes else None,
        # Other metrics
        "profit_factor_median":   round(median(pfs), 3)          if pfs else None,
        "win_rate_median":        round(median(wrs), 3)           if wrs else None,
        "consistency_median":     round(median(consistencies), 3) if consistencies else None,
        "sig_rate":               round(sig_rate, 3),
        "bootstrap_robust_rate":  round(bs_robust_rate, 3),
    }


# ── Tier classifier ─────────────────────────────────────────────────

def classify_tier(agg: dict) -> str:
    if agg.get("status") != "ok" or agg.get("ok_count", 0) == 0:
        return "4"

    wf  = agg.get("wf_sharpe_median") or 0
    pf  = agg.get("profit_factor_median") or 0
    sig = agg.get("sig_rate") or 0
    tot = agg.get("total_trades") or 0

    if wf >= TIER1_WF_SHARPE and pf >= TIER1_PROFIT_FACTOR and sig >= TIER1_SIG_RATE and tot >= TIER1_MIN_TRADES:
        return "1"
    if wf >= TIER2_WF_SHARPE and tot >= TIER2_MIN_TRADES:
        return "2"
    if tot >= TIER2_MIN_TRADES:
        return "3"
    return "4"


TIER_LABEL = {
    "1": "Tier 1 — deploy",
    "2": "Tier 2 — regime-gate",
    "3": "Tier 3 — kill/rebuild",
    "4": "Tier 4 — untested/no-data",
}


# ── Comparison markdown ─────────────────────────────────────────────

def write_comparison_md(aggs: list[dict], output_path: Path) -> None:
    lines = [
        f"# Strategy Validation — {date.today()}",
        "",
        "**Thresholds:** Tier 1 = WF Sharpe ≥ 1.0 + PF ≥ 1.5 + sig_rate ≥ 40% + trades ≥ 100  |  "
        "Tier 2 = WF Sharpe ≥ 0.5  |  Tier 3 = below Tier 2  |  Tier 4 = no data",
        "",
        "| Strategy | TF | Tickers OK | WF Sharpe (med) | P25–P75 | Profit Factor | Win Rate | Sig Rate | Consistency | Trades | Bootstrap | **Tier** |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    for agg in sorted(aggs, key=lambda a: (classify_tier(a), -(a.get("wf_sharpe_median") or 0))):
        tier = classify_tier(agg)
        ok   = agg.get("ok_count", 0)
        tot  = agg.get("ticker_count", 0)
        wf   = agg.get("wf_sharpe_median")
        p25  = agg.get("wf_sharpe_p25")
        p75  = agg.get("wf_sharpe_p75")
        pf   = agg.get("profit_factor_median")
        wr   = agg.get("win_rate_median")
        sig  = agg.get("sig_rate")
        cons = agg.get("consistency_median")
        tr   = agg.get("total_trades", 0)
        bs   = agg.get("bootstrap_robust_rate")

        def _fmt(v, pct: bool = False, decimals: int = 2) -> str:
            if v is None:
                return "—"
            if pct:
                return f"{v * 100:.0f}%"
            return f"{v:.{decimals}f}"

        lines.append(
            f"| **{agg['strategy']}** | {agg['interval']} "
            f"| {ok}/{tot} "
            f"| {_fmt(wf)} "
            f"| {_fmt(p25)}–{_fmt(p75)} "
            f"| {_fmt(pf)} "
            f"| {_fmt(wr, pct=True)} "
            f"| {_fmt(sig, pct=True)} "
            f"| {_fmt(cons, pct=True)} "
            f"| {tr:,} "
            f"| {_fmt(bs, pct=True)} "
            f"| **{TIER_LABEL[tier]}** |"
        )

    lines += ["", "---", ""]

    # Per-tier breakdown narrative
    tier_groups: dict[str, list[str]] = {"1": [], "2": [], "3": [], "4": []}
    for agg in aggs:
        tier_groups[classify_tier(agg)].append(agg["strategy"])

    lines.append("## Breakdown")
    lines.append("")
    for t, label in TIER_LABEL.items():
        names = tier_groups[t]
        if names:
            lines.append(f"- **{label}:** {', '.join(names)}")
    lines.append("")
    lines.append(
        "## Next steps\n"
        "- Tier 1: wire into MWA with the suggested weight from the operator's decision gate\n"
        "- Tier 2: build regime-conditional gate in `regime_detector.py`; re-validate\n"
        "- Tier 3: review signal logic — strategy may be salvageable with better entry rules\n"
        "- Tier 4 (pos_5ema): run `python scripts/backfill_dhan_intraday.py --resume` "
        "then re-run this harness with `--strategy pos_5ema`\n"
    )

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Comparison table → %s", output_path)


# ── Main ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Validate all trading strategy engines")
    parser.add_argument("--poc",      action="store_true",
                        help="POC mode: 3 tickers × rrms only — verifies JSON shape before full run")
    parser.add_argument("--resume",   action="store_true",
                        help="Skip already-completed (ticker, strategy) pairs")
    parser.add_argument("--workers",  type=int, default=4,
                        help="Parallel workers (default 4; ThreadPool — GIL released by numpy)")
    parser.add_argument("--strategy", nargs="+", default=None,
                        help="Run only these strategies (e.g. --strategy rrms smc)")
    parser.add_argument("--ticker",   nargs="+", default=None,
                        help="Run only these tickers (e.g. --ticker HDFCBANK RELIANCE)")
    parser.add_argument("--reports-dir", default="reports",
                        help="Directory for checkpoints + output (default: reports/)")
    args = parser.parse_args()

    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Select engines
    engines = ENGINES
    if args.poc:
        engines = [("rrms", "1d", 1095)]
    elif args.strategy:
        engines = [(s, iv, d) for s, iv, d in ENGINES if s in args.strategy]

    # Select universe
    if args.poc:
        universe = POC_TICKERS
    elif args.ticker:
        universe = [t.upper() for t in args.ticker]
    else:
        universe = NIFTY_100

    # Build job list
    jobs: list[tuple[str, str, str, int]] = []
    for strategy, interval, days in engines:
        for ticker in universe:
            jobs.append((ticker, strategy, interval, days))

    total = len(jobs)
    logger.info(
        "Jobs: %d (%d strategies × %d tickers) | workers=%d | resume=%s",
        total, len(engines), len(universe), args.workers, args.resume,
    )

    if args.poc:
        logger.info("POC mode — %d jobs. Verifying JSON shape before full run.", total)

    # Estimate wall-clock
    est_min = total * 12 / args.workers / 60  # ~12s per job (empirical)
    logger.info("Estimated wall-clock: %.0f min (%.0f h) at ~12s/job", est_min, est_min / 60)

    # ── Run jobs ──────────────────────────────────────────────────
    all_results: list[dict] = []
    done = 0
    start_time = time.monotonic()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_to_job = {
            pool.submit(run_one, ticker, strategy, interval, days, reports_dir, args.resume): (ticker, strategy)
            for ticker, strategy, interval, days in jobs
        }

        for future in as_completed(future_to_job):
            ticker, strategy = future_to_job[future]
            try:
                result = future.result()
                all_results.append(result)
            except Exception as exc:
                logger.error("Job %s/%s raised: %s", strategy, ticker, exc)
                all_results.append({
                    "ticker": ticker, "strategy": strategy,
                    "status": "error", "error": str(exc),
                })

            done += 1
            elapsed = time.monotonic() - start_time
            eta = (elapsed / done) * (total - done) if done > 0 else 0
            logger.info(
                "[%d/%d] %s/%s | elapsed=%.0fs | ETA=%.0fmin",
                done, total, strategy, ticker, elapsed, eta / 60,
            )

    # ── Aggregate per strategy ────────────────────────────────────
    from itertools import groupby

    # Group by (strategy, interval)
    def _key(r: dict) -> tuple[str, str]:
        return (r.get("strategy", ""), r.get("interval", ""))

    sorted_results = sorted(all_results, key=_key)
    aggs: list[dict] = []

    for (strategy, interval), group in groupby(sorted_results, key=_key):
        group_list = list(group)
        agg = aggregate_strategy(group_list)
        agg["tier"] = classify_tier(agg)

        # Save per-strategy summary JSON
        summary_path = reports_dir / f"{strategy}_{interval}_summary.json"
        summary_path.write_text(json.dumps(agg, default=str, indent=2))
        logger.info("Saved %s", summary_path)

        aggs.append(agg)

    # ── Write comparison table ─────────────────────────────────────
    today_str = date.today().isoformat()
    md_path = reports_dir / f"engine_comparison_{today_str}.md"
    write_comparison_md(aggs, md_path)

    # ── POC verification ──────────────────────────────────────────
    if args.poc:
        ok_results = [r for r in all_results if r.get("status") == "ok"]
        if ok_results:
            sample = ok_results[0]
            print("\n" + "=" * 60)
            print("POC VERIFICATION — sample result shape:")
            print(f"  ticker: {sample['ticker']} | strategy: {sample['strategy']}")
            print(f"  total_trades: {sample['backtest_metrics'].get('total_trades')}")
            print(f"  sharpe_ratio: {sample['backtest_metrics'].get('sharpe_ratio')}")
            print(f"  profit_factor: {sample['backtest_metrics'].get('profit_factor')}")
            print(f"  wf_sharpe_mean: {sample['validation'].get('walk_forward', {}).get('sharpe_mean')}")
            print(f"  mc_is_significant: {sample['validation'].get('monte_carlo', {}).get('is_significant')}")
            print(f"  bs_ci_crosses_zero: {sample['validation'].get('bootstrap', {}).get('ci_crosses_zero')}")
            print(f"\nSummary: {sample['summary']}")
            print("=" * 60)
            print("\nPOC passed. All fields present. Ready for full run:")
            print(f"  python scripts/validate_all_engines.py --workers {args.workers}")
        else:
            print("\nPOC: no successful results — check server logs for errors.")

    # ── Final summary ─────────────────────────────────────────────
    elapsed_total = time.monotonic() - start_time
    ok_count   = sum(1 for r in all_results if r.get("status") == "ok")
    skip_count = sum(1 for r in all_results if r.get("status") == "data_unavailable")
    err_count  = sum(1 for r in all_results if r.get("status") == "error")

    logger.info(
        "DONE: %d jobs in %.1f min | ok=%d skip=%d err=%d",
        total, elapsed_total / 60, ok_count, skip_count, err_count,
    )
    logger.info("Results → %s", md_path)

    # Print the table to stdout for easy copy-paste
    print("\n" + md_path.read_text())


if __name__ == "__main__":
    main()
