# USDINR Trend Following — Pre-committed Decision Criteria

**Date set:** 2026-05-12
**Committed before any validation run:** Yes

---

## Hypothesis

USDINR (US Dollar vs Indian Rupee) trends persistently due to structural macro forces
(RBI intervention, trade flows, FII activity). A Donchian channel breakout strategy —
long when USDINR breaks above its 20-day high, exit when it breaks below the 10-day
low — captures these multi-week trends after costs.

---

## Strategy Parameters

| Parameter | Value |
|---|---|
| Instrument | USDINR spot/futures (yfinance: INR=X) |
| Entry | Close > 20-day rolling high (Donchian breakout) |
| Exit | Close < 10-day rolling low (trailing channel) |
| Hard stop | -1.5% from entry (currency-appropriate) |
| Direction | Long-only (rupee weakness — structurally easier to trade in India) |
| Position size | ₹10,00,000 notional per trade |
| Period | 2021-01-01 → today |
| Benchmark | USDINR buy-and-hold total return |

---

## Cost Model (CDS currency futures, per lot = $1,000)

| Cost | Rate |
|---|---|
| Brokerage | ₹20 flat per order |
| Exchange | 0.00045% per side |
| GST | 18% on brokerage + exchange |
| Stamp duty | 0.002% on notional |
| Slippage | 0.05 paise (≈ 0.01% on USDINR ≈ 83) |

---

## Decision Criteria

### Tier 1 — PROCEED: automate currency trend signals

- Trades ≥ 20
- CAGR of excess return over benchmark ≥ 8%
- Sharpe ≥ 0.7
- Max drawdown ≤ 20%
- Win rate ≥ 40% (trend strategies have lower win rate, large winners)

### Tier 2 — PROCEED WITH CAUTION: manual signal only

- Trades ≥ 10
- Excess CAGR ≥ 3%
- Sharpe ≥ 0.4
- Max drawdown ≤ 30%

### OVERRIDE

- Trades < 10, OR Sharpe < 0.4, OR Max drawdown > 30%

---

_Criteria committed 2026-05-12, before any validation run._
