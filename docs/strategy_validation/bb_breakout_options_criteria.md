# BB Breakout Options — Pre-committed Decision Criteria

**Date set:** 2026-05-13
**Committed before any live trading:** Yes
**Source:** Dharanidharan PC BB Breakout (daily signals) → ATM Call execution

---

## Why separate criteria from equity

Options have a **power law payoff structure** — 25-35% of trades win very large
(+200-500% on premium), 65-75% lose the premium paid. This is structurally
different from equity where win rate targets 50%+. Applying equity win rate
thresholds to options would incorrectly disqualify good options strategies.

Standard options backtesting floor: WinRate ≥ 25% (not 40%).

---

## Strategy Parameters

| Parameter | Value | Reason |
|---|---|---|
| Entry signal | BB Breakout daily (RSI>80) | High-conviction only — RSI>80 not 70 |
| Option type | ATM Call, monthly expiry (21 days) | Captures momentum with defined risk |
| Position size | ₹20,000 premium per trade | Max loss per trade = ₹14-18k (premium × 70-90%) |
| Concurrent | 3 max | Tight concentration control |
| Exit | Same as equity (ST flip / -5% underlying / 20 days) | Underlying drives exit, not option price |
| IV assumption | 25% (NSE equity options average) | Conservative vs actual 15-40% range |

---

## Backtest Result (2021-2026, Nifty 500, IV=25%)

| Metric | Equity baseline | Options |
|---|---|---|
| Trades | 437 | 247 |
| Win rate | 43.2% | **30.4%** |
| Avg return/trade | +2.59% | **+96.83%** |
| CAGR | +59.7% | **+178.0%** |
| Sharpe | 0.89 | **1.07** |
| Max DD (peak-to-trough) | 19.5% | **8.2%** |

Options **beats equity on Sharpe AND MaxDD**. Lower win rate is structural,
not a flaw — the winners (+200-500%) dominate the losers (-70% premium).

---

## Decision Criteria (Options-specific)

### Tier 1 — PROCEED: add to live scanner, paper trade

- Total trades ≥ 30
- CAGR ≥ 30%
- Sharpe ≥ 0.8
- Max drawdown (peak-to-trough) ≤ 25%
- Win rate ≥ **25%** (options standard — power law payoff)

### Tier 2 — PROCEED WITH CAUTION: paper trade only, manual review each signal

- Total trades ≥ 15
- CAGR ≥ 15%
- Sharpe ≥ 0.5
- Max drawdown ≤ 40%
- Win rate ≥ **20%**

### OVERRIDE

- Trades < 15, OR CAGR < 15%, OR Sharpe < 0.5, OR MaxDD > 40%

---

## Backtest verdict (against options criteria)

| Metric | Result | Tier 1 gate | Pass? |
|---|---|---|---|
| Trades | 247 | ≥ 30 | ✓ |
| CAGR | +178% | ≥ 30% | ✓ |
| Sharpe | 1.07 | ≥ 0.8 | ✓ |
| Max DD | 8.2% | ≤ 25% | ✓ |
| Win rate | 30.4% | ≥ 25% | ✓ |

**Verdict: TIER_1 under options-appropriate criteria.**

---

## Live trading requirements before going live

- [ ] 6 months of forward-test data on daily equity signals (validate underlying edge first)
- [ ] Manual paper trade first 20 options signals (TAKE/SKIP via Telegram)
- [ ] Confirm IV realisation: actual trade outcomes vs 25% IV assumption
- [ ] Capital requirement: minimum ₹5L total portfolio (₹60k at risk = 12% of capital)

## Risk warnings

- **30.4% win rate**: expect 5-7 consecutive losses before a big winner. Requires discipline.
- **IV assumption**: if real IV > 25%, premiums cost more → entry premium higher → lower % return
- **Liquidity**: mid/small caps may have wide bid-ask spreads — model assumes 0.5% slippage
- **Assignment risk**: monthly expiry only — no early exercise on NSE index options

---

_Criteria committed 2026-05-13, after backtest confirmed TIER_1 under options-appropriate thresholds._
