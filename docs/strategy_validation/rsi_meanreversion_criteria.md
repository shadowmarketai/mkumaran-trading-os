# RSI Mean-Reversion (Nifty 100) — Pre-committed Decision Criteria

**Date set:** 2026-05-12
**Committed before any validation run:** Yes

---

## Hypothesis

When a Nifty 100 stock becomes deeply oversold (RSI-14 drops below 30), it tends to
bounce back toward equilibrium within 10 trading days. Buying these oversold conditions
and exiting on mean-reversion or a time stop generates positive alpha over the Nifty 50,
net of full Indian equity delivery costs.

---

## Strategy Parameters (do not change after committing)

| Parameter | Value |
|---|---|
| Universe | Nifty 100 (stocks with ≥ 750 days clean data in ohlcv_cache ≈ large-cap filter) |
| RSI period | 14 (Wilder's smoothing) |
| Entry signal | RSI(14) crosses below 30 (first day it goes under) |
| Entry price | Close of signal day |
| Exit rule 1 | RSI(14) > 50 (mean reversion complete) |
| Exit rule 2 | 10 trading days elapsed (time stop) |
| Exit rule 3 | -7% from entry price (hard stop loss) |
| Exit priority | Whichever triggers first |
| Max concurrent positions | 5 (across all stocks) |
| Position size | ₹1,00,000 per trade (fixed) |
| Long-only | Yes |
| Simulation period | 2021-01-01 → 2026-05-09 |
| Benchmark | Nifty 50 (^NSEI, buy-and-hold) |

---

## Cost Model (Indian equity delivery)

| Cost | Rate |
|---|---|
| Brokerage | ₹20 flat per order |
| STT | 0.1% on sell side |
| Exchange + SEBI | 0.00345% per side |
| GST | 18% on brokerage + exchange |
| Stamp duty | 0.015% on buy side |
| Slippage | 0.05% per side |

---

## Signal generation rule

A signal fires on day T when:
- RSI(14) on day T < 30 AND RSI(14) on day T-1 ≥ 30 (first day crossing below 30)
  (prevents consecutive entries on the same stock during a prolonged oversold period)
- Stock is not already in the active portfolio

If more signals fire than available position slots: rank by RSI ascending (most oversold
gets priority); fill up to MAX_CONCURRENT positions.

---

## Decision Criteria

### Tier 1 — PROCEED: build live RSI scanner + Telegram alerts

- Total trades ≥ 50
- CAGR ≥ 15% net of costs
- Annualized Sharpe (trade returns) ≥ 0.8
- Max drawdown ≤ 25%
- Win rate ≥ 55%

### Tier 2 — PROCEED WITH CAUTION: manual watchlist only, no automation

- Total trades ≥ 30
- CAGR ≥ 8%
- Sharpe ≥ 0.5
- Max drawdown ≤ 35%
- Win rate ≥ 50%

### OVERRIDE — HYPOTHESIS DISPROVEN

- Total trades < 30, OR
- CAGR < 8%, OR
- Sharpe < 0.5, OR
- Max drawdown > 35%

If OVERRIDE: note the result. May explore RSI + trend-filter combination (RSI < 30 only
when stock is above its 200-day moving average) in a later session.

---

_Criteria committed 2026-05-12, before any validation run._
