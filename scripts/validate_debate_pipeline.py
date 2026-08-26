"""
MKUMARAN Trading OS — Debate Validator Backtest

Replaces the rule-based quality gate (RRR ≥ 1.5, conf ≥ 55) with the
skill-based debate validator (ZERO API calls — pure algorithmic).

Compares: does debate routing produce better PF than the rule-based
baseline (PF 0.43 from 2026-05-08 pipeline run)?

Criteria doc: docs/strategy_validation/debate_validator_criteria.md
Baseline:     docs/strategy_validation/pipeline_validation_criteria.md

Usage
─────
    python scripts/validate_debate_pipeline.py --poc             # 5 tickers
    python scripts/validate_debate_pipeline.py --workers 4       # full run
    python scripts/validate_debate_pipeline.py --alert-only      # ALERT path only
    python scripts/validate_debate_pipeline.py --skip-debate     # rule-based baseline
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp1252 fix

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("debate_pipeline")


# ── Constants (match production pipeline for fair comparison) ────────

CONFLUENCE_ENGINES = ["smc", "wyckoff", "vsa", "harmonic"]
MWA_TICKER = "^NSEI"
MWA_EMA_PERIOD = 200

MIN_ENGINES = 2
MAX_OPEN_POSITIONS = 5
DEDUP_HOLD_DAYS = 30

DAYS = 1095
CAPITAL = 100_000
DEFAULT_WORKERS = 4

# Debate routing thresholds (match settings.DEBATE_UNCERTAIN_LOW/HIGH defaults)
PRE_CONF_DEBATE_LOW = 40
PRE_CONF_DEBATE_HIGH = 75
PRE_CONF_SKIP_BELOW = 40

# Baseline from 2026-05-08 pipeline run (frozen — used for lift calculation)
BASELINE_PF = 0.43
BASELINE_PROFITABLE_TICKERS_PCT = 13.3

# Universe — Nifty 100 (same as pipeline test)
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

POC_TICKERS = ["HDFCBANK", "TCS", "INFY", "FEDERALBNK", "SBIN"]


# ── MWA proxy (identical to production pipeline) ──────────────────────

def _load_mwa_series(days: int):
    try:
        import pandas as pd
        import yfinance as yf
        period = "5y" if days > 1095 else "4y"
        df = yf.download(MWA_TICKER, period=period, progress=False, auto_adjust=True)
        if df is None or df.empty or len(df) < MWA_EMA_PERIOD + 10:
            return None
        close = df["Close"].squeeze()
        ema200 = close.ewm(span=MWA_EMA_PERIOD, adjust=False).mean()
        bullish = close > ema200
        bullish.index = pd.to_datetime(bullish.index).normalize()
        logger.info("MWA: %d bars, %.0f%% bullish days", len(bullish), bullish.mean() * 100)
        return bullish
    except Exception as exc:
        logger.warning("MWA unavailable: %s", exc)
        return None


def _mwa_ok(date_val, mwa_series) -> bool:
    if mwa_series is None:
        return True
    try:
        import pandas as pd
        key = pd.to_datetime(date_val).normalize()
        for delta in (0, -1, -2, 1, 2):
            shifted = key + pd.Timedelta(days=delta)
            if shifted in mwa_series.index:
                return bool(mwa_series[shifted])
        return True
    except Exception:
        return True


# ── Pre-confidence scoring ────────────────────────────────────────────

def _compute_pre_confidence(
    engines_agreed: int,
    rrr: float,
    mwa_aligned: bool,
) -> int:
    """Score a signal before debate routing.

    This approximates the rule-based scanner confidence without LLM.
    Formula mirrors the confluence-based confidence in the production
    pipeline (each engine adds ~15 points on a base of 10).
    """
    base = 10
    base += engines_agreed * 15      # 2 engines → 40, 3 → 55, 4 → 70
    if mwa_aligned:
        base += 10
    if rrr >= 2.0:
        base += 5
    elif rrr >= 3.0:
        base += 10
    return min(95, max(10, base))


# ── Debate routing ────────────────────────────────────────────────────

def _route_through_debate(
    ticker: str,
    direction: str,
    pattern: str,
    rrr: float,
    entry_price: float,
    stop_loss: float,
    target: float,
    engines_agreed: int,
    pre_confidence: int,
    alert_only: bool,
    skip_debate: bool,
) -> str:
    """Return 'ALERT', 'WATCHLIST', or 'SKIP'.

    skip_debate=True uses the same rule-based gate as the production pipeline
    (RRR ≥ 1.5, conf ≥ 55) — this is the 'no debate' comparison baseline.
    """
    if skip_debate:
        if rrr >= 1.5 and pre_confidence >= 55:
            return "ALERT"
        return "SKIP"

    # Route based on pre-confidence triage
    if pre_confidence < PRE_CONF_SKIP_BELOW:
        return "SKIP"

    try:
        from mcp_server.debate_validator import run_debate
        result = run_debate(
            ticker=ticker,
            direction=direction,
            pattern=pattern,
            rrr=rrr,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=target,
            mwa_direction="BULL" if direction == "LONG" else "BEAR",
            scanner_count=engines_agreed,
            tv_confirmed=False,
            sector_strength="NEUTRAL",
            fii_net=0.0,
            delivery_pct=50.0,
            confidence_boosts=[],
            pre_confidence=pre_confidence,
        )
        rec = result.recommendation
    except Exception as exc:
        logger.debug("Debate failed for %s (fallback to rule-based): %s", ticker, exc)
        # Fallback: use pre-confidence threshold
        rec = "ALERT" if pre_confidence >= 55 else "SKIP"

    if alert_only and rec == "WATCHLIST":
        return "SKIP"
    return rec


# ── Checkpoint helpers ────────────────────────────────────────────────

def _ckpt_path(reports_dir: Path, ticker: str, suffix: str = "") -> Path:
    name = f"{ticker}{suffix}.json"
    return reports_dir / "debate_checkpoints" / name


def _load_ckpt(path: Path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return None


def _save_ckpt(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, default=str, indent=2), encoding='utf-8')


# ── Per-ticker runner ─────────────────────────────────────────────────

def run_ticker(
    ticker: str,
    days: int,
    mwa_series,
    reports_dir: Path,
    resume: bool,
    alert_only: bool,
    skip_debate: bool,
    suffix: str,
) -> dict:
    ckpt = _ckpt_path(reports_dir, ticker, suffix)
    if resume and (cached := _load_ckpt(ckpt)) is not None:
        return cached

    try:
        from mcp_server.backtester import (
            DEFAULT_SLIPPAGE_PCT,
            _calculate_metrics,
            _generate_confluence_signals,
            _simulate_trades,
        )
        from mcp_server.nse_scanner import get_stock_data

        period = "3y" if days <= 1095 else "5y"
        data = get_stock_data(ticker, period=period)
        if data is None or data.empty or len(data) < 100:
            result = {"ticker": ticker, "status": "data_unavailable"}
            _save_ckpt(ckpt, result)
            return result

        data.columns = [c.lower() for c in data.columns]
        raw = _generate_confluence_signals(data, ticker, CAPITAL)

        approved_signals = []
        routed = {"ALERT": 0, "WATCHLIST": 0, "SKIP": 0, "pre_skip": 0}

        for sig in raw:
            bar_idx = sig.get("bar_idx", 0)
            if bar_idx >= len(data):
                continue
            try:
                sig_date = data.index[bar_idx].date()
            except Exception:
                continue

            engines_agreed = sig.get("engines_agreed", 1)
            if engines_agreed < MIN_ENGINES:
                continue

            rps = float(sig.get("risk_per_share") or 0)
            rwps = float(sig.get("reward_per_share") or 0)
            rrr = rwps / rps if rps > 0 else 0
            direction = sig.get("direction", "LONG")
            mwa_aligned = _mwa_ok(sig_date, mwa_series) if direction == "LONG" else True

            pre_conf = _compute_pre_confidence(engines_agreed, rrr, mwa_aligned)

            if pre_conf < PRE_CONF_SKIP_BELOW and not skip_debate:
                routed["pre_skip"] += 1
                continue

            # MWA filter (same as production)
            if direction == "LONG" and not mwa_aligned:
                routed["pre_skip"] += 1
                continue

            entry = float(data["close"].iloc[bar_idx])
            sl = float(sig.get("stop_loss") or (entry * 0.97))
            target = float(sig.get("target") or (entry * 1.05))

            verdict = _route_through_debate(
                ticker=ticker,
                direction=direction,
                pattern=sig.get("pattern", "confluence"),
                rrr=rrr,
                entry_price=entry,
                stop_loss=sl,
                target=target,
                engines_agreed=engines_agreed,
                pre_confidence=pre_conf,
                alert_only=alert_only,
                skip_debate=skip_debate,
            )
            routed[verdict] = routed.get(verdict, 0) + 1

            if verdict in ("ALERT", "WATCHLIST"):
                approved_signals.append({
                    **sig,
                    "ticker": ticker,
                    "sig_date": str(sig_date),
                    "debate_verdict": verdict,
                })

        if not approved_signals:
            result = {
                "ticker": ticker, "status": "ok",
                "approved_signal_count": 0, "total_trades": 0,
                "win_rate": 0, "profit_factor": 0,
                "sharpe_ratio": None, "max_drawdown_pct": 0,
                "routed": routed,
            }
            _save_ckpt(ckpt, result)
            return result

        trades, equity, total_costs = _simulate_trades(
            data, approved_signals, CAPITAL, slippage_pct=DEFAULT_SLIPPAGE_PCT,
        )
        metrics = _calculate_metrics(trades, equity, CAPITAL, total_costs, backtest_days=days)

        result = {
            "ticker": ticker,
            "status": "ok",
            "approved_signal_count": len(approved_signals),
            "routed": routed,
            **{k: metrics.get(k) for k in (
                "total_trades", "win_rate", "profit_factor",
                "sharpe_ratio", "max_drawdown_pct", "total_return",
            )},
        }

    except Exception as exc:
        import traceback as _tb
        result = {
            "ticker": ticker, "status": "error",
            "error": str(exc),
            "traceback": _tb.format_exc(),
        }
        logger.warning("Error on %s: %s", ticker, exc)

    _save_ckpt(ckpt, result)
    return result


# ── Global position dedup ──────────────────────────────────────────────

def apply_dedup(all_signals: list[dict]) -> list[dict]:
    import datetime as _dt

    def _to_date(s):
        try:
            return _dt.date.fromisoformat(str(s.get("sig_date", "2000-01-01")))
        except Exception:
            return _dt.date(2000, 1, 1)

    sorted_sigs = sorted(all_signals, key=_to_date)
    open_until: dict[str, _dt.date] = {}
    open_count = 0
    approved: list[dict] = []

    for sig in sorted_sigs:
        ticker = sig["ticker"]
        sig_date = _to_date(sig)
        expired = [t for t, d in open_until.items() if sig_date >= d]
        for t in expired:
            del open_until[t]
            open_count -= 1
        if ticker in open_until or open_count >= MAX_OPEN_POSITIONS:
            continue
        approved.append(sig)
        open_until[ticker] = sig_date + timedelta(days=DEDUP_HOLD_DAYS)
        open_count += 1

    return approved


# ── Aggregation + report ──────────────────────────────────────────────

def _safe(v, default=None):
    try:
        f = float(v)
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def aggregate(results: list[dict]) -> dict:
    ok = [r for r in results if r.get("status") == "ok" and r.get("total_trades", 0) > 0]
    pfs = [s for r in ok if (s := _safe(r.get("profit_factor"))) is not None and s < 100]
    wrs = [s for r in ok if (s := _safe(r.get("win_rate"))) is not None]
    sharpes = [s for r in ok if (s := _safe(r.get("sharpe_ratio"))) is not None]
    total_trades = sum(int(r.get("total_trades") or 0) for r in ok)
    profitable = sum(1 for r in ok if _safe(r.get("profit_factor"), 0) >= 1.0)

    routed_total: dict[str, int] = {}
    for r in results:
        for k, v in (r.get("routed") or {}).items():
            routed_total[k] = routed_total.get(k, 0) + v

    return {
        "ticker_count": len(results),
        "ok_count": len(ok),
        "total_trades": total_trades,
        "pf_median": round(median(pfs), 3) if pfs else None,
        "wr_median": round(median(wrs), 1) if wrs else None,
        "sharpe_median": round(median(sharpes), 3) if sharpes else None,
        "profitable_tickers": profitable,
        "profitable_pct": round(profitable / len(ok) * 100, 1) if ok else 0,
        "routed": routed_total,
    }


def write_report(agg: dict, results: list[dict], path: Path, config: dict) -> None:
    pf = agg["pf_median"]
    lift = round(pf - BASELINE_PF, 3) if pf is not None else None
    profitable_pct = agg["profitable_pct"]

    lines = [
        f"# Debate Validator Pipeline — {date.today()}",
        "",
        "## Configuration",
        f"- Mode: {'SKIP-DEBATE (rule-based baseline)' if config['skip_debate'] else 'DEBATE ROUTING (skill agents)'}",
        f"- Alert-only: {config['alert_only']}",
        f"- Universe: {agg['ticker_count']} tickers  |  Lookback: {config['days']} days",
        "",
        "## Portfolio Summary",
        "",
        "| Metric | This run | Baseline (rule-based) | Lift |",
        "|---|---|---|---|",
        f"| Median PF | {pf or '—'} | {BASELINE_PF} | {lift:+.3f} |" if lift is not None else f"| Median PF | — | {BASELINE_PF} | — |",
        f"| Profitable tickers | {agg['profitable_tickers']}/{agg['ok_count']} ({profitable_pct}%) | 12/90 (13.3%) | — |",
        f"| Total trades | {agg['total_trades']:,} | 744 | — |",
        f"| Median WR | {str(round(agg['wr_median'], 1)) + '%' if agg['wr_median'] is not None else '—'} | 15.5% | — |",
        f"| Median Sharpe | {agg['sharpe_median'] or '—'} | — | — |",
        "",
        "## Debate Routing Summary",
        "",
        "| Verdict | Count |",
        "|---|---|",
    ]
    for k, v in sorted(agg.get("routed", {}).items()):
        lines.append(f"| {k} | {v:,} |")

    lines.extend([
        "",
        "## Tier Assessment vs Criteria Doc",
        "",
    ])

    if pf is None:
        lines.append("Insufficient data to tier.")
    elif pf >= 1.2 and profitable_pct >= 40 and agg["total_trades"] >= 100:
        lines.append("**TIER 1** — Debate validator has positive expectancy. Walk-forward validation next.")
    elif pf >= 0.8:
        lines.append("**TIER 2** — Marginal improvement over baseline. Consider alert-only or tighter debate threshold.")
    else:
        lines.append("**TIER 3** — Debate routing does not improve on rule-based baseline.")

    if lift is not None:
        if lift > 0:
            lines.append(f"Lift over baseline: +{lift:.3f} PF.")
        else:
            lines.append(f"Drag vs baseline: {lift:.3f} PF (debate routing made things worse).")

    lines.extend([
        "",
        "## Per-Ticker Results",
        "",
        "| Ticker | Status | Trades | PF | WR | Sharpe |",
        "|---|---|---|---|---|---|",
    ])
    for r in sorted(results, key=lambda x: -(x.get("total_trades") or 0)):
        if r.get("status") == "data_unavailable":
            lines.append(f"| {r['ticker']} | no data | — | — | — | — |")
        elif r.get("status") == "error":
            lines.append(f"| {r['ticker']} | ERROR | — | — | — | — |")
        else:
            pf_t = _safe(r.get("profit_factor"))
            wr_t = _safe(r.get("win_rate"))
            sh_t = _safe(r.get("sharpe_ratio"))
            lines.append(
                f"| {r['ticker']} | ok | {r.get('total_trades', 0)} |"
                f" {f'{pf_t:.2f}' if pf_t is not None else '—'} |"
                f" {f'{wr_t:.0f}%' if wr_t is not None else '—'} |"
                f" {f'{sh_t:.2f}' if sh_t is not None else '—'} |"
            )

    path.write_text("\n".join(lines), encoding='utf-8')
    logger.info("Report written: %s", path)


# ── Main ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poc", action="store_true", help="Run on POC_TICKERS only")
    parser.add_argument("--tickers", default="", help="Comma-separated ticker override")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--resume", action="store_true", help="Skip already-checkpointed tickers")
    parser.add_argument("--alert-only", action="store_true", help="WATCHLIST signals do not trade")
    parser.add_argument("--skip-debate", action="store_true", help="Use rule-based gate (no debate, for comparison)")
    parser.add_argument("--days", type=int, default=DAYS)
    args = parser.parse_args()

    if args.tickers:
        universe = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    elif args.poc:
        universe = POC_TICKERS
    else:
        universe = NIFTY_100

    suffix = "_alert_only" if args.alert_only else ("_no_debate" if args.skip_debate else "")
    reports_dir = Path("reports") / "debate_pipeline"
    reports_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Debate pipeline: %d tickers, %s mode, workers=%d",
        len(universe),
        "ALERT-ONLY" if args.alert_only else ("NO-DEBATE" if args.skip_debate else "FULL-DEBATE"),
        args.workers,
    )

    mwa_series = _load_mwa_series(args.days)

    results: list[dict] = []
    t0 = time.monotonic()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                run_ticker,
                ticker, args.days, mwa_series, reports_dir, args.resume,
                args.alert_only, args.skip_debate, suffix,
            ): ticker
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

    agg = aggregate(results)
    report_name = f"debate_pipeline_{date.today()}{suffix}.md"
    write_report(agg, results, reports_dir / report_name, {
        "days": args.days,
        "alert_only": args.alert_only,
        "skip_debate": args.skip_debate,
    })

    # Print summary
    print(f"\n{'='*60}")
    print("DEBATE VALIDATOR PIPELINE — RESULTS")
    print(f"{'='*60}")
    print(f"Universe:    {len(universe)} tickers")
    print(f"Mode:        {'alert-only' if args.alert_only else ('rule-based' if args.skip_debate else 'full-debate')}")
    print(f"Total trades:{agg['total_trades']:>6}")
    print(f"Median PF:   {agg['pf_median'] or 'insufficient data'}")
    print(f"Baseline PF: {BASELINE_PF}")
    if agg["pf_median"] is not None:
        lift = agg["pf_median"] - BASELINE_PF
        print(f"Lift:        {lift:+.3f}")
    print(f"Profitable:  {agg['profitable_tickers']}/{agg['ok_count']} ({agg['profitable_pct']}%)")
    print(f"Routing:     {agg.get('routed', {})}")
    print(f"Report:      {reports_dir / report_name}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
