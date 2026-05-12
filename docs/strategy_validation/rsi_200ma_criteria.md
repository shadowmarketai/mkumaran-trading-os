# RSI Mean-Reversion + 200-Day MA Filter — Pre-committed Decision Criteria

**Date set:** 2026-05-12
**Committed before any validation run:** Yes
**Prior attempt:** `rsi_meanreversion_criteria.md` — OVERRIDE (WinRate 23.8%, avg -3.36%)

---

## Why this attempt exists

The plain RSI < 30 strategy failed with 23.8% win rate — stocks kept falling after the
signal. Root cause: catching falling knives. 42% of trades hit the -7% stop.

**Key insight from the top 10 trades:** GPIL, PERSISTENT, JSL, GRANULES — all were in
structural uptrends (above 200-day MA) when they dipped to RSI < 30. Those bounced.
The bottom trades (March 2026 market selloff) were stocks in downtrends — they had no
base to bounce from.

**This attempt adds a 200-day MA filter:** only enter RSI < 30 when the stock is ABOVE
its 200-day simple moving average. This filters "strong stock having a pullback" from
"weak stock continuing its downtrend."

---

## Strategy Parameters (do not change after committing)

| Parameter | Value | Change vs prior |
|---|---|---|
| RSI period | 14 | Same |
| Entry signal | RSI(14) < 30 crossover | Same |
| **200-day MA filter** | Stock close > 200-day SMA at entry | NEW |
| Entry price | Close of signal day | Same |
| Exit rule 1 | RSI(14) > 50 | Same |
| Exit rule 2 | 10 trading days elapsed | Same |
| Exit rule 3 | -7% from entry (hard stop) | Same |
| Max concurrent | 5 | Same |
| Position size | ₹1,00,000 per trade | Same |
| Universe | Stocks with ≥ 750 days data | Same |
| Period | 2021-01-01 → today | Same |

---

## Decision Criteria

### Tier 1 — PROCEED: build live RSI+MA scanner + Telegram alerts

- Total trades ≥ 30 (fewer expected due to stricter filter)
- CAGR ≥ 12% net
- Sharpe ≥ 0.8
- Max drawdown ≤ 25%
- Win rate ≥ 55%

### Tier 2 — PROCEED WITH CAUTION: manual watchlist

- Total trades ≥ 20
- CAGR ≥ 6%
- Sharpe ≥ 0.5
- Max drawdown ≤ 35%
- Win rate ≥ 50%

### OVERRIDE — HYPOTHESIS DISPROVEN (FINAL)

- Total trades < 20, OR
- CAGR < 6%, OR
- Sharpe < 0.5, OR
- Max drawdown > 35%

If OVERRIDE: RSI mean-reversion chapter closed. Do not retest with further filters.

---

_Criteria committed 2026-05-12, before any validation run._
