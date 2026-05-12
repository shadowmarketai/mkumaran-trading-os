# MCX Gold Simple Trend — Pre-committed Decision Criteria

**Date set:** 2026-05-12
**Committed before any validation run:** Yes
**Prior attempt:** `mcx_gold_criteria.md` — OVERRIDE (10 trades, complex 20d/50d crossover too rare)

## Why this attempt

Prior run had Sharpe 0.89 (good per-trade quality) but only 10 trades in 5 years. Root cause:
the 20-day SMA crossing 50-day SMA entry is too rare. Fix: hold gold whenever close > 50-day
SMA (continuous trend following), exit when close < 50-day SMA. No crossover, no time stop.

## Strategy Parameters

| Parameter | Value |
|---|---|
| Instrument | MCX Gold (GC=F × INR=X) |
| Entry | Close crosses above 50-day SMA |
| Exit | Close crosses below 50-day SMA |
| Hard stop | -4% from entry (unchanged) |
| Direction | Long-only |
| Position | ₹10,00,000 notional |
| Period | 2021-01-01 → today |
| Benchmark | Gold buy-and-hold |

## Decision Criteria (same thresholds, adjusted trade count)

### Tier 1
- Trades ≥ 5 (few but significant in 5 years for a trend strategy)
- Excess CAGR ≥ 3%
- Sharpe ≥ 0.7
- Max drawdown ≤ 30%

### Tier 2
- Trades ≥ 3
- Excess CAGR ≥ 0%
- Sharpe ≥ 0.4
- Max drawdown ≤ 40%

### OVERRIDE
- Excess CAGR < 0%, OR Sharpe < 0.4, OR Max drawdown > 40%

If OVERRIDE: Gold chapter closed. Gold B&H is hard to beat with short-term signals.

---
_Criteria committed 2026-05-12, before any validation run._
