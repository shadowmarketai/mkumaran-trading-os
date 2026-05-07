# Nifty Weekly Short Strangle — Pre-Committed Decision Criteria

**Date set:** 2026-05-02
**Author:** M. Kumaran
**Committed before any data observed:** Yes

---

## Hypothesis

Short strangles on Nifty weekly options, entered ~5 DTE with VIX regime filter,
held with adjustment-engine management, will produce positive risk-adjusted
returns after costs over a 3+ year window (2023-01-01 to 2026-04-30).

---

## Why this test follows from BankNifty

BankNifty weekly (Jan 2023 – Nov 2024, 36 qualifying trades):
- VIX gate ON: WF return 13.9%, Sharpe 1.15, MC P95 DD 7.5%, win rate 80.6% — OVERRIDE on trade count (< 50)
- VIX gate OFF: WF return -5.6% — gate confirmed load-bearing (19.5pp delta)
- BankNifty weekly discontinued November 2024

Nifty weekly is the only surviving weekly index derivative in India after SEBI's
expiry rationalization. Same strategy family, same regime gate, different underlying.
The gate is carried over unchanged — it was empirically load-bearing in BankNifty.

---

## Strategy parameters (locked, no iteration permitted)

| Parameter | Value |
|---|---|
| Underlying | Nifty 50 index |
| Expiry type | Weekly |
| Entry timing | ~5 DTE before weekly expiry (see calendar note below) |
| Strike selection | 15-delta both legs (nearest CE and PE) |
| VIX gate | 30th–80th percentile of trailing 252-day VIX window |
| Profit target | 50% of initial combined credit |
| Stop loss | 2× initial combined credit |
| Time exit | Market close on expiry day |
| Adjustment engine | Existing module, no rule changes for this test |
| Lot size | 75 (current NSE mandate) |
| Margin basis | ₹1,50,000 per strangle (fixed denominator for return calculation) |
| Brokerage | ₹20 flat per order × 4 orders per trade |
| STT | 0.05% on sell-side (options exercise) |
| Exchange charges | 0.053% per side |
| GST | 18% on brokerage + exchange charges |
| Stamp duty | 0.003% on buy-side |
| Slippage | 0.05% for Nifty 50 ATM strikes; 0.10% for OTM |

### Calendar note — expiry day transition

Per NSE circular, effective September 1, 2025:

| Period | Expiry day | Entry day | DTE at entry |
|---|---|---|---|
| 2023-01-01 to 2025-08-31 | Thursday | Friday prior week | ~5 DTE |
| 2025-09-01 to 2026-04-30 | Tuesday | Wednesday prior week | ~5–6 DTE |

The transition is an implementation detail in the validation script, not a change
to the strategy hypothesis. The hypothesis is the same on both sides: enter ~5 DTE,
exit at expiry close or at profit/stop trigger.

---

## Decision criteria

### Tier 1 — Strong validation → Paper trade

| Metric | Threshold |
|---|---|
| Walk-forward annual return on margin | > 20% |
| Walk-forward Sharpe ratio | > 1.0 |
| Monte Carlo P95 max drawdown | < 35% |
| Walk-forward consistency (profitable windows) | ≥ 60% |
| Win rate | ≥ 60% |
| Trade count over validation window | ≥ 50 |

**Decision:** Paper trade 30 calendar days, 1 lot. If closed-trade P&L tracks within
±2 SD of backtest expectation, move to 1-lot live with defined weekly risk cap.

Tier 1 threshold is 20% (not 25% as in BankNifty weekly) because Nifty carries
structurally lower IV than BankNifty did. Same risk-adjusted edge produces lower
absolute returns on a lower-IV instrument.

### Tier 2 — Marginal → One iteration only

| Metric | Threshold |
|---|---|
| Walk-forward annual return on margin | 12–20% |
| Walk-forward Sharpe ratio | 0.5–1.0 |
| Monte Carlo P95 max drawdown | < 50% |
| Walk-forward consistency | ≥ 50% |
| Trade count | ≥ 50 |

**Decision:** ONE iteration permitted on **adjustment rules only** (not on entry delta,
not on VIX gate, not on DTE). State the structural reason for the change in writing
before running the iteration. If still Tier 2 after that single rerun, treat as Tier 3.

### Tier 3 — Edge too thin → Move to monthly Nifty test

Any of:
- Walk-forward annual return on margin: 5–12%, OR
- Walk-forward Sharpe ratio: 0–0.5, OR
- Monte Carlo P95 max drawdown: > 50%

**Decision:** Document findings. Run monthly Nifty criteria test. No weekly iteration.

### Tier 4 — Failed → Hypothesis disproven for weekly variant

- Walk-forward annual return on margin: < 5% or negative, OR
- Walk-forward Sharpe ratio: < 0

**Decision:** Weekly Nifty short strangle has no positive expectancy after realistic
costs. Document. Run monthly Nifty criteria test. No iteration.

