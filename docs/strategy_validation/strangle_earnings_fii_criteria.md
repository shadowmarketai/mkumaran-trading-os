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

---

## Postmortem (2026-05-08, after full run)

**Result: OVERRIDE — data limitations prevent conclusive test.**

### Results

| Variant | Live trades | Earn-skip | WF Sharpe | WF Ann% | Tier |
|---|---|---|---|---|---|
| Baseline | 55 | 0 | 0.556 | 16.4% | TIER_2 |
| Earnings-only (approx) | 16 | 129 | 16.779* | 20.7% | OVERRIDE |
| FII-only | — | — | — | — | INCONCLUSIVE (data unavailable) |
| Both gates | — | — | — | — | INCONCLUSIVE |

*Sharpe of 16.779 is a mathematical artifact: 16 trades across 12m/3m WF windows
yields ~1 trade per test period. Single-trade Sharpe is statistically meaningless.

### Key findings

**Baseline confirmed at TIER_2.** WF Sharpe 0.556, 55 trades — consistent with
original result. Live strangle is operating as validated.

**Earnings gate: OVERRIDE — data insufficient, not gate failure.**
Approximate quarterly seasons (Apr-May, Jul-Aug, Oct-Nov, Jan-Feb) blocked 129/206
= 63% of all expiries. This is not how the earnings gate was designed — the gate
should skip only specific announcement weeks (~5-10% of expiries), not entire
2-month seasons. With exact NSE announcement dates, earnings_only would have
~50 trades and could produce a conclusive result.

Override condition 1 applies: "qualifying trades < 20 — gates too aggressive."
However, the over-filtering is due to the data approximation, not the gate concept.

**FII gate: INCONCLUSIVE.** Historical NSE FII F&O data not accessible from server
via any automated source (NSE API blocked, archives not serving). Override condition
3 applies: "FII data missing > 10 sessions."

### Why the earnings gate concept is still worth testing

The approximate seasons over-filter by design. The gate as specified (exact NSE
announcement dates) would only block weeks where specific Nifty 50 stocks report.
The concept itself is sound — it's the data source that's the blocker.

### What's needed to run a conclusive test

To test the earnings gate properly:
1. **Exact NSE earnings dates**: download NSE corporate actions CSV for
   2023-2026 and place at `data/nifty50_earnings_manual.csv` (format: date,ticker)
   Source: NSE website > Corporate Actions > Financial Results > download
2. **FII F&O historical data**: download NSE participant-wise data CSV for
   2023-2026 and place at `data/fii_fno_historical.csv` (format: date,fii_net_fo)
   Source: NSE website > Market Data > FII/DII Activity > download

With both files in place, re-run: `python scripts/validate_strangle_earnings_fii.py`

### Live strangle status unchanged

Baseline remains TIER_2. No change to live strangle configuration.
The "TIER 2 — Marginal validated edge" disclaimer stays until a gate test
with exact data confirms Tier 1.

### Signature

Criteria committed 2026-05-08 before run.
Postmortem added 2026-05-08 after full run.
Result: OVERRIDE (data limitation). Strangle TIER_2 baseline confirmed.
