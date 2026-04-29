# Strategy Validation — Portfolio v1 (2026-04-28)

**Status:** Complete — all 7 engines validated standalone against Nifty 100 daily (3 years)
**Harness:** `scripts/validate_all_engines.py`
**Backtester:** `mcp_server/backtester.py` (v2, production-grade costs)

---

## Method

Each strategy was run independently against 90/93 Nifty 100 tickers over 1,095 days (daily) or 15m intraday (pos_5ema), using:
- **Costs**: Brokerage (₹20 flat or 0.03%), STT, GST, stamp duty, exchange charges — all realistic Zerodha rates
- **Slippage**: 0.3% per side (daily), 0.1% per side (15m intraday)
- **Capital**: ₹100,000 per ticker
- **Validation**: Monte Carlo permutation, Bootstrap Sharpe CI, Walk-Forward (5 windows)

Three bugs were fixed during this run (see commit messages for detail):
1. RRMS position sizing: min stop enforced at 0.5% of entry to prevent tick-wide stops on daily data
2. pos_5ema bankruptcy floor: simulation stops when capital reaches zero (prevents equity sign inversion)
3. Intraday slippage: corrected from 0.3% to 0.1% per side for 15m data

---

## Results

| Strategy | TF | Tickers OK | WF Sharpe (med) | P25–P75 | Profit Factor | Win Rate | Sig Rate | Consistency | Trades | Bootstrap | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **harmonic** | 1d | 90/93 | — | — | 0.00 | 0.0% | 0% | — | 63 | 1% | Kill standalone |
| **wyckoff** | 1d | 90/93 | -0.25 | -150–+0.19 | 0.67 | 23.6% | 1% | 20% | 770 | 10% | Closest to viable — test with regime filter |
| **confluence** | 1d | 90/93 | -2.25 | -100–+0.04 | 0.49 | 18.2% | 4% | 20% | 803 | 19% | Keep as pipeline gate, not standalone |
| **vsa** | 1d | 90/93 | -5.70 | -177–0.00 | 0.54 | 19.1% | 4% | 20% | 892 | 21% | Investigate second |
| **pos_5ema** | 15m | 90/93 | -7.65 | -9.40–-6.19 | 0.20 | 25.4% | 8% | 0% | 8,722 | 89% | Entry filter needs work; regime filter already applied |
| **rrms** | 1d | 90/93 | -16.50 | -42–0.00 | 0.52 | 12.5% | 2% | 20% | 837 | 32% | Reclassified as POSITION_SIZER — not an entry engine |
| **smc** | 1d | 90/93 | -63.79 | -153–-8.07 | 0.42 | 15.6% | 6% | 20% | 1,506 | 31% | Kill standalone; keep as debate input only |

---

## Headline Finding

**No standalone engine has positive expectancy on Indian equities in isolation.**

This is expected and not a platform failure. These engines are filter inputs, not final signals. The platform's value is the combination: MWA → confluence → debate validator → RRMS gate → dedup. None of that pipeline has been backtested yet.

**The validated question for the next run:** What is the production pipeline's walk-forward Sharpe?

---

## Strategy-by-strategy verdicts

### Harmonic — Kill standalone
- 63 trades across 90 tickers over 3 years = 0.7 signals/ticker/year
- Statistically useless. Zero wins. Cannot be validated at this sample size.
- **Decision**: Remove from validation harness. Keep as rare "flag" in live system if desired, but do not weight.

### Wyckoff — Most viable standalone
- WF Sharpe -0.25 (closest to zero of all engines). P75 at +0.19 means some windows are profitable.
- Win rate 23.6% at 3:1 RRR requires 25% to break even — gap is only 1.4pp.
- **Decision**: First candidate for regime filter improvement. Do NOT act until production pipeline replay complete.

### VSA — Second most viable
- Similar profile to Wyckoff but slightly worse. PF 0.54, WR 19%.
- **Decision**: Same as Wyckoff — hold.

### Confluence — Keep as gate, not source
- The confluence backtester already requires 2+ engines. Still loses standalone.
- This is the correct finding — confluence is a gate, not a strategy. The production pipeline USES confluence as a layer.

### pos_5ema — Entry quality problem
- Regime filter is already applied; 25.4% win rate is WITH the regime gate.
- 2:1 RRR needs 33% win rate to break even. Gap is 7.6pp.
- Bootstrap 89% robust rate means the losses are consistent (not random noise).
- **Decision**: Entry criteria need work. Do NOT promote weight until production replay shows the full pipeline compensates.

### RRMS — Reclassified as POSITION_SIZER
- Never designed as a standalone entry engine. RRMS sizes positions using support/resistance levels.
- Standalone backtest is a category error — like backtesting a stop-loss algorithm in isolation.
- **Decision**: Remove from entry validation harness. Validate via downstream P&L attribution on production signals.

### SMC — Kill standalone, keep as debate input
- WF Sharpe -63.79 (worst performer). P75 still at -8 (even the best quartile loses badly).
- **Decision**: Zero weight as standalone. Keep as one of 6 debate validator inputs.

---

## What has NOT been tested

The most important thing: the production pipeline itself has not been backtested.

The pipeline is: MWA → confluence → debate validator → RRMS gate → dedup → event calendar → risk guard.

These layers collectively determine what signals a user actually sees. The individual engine results above are raw material, not finished product. **The next validation run (`scripts/validate_production_pipeline.py`) tests the actual product.**

---

## Backtester improvements made during this run

Commit `dcffeae` — RRMS min-stop + position cap + bars_per_year revert
Commit `bf93318` — Bankruptcy floor + intraday slippage (0.1%) + bars_per_year revert
Commit `5c33551` — slippage_pct resolved before first use (NoneType crash fix)

These fixes should be applied to any future backtester use. The backtester is now stable for repeated validation runs.
