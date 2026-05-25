#!/usr/bin/env python
"""
Monthly momentum portfolio rebalancer — CLI entry point.

Usage:
    python scripts/run_monthly_rebalancer.py
    python scripts/run_monthly_rebalancer.py --portfolio-value 1000000
    python scripts/run_monthly_rebalancer.py --dry-run
    python scripts/run_monthly_rebalancer.py --portfolio-value 500000 --date 2026-06-01

The rebalancer:
  - Loads Nifty 500 universe from data/nifty500.json
  - Fetches ~14 months of daily prices via yfinance (batches of 50)
  - Ranks by pure 12-month trailing return (matches validated backtest)
  - Takes top 20% of stocks with >= 200 data points
  - Diffs against data/momentum_portfolio_live.json for ENTER/EXIT/HOLD
  - Prints the plan to stdout
  - Saves new state unless --dry-run

Set MOMENTUM_PORTFOLIO_VALUE=<INR> in .env (default: 500000).
"""

import logging
import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

from mcp_server.momentum_rebalancer import _cli_main

if __name__ == "__main__":
    _cli_main()
