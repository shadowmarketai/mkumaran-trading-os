# 12-Month Cross-Sectional Momentum (Nifty 500) — Pre-committed Decision Criteria

**Date set:** 2026-05-12
**Committed before any validation run:** Yes

---

## Hypothesis

Nifty 500 stocks that outperformed their peers over the trailing 12 months continue to
outperform over the next 1 month (cross-sectional momentum). Buying the top quintile
(100 of 500 stocks) and rebalancing monthly generates positive alpha over the equal-weight
universe and the Nifty 50 index, net of Indian equity delivery costs.

**Known limitation:** Universe is the *current* Nifty 500 (data/nifty500.json). Survivorship
bias applies — stocks that were delisted or dropped from the index between 2021-2026 are
excluded. True forward alpha will be ~2-3 percentage points lower than backtest reports.
Tier thresholds are set high to account for this.

---

## Strategy Parameters (do not change after committing)

| Parameter | Value |
|---|---|
| Universe | Nifty 500 (data/nifty500.json, current composition) |
| Ranking signal | Trailing 12-month price return (252 trading days) |
| Skip period | None (straightforward trailing 12m) |
| Portfolio | Top quintile = top 100 stocks by ranking |
| Weighting | Equal weight within portfolio |
| Rebalance | Monthly (first trading day of each calendar month) |
| Direction | Long-only (no short selling) |
| Simulation period | 2021-01-01 → 2026-05-09 (~64 months, ~64 rebalances) |
| Portfolio size | ₹10,00,000 (₹10 lakhs) for cost calculation |

---

## Cost Model (Indian equity delivery)

| Cost | Rate |
|---|---|
| Brokerage | ₹20 flat per order (Zerodha model) |
| STT | 0.1% on sell side only |
| Exchange + SEBI | 0.00345% per side |
| GST | 18% on brokerage + exchange charge |
| Stamp duty | 0.015% on buy side |
| Slippage | 0.05% per side (Nifty 500 mid-large caps) |

---

## Minimum data requirements

- Stock must have ≥ 13 months of clean daily close data to be eligible for ranking at any
  given rebalance date.
- Universe of eligible stocks must be ≥ 50 at each rebalance to proceed with ranking.
- If fewer than 50 stocks are eligible at a given rebalance, skip that rebalance (hold prior
  portfolio and record zero turnover for that month).

---

## Benchmark

- **Primary:** Equal-weight portfolio of all eligible universe stocks at each rebalance.
- **Secondary:** Nifty 50 (^NSEI, yfinance) — widely used practitioner benchmark.

---

## Decision Criteria

### Tier 1 — PROCEED: build live monthly rebalancer

- Net CAGR > benchmark CAGR + **7%** (high threshold accounts for 2-3% survivorship bias)
- Annualized Sharpe ratio (monthly returns) > **0.8**
- Maximum portfolio drawdown < **40%**
- Win rate (months portfolio excess return > 0) > **55%**

### Tier 2 — PROCEED WITH CAUTION: paper trade 3 months, then re-evaluate

- Net CAGR in range [benchmark + 3%, benchmark + 7%)
- Annualized Sharpe 0.5 – 0.8
- Maximum drawdown < 50%
- Win rate > 50%

### OVERRIDE — HYPOTHESIS DISPROVEN

- Net CAGR ≤ benchmark CAGR + 3%, OR
- Sharpe ≤ 0.5, OR
- Max drawdown ≥ 50%

If OVERRIDE: note the result, explore factor combinations (momentum + quality, momentum +
low-volatility) in a future session rather than re-running momentum alone.

---

## Permitted post-result exploration (Tier 2 only, one iteration)

If Tier 2 result: may test ONE alternative — "12-month momentum with 1-month skip" (use
trailing return from t-252 days to t-22 days instead of t-252 to t). No further iterations
permitted after that.

---

_Criteria committed 2026-05-12, before any validation run._
