# BankNifty Short Strangle — Pre-Committed Decision Criteria

**Date committed:** 2026-04-29  
**Committed BEFORE any validation results are observed.**  
**Do not modify after the validation script is run.**

---

## Why pre-committing matters

Post-hoc rationalization is the most common path to overfitting. Without pre-committed criteria:
- "PF 1.1 is close enough — let me adjust the stop-loss multiplier"
- "Sharpe 0.4 is fine — options strategies have low Sharpe by design"
- "Max DD 45% is acceptable if we position-size correctly"

These statements feel reasonable in the moment and lead to deploying strategies that lose money. The criteria below are set in advance based on what a viable retail options strategy should look like, not on what the backtest happened to produce.

---

## Decision criteria

The primary metric is **walk-forward annual return on margin** — not in-sample. Walk-forward is the 12-month rolling train / 3-month test result averaged across all windows.

Secondary confirmation metrics must all pass for Tier 1 or Tier 2 verdicts.

### Tier 1 — Strong validation → Plan deployment

| Metric | Threshold |
|---|---|
| Walk-forward annual return on margin | > 25% |
| Walk-forward Sharpe ratio | > 1.0 |
| Monte Carlo P95 max drawdown | < 35% |
| Walk-forward consistency (profitable windows) | ≥ 60% |
| Win rate | ≥ 60% |

**Decision:** Paper trade for 30 calendar days with 1 lot. If paper trade confirms (>= 50% of credit collected on closed trades), move to 1-lot live with defined risk per week.

### Tier 2 — Marginal validation → One iteration only

| Metric | Threshold |
|---|---|
| Walk-forward annual return on margin | 15–25% |
| Walk-forward Sharpe ratio | 0.5–1.0 |
| Monte Carlo P95 max drawdown | < 50% |
| Walk-forward consistency | ≥ 50% |

**Decision:** Identify the single weakest link (most likely: stop-loss multiplier OR entry delta). Change ONE parameter. Re-run validation once. If Tier 1 after that iteration, proceed. If not, move to Tier 3 verdict.

No other iteration permitted. The "one iteration" gate exists because one systematic change to a specific parameter is distinguishable from parameter fishing. Two iterations is not.

### Tier 3 — Edge exists but margin too thin → Move on

| Metric | Threshold |
|---|---|
| Walk-forward annual return on margin | 5–15% |
| Walk-forward Sharpe ratio | 0–0.5 |

**Decision:** The strategy has detectable edge but is not worth the operational complexity of managing weekly option positions (margin, rolls, risk monitoring). Document findings. Move to next strategic decision.

Explicitly: **do not iterate** on a Tier 3 result. The edge is too thin to survive overfitting risk from further parameter tuning.

### Tier 4 — Failed → Hypothesis disproven

| Metric | Threshold |
|---|---|
| Walk-forward annual return on margin | < 5% or negative |
| Walk-forward Sharpe ratio | < 0 |

**Decision:** Hypothesis disproven. The short strangle on BankNifty weekly does not produce positive expectancy in the tested period after realistic costs.

**Do not iterate. Do not adjust parameters.** Document as a clean failure. Update TRADING.md to note this hypothesis was tested and rejected.

Next steps after Tier 4 result:
1. Review the positions-seller module itself — it's well-built for paper trading but the underlying hypothesis needs revision
2. Consider: longer DTE (monthly), different delta target, or different underlying

---

## Additional conditions that override all tiers

These override even a Tier 1 result downward to "do not deploy":

1. **Monte Carlo P95 max drawdown > 60%** — account wipeout risk is unacceptable regardless of return
2. **Walk-forward consistency < 40%** — too many losing periods even if mean return is positive
3. **Any single walk-forward window shows > 50% drawdown** — suggests regime sensitivity the aggregate hides
4. **Total trade count < 50 over the validation period** — insufficient statistical mass for any decision
5. **Significant data quality issues identified post-run** — e.g., discovered gaps > 1 day in chain data during peak volatility periods (earnings/RBI events)

---

## Reference: what professional outcomes look like

For context when reading results:

- **Good retail options strategy:** Sharpe 0.8–1.5, annual return 20–40% on margin, max DD 25–35%
- **Institutional options desk:** Sharpe 1.5+, tighter DD, but with much better execution and faster adjustment
- **Typical naive strangle (no management):** Win rate ~75% but negative expectancy due to rare large losses

Anything in the "good retail" range warrants deployment. Anything above institutional range on a backtest is suspicious (overfitting).

---

## Signature

These criteria were set by the operator (mkumaran2931@gmail.com) on 2026-04-29, before the validation script was run or any results were observed.

The validation window, methodology, and cost model are specified in `docs/strategy_validation/banknifty_strangle_test_plan.md`.
