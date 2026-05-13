# Pattern Engine Backtest — Pre-committed Decision Criteria

**Date set:** 2026-05-13
**Committed before backtest run:** Yes
**Engines:** SMC, VSA, Wyckoff, Harmonic

---

## Methodology

**Point-in-time sliding window** — for each bar T, calls `detect_all(df.iloc[:T+1])`.
The engine's internal `.tail(lookback)` then uses bars [T-lookback+1 .. T] only.
No lookahead bias.

| Engine | Lookback | Sub-detectors |
|---|---|---|
| SMC | 60 bars | BOS, CHoCH, Order Blocks, FVG, Liquidity Sweep, Premium/Discount, Breaker, Mitigation, Inversion FVG, MSS, OTE, Inducement, CE, IRL/ERL, Fake Breakout, EMA Pullback (16 total) |
| VSA | 60 bars | Stopping Volume, No Supply, No Demand, Selling Climax, Buying Climax, Effort No Result, Supply Entry, Demand Entry |
| Wyckoff | 60 bars | Accumulation Phase, Distribution Phase, Spring, Upthrust, Test After Spring |
| Harmonic | 120 bars | Gartley, Bat, Crab, Cypher (bullish + bearish) |

**Sampling:** every 5 bars (roughly weekly) — trades signal on day T, enter day T+1.
**Exit:** -7% hard stop OR 20 trading days (whichever first).

---

## Decision Criteria (Same as individual MWA scanners)

### Tier 1 — PROCEED as standalone signal

- Total trades >= 30
- CAGR >= 20% (portfolio-level, each trade weighted 1/5)
- Sharpe >= 0.8
- Max drawdown <= 30%
- Win rate >= 50%

### Tier 2 — PROCEED WITH CAUTION

- Total trades >= 15
- CAGR >= 10%
- Sharpe >= 0.5
- Max drawdown <= 40%
- Win rate >= 40%

### OVERRIDE — expected for standalone pattern inputs

- Fails any Tier 2 gate

---

## Expected Outcome

All 4 engines are EXPECTED to show OVERRIDE as standalone strategies for the
same reason as the simpler indicators (Supertrend, MACD, EMA) — they are
confluence inputs to the composite MWA score, not standalone strategies.

The PURPOSE of this backtest is to confirm:
1. Each engine generates a statistically meaningful number of signals (>30)
2. Win rate is non-trivially above 50% (if it is, it contributes real edge)
3. No engine has catastrophically negative CAGR (which would suggest a broken signal)

**If any engine shows WinRate > 50%** — this is notable and should be highlighted
as a stronger component of the MWA composite. Increase its weight.

**If any engine shows WinRate < 40%** — inspect its sub-detectors and potentially
reduce its weight in the composite score.

---

## Backtest Results (2021-2026, Nifty 500, step=5)

_To be filled after backtest completes_

| Engine | Trades | CAGR | Sharpe | MaxDD | WinRate | Verdict |
|---|---|---|---|---|---|---|
| SMC | TBD | TBD | TBD | TBD | TBD | TBD |
| VSA | TBD | TBD | TBD | TBD | TBD | TBD |
| Wyckoff | TBD | TBD | TBD | TBD | TBD | TBD |
| Harmonic | TBD | TBD | TBD | TBD | TBD | TBD |

---

_Criteria committed 2026-05-13, before backtest run._
