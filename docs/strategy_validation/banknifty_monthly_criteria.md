# BankNifty Monthly Short Strangle — Pre-Committed Decision Criteria

**Date committed:** 2026-04-29  
**Committed BEFORE any validation results are observed.**  
**Do not modify after the validation script is run.**

---

## Hypothesis

Monthly BankNifty short strangles, with the same VIX regime gate that proved
load-bearing in the weekly test (19.5pp delta between gated and ungated),
produce higher annual return than weekly because per-trade premium is 3–4×
larger while preserving the risk profile (80%+ win rate, <10% MC P95 DD).

The regime gate is not a parameter under test — it is carried over as-is from
the weekly validation where it was empirically demonstrated to be load-bearing.

---

## Why this test follows from the weekly result

The weekly validation (Jan 2023 – Nov 2024, 36 qualifying trades) showed:
- VIX gate ON: WF return 13.9%, Sharpe 1.15, MC P95 DD 7.5%, win rate 80.6%
- VIX gate OFF: WF return -5.6%, Sharpe -0.32

All Tier 1 risk thresholds passed with the gate. The single constraint was
return magnitude (13.9% vs 25% threshold), which is structurally explained by
small weekly premium (~₹3,000 credit × 12 qualifying trades/year).

Monthly directly addresses this constraint: same instrument, same VIX gate,
~3–4× premium per trade, currently active market (weekly BankNifty discontinued
November 2024). This is hypothesis-driven iteration on the binding constraint,
not parameter fishing.

---

## Decision criteria

Primary metric: **walk-forward annual return on margin** (not in-sample).

### Tier 1 — Strong validation → Plan deployment

| Metric | Threshold |
|---|---|
| Walk-forward annual return on margin | > 18% |
| Walk-forward Sharpe ratio | > 0.9 |
| Monte Carlo P95 max drawdown | < 30% |
| Walk-forward consistency (profitable windows) | ≥ 60% |
| Win rate | ≥ 65% |
| Trade count | ≥ 30 |

**Decision:** Paper trade for 30 calendar days. If paper P&L tracks within
±2 SD of backtest expectation on closed trades, move to 1-lot live.

Tier 1 threshold is set lower than weekly (25%) because monthly is the
ceiling of the same strategy family — setting bar higher than structurally
achievable would be an unfair test.

### Tier 2 — Marginal validation → ONE iteration only

| Metric | Threshold |
|---|---|
| Walk-forward annual return on margin | 10–18% |
| Walk-forward Sharpe ratio | 0.5–0.9 |
| Monte Carlo P95 max drawdown | < 40% |
| Walk-forward consistency | ≥ 50% |
| Trade count | ≥ 30 |

**Decision:** ONE iteration permitted on the **adjustment rules only**, not on
entry parameters (delta, VIX gate) or exit parameters (profit target, stop mult).
Write the specific adjustment rule change AND the structural reason for it BEFORE
running the iteration. No scanning.

### Tier 3 — Unconvincing → Move on

Any of:
- Walk-forward annual return on margin: 5–10%
- Walk-forward Sharpe ratio: 0–0.5
- Monte Carlo P95 max drawdown: > 40%

**Decision:** Two failed options-selling tests is a signal, not noise. Move to
Path B (pairs trading) or Path C (B2B infrastructure). No third options-selling
test.

### Tier 4 — Failed → Hypothesis disproven

- Walk-forward annual return on margin: < 5% or negative
- Walk-forward Sharpe ratio: < 0

**Decision:** Monthly BankNifty short strangle has no positive expectancy after
realistic costs. Document. Move to Path B or C. No iteration.

---

## Override conditions (apply regardless of tier)

1. **Monte Carlo P95 max drawdown > 50%** — unacceptable tail risk
2. **Walk-forward consistency < 40%** — too regime-dependent
3. **Trade count < 30** — insufficient statistical mass for monthly frequency
4. **Any single WF window shows > 50% drawdown** — hidden regime sensitivity
5. **Data quality issues found post-run** — gaps in chain data during key periods

---

## Fixed parameters (do not change for this test)

| Parameter | Value | Source |
|---|---|---|
| Target delta | 0.15 per leg | Same as weekly |
| VIX gate | 30th–80th percentile | Carried over from weekly test |
| Profit target | 50% of initial credit | Same as weekly |
| Stop loss | 2× initial credit | Same as weekly |
| Time exit | 5 DTE before expiry | Monthly-adjusted (weekly used expiry day) |
| Lot size | 15 (BankNifty) | Same as weekly |
| Margin basis | ₹1,50,000 per strangle | Same as weekly |

---

## Operational constraints

- Do not test Nifty monthly until BankNifty monthly is decided (one test at a time)
- Do not adjust delta target (15-delta both legs)
- Do not modify the VIX gate percentile thresholds
- Do not adjust adjustment_engine.py rules for this test
- Run with `--expiry-type monthly` flag on the existing validation script

---

## If the test produces < 30 qualifying trades (sample size override)

The override condition states "insufficient statistical mass for any decision."
Permitted response: extend the backfill window to 2021–2026 (adds ~24 monthly
expiries, expect ~12 more qualifying trades at 50% gate pass rate). This is a
data extension, not a parameter change. Re-run with extended data.

If the extended run STILL produces < 30 qualifying trades, the instrument is
too infrequently traded in the qualifying regime to produce a statistically
valid result at monthly frequency. In that case: Pivot to Path B or C without
further options-selling tests.

---

## Signature

These criteria were set by the operator (mkumaran2931@gmail.com) on 2026-04-29,
before any monthly validation results were observed. The weekly validation results
(WF return 13.9%, Sharpe 1.15, OVERRIDE-by-sample-size) are known and influenced
only the structural hypothesis, not the tier thresholds.

See `docs/strategy_validation/banknifty_strangle_criteria.md` for the weekly
pre-committed criteria document (same discipline applied there).
