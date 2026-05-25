"""
MKUMARAN Trading OS — Diagnostic 1: Universe Characteristics vs Pipeline PF

Answers: what structural feature separates the 7 profitable tickers from the 83 losers?

Takes PF scores from the production pipeline validation run, then fetches
ticker characteristics from yfinance/NSE, computes correlations, and
prints a ranked table + correlation matrix.

The goal is to find a RULE (not a ticker list) that predicts PF >= 1.0.
That rule becomes the universe filter.

Usage
─────
    python scripts/diagnose_universe.py

Outputs
───────
    reports/universe_diagnostics_<date>.md   — correlation table + per-ticker data
    Stdout: key findings in plain English
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger("diagnose")


# ── PF scores from production pipeline validation run 2026-04-29 ────
# Source: scripts/validate_production_pipeline.py full run.
# DO NOT modify — these are the measured outcomes, not parameters.
TICKER_PF: dict[str, float] = {
    "HDFCBANK": 1.68, "FEDERALBNK": 1.34, "RELIANCE": 1.32, "WIPRO": 1.23,
    "CESC": 1.18, "MOTHERSON": 1.02, "DRREDDY": 1.01, "BOSCHLTD": 0.99,
    "BERGEPAINT": 0.93, "AUBANK": 0.92, "TORNTPHARM": 0.90, "CANBK": 0.88,
    "INFY": 0.86, "CHOLAFIN": 0.86, "BAJAJ-AUTO": 0.85, "TORNTPOWER": 0.85,
    "PNB": 0.83, "BRITANNIA": 0.82, "BAJAJFINSV": 0.79, "AXISBANK": 0.72,
    "APOLLOHOSP": 0.71, "BIOCON": 0.71, "SBIN": 0.70, "MARICO": 0.70,
    "ONGC": 0.69, "ULTRACEMCO": 0.68, "CIPLA": 0.67, "PETRONET": 0.67,
    "BHARTIARTL": 0.66, "TECHM": 0.66, "M&M": 0.66, "IGL": 0.66,
    "TATASTEEL": 0.65, "HINDALCO": 0.65, "BPCL": 0.64, "BANKBARODA": 0.64,
    "ABB": 0.63, "ADANIENT": 0.62, "GODREJCP": 0.62, "BANDHANBNK": 0.58,
    "POWERGRID": 0.57, "HDFCLIFE": 0.57, "ACC": 0.57, "MUTHOOTFIN": 0.56,
    "IRCTC": 0.55, "GRASIM": 0.54, "HEROMOTOCO": 0.54, "PGHH": 0.54,
    "CONCOR": 0.53, "NTPC": 0.52, "GUJGASLTD": 0.52, "TCS": 0.51,
    "BAJFINANCE": 0.50, "ASIANPAINT": 0.49, "TITAN": 0.47, "HCLTECH": 0.47,
    "DABUR": 0.47, "NESTLEIND": 0.45, "DMART": 0.45, "ICICIBANK": 0.44,
    "ALKEM": 0.44, "DELHIVERY": 0.44, "JSWSTEEL": 0.43, "DIVISLAB": 0.42,
    "RBLBANK": 0.41, "AUROPHARMA": 0.40, "ATGL": 0.40, "PIDILITIND": 0.39,
    "KOTAKBANK": 0.38, "IDFCFIRSTB": 0.38, "IPCALAB": 0.37, "LT": 0.34,
    "HAVELLS": 0.34, "SUNPHARMA": 0.33, "TVSMOTOR": 0.33, "SBILIFE": 0.32,
    "ADANIPORTS": 0.31, "AMBUJACEM": 0.31, "COALINDIA": 0.30, "MGL": 0.30,
    "SHRIRAMFIN": 0.25, "TATACONSUM": 0.24, "SIEMENS": 0.24, "MARUTI": 0.23,
    "COLPAL": 0.21, "ADANIGREEN": 0.21, "EICHERMOT": 0.18, "LUPIN": 0.16,
    "ICICIGI": 0.09, "INDUSINDBK": 0.07,
}

YF_SUFFIX = ".NS"


def _yf_ticker(ticker: str) -> str:
    """Map NSE symbol to yfinance ticker."""
    overrides = {
        "M&M": "M&M.NS",
        "BAJAJ-AUTO": "BAJAJ-AUTO.NS",
        "MCDOWELL-N": "MCDOWELL-N.NS",
    }
    return overrides.get(ticker, f"{ticker}{YF_SUFFIX}")


def fetch_characteristics(tickers: list[str]):
    """Fetch market cap, sector, beta, ADV, volatility for each ticker."""
    import yfinance as yf
    import pandas as pd
    import numpy as np

    rows = []
    for ticker in tickers:
        yf_sym = _yf_ticker(ticker)
        try:
            obj = yf.Ticker(yf_sym)
            info = obj.info or {}

            market_cap_cr = (info.get("marketCap") or 0) / 1e7  # → crores
            sector = info.get("sector", "Unknown")
            beta = info.get("beta") or float("nan")
            # Fetch 1-year daily close for volatility
            hist = obj.history(period="3y", auto_adjust=True)
            if hist is not None and len(hist) >= 50:
                returns = hist["Close"].pct_change().dropna()
                ann_vol = float(returns.std() * np.sqrt(252) * 100)  # %
                avg_daily_vol_cr = float(
                    (hist["Close"] * hist["Volume"]).mean() / 1e7
                )  # average daily turnover in crores
            else:
                ann_vol = float("nan")
                avg_daily_vol_cr = float("nan")

            rows.append({
                "ticker": ticker,
                "market_cap_cr": round(market_cap_cr, 0),
                "sector": sector,
                "beta": round(beta, 2) if not pd.isna(beta) else None,
                "ann_vol_pct": round(ann_vol, 1) if not pd.isna(ann_vol) else None,
                "adv_cr": round(avg_daily_vol_cr, 1) if not pd.isna(avg_daily_vol_cr) else None,
                "pf": TICKER_PF.get(ticker),
                "profitable": 1 if TICKER_PF.get(ticker, 0) >= 1.0 else 0,
            })
            logger.info("  %s: mcap=₹%.0fCr sector=%s vol=%.1f%%", ticker, market_cap_cr, sector, ann_vol)
        except Exception as e:
            logger.warning("  %s: failed (%s)", ticker, e)
            rows.append({"ticker": ticker, "pf": TICKER_PF.get(ticker), "profitable": 0})

    return pd.DataFrame(rows)


def compute_correlations(df) -> dict[str, float]:
    """Pearson correlation of each numeric feature vs PF."""
    features = ["market_cap_cr", "beta", "ann_vol_pct", "adv_cr"]
    corrs = {}
    for feat in features:
        if feat in df.columns:
            clean = df[["pf", feat]].dropna()
            if len(clean) >= 10:
                corrs[feat] = round(float(clean["pf"].corr(clean[feat])), 3)
    return corrs


def sector_analysis(df):
    """Mean PF and profitable rate by sector."""
    import pandas as pd
    if "sector" not in df.columns:
        return pd.DataFrame()
    result = (
        df.groupby("sector")
        .agg(
            mean_pf=("pf", "mean"),
            profitable_count=("profitable", "sum"),
            ticker_count=("ticker", "count"),
        )
        .reset_index()
    )
    result["profitable_pct"] = (result["profitable_count"] / result["ticker_count"] * 100).round(0)
    result["mean_pf"] = result["mean_pf"].round(3)
    return result.sort_values("mean_pf", ascending=False)


def find_rule(df) -> dict:
    """Find the simplest threshold rule that separates profitable from losing tickers.

    Tests: market_cap > X, ann_vol < Y, adv_cr > Z.
    Returns the rule with the best F1 on the in-sample data (for reference only —
    do NOT use this to select the validation universe without out-of-sample testing).
    """
    import numpy as np

    best = {"f1": 0.0, "rule": None, "profitable_captured": 0, "total_predicted": 0}
    clean = df.dropna(subset=["market_cap_cr", "ann_vol_pct", "adv_cr", "profitable"])

    mcap_thresholds = np.percentile(clean["market_cap_cr"].dropna(), [25, 50, 75])
    vol_thresholds = np.percentile(clean["ann_vol_pct"].dropna(), [25, 50, 75])
    for mcap_min in mcap_thresholds:
        for vol_max in vol_thresholds:
            mask = (clean["market_cap_cr"] >= mcap_min) & (clean["ann_vol_pct"] <= vol_max)
            predicted = clean[mask]
            if len(predicted) == 0:
                continue
            tp = (predicted["profitable"] == 1).sum()
            fp = (predicted["profitable"] == 0).sum()
            fn = ((~mask) & (clean["profitable"] == 1)).sum()
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            if f1 > best["f1"]:
                best = {
                    "f1": round(f1, 3),
                    "rule": f"market_cap ≥ ₹{mcap_min:,.0f}Cr AND ann_vol ≤ {vol_max:.1f}%",
                    "rule_dict": {"mcap_min_cr": mcap_min, "vol_max_pct": vol_max},
                    "profitable_captured": int(tp),
                    "total_profitable": int(clean["profitable"].sum()),
                    "total_predicted": int(len(predicted)),
                    "precision": round(precision, 3),
                    "recall": round(recall, 3),
                }
    return best


def write_report(df, corrs: dict, sector_df, rule: dict, output_path: Path) -> None:

    lines = [
        f"# Universe Diagnostic — {date.today()}",
        "",
        "## Correlations: ticker characteristics vs Profit Factor",
        "",
        "Pearson correlation coefficient (−1 to +1). Positive = feature predicts higher PF.",
        "",
        "| Feature | Correlation with PF | Interpretation |",
        "|---|---|---|",
    ]

    interp = {
        "market_cap_cr": "Larger stocks → better signals",
        "beta": "Higher beta → worse signals (more noise)",
        "ann_vol_pct": "Higher volatility → worse signals",
        "adv_cr": "Higher daily turnover → better signals",
    }
    for feat, corr in sorted(corrs.items(), key=lambda x: -abs(x[1])):
        lines.append(f"| {feat} | {corr:+.3f} | {interp.get(feat, '')} |")

    lines += [
        "",
        "## Sector analysis",
        "",
        "| Sector | Mean PF | Profitable tickers | Total tickers | Profitable % |",
        "|---|---|---|---|---|",
    ]
    if not sector_df.empty:
        for _, row in sector_df.iterrows():
            lines.append(
                f"| {row['sector']} | {row['mean_pf']:.3f} "
                f"| {int(row['profitable_count'])} | {int(row['ticker_count'])} "
                f"| {int(row['profitable_pct'])}% |"
            )

    lines += [
        "",
        "## Best simple rule (in-sample only — requires out-of-sample validation)",
        "",
        f"**Rule:** {rule.get('rule', 'Could not determine')}",
        f"**F1 score:** {rule.get('f1', 0):.3f}",
        f"**Precision:** {rule.get('precision', 0):.3f} (of tickers predicted profitable, this fraction are)",
        f"**Recall:** {rule.get('recall', 0):.3f} (of actual profitable tickers, this fraction are captured)",
        f"**Profitable tickers captured:** {rule.get('profitable_captured', 0)}/{rule.get('total_profitable', 0)}",
        f"**Tickers in rule-filtered universe:** {rule.get('total_predicted', 0)}/90",
        "",
        "⚠️ This rule was found on the SAME data used for PF measurement.",
        "It will overfit. Run Diagnostic 2 to test on out-of-sample tickers before using it.",
        "",
        "## Full per-ticker data (sorted by PF)",
        "",
        "| Ticker | PF | Market Cap (₹Cr) | Sector | Ann Vol % | ADV (₹Cr) | Beta |",
        "|---|---|---|---|---|---|---|",
    ]

    for _, row in df.sort_values("pf", ascending=False).iterrows():
        pf_str = f"{row['pf']:.2f}" if row.get("pf") is not None else "—"
        mc = f"{row['market_cap_cr']:,.0f}" if row.get("market_cap_cr") else "—"
        vol = f"{row['ann_vol_pct']:.1f}" if row.get("ann_vol_pct") else "—"
        adv = f"{row['adv_cr']:.1f}" if row.get("adv_cr") else "—"
        beta = f"{row['beta']:.2f}" if row.get("beta") else "—"
        sector = row.get("sector", "—")
        lines.append(
            f"| {row['ticker']} | {pf_str} | {mc} | {sector} | {vol} | {adv} | {beta} |"
        )

    output_path.write_text("\n".join(lines, encoding='utf-8'), encoding="utf-8")
    logger.info("Report → %s", output_path)


def main() -> None:

    Path("reports").mkdir(exist_ok=True)

    tickers = list(TICKER_PF.keys())
    logger.info("Fetching characteristics for %d tickers...", len(tickers))

    df = fetch_characteristics(tickers)

    corrs = compute_correlations(df)
    sector_df = sector_analysis(df)
    rule = find_rule(df)

    # ── Print key findings ─────────────────────────────────────────
    print("\n" + "=" * 60)
    print("DIAGNOSTIC 1 — UNIVERSE CHARACTERISTICS vs PF")
    print("=" * 60)

    print("\nCorrelations with Profit Factor:")
    for feat, corr in sorted(corrs.items(), key=lambda x: -abs(x[1])):
        direction = "↑ predicts higher PF" if corr > 0 else "↑ predicts lower PF"
        print(f"  {feat:<20} {corr:+.3f}  ({direction})")

    print("\nSector breakdown (mean PF):")
    if not sector_df.empty:
        for _, row in sector_df.iterrows():
            print(f"  {row['sector']:<35} PF={row['mean_pf']:.3f}  ({int(row['profitable_count'])}/{int(row['ticker_count'])} profitable)")

    print("\nBest simple rule (in-sample — requires out-of-sample validation before use):")
    print(f"  {rule.get('rule', 'not found')}")
    print(f"  F1={rule.get('f1', 0):.3f}, captures {rule.get('profitable_captured', 0)}/{rule.get('total_profitable', 0)} profitable tickers")
    print(f"  Universe size: {rule.get('total_predicted', 0)} tickers")

    print("\nTop 10 tickers (PF vs key features):")
    top10 = df.sort_values("pf", ascending=False).head(10)
    for _, row in top10.iterrows():
        print(
            f"  {row['ticker']:<15} PF={row.get('pf', 0):.2f}  "
            f"mcap=₹{row.get('market_cap_cr', 0):,.0f}Cr  "
            f"vol={row.get('ann_vol_pct', 0):.1f}%  "
            f"ADV=₹{row.get('adv_cr', 0):.1f}Cr"
        )

    print("\nBottom 10 tickers:")
    bot10 = df.sort_values("pf").head(10)
    for _, row in bot10.iterrows():
        print(
            f"  {row['ticker']:<15} PF={row.get('pf', 0):.2f}  "
            f"mcap=₹{row.get('market_cap_cr', 0):,.0f}Cr  "
            f"vol={row.get('ann_vol_pct', 0):.1f}%  "
            f"ADV=₹{row.get('adv_cr', 0):.1f}Cr"
        )
    print("=" * 60 + "\n")

    today_str = date.today().isoformat()
    output_path = Path("reports") / f"universe_diagnostics_{today_str}.md"
    write_report(df, corrs, sector_df, rule, output_path)
    print(f"\nFull report: {output_path}")


if __name__ == "__main__":
    main()
