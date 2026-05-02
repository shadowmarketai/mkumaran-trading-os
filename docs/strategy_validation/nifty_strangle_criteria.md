# Nifty 50 Short Strangle — Pre-Committed Decision Criteria

**Date committed:** 2026-05-02
**Committed BEFORE any validation results are observed.**
**Do not modify after the validation script is run.**

---

## Why this test follows from the BankNifty results

BankNifty weekly (Jan 2023 – Nov 2024, 36 qualifying trades):
- VIX gate ON: WF return 13.9%, Sharpe 1.15, MC P95 DD 7.5%, win rate 80.6% — OVERRIDE on trade count (< 50)
- VIX gate OFF: WF return -5.6%, Sharpe -0.32 — VIX gate confirmed load-bearing (19.5pp delta)

BankNifty monthly (2021–2026, 10 qualifying trades):
- VIX gate ON: WF return -5.6%, insufficient sample — OVERRIDE on trade count (< 30)

BankNifty is no longer viable for weekly (discontinued November 2024). Monthly sample
was structurally too thin at ~10 qualifying trades over 5 years.

Nifty 50 options address two BankNifty constraints:
1. **Weekly contracts are active** — no discontinuation risk, longer history available
2. **Higher retail participation** — Nifty is the most liquid index options market in India,
   with tighter spreads and more qualifying entry opportunities

This is instrument substitution within the same strategy family, not hypothesis change.
The VIX gate is carried over unchanged as an empirically load-bearing component.

---

## Hypothesis

Nifty 50 short strangles at 0.15-delta, with the VIX regime gate
(30th–80th rolling percentile), produce positive risk-adjusted returns after
realistic costs over a multi-year validation window.

Weekly variant: tested on 2021-01-01 to 2026-04-30.
Monthly variant: tested on the same window.

Both variants go through the identical pipeline. The better-performing variant
(or both, if both validate) is the candidate for paper trading.

---

## Fixed parameters (identical to BankNifty; do not change for this test)

| Parameter | Value | Source |
|---|---|---|
| Target delta | 0.15 per leg | Same as BankNifty |
| VIX gate | 30th–80th percentile, rolling 252-day | Carried over as load-bearing |
| Profit target | 50% of initial credit | Same as BankNifty |
| Stop loss | 2× initial credit | Same as BankNifty |
| Time exit (weekly) | Expiry day (Thursday) | Same as BankNifty weekly |
| Time exit (monthly) | 5 DTE before last Thursday | Same as BankNifty monthly |
| Lot size | 75 (Nifty 50 current) | Exchange-mandated |
| Margin basis | ₹1,50,000 per strangle | Approximate SPAN; used as fixed denominator |
| Brokerage | ₹20 flat per order × 4 orders | Same as BankNifty |
| STT | 0.05% on sell-side (options exercise) | SEBI schedule |
| Exchange charges | 0.053% per side | NSE |
| GST | 18% on brokerage + exchange | Standard |
| Stamp duty | 0.003% buy-side | SEBI schedule |

---

## Weekly variant decision criteria

Entry: Monday open, short OTM call + put at nearest 0.15 delta.
Exit: 50% credit collected, OR 2× credit stop, OR Thursday expiry close.
Gate: VIX must be in 30th–80th percentile of trailing 252-day window at entry.

### Tier 1 — Strong validation

| Metric | Threshold |
|---|---|
| Walk-forward annual return on margin | > 25% |
| Walk-forward Sharpe ratio | > 1.0 |
| Monte Carlo P95 max drawdown | < 35% |
| Walk-forward consistency (profitable windows) | ≥ 60% |
| Win rate | ≥ 60% |
| Trade count over validation window | ≥ 50 |

**Decision:** Paper trade 30 calendar days, 1 lot. If closed-trade P&L tracks within
±2 SD of backtest expectation, move to 1-lot live with defined weekly risk.

### Tier 2 — Marginal

| Metric | Threshold |
|---|---|
| Walk-forward annual return on margin | 15–25% |
| Walk-forward Sharpe ratio | 0.5–1.0 |
| Monte Carlo P95 max drawdown | < 50% |
| Walk-forward consistency | ≥ 50% |
| Trade count | ≥ 50 |

**Decision:** ONE iteration permitted on exit parameters only (profit target OR stop
multiplier, not both). State the structural hypothesis for the change before running.
If still Tier 2 after iteration, treat as Tier 3.

### Tier 3 — Edge too thin

- Walk-forward annual return on margin: 5–15%, OR
- Walk-forward Sharpe ratio: 0–0.5, OR
- Monte Carlo P95 max drawdown: > 50%

