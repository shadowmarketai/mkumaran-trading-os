"""
Nifty 50 Cointegration Screener

Runs Engle-Granger cointegration on all ~1225 Nifty 50 pairs (50 C 2).
Outputs a ranked table — use this to pick the validation universe instead
of sector-based selection.

Usage:
    python scripts/screen_nifty50_pairs.py
    python scripts/screen_nifty50_pairs.py --top 20 --p-threshold 0.05
    python scripts/screen_nifty50_pairs.py --start 2023-01-01  # shorter window

After this, re-run pairs validation on the top cointegrated pairs:
    python scripts/validate_pairs_trading.py --pair RELIANCE,ONGC
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from itertools import combinations
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("coint_screen")

NIFTY50 = [
    "RELIANCE", "TCS", "HDFCBANK", "BHARTIARTL", "ICICIBANK",
    "INFY", "SBIN", "LT", "HINDUNILVR", "BAJFINANCE",
    "KOTAKBANK", "ITC", "AXISBANK", "M&M", "TITAN",
    "MARUTI", "ULTRACEMCO", "TATAMOTORS", "SUNPHARMA", "WIPRO",
    "HCLTECH", "ADANIPORTS", "TATASTEEL", "JSWSTEEL", "ASIANPAINT",
    "NTPC", "POWERGRID", "BAJAJFINSV", "ONGC", "COALINDIA",
    "DRREDDY", "CIPLA", "DIVISLAB", "GRASIM", "HINDALCO",
    "TRENT", "HEROMOTOCO", "BAJAJ-AUTO", "EICHERMOT", "BPCL",
    "INDUSINDBK", "TECHM", "NESTLEIND", "BRITANNIA", "SHRIRAMFIN",
    "APOLLOHOSP", "LTIM", "TATACONSUM", "IOC", "BERGEPAINT",
]


def _fetch_prices(symbols: list[str], start: str, end: str) -> dict[str, dict]:
    """Load closes from ohlcv_cache; yfinance for any gaps."""
    import pandas as pd
    import yfinance as yf
    from sqlalchemy import text

    from mcp_server.db import engine

    prices: dict[str, dict] = {}

    with engine.connect() as conn:
        for sym in symbols:
            rows = conn.execute(
                text(
                    "SELECT bar_date, close FROM ohlcv_cache "
                    "WHERE ticker=:s AND interval='1d' "
                    "AND bar_date BETWEEN :s0 AND :e "
                    "AND close IS NOT NULL AND close > 0 "
                    "ORDER BY bar_date"
                ),
                {"s": sym, "s0": start, "e": end},
            ).fetchall()
            if len(rows) >= 200:
                prices[sym] = {r.bar_date: float(r.close) for r in rows}

    missing = [s for s in symbols if s not in prices]
    if missing:
        logger.info("yfinance: fetching %d symbols not in DB...", len(missing))
        yf_syms = [s + ".NS" for s in missing]
        try:
            raw = yf.download(
                yf_syms,
                start=start,
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if not raw.empty:
                for sym, yf_sym in zip(missing, yf_syms):
                    try:
                        closes = (
                            raw["Close"][yf_sym].dropna()
                            if isinstance(raw.columns, pd.MultiIndex)
                            else raw["Close"].dropna()
                        )
                        if len(closes) >= 200:
                            prices[sym] = {d.date(): float(c) for d, c in closes.items()}
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("yfinance batch failed: %s", e)

    logger.info(
        "%d/%d symbols with ≥200 bars",
        len(prices),
        len(symbols),
    )
    return prices


def _coint_p(ya: list[float], yb: list[float]) -> float:
    import numpy as np
    from statsmodels.tsa.stattools import coint

    _, p, _ = coint(np.array(ya), np.array(yb))
    return float(p)


def main() -> None:
    parser = argparse.ArgumentParser(description="Nifty 50 cointegration screener")
    parser.add_argument("--top", type=int, default=25,
                        help="Top N pairs to display (default 25)")
    parser.add_argument("--p-threshold", type=float, default=0.10,
                        help="p-value cutoff for candidate list (default 0.10)")
    parser.add_argument("--start", default="2021-01-01",
                        help="Start date (default 2021-01-01)")
    args = parser.parse_args()
    end = date.today().isoformat()

    logger.info(
        "Loading prices for %d symbols: %s → %s",
        len(NIFTY50), args.start, end,
    )
    prices = _fetch_prices(NIFTY50, args.start, end)
    available = list(prices.keys())

    pairs = list(combinations(available, 2))
    logger.info("Testing %d pairs...", len(pairs))

    results: list[tuple[float, str, str, int]] = []
    for i, (a, b) in enumerate(pairs):
        common = sorted(set(prices[a]) & set(prices[b]))
        if len(common) < 200:
            continue
        ya = [prices[a][d] for d in common]
        yb = [prices[b][d] for d in common]
        try:
            p = _coint_p(ya, yb)
            results.append((p, a, b, len(common)))
        except Exception:
            pass
        if (i + 1) % 200 == 0:
            logger.info("  %d/%d pairs done ...", i + 1, len(pairs))

    results.sort(key=lambda x: x[0])

    print()
    print("=" * 66)
    print("NIFTY 50 COINTEGRATION SCREEN")
    print(f"Period: {args.start} → {end}  |  {len(results)} pairs tested")
    print("=" * 66)
    print(f"{'Pair':<28} {'p-value':>8}  {'Bars':>5}  {'Signal':>12}")
    print("-" * 66)
    candidates: list[str] = []
    for rank, (p, a, b, n) in enumerate(results[: args.top], 1):
        tag = "★ p<0.05" if p < 0.05 else ("~ p<0.10" if p < 0.10 else "")
        print(f"{rank:>2}. {a+'/'+b:<26} {p:>8.4f}  {n:>5}  {tag:>12}")
        if p < args.p_threshold:
            candidates.append(f"{a},{b}")
    print("=" * 66)

    sig = sum(1 for p, *_ in results if p < 0.05)
    marg = sum(1 for p, *_ in results if p < 0.10)
    print(f"\nOf {len(results)} pairs:  p<0.05: {sig}   p<0.10: {marg}")

    if candidates:
        print(f"\nTop {len(candidates)} candidates (p < {args.p_threshold}):")
        print("Run each pair through the full walk-forward validator:")
        for cp in candidates[:10]:
            a, b = cp.split(",")
            print(f"  python scripts/validate_pairs_trading.py --pair {a},{b}")

    out = Path("reports/nifty50_coint_screen.csv")
    out.parent.mkdir(exist_ok=True)
    with open(out, "w") as f:
        f.write("rank,symbol_a,symbol_b,coint_p,bars\n")
        for rank, (p, a, b, n) in enumerate(results, 1):
            f.write(f"{rank},{a},{b},{p:.6f},{n}\n")
    logger.info("Full results → %s", out)


if __name__ == "__main__":
    main()
