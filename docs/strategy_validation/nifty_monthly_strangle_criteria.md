# Nifty Monthly Short Strangle — Pre-Committed Decision Criteria

**Date set:** 2026-05-07
**Author:** M. Kumaran
**Committed before any data observed:** Yes

---

## Why this test follows from the weekly result

Nifty weekly short strangle (2023-01-01 → 2026-04-30, 55 qualifying trades):
- VIX gate ON: WF return 16.4%, Sharpe 0.556, MC P95 DD 28.7%, win rate 78.2%
- TIER 2 result: exit parameters functioning correctly; binding constraint is
  VIX gate selectivity on weekly frequency, not strategy edge

Monthly directly addresses the weekly's binding constraint: same instrument, same
VIX gate, same structural logic — but 25 DTE entry produces 3–4× the credit per
trade and reduces gate-rejection frequency because the monthly has more premium
runway to absorb mild adverse VIX regimes.

The VIX gate is carried over unchanged. It was empirically load-bearing on
BankNifty (19.5pp delta) and the conceptual basis is unchanged for monthly.

---

## Hypothesis

Nifty 50 monthly short strangles at 0.15-delta, entered at ~25 DTE with the
VIX regime gate (30th–80th percentile, rolling 252-day), produce positive
risk-adjusted returns after realistic costs over a 3+ year validation window
(2023-01-01 to 2026-04-30).

---

## Strategy parameters (locked, no iteration permitted)

| Parameter | Value | Source |
|---|---|---|
| Underlying | Nifty 50 index | — |
| Expiry type | Monthly (last expiry of each calendar month) | — |
| Entry timing | ~25 DTE before monthly expiry | Monthly-appropriate DTE |
| Strike selection | 0.15-delta both legs (CE and PE) | Same as weekly |
| VIX gate | 30th–80th percentile, rolling 252-day | Carried over unchanged |
| Profit target | 50% of initial combined credit | Same as weekly |
| Stop loss | 2× initial combined credit | Same as weekly |
| Time exit | Expiry day close; OR 5 DTE if profit ≥ 25% of initial credit at that point | Monthly gamma management |
| Lot size | 75 (current NSE mandate) | Same as weekly |
| Margin basis | ₹1,50,000 per strangle | Same as weekly |
| Brokerage | ₹20 flat per order × 4 orders | Same as weekly |
| STT | 0.05% on sell-side | Same as weekly |
| Exchange charges | 0.053% per side | Same as weekly |
| GST | 18% on brokerage + exchange | Same as weekly |
| Stamp duty | 0.003% on buy-side | Same as weekly |

**Time exit note:** The "5 DTE if profit ≥ 25%" rule exists because monthly
strangles with significant credit at 5 DTE face accelerating gamma risk. Exiting
early when the position is already profitable at 25% locks gains before the
gamma explosion window. This is a structural rule motivated by monthly option
mechanics, not a parameter chosen after seeing results.

---

## Decision criteria

### Tier 1 — Strong validation → Paper trade

| Metric | Threshold |
|---|---|
| Walk-forward annual return on margin | > 18% |
| Walk-forward Sharpe ratio | > 0.9 |
| Monte Carlo P95 max drawdown | < 30% |
| Walk-forward consistency (profitable windows) | ≥ 60% |
| Win rate (net of all costs) | ≥ 65% |
| Trade count over validation window | ≥ 30 |

**Decision:** Paper trade 30 calendar days, 1 lot. If closed-trade P&L tracks
within ±2 SD of backtest expectation, move to 1-lot live with defined monthly
risk cap.

Tier 1 return set at 18% (not 20% as for weekly) because monthly has lower
absolute premium frequency — the same risk-adjusted edge produces lower annual
return at monthly frequency.

### Tier 2 — Marginal → One iteration only

| Metric | Threshold |
|---|---|
| Walk-forward annual return on margin | 10–18% |
| Walk-forward Sharpe ratio | 0.5–0.9 |
| Monte Carlo P95 max drawdown | < 40% |
| Walk-forward consistency | ≥ 50% |
| Trade count | ≥ 30 |

**Decision:** ONE iteration permitted on exit parameters only (profit target OR
the early-exit threshold, not both, not stop multiplier). State the structural
reason before running. If still Tier 2 after that single rerun, treat as Tier 3.

### Tier 3 — Edge too thin → Move on

Any of:
- Walk-forward annual return on margin: 5–10%, OR
- Walk-forward Sharpe ratio: 0–0.5, OR
- Monte Carlo P95 max drawdown: > 40%

**Decision:** Two marginal results across Nifty weekly (Tier 2) and Nifty monthly
(Tier 3) establishes that short strangles on Nifty at these parameters are not
commercially viable at standalone confidence. Document. No further options-selling
iteration on Nifty.

### Tier 4 — Failed → Hypothesis disproven

- Walk-forward annual return on margin: < 5% or negative, OR
- Walk-forward Sharpe ratio: < 0

**Decision:** Hypothesis disproven for monthly Nifty strangles. Document. No
iteration.

### OVERRIDE — Insufficient sample

- Trade count < 30 after VIX gate applied

**Decision:** Inconclusive, not failed. Permitted response: extend validation
window to 2021-01-01. If still < 30 qualifying trades, result is sample-size-
limited. Document and move on. Do NOT loosen VIX gate or change delta to increase
trade count.

---

## Override conditions (apply regardless of tier)

1. **Monte Carlo P95 max drawdown > 50%** — tail risk unacceptable
2. **Walk-forward consistency < 40%** — too regime-dependent
3. **Any single walk-forward window shows > 50% drawdown** — hidden regime sensitivity
4. **Trade count < 30** — insufficient statistical mass

---

## Sequencing rule

This test runs after Nifty weekly is decided (it is — Tier 2 accepted 2026-05-07).

If monthly validates at Tier 1: consider deploying as a combined weekly+monthly
book — the two expiry streams are partially decorrelated and improve portfolio-
level frequency.

If monthly is Tier 3 or 4: the Nifty options-selling strategy class is
exhausted at these parameters. Move to Path C (B2B infrastructure) or a new
hypothesis with new pre-committed criteria.

---

## Hard rules (non-negotiable)

1. No parameter optimization beyond what is specified above
2. No retest with looser VIX gate or different delta
3. No addition of adjustment rules (gamma scalp, roll-out) to improve results
4. Do not test FinNifty or MidcapNifty if this fails — different hypothesis,
   new pre-committed criteria required
5. If any result shows Sharpe > 2.5, treat as a bug first

---

## Postmortem template (to be completed after validation)

After validation completes, append here:

- Final tier verdict (mechanical, per criteria above)
- Trade count: total months, gates applied, trades executed
- Walk-forward results per window
- Whether any data quality issues were found
- Confirmation that no parameter adjustments were made post-hoc

---

## Signature

These criteria were committed by the operator (mkumaran2931@gmail.com) on
2026-05-07, before any Nifty monthly validation was run or any results were
observed.

Context: BankNifty weekly OVERRIDE (positive, discontinued). BankNifty monthly
OVERRIDE (10 trades, inconclusive). Pairs trading inconclusive. Nifty weekly
TIER 2 (marginal validation, accepted without iteration). Six prior tests,
all accepted without iteration. The same discipline applies here.
