# MCX Gold Momentum — Pre-committed Decision Criteria

**Date set:** 2026-05-12
**Committed before any validation run:** Yes

---

## Hypothesis

Gold (MCX) trends persistently in INR terms due to combined USD/gold momentum and
INR depreciation. A simple moving average crossover (close > 50-day SMA = trend up)
filters the direction, with entry on a pullback (RSI < 45 while above SMA) to avoid
chasing. Exits via trailing stop or time limit.

---

## Strategy Parameters

| Parameter | Value |
|---|---|
| Instrument | MCX Gold futures (yfinance: GC=F × INR=X for INR price) |
| Trend filter | 50-day SMA (only long when close > 50-day SMA) |
| Entry | Close > 50-day SMA AND (close crosses above 20-day SMA OR RSI < 45) |
| Exit rule 1 | Close < 20-day trailing low |
| Exit rule 2 | -4% hard stop from entry |
| Exit rule 3 | 30 trading days max hold |
| Direction | Long-only |
| Position size | ₹10,00,000 notional per trade |
| Period | 2021-01-01 → today |
| Benchmark | MCX Gold buy-and-hold |

---

## Cost Model (MCX futures)

| Cost | Rate |
|---|---|
| Brokerage | ₹20 flat per order |
| CTT (commodity transaction tax) | 0.01% on sell side |
| Exchange | 0.003% per side |
| GST | 18% on brokerage + exchange |
| Slippage | 0.05% per side |

---

## Decision Criteria

### Tier 1 — PROCEED: add Gold signal to Telegram scanner

- Trades ≥ 15
- Excess CAGR over benchmark ≥ 5%
- Sharpe ≥ 0.7
- Max drawdown ≤ 25%
- Win rate ≥ 45%

### Tier 2 — PROCEED WITH CAUTION: manual alerts only

- Trades ≥ 8
- Excess CAGR ≥ 2%
- Sharpe ≥ 0.4
- Max drawdown ≤ 35%

### OVERRIDE

- Trades < 8, OR Sharpe < 0.4, OR Max drawdown > 35%

---

_Criteria committed 2026-05-12, before any validation run._
