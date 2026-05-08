# Nifty Weekly Strangle — Earnings/FII Gate Refinement Criteria

**Date set:** 2026-05-08
**Author:** M. Kumaran
**Committed before any refinement run:** Yes

---

## Hypothesis

Adding two additional gates to the Tier 2 validated Nifty weekly short strangle:
1. **Earnings blackout**: skip entry if any Nifty 50 constituent reports earnings
   within the trade window (entry to expiry)
2. **FII directional filter**: enter only when FII net flow for the prior 5 sessions
   matches the volatility regime (net outflow = skip, net inflow = proceed; or
   VIX regime takes precedence)

...will improve the strategy's Sharpe and reduce max drawdown without materially
reducing trade count below statistical significance.

This test answers: does market-event awareness rescue the marginal cases that
currently drag the Tier 2 result below Tier 1?

---

## Starting point — Tier 2 validated result (locked)

From `nifty_weekly_strangle_criteria.md` (2026-05-02):

| Metric | Value | Tier |
|---|---|---|
| Annualized return | ≈ 12–15% (walk-forward estimate) | Tier 2 |
| Walk-forward Sharpe | ≈ 0.7–0.9 | Tier 2 |
| Win rate | ≈ 73–78% | Tier 2 |
| Max drawdown (MC P95) | ≈ 12–16% | Tier 2 |
| Trade count | 36 qualifying (OVERRIDE: < 50 minimum) | Inconclusive on count |

The Tier 2 result had marginal positive edge. Trade count was below the 50-trade minimum,
so the result was OVERRIDE-inconclusive, not validated. The strangle was deployed live
with "TIER 2 — Marginal validated edge" disclaimer.

---

## What changes in this test

### Gate 1: Earnings blackout (strict)

**Rule:** If any Nifty 50 constituent has an earnings announcement date that falls
within [entry_date, expiry_date], skip that strangle entry entirely.

**Rationale:** Earnings events cause IV crush + gap risk that violates the short
strangle's volatility assumption. Historical data shows IV can spike 30–60% around
large-cap earnings even when Nifty 50 is range-bound.

**Data source:** `mcp_server/earnings_calendar.py` (existing) — NSE announcement dates.

**Implementation:** Filter applied BEFORE VIX gate (reject first, then regime-check).

### Gate 2: FII net flow directional filter

**Rule:** Compute rolling 5-session FII net F&O flow. If the rolling sum is negative
(net outflow > 0), skip the strangle entry for that week. Neutral or positive flow:
proceed (VIX gate still applies).

**Rationale:** Large sustained FII outflows coincide with directional trending conditions
that break the strangle's range-bound assumption. This replicates the "smart money
alignment" concept from Vibe-Trading's institutional flow module.

**Data source:** `mcp_server/fii_dii_filter.py` (to be implemented) — NSE FII F&O data.

**Implementation:** Applied AFTER earnings gate, BEFORE VIX gate.

---

## Test parameters (locked)

All strategy parameters are IDENTICAL to the original Tier 2 test:

| Parameter | Value |
|---|---|
| Underlying | Nifty 50 index |
| Expiry type | Weekly |
| Entry timing | ~5 DTE before weekly expiry |
| Strike selection | 15-delta both legs |
| VIX gate | 30th–80th percentile rolling 252-day |
| Profit target | 50% of initial credit |
| Stop loss | 2× initial credit |
| Time exit | Market close on expiry day |
| Lot size | 75 |
| Margin basis | ₹1,50,000 per strangle |
| Full Zerodha cost model | unchanged |
| Lookback | 2023-01-01 to 2026-04-30 |

**Only the entry gate logic changes.** No strategy parameter modifications permitted.

---

## Decision criteria

### Tier 1 — Gates improve the strategy → deploy to live strangle

| Metric | Threshold |
|---|---|
| Walk-forward Sharpe | ≥ 1.0 (vs ~0.8 baseline) |
| Annualized return | ≥ 12% (maintained or improved) |
| Win rate | ≥ 75% |
| Max drawdown (MC P95) | ≤ 12% (tighter than baseline ~14%) |
| Qualifying trades | ≥ 30 (minimum statistical floor) |

**Decision:** Replace unfiltered live strangle with earnings/FII-gated version.
Update `nifty_strangle_live.py` with both gates. Update live signal card disclaimer
from "TIER 2 — Marginal" to "TIER 1 — Validated edge, earnings/FII-gated".

### Tier 2 — Gates help but no clear improvement → keep original

| Metric | Threshold |
|---|---|
| Walk-forward Sharpe | 0.6–1.0 (similar to baseline) |
| Qualifying trades | ≥ 30 |

**Decision:** Gates add complexity without statistical benefit. Keep the original
Tier 2 strangle unmodified. Document earnings/FII data as unavailable or too noisy.

### Tier 3 — Gates harm the strategy

| Metric | Threshold |
|---|---|
| Walk-forward Sharpe | < 0.6 (degraded vs baseline) |
| OR qualifying trades | < 20 (gates too aggressive) |

**Decision:** Gates over-filter — remove too many good entries. Do not apply gates to
live strangle. Consider looser gate definitions in a new criteria doc.

---

## Override conditions

1. **Qualifying trades < 20** — gates too aggressive (over-filter), result inconclusive
2. **Earnings data coverage < 80%** of the test window — unreliable data; fix source then re-run
3. **FII data missing > 10 sessions** — interpolation risk; document and consider removing FII gate

---

## What this test does NOT answer

- Whether gates improve BankNifty (discontinued) or other indices
- Whether gates should apply to equity strangle/straddle strategies
- Monthly strangle refinement (separate criteria doc needed)
- Intraday strangle gates (different regime dynamics)

---

## Run commands

```bash
# POC — verify gates run on 2023 data
python scripts/validate_strangle_earnings_fii.py --poc

# Full walk-forward run
python scripts/validate_strangle_earnings_fii.py --workers 2

# Variant: earnings gate only (no FII)
python scripts/validate_strangle_earnings_fii.py --earnings-only

# Variant: FII gate only (no earnings)
python scripts/validate_strangle_earnings_fii.py --fii-only
```

---

## Signature

Criteria committed 2026-05-08 before any refinement run.

Context: Tier 2 weekly strangle deployed live with disclaimer. This test determines
if earnings blackout + FII flow gates push it to Tier 1 (fully validated, no disclaimer).
Strategy parameters are frozen — only gate logic changes.
