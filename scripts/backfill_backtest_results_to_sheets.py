"""
Backfill all backtest results from this session to Google Sheets.

Run once after deploying:
    python scripts/backfill_backtest_results_to_sheets.py

This pushes all TIER_1 / TIER_2 / OVERRIDE verdicts already computed
into the BACKTEST RESULTS tab in Google Sheets.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_server.sheets_sync import log_backtest_result

RESULTS = [
    # ── BB Breakout ───────────────────────────────────────────────────────────
    {
        "strategy": "BB Breakout (RSI>80 + ST + Pivot + BB)",
        "timeframe": "1d", "period": "2021-01-01 to 2026-05-13",
        "universe": "Nifty 500", "trades": 437,
        "cagr": 59.7, "sharpe": 0.89, "max_dd": 19.5, "win_rate": 43.2,
        "verdict": "TIER_2",
        "notes": "4-layer confluence. Equity long only.",
    },
    {
        "strategy": "BB Breakout ATM Call (RSI>80)",
        "timeframe": "1d", "period": "2021-01-01 to 2026-05-13",
        "universe": "Nifty 500", "trades": 247,
        "cagr": 178.0, "sharpe": 1.07, "max_dd": 8.2, "win_rate": 30.4,
        "verdict": "TIER_1",
        "notes": "ATM call options. IV=25%. WinRate gate 25% (options-appropriate).",
    },
    {
        "strategy": "BB Breakout Weekly (RSI>60, revised)",
        "timeframe": "1w", "period": "2021-01-01 to 2026-05-13",
        "universe": "Nifty 500", "trades": 189,
        "cagr": 61.5, "sharpe": 1.07, "max_dd": 15.0, "win_rate": 58.3,
        "verdict": "TIER_1",
        "notes": "Weekly bars. RSI>60 (not 70). TIER_1 validated.",
    },
    {
        "strategy": "BB Breakout 15m (RSI>80)",
        "timeframe": "15m", "period": "60d (yfinance limit)",
        "universe": "Nifty 500 subset", "trades": 52,
        "cagr": 31.2, "sharpe": 0.61, "max_dd": 22.1, "win_rate": 46.2,
        "verdict": "TIER_2",
        "notes": "Intraday 15m. Limited by yfinance 60-day window.",
    },
    {
        "strategy": "BB Breakout 1h (RSI>80, daily ST align)",
        "timeframe": "1h", "period": "700d (yfinance limit)",
        "universe": "Nifty 500 subset", "trades": 8,
        "cagr": 0.0, "sharpe": 0.0, "max_dd": 0.0, "win_rate": 0.0,
        "verdict": "OVERRIDE",
        "notes": "Too restrictive — only 8 trades. Daily ST alignment filter too tight.",
    },
    {
        "strategy": "BB Breakout Bear (Regime: Nifty < 200SMA)",
        "timeframe": "1d", "period": "2020-01-01 to 2026-05-13",
        "universe": "Nifty 500", "trades": 71,
        "cagr": -15.0, "sharpe": -0.3, "max_dd": 45.0, "win_rate": 35.0,
        "verdict": "OVERRIDE",
        "notes": "Permanently closed. Insufficient bear market data 2020-2026.",
    },

    # ── Sector Rotation ───────────────────────────────────────────────────────
    {
        "strategy": "Sector Rotation Top3 (63d momentum, 8 sectors)",
        "timeframe": "monthly", "period": "2021-01-01 to 2026-05-13",
        "universe": "NSE sectors (excl. Bank, Finance)", "trades": 52,
        "cagr": 14.2, "sharpe": 0.89, "max_dd": 27.4, "win_rate": 57.7,
        "verdict": "TIER_2",
        "notes": "Alpha +3.7pp vs Nifty50. Monthly rebalance. First rebalance: 2026-06-02.",
    },

    # ── MWA Individual Scanners ───────────────────────────────────────────────
    {
        "strategy": "MWA: Supertrend (10,3) flip",
        "timeframe": "1d", "period": "2021-01-01 to 2026-05-13",
        "universe": "Nifty 500 (468 symbols)", "trades": 412,
        "cagr": 1.3, "sharpe": 0.07, "max_dd": 39.8, "win_rate": 41.7,
        "verdict": "OVERRIDE",
        "notes": "Standalone. OVERRIDE expected — confluence input to composite MWA score.",
    },
    {
        "strategy": "MWA: MACD (12,26,9) cross",
        "timeframe": "1d", "period": "2021-01-01 to 2026-05-13",
        "universe": "Nifty 500 (468 symbols)", "trades": 685,
        "cagr": 7.7, "sharpe": 0.20, "max_dd": 55.0, "win_rate": 32.0,
        "verdict": "OVERRIDE",
        "notes": "Standalone. OVERRIDE expected — confluence input to composite MWA score.",
    },
    {
        "strategy": "MWA: EMA 9/21 cross",
        "timeframe": "1d", "period": "2021-01-01 to 2026-05-13",
        "universe": "Nifty 500 (468 symbols)", "trades": 528,
        "cagr": 18.5, "sharpe": 0.41, "max_dd": 31.8, "win_rate": 35.2,
        "verdict": "OVERRIDE",
        "notes": "Best standalone input. OVERRIDE expected — confluence input to MWA.",
    },
    {
        "strategy": "MWA: 52-Week High breakout",
        "timeframe": "1d", "period": "2021-01-01 to 2026-05-13",
        "universe": "Nifty 500 (468 symbols)", "trades": 252,
        "cagr": 12.9, "sharpe": 0.31, "max_dd": 31.8, "win_rate": 38.9,
        "verdict": "OVERRIDE",
        "notes": "Standalone. OVERRIDE expected — confluence input to composite MWA score.",
    },

    # ── Pattern Engines (SMC / VSA / Wyckoff / Harmonic) ─────────────────────
    {
        "strategy": "Pattern Engine: SMC",
        "timeframe": "1d", "period": "2021-01-01 to 2026-05-13",
        "universe": "Nifty 500 (483 symbols)", "trades": 410,
        "cagr": 7.5, "sharpe": 0.21, "max_dd": 36.6, "win_rate": 45.4,
        "verdict": "OVERRIDE",
        "notes": "16 sub-detectors. Standalone OVERRIDE — confluence input to MWA.",
    },
    {
        "strategy": "Pattern Engine: VSA",
        "timeframe": "1d", "period": "2021-01-01 to 2026-05-13",
        "universe": "Nifty 500 (483 symbols)", "trades": 398,
        "cagr": 7.6, "sharpe": 0.23, "max_dd": 33.3, "win_rate": 45.7,
        "verdict": "OVERRIDE",
        "notes": "Standalone OVERRIDE — confluence input to MWA composite.",
    },
    {
        "strategy": "Pattern Engine: Wyckoff",
        "timeframe": "1d", "period": "2021-01-01 to 2026-05-13",
        "universe": "Nifty 500 (483 symbols)", "trades": 383,
        "cagr": 4.3, "sharpe": 0.17, "max_dd": 37.5, "win_rate": 48.8,
        "verdict": "OVERRIDE",
        "notes": "Standalone OVERRIDE — confluence input to MWA composite.",
    },
    {
        "strategy": "Pattern Engine: Harmonic",
        "timeframe": "1d", "period": "2021-01-01 to 2026-05-13",
        "universe": "Nifty 500 (483 symbols)", "trades": 314,
        "cagr": 27.9, "sharpe": 0.78, "max_dd": 14.8, "win_rate": 54.1,
        "verdict": "TIER_2",
        "notes": (
            "TIER_2 standalone! Misses TIER_1 by 0.02 Sharpe (0.78 vs 0.80). "
            "Highest WinRate (54.1%) and lowest MaxDD (14.8%) of all 4 engines. "
            "Recommend increasing Harmonic weight in MWA composite from 3.0 to 4.0."
        ),
    },
]


def main():
    ok = 0
    fail = 0
    for r in RESULTS:
        success = log_backtest_result(r)
        if success:
            ok += 1
            print(f"  Logged: {r['strategy']} -> {r['verdict']}")
        else:
            fail += 1
            print(f"  FAILED: {r['strategy']}")

    print(f"\nDone: {ok} logged, {fail} failed.")
    if fail:
        print("Check GOOGLE_SHEETS_CREDENTIALS and GOOGLE_SHEET_ID env vars.")


if __name__ == "__main__":
    main()
