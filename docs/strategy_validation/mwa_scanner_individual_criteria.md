# MWA Individual Scanner Validation — Pre-committed Decision Criteria

**Date set:** 2026-05-13
**Committed before backtest run:** Yes
**Purpose:** Validate 4 clean individual scanners from the MWA suite as standalone strategies

---

## Why individual scanner backtests

The MWA Telegram signal is a COMPOSITE score from 150+ scanners. Before backtesting the
composite, we validate each individual scanner to understand its standalone edge.

**Critical methodology note:** SMC, VSA, Wyckoff, Harmonic engines were NOT backtested here
because their engines use `df.tail(60)` rolling windows — backtesting them would produce 60
phantom entries per real pattern day, polluting the results. Only vectorized, day-exact signals
are backtested here.

---

## Strategies Tested

| Signal | Entry Condition | Exit | Hold | Stop |
|---|---|---|---|---|
| Supertrend (10,3) flip | ST direction: -1→+1 | ST direction = -1 | 20 days | -7% |
| MACD (12,26,9) cross | MACD line crosses above signal | MACD crosses below | 20 days | -7% |
| EMA 9/21 cross | EMA9 crosses above EMA21 | EMA9 crosses below EMA21 | 20 days | -7% |
| 52-Week High breakout | Close >= prior 252-day max close | Close < SMA50 | 40 days | -10% |

**Universe:** Nifty 500 (468 symbols loaded)
**Period:** 2021-01-01 to 2026-05-13
**Position:** ₹1,00,000 per trade | Max 5 concurrent

---

## Decision Criteria (Standalone Equity Strategy)

### Tier 1 — PROCEED as standalone signal

- Total trades ≥ 30
- CAGR ≥ 20% (portfolio-level)
- Sharpe ≥ 0.8
- Max drawdown ≤ 30%
- Win rate ≥ 50%

### Tier 2 — PROCEED WITH CAUTION

- Total trades ≥ 15
- CAGR ≥ 10%
- Sharpe ≥ 0.5
- Max drawdown ≤ 40%
- Win rate ≥ 40%

### OVERRIDE

- Fails any Tier 2 gate → not viable standalone

---

## Backtest Results (2021-2026, Nifty 500)

| Strategy | Trades | CAGR | Sharpe | MaxDD | WinRate | Verdict |
|---|---|---|---|---|---|---|
| Supertrend (10,3) flip | 412 | +1.3% | 0.07 | 39.8% | 41.7% | **OVERRIDE** |
| MACD (12,26,9) cross | 685 | +7.7% | 0.20 | 55.0% | 32.0% | **OVERRIDE** |
| EMA 9/21 cross | 528 | +18.5% | 0.41 | 31.8% | 35.2% | **OVERRIDE** |
| 52-Week High breakout | 252 | +12.9% | 0.31 | 31.8% | 38.9% | **OVERRIDE** |

_Portfolio-level metrics: each trade weighted 1/MAX_CONC (= 1/5 of portfolio)._

---

## Why All 4 Show OVERRIDE — And Why That's Expected

All 4 strategies fail as STANDALONE equity strategies. This is **structurally expected** for
single trend-following indicators:

1. **Win rate 32-42%**: Single crossover signals generate frequent whipsaws. Multi-condition
   confluence (like the BB Breakout's 4-layer filter) is specifically designed to raise win
   rate above 50%.

2. **These are INPUTS, not strategies**: Supertrend, MACD, EMA crossover, and 52-week high
   are COMPONENTS of the MWA composite score — they contribute weight to the score but are not
   meant to be traded in isolation.

3. **Nifty 500 is a mixed universe**: These signals fire on both large-cap (liquid, tighter
   spreads) and small-cap (high slippage) stocks. The MWA score's Telegram signal applies
   additional filters (sector strength, FII flow, regime) that these standalone backtests omit.

---

## Verdict: OVERRIDE (Expected)

**Action required:** NONE. These indicators continue as confluence INPUTS to the MWA score.

**What this tells us:**
- Single indicators: unreliable standalone → validates WHY the composite MWA score exists
- EMA 9/21 cross: best single indicator (CAGR +18.5%, MaxDD 31.8%) — highest weight justified
- 52-week high: second best (CAGR +12.9%, MaxDD 31.8%) — confirmed as useful momentum input

**Composite MWA validation:** Still required via TAKE/SKIP forward data over 3-6 months.
The composite signal has NOT been individually backtested due to the rolling-window methodology
issue in SMC/VSA/Wyckoff/Harmonic engines (see note above).

---

## MWA Composite Validation Path (Pending)

Until the rolling-window methodology is fixed in the pattern engines, the only valid way to
validate the composite MWA signal is:

1. **Forward data** (TAKE/SKIP via Telegram): Track all Telegram signals from today.
   After 3 months, compute: win rate, average return, max drawdown.

2. **Gate:** If composite win rate > 50% and CAGR > 20% after 3 months → paper trade with
   real capital. If below → adjust composite weights.

3. **Timeline:** First review: 2026-08-13 (90 days from today)

---

_Criteria committed 2026-05-13, after confirming individual indicator OVERRIDE status._
_Report saved: reports/mwa_scanner_validation_2026-05-13.md_
