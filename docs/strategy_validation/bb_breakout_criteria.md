# BB Breakout Strategy — Pre-committed Decision Criteria

**Date set:** 2026-05-12
**Committed before any validation run:** Yes
**Source:** Dharanidharan PC — BB Breakout Strategy (5-layer confluence)

---

## Hypothesis

When all 5 layers align simultaneously on a daily bar, the resulting breakout has
directional momentum strong enough to produce positive expectancy after costs.
This is NOT a mean-reversion strategy — RSI > 70 + SuperTrend BULL + Pivot Break +
BB Breakout = momentum continuation, not reversal.

---

## Strategy Parameters (exact as per source framework)

### Indicators

| Indicator | Settings |
|---|---|
| SuperTrend | Period 7, Multiplier 3.0 |
| RSI | Period 14 (Wilder's) |
| Pivot Points | Standard daily (H+L+C)/3 |
| Bollinger Bands | Period 20, 2 standard deviations |

### Entry conditions — ALL FOUR must be true simultaneously on daily close

**Bullish Breakout:**
1. Close > SuperTrend (direction = +1, bullish)
2. RSI(14) > 70 (momentum overbought — breakout fuel)
3. Close > R1 pivot (yesterday's resistance broken)
4. Close > Upper Bollinger Band(20, 2) (volatility breakout)

**Bearish Breakout:**
1. Close < SuperTrend (direction = -1, bearish)
2. RSI(14) < 30 (momentum oversold — breakdown fuel)
3. Close < S1 pivot (yesterday's support broken)
4. Close < Lower Bollinger Band(20, 2) (volatility breakdown)

### Exit conditions

- **Primary:** SuperTrend direction flips (trend reverses)
- **Hard stop:** -5% from entry price (catastrophic risk protection)
- **Max hold:** 20 trading days (prevents stale positions)

### Position sizing

- ₹1,00,000 per trade
- Max 5 concurrent positions
- Long-only (bullish breakout only; bearish tracked but not traded — shorting restrictions in India)

### Universe

- Nifty 500 (data/nifty500.json)
- Minimum 252 days of daily OHLCV data
- Period: 2021-01-01 → today

---

## Decision Criteria

### Tier 1 — PROCEED: add to live MWA scanner + Telegram alerts

- Total bullish trades ≥ 30
- CAGR ≥ 20% net of costs
- Sharpe ≥ 0.8
- Max drawdown ≤ 30%
- Win rate ≥ 50%

### Tier 2 — PROCEED WITH CAUTION: add to scanner, manual TAKE/SKIP only

- Total trades ≥ 15
- CAGR ≥ 10%
- Sharpe ≥ 0.5
- Max drawdown ≤ 40%
- Win rate ≥ 40%

### OVERRIDE

- Trades < 15, OR CAGR < 10%, OR Sharpe < 0.5, OR Max drawdown > 40%

**Note:** Given the strategy is 5-layer confluence, trade count will be low (strict conditions rarely all fire simultaneously). Lower thresholds than single-indicator strategies are appropriate.

---

_Criteria committed 2026-05-12, before any validation run._
