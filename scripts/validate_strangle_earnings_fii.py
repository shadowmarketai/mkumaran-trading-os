"""
Nifty Weekly Strangle — Earnings/FII Gate Refinement Backtest

Tests whether adding earnings blackout + FII net flow gates to the Tier 2
validated Nifty weekly short strangle pushes it to Tier 1.

Criteria doc: docs/strategy_validation/strangle_earnings_fii_criteria.md
Baseline:     validate_nifty_weekly_strangle.py (Tier 2, Sharpe ~0.55)

Gate logic:
  Gate 1 — Earnings blackout: skip if any Nifty 50 constituent reports
            within [entry_date, expiry_date]. NSE corporate actions API.
            Cached to data/nifty50_earnings_cache.json on first run.

  Gate 2 — FII net flow: skip if rolling 5-session FII F&O net < 0.
            Primary: NSE historical FII API.
            Fallback: NSE F&O daily archives (per-day CSV).
            Cached to data/fii_fno_historical.csv on first fetch.
            If data unavailable: gate marked INCONCLUSIVE, not substituted.

Runs 4 variants: baseline | earnings-only | fii-only | both-gates
Reports comparison table + per-variant Tier verdict.

Usage:
    python scripts/validate_strangle_earnings_fii.py --poc
    python scripts/validate_strangle_earnings_fii.py
    python scripts/validate_strangle_earnings_fii.py --earnings-only
    python scripts/validate_strangle_earnings_fii.py --fii-only
    python scripts/validate_strangle_earnings_fii.py --from 2023-01-01
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS   = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(1, _SCRIPTS)

# ── Import simulation core from existing weekly strangle script ────────────

from validate_nifty_weekly_strangle import (  # noqa: E402
    simulate_trade,
    _load_options_data,
    _load_spot_from_db,
    _load_spot_from_yfinance,
    _load_vix_data,
    _build_vix_percentiles,
    _entry_target_for_expiry,
    _select_weekly_expiries,
    walk_forward,
    monte_carlo,
    bootstrap_sharpe,
    aggregate_metrics,
    check_override_conditions,
    determine_tier,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("strangle_gates_val")

# ── Nifty 50 tickers for earnings gate ────────────────────────────────────

NIFTY_50 = frozenset({
    "HDFCBANK", "RELIANCE", "ICICIBANK", "INFY", "TCS",
    "BHARTIARTL", "SBIN", "KOTAKBANK", "BAJFINANCE", "LT",
    "AXISBANK", "WIPRO", "ASIANPAINT", "MARUTI", "TITAN",
    "SUNPHARMA", "ULTRACEMCO", "NTPC", "POWERGRID", "ONGC",
    "TECHM", "HCLTECH", "BAJAJFINSV", "TATAMOTORS", "NESTLEIND",
    "M&M", "JSWSTEEL", "TATASTEEL", "INDUSINDBK", "HINDALCO",
    "CIPLA", "ADANIPORTS", "GRASIM", "BPCL", "COALINDIA",
    "EICHERMOT", "DRREDDY", "DIVISLAB", "SBILIFE", "BRITANNIA",
    "HEROMOTOCO", "APOLLOHOSP", "BAJAJ-AUTO", "TATACONSUM",
    "SHRIRAMFIN", "ADANIENT", "HDFCLIFE", "ICICIGI", "PIDILITIND",
    "HAVELLS",
})

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
}

EARNINGS_CACHE = Path("data/nifty50_earnings_cache.json")
FII_CACHE      = Path("data/fii_fno_historical.csv")

FII_WINDOW = 5  # rolling sessions for FII net flow


# ── Gate 1: Earnings calendar ────────────────────────────────────────────

def _nse_session():
    import requests
    s = requests.Session()
    s.headers.update(NSE_HEADERS)
    try:
        s.get("https://www.nseindia.com", timeout=10)
        time.sleep(0.5)
    except Exception:
        pass
    return s


def _fetch_earnings_batch(session, from_date: date, to_date: date) -> list[dict]:
    url = "https://www.nseindia.com/api/corporates-corporateActions"
    params = {
        "index":     "equities",
        "from_date": from_date.strftime("%d-%m-%Y"),
        "to_date":   to_date.strftime("%d-%m-%Y"),
        "type":      "financial results",
    }
    try:
        resp = session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            return []
        events = []
        for item in data:
            purpose = item.get("purpose", "").lower()
            if not any(kw in purpose for kw in [
                "financial result", "quarterly result",
                "annual result", "q1", "q2", "q3", "q4",
            ]):
                continue
            try:
                results_date = date(
                    *[int(p) for p in reversed(item["exDate"].split("-"))]
                    if "-" in item["exDate"]
                    else (
                        int(item["exDate"][7:]),
                        {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
                         "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}[item["exDate"][3:6]],
                        int(item["exDate"][:2]),
                    )
                )
            except Exception:
                try:
                    from datetime import datetime
                    results_date = datetime.strptime(item["exDate"], "%d-%b-%Y").date()
                except Exception:
                    continue
            events.append({
                "ticker":       item.get("symbol", ""),
                "results_date": results_date.isoformat(),
            })
        return events
    except Exception as e:
        logger.warning("NSE earnings batch %s→%s failed: %s", from_date, to_date, e)
        return []


# NSE quarterly results seasons — approximate blackout windows.
# Virtually all Nifty 50 companies report within these month ranges each year.
# Used only when exact NSE corporate action dates are unavailable from the server.
# (month_start, day_start, month_end, day_end)
_RESULTS_SEASONS = [
    (4, 1,  5, 31),   # Q4 FY results
    (7, 1,  8, 31),   # Q1 results
    (10, 1, 11, 30),  # Q2 results
    (1, 1,  2, 28),   # Q3 results
]


def _approx_results_season_calendar(
    from_date: date, to_date: date
) -> dict[date, list[str]]:
    """
    Approximate earnings calendar: marks every trading day inside an NSE
    results season window as blocked. Over-filters (entire season blocked,
    not just days with confirmed announcements), but avoids look-ahead bias.
    Used only when exact NSE API dates are unavailable.
    """
    result: dict[date, list[str]] = {}
    cur = from_date
    while cur <= to_date:
        if cur.weekday() < 5:
            for m_start, d_start, m_end, d_end in _RESULTS_SEASONS:
                # Handle Feb 28/29
                if m_end == 2:
                    import calendar as _cal
                    d_end = _cal.monthrange(cur.year, 2)[1]
                try:
                    start = date(cur.year, m_start, d_start)
                    end   = date(cur.year, m_end, d_end)
                    if start <= cur <= end:
                        result[cur] = ["RESULTS_SEASON_APPROX"]
                        break
                except ValueError:
                    continue
        cur += timedelta(days=1)
    return result


def load_earnings_calendar(from_date: date, to_date: date) -> tuple[dict[date, list[str]], bool]:
    """
    Returns (calendar, is_exact).
    is_exact=True  → NSE API data (exact announcement dates)
    is_exact=False → approximate quarterly season windows (over-filters)

    Sources (in order): cache → NSE API → approximate seasons.
    Cache is skipped when it contains 0 events (failed previous fetch).
    """
    if EARNINGS_CACHE.exists():
        try:
            raw = json.loads(EARNINGS_CACHE.read_text())
            if (raw.get("fetched_from") <= from_date.isoformat() and
                    raw.get("fetched_to") >= to_date.isoformat() and
                    len(raw.get("events", {})) > 0):
                logger.info("Earnings calendar loaded from cache (%d event dates)", len(raw["events"]))
                result: dict[date, list[str]] = {}
                for d_str, tickers in raw["events"].items():
                    result[date.fromisoformat(d_str)] = tickers
                return result, raw.get("is_exact", True)
        except Exception:
            pass

    logger.info("Fetching Nifty 50 earnings calendar %s → %s from NSE...", from_date, to_date)
    session = _nse_session()
    all_events: list[dict] = []

    # Try one batch first; if it returns 0, server is likely blocked — skip remaining
    test_end = min(from_date + timedelta(days=89), to_date)
    test_batch = _fetch_earnings_batch(session, from_date, test_end)
    if test_batch:
        all_events.extend(test_batch)
        cur = test_end + timedelta(days=1)
        while cur <= to_date:
            batch_end = min(cur + timedelta(days=89), to_date)
            batch = _fetch_earnings_batch(session, cur, batch_end)
            all_events.extend(batch)
            cur = batch_end + timedelta(days=1)
            time.sleep(0.5)
    else:
        logger.info("NSE earnings API blocked (0 from first batch) — skipping remaining batches")

    result: dict[date, list[str]] = {}
    for ev in all_events:
        t = ev["ticker"]
        if t not in NIFTY_50:
            continue
        d = date.fromisoformat(ev["results_date"])
        result.setdefault(d, []).append(t)

    is_exact = bool(result)

    if not result:
        logger.info("Exact earnings dates unavailable — using approximate quarterly season windows")
        result = _approx_results_season_calendar(from_date, to_date)

    EARNINGS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    EARNINGS_CACHE.write_text(json.dumps({
        "fetched_from": from_date.isoformat(, encoding='utf-8'),
        "fetched_to":   to_date.isoformat(),
        "is_exact":     is_exact,
        "events":       {str(k): v for k, v in result.items()},
    }, indent=2))

    src = "exact NSE dates" if is_exact else "approximate quarterly seasons"
    logger.info("Earnings calendar: %d event dates (%s)", len(result), src)
    return result, is_exact


def earnings_blocked(
    entry_date: date,
    expiry_date: date,
    calendar: dict[date, list[str]],
) -> tuple[bool, str]:
    """Returns (blocked, reason). Blocked if any Nifty 50 stock reports in [entry, expiry]."""
    cur = entry_date
    while cur <= expiry_date:
        tickers = calendar.get(cur, [])
        if tickers:
            return True, "earnings:{},{}".format(",".join(tickers[:3]), cur)
        cur += timedelta(days=1)
    return False, ""


# ── Gate 2: FII net flow ─────────────────────────────────────────────────

def load_fii_historical(from_date: date, to_date: date) -> dict[date, float] | None:
    """
    Returns {date: fii_net_fo_crore} or None if data unavailable.
    Tries:
      1. Local cache (FII_CACHE)
      2. NSE historical FII API
      3. NSE F&O archives (per-month CSV)
    Per criteria doc: if unavailable, returns None (gate marked INCONCLUSIVE).
    """
    # Check local cache first
    if FII_CACHE.exists():
        try:
            import csv
            result: dict[date, float] = {}
            with FII_CACHE.open() as f:
                reader = csv.DictReader(f)
                for row in reader:
                    d = date.fromisoformat(row["date"])
                    if from_date <= d <= to_date:
                        result[d] = float(row["fii_net_fo"])
            if len(result) >= 200:
                logger.info("FII F&O data loaded from cache: %d sessions", len(result))
                return result
        except Exception as e:
            logger.warning("FII cache read failed: %s", e)

    # Try NSE historical FII API
    logger.info("Fetching historical FII F&O data from NSE...")
    result = _try_nse_fii_api(from_date, to_date)
    if result and len(result) >= 200:
        _save_fii_cache(result)
        return result

    # Try NSE F&O archives (daily CSV)
    result = _try_nse_fii_archives(from_date, to_date)
    if result and len(result) >= 200:
        _save_fii_cache(result)
        return result

    logger.warning(
        "FII F&O historical data unavailable after all sources. "
        "FII gate will be marked INCONCLUSIVE per criteria doc override condition."
    )
    return None


def _try_nse_fii_api(from_date: date, to_date: date) -> dict[date, float]:
    result: dict[date, float] = {}
    session = _nse_session()
    cur = from_date
    while cur <= to_date:
        batch_end = min(cur + timedelta(days=89), to_date)
        url = "https://www.nseindia.com/api/historical/fiidiiData"
        params = {
            "type":      "fiiDerivatives",
            "from_date": cur.strftime("%d-%m-%Y"),
            "to_date":   batch_end.strftime("%d-%m-%Y"),
        }
        try:
            resp = session.get(url, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                for row in data:
                    try:
                        d = date(*[int(p) for p in reversed(
                            row.get("date", "").split("-")
                        )])
                        net = float(str(row.get("netPurchase", 0)).replace(",", ""))
                        result[d] = net
                    except Exception:
                        continue
        except Exception as e:
            logger.debug("NSE FII API batch %s→%s: %s", cur, batch_end, e)
        cur = batch_end + timedelta(days=1)
        time.sleep(0.8)
    logger.info("NSE FII API returned %d sessions", len(result))
    return result


def _try_nse_fii_archives(from_date: date, to_date: date) -> dict[date, float]:
    result: dict[date, float] = {}
    session = _nse_session()
    cur = from_date
    fetched = 0
    consecutive_failures = 0
    while cur <= to_date:
        if cur.weekday() < 5:
            url = "https://archives.nseindia.com/content/fo/fii_stats_{}.csv".format(
                cur.strftime("%d%m%Y")
            )
            try:
                resp = session.get(url, timeout=10)
                if resp.status_code == 200 and len(resp.text) > 100:
                    lines = resp.text.strip().split("\n")
                    for line in lines:
                        parts = [p.strip().strip('"') for p in line.split(",")]
                        if len(parts) >= 5 and "derivatives" in parts[0].lower():
                            try:
                                buy  = float(parts[2].replace(",", ""))
                                sell = float(parts[3].replace(",", ""))
                                result[cur] = buy - sell
                                fetched += 1
                                consecutive_failures = 0
                            except Exception:
                                pass
                else:
                    consecutive_failures += 1
            except Exception:
                consecutive_failures += 1
            # Server is blocking — stop early rather than waste minutes
            if consecutive_failures >= 10:
                logger.info("FII archives: 10 consecutive failures — server blocking, stopping early")
                break
        cur += timedelta(days=1)
    logger.info("NSE F&O archives returned %d sessions", len(result))
    return result


def _save_fii_cache(data: dict[date, float]) -> None:
    FII_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with FII_CACHE.open("w", newline="") as f:
        f.write("date,fii_net_fo\n")
        for d in sorted(data.keys()):
            f.write("{},{}\n".format(d.isoformat(), data[d]))
    logger.info("FII cache saved: %d sessions → %s", len(data), FII_CACHE)


def _fii_rolling_net(
    fii_series: dict[date, float],
    as_of: date,
    window: int = FII_WINDOW,
) -> float | None:
    sorted_dates = sorted(d for d in fii_series if d <= as_of)
    if len(sorted_dates) < window:
        return None
    return sum(fii_series[d] for d in sorted_dates[-window:])


def fii_blocked(
    entry_date: date,
    fii_series: dict[date, float],
) -> tuple[bool, str]:
    net = _fii_rolling_net(fii_series, entry_date)
    if net is None:
        return False, ""
    if net < 0:
        return True, "fii_net:{:.0f}".format(net)
    return False, ""


# ── Gate-aware trade simulation wrapper ──────────────────────────────────

def simulate_with_gates(
    entry_date: date,
    expiry_date: date,
    expiry_chain: dict,
    spot_series: dict,
    vix_series: dict,
    vix_pct_series: dict,
    use_vix_gate: bool,
    earnings_calendar: dict[date, list[str]],
    fii_series: dict[date, float] | None,
    use_earnings_gate: bool,
    use_fii_gate: bool,
) -> dict | None:
    if use_earnings_gate and earnings_calendar:
        blocked, reason = earnings_blocked(entry_date, expiry_date, earnings_calendar)
        if blocked:
            return {
                "entry_date":  entry_date,
                "expiry_date": expiry_date,
                "skipped":     True,
                "skip_reason": "earnings_gate: " + reason,
                "vix":         vix_series.get(entry_date),
                "vix_pct":     vix_pct_series.get(entry_date),
            }

    if use_fii_gate and fii_series is not None:
        blocked, reason = fii_blocked(entry_date, fii_series)
        if blocked:
            return {
                "entry_date":  entry_date,
                "expiry_date": expiry_date,
                "skipped":     True,
                "skip_reason": "fii_gate: " + reason,
                "vix":         vix_series.get(entry_date),
                "vix_pct":     vix_pct_series.get(entry_date),
            }

    return simulate_trade(
        entry_date=entry_date,
        expiry_date=expiry_date,
        expiry_chain=expiry_chain,
        spot_series=spot_series,
        vix_series=vix_series,
        vix_pct_series=vix_pct_series,
        use_vix_gate=use_vix_gate,
    )


# ── Variant runner ────────────────────────────────────────────────────────

def run_variant(
    name: str,
    expiry_dates: list[date],
    options_data: dict,
    spot_series: dict,
    vix_series: dict,
    vix_pct_series: dict,
    earnings_calendar: dict[date, list[str]],
    fii_series: dict[date, float] | None,
    use_earnings_gate: bool,
    use_fii_gate: bool,
) -> dict:
    trades = []
    for expiry_date in expiry_dates:
        result = simulate_with_gates(
            entry_date=_entry_target_for_expiry(expiry_date),
            expiry_date=expiry_date,
            expiry_chain=options_data[expiry_date],
            spot_series=spot_series,
            vix_series=vix_series,
            vix_pct_series=vix_pct_series,
            use_vix_gate=True,
            earnings_calendar=earnings_calendar,
            fii_series=fii_series,
            use_earnings_gate=use_earnings_gate,
            use_fii_gate=use_fii_gate,
        )
        if result:
            trades.append(result)

    live_count = sum(1 for t in trades if not t.get("skipped"))
    skip_vix   = sum(1 for t in trades if t.get("skipped") and "VIX gate" in t.get("skip_reason", ""))
    skip_earn  = sum(1 for t in trades if t.get("skipped") and "earnings_gate" in t.get("skip_reason", ""))
    skip_fii   = sum(1 for t in trades if t.get("skipped") and "fii_gate" in t.get("skip_reason", ""))

    logger.info("[%s] %d live, %d vix-skip, %d earn-skip, %d fii-skip",
                name, live_count, skip_vix, skip_earn, skip_fii)

    if live_count < 5:
        return {
            "name": name, "trades": trades,
            "agg": {"error": "insufficient trades: {}".format(live_count)},
            "wf": {}, "mc": {}, "shp": {}, "tier": "INCONCLUSIVE",
            "overrides": ["Insufficient live trades: {}".format(live_count)],
            "live_count": live_count,
            "skip_vix": skip_vix, "skip_earn": skip_earn, "skip_fii": skip_fii,
        }

    agg = aggregate_metrics(trades)
    wf  = walk_forward(trades)
    mc  = monte_carlo(trades)
    shp = bootstrap_sharpe(trades)
    overrides = check_override_conditions(agg, mc, wf)
    tier = determine_tier(agg, wf, mc, overrides)

    return {
        "name": name, "trades": trades,
        "agg": agg, "wf": wf, "mc": mc, "shp": shp,
        "tier": tier, "overrides": overrides,
        "live_count": live_count,
        "skip_vix": skip_vix, "skip_earn": skip_earn, "skip_fii": skip_fii,
    }


# ── Comparison report ─────────────────────────────────────────────────────

def write_comparison_report(
    variants: list[dict],
    fii_available: bool,
    output_path: Path,
    earnings_exact: bool = True,
) -> None:
    lines = [
        "# Nifty Strangle — Earnings/FII Gate Comparison",
        "",
        "**Run date:** {}".format(date.today()),
        "**Criteria doc:** docs/strategy_validation/strangle_earnings_fii_criteria.md",
        "",
    ]

    if not earnings_exact:
        lines += [
            "> **Earnings gate using APPROXIMATE quarterly seasons** (NSE corporate "
            "actions API blocked from server). Results season windows used: Apr-May, "
            "Jul-Aug, Oct-Nov, Jan-Feb. This over-filters vs exact announcement dates — "
            "earnings_only variant removes more trades than it would with exact dates.",
            "",
        ]

    if not fii_available:
        lines += [
            "> **FII gate data unavailable.** Historical NSE FII F&O data could not be "
            "fetched. Per criteria doc override condition 3, FII gate variants are "
            "marked INCONCLUSIVE. Earnings-only results are authoritative.",
            "",
        ]

    lines += [
        "## Variant Summary",
        "",
        "| Variant | Live trades | Earn-skip | FII-skip | WR | WF Sharpe | WF return | "
        "MC P95 DD | Tier |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for v in variants:
        agg = v["agg"]
        wf  = v["wf"]
        mc  = v["mc"]
        if "error" in agg:
            lines.append("| {} | {} | {} | {} | — | — | — | — | {} |".format(
                v["name"], v["live_count"], v["skip_earn"], v["skip_fii"],
                v["tier"],
            ))
            continue
        lines.append(
            "| {} | {} | {} | {} | {:.0%} | {:.3f} | {:.1f}% | {:.1f}% | {} |".format(
                v["name"],
                v["live_count"],
                v["skip_earn"],
                v["skip_fii"],
                agg.get("win_rate", 0),
                wf.get("avg_sharpe", 0),
                wf.get("avg_ann_return_on_margin", 0) * 100,
                mc.get("p95", 0) * 100,
                v["tier"].split(":")[0],
            )
        )

    lines += ["", "## Tier 1 threshold reference", "",
              "WF Sharpe ≥ 1.0 | Ann return ≥ 12% | Win rate ≥ 75% | MC P95 DD ≤ 12% | Trades ≥ 30",
              ""]

    for v in variants:
        agg = v["agg"]
        wf  = v["wf"]
        mc  = v["mc"]
        lines += ["", "---", "", "## Variant: {}".format(v["name"]), ""]
        lines.append("**Verdict:** {}".format(v["tier"]))
        if v["overrides"]:
            lines.append("")
            for o in v["overrides"]:
                lines.append("- OVERRIDE: {}".format(o))
        lines += [
            "",
            "| Metric | Value |",
            "|---|---|",
            "| Live trades | {} |".format(v["live_count"]),
            "| VIX-skipped | {} |".format(v["skip_vix"]),
            "| Earnings-skipped | {} |".format(v["skip_earn"]),
            "| FII-skipped | {} |".format(v["skip_fii"]),
        ]
        if "error" not in agg:
            lines += [
                "| Win rate | {:.1%} |".format(agg.get("win_rate", 0)),
                "| Profit factor | {:.3f} |".format(agg.get("profit_factor", 0)),
                "| Sharpe (annualized) | {:.3f} |".format(agg.get("sharpe_annualized", 0)),
                "| Ann return on margin | {:.1f}% |".format(agg.get("ann_return_on_margin_pct", 0)),
                "| Max DD on margin | {:.1f}% |".format(agg.get("max_drawdown_on_margin_pct", 0)),
                "| WF Sharpe (OOS) | {:.3f} |".format(wf.get("avg_sharpe", 0)),
                "| WF Ann return | {:.1f}% |".format(wf.get("avg_ann_return_on_margin", 0) * 100),
                "| WF consistency | {:.0%} ({}/{}) |".format(
                    wf.get("consistency", 0),
                    wf.get("profitable_windows", 0),
                    wf.get("n_windows", 0),
                ),
                "| MC P95 max DD | {:.1f}% |".format(mc.get("p95", 0) * 100),
            ]
            shp = v.get("shp", {})
            if shp.get("ci_95_low") is not None:
                lines.append(
                    "| Bootstrap Sharpe 95% CI | [{}, {}] |".format(
                        shp["ci_95_low"], shp["ci_95_high"]
                    )
                )

    output_path.write_text("\n".join(lines, encoding='utf-8'), encoding="utf-8")
    logger.info("Comparison report: %s", output_path)


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Nifty strangle earnings/FII gate refinement backtest"
    )
    parser.add_argument("--from", dest="from_date", default="2023-01-01")
    parser.add_argument("--to",   dest="to_date",   default=None)
    parser.add_argument("--poc",          action="store_true",
                        help="Load data normally but run only 20 spread expiries per variant")
    parser.add_argument("--earnings-only", action="store_true",
                        help="Run baseline and earnings-only variants, skip FII")
    parser.add_argument("--fii-only",      action="store_true",
                        help="Run baseline and FII-only variants, skip earnings")
    parser.add_argument("--output-dir",    default="reports/strangle_gates")
    parser.add_argument("--no-cache",      action="store_true",
                        help="Ignore cached earnings/FII data and re-fetch")
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date)
    to_date   = date.fromisoformat(args.to_date) if args.to_date else date.today()

    if args.no_cache:
        EARNINGS_CACHE.unlink(missing_ok=True)
        FII_CACHE.unlink(missing_ok=True)

    logger.info("=== Nifty Strangle — Earnings/FII Gate Validation ===")
    logger.info("Period: %s → %s", from_date, to_date)

    # ── Load market data ──────────────────────────────────────────────

    from mcp_server.db import SessionLocal
    session = SessionLocal()
    try:
        options_data = _load_options_data(session, from_date, to_date)
        spot_series  = _load_spot_from_db(session, from_date, to_date)
        if len(spot_series) < 500:
            logger.info("Sparse DB spot (%d bars), falling back to yfinance...", len(spot_series))
            spot_series = _load_spot_from_yfinance(from_date, to_date)
    finally:
        session.close()

    vix_series     = _load_vix_data(from_date, to_date)
    vix_pct_series = _build_vix_percentiles(vix_series)

    if not spot_series:
        logger.error("No Nifty spot data. Cannot proceed.")
        sys.exit(1)

    all_expiry_dates = sorted(options_data.keys())
    expiry_dates     = _select_weekly_expiries(all_expiry_dates)
    logger.info("Found %d unique weekly expiries", len(expiry_dates))

    if args.poc:
        # Sample 20 evenly spread expiries so we hit different VIX regimes.
        # First 10 are often in low-VIX periods (early 2023) and all get gated.
        n = len(expiry_dates)
        step = max(n // 20, 1)
        expiry_dates = expiry_dates[::step][:20]
        logger.info("POC mode: using 20 evenly-spread expiries (from %d total)", n)

    # ── Load gate data ────────────────────────────────────────────────

    # Fetch earnings slightly before backtest start so expiries at the beginning
    # can check if earnings fall near start of window
    earn_from = from_date - timedelta(days=30)
    earnings_cal, earnings_exact = load_earnings_calendar(earn_from, to_date)
    if not earnings_exact:
        logger.warning("Earnings gate using APPROXIMATE quarterly seasons (NSE API unavailable). "
                       "Gate will over-filter vs exact announcement dates.")

    fii_available = not args.earnings_only
    fii_series: dict[date, float] | None = None
    if fii_available and not args.fii_only:
        fii_series = load_fii_historical(from_date, to_date)
        fii_available = fii_series is not None
    elif args.fii_only:
        fii_series = load_fii_historical(from_date, to_date)
        fii_available = fii_series is not None

    # ── Define which variants to run ──────────────────────────────────

    if args.earnings_only:
        variants_cfg = [
            ("baseline",       False, False),
            ("earnings_only",  True,  False),
        ]
    elif args.fii_only:
        if not fii_available:
            logger.error("FII data unavailable — cannot run --fii-only. "
                         "Check NSE connectivity or provide data/fii_fno_historical.csv")
            sys.exit(1)
        variants_cfg = [
            ("baseline",    False, False),
            ("fii_only",    False, True),
        ]
    else:
        variants_cfg = [
            ("baseline",       False, False),
            ("earnings_only",  True,  False),
            ("fii_only",       False, fii_available),
            ("both_gates",     True,  fii_available),
        ]
        if not fii_available:
            logger.warning("FII data unavailable — fii_only and both_gates variants "
                           "will run without FII gate (INCONCLUSIVE per criteria override)")

    # ── Run all variants ──────────────────────────────────────────────

    results = []
    for variant_name, use_earn, use_fii in variants_cfg:
        logger.info("Running variant: %s", variant_name)
        v = run_variant(
            name=variant_name,
            expiry_dates=expiry_dates,
            options_data=options_data,
            spot_series=spot_series,
            vix_series=vix_series,
            vix_pct_series=vix_pct_series,
            earnings_calendar=earnings_cal,
            fii_series=fii_series,
            use_earnings_gate=use_earn,
            use_fii_gate=use_fii,
        )
        results.append(v)

    # ── Output ────────────────────────────────────────────────────────

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_date_str = date.today().isoformat()
    md_path = output_dir / "strangle_gates_{}.md".format(run_date_str)
    write_comparison_report(results, fii_available, md_path, earnings_exact=earnings_exact)

    # ── Console summary ───────────────────────────────────────────────

    print("\n" + "=" * 72)
    print("NIFTY STRANGLE GATE REFINEMENT — RESULTS")
    print("FII data: {}".format("available" if fii_available else "UNAVAILABLE — FII variants inconclusive"))
    print("=" * 72)
    print("{:<18} {:>7} {:>7} {:>7}  {:>8}  {:>8}  {}".format(
        "Variant", "Live", "E-skip", "F-skip", "WF Sharpe", "WF Ann%", "Tier"
    ))
    print("-" * 72)
    for v in results:
        wf  = v["wf"]
        agg = v["agg"]
        if "error" in agg:
            print("{:<18} {:>7} {:>7} {:>7}  {:>8}  {:>8}  {}".format(
                v["name"], v["live_count"], v["skip_earn"], v["skip_fii"],
                "—", "—", v["tier"],
            ))
        else:
            print("{:<18} {:>7} {:>7} {:>7}  {:>8.3f}  {:>7.1f}%  {}".format(
                v["name"],
                v["live_count"],
                v["skip_earn"],
                v["skip_fii"],
                wf.get("avg_sharpe", 0),
                wf.get("avg_ann_return_on_margin", 0) * 100,
                v["tier"].split(":")[0],
            ))
    print("=" * 72)
    print("Report:", md_path)
    print()


if __name__ == "__main__":
    main()
