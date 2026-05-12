# Pairs Trading (Screener-Selected) — Pre-committed Decision Criteria

**Date set:** 2026-05-12
**Committed before any validation run:** Yes
**Prior attempt:** `pairs_trading_criteria.md` — HYPOTHESIS DISPROVEN (all 10 pairs OVERRIDE, trade count < 30)

---

## New Hypothesis

Cointegration-screened pairs (selected by Engle-Granger p-value, not sector logic)
generate sufficient trade count and positive risk-adjusted returns after costs
over a 5-year window (2021-01-01 → 2026-05-12).

The prior failure was caused by using sector-based pair selection; 8/10 original pairs
had no statistically significant cointegration. This iteration uses math-first selection.

---

## Test Universe

6 pairs selected from `reports/nifty50_coint_screen.csv` by ranking:

| Pair | Full-period p | Bars | Structural rationale |
|---|---|---|---|
| AXISBANK/COALINDIA | 0.0007 | 1324 | Strongest cointegration signal |
| NTPC/COALINDIA | 0.0011 | 1324 | Power generator + coal supplier |
| RELIANCE/IOC | 0.0015 | 1324 | Both oil refiners |
| NTPC/ONGC | 0.0038 | 1324 | Power + upstream oil |
| ONGC/COALINDIA | 0.0094 | 1324 | Both state-owned energy |
| DRREDDY/CIPLA | 0.0120 | 747 | Both large pharma |

Selection rule: top 5 pairs with 1324 bars (full 5-year history) + 1 structural pair with
shorter but meaningful history. No cherry-picking of Sharpe after the fact.

---

## Methodology (unchanged from prior criteria)

| Parameter | Value |
|---|---|
| Cointegration test | Engle-Granger (primary) |
| Signal | Z-score on spread, OLS hedge ratio |
| Entry | \|z\| > 2.0 |
| Exit | \|z\| < 0.5 |
| Stop | \|z\| > 4.0 (skip pair 30 days) |
| Walk-forward | 12-month train / 3-month test |
| All costs | As per `pairs_trading_criteria.md` |

---

## Per-pair decision criteria (unchanged)

### Tier 1
- WF Sharpe > 1.0
- Max drawdown < 15%
- Trade count ≥ 30
- Cointegration p < 0.05 in ≥ 80% of WF windows

### Tier 2 (marginal — one z-threshold iteration permitted)
- WF Sharpe 0.6–1.0
- Max drawdown < 25%
- Trade count ≥ 30
- Permitted change: z-entry 2.0 → 1.5 only, motivated by "cointegration is real but threshold too strict"

### OVERRIDE
- Trade count < 30, OR
- WF Sharpe < 0.6, OR
- Max drawdown > 25%

### TIER 3 (hypothesis failed)
- WF Sharpe < 0 on a pair with ≥ 30 trades

---

## Universe-level decision rules

| Outcome | Decision |
|---|---|
| ≥ 2 pairs TIER 1 | PROCEED: build live pairs scanner |
| ≥ 3 pairs TIER 2 | PROCEED with caution: paper-trade first |
| < 2 pairs TIER 1, < 3 pairs TIER 2 | HYPOTHESIS DISPROVEN (final) |

If HYPOTHESIS DISPROVEN: close pairs trading chapter, proceed with Path C.

**No further pairs iterations permitted after this run.**

---

_Criteria committed 2026-05-12, before any validation run._
