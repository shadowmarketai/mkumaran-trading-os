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

## Backtest Results (2021-2026-05-13, Nifty 500, 483 symbols, step=5)

| Engine | Trades | CAGR | Sharpe | MaxDD | WinRate | Verdict |
|---|---|---|---|---|---|---|
| SMC | 410 | +7.5% | 0.21 | 36.6% | 45.4% | **OVERRIDE** |
| VSA | 398 | +7.6% | 0.23 | 33.3% | 45.7% | **OVERRIDE** |
| Wyckoff | 383 | +4.3% | 0.17 | 37.5% | 48.8% | **OVERRIDE** |
| **Harmonic** | **314** | **+27.9%** | **0.78** | **14.8%** | **54.1%** | **TIER_2** |

---

## Key Finding: Harmonic is TIER_2

Harmonic misses TIER_1 by **0.02 Sharpe** (0.78 vs 0.80 gate). All other TIER_1 gates pass:
- WinRate 54.1% (>= 50%) ✓
- CAGR +27.9% (>= 20%) ✓
- MaxDD 14.8% (<= 30%) ✓
- Trades 314 (>= 30) ✓
- Sharpe 0.78 (needs 0.80) ✗ — misses by 0.02

**Implications:**
1. Harmonic is the only engine with standalone positive edge (WinRate > 50%)
2. It has the lowest MaxDD of all 4 engines (14.8%) — very controlled risk
3. As a composite input to MWA, it should carry the highest weight of all pattern engines
4. Consider increasing Harmonic scanner weight in `mcp_server/mwa_scanner.py`

**SMC/VSA/Wyckoff:** All OVERRIDE standalone. Win rates 45-49% show some edge but
not enough for standalone trading. They contribute real information to the MWA composite
but should not be traded in isolation.

---

## Weight recommendation for MWA composite

Based on standalone backtest win rates (higher WinRate = more standalone edge = higher weight):

| Engine | WinRate standalone | Current weight | Suggested weight |
|---|---|---|---|
| Harmonic | 54.1% | 3.0 | **4.0** (increase) |
| Wyckoff | 48.8% | 3.0 | 3.0 (keep) |
| VSA | 45.7% | 3.0 | 2.5 (slight decrease) |
| SMC | 45.4% | 3.0 | 2.5 (slight decrease) |

_Decision on weight changes: operator's call. Commit changes to `mcp_server/mwa_scanner.py`._

---

_Criteria committed 2026-05-13, before backtest run._
_Results filled 2026-05-13, after backtest completed._