**Decision:** Document findings. Move on. No further weekly options iteration.

### Tier 4 — Failed

- Walk-forward annual return on margin: < 5% or negative, OR
- Walk-forward Sharpe ratio: < 0

**Decision:** Hypothesis disproven for weekly Nifty strangles. Document. No iteration.

---

## Monthly variant decision criteria

Entry: First Monday of expiry month (or next trading day), 25 DTE target.
Exit: 50% credit collected, OR 2× credit stop, OR 5 DTE time exit.
Gate: VIX must be in 30th–80th percentile of trailing 252-day window at entry.

### Tier 1 — Strong validation

| Metric | Threshold |
|---|---|
| Walk-forward annual return on margin | > 20% |
| Walk-forward Sharpe ratio | > 0.9 |
| Monte Carlo P95 max drawdown | < 30% |
| Walk-forward consistency (profitable windows) | ≥ 60% |
| Win rate | ≥ 65% |
| Trade count over validation window | ≥ 30 |

**Decision:** Paper trade 30 calendar days, 1 lot.

### Tier 2 — Marginal

| Metric | Threshold |
|---|---|
| Walk-forward annual return on margin | 10–20% |
| Walk-forward Sharpe ratio | 0.5–0.9 |
| Monte Carlo P95 max drawdown | < 40% |
| Walk-forward consistency | ≥ 50% |
| Trade count | ≥ 30 |

**Decision:** ONE iteration on exit parameters only. State hypothesis before running.

### Tier 3 — Edge too thin

- Walk-forward annual return on margin: 5–10%, OR
- Walk-forward Sharpe ratio: 0–0.5

**Decision:** Two thin results across BankNifty and Nifty monthly confirms options-selling
at this frequency is not commercially viable in this regime. Document. Move on.

### Tier 4 — Failed

- Walk-forward annual return on margin: < 5% or negative

**Decision:** Hypothesis disproven. No iteration.

---

## Override conditions (apply to both variants regardless of tier)

Any one of these overrides a Tier 1 or Tier 2 verdict downward to "do not deploy":

1. **Monte Carlo P95 max drawdown > 60%** — tail risk unacceptable at any return level
2. **Walk-forward consistency < 40%** — too regime-dependent
3. **Any single walk-forward window shows > 50% drawdown** — hidden regime sensitivity
4. **Trade count below minimum** — see per-variant thresholds above
5. **Data quality issues discovered post-run** — gaps in options chain during key events

---

## If trade count < minimum (sample size override handling)

This is explicitly addressed, unlike pairs trading criteria (which had a gap here).

For weekly variant (< 50 trades):
- Extend validation window to 2019-01-01 if NSE data is available.
- This is a data extension, not a parameter change.
- If extended run still < 50 trades: the gate is too restrictive for weekly frequency.
  Verdict: hypothesis is sample-size-limited, NOT disproven. No iteration. Move on.

For monthly variant (< 30 trades):
- Same extension to 2019 if available.
- If still < 30 trades: same verdict — sample-size-limited, not disproven. Move on.

---

## Sequencing rule

Run weekly variant first. Report results before running monthly.
Do not run monthly in parallel with weekly — each result informs whether the other
test is worth running under the same hypothesis.

If weekly validates at Tier 1: still run monthly as a portfolio-building exercise
(two expiry types diversifies entry frequency).

If weekly is Tier 3 or 4: monthly is still run, but under reduced expectations.
Two consecutive Tier 3/4 results across both variants of Nifty options confirms
the strategy family is exhausted on this instrument. Move to Path C.

---

## Hard rules

1. Do not modify delta target (0.15)
2. Do not modify VIX gate percentiles
3. Do not add adjustment rules (gamma scalp, roll-out, etc.) to improve results
4. Do not test different underlyings (Finnifty, MidcapNifty) if these fail — that
   is a different hypothesis and requires new pre-committed criteria
5. If any window shows Sharpe > 3.0, treat as bug — investigate before claiming result

---

## Signature

These criteria were committed by the operator (mkumaran2931@gmail.com) on 2026-05-02,
before any Nifty options validation was run or any results were observed.

Context: BankNifty weekly OVERRIDE (13.9% WF return, 36 trades, Sharpe 1.15 — positive
but below trade-count threshold). BankNifty monthly OVERRIDE (10 trades, inconclusive).
Pairs trading inconclusive (all OVERRIDE on sample size, 2 of 10 pairs cointegrated).
Four prior tests, all accepted without iteration. The same discipline applies here.
