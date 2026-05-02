# Pairs Trading — Pre-committed Decision Criteria

**Date set:** 2026-05-02  
**Author:** M. Kumaran  
**Committed before any data observed:** Yes

---

## Hypothesis

Cointegrated pairs of Indian large-cap stocks exhibit mean-reverting behavior
on the spread, sufficient to generate positive risk-adjusted returns after
costs over a 5-year window (2021-01-01 to 2026-04-30).

---

## Universe

10 candidate pairs defined in `data/pairs_universe.csv`. Pairs were selected
based on structural similarity (same sector, shared fundamental drivers),
not statistical correlation. All 10 pairs go through the identical
validation pipeline. No cherry-picking permitted.

---

## Methodology

| Parameter | Value |
|---|---|
| Cointegration test | Engle-Granger two-step (primary), Johansen (secondary) |
| Spread construction | OLS hedge ratio on the cointegration window |
| Signal | Z-score on spread, recomputed daily |
| Entry | \|z-score\| > 2.0 (short rich leg, long cheap leg) |
| Exit | \|z-score\| < 0.5 (mean reversion to band) |
| Stop | \|z-score\| > 4.0 (cointegration broken; close position, skip pair 30 days) |
| Brokerage | ₹20 flat per order |
| STT | 0.025% on sell-side (equity delivery) |
| Exchange charges | 0.00345% per side |
| GST | 18% on brokerage + exchange |
| Stamp duty | 0.015% on buy-side |
| Slippage | 0.05% Nifty 50 components, 0.10% Nifty 100, 0.15% others |
| Borrow cost | 0.04% per day on the short leg notional |
| Walk-forward | 12-month train, 3-month test, 3-month roll |

---

## Per-pair decision criteria

### Tier 1 — Strong validation

| Metric | Threshold |
|---|---|
| Walk-forward Sharpe | > 1.0 |
| Maximum drawdown | < 15% |
| Trade count over 5 years | ≥ 30 |
| Cointegration p-value < 0.05 | ≥ 80% of walk-forward windows |

### Tier 2 — Marginal (one parameter iteration permitted)

| Metric | Threshold |
|---|---|
| Walk-forward Sharpe | 0.6–1.0 |
| Maximum drawdown | 15–25% |
| Trade count | ≥ 30 |

**Permitted iteration:** ONE change to z-score entry/exit thresholds (not hedge ratio, not cointegration window). Must be motivated by a structural hypothesis stated before re-testing.

### Tier 3 — Failed

- Walk-forward Sharpe below Tier 2, OR
- Maximum drawdown > 25%, OR
- Cointegration holds (p < 0.05) in fewer than 60% of walk-forward windows

---

## Universe-level decision rules

After all 10 pairs are tested:

| Outcome | Decision |
|---|---|
| 3 or more pairs at Tier 1 | Deploy as multi-pair portfolio in paper trading (Phase 2) |
| 1–2 pairs at Tier 1 | Run out-of-sample confirmation on 2018–2022 window. If holds, deploy as narrow strategy |
| 0 pairs at Tier 1 | Hypothesis disproven. Move to next strategic decision (Path C or other) |

---

## Hard rules (non-negotiable)

1. **No cherry-picking pairs after seeing results** — all 10 run the same pipeline
2. **No parameter optimization beyond what is specified above** — entry/exit thresholds, hedge ratio window, and cointegration window are fixed at values above
3. **No mid-phase pivots** — no "let me also test [different methodology]" while Phase 1 is running
4. **Walk-forward must use only past-data hedge ratio** — no future leakage; hedge ratio estimated on train window only, applied to test window
5. **If any pair shows Sharpe > 3.0, treat as bug first** — investigate for look-ahead bias before claiming a result
6. **30-day cooldown is mandatory** after a stop trigger (cointegration breakdown signal); do not re-enter the pair earlier

---

## What success looks like

**Best case:** 3–5 pairs validate cleanly. Deployable multi-pair strategy class.

**Realistic:** 1–2 pairs marginal, rest fail. Narrow strategy candidate with documented edge.

**Worst case:** 0 pairs validate. Another major strategy class eliminated with rigor. Move on without sunk-cost regret.

All three outcomes are acceptable. The goal is honest answers, not predetermined success.

---

## Constraints I'm choosing to honor

- I will not adjust criteria after seeing results
- I will not run alternative variants if these fail
- I will not skip walk-forward to "see the aggregate first"
- I will respect the 30-day cointegration-breakdown cooldown rule

---

## Signature

These criteria were committed by the operator (mkumaran2931@gmail.com) on 2026-05-02,
before any pairs backtest was run or any cointegration test was observed.

Context: this follows three documented negative results on options-selling strategies
(BankNifty weekly and monthly, with and without VIX gate), all tested with
pre-committed criteria and accepted without iteration. The same discipline applies here.

---

## Postmortem (2026-05-02, after first validation run)

**Result:** All 10 pairs OVERRIDE on trade count. Range: 4–17 trades over 5 years per pair.

**Interpretation under committed criteria:** Inconclusive. The criteria doc as committed
did not address the case where all pairs return OVERRIDE on sample size.

**What we learned:**
- 2 of 10 candidate pairs (RELIANCE/IOC, COALINDIA/NTPC) showed full-period cointegration p < 0.05
- 8 of 10 candidate pairs were not cointegrated; structural-similarity heuristic for pair selection
  was weaker than expected in Indian large-caps over this period
- 2021–2026 was a strongly trending period in Indian large-caps, which limits mean-reversion
  strategies broadly
- |z| > 2.0 with 12-month training window generates 1–3 trades per pair per year on this universe —
  insufficient frequency to be statistically valid or commercially viable as a standalone strategy

**Verdict:** Hypothesis is NOT VALIDATED. Hypothesis is also NOT DISPROVEN. The methodology
as committed could not produce a conclusive answer.

**Action:** Move to Phase 2 (Nifty options) as scheduled. No iteration on pairs methodology.

**Future criteria template improvement:** All future strategy criteria docs must explicitly address
the case of all-OVERRIDE-on-sample-size. Either as an additional decision tier
("Tier 0 — insufficient sample") or as a hard rule distinguishing OVERRIDE-induced inconclusiveness
from genuine Tier 3/4 failure. The two states require different verdicts.

**Possible future revisit (not now, not an iteration of this test):** If revisiting pairs trading
as a separate research project in the future, new criteria should: (a) use rolling z-score
normalization (60-day rolling window) for higher signal frequency, (b) test a wider candidate
universe to find genuinely cointegrated pairs, (c) reconsider whether Engle-Granger cointegration
is the right structural entry filter for Indian large-cap markets with persistent multi-year trends.
This is a future project with new pre-committed criteria — not a continuation of this one.
