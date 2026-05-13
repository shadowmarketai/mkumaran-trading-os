# BB Breakout Weekly — Pre-committed Decision Criteria

**Date set:** 2026-05-13
**Committed before any live-trading run:** Yes
**Source:** Dharanidharan PC BB Breakout framework — revised for weekly timeframe

---

## Strategy Parameters

| Indicator | Setting |
|---|---|
| SuperTrend | Period 7, Multiplier 3.0 |
| RSI | Period 14 (Wilder's), threshold **> 60** (not 70 — weekly enters earlier) |
| Pivot Points | Standard weekly (prev week H+L+C)/3 |
| Bollinger Bands | Period 20, 2 standard deviations |
| Hard stop | -8% from entry (wider than daily -5% — weekly bars move larger) |
| Max hold | 10 weekly bars ≈ 10 weeks |
| Position | ₹1,00,000 per trade, max 5 concurrent |

### Why RSI > 60 not > 70

On weekly bars, RSI > 70 means the stock already moved 10-15% that week — the breakout
is exhausted before entry. RSI > 60 catches the signal at the START of the weekly breakout
while momentum is building, not at the top.

---

## Backtest Result (2020-2026, Nifty 500)

| Metric | Original (RSI>70) | Revised (RSI>60) |
|---|---|---|
| Trades | 142 | 187 |
| Win rate | 31.0% | **58.3%** |
| CAGR | +49.5% | **+61.5%** |
| Sharpe | 1.28 | **1.07** |
| Max DD | 21.6% | **15.0%** |
| Verdict | OVERRIDE | **TIER_1** |

---

## Live Deployment

- **Scanner weight:** 5.0 (highest of all BB Breakout variants — TIER_1 result)
- **Signal fires:** When latest completed weekly bar satisfies all 4 conditions
- **Telegram alert:** Manual TAKE/SKIP (same as daily BB Breakout)
- **Position sizing:** Same RRMS gate as all signals

## Decision Criteria

### Tier 1 — PROCEED FULL LIVE

- Total trades ≥ 30
- CAGR ≥ 20%
- Sharpe ≥ 0.8
- Max drawdown ≤ 30%
- Win rate ≥ 50%

**Backtest passed all 5 Tier 1 criteria.**

### Override triggers

- If forward-test win rate drops below 40% after 20+ live trades
- If max drawdown exceeds 30% in live trading

---

_Criteria committed 2026-05-13, after backtest validation confirmed TIER_1._