### OVERRIDE — Insufficient sample

- Trade count < 50 after VIX gate applied

**Decision:** Inconclusive, not failed. Permitted response: extend validation window
to 2021-01-01 to capture more data. If extended run still < 50 trades, result is
sample-size-limited. Document and move to monthly Nifty test. Do NOT loosen VIX gate
or change delta in order to increase trade count.

---

## Override conditions (apply regardless of tier)

These override even a Tier 1 verdict downward to "do not deploy":

1. **Monte Carlo P95 max drawdown > 60%** — tail risk unacceptable
2. **Walk-forward consistency < 40%** — too regime-dependent
3. **Any single walk-forward window shows > 50% drawdown** — hidden regime sensitivity
4. **Total trade count < 50** — insufficient statistical mass
5. **Data quality issues discovered post-run** — gaps in chain data during key events

---

## Hard rules (non-negotiable)

1. No parameter optimization beyond what is specified above
2. No retest with looser VIX gate or different delta target if trade count is low
3. The Thursday→Tuesday expiry transition is a calendar implementation detail — it
   does not change the strategy and is not a variable under test
4. Walk-forward must use only past-period IV percentile data at each window (no leakage)
5. If any result shows Sharpe > 2.5, treat as a bug first — investigate for look-ahead
   bias before recording as a result
6. Do not test FinNifty, MidcapNifty, or BankNifty as fallbacks if this fails —
   those are different hypotheses requiring new pre-committed criteria

---

## Postmortem template (to be completed after validation)

After validation completes, append here:

- Final tier verdict (mechanical, per criteria above)
- Trade count: total weeks evaluated, gates applied, trades executed
- Walk-forward results per window
- Whether any data quality issues were found
- Confirmation that no parameter adjustments were made post-hoc

---

## Future revisits (explicitly not part of this test)

If this test produces OVERRIDE, Tier 3, or Tier 4, the following are possible
future research questions — each requires a NEW pre-committed criteria doc:

- Different DTE windows (3 DTE, 7 DTE, 10 DTE)
- Different delta targets (10-delta, 20-delta)
- Iron condor variant (defined maximum loss per leg)
- Directional bias filter (ATM skew as entry signal)
- Different IV percentile bands

None of these are permitted within this test.

---

## Signature

These criteria were committed by the operator (mkumaran2931@gmail.com) on 2026-05-02,
before any Nifty weekly validation was run or any results were observed.

Context: BankNifty weekly OVERRIDE (13.9% WF return, Sharpe 1.15, 36 trades — positive
but below 50-trade threshold). BankNifty monthly OVERRIDE (10 trades, inconclusive).
Pairs trading inconclusive. Five prior tests, all accepted without iteration.
The same discipline applies here.

---

## Postmortem (2026-05-07, after first validation run)

**Result:** TIER 2 — Marginal validation.

**Key metrics (net P&L, after all costs):**

| Metric | Value | Tier 1 threshold | Tier 2 threshold |
|---|---|---|---|
| Trade count | 55 | ≥ 50 ✓ | ≥ 50 ✓ |
| Win rate (net) | 78.2% | ≥ 60% ✓ | — |
| WF return (OOS) | 16.4% | > 20% | 12–20% ✓ |
| WF Sharpe (chronological OOS) | 0.556 | > 1.0 | 0.5–1.0 ✓ |
| WF consistency | 75% (3/4 windows) | ≥ 60% ✓ | ≥ 50% ✓ |
| MC P95 max drawdown | 28.7% | < 35% ✓ | < 50% ✓ |
| Aggregate annual return | 8.9% | — | — |
| Max drawdown (aggregate) | 13.6% | — | — |

**Exit breakdown:**
- 42/55 (76%) profit exits — exit logic working correctly
- 4/55 (7%) stop-outs — stops are rare, not the binding constraint
- 8/55 (15%) adjustment exits — conservative full-close on delta breach
- 1/55 (2%) time exits

**Decision: Tier 2 accepted. No iteration invoked.**

The criteria permit ONE iteration on exit parameters with a stated structural
hypothesis. Iteration was evaluated and declined because:

1. 76% profit exits confirms the profit target is functioning correctly
2. 7% stop rate confirms stops are not killing returns — no structural case for
   a wider stop
3. The binding constraint is VIX gate selectivity (120/206 = 58% of weeks
   filtered) → small OOS window count (4 windows, 55 trades), not exit parameters
4. Iterating on exit parameters with no structural hypothesis would constitute
   parameter fishing. The criteria explicitly require a structural hypothesis
   before iteration. None exists here.

**Conclusion:** Strategy has marginal validated edge. Not Tier 1 deployable as a
standalone strategy. Parked as a candidate (see docs/strategy_candidates.md).

**Action:** Move to Phase 2 — Nifty monthly short strangle test.
No further Nifty weekly iteration permitted.
