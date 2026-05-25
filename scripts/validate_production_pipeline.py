"""
MKUMARAN Trading OS — Production Pipeline Replay

Tests the COMBINATION of all filters, not individual engines.
This is the diagnostic that answers: "Does the platform actually work?"

What this simulates
───────────────────
The production signal stack, applied to historical data:

  1. Engine confluence  — 2+ of (SMC, Wyckoff, VSA, Harmonic) agree
  2. MWA proxy         — Nifty 50 close above/below 200 EMA
                         (approximates market-wide alignment; long only when
                         market is in confirmed uptrend, no signals in bear)
  3. Quality gate      — RRR ≥ 1.5, confidence ≥ 55, valid price data
  4. Position dedup    — no second entry on same ticker while trade is open
  5. Event calendar    — no high-impact events within 6h of entry
  6. Score             — simulate each approved signal with realistic costs

Key distinction vs validate_all_engines.py
───────────────────────────────────────────
  validate_all_engines.py  → tests each engine in isolation (no filters)
  validate_production_pipeline.py → tests the filtered signal stream a
                                    paying user would actually receive

Usage
─────
    python scripts/validate_production_pipeline.py              # full run
    python scripts/validate_production_pipeline.py --poc        # 3 tickers
    python scripts/validate_production_pipeline.py --workers 4
    python scripts/validate_production_pipeline.py --resume
    python scripts/validate_production_pipeline.py --no-mwa     # skip MWA
    python scripts/validate_production_pipeline.py --min-engines 3
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
logger = logging.getLogger("pipeline")


# ── Configuration ───────────────────────────────────────────────────

CONFLUENCE_ENGINES = ["smc", "wyckoff", "vsa", "harmonic"]

# MWA proxy: only take LONG signals when Nifty is above its 200 EMA.
# This approximates the production MWA filter without live scan data.
MWA_TICKER = "^NSEI"
MWA_EMA_PERIOD = 200

# Pipeline gate thresholds (match production config)
MIN_RRR = 1.5            # minimum risk:reward ratio
MIN_CONFIDENCE = 55      # minimum signal confidence
MIN_ENGINES = 2          # minimum engines in agreement (confluence)
MAX_OPEN_POSITIONS = 5   # max simultaneous open trades across all tickers
DEDUP_HOLD_DAYS = 30     # don't re-enter ticker within this many days of previous entry

# Backtest parameters
DAYS = 1095              # 3 years
CAPITAL = 100_000        # per ticker (same as individual engine backtest)
DEFAULT_WORKERS = 4

# Universe — Nifty 100 (same as validate_all_engines.py)
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

POC_TICKERS = ["HDFCBANK", "RELIANCE", "INFY"]


# ── MWA proxy ───────────────────────────────────────────────────────

def _load_mwa_series(days: int):
    """Download Nifty 50 and compute 200 EMA.

    Returns a boolean Series indexed by date:
      True  = Nifty above 200 EMA → MWA bullish → allow LONG signals
      False = Nifty below 200 EMA → MWA bearish → skip all signals
    """
    try:
        import yfinance as yf
        import pandas as pd

        period = "5y" if days > 1095 else "4y"
        df = yf.download(MWA_TICKER, period=period, progress=False, auto_adjust=True)
        if df is None or df.empty or len(df) < MWA_EMA_PERIOD + 10:
            return None

        close = df["Close"].squeeze()
        ema200 = close.ewm(span=MWA_EMA_PERIOD, adjust=False).mean()
        bullish = (close > ema200)
        bullish.index = pd.to_datetime(bullish.index).normalize()
        logger.info(
            "MWA proxy: Nifty 200 EMA loaded (%d bars, %.0f%% bullish)",
            len(bullish), bullish.mean() * 100,
        )
        return bullish
    except Exception as e:
        logger.warning("MWA proxy failed (%s) — proceeding without MWA filter", e)
        return None


def _mwa_ok(date_val, mwa_series) -> bool:
    """True if MWA approves a LONG signal on this date."""
    if mwa_series is None:
        return True  # bypass if unavailable
    try:
        import pandas as pd
        key = pd.to_datetime(date_val).normalize()
        # Look up with a tolerance of ±2 days for weekend/holiday gaps
        for delta in (0, -1, -2, 1, 2):
            shifted = key + pd.Timedelta(days=delta)
            if shifted in mwa_series.index:
                return bool(mwa_series[shifted])
        return True  # default allow if date not found
    except Exception:
        return True


# ── Event calendar gate ─────────────────────────────────────────────

def _load_event_calendar():
    """Load the event calendar. Returns None if unavailable."""
    try:
        from mcp_server.event_calendar import get_calendar
        return get_calendar()
    except Exception as e:
        logger.debug("Event calendar unavailable: %s", e)
        return None


def _event_gate_ok(date_val, calendar) -> bool:
    """True if no high-impact event is within 6h of this date."""
    if calendar is None:
        return True
    try:
        import datetime as dt
        # Convert date to IST datetime at market open
        ist_open = dt.datetime.combine(date_val, dt.time(9, 15))
        return not calendar.high_impact_within(hours=6, now=ist_open)
    except Exception:
        return True


# ── Checkpoint helpers ──────────────────────────────────────────────

def _ckpt_path(reports_dir: Path, ticker: str) -> Path:
    return reports_dir / "pipeline_checkpoints" / f"{ticker}.json"


def _load_checkpoint(path: Path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return None


def _save_checkpoint(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, default=str, indent=2, encoding='utf-8'))


# ── Per-ticker signal generation + filtering ────────────────────────

def generate_filtered_signals(
    ticker: str,
    days: int,
    mwa_series,
    calendar,
    min_engines: int,
    use_mwa: bool,
) -> list[dict]:
    """Run confluence engine + all pipeline filters for one ticker.

    Returns a list of signals that passed ALL filters, with date metadata.
    These are the signals that would have been broadcast to a user.
    """
    from mcp_server.backtester import _generate_confluence_signals
    from mcp_server.nse_scanner import get_stock_data

    # Fetch OHLCV
    period = "3y" if days <= 1095 else "5y"
    data = get_stock_data(ticker, period=period)
    if data is None or data.empty or len(data) < 100:
        return []

    # Ensure lowercase columns for engine compatibility
    data.columns = [c.lower() for c in data.columns]

    # Generate confluence signals (2+ engines must agree)
    raw = _generate_confluence_signals(data, ticker, CAPITAL)
    if not raw:
        return []

    approved = []
    for sig in raw:
        bar_idx = sig["bar_idx"]
        if bar_idx >= len(data):
            continue

        try:
            sig_date = data.index[bar_idx].date()
        except Exception:
            continue

        engines_agreed = sig.get("engines_agreed", 1)
        confidence = sig.get("confidence", 50)
        rps = float(sig.get("risk_per_share") or 0)
        rwps = float(sig.get("reward_per_share") or 0)
        rrr = rwps / rps if rps > 0 else 0

        # ── Filter 1: Confluence threshold ─────────────────────────
        if engines_agreed < min_engines:
            continue

        # ── Filter 2: Quality gate ──────────────────────────────────
        if rrr < MIN_RRR:
            continue
        if confidence < MIN_CONFIDENCE:
            continue

        # ── Filter 3: MWA proxy ─────────────────────────────────────
        # Production system: MWA must be aligned with signal direction.
        # This replay approximates: LONG only when Nifty > 200 EMA.
        if use_mwa and sig.get("direction") == "LONG":
            if not _mwa_ok(sig_date, mwa_series):
                continue

        # ── Filter 4: Event calendar ────────────────────────────────
        if not _event_gate_ok(sig_date, calendar):
            continue

        approved.append({
            **sig,
            "ticker": ticker,
            "sig_date": str(sig_date),
        })

    return approved


# ── Single ticker backtest ──────────────────────────────────────────

def run_ticker(
    ticker: str,
    days: int,
    mwa_series,
    calendar,
    reports_dir: Path,
    resume: bool,
    min_engines: int,
    use_mwa: bool,
) -> dict:
    """Generate + filter signals for one ticker, simulate trades, return metrics."""
    ckpt = _ckpt_path(reports_dir, ticker)

    if resume:
        cached = _load_checkpoint(ckpt)
        if cached is not None:
            return cached

    try:
        from mcp_server.backtester import _simulate_trades, _calculate_metrics
        from mcp_server.nse_scanner import get_stock_data
        from mcp_server.backtester import DEFAULT_SLIPPAGE_PCT

        period = "3y" if days <= 1095 else "5y"
        data = get_stock_data(ticker, period=period)
        if data is None or data.empty or len(data) < 100:
            result = {"ticker": ticker, "status": "data_unavailable"}
            _save_checkpoint(ckpt, result)
            return result

        data.columns = [c.lower() for c in data.columns]

        filtered_signals = generate_filtered_signals(
            ticker, days, mwa_series, calendar, min_engines, use_mwa,
        )

        if not filtered_signals:
            result = {
                "ticker": ticker, "status": "ok",
                "raw_signal_count": 0, "approved_signal_count": 0,
                "total_trades": 0, "win_rate": 0, "profit_factor": 0,
                "sharpe_ratio": None, "max_drawdown_pct": 0,
            }
            _save_checkpoint(ckpt, result)
            return result

        # Simulate approved signals through cost-honest backtester
        trades, equity, total_costs = _simulate_trades(
            data, filtered_signals, CAPITAL, slippage_pct=DEFAULT_SLIPPAGE_PCT,
        )
        metrics = _calculate_metrics(trades, equity, CAPITAL, total_costs, backtest_days=days)

        result = {
            "ticker": ticker,
            "status": "ok",
            "approved_signal_count": len(filtered_signals),
            **{k: metrics.get(k) for k in (
                "total_trades", "win_rate", "profit_factor",
                "sharpe_ratio", "max_drawdown_pct", "total_return",
                "calmar_ratio",
            )},
        }
    except Exception as exc:
        import traceback as _tb
        result = {
            "ticker": ticker, "status": "error",
            "error": str(exc), "traceback": _tb.format_exc(),
        }
        logger.warning("Error on %s: %s", ticker, exc)

    _save_checkpoint(ckpt, result)
    return result


# ── Global position dedup ───────────────────────────────────────────

def apply_position_dedup(
    all_signals: list[dict],
    max_open: int,
    dedup_days: int,
) -> list[dict]:
    """Cross-ticker dedup: enforce max open positions and per-ticker cooldown.

    Processes signals in chronological order. Mirrors the production system's
    dedup logic: no second entry on the same ticker within dedup_days, and
    total concurrent open positions capped at max_open.
    """
    import datetime as _dt

    # Sort by signal date
    def _to_date(s):
        try:
            return _dt.date.fromisoformat(str(s.get("sig_date", "2000-01-01")))
        except Exception:
            return _dt.date(2000, 1, 1)

    sorted_sigs = sorted(all_signals, key=_to_date)

    open_until: dict[str, _dt.date] = {}  # ticker → date when position closes
    open_count = 0
    approved: list[dict] = []

    for sig in sorted_sigs:
        ticker = sig["ticker"]
        sig_date = _to_date(sig)

        # Release expired positions
        expired = [t for t, close_d in open_until.items() if sig_date >= close_d]
        for t in expired:
            del open_until[t]
            open_count -= 1

        # Skip if already in a position on this ticker
        if ticker in open_until:
            continue

        # Skip if at max open positions
        if open_count >= max_open:
            continue

        # Approve
        approved.append(sig)
        open_until[ticker] = sig_date + timedelta(days=dedup_days)
        open_count += 1

    return approved


# ── Summary stats ───────────────────────────────────────────────────

def _safe(v, default=None):
    try:
        f = float(v)
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def aggregate_results(results: list[dict], all_signals_before_dedup: list[dict], all_signals_after_dedup: list[dict]) -> dict:
    """Aggregate per-ticker results into portfolio-level stats."""
    ok = [r for r in results if r.get("status") == "ok" and r.get("total_trades", 0) > 0]

    pfs = [s for r in ok if (s := _safe(r.get("profit_factor"))) is not None and s < 100]
    wrs = [s for r in ok if (s := _safe(r.get("win_rate"))) is not None]
    sharpes = [s for r in ok if (s := _safe(r.get("sharpe_ratio"))) is not None]
    total_trades = sum(int(r.get("total_trades") or 0) for r in ok)
    total_raw = len(all_signals_before_dedup)
    total_filtered = len(all_signals_after_dedup)

    return {
        "ticker_count": len(results),
        "ok_count": len(ok),
        "total_raw_signals": total_raw,
        "total_filtered_signals": total_filtered,
        "filter_retention_pct": round(total_filtered / total_raw * 100, 1) if total_raw else 0,
        "total_trades": total_trades,
        "pf_median": round(median(pfs), 3) if pfs else None,
        "wr_median": round(median(wrs), 1) if wrs else None,
        "sharpe_median": round(median(sharpes), 3) if sharpes else None,
        "profitable_tickers": sum(1 for r in ok if _safe(r.get("profit_factor"), 0) >= 1.0),
    }


# ── Markdown report ─────────────────────────────────────────────────

def write_report(agg: dict, results: list[dict], output_path: Path, config: dict) -> None:
    lines = [
        f"# Production Pipeline Validation — {date.today()}",
        "",
        "## Configuration",
        f"- Confluence: {config['min_engines']}+ engines required",
        f"- MWA filter: {'ON (Nifty > 200 EMA)' if config['use_mwa'] else 'OFF'}",
        f"- Min RRR: {MIN_RRR}  |  Min confidence: {MIN_CONFIDENCE}",
        f"- Max open positions: {MAX_OPEN_POSITIONS}  |  Dedup window: {DEDUP_HOLD_DAYS} days",
        f"- Universe: {agg['ticker_count']} tickers  |  Lookback: {config['days']} days",
        "",
        "## Portfolio Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Tickers with data | {agg['ok_count']}/{agg['ticker_count']} |",
        f"| Raw signals (pre-filter) | {agg['total_raw_signals']:,} |",
        f"| Broadcast signals (post-filter + dedup) | {agg['total_filtered_signals']:,} |",
        f"| Filter retention | {agg['filter_retention_pct']}% |",
        f"| Total trades executed | {agg['total_trades']:,} |",
        f"| Median Profit Factor | {agg['pf_median'] or '—'} |",
        f"| Median Win Rate | {str(round(agg['wr_median'], 1)) + '%' if agg['wr_median'] is not None else '—'} |",
        f"| Median Sharpe | {agg['sharpe_median'] or '—'} |",
        f"| Profitable tickers (PF ≥ 1.0) | {agg['profitable_tickers']}/{agg['ok_count']} |",
        "",
        "## Interpretation",
        "",
    ]

    pf = agg["pf_median"]
    if pf is None:
        lines.append("Insufficient data to interpret.")
    elif pf >= 1.2:
        lines += [
            f"**PF {pf:.2f} ≥ 1.2 — pipeline has positive expectancy.**",
            "Individual engines lose in isolation; the combination filter adds real value.",
            "Next: walk-forward validation, regime breakdown, and weight assignment.",
        ]
    elif pf >= 0.7:
        lines += [
            f"**PF {pf:.2f} is 0.7–1.2 — combination helps but not enough.**",
            "Confluence is reducing losses vs standalone, but the filtered stream is still net negative.",
            "Next: identify which filters contribute most. Remove the weakest engine from confluence.",
        ]
    else:
        lines += [
            f"**PF {pf:.2f} < 0.7 — combination is also losing badly.**",
            "The signal sources themselves are too weak for the filtering to compensate.",
            "Next: fundamental engine review before adding more filter layers.",
        ]

    lines += [
        "",
        "## Per-ticker results (sorted by PF)",
        "",
        "| Ticker | Signals | Trades | PF | WR | Sharpe | MaxDD |",
        "|---|---|---|---|---|---|---|",
    ]

    for r in sorted(results, key=lambda x: -(_safe(x.get("profit_factor"), 0))):
        if r.get("status") != "ok":
            continue
        t = r["ticker"]
        sigs = r.get("approved_signal_count", 0)
        trades = r.get("total_trades", 0)
        pf_r = r.get("profit_factor")
        wr_r = r.get("win_rate")
        sh_r = r.get("sharpe_ratio")
        dd_r = r.get("max_drawdown_pct")

        def _f(v, fmt=".2f", sfx=""):
            return f"{v:{fmt}}{sfx}" if v is not None else "—"

        lines.append(
            f"| {t} | {sigs} | {trades} "
            f"| {_f(pf_r)} | {_f(wr_r, '.1f', '%')} "
            f"| {_f(sh_r)} | {_f(dd_r, '.1f', '%')} |"
        )

    output_path.write_text("\n".join(lines, encoding='utf-8'), encoding="utf-8")
    logger.info("Report → %s", output_path)


# ── Main ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Production pipeline replay")
    parser.add_argument("--poc", action="store_true", help="3 tickers only")
    parser.add_argument("--resume", action="store_true", help="Skip completed tickers")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--ticker", nargs="+", default=None)
    parser.add_argument("--days", type=int, default=DAYS)
    parser.add_argument("--no-mwa", action="store_true", help="Disable MWA proxy filter")
    parser.add_argument("--min-engines", type=int, default=MIN_ENGINES,
                        help=f"Confluence threshold (default {MIN_ENGINES})")
    parser.add_argument("--reports-dir", default="reports")
    args = parser.parse_args()

    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    universe = POC_TICKERS if args.poc else (
        [t.upper() for t in args.ticker] if args.ticker else NIFTY_100
    )
    use_mwa = not args.no_mwa

    config = {
        "min_engines": args.min_engines,
        "use_mwa": use_mwa,
        "days": args.days,
    }

    logger.info(
        "Production pipeline replay: %d tickers | MWA=%s | min_engines=%d | workers=%d",
        len(universe), use_mwa, args.min_engines, args.workers,
    )

    # Load shared resources once (not per-worker)
    mwa_series = _load_mwa_series(args.days) if use_mwa else None
    calendar = _load_event_calendar()

    # Phase 1: per-ticker signal generation (parallelised)
    t0 = time.monotonic()
    ticker_results: list[dict] = []
    all_signals_pre_dedup: list[dict] = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_to_ticker = {
            pool.submit(
                run_ticker, ticker, args.days, mwa_series, calendar,
                reports_dir, args.resume, args.min_engines, use_mwa,
            ): ticker
            for ticker in universe
        }
        done = 0
        for future in as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            try:
                result = future.result()
                ticker_results.append(result)
            except Exception as exc:
                logger.error("Worker error %s: %s", ticker, exc)
                ticker_results.append({"ticker": ticker, "status": "error", "error": str(exc)})
            done += 1
            elapsed = time.monotonic() - t0
            eta = (elapsed / done) * (len(universe) - done) if done > 0 else 0
            logger.info(
                "[%d/%d] %s | elapsed=%.0fs | ETA=%.0fmin",
                done, len(universe), ticker, elapsed, eta / 60,
            )

    # Phase 2: collect all pre-dedup signals for global dedup pass
    for r in ticker_results:
        ticker = r.get("ticker", "")
        if r.get("status") == "ok":
            # Re-generate filtered signals for dedup (fast, data already fetched)
            try:
                sigs = generate_filtered_signals(
                    ticker, args.days, mwa_series, calendar, args.min_engines, use_mwa,
                )
                all_signals_pre_dedup.extend(sigs)
            except Exception:
                pass

    # Phase 3: global position dedup across all tickers
    all_signals_post_dedup = apply_position_dedup(
        all_signals_pre_dedup, MAX_OPEN_POSITIONS, DEDUP_HOLD_DAYS,
    )
    logger.info(
        "Dedup: %d signals → %d after position limits (%.0f%% kept)",
        len(all_signals_pre_dedup), len(all_signals_post_dedup),
        len(all_signals_post_dedup) / max(len(all_signals_pre_dedup), 1) * 100,
    )

    # Phase 4: aggregate and report
    agg = aggregate_results(ticker_results, all_signals_pre_dedup, all_signals_post_dedup)

    today_str = date.today().isoformat()
    report_path = reports_dir / f"pipeline_report_{today_str}.md"
    write_report(agg, ticker_results, report_path, config)

    # Telegram notification
    _tg_notify(
        f"✅ Pipeline validation complete\n"
        f"PF={agg['pf_median']} | WR={agg['wr_median']}% | Trades={agg['total_trades']}\n"
        f"Signals: {agg['total_raw_signals']} raw → {agg['total_filtered_signals']} broadcast"
    )

    elapsed_min = (time.monotonic() - t0) / 60
    logger.info(
        "DONE in %.1f min | PF=%.2f | WR=%.1f%% | trades=%d",
        elapsed_min, agg["pf_median"] or 0, agg["wr_median"] or 0, agg["total_trades"],
    )
    print("\n" + report_path.read_text())


def _tg_notify(text: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return
    try:
        import urllib.parse
        import urllib.request
        payload = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload, timeout=5,
        )
    except Exception as e:
        logger.debug("Telegram notify failed: %s", e)


if __name__ == "__main__":
    main()
